# HMH outbound phone verification

This is a separate, single-worker FastAPI backend. Streamlit is the review/call-control UI; it cannot itself serve the Twilio answer and recording callbacks.

## Current Twilio trial restriction

Twilio's [current Voice trial documentation](https://www.twilio.com/docs/usage/trials/try-out-voice) explicitly blocks `<Record>` and `<Stream>`. This backend uses `<Record>` to obtain answer audio for Prisma. It checks the account type and refuses trial calls before dialling. No code bypasses that restriction or upgrades the account. An account with the required features enabled and a permitted caller number is needed. Destination permissions and account/number availability still apply.

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

- The server prepares the opening disclosure/question and a localized waiting message using Timbre **before** calling. It calls only the configured test destination.
- The signed answer webhook returns `<Play>` with Timbre WAV audio followed by `<Record>` (25-second maximum, 3-second silence timeout, `#` to finish). A recording disclosure is spoken first. This is turn-based: interrupting the assistant is not implemented.
- The record action moves the caller into a waiting loop. The separate `recordingStatusCallback` triggers work only when the recording is available, as required by [Twilio's Record guidance](https://www.twilio.com/docs/voice/twiml/record).
- A worker fetches audio from a reconstructed Twilio recording URL using account authentication, sends it to Prisma, scores the transcript, applies the Python policy, and prepares the next Timbre response. Twilio's own speech-to-text is not used.
- Questions/retries share a total budget of 15 answer turns. Exhaustion stops with human review, rather than pretending unasked topics passed. A call also has a 15-minute provider time limit.
- Failed audio/assessment routes to human review or ends the call. It never accepts consent. The final outcome remains the pack's demo/check result, not legal consent certification.
- **Refresh call status** shows progress; **End test call** requests hangup. An uncertain network error must be checked in Twilio before redialling.

## Protections and limits

Call-control endpoints require a strong bearer token. Webhooks validate Twilio signatures, configured account and call IDs; media URLs use expiring per-call tokens. No CORS-based public browser dialling API is enabled. Creation IDs and recording SIDs are deduplicated; the backend permits one active test call and at most six creations per hour. Basic account-type readiness is cached for 60 seconds. SDK/worker tasks do not automatically retry billable call creation.

This is a single-process prototype with in-memory call state and local audit JSONL under `data/phone/`. Restarting during a call loses routing state; use the provider console/handset to end a call if the process is unavailable. Access controls, retention, reviewer roles, durable job storage, interruption handling and production capacity need further work. Twilio stores answer recordings under your account; configure/delete them using provider retention controls. HMH does not start a separate full-call recording.

The call workflow was tested with mocked provider/model/audio services, including signature checks, callback deduplication, failure-before-dial, trial rejection and question-budget exhaustion. No real outbound phone call has been verified yet.
