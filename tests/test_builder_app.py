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
        next(t for t in app.text_input if t.label.startswith("Reason to exclude:")).set_value("Covered in a separate demo step").run()
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
