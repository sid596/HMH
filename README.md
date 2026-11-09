# Haan Matlab Haan

A local multilingual teach-back verification prototype for a fictional savings product. Intended buyer: a lender/insurer's compliance or risk team running post-sale verification. It records evidence of what a customer could explain and routes unresolved confusion to human review. It cannot prove understanding or certify legal consent.

## Run

Python 3.11+:

```sh
python3 -m venv .venv
source .venv/bin/activate
python -m pip install -r requirements.txt
streamlit run app/main.py
```

Voice conversation is the default. Click **Start conversation**, listen to the selected voice, tap the microphone to record, and stop when finished. Prisma transcription, rubric assessment, and the next spoken response run automatically. Recordings longer than 30 seconds are rejected locally. Separate listening and speaking language settings allow auto-detection for Prisma while Timbre uses a supported voice/language pair. Browser autoplay policies may require pressing play once.

Scripted walkthrough is available in the sidebar and works without keys. It exercises the flow with predefined evidence and is explicitly not a semantic assessment. Choose the nodding persona to see retries and escalation; attentive passes all demo checks.

For live requests, run `python scripts/configure.py` in your terminal. It prompts for keys without displaying them and saves `.hmh-secrets.json` locally with owner-only permissions, ignored by Git. The app loads it on launch. Never share that file.

