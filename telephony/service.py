"""Twilio turn-based phone verification. Gather phone transcription or optional paid Prisma recording mode."""
import asyncio
from dataclasses import dataclass, field
import hmac
import os
import re
import secrets
import time
from urllib.parse import quote, urlsplit
from xml.etree.ElementTree import Element, SubElement, tostring
import httpx
from engine.conversation import Conversation
from engine.localization import PROFILES
from engine.scorer import score
from voice.gnani import synthesize, transcribe

REQUIRED=("TWILIO_ACCOUNT_SID","TWILIO_AUTH_TOKEN","TWILIO_FROM_NUMBER","TWILIO_TO_NUMBER",
          "HMH_PUBLIC_BASE_URL","HMH_CALL_API_TOKEN","GNANI_API_KEY","SCORER_API_KEY","SCORER_MODEL")
WAITING={"en-IN":"Thank you. Please wait while I check your explanation.",
         "hi-IN":"धन्यवाद। आपके जवाब की जाँच हो रही है। कृपया थोड़ी देर रुकिए।",
         "hi-en":"Thank you. Aapke jawab ko check kar rahe hain. Please thoda wait karein.",
         "mr-IN":"धन्यवाद. तुमच्या उत्तराची तपासणी सुरू आहे. कृपया थोडे थांबा.",
         "kn-IN":"ಧನ್ಯವಾದಗಳು. ನಿಮ್ಮ ಉತ್ತರವನ್ನು ಪರಿಶೀಲಿಸುತ್ತಿದ್ದೇವೆ. ದಯವಿಟ್ಟು ಸ್ವಲ್ಪ ಕಾಯಿರಿ."}
RECORDING_NOTICE={"en-IN":"This synthetic test call records your answers for automated teach-back verification. After each question, answer after the beep. Stop speaking or press the hash key when finished.",
 "hi-IN":"इस काल्पनिक परीक्षण कॉल में आपके जवाब रिकॉर्ड किए जाते हैं। हर सवाल के बाद बीप सुनकर जवाब दीजिए। जवाब पूरा हो तो बोलना रोकिए या हैश का बटन दबाइए।",
 "hi-en":"Yeh synthetic test call aapke answers record karti hai. Har question ke baad beep sunkar answer dein. Finish hone par bolna rokein ya hash button dabayein.",
 "mr-IN":"या काल्पनिक चाचणी कॉलमध्ये तुमची उत्तरे ध्वनिमुद्रित केली जातात. प्रत्येक प्रश्नानंतर बीप ऐकून उत्तर द्या. उत्तर संपल्यावर बोलणे थांबवा किंवा हॅश बटण दाबा.",
 "kn-IN":"ಈ ಕಾಲ್ಪನಿಕ ಪರೀಕ್ಷಾ ಕರೆಯಲ್ಲಿ ನಿಮ್ಮ ಉತ್ತರಗಳನ್ನು ಧ್ವನಿಮುದ್ರಿಸಲಾಗುತ್ತದೆ. ಪ್ರತಿ ಪ್ರಶ್ನೆಯ ನಂತರ ಬೀಪ್ ಕೇಳಿದ ಮೇಲೆ ಉತ್ತರಿಸಿ. ಮುಗಿದಾಗ ಮಾತನಾಡುವುದನ್ನು ನಿಲ್ಲಿಸಿ ಅಥವಾ ಹ್ಯಾಶ್ ಬಟನ್ ಒತ್ತಿರಿ."}

GATHER_NOTICE={
 "en-IN":"Please answer in your own words.",
 "hi-IN":"कृपया अपने शब्दों में जवाब दें।",
 "hi-en":"Please apne words mein answer dein.",
 "mr-IN":"कृपया तुमच्या शब्दांत उत्तर द्या.",
 "kn-IN":"ದಯವಿಟ್ಟು ನಿಮ್ಮದೇ ಮಾತುಗಳಲ್ಲಿ ಉತ್ತರಿಸಿ."
}
PHONE_MESSAGES={
 "en-IN":{"complete":"Thank you. Verification is complete. Goodbye.","human_review":"A team member needs to review this with you. Goodbye."},
 "hi-IN":{"complete":"धन्यवाद। सत्यापन पूरा हुआ। नमस्ते।","human_review":"एक कर्मचारी को आपके साथ इसकी समीक्षा करनी होगी। नमस्ते।"},
 "hi-en":{"complete":"Thank you. Verification complete hai. Goodbye.","human_review":"Ek team member aapke saath review karega. Goodbye."},
 "mr-IN":{"complete":"धन्यवाद. पडताळणी पूर्ण झाली. नमस्कार.","human_review":"एका कर्मचाऱ्याने तुमच्यासोबत याचे पुनरावलोकन करणे आवश्यक आहे. नमस्कार."},
 "kn-IN":{"complete":"ಧನ್ಯವಾದಗಳು. ಪರಿಶೀಲನೆ ಪೂರ್ಣಗೊಂಡಿದೆ. ನಮಸ್ಕಾರ.","human_review":"ತಂಡದ ಸದಸ್ಯರು ನಿಮ್ಮೊಂದಿಗೆ ಇದನ್ನು ಪರಿಶೀಲಿಸಬೇಕಾಗಿದೆ. ನಮಸ್ಕಾರ."}
}

