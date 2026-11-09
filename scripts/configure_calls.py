"""Configure outbound testing locally without echoing credentials or phone numbers."""
from getpass import getpass
import json
import os
from pathlib import Path
import secrets

path=Path(__file__).resolve().parents[1]/".hmh-secrets.json"
config=json.loads(path.read_text()) if path.exists() else {}
for name,label in [("TWILIO_ACCOUNT_SID","Twilio Account SID"),("TWILIO_AUTH_TOKEN","Twilio Auth Token"),
                   ("TWILIO_FROM_NUMBER","Twilio-permitted caller number, including +country code"),
                   ("TWILIO_TO_NUMBER","Your verified test mobile number, including +country code")]:
    value=getpass(label+" (blank keeps existing): ").strip()
    if value:config[name]=value
url=input("Public HTTPS origin for the call server (ngrok/hosted backend; blank keeps existing): ").strip().rstrip('/')
if url:config["HMH_PUBLIC_BASE_URL"]=url
api=input("Call API URL used by this local Streamlit app [http://127.0.0.1:8000]: ").strip()
config["HMH_CALL_API_URL"]=api or "http://127.0.0.1:8000"
config.setdefault("HMH_CALL_API_TOKEN",secrets.token_urlsafe(40))
fd=os.open(path,os.O_WRONLY|os.O_CREAT|os.O_TRUNC,0o600)
os.chmod(path,0o600)
with os.fdopen(fd,"w") as f:json.dump(config,f)
print("Call settings saved locally. No call was placed. Restart Streamlit and the call backend to load them.")
print("For Streamlit Cloud, privately copy only HMH_CALL_API_URL (your public backend URL) and HMH_CALL_API_TOKEN into its Secrets.")