Recommended starting scorer: `gpt-5.4-mini` (subject to your account access), supported on Chat Completions with structured outputs according to [official OpenAI documentation](https://developers.openai.com/api/docs/models/gpt-5.4-mini). Validate Hindi–English quality on human-labelled samples before relying on it. Create a project API key using the [OpenAI quick start](https://developers.openai.com/api/docs/quickstart); provider billing/credits are separate from Gnani credits.

Alternatively set environment variables before launching Streamlit:

```sh
export GNANI_API_KEY='your-local-key'
export SCORER_API_KEY='your-local-scorer-key'
export SCORER_MODEL='your-provider-model-id'
# Optional OpenAI-compatible provider:
export SCORER_BASE_URL='https://api.openai.com/v1'
```

`.env.example` documents variable names; the app does not automatically load `.env`. Never commit keys. Live semantic scoring needs a separate compatible model provider; Gnani challenge credits do not imply access to that provider. Evon hosting is not implemented.

The browser microphone is for synthetic scripted speech only. Live flow: Timbre speaks the prompt → record a fictional customer's teach-back → Prisma transcribes → semantic scorer extracts rubric evidence → plain Python policy passes/retries/escalates. API failures never record a pass. Each new recording triggers one assessment automatically. Failed requests require an explicit retry; a scorer retry reuses a successful transcript. UI reruns do not automatically retry failed API calls. Timbre audio is reused within each turn. Voice-language compatibility must be checked against the account's voice catalog.

## Policy and review

Four critical clauses, two retries per clause. The second retry uses a simpler explanation. All required facts must be present without contradiction. A provisional self-reported scorer confidence below 0.85 routes to human review immediately. This threshold is uncalibrated. Partial understanding never passes a critical clause.

`packs/fictional_savings_v1.json` is a DRAFT. Both teammates should review every invented term, fact, misconception and Hindi–English script. Record reviewer and timestamp and increment the version only after review; the app never approves it itself. Draft sessions end in `demo_checks_passed`, never a legal-consent claim.

Audit JSONL files in `data/` contain prompts, answers, evidence, decisions, timestamps, pack version/hash/snapshot and linked event hashes. The writer appends; storage is local and mutable. No authentication, durable multi-user store, concurrency protection or production retention policy is implemented. Keep the server local.

## Verify

```sh
python -m unittest discover -s tests -v
```

See `eval/README.md` for human labelling and baseline-first evaluation. No real accuracy numbers have been collected. Policy tests and scripted examples are not model evaluation.

## Challenge references (checked November 7, 2026)

- [Official challenge](https://www.gnani.ai/internship): November 10, 2026 at 11:59 PM IST; one team entry; synthetic data; public demo post before submission; name each contribution and Gnani models used.
- [Gnani quick start](https://docs.gnani.ai/api/introduction/quick-start): REST Prisma v3.0 transcription and Timbre v2.5 synthesis adapters.

Real API response shape, account model access, credit cost and scorer quality remain unverified until keys are configured and live probes run. `ffmpeg` was not installed at setup; this comprehension prototype does not need it.

## Streamlit Cloud keys

Add these top-level values in the app settings → Secrets (never commit actual keys):

```toml
GNANI_API_KEY = "your-gnani-key"
SCORER_API_KEY = "your-text-model-key"
SCORER_MODEL = "gpt-5.4-mini"
SCORER_BASE_URL = "https://api.openai.com/v1"
```

Restart after configuration. The voice Start button stays disabled until all required values are present. Tests mock speech/scorer calls; browser microphone, autoplay, real API access and semantic accuracy still require a live check.

## Language packs and automatic voices

Speaking language loads a complete saved rubric from `packs/fictional_savings_v1_<language>.json`, including explanations, questions, simpler fallbacks, required facts, misconceptions, disclosure, feedback and endings. The same localized rubric is passed to the scorer and saved in the audit snapshot. Pack versions include the language. No live translation request is made.

| Language | Timbre v2.5 voice | Selection rationale |
|---|---|---|
| Hindi | Yashvi | Warm, empathetic |
| Hinglish | Poorvi | Conversational bilingual voice |
| English | Pranav | Friendly |
| Marathi | Ishaan | Professional, clear instructions |
| Kannada | Kavin | Professional, articulate |

Routing follows the [Gnani voice catalog](https://docs.gnani.ai/api/TTS/available-voices), checked November 7, 2026. These are catalog-based defaults, not a listening evaluation of the voices. Each translation is a draft pending native-speaker review of meaning, naturalness and spoken numbers. Hindi, Marathi and Kannada scripts use their native writing systems. Hinglish intentionally mixes Hindi and English. The original pack remains available for older tests and evaluations.

Listening language is independent: it tells Prisma how to transcribe the customer's answer. It does not translate prompts. Reset a session to change speaking language; active sessions keep their selected pack and voice. To test Kannada, reset, select Kannada as speaking language, then choose Kannada or auto-detect for listening.

## PDF topic-review workspace

The app opens on **Build a verification pack**. The example product is explicitly a prewritten fixture: four synthetic topics with two example required topics. Use `+` to add a topic, expand its source/rubric, search or filter the library, and record a reason for each omission. Enter a reviewer name, attest to reviewing the content, and save a demo pack. **Open voice verification** selects that pack and its matching language/voice. Resetting the call preserves your builder state.

For PDF generation choose **Upload synthetic PDF**, choose the output language, upload a text PDF, confirm synthetic data, then click **Generate topic library**. Text is sent to the configured semantic-model provider using the same SCORER settings. The UI displays the number of chunk requests before generation. There are no automatic retries. No Gnani credits are used for document generation.

- Limits: 20 MB, 300 pages, 1.5 million extracted characters. OCR is not included; unreadable pages block generation rather than being silently omitted.
- Each generated topic needs a verbatim quote and physical PDF page number. Code checks quote presence, not whether the model's interpretation is correct. Topics remain machine drafts pending review.
- All text chunks are processed; extraction is not guaranteed exhaustive. Exact duplicate topic/source combinations are removed, but a human must review overlap across chunks.
- Unresolved model-reported details prevent creating a runnable pack. Export the library to review those issues and supply a corrected/complete synthetic source before regenerating.
- Required core topics are configured only for the built-in example. Uploaded PDFs have model-suggested risk labels, not an organisation-approved core. The generator cannot declare a topic mandatory.
- Review identity is self-attested. No reviewer roles/authentication are enforced. Exported packs stay `draft` and never certify legal consent.
- Saved packs include selected clauses, the full topic catalog, exclusion reasons, source document hash, model/prompt version, reviewer and timestamp. The session's audit log includes the pack snapshot. Storage in `data/packs/` and browser session state is local/ephemeral on cloud restarts; download packs and libraries to retain them. This prototype does not reload saved packs after a server restart.

Run `python -m unittest discover -s tests -v` for policy, language, quote validation, selection and UI workflow tests. Live PDF-to-topic model quality and actual voice pronunciation require human evaluation; tests do not measure either.

## Fictional policy for uploader testing

Download **Nivara ClearCare** using the button in the builder, or open `output/pdf/nivara_clearcare_fictional_policy.pdf`. The text PDF contains eight pages and 32 explicitly numbered, entirely invented insurance clauses. It includes the selected schedule, exclusions, exceptions, overlapping waits, grace-period limits, cancellation conditions and a worked deductible/co-payment example.

Upload only the PDF. Keep `nivara_clearcare_reviewer_checklist.txt` and `nivara_clearcare_clause_inventory.json` separate as independent expected-fact checklists. Extraction may group or split clauses, so compare covered facts, conditions, numbers and source pages rather than demanding exactly 32 topic cards. These fixtures do not contain real insurance rules or personal data.

To regenerate the policy, install `reportlab` in your development environment and run `python scripts/create_test_policy.py`. ReportLab is not required to run the deployed uploader. The generated PDF was rendered and visually inspected; the uploader successfully extracts all eight pages. Live model extraction results have not yet been scored against the checklist.

### JSON mode and document-chunk context

Topic requests explicitly instruct the model to return a JSON object, as required by the JSON-object response mode. Chunk prompts distinguish actual missing terms from cross-references handled in other chunks. For documents up to 60,000 extracted characters, unresolved notes can trigger one additional full-source review request. A note is cleared only when the reviewer model supplies a source quote that the code verifies on the cited page; the original note and resolution evidence remain in the exported catalog and compiled pack. This automated check is not human approval or a guarantee of semantic correctness. Larger documents retain unresolved notes for human review without this extra request.

A live local integration run with the configured GPT-6 Luna model generated 32 topic drafts from the eight-page fixture, validated their source quotes, resolved three chunk-context notes against the full source and compiled a draft pack. This verifies connectivity and workflow, not completeness or comprehension accuracy.
