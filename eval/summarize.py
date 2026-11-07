"""Summarize answer-level decisions with explicit denominators, including API errors."""
import json
import sys
from pathlib import Path

rows = [json.loads(line) for line in Path(sys.argv[1]).read_text().splitlines()]
unsafe = [r for r in rows if r["human_verdict"] in {"misunderstood", "no_evidence"}]
understood = [r for r in rows if r["human_verdict"] == "understood"]
print(json.dumps({
    "total_answers": len(rows),
    "false_acceptances": sum(r["accepted"] for r in unsafe),
    "false_acceptance_denominator": len(unsafe),
    "understood_not_accepted": sum(not r["accepted"] for r in understood),
    "understood_denominator": len(understood),
    "api_or_validation_errors": sum("error_type" in r for r in rows),
    "limitation": "Answer-level only. Not-accepted includes retry/escalation/errors; not final session rejection."
}, indent=2))
