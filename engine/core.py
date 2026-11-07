"""Semantic evidence is supplied by a scorer; every pass decision stays here."""
from dataclasses import asdict, dataclass
import hashlib
import json
import os
from pathlib import Path
from datetime import datetime, timezone
import uuid

VERDICTS = {"understood", "partial", "misunderstood", "no_evidence"}
MIN_CONFIDENCE = 0.85
MAX_RETRIES = 2


def utc_now():
    return datetime.now(timezone.utc).isoformat()


def load_pack(path):
    pack = json.loads(Path(path).read_text())
    assert pack["synthetic"] is True, "Demo packs must be synthetic"
    ids = [c["id"] for c in pack["clauses"]]
    assert ids and len(ids) == len(set(ids)), "Clause IDs must be unique"
    for c in pack["clauses"]:
        assert c["must_have_facts"] and c["question"] and c["fallback_explain"]
    return pack


def pack_hash(pack):
    return hashlib.sha256(json.dumps(pack, sort_keys=True, ensure_ascii=False).encode()).hexdigest()


@dataclass(frozen=True)
class Evidence:
    facts_present: list[int]
    facts_missing: list[int]
    misconception_detected: bool
    verdict: str
    confidence: float
    rationale: str

    @classmethod
    def validate(cls, raw, clause):
        if set(raw) != set(cls.__dataclass_fields__):
            raise ValueError("Scorer output has missing or unexpected fields")
        if raw["verdict"] not in VERDICTS:
            raise ValueError("Unknown verdict")
        confidence = raw["confidence"]
        if type(confidence) not in (int, float) or not 0 <= confidence <= 1:
            raise ValueError("Invalid confidence")
        if type(raw["misconception_detected"]) is not bool or not isinstance(raw["rationale"], str):
            raise ValueError("Invalid evidence types")
        universe = set(range(len(clause["must_have_facts"])))
        for key in ("facts_present", "facts_missing"):
            values = raw[key]
            if not isinstance(values, list) or any(type(i) is not int for i in values) or len(set(values)) != len(values):
                raise ValueError("Fact indices must be unique integers")
        present, missing = set(raw["facts_present"]), set(raw["facts_missing"])
        if present & missing or present | missing != universe:
            raise ValueError("Every fact must be classified exactly once")
        # Derive verdict from evidence, rejecting internally inconsistent output.
        derived = ("misunderstood" if raw["misconception_detected"] else
                   "understood" if not missing else "partial" if present else "no_evidence")
        if raw["verdict"] != derived:
            raise ValueError("Verdict contradicts fact evidence")
        return cls(**raw)


def decide(evidence, critical, attempt):
    if evidence.confidence < MIN_CONFIDENCE:
        return "escalate"
    if evidence.verdict == "understood":
        return "pass"
    if not critical and evidence.verdict == "partial":
        return "pass"
    return "retry" if attempt <= MAX_RETRIES else "escalate"


class AuditLog:
    """Local append-only writer with a hash chain; not immutable/WORM storage."""
    def __init__(self, directory, session_id=None):
        self.session_id = session_id or uuid.uuid4().hex
        self.path = Path(directory) / f"{self.session_id}.jsonl"
        self.path.parent.mkdir(parents=True, exist_ok=True)

    def append(self, event, **payload):
        previous = "0" * 64
        if self.path.exists():
            previous = json.loads(self.path.read_text().splitlines()[-1])["hash"]
        record = {"session_id": self.session_id, "timestamp": utc_now(), "event": event,
                  "payload": payload, "previous_hash": previous}
        record["hash"] = hashlib.sha256(json.dumps(record, sort_keys=True, ensure_ascii=False).encode()).hexdigest()
        with self.path.open("a") as f:
            f.write(json.dumps(record, ensure_ascii=False) + "\n")
        return record

    def records(self):
        return [json.loads(line) for line in self.path.read_text().splitlines()]


class Session:
    def __init__(self, pack, directory, mode):
        self.pack, self.mode = pack, mode
        self.audit = AuditLog(directory)
        self.index, self.attempt = 0, 0
        self.status, self.results = "active", []
        self.audit.append("session_started", pack_version=pack["pack_version"], pack_hash=pack_hash(pack),
                          pack_snapshot=pack, mode=mode, disclosure=pack["disclosure"],
                          scorer_model=os.getenv("SCORER_MODEL") if mode == "live" else "scripted_fixture",
                          scorer_prompt_version="teachback-2-multilingual", policy_version="policy-1")
        self.prompt()

    @property
    def clause(self):
        return self.pack["clauses"][self.index]

    def prompt(self):
        c = self.clause
        explanation = c["fallback_explain"] if self.attempt >= 2 else c["explain"]
        self.audit.append("prompt", clause_id=c["id"], explanation=explanation, question=c["question"])

    def submit(self, answer, evidence, source="typed", transcript_metadata=None):
        if self.status != "active" or not answer.strip():
            raise ValueError("An active session and a nonempty answer are required")
        self.attempt += 1
        action = decide(evidence, self.clause["critical"], self.attempt)
        self.audit.append("assessment", clause_id=self.clause["id"], attempt=self.attempt,
                          answer=answer, input_source=source, transcript_metadata=transcript_metadata,
                          evidence=asdict(evidence), action=action)
        if action == "retry":
            self.prompt()
        elif action == "escalate":
            self.status = "human_review"
            self.audit.append("session_finished", status=self.status)
        else:
            self.results.append(self.clause["id"])
            self.index += 1
            self.attempt = 0
            if self.index == len(self.pack["clauses"]):
                approved = self.pack["approval"]["status"] == "approved"
                self.status = "checks_passed" if approved and self.mode == "live" else "demo_checks_passed"
                self.audit.append("session_finished", status=self.status,
                                  limitation="Evidence of teach-back only; not proof of understanding or legal consent.")
            else:
                self.prompt()
        return action
