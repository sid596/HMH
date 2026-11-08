import tempfile
import unittest
from unittest.mock import Mock
from engine.localization import PROFILES, localized_pack
from engine.conversation import Conversation

class LocalizationTests(unittest.TestCase):
    def test_all_packs_complete_and_unapproved(self):
        for language in PROFILES:
            with self.subTest(language=language):
                pack = localized_pack(language)
                self.assertEqual(pack["language"], language)
                self.assertEqual(pack["approval"]["status"], "draft")
                self.assertEqual(pack["translation_review"], "pending_native_speaker_review")
                self.assertEqual([c["id"] for c in pack["clauses"]], ["contribution", "early_exit", "returns", "cancellation"])
                for clause in pack["clauses"]:
                    self.assertEqual(len(clause["must_have_facts"]), 2)
                    self.assertTrue(clause["critical"])
                    for key in ["title", "explain", "question", "fallback_explain", "misconceptions"]:
                        self.assertTrue(clause[key])

    def test_translated_speech_and_matching_voice_for_every_state(self):
        for language, profile in PROFILES.items():
            with self.subTest(language=language), tempfile.TemporaryDirectory() as d:
                pack = localized_pack(language)
                c = Conversation(pack, d, "indic-auto", language, profile["voice"])
                tts = Mock(return_value=b"RIFF_test")
                c.speak(tts)
                text = tts.call_args.args[0]
                self.assertIn(pack["disclosure"], text)
                self.assertIn(pack["clauses"][0]["question"], text)
                self.assertEqual(tts.call_args.kwargs, {"language": language, "voice": profile["voice"]})
                for verdict in ("partial", "misunderstood", "no_evidence"):
                    c.history = [{"verdict": verdict}]
                    c.session.attempt = 2
                    self.assertIn(pack["messages"][verdict], c.speech_text())
                    self.assertIn(pack["clauses"][0]["fallback_explain"], c.speech_text())
                c.session.status = "human_review"
                self.assertEqual(c.speech_text(), pack["messages"]["human_review"])
                c.session.status = "demo_checks_passed"
                self.assertEqual(c.speech_text(), pack["messages"]["complete"])

    def test_kannada_has_no_hindi_script_in_any_spoken_field(self):
        pack = localized_pack("kn-IN")
        texts = [pack["disclosure"], *pack["messages"].values()]
        for clause in pack["clauses"]:
            texts.extend(clause[k] for k in ("explain", "question", "fallback_explain"))
        for text in texts:
            self.assertTrue(any('\u0c80' <= char <= '\u0cff' for char in text))
            self.assertFalse(any('\u0900' <= char <= '\u097f' for char in text))

    def test_language_mismatch_is_rejected(self):
        with tempfile.TemporaryDirectory() as d:
            with self.assertRaises(ValueError):
                Conversation(localized_pack("kn-IN"), d, tts_language="hi-IN")

    def test_auto_input_cannot_change_marathi_feedback_after_actual_assessment(self):
        import io
        import wave
        from engine.scorer import fixture_evidence
        buffer = io.BytesIO()
        with wave.open(buffer, "wb") as wav:
            wav.setnchannels(1)
            wav.setsampwidth(2)
            wav.setframerate(16000)
            wav.writeframes(b"\0\0" * 16000)
        pack = localized_pack("mr-IN")
        with tempfile.TemporaryDirectory() as d:
            c = Conversation(pack, d, "indic-auto", "mr-IN", "Ishaan")
            stt = Mock(return_value={"transcript": "गलत उत्तर", "detected_language_code": "hi-IN"})
            scorer = Mock(return_value=fixture_evidence(c.session.clause, "misconception")[1])
            self.assertTrue(c.receive(buffer.getvalue(), stt, scorer))
            c.feedback = "Shayad meri explanation clear nahi thi."
            tts = Mock(return_value=b"RIFF_test")
            c.speak(tts)
            text = tts.call_args.args[0]
            self.assertTrue(text.startswith(pack["messages"]["misunderstood"]))
            self.assertIn(pack["clauses"][0]["explain"], text)
            self.assertNotIn("Shayad", text)
            self.assertEqual(tts.call_args.kwargs["language"], "mr-IN")
            self.assertEqual(tts.call_args.kwargs["voice"], "Ishaan")

    def test_legacy_messages_resolve_in_selected_speaking_language(self):
        pack = localized_pack("mr-IN")
        del pack["messages"]
        with tempfile.TemporaryDirectory() as d:
            c = Conversation(pack, d, "indic-auto", "mr-IN", "Ishaan")
            c.history = [{"verdict": "misunderstood"}]
            c.session.attempt = 1
            self.assertTrue(c.speech_text().startswith(localized_pack("mr-IN")["messages"]["misunderstood"]))
