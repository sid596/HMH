import asyncio
from copy import deepcopy
import os
from pathlib import Path
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import Mock,AsyncMock,patch
from xml.etree.ElementTree import fromstring
from engine.pack_builder import sample_catalog,compile_pack
from engine.core import Session
from engine.scorer import fixture_evidence
from telephony.service import CallService,validate_pack

ENV={'PHONE_STT_MODE':'prisma_record','TWILIO_ACCOUNT_SID':'AC'+'a'*32,'TWILIO_AUTH_TOKEN':'not-a-real-token',
     'TWILIO_FROM_NUMBER':'+12025550101','TWILIO_TO_NUMBER':'+12025550102',
     'HMH_PUBLIC_BASE_URL':'https://hmh.example.test','HMH_CALL_API_TOKEN':'test-control-token-'+'x'*32,
     'GNANI_API_KEY':'test-gnani-key','SCORER_API_KEY':'test-scorer-key','SCORER_MODEL':'test-model'}

def pack():
    catalog=sample_catalog('en-IN')
    return compile_pack(catalog,{'contribution','returns'},'Test reviewer',{'early_exit':'Separate test','cancellation':'Separate test'})

class PhoneTests(unittest.IsolatedAsyncioTestCase):
    async def test_prepare_then_dial_and_duplicate_request_does_not_redial(self):
        with tempfile.TemporaryDirectory() as d,patch.dict(os.environ,ENV,clear=True):
            client=Mock()
            client.calls.create.return_value=SimpleNamespace(sid='CA'+'b'*32)
            tts=Mock(return_value=b'RIFF_audio')
            service=CallService(d,client_factory=lambda:client,synthesizer=tts)
            record,created=service.create(pack(),'request_'+'a'*20)
            self.assertTrue(created)
            self.assertEqual(record.phase,'preparing')
            await service.prepare_and_dial(record)
            self.assertEqual(record.phase,'dialing')
            self.assertEqual(tts.call_count,2)
            client.calls.create.assert_called_once()
            self.assertEqual(client.calls.create.call_args.kwargs['to'],ENV['TWILIO_TO_NUMBER'])
            _,created=service.create(pack(),record.id)
            self.assertFalse(created)
            record.phase='ready'
            xml=fromstring(service.twiml(record))
            self.assertIsNotNone(xml.find('Play'))
            self.assertEqual(xml.find('Record').attrib['maxLength'],'25')
            self.assertIn('/twilio/ready/',xml.find('Record').attrib['recordingStatusCallback'])

    async def test_tts_failure_never_dials_phone(self):
        with tempfile.TemporaryDirectory() as d,patch.dict(os.environ,ENV,clear=True):
            client=Mock()
            service=CallService(d,client_factory=lambda:client,synthesizer=Mock(side_effect=RuntimeError()))
            record,_=service.create(pack(),'request_'+'a'*20)
            await service.prepare_and_dial(record)
            self.assertEqual(record.phase,'failed')
            client.calls.create.assert_not_called()

    async def test_terminal_verdict_hangs_up_without_another_recording(self):
        with tempfile.TemporaryDirectory() as d,patch.dict(os.environ,ENV,clear=True):
            service=CallService(d,client_factory=Mock)
            record,_=service.create(pack(),'request_'+'a'*20)
            record.conversation.session.status='human_review'
            record.audio[record.conversation.turn]=b'RIFF_end'
            record.phase='ready'
            xml=fromstring(service.twiml(record))
            self.assertIsNone(xml.find('Record'))
            self.assertIsNotNone(xml.find('Hangup'))

class BudgetTests(unittest.TestCase):
    def test_retries_count_against_fifteen_question_budget(self):
        template=pack()
        template['clauses']=[dict(deepcopy(template['clauses'][0]),id=f'clause_{n}') for n in range(15)]
        with tempfile.TemporaryDirectory() as d:
            session=Session(template,d,'live')
            answer,e=fixture_evidence(session.clause,'partial')
            session.submit(answer,e)
            for _ in range(14):
                answer,e=fixture_evidence(session.clause,'attentive')
                session.submit(answer,e)
            self.assertEqual(session.answer_turns,15)
            self.assertEqual(session.status,'human_review')
            self.assertTrue([r for r in session.audit.records() if r['event']=='assessment'][-1]['payload']['question_budget_exhausted'])

