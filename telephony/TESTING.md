# Phone demo test plan

## First live smoke test

1. Run `.venv/bin/python -m unittest discover -s tests -v`.
2. Restart the single-worker backend; keep ngrok forwarding port 8000. No code test initiates a real call.
3. Use Gather mode (default). Save a reviewed synthetic pack with 1 topic in English. Confirm the configured destination is your own test phone and trial-verified. Inspect backend readiness.
4. Explicitly click Call my test phone once. Check Twilio logs if no ring; do not repeat calls on uncertain creation responses. A trial may reject our custom answer URL or caller number; preserve the numeric provider error. Do not assume an API health check verifies routing.
5. On Android, answer with all required facts. Check transcript, exact amounts/negation, verdict and closing audio. Repeat on iPhone after configuring the intended destination locally and restarting the backend.
6. Test a wrong amount, a partial answer, only "yes", and silence. None should produce a false pass. Inspect logged `twilio_gather` source and no Prisma transcription requests.

## Language/understanding matrix

For English, Hindi, Marathi and Kannada, native reviewers prepare expected answers before testing. Start with 1 topic; expand to 2–3 only after a clean call. For each language test: complete paraphrase, partial facts, explicit misconception, negation, just agreement, off-topic answer, numerical mistake, code mixing, and silence. Test quiet rooms first, then speakerphone, normal background noise and weak connectivity. Language recognition is set per pack; automatic multilingual recognition is not promised.

Record case ID, pack/version, language, device, expected facts/verdict, actual transcript, actual verdict, time from end of speech to response, callback hops, call termination, and reviewer notes. Distinguish transcription errors from assessment errors by comparing the spoken answer, transcript and rubric. Since Gather mode provides no source audio recording, use contemporaneous reviewer notes; independently recording a synthetic test requires participants' agreement.

## Gates

A misunderstood critical fact must never pass in the planned test set. Every intentional silence/failure must stop or require review. Duplicated callbacks must cause exactly one assessment; terminal calls must not restart. Measure recognition errors separately for amounts, durations and negation; report p50/p95 response delay only after enough samples. Do not claim production reliability from a few successful calls. Use mocked/recorded-text cases for broad regression coverage and spend limited trial minutes on representative end-to-end cases. Trial hops include waiting redirects, so slow model calls can exhaust the limit before all topics are asked.

## Previous sales-call recording

Optional context only: useful to identify confusion, material statements and explicitly stated customer language. It does not establish policy truth, consent or comprehension. The approved policy and selected rubric remain authoritative. Verification works without a previous recording. In a future contact-center integration, authorised transcript/context can be passed automatically; the current demo uses optional upload.
