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
        with self.assertRaisesRegex(ValueError,'No agent/customer-labelled turns'):
            analyse_context(catalog,transcript,caller)
        caller.assert_not_called()
        note['kind']='agent_claim'
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


class AssistedReviewTests(unittest.TestCase):
    def test_suggestions_split_turns_but_preserve_raw_transcript_and_chunk_times(self):
        from engine.call_context import suggest_transcript_review
        raw={'sha256':'fixture','segments':[{'start_seconds':0,'end_seconds':25,'speaker':'unknown','text':'Do I get a refund? Only minus 100.'}]}
        caller=Mock(return_value={'utterances':[
            {'segment_index':0,'source_text':'Do I get a refund?','text':'Do I get a refund?','suggested_speaker':'customer','reason':'Question, inferred role'},
            {'segment_index':0,'source_text':'Only minus 100.','text':'Only minus 100.','suggested_speaker':'agent','reason':'Response, inferred role'}]})
        result=suggest_transcript_review(raw,caller)
        self.assertTrue(result['review_required'])
        self.assertEqual(result['raw_transcript'],raw)
        self.assertEqual(raw['segments'][0]['speaker'],'unknown')
        self.assertEqual([s['speaker'] for s in result['segments']],['customer','agent'])
        self.assertEqual(result['segments'][1]['start_seconds'],0)

    def test_review_rejects_invented_source_changed_numbers_or_lost_negation(self):
        from engine.call_context import suggest_transcript_review
        raw={'segments':[{'start_seconds':0,'end_seconds':25,'speaker':'unknown','text':'No refund after 15 days.'}]}
        for source,text in [('Invented words','Invented words'),('No refund after 15 days.','No refund after 30 days.'),('No refund after 15 days.','Refund after 15 days.')]:
            caller=Mock(return_value={'utterances':[{'segment_index':0,'source_text':source,'text':text,'suggested_speaker':'agent','reason':'test'}]})
            with self.assertRaises(ValueError):suggest_transcript_review(raw,caller)

    def test_review_rejects_omitted_raw_words(self):
        from engine.call_context import suggest_transcript_review
        raw={'segments':[{'start_seconds':0,'end_seconds':25,'speaker':'unknown','text':'Wait. No refund.'}]}
        caller=Mock(return_value={'utterances':[{'segment_index':0,'source_text':'No refund.','text':'No refund.','suggested_speaker':'agent','reason':'test'}]})
        with self.assertRaisesRegex(ValueError,'omitted or duplicated'):suggest_transcript_review(raw,caller)

class ParallelTranscriptionTests(unittest.TestCase):
    def test_clip_requests_overlap_and_repeated_results_are_reused(self):
        from threading import Barrier
        barrier=Barrier(3)
        def stt(audio,language):
            barrier.wait(timeout=5)
            return {'transcript':'Recognized words'}
        caller=Mock(side_effect=stt)
        cache={}
        result=transcribe_recording(wav(51),caller,language='en-IN',cache=cache,max_workers=3)
        self.assertEqual([s['start_seconds'] for s in result['segments']],[0,25,50])
        self.assertEqual(caller.call_count,3)
        again=transcribe_recording(wav(51),caller,language='en-IN',cache=cache,max_workers=3)
        self.assertEqual(caller.call_count,3)
        self.assertEqual(again['performance']['reused_clips'],3)


class QuietBoundaryTests(unittest.TestCase):
    def test_clipping_prefers_silence_without_losing_frames(self):
        samples=np.full(16000*32,1000,dtype='<i2')
        samples[16000*24:16000*24+8000]=0
        buffer=io.BytesIO()
        with wave.open(buffer,'wb') as w:
            w.setnchannels(1);w.setsampwidth(2);w.setframerate(16000);w.writeframes(samples.tobytes())
        clips=wav_segments(buffer.getvalue())
        self.assertAlmostEqual(clips[0]['end_seconds'],24.5,places=1)
        self.assertEqual(clips[1]['start_seconds'],clips[0]['end_seconds'])
        frames=0
        for c in clips:
            with wave.open(io.BytesIO(c['audio'])) as w:frames+=w.getnframes()
        self.assertEqual(frames,len(samples))