class ServerTests(unittest.TestCase):
    def setUp(self):
        from fastapi.testclient import TestClient
        from telephony import server
        self.directory=tempfile.TemporaryDirectory()
        self.env=patch.dict(os.environ,ENV,clear=True);self.env.start()
        self.server=server
        self.saved_service=server.service
        server.service=CallService(self.directory.name,client_factory=Mock)
        server.service.prepare_and_dial=AsyncMock()
        self.client=TestClient(server.app)
        self.header={'Authorization':'Bearer '+ENV['HMH_CALL_API_TOKEN']}

    def tearDown(self):
        self.server.service=self.saved_service
        self.env.stop();self.directory.cleanup()

    def test_call_controls_require_admin_token(self):
        self.assertEqual(self.client.post('/calls',json={}).status_code,401)
        self.assertEqual(self.client.get('/health').status_code,401)
        self.assertTrue(self.client.get('/health',headers=self.header).json()['ready'])

    def test_unsigned_callbacks_and_wrong_media_token_are_rejected(self):
        body={'request_id':'request_'+'a'*20,'pack':pack()}
        response=self.client.post('/calls',json=body,headers=self.header)
        self.assertEqual(response.status_code,200)
        self.assertEqual(self.client.post('/twilio/answer/'+body['request_id'],data={'AccountSid':ENV['TWILIO_ACCOUNT_SID'],'CallSid':'CA'+'b'*32}).status_code,403)
        self.assertEqual(self.client.get('/media/'+body['request_id']+'/wrong/waiting').status_code,404)

    def test_signed_answer_callback_serves_gnani_audio_and_record_instructions(self):
        from twilio.request_validator import RequestValidator
        body={'request_id':'request_'+'a'*20,'pack':pack()}
        self.client.post('/calls',json=body,headers=self.header)
        record=self.server.service.calls[body['request_id']]
        record.audio[record.conversation.turn]=b'RIFF_audio'
        path='/twilio/answer/'+body['request_id']
        form={'AccountSid':ENV['TWILIO_ACCOUNT_SID'],'CallSid':'CA'+'b'*32}
        signature=RequestValidator(ENV['TWILIO_AUTH_TOKEN']).compute_signature(ENV['HMH_PUBLIC_BASE_URL']+path,form)
        response=self.client.post(path,data=form,headers={'X-Twilio-Signature':signature})
        self.assertEqual(response.status_code,200)
        self.assertIsNotNone(fromstring(response.text).find('Record'))

class TrialGuardTests(unittest.TestCase):
    def test_trial_cannot_trigger_a_billable_call_with_unsupported_audio(self):
        with tempfile.TemporaryDirectory() as d,patch.dict(os.environ,ENV,clear=True):
            client=Mock()
            client.api.accounts.return_value.fetch.return_value=SimpleNamespace(type='Trial')
            service=CallService(d,client_factory=lambda:client)
            with self.assertRaisesRegex(ValueError,'trial blocks'):
                service.create(pack(),'request_'+'a'*20)
            client.calls.create.assert_not_called()
            self.assertEqual(len(service.calls),0)

class RecordingCallbackTests(unittest.IsolatedAsyncioTestCase):
    async def test_recording_ready_assesses_once_and_prepares_next_spoken_turn(self):
        import io,wave,httpx
        buffer=io.BytesIO()
        with wave.open(buffer,'wb') as audio:
            audio.setnchannels(1);audio.setsampwidth(2);audio.setframerate(16000);audio.writeframes(b'\0\0'*16000)
        with tempfile.TemporaryDirectory() as d,patch.dict(os.environ,ENV,clear=True):
            stt=Mock(return_value={'transcript':'1,000 each month for 3 years'})
            scorer=Mock(return_value=fixture_evidence(pack()['clauses'][0],'attentive')[1])
            service=CallService(d,client_factory=Mock,synthesizer=Mock(return_value=b'RIFF_next'),transcriber=stt,scorer=scorer)
            record,_=service.create(pack(),'request_'+'z'*20)
            turn=record.conversation.turn
            response=httpx.Response(200,content=buffer.getvalue(),request=httpx.Request('GET','https://api.twilio.com/test'))
            transport=AsyncMock()
            transport.__aenter__.return_value.get.return_value=response
            with patch('telephony.service.httpx.AsyncClient',return_value=transport):
                await service.recording_ready(record,turn,'RE'+'a'*32)
                await service.recording_ready(record,turn,'RE'+'a'*32)
            self.assertEqual(stt.call_count,1)
            self.assertEqual(scorer.call_count,1)
            self.assertEqual(record.phase,'ready')
            self.assertIsNone(record.pending_turn)
            self.assertEqual(record.conversation.session.index,1)
            self.assertIn(record.conversation.turn,record.audio)

