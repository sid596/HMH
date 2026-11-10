"""Load local credentials without printing them. Cloud secrets remain environment variables."""
import json
import os
from pathlib import Path

KEYS = {"GNANI_API_KEY","SCORER_API_KEY","SCORER_MODEL","SCORER_BASE_URL",
        "TWILIO_ACCOUNT_SID","TWILIO_AUTH_TOKEN","TWILIO_FROM_NUMBER","TWILIO_TO_NUMBER",
        "HMH_PUBLIC_BASE_URL","HMH_CALL_API_URL","HMH_CALL_API_TOKEN","DOCUMENT_REASONING_EFFORT","DOCUMENT_WORKERS","PHONE_STT_MODE"}


def load_local_settings():
    path=Path(__file__).resolve().parents[1]/".hmh-secrets.json"
    if path.exists():
        for key,value in json.loads(path.read_text()).items():
            if key in KEYS and isinstance(value,str):
                os.environ.setdefault(key,value)
