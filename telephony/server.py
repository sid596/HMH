"""Single-worker demo API: protected call controls plus signed Twilio callbacks."""
import asyncio
import hmac
import os
import time
from pathlib import Path
from fastapi import FastAPI, Request, HTTPException, BackgroundTasks
from fastapi.responses import Response
from twilio.request_validator import RequestValidator
from engine.settings import load_local_settings
from telephony.service import CallService, REQUIRED, validate_config, provider_error

load_local_settings()
app=FastAPI(title="HMH phone verification",docs_url=None,redoc_url=None)
service=CallService(Path(__file__).resolve().parents[1]/"data/phone")


def admin(request):
    expected=os.getenv("HMH_CALL_API_TOKEN","")
    supplied=request.headers.get("Authorization","").removeprefix("Bearer ")
    if len(expected)<32 or not hmac.compare_digest(expected,supplied):
        raise HTTPException(401,"Call-control authentication required")


def record_for(call_id):
    if call_id not in service.calls:
        raise HTTPException(404,"Call not found")
    return service.calls[call_id]


async def signed_form(request,record):
    form=await request.form()
    token=os.getenv("TWILIO_AUTH_TOKEN","")
    base=os.getenv("HMH_PUBLIC_BASE_URL","").rstrip("/")
    # Validate the configured public URL rather than trusting proxy Host headers.
    url=base+request.url.path+("?"+request.url.query if request.url.query else "")
    if not token or not RequestValidator(token).validate(url,form,request.headers.get("X-Twilio-Signature","")):
        raise HTTPException(403,"Invalid Twilio signature")
    if form.get("AccountSid")!=os.getenv("TWILIO_ACCOUNT_SID"):
        raise HTTPException(403,"Account mismatch")
    sid=form.get("CallSid")
    if not sid or (record.sid and sid!=record.sid):
        raise HTTPException(403,"Call mismatch")
    record.sid=sid
    return form


def xml(record,waiting=False):
    return Response(service.twiml(record,waiting),media_type="application/xml")


@app.get('/health')
def health(request:Request):
    admin(request)
    missing=[key for key in REQUIRED if not os.getenv(key)]
    issue=None
    account_type=None
    if not missing:
        try:
            validate_config()
            account_type=service.check_account()
        except ValueError as exc:issue=str(exc)
        except Exception as exc:issue=provider_error(exc)
    return {"ready":not missing and issue is None,"missing":missing,"configuration_issue":issue,
            "max_topics":3 if account_type=="Trial" else 15}


@app.post('/calls')
async def create_call(request:Request,tasks:BackgroundTasks):
    admin(request)
    if int(request.headers.get("content-length","0"))>2*1024*1024:
        raise HTTPException(413,"Pack too large")
    body=await request.json()
    try:
        record,created=service.create(body.get("pack"),body.get("request_id",""))
    except ValueError as exc:
        raise HTTPException(400,str(exc))
    if created:tasks.add_task(service.prepare_and_dial,record)
    return service.summary(record)


@app.get('/calls/{call_id}')
def get_call(call_id:str,request:Request):
    admin(request)
    return service.summary(record_for(call_id))


@app.post('/calls/{call_id}/cancel')
async def cancel_call(call_id:str,request:Request):
    admin(request)
    record=record_for(call_id)
    record.phase="cancelled"
    record.conversation.session.audit.append("phone_call_cancelled")
    if record.sid:
        try:await asyncio.to_thread(service.client().calls(record.sid).update,status="completed")
        except Exception:raise HTTPException(502,"Could not confirm hangup. Check Twilio console.")
    return service.summary(record)


@app.post('/twilio/answer/{call_id}')
async def answer(call_id:str,request:Request):
    record=record_for(call_id)
    await signed_form(request,record)
    if record.phase not in {"cancelled","failed","completed"}:record.phase="ready"
    return xml(record)


@app.post('/twilio/gathered/{call_id}/{turn}')
async def gathered(call_id:str,turn:str,request:Request,tasks:BackgroundTasks):
    record=record_for(call_id)
    form=await signed_form(request,record)
    if record.stt_mode!="gather":raise HTTPException(400,"Wrong speech mode")
    if turn==record.conversation.turn and turn not in record.submitted_turns and record.phase not in {"cancelled","failed","completed"}:
        record.phase="processing"
        record.processing_since=record.processing_since or time.time()
        tasks.add_task(service.gathered,record,turn,str(form.get("SpeechResult","")),form.get("Confidence"))
    return xml(record,waiting=record.phase=="processing")


@app.post('/twilio/recorded/{call_id}/{turn}')
async def recorded(call_id:str,turn:str,request:Request,tasks:BackgroundTasks):
    record=record_for(call_id)
    form=await signed_form(request,record)
    if form.get("Digits")=="hangup":
        record.phase="completed"
        return xml(record)
    if turn==record.conversation.turn and record.phase not in {"cancelled","failed","completed"}:
        # Availability callback, not action callback, triggers transcription.
        record.pending_turn=turn
        record.processing_since=record.processing_since or time.time()
        record.phase="processing"
        if not form.get("RecordingSid"):
            tasks.add_task(service.escalate,record,"No answer recording received")
    return xml(record,waiting=record.pending_turn is not None)


@app.post('/twilio/ready/{call_id}/{turn}')
async def ready(call_id:str,turn:str,request:Request,tasks:BackgroundTasks):
    record=record_for(call_id)
    form=await signed_form(request,record)
    if form.get("RecordingStatus")=="completed":
        tasks.add_task(service.recording_ready,record,turn,form.get("RecordingSid",""))
    elif turn==record.conversation.turn:
        tasks.add_task(service.escalate,record,"Answer recording unavailable")
    return Response(status_code=204)


@app.post('/twilio/next/{call_id}')
async def next_turn(call_id:str,request:Request,tasks:BackgroundTasks):
    record=record_for(call_id)
    await signed_form(request,record)
    if record.processing_since and time.time()-record.processing_since>180:
        tasks.add_task(service.escalate,record,"Answer processing timed out")
    return xml(record,waiting=record.phase=="processing")


@app.post('/twilio/status/{call_id}')
async def status(call_id:str,request:Request):
    record=record_for(call_id)
    form=await signed_form(request,record)
    state=form.get("CallStatus")
    record.conversation.session.audit.append("phone_status",status=state)
    if state in {"completed","busy","failed","no-answer","canceled"}:
        record.phase="completed" if state=="completed" else "failed"
        if record.conversation.session.status=="active":
            record.conversation.session.status="human_review"
            record.conversation.session.audit.append("session_finished",status="human_review",reason="Call ended before verification completed")
    return Response(status_code=204)


@app.get('/media/{call_id}/{token}/{key}')
def media(call_id:str,token:str,key:str):
    record=record_for(call_id)
    if time.time()-record.created>1800 or not hmac.compare_digest(record.media_token,token) or key not in record.audio:
        raise HTTPException(404,"Audio unavailable")
    return Response(record.audio[key],media_type="audio/wav",headers={"Cache-Control":"private, max-age=60"})
