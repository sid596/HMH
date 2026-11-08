import io
import tempfile
import unittest
import wave
from pathlib import Path
from unittest.mock import Mock
from engine.conversation import Conversation
from engine.core import load_pack
from engine.localization import localized_pack
from engine.scorer import fixture_evidence

PACK = load_pack(Path(__file__).resolve().parents[1] / "packs/fictional_savings_v1.json")

def recording(seconds=1):
    buffer = io.BytesIO()
    with wave.open(buffer, "wb") as wav:
        wav.setnchannels(1)
        wav.setsampwidth(2)
        wav.setframerate(16000)
        wav.writeframes(b'\0\0' * 16000 * seconds)
    return buffer.getvalue()

class ConversationTests(unittest.TestCase):
    def test_response_drives_retry_then_pass_and_completion(self):
        with tempfile.TemporaryDirectory() as d:
            c = Conversation(PACK, d)
            stt = Mock(return_value={"transcript": "Haan haan", "request_id": "test"})
            scorer = Mock(return_value=fixture_evidence(c.session.clause, "nods_along")[1])
            self.assertTrue(c.receive(recording(), stt, scorer))
            self.assertEqual(c.session.attempt, 1)
            self.assertIn(localized_pack("hi-IN")["messages"]["no_evidence"], c.speech_text())
            for _ in PACK["clauses"]:
                scorer.return_value = fixture_evidence(c.session.clause, "attentive")[1]
                self.assertTrue(c.receive(recording(), stt, scorer))
            self.assertEqual(c.session.status, "demo_checks_passed")
            self.assertEqual(localized_pack("hi-IN")["messages"]["complete"], c.speech_text())
            self.assertFalse(c.receive(recording(), stt, scorer))

    def test_scorer_failure_reuses_transcript_only_on_explicit_retry(self):
        with tempfile.TemporaryDirectory() as d:
            c = Conversation(PACK, d)
            stt = Mock(return_value={"transcript": "Synthetic answer"})
            scorer = Mock(side_effect=RuntimeError("Unavailable"))
            self.assertFalse(c.receive(recording(), stt, scorer))
            self.assertFalse(c.receive(recording(), stt, scorer))
            self.assertEqual(stt.call_count, 1)
            self.assertEqual(scorer.call_count, 1)
            self.assertEqual(c.session.attempt, 0)
            scorer.side_effect = None
            scorer.return_value = fixture_evidence(c.session.clause, "attentive")[1]
            self.assertTrue(c.receive(recording(), stt, scorer, retry=True))
            self.assertEqual(stt.call_count, 1)

    def test_tts_runs_once_per_turn_and_failure_waits_for_retry(self):
        with tempfile.TemporaryDirectory() as d:
            c = Conversation(PACK, d)
            tts = Mock(side_effect=RuntimeError())
            self.assertIsNone(c.speak(tts))
            self.assertIsNone(c.speak(tts))
            self.assertEqual(tts.call_count, 1)
            tts.side_effect = None
            tts.return_value = b"RIFF_test"
            self.assertEqual(c.speak(tts, retry=True), b"RIFF_test")
            c.speak(tts)
            self.assertEqual(tts.call_count, 2)

    def test_long_recording_never_calls_api(self):
        with tempfile.TemporaryDirectory() as d:
            c = Conversation(PACK, d)
            stt, scorer = Mock(), Mock()
            self.assertFalse(c.receive(recording(31), stt, scorer))
            stt.assert_not_called()
            scorer.assert_not_called()
            self.assertEqual(c.session.attempt, 0)