class TranscriptionFailureCacheTests(unittest.TestCase):
    def test_successful_clip_is_reused_after_explicit_retry(self):
        import httpx
        calls=0
        def provider(audio,language):
            nonlocal calls
            calls+=1
            if calls==2:
                response=httpx.Response(429,request=httpx.Request('POST','https://example.test'))
                raise httpx.HTTPStatusError('private provider message',request=response.request,response=response)
            return {'transcript':'Recognized speech'}
        cache={}
        with self.assertRaises(httpx.HTTPStatusError):
            transcribe_recording(wav(26),provider,cache=cache,max_workers=1)
        self.assertEqual(len(cache),1)
        result=transcribe_recording(wav(26),provider,cache=cache,max_workers=1)
        self.assertEqual(calls,3)
        self.assertEqual(result['performance']['reused_clips'],1)
        self.assertEqual(len(result['segments']),2)

class CleanupContractionTests(unittest.TestCase):
    def test_expanding_negative_contraction_preserves_polarity(self):
        from engine.call_context import suggest_transcript_review
        raw={'segments':[{'start_seconds':0,'end_seconds':5,'speaker':'unknown','text':"I don't get a refund?"}]}
        caller=Mock(return_value={'utterances':[{'segment_index':0,'source_text':"I don't get a refund?",'text':'I do not get a refund?','suggested_speaker':'customer','reason':'Expanded contraction'}]})
        result=suggest_transcript_review(raw,caller)
        self.assertEqual(result['segments'][0]['speaker'],'customer')
        self.assertEqual(result['segments'][0]['raw_text'],"I don't get a refund?")


class UnknownTurnFilteringTests(unittest.TestCase):
    def test_unknown_turns_are_not_sent_to_model_but_remain_in_record(self):
        transcript={'segments':[{'speaker':'unknown','text':'Opening chatter'}, {'speaker':'customer','text':'I am confused about cancellation'}]}
        caller=Mock(return_value={'notes':[{'topic_id':'cancellation','segment_index':0,'quote':'confused about cancellation','kind':'customer_question','observation':'Customer needs clarification'}],'preferred_language':None,'preference_evidence':None})
        result=analyse_context(sample_catalog('en-IN'),transcript,caller)
        sent=caller.call_args.args[1]['segments']
        self.assertEqual(len(sent),1)
        self.assertEqual(sent[0]['speaker'],'customer')
        record=result['call_context']['transcript']
        self.assertEqual(record['excluded_unknown_segments'][0]['text'],'Opening chatter')
        self.assertEqual(record['transcript_before_filtering'],transcript)
        self.assertEqual(len(transcript['segments']),2)

class ContextEvidenceReferenceTests(unittest.TestCase):
    def transcript(self):
        return {'segments':[{'speaker':'unknown','text':'Opening chatter'}, {'speaker':'customer','text':'When does the cancellation window start?','source_segment_index':9}, {'speaker':'agent','text':'It starts on receipt of the document.'}]}

    def test_evidence_id_copies_exact_reviewed_quote_after_unknown_filtering(self):
        caller=Mock(return_value={'notes':[{'topic_id':'cancellation','evidence_id':'evidence_0000','kind':'customer_question','observation':'Needs deadline clarification'}],'preferred_language':None,'preference_evidence':None})
        result=analyse_context(sample_catalog('en-IN'),self.transcript(),caller)
        note=result['call_context']['notes'][0]
        self.assertEqual(note['segment_index'],0)
        self.assertEqual(note['quote'],'When does the cancellation window start?')
        self.assertEqual(note['speaker'],'customer')
        sent=caller.call_args.args[1]['segments']
        self.assertNotIn('source_segment_index',sent[0])

    def test_wrong_legacy_index_is_repaired_only_by_unique_exact_quote(self):
        caller=Mock(return_value={'notes':[{'topic_id':'cancellation','segment_index':9,'quote':'cancellation window start','kind':'customer_question','observation':'Needs clarification'}],'preferred_language':None,'preference_evidence':None})
        result=analyse_context(sample_catalog('en-IN'),self.transcript(),caller)
        self.assertTrue(result['call_context']['notes'][0]['reference_repaired'])
        caller.return_value['notes'][0]['quote']='A fabricated promise of free coverage'
        with self.assertRaises(ValueError):analyse_context(sample_catalog('en-IN'),self.transcript(),caller)

    def test_invented_evidence_id_is_rejected(self):
        caller=Mock(return_value={'notes':[{'topic_id':'cancellation','evidence_id':'evidence_9999','kind':'confusion','observation':'test'}],'preferred_language':None,'preference_evidence':None})
        with self.assertRaisesRegex(ValueError,'unknown transcript evidence ID'):
            analyse_context(sample_catalog('en-IN'),self.transcript(),caller)