def speech_mode():
    mode=os.getenv("PHONE_STT_MODE","gather")
    if mode not in {"gather","prisma_record"}:
        raise ValueError("PHONE_STT_MODE must be gather or prisma_record")
    return mode


def validate_config():
    missing=[k for k in REQUIRED if not os.getenv(k)]
    if missing:
        raise ValueError("Missing backend settings: "+", ".join(missing))
    for key in ("TWILIO_FROM_NUMBER","TWILIO_TO_NUMBER"):
        if not re.fullmatch(r"\+[1-9]\d{7,14}",os.environ[key]):
            raise ValueError(key+" must be an international E.164 number")
    parsed=urlsplit(os.environ["HMH_PUBLIC_BASE_URL"])
    if parsed.scheme!="https" or not parsed.netloc or parsed.query or parsed.fragment or parsed.path not in ("","/"):
        raise ValueError("HMH_PUBLIC_BASE_URL must be the public HTTPS origin of the call backend")
    if len(os.environ["HMH_CALL_API_TOKEN"])<32:
        raise ValueError("HMH_CALL_API_TOKEN must contain at least 32 characters")


def validate_pack(pack):
    if not isinstance(pack,dict) or pack.get("synthetic") is not True or pack.get("language") not in PROFILES:
        raise ValueError("Use a synthetic pack in a supported language")
    clauses=pack.get("clauses")
    if not isinstance(clauses,list) or not 1<=len(clauses)<=15:
        raise ValueError("The phone pack needs 1–15 questions")
    if not pack.get("review_record",{}).get("reviewer"):
        raise ValueError("Save a reviewed demo pack before calling")
    if len({c.get("id") for c in clauses})!=len(clauses):
        raise ValueError("Clause IDs must be unique")
    for c in clauses:
        for key in ("id","explain","question","fallback_explain"):
            if not isinstance(c.get(key),str) or not c[key] or len(c[key])>6000:
                raise ValueError("Incomplete or excessive clause text")
        if not isinstance(c.get("must_have_facts"),list) or not c["must_have_facts"]:
            raise ValueError("Every clause needs required facts")
        if type(c.get("critical")) is not bool:
            raise ValueError("Every clause needs a critical flag")
    if not isinstance(pack.get("messages"),dict) or not all(pack["messages"].get(k) for k in ("understood","partial","misunderstood","no_evidence","human_review","complete")):
        raise ValueError("The pack needs complete localized conversation messages")
    if not isinstance(pack.get("pack_version"),str):
        raise ValueError("Missing pack version")
    if not isinstance(pack.get("disclosure"),str) or len(pack["disclosure"])>6000 or not isinstance(pack.get("approval"),dict):
        raise ValueError("Missing disclosure or pack metadata")


def provider_error(exc):
    code=getattr(exc,"code",None)
    actions={20003:"Twilio rejected the account credentials.",21211:"Twilio rejected the destination number.",
             21210:"Twilio rejected the caller number. Use a number this account may call from.",
             21608:"The trial destination must be verified in Twilio.",21215:"Check Twilio geographic calling permissions for the destination.",
             21214:"This destination is not permitted for this account."}
    if code in (0,"0",None) and getattr(exc,"status",None):
        # Some trial gateways return code=0. Keep the HTTP status and a
        # redacted explanation instead of inventing a documentation error code.
        message=str(getattr(exc,"msg",None) or getattr(exc,"detail",None) or "No provider explanation supplied")
        for key in ("TWILIO_ACCOUNT_SID","TWILIO_AUTH_TOKEN","TWILIO_FROM_NUMBER","TWILIO_TO_NUMBER",
                    "HMH_CALL_API_TOKEN","GNANI_API_KEY","SCORER_API_KEY"):
            value=os.getenv(key,"")
            if value:message=message.replace(value,"[redacted]")
        message=re.sub(r"https?://[^\s]+","[URL]",message)
        message=re.sub(r"\+\d[\d ()-]{6,}","[phone]",message)
        message=re.sub(r"\b(?:AC|CA|RE|SK)[a-fA-F0-9]{32}\b","[identifier]",message)
        message=" ".join(message.split())[:500]
        return f"Twilio rejected call setup (HTTP {exc.status}; no specific error code): {message}"
    if code in actions:
        return actions[code]+f" (Twilio {code})"
    if isinstance(code,int) or (isinstance(code,str) and code.isdigit()):
        return f"Twilio rejected the request (error {code}). See https://www.twilio.com/docs/api/errors/{code}. Check provider logs before retrying."
    return "Call setup or processing failed ("+type(exc).__name__+"). Check the provider console before retrying; a timed-out call request may still have been accepted."


