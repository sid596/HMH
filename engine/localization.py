"""Reviewed-in-code routing; translated content remains human-review-pending data."""
from pathlib import Path
from engine.core import load_pack

PROFILES = {
    "hi-IN": {"label": "Hindi", "voice": "Yashvi", "persona": "Warm, empathetic"},
    "hi-en": {"label": "Hinglish", "voice": "Poorvi", "persona": "Conversational"},
    "en-IN": {"label": "English", "voice": "Pranav", "persona": "Friendly"},
    "mr-IN": {"label": "Marathi", "voice": "Ishaan", "persona": "Professional, clear instructions"},
    "kn-IN": {"label": "Kannada", "voice": "Kavin", "persona": "Professional, articulate"},
}


def localized_pack(language):
    if language not in PROFILES:
        raise ValueError("No reviewed routing profile for this language")
    path = Path(__file__).resolve().parents[1] / "packs" / f"fictional_savings_v1_{language}.json"
    pack = load_pack(path)
    if pack.get("language") != language:
        raise ValueError("Rubric language does not match selected speaking language")
    required = {"understood", "partial", "misunderstood", "no_evidence", "human_review", "complete"}
    if set(pack.get("messages", {})) != required or not all(pack["messages"].values()):
        raise ValueError("Translated conversation messages are incomplete")
    return pack
