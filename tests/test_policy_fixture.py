import json
from pathlib import Path
import re
import unittest
from engine.pack_builder import extract_document, chunks

ROOT = Path(__file__).resolve().parents[1]

class PolicyFixtureTests(unittest.TestCase):
    def test_fixture_is_readable_and_clause_sources_match_inventory(self):
        path = ROOT / "output/pdf/nivara_clearcare_fictional_policy.pdf"
        document = extract_document(path.read_bytes(), path.name)
        inventory = json.loads((path.parent / "nivara_clearcare_clause_inventory.json").read_text())
        self.assertEqual(len(document["pages"]), 8)
        combined = "\n".join(p["text"] for p in document["pages"])
        self.assertEqual(len(re.findall(r"Clause \d\d \|", combined)), 32)
        for clause in inventory["clauses"]:
            self.assertIn("Clause " + clause["clause_id"] + " |", document["pages"][clause["page"] - 1]["text"])
        # This fixture previously placed over 15 clauses in one generation call,
        # exceeding the topic generator's response limit before review could begin.
        for batch in chunks(document):
            count = sum(len(re.findall(r"Clause \d\d \|", p["text"])) for p in batch)
            self.assertLessEqual(count, 15)
