# HMH outbound phone verification

This is a separate, single-worker FastAPI backend. Streamlit is the review/call-control UI; it cannot itself serve the Twilio answer and recording callbacks.

## Phone speech recognition

Default `PHONE_STT_MODE=gather`: Twilio Gather transcribes customer speech; Timbre generates the voice; HMH assesses transcripts against the reviewed pack. No Prisma or answer-audio recording is used on this phone path. Browser microphone and optional prior-call uploads still use Prisma. Set `PHONE_STT_MODE=prisma_record` only on an account with Record enabled to use the original audio path.

Twilio's trial supports Gather and Play but restricts routing and call creation, 10-minute calls, 75 total minutes and 10 action/redirect hops. Trial packs are capped at 3 topics. Waiting polls also consume hops; the backend stops for human review before its conservative 8-hop budget is exhausted. This is implementation against documented capabilities, not a verified live trial call. The trial documentation also lists restricted call-creation templates, so account acceptance of our custom answer URL must be tested before claiming the phone demo works.

## Local setup

1. Install the phone server dependencies alongside the app:

   ```sh
   .venv/bin/python -m pip install -r requirements-call.txt
   ```

2. Expose local port 8000 using a public HTTPS tunnel, for example your configured ngrok account:

   ```sh
   ngrok http 8000
   ```

   Note the HTTPS origin displayed by ngrok. An ngrok account/token may be needed; use the official CLI's account setup. Keep the tunnel running.

3. Run the local-only setup helper:

   ```sh
   .venv/bin/python scripts/configure_calls.py
   ```

   Supply the Twilio Account SID, Auth Token, a Twilio-permitted `From` number, your test mobile as `To` in international format, and the public HTTPS origin from step 2. The helper keeps phone numbers/credentials hidden during input and creates a strong call-control token. These go only into ignored `.hmh-secrets.json`, not GitHub. Existing Gnani/scorer settings remain intact. No call is placed by configuration.

4. Start/restart the backend with one worker:

   ```sh
   .venv/bin/python -m uvicorn telephony.server:app --host 127.0.0.1 --port 8000 --workers 1 --no-access-log
   ```

5. Refresh/restart Streamlit if needed. Build a pack of at most 15 questions, record the review, and save it. Expand **Call my test phone** and inspect backend readiness. Only the explicit call button starts preparation and dialling. The destination is fixed in the backend configuration; public visitors cannot choose arbitrary phone numbers. Keep private access to the app/call-control token.

6. If your Streamlit app runs in Community Cloud, set `HMH_CALL_API_URL` to the public backend HTTPS origin and set `HMH_CALL_API_TOKEN` to the same token as the backend. `127.0.0.1` on Streamlit Cloud is not your laptop. Keep Twilio credentials on the backend. The laptop and tunnel must stay online, or host the backend on a service that supports a persistent Python process.

The frontend checks the protected backend `/health` endpoint. It reports missing settings, invalid configuration and the trial restriction. Changing a tunnel URL requires updating `HMH_PUBLIC_BASE_URL` and restarting the backend. When using Streamlit Cloud also update its `HMH_CALL_API_URL`.

## How the call works

The backend prepares opening audio with a short answer instruction before dialling. It plays Timbre audio, then Gather listens for speech in the pack language (Hinglish uses Hindi recognition). Pause for 3 seconds to finish an answer. An empty transcript ends in human review. A signed, turn-specific callback returns waiting instructions immediately, while a worker scores the transcript and prepares Timbre audio. Duplicate/stale callbacks do not rescore. Twilio recognition confidence is logged as provider metadata, not treated as customer understanding. The prototype is turn-based, without interruption support.

The optional `prisma_record` mode retains Record/Prisma callbacks and is rejected on trial accounts. Failure, silence, processing timeout, question exhaustion or trial-hop exhaustion never counts as a pass. Call status is available through the protected API and frontend refresh button. No live call has been verified yet.

## Protections and limits

Call-control endpoints require a strong bearer token. Webhooks validate Twilio signatures, configured account and call IDs. Unsigned trial callbacks require a random per-call URL capability, an already bound CallSid, matching account/call IDs and a 30-minute expiry; invalid supplied signatures never fall back. Treat callback URLs as secrets. media URLs use expiring per-call tokens. No CORS-based public browser dialling API is enabled. Creation IDs and recording SIDs are deduplicated; the backend permits one active test call and at most six creations per hour. Basic account-type readiness is cached for 60 seconds. SDK/worker tasks do not automatically retry billable call creation.

This is a single-process prototype with in-memory call state and local audit JSONL under `data/phone/`. Restarting during a call loses routing state; use the provider console/handset to end a call if the process is unavailable. Access controls, retention, reviewer roles, durable job storage, interruption handling and production capacity need further work. Twilio stores answer recordings under your account; configure/delete them using provider retention controls. HMH does not start a separate full-call recording.

The call workflow was tested with mocked provider/model/audio services, including signature checks, callback deduplication, failure-before-dial, trial rejection and question-budget exhaustion. No real outbound phone call has been verified yet.

Phone calls omit the long spoken synthetic/demo disclosure and use brief closing messages. The frontend retains transcription/provider details and explicit call consent. Original pack text remains in the audit snapshot; spoken message overrides are logged separately. Browser voice keeps its existing disclosure. Provider-inserted trial announcements are outside HMH control.
