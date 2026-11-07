"""Smoke-test both safe demo outcomes without making network calls."""
import unittest
from pathlib import Path
from streamlit.testing.v1 import AppTest

class AppTests(unittest.TestCase):
    def test_scripted_happy_path(self):
        app = AppTest.from_file(str(Path(__file__).resolve().parents[1] / "app/main.py")).run()
        self.assertEqual(len(app.exception), 0)
        next(b for b in app.button if b.label == "Start disclosed demo session").click().run()
        for _ in range(4):
            next(s for s in app.selectbox if s.label == "Synthetic response").select("attentive").run()
            next(b for b in app.button if b.label == "Run scripted assessment").click().run()
        self.assertEqual(len(app.exception), 0)
        self.assertIn("Demo teach-back checks passed", app.success[0].value)

    def test_scripted_nodding_stops(self):
        app = AppTest.from_file(str(Path(__file__).resolve().parents[1] / "app/main.py")).run()
        next(b for b in app.button if b.label == "Start disclosed demo session").click().run()
        for _ in range(3):
            next(b for b in app.button if b.label == "Run scripted assessment").click().run()
        self.assertEqual(len(app.exception), 0)
        self.assertIn("Human review required", app.error[0].value)
