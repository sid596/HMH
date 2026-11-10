import io
import wave
import unittest
from unittest.mock import Mock
import numpy as np
from engine.call_context import wav_segments, transcribe_recording, analyse_context
from engine.pack_builder import sample_catalog, ranked_topics, compile_pack, detect_document_language


def wav(seconds=1,channels=1):
    out=io.BytesIO()
    samples=np.zeros((16000*seconds,channels),dtype='<i2')
    samples[:,0]=1000
    if channels==2:samples[:,1]=2000
    with wave.open(out,'wb') as f:
        f.setnchannels(channels);f.setsampwidth(2);f.setframerate(16000);f.writeframes(samples.tobytes())
    return out.getvalue()

class CallContextTests(unittest.TestCase):
    def test_stereo_roles_and_all_frames_are_preserved(self):
        clips=wav_segments(wav(26,2),'agent_left')
        self.assertEqual(len(clips),4)
        self.assertEqual([c['speaker'] for c in clips],['agent','customer','agent','customer'])
        self.assertEqual(clips[-1]['end_seconds'],26)
        with wave.open(io.BytesIO(clips[1]['audio'])) as f:
            self.assertEqual(np.frombuffer(f.readframes(1),dtype='<i2')[0],2000)
        self.assertEqual(wav_segments(wav())[0]['speaker'],'unknown')

    def test_recording_transcription_does_not_assign_unknown_roles(self):
        stt=Mock(return_value={'transcript':'Some words'})
        result=transcribe_recording(wav(26),stt)
        self.assertEqual(stt.call_count,2)
        self.assertTrue(all(s['speaker']=='unknown' for s in result['segments']))
        self.assertEqual(stt.call_args.kwargs['language'],'indic-auto')

    def test_false_language_preference_from_unknown_speaker_is_rejected(self):
        transcript={'segments':[{'speaker':'unknown','text':'Please speak Kannada'}]}
        caller=Mock(return_value={'preferred_language':'kn-IN','preference_evidence':{'segment_index':0,'quote':'Please speak Kannada'},'notes':[]})
        with self.assertRaises(ValueError):analyse_context(sample_catalog('en-IN'),transcript,caller)
        transcript['segments'][0]['speaker']='customer'
        result=analyse_context(sample_catalog('en-IN'),transcript,caller)
        self.assertEqual(result['call_context']['preferred_language'],'kn-IN')

    def test_prior_call_cannot_rewrite_policy_or_invent_agent_attribution(self):
        catalog=sample_catalog('en-IN')
        transcript={'segments':[{'speaker':'unknown','text':'Early withdrawal is completely free'}]}
        note={'topic_id':'early_exit','segment_index':0,'quote':'Early withdrawal is completely free','kind':'agent_claim','observation':'Potential contradiction'}
        caller=Mock(return_value={'preferred_language':None,'preference_evidence':None,'notes':[note]})
        with self.assertRaises(ValueError):analyse_context(catalog,transcript,caller)
        transcript['segments'][0]['speaker']='agent'
        result=analyse_context(catalog,transcript,caller)
        self.assertEqual(result['topics'],catalog['topics'])

    def test_important_topics_precede_optional_even_with_lower_score(self):
        catalog=sample_catalog('en-IN')
        catalog['topics'][1]['priority_score']=1
        catalog['topics'][3]['risk']='standard'
        catalog['topics'][3]['priority_score']=100
        self.assertEqual([t['id'] for t in ranked_topics(catalog)],['contribution','returns','early_exit','cancellation'])

    def test_more_than_fifteen_selected_questions_is_rejected(self):
        from copy import deepcopy
        catalog=sample_catalog('en-IN')
        template=catalog['topics'][0]
        catalog['topics']=[dict(deepcopy(template),id=f'topic_{n}') for n in range(16)]
        with self.assertRaisesRegex(ValueError,'15 questions'):
            compile_pack(catalog,{t['id'] for t in catalog['topics']},'Reviewer',{})

    def test_auto_language_uses_document_evidence(self):
        document=sample_catalog('en-IN')['document']
        caller=Mock(return_value={'language':'en-IN','evidence_id':0})
        self.assertEqual(detect_document_language(document,caller),'en-IN')
        caller.return_value={'language':'en-IN','evidence_id':100}
        with self.assertRaises(ValueError):detect_document_language(document,caller)
