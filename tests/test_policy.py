import tempfile
import unittest
from pathlib import Path
from engine.core import Evidence, Session, decide, load_pack
from engine.scorer import fixture_evidence

PACK = load_pack(Path(__file__).resolve().parents[1] / "packs/fictional_savings_v1.json")

class PolicyTests(unittest.TestCase):
    def test_critical_partial_never_passes(self):
        _, e = fixture_evidence(PACK["clauses"][0], "partial")
        self.assertEqual([decide(e, True, n) for n in (1,2,3)], ["retry", "retry", "escalate"])

    def test_low_confidence_understood_passes_based_on_complete_facts(self):
        raw = dict(facts_present=[0,1], facts_missing=[], misconception_detected=False,
                   verdict="understood", confidence=0.5, rationale="Uncertain translation")
        self.assertEqual(decide(Evidence.validate(raw, PACK["clauses"][0]), True, 1), "pass")

    def test_confidence_never_changes_wrong_answer_retry_budget(self):
        from dataclasses import replace
        _, evidence=fixture_evidence(PACK["clauses"][0],"misconception")
        for confidence in (0.0,0.5,0.78,0.99,1.0):
            e=replace(evidence,confidence=confidence)
            self.assertEqual([decide(e,True,n) for n in (1,2,3)],["retry","retry","escalate"])

    def test_partial_noncritical_topic_does_not_advance(self):
        _, e=fixture_evidence(PACK["clauses"][0],"partial")
        self.assertEqual(decide(e,False,1),"retry")

    def test_low_confidence_wrong_then_correct_advances_without_ending_session(self):
        from dataclasses import replace
        with tempfile.TemporaryDirectory() as d:
            session=Session(PACK,d,"live")
            answer,e=fixture_evidence(session.clause,"misconception")
            self.assertEqual(session.submit(answer,replace(e,confidence=0.78)),"retry")
            self.assertEqual(session.status,"active")
            answer,e=fixture_evidence(session.clause,"attentive")
            self.assertEqual(session.submit(answer,replace(e,confidence=0.1)),"pass")
            self.assertEqual(session.index,1)
            self.assertEqual(session.attempt,0)

    def test_inconsistent_model_output_rejected(self):
        raw = dict(facts_present=[0], facts_missing=[1], misconception_detected=False,
                   verdict="understood", confidence=0.99, rationale="")
        with self.assertRaises(ValueError):
            Evidence.validate(raw, PACK["clauses"][0])

    def test_nodding_exhausts_retries_and_stops(self):
        with tempfile.TemporaryDirectory() as d:
            s = Session(PACK, d, "scripted")
            for _ in range(3):
                answer, e = fixture_evidence(s.clause, "nods_along")
                s.submit(answer, e)
            self.assertEqual(s.status, "human_review")
            with self.assertRaises(ValueError):
                s.submit(answer, e)
            prompts = [r for r in s.audit.records() if r["event"] == "prompt"]
            self.assertEqual(prompts[-1]["payload"]["explanation"], PACK["clauses"][0]["fallback_explain"])

    def test_draft_never_produces_live_consent(self):
        with tempfile.TemporaryDirectory() as d:
            s = Session(PACK, d, "live")
            for _ in PACK["clauses"]:
                answer, e = fixture_evidence(s.clause, "attentive")
                s.submit(answer, e)
            self.assertEqual(s.status, "demo_checks_passed")
            records = s.audit.records()
            self.assertEqual(records[0]["payload"]["pack_version"], PACK["pack_version"])
            for before, after in zip(records, records[1:]):
                self.assertEqual(after["previous_hash"], before["hash"])

if __name__ == "__main__":
    unittest.main()


class UnderstandingThresholdTests(unittest.TestCase):
    def evidence(self,present,missing,contradiction=False,confidence=0.5):
        return Evidence(present,missing,contradiction,"misunderstood" if contradiction else "partial",confidence,"test")

    def test_seventy_five_percent_advances_regardless_of_model_certainty(self):
        for confidence in (0.1,0.74,0.99):
            self.assertEqual(decide(self.evidence([0,1,2],[3],confidence=confidence),True,1),"pass")

    def test_latest_call_four_of_five_advances_on_final_attempt(self):
        self.assertEqual(decide(self.evidence([0,1,3,4],[2]),True,3),"pass")

    def test_below_threshold_and_contradiction_do_not_pass(self):
        self.assertEqual(decide(self.evidence([0,1,3],[2,4]),True,1),"retry")
        self.assertEqual(decide(self.evidence([0,1,2],[3],True),True,1),"retry")
        self.assertEqual(decide(self.evidence([0,1,3],[2,4]),True,3),"escalate")

    def test_partial_threshold_pass_uses_positive_feedback(self):
        from copy import deepcopy
        from engine.conversation import Conversation
        from engine.localization import localized_pack
        pack=deepcopy(localized_pack('en-IN'))
        pack['clauses'][0]['must_have_facts']=['one','two','three','four']
        with tempfile.TemporaryDirectory() as d:
            conversation=Conversation(pack,d,'en-IN','en-IN','Pranav')
            evidence=self.evidence([0,1,2],[3])
            self.assertTrue(conversation.receive_transcript('A paraphrase',lambda answer,clause:evidence))
            self.assertEqual(conversation.history[-1]['verdict'],'understood')
            self.assertEqual(conversation.history[-1]['rubric_verdict'],'partial')
            self.assertEqual(conversation.session.index,1)