class RelatedTopicPriorityTests(unittest.TestCase):
    def relationship(self):
        return {'topic_id':'early_exit','anchor_topic_id':'cancellation','relationship':'condition',
                'topic_fact_indices':[0],'anchor_fact_indices':[0],'reason':'Both concern leaving the product and the applicable conditions.'}

    def test_direct_then_related_then_unaffected_within_risk_tier(self):
        from engine.call_context import validate_related_topics
        catalog=sample_catalog('en-IN')
        for topic in catalog['topics']:topic['required']=False
        notes=[{'topic_id':'cancellation','kind':'customer_question'}]
        catalog['call_context']={'notes':notes,'related_topics':validate_related_topics([self.relationship()],catalog,notes)}
        for t in catalog['topics']:t['priority_score']=100 if t['id']=='returns' else 1
        ordered=[t['id'] for t in ranked_topics(catalog)]
        self.assertEqual(ordered[:2],['cancellation','early_exit'])
        saved=compile_pack(catalog,{t['id'] for t in catalog['topics']},'Reviewer')
        self.assertEqual([c['id'] for c in saved['clauses']],ordered)
        next(t for t in catalog['topics'] if t['id']=='early_exit')['risk']='standard'
        self.assertLess([t['id'] for t in ranked_topics(catalog)].index('returns'),[t['id'] for t in ranked_topics(catalog)].index('early_exit'))

    def test_invalid_anchors_or_invented_facts_cannot_promote_topics(self):
        from engine.call_context import validate_related_topics
        catalog=sample_catalog('en-IN');notes=[{'topic_id':'cancellation','kind':'confusion'}]
        for change in ({'anchor_topic_id':'returns'},{'topic_id':'invented'},{'topic_fact_indices':[999]},{'topic_id':'cancellation'}):
            with self.assertRaises(ValueError):validate_related_topics([self.relationship()|change],catalog,notes)

    def test_related_topics_do_not_enter_pack_without_selection(self):
        from engine.call_context import validate_related_topics
        catalog=sample_catalog('en-IN');notes=[{'topic_id':'cancellation','kind':'confusion'}]
        catalog['call_context']={'notes':notes,'related_topics':validate_related_topics([self.relationship()],catalog,notes)}
        saved=compile_pack(catalog,{'contribution','returns','cancellation'},'Reviewer')
        self.assertNotIn('early_exit',[c['id'] for c in saved['clauses']])
        self.assertEqual(saved['call_context']['related_topics'][0]['topic_id'],'early_exit')


class MultilingualEvidenceTests(unittest.TestCase):
    def test_reviewed_customer_quotes_remain_exact_in_supported_languages(self):
        for text in [
            'मुझे समझ नहीं आया, पंद्रह दिन पैसे देने से शुरू होते हैं या दस्तावेज मिलने से?',
            'मला शंका आहे, पंधरा दिवस पैसे भरल्यापासून की कागदपत्र मिळाल्यापासून मोजायचे?',
            'ನನಗೆ ಗೊಂದಲವಾಗಿದೆ, ಹದಿನೈದು ದಿನಗಳು ಹಣ ಪಾವತಿಸಿದ ದಿನದಿಂದಲೋ ಅಥವಾ ದಾಖಲೆ ಸಿಕ್ಕ ದಿನದಿಂದಲೋ?']:
            caller=Mock(return_value={'notes':[{'topic_id':'cancellation','evidence_id':'evidence_0000','kind':'customer_question','observation':'Clarify deadline'}],'preferred_language':None,'preference_evidence':None})
            result=analyse_context(sample_catalog('en-IN'),{'segments':[{'speaker':'customer','text':text}]},caller)
            self.assertEqual(result['call_context']['notes'][0]['quote'],text)
