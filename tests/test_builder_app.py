from pathlib import Path
import unittest
from streamlit.testing.v1 import AppTest

APP = str(Path(__file__).resolve().parents[1] / "app/main.py")

class BuilderAppTests(unittest.TestCase):
    def test_plus_changes_preview_and_saved_pack_is_used_by_conversation(self):
        app = AppTest.from_file(APP).run()
        self.assertFalse(app.exception)
        self.assertEqual([m.value for m in app.metric], ["4", "2", "2"])
        next(b for b in app.button if b.label == "+").click().run()
        self.assertEqual([m.value for m in app.metric], ["4", "3", "1"])
        next(t for t in app.text_input if t.label == "Reviewer name").set_value("Demo reviewer").run()
        self.assertFalse(any("reason" in t.label.lower() for t in app.text_input))
        next(c for c in app.checkbox if c.label == "I reviewed the source, wording and exclusions.").check().run()
        next(b for b in app.button if b.label == "Save reviewed demo pack").click().run()
        self.assertFalse(app.exception)
        self.assertEqual(len(app.session_state.compiled_pack["clauses"]), 3)
        next(b for b in app.button if b.label == "Open voice verification →").click().run()
        self.assertFalse(app.exception)
        self.assertEqual(next(s for s in app.selectbox if s.label == "Speaking language").value, "en-IN")
        self.assertEqual(next(s for s in app.selectbox if s.label == "Verification pack").value, "My reviewed demo pack")
        next(s for s in app.selectbox if s.label == "Assessment mode").select("Scripted walkthrough").run()
        next(b for b in app.button if b.label == "Start disclosed demo session").click().run()
        self.assertFalse(app.exception)
        self.assertEqual(len(app.session_state.session.pack["clauses"]), 3)
        self.assertEqual(app.session_state.session.pack["review_record"]["reviewer"], "Demo reviewer")

    def test_assisted_transcript_review_can_be_applied_without_manual_json_copy(self):
        import os
        from unittest.mock import patch
        raw={'sha256':'review-fixture','segments':[{'start_seconds':0,'end_seconds':2,'speaker':'unknown','text':'Do I get a refund?'}]}
        proposal={'segments':[{'start_seconds':0,'end_seconds':2,'speaker':'customer','text':'Do I get a refund?','raw_text':'Do I get a refund?','source_segment_index':0,'review_note':'Question','role_origin':'model_suggestion'}],'raw_transcript':raw,'review_required':True}
        with patch.dict(os.environ,{'SCORER_API_KEY':'test-key','SCORER_MODEL':'test-model'}):
            app=AppTest.from_file(APP).run()
            app.session_state.prior_transcript=raw
            app.session_state.transcript_suggestions=proposal
            app.run()
            next(c for c in app.checkbox if c.key=='call_context_permission').check().run()
            self.assertFalse(app.exception)
            next(c for c in app.checkbox if c.label=='I checked these suggested edits and speaker labels against the recording.').check().run()
            next(b for b in app.button if b.label=='Apply reviewed suggestions').click().run()
            self.assertFalse(app.exception)
            self.assertEqual(app.session_state.prior_transcript['segments'][0]['speaker'],'customer')
            self.assertEqual(app.session_state.prior_transcript['raw_transcript'],raw)
