"""Interactive local-only credentials setup; never prints keys."""
from getpass import getpass
import json
import os
from pathlib import Path

path = Path(__file__).resolve().parents[1] / ".hmh-secrets.json"
config = json.loads(path.read_text()) if path.exists() else {}
for name, label in [("GNANI_API_KEY", "Gnani API key"), ("SCORER_API_KEY", "Text model API key")]:
    value = getpass(f"{label} (blank keeps existing): ")
    if value:
        config[name] = value
config["SCORER_MODEL"] = input(f"Model [{config.get('SCORER_MODEL', 'gpt-5.4-mini')}]: ").strip() or config.get("SCORER_MODEL", "gpt-5.4-mini")
config["SCORER_BASE_URL"] = input(f"Base URL [{config.get('SCORER_BASE_URL', 'https://api.openai.com/v1')}]: ").strip() or config.get("SCORER_BASE_URL", "https://api.openai.com/v1")
fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
os.chmod(path, 0o600)
with os.fdopen(fd, "w") as f:
    json.dump(config, f)
print("Saved credentials locally. Keys were not printed. Restart the app to load them.")
