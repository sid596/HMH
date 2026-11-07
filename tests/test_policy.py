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

    def test_low_confidence_understood_escalates(self):
        raw = dict(facts_present=[0,1], facts_missing=[], misconception_detected=False,
                   verdict="understood", confidence=0.5, rationale="Uncertain translation")
        self.assertEqual(decide(Evidence.validate(raw, PACK["clauses"][0]), True, 1), "escalate")

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