class GatherTests(unittest.IsolatedAsyncioTestCase):
    async def test_trial_gather_uses_transcript_once_without_prisma(self):
        with tempfile.TemporaryDirectory() as d,patch.dict(os.environ,dict(ENV,PHONE_STT_MODE='gather'),clear=True):
            client=Mock()
            client.api.accounts.return_value.fetch.return_value=SimpleNamespace(type='Trial')
            stt=Mock(side_effect=AssertionError('Prisma must not be used'))
            scorer=Mock(return_value=fixture_evidence(pack()['clauses'][0],'attentive')[1])
            service=CallService(d,client_factory=lambda:client,transcriber=stt,scorer=scorer,synthesizer=Mock(return_value=b'RIFF_next'))
            record,_=service.create(pack(),'gather_'+'x'*20)
            record.phase='ready';record.audio[record.conversation.turn]=b'RIFF_open'
            xml=fromstring(service.twiml(record))
            self.assertIsNotNone(xml.find('Gather'))
            self.assertIsNone(xml.find('Record'))
            self.assertEqual(xml.find('Gather').attrib['language'],'en-IN')
            turn=record.conversation.turn
            await service.gathered(record,turn,'1,000 each month for 3 years','0.9')
            await service.gathered(record,turn,'duplicate','0.9')
            self.assertEqual(scorer.call_count,1)
            stt.assert_not_called()
            self.assertEqual(record.conversation.session.index,1)
            events=record.conversation.session.audit.records()
            assessment=next(e for e in events if e['event']=='assessment')
            self.assertEqual(assessment['payload']['input_source'],'twilio_gather')

    async def test_silence_goes_to_human_review_without_scoring(self):
        with tempfile.TemporaryDirectory() as d,patch.dict(os.environ,dict(ENV,PHONE_STT_MODE='gather'),clear=True):
            scorer=Mock()
            service=CallService(d,client_factory=Mock,scorer=scorer,synthesizer=Mock(return_value=b'RIFF_end'))
            record,_=service.create(pack(),'gather_'+'s'*20)
            await service.gathered(record,record.conversation.turn,'')
            self.assertEqual(record.conversation.session.status,'human_review')
            scorer.assert_not_called()

    async def test_trial_hop_budget_stops_instead_of_false_pass(self):
        with tempfile.TemporaryDirectory() as d,patch.dict(os.environ,dict(ENV,PHONE_STT_MODE='gather'),clear=True):
            service=CallService(d,client_factory=Mock)
            record,_=service.create(pack(),'gather_'+'h'*20)
            record.trial=True;record.hops=8;record.phase='ready'
            xml=fromstring(service.twiml(record))
            self.assertIsNotNone(xml.find('Hangup'))
            self.assertEqual(record.conversation.session.status,'human_review')

class GatherServerTests(ServerTests):
    def test_signed_gather_callback_is_authenticated_and_deduplicated(self):
        from twilio.request_validator import RequestValidator
        with patch.dict(os.environ,{'PHONE_STT_MODE':'gather'}):
            service=self.server.service
            service.synthesizer=Mock(return_value=b'RIFF_next')
            service.scorer=Mock(return_value=fixture_evidence(pack()['clauses'][0],'attentive')[1])
            record,_=service.create(pack(),'signed_'+'g'*20)
            record.phase='ready'
            path='/twilio/gathered/'+record.id+'/'+record.conversation.turn
            form={'AccountSid':ENV['TWILIO_ACCOUNT_SID'],'CallSid':'CA'+'b'*32,'SpeechResult':'1,000 each month for 3 years','Confidence':'0.9'}
            self.assertEqual(self.client.post(path,data=form).status_code,403)
            signature=RequestValidator(ENV['TWILIO_AUTH_TOKEN']).compute_signature(ENV['HMH_PUBLIC_BASE_URL']+path,form)
            headers={'X-Twilio-Signature':signature}
            self.assertEqual(self.client.post(path,data=form,headers=headers).status_code,200)
            self.assertEqual(self.client.post(path,data=form,headers=headers).status_code,200)
            self.assertEqual(service.scorer.call_count,1)


class TrialPackLimitTests(unittest.TestCase):
    def test_oversized_trial_pack_is_rejected_before_dialling(self):
        with tempfile.TemporaryDirectory() as d,patch.dict(os.environ,dict(ENV,PHONE_STT_MODE='gather'),clear=True):
            client=Mock()
            client.api.accounts.return_value.fetch.return_value=SimpleNamespace(type='Trial')
            service=CallService(d,client_factory=lambda:client)
            large=pack()
            large['clauses']=[dict(deepcopy(large['clauses'][0]),id=f'topic_{i}') for i in range(4)]
            with self.assertRaisesRegex(ValueError,'at most 3 topics'):
                service.create(large,'oversized_'+'x'*20)
            client.calls.create.assert_not_called()

class ProviderDiagnosticTests(unittest.TestCase):
    def test_unmapped_error_keeps_numeric_code_without_provider_message(self):
        from telephony.service import provider_error
        error=RuntimeError('private response must not be displayed')
        error.code=21205
        message=provider_error(error)
        self.assertIn('21205',message)
        self.assertNotIn('private response',message)