@dataclass
class PhoneCall:
    id:str
    conversation:Conversation
    created:float=field(default_factory=time.time)
    media_token:str=field(default_factory=lambda:secrets.token_urlsafe(32))
    webhook_token:str=field(default_factory=lambda:secrets.token_urlsafe(32))
    phase:str="preparing"
    sid:str|None=None
    error:str|None=None
    audio:dict=field(default_factory=dict)
    recordings:set=field(default_factory=set)
    pending_turn:str|None=None
    processing_since:float|None=None
    stt_mode:str="gather"
    trial:bool=False
    hops:int=0
    submitted_turns:set=field(default_factory=set)
    lock:asyncio.Lock=field(default_factory=asyncio.Lock)


class CallService:
    def __init__(self,directory,client_factory=None,synthesizer=synthesize,transcriber=transcribe,scorer=score):
        self.directory=directory
        self.calls={}
        self._account_cache=None
        self.client_factory=client_factory
        self.synthesizer,self.transcriber,self.scorer=synthesizer,transcriber,scorer

    def client(self):
        if self.client_factory:
            return self.client_factory()
        from twilio.rest import Client
        from twilio.http.http_client import TwilioHttpClient
        return Client(os.environ["TWILIO_ACCOUNT_SID"],os.environ["TWILIO_AUTH_TOKEN"],http_client=TwilioHttpClient(timeout=10))

    def check_account(self):
        key=(os.environ["TWILIO_ACCOUNT_SID"],os.environ["TWILIO_AUTH_TOKEN"])
        if self._account_cache and self._account_cache[0]==key and time.time()-self._account_cache[1]<60:
            account_type=self._account_cache[2]
        else:
            account=self.client().api.accounts(key[0]).fetch()
            account_type=getattr(account,"type",None)
            self._account_cache=(key,time.time(),account_type)
        if account_type=="Trial" and speech_mode()=="prisma_record":
            raise ValueError("Twilio trial blocks Record and Stream. This Gnani phone flow requires those features enabled; no call was placed.")

        return account_type

    def base(self):
        return os.environ["HMH_PUBLIC_BASE_URL"].rstrip("/")

    def webhook_url(self,record,path):
        url=self.base()+path
        return url+"?trial_token="+record.webhook_token if record.trial else url

    def create(self,pack,request_id):
        validate_config()
        validate_pack(pack)
        if not re.fullmatch(r"[a-zA-Z0-9_-]{16,80}",request_id):
            raise ValueError("Invalid idempotency ID")
        if request_id in self.calls:
            return self.calls[request_id],False
        if any(c.phase not in {"completed","failed","cancelled"} for c in self.calls.values()):
            raise ValueError("A test call is already active; finish it before starting another")
        if sum(c.created>time.time()-3600 for c in self.calls.values())>=6:
            raise ValueError("This demo allows at most 6 test calls per hour")
        if len(self.calls)>=100:
            expired=[key for key,c in self.calls.items() if c.created<time.time()-3600 and c.phase in {"completed","failed","cancelled"}]
            for key in expired:
                del self.calls[key]
        account_type=self.check_account()
        if account_type=="Trial" and len(pack["clauses"])>3:
            raise ValueError("Use at most 3 topics for the trial demo; Twilio limits callback hops to 10.")
        language=pack["language"]
        conversation=Conversation(pack,self.directory,"indic-auto",language,PROFILES[language]["voice"],
            include_disclosure=False,message_overrides=PHONE_MESSAGES[language])
        record=PhoneCall(request_id,conversation,stt_mode=speech_mode(),trial=account_type=="Trial")
        self.calls[request_id]=record
        return record,True

    async def prepare_and_dial(self,record):
        try:
            c=record.conversation
            # Prepare audio BEFORE ringing the phone, so the answer webhook responds immediately.
            c.session.audit.append("phone_spoken_configuration",include_pack_disclosure=False,message_overrides=PHONE_MESSAGES[c.tts_language])
            opening=(GATHER_NOTICE if record.stt_mode=="gather" else RECORDING_NOTICE)[c.tts_language]+" "+c.speech_text()
            record.audio[c.turn]=await asyncio.to_thread(self.synthesizer,opening,language=c.tts_language,voice=c.voice)
            record.audio["waiting"]=await asyncio.to_thread(self.synthesizer,WAITING[c.tts_language],language=c.tts_language,voice=c.voice)
            if record.phase=="cancelled":
                return
            record.phase="dialing"
            parameters={"to":os.environ["TWILIO_TO_NUMBER"],
                "url":self.webhook_url(record,f"/twilio/answer/{record.id}"),
                "status_callback":self.webhook_url(record,f"/twilio/status/{record.id}")}
            # New trial accounts choose their shared caller number themselves.
            # Do not send paid-account-only optional call parameters.
            if not record.trial:
                parameters.update(from_=os.environ["TWILIO_FROM_NUMBER"],method="POST",
                    status_callback_event=["initiated","ringing","answered","completed"],
                    timeout=30,time_limit=900)
            if record.trial:
                # The generated SDK requires From even though the new trial API
                # chooses its own shared caller ID. Use its authenticated HTTP
                # transport without adding that disallowed field.
                def create_trial():
                    from twilio.base.version import Version
                    from types import SimpleNamespace
                    response=self.client().request("POST",
                        "https://api.twilio.com/2010-04-01/Accounts/"+os.environ["TWILIO_ACCOUNT_SID"]+"/Calls.json",
                        data={"To":parameters["to"],"Url":parameters["url"],"StatusCallback":parameters["status_callback"]})
                    if not 200<=response.status_code<300:
                        raise Version.exception("POST","/Calls.json",response,"Unable to create record")
                    import json
                    sid=json.loads(response.text).get("sid")
                    if not isinstance(sid,str) or not re.fullmatch(r"CA[a-fA-F0-9]{32}",sid):
                        raise ValueError("Twilio returned no valid call identifier; check provider logs before retrying")
                    return SimpleNamespace(sid=sid)
                call=await asyncio.to_thread(create_trial)
            else:
                call=await asyncio.to_thread(self.client().calls.create,**parameters)
            record.sid=call.sid
            c.session.audit.append("outbound_call_created",call_sid=call.sid,
                                   destination="configured_test_phone",question_limit=15,answer_recording=record.stt_mode=="prisma_record",stt_provider=record.stt_mode)
            if record.phase=="cancelled":
                await asyncio.to_thread(self.client().calls(call.sid).update,status="completed")
        except Exception as exc:
            record.phase="failed"
            record.error=provider_error(exc)
            record.conversation.session.status="human_review"
            record.conversation.session.audit.append("outbound_failed",error_type=type(exc).__name__,provider_code=getattr(exc,"code",None))

    def media_url(self,record,key):
        return self.base()+f"/media/{record.id}/{record.media_token}/{quote(key,safe=':')}"

    def twiml(self,record,waiting=False):
        response=Element("Response")
        c=record.conversation
        if record.trial and record.hops>=10 and c.session.status=="active":
            c.session.status="human_review"
            c.session.audit.append("session_finished",status="human_review",reason="Trial callback budget reached")
            SubElement(response,"Say",language="en-US").text="This demo has reached its call limit. Your verification is incomplete."
            SubElement(response,"Hangup")
            return tostring(response,encoding="unicode")
        if record.phase in {"failed","cancelled","completed"}:
            SubElement(response,"Hangup")
        elif waiting or record.phase in {"preparing","processing"}:
            if "waiting" in record.audio:
                SubElement(response,"Play").text=self.media_url(record,"waiting")
            record.hops+=1
            SubElement(response,"Pause",length="8" if record.trial else "2")
            SubElement(response,"Redirect",method="POST").text=self.webhook_url(record,f"/twilio/next/{record.id}")
        else:
            if c.turn in record.audio:
                SubElement(response,"Play").text=self.media_url(record,c.turn)
            else:
                SubElement(response,"Hangup")
                return tostring(response,encoding="unicode")
            if c.session.status!="active":
                SubElement(response,"Hangup")
            else:
                turn=quote(c.turn,safe=':')
                if record.stt_mode=="gather":
                    record.hops+=1
                    SubElement(response,"Gather",input="speech",language="hi-IN" if c.tts_language=="hi-en" else c.tts_language,
                        speechTimeout="3",timeout="8",actionOnEmptyResult="true",method="POST",
                        action=self.webhook_url(record,f"/twilio/gathered/{record.id}/{turn}"))
                    return tostring(response,encoding="unicode")
                SubElement(response,"Record",action=self.base()+f"/twilio/recorded/{record.id}/{turn}",
                    method="POST",maxLength="25",timeout="3",playBeep="true",finishOnKey="#",
                    recordingStatusCallback=self.base()+f"/twilio/ready/{record.id}/{turn}",
                    recordingStatusCallbackMethod="POST",recordingStatusCallbackEvent="completed absent")
                SubElement(response,"Redirect",method="POST").text=self.webhook_url(record,f"/twilio/next/{record.id}")
        return tostring(response,encoding="unicode")

    async def gathered(self,record,turn,answer,confidence=None):
        async with record.lock:
            if record.stt_mode!="gather" or turn!=record.conversation.turn or turn in record.submitted_turns or record.phase in {"cancelled","failed","completed"}:
                return
            record.submitted_turns.add(turn)
            record.pending_turn=turn
            record.processing_since=time.time()
            record.phase="processing"
            try:
                changed=await asyncio.to_thread(record.conversation.receive_transcript,answer,self.scorer,
                    {"provider":"twilio_gather","confidence":confidence,"language":record.conversation.tts_language})
                if record.phase in {"cancelled","completed"}:return
                if not changed:raise ValueError("No usable transcript")
                audio=await asyncio.to_thread(record.conversation.speak,self.synthesizer)
                if audio is None:raise ValueError("TTS failed")
                record.audio[record.conversation.turn]=audio
                record.pending_turn=None
                if record.phase not in {"cancelled","completed"}:record.phase="ready"
            except Exception as exc:
                await self.escalate(record,type(exc).__name__)
            finally:
                record.processing_since=None

    async def recording_ready(self,record,turn,recording_sid):
        async with record.lock:
            if record.phase in {"cancelled","failed","completed"} or turn!=record.conversation.turn or recording_sid in record.recordings:
                return
            if not re.fullmatch(r"RE[a-fA-F0-9]{32}",recording_sid):
                raise ValueError("Invalid recording identifier")
            record.recordings.add(recording_sid)
            record.pending_turn=turn
            record.processing_since=time.time()
            record.phase="processing"
            try:
                # Reconstruct the URL from trusted account/recording IDs, never a webhook-provided URL.
                url=f"https://api.twilio.com/2010-04-01/Accounts/{os.environ['TWILIO_ACCOUNT_SID']}/Recordings/{recording_sid}.wav"
                async with httpx.AsyncClient(timeout=30,follow_redirects=True) as client:
                    response=await client.get(url,auth=(os.environ["TWILIO_ACCOUNT_SID"],os.environ["TWILIO_AUTH_TOKEN"]))
                    response.raise_for_status()
                if len(response.content)>3*1024*1024:
                    raise ValueError("Recording exceeds test limit")
                changed=await asyncio.to_thread(record.conversation.receive,response.content,self.transcriber,self.scorer)
                if record.phase in {"cancelled","completed"}:
                    return
                if not changed:
                    raise ValueError("Answer could not be assessed; human review required")
                audio=await asyncio.to_thread(record.conversation.speak,self.synthesizer)
                if audio is None:
                    raise ValueError("Could not synthesize the next response")
                record.audio[record.conversation.turn]=audio
                record.pending_turn=None
                if record.phase not in {"cancelled","completed"}:
                    record.phase="ready"
            except Exception as exc:
                await self.escalate(record,type(exc).__name__)
            finally:
                record.processing_since=None

    async def escalate(self,record,reason):
        if record.phase in {"cancelled","completed"}:
            return
        s=record.conversation.session
        if s.status=="active":
            s.status="human_review"
            s.audit.append("session_finished",status="human_review",reason=reason)
        record.pending_turn=None
        try:
            audio=await asyncio.to_thread(record.conversation.speak,self.synthesizer)
            if audio is None:raise ValueError("TTS failed")
            record.audio[record.conversation.turn]=audio
            record.phase="ready"
        except Exception:
            record.phase="failed"
        record.error="Verification stopped for human review: "+reason

    def summary(self,record):
        s=record.conversation.session
        return {"id":record.id,"phase":record.phase,"verification_status":s.status,"checks_passed":len(s.results),
                "questions_selected":len(s.pack["clauses"]),"answer_turns":s.answer_turns,
                "stt_provider":record.stt_mode,"trial":record.trial,"callback_hops":record.hops,"error":record.error,"last_assessment":record.conversation.history[-1] if record.conversation.history else None}
