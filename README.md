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

Four critical clauses, two retries per clause. The second retry uses a simpler explanation. Scorer confidence is retained as diagnostic metadata only and never controls progression. At least 75% of rubric facts must be conveyed, with no detected contradiction. Facts currently have equal weight; this permits up to 25% of facts to remain unverified, and a pass is not full understanding. The percentage is rubric coverage, not model certainty.

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

The app opens on **Build a verification pack**. The example product is explicitly a prewritten fixture: four synthetic topics with two example required topics. Use `+` to add a topic, expand its source/rubric, search or filter the library, and select the topics to include. Enter a reviewer name, attest to reviewing the content, and save a demo pack. **Open voice verification** selects that pack and its matching language/voice. Resetting the call preserves your builder state.

For PDF generation choose **Upload synthetic PDF**, choose the output language, upload a text PDF, confirm synthetic data, then click **Generate topic library**. Text is sent to the configured semantic-model provider using the same SCORER settings. The UI displays the number of chunk requests before generation. There are no automatic retries. No Gnani credits are used for document generation.

- Limits: 20 MB, 300 pages, 1.5 million extracted characters. OCR is not included; unreadable pages block generation rather than being silently omitted.
- Each generated topic needs a verbatim quote and physical PDF page number. Code checks quote presence, not whether the model's interpretation is correct. Topics remain machine drafts pending review.
- All text chunks are processed; extraction is not guaranteed exhaustive. Exact duplicate topic/source combinations are removed, but a human must review overlap across chunks.
- Unresolved model-reported details prevent creating a runnable pack. Export the library to review those issues and supply a corrected/complete synthetic source before regenerating.
- Required core topics are configured only for the built-in example. Uploaded PDFs have model-suggested risk labels, not an organisation-approved core. The generator cannot declare a topic mandatory.
- Review identity is self-attested. No reviewer roles/authentication are enforced. Exported packs stay `draft` and never certify legal consent.
- Saved packs include selected clauses, the full topic catalog, omitted topics, source document hash, model/prompt version, reviewer and timestamp. The session's audit log includes the pack snapshot. Storage in `data/packs/` and browser session state is local/ephemeral on cloud restarts; download packs and libraries to retain them. This prototype does not reload saved packs after a server restart.

Run `python -m unittest discover -s tests -v` for policy, language, quote validation, selection and UI workflow tests. Live PDF-to-topic model quality and actual voice pronunciation require human evaluation; tests do not measure either.

## Fictional policy for uploader testing

Download **Nivara ClearCare** using the button in the builder, or open `output/pdf/nivara_clearcare_fictional_policy.pdf`. The text PDF contains eight pages and 32 explicitly numbered, entirely invented insurance clauses. It includes the selected schedule, exclusions, exceptions, overlapping waits, grace-period limits, cancellation conditions and a worked deductible/co-payment example.

Upload only the PDF. Keep `nivara_clearcare_reviewer_checklist.txt` and `nivara_clearcare_clause_inventory.json` separate as independent expected-fact checklists. Extraction may group or split clauses, so compare covered facts, conditions, numbers and source pages rather than demanding exactly 32 topic cards. These fixtures do not contain real insurance rules or personal data.

To regenerate the policy, install `reportlab` in your development environment and run `python scripts/create_test_policy.py`. ReportLab is not required to run the deployed uploader. The generated PDF was rendered and visually inspected; the uploader successfully extracts all eight pages. Live model extraction results have not yet been scored against the checklist.

### JSON mode and document-chunk context

Topic requests explicitly instruct the model to return a JSON object, as required by the JSON-object response mode. Chunk prompts distinguish actual missing terms from cross-references handled in other chunks. For documents up to 60,000 extracted characters, unresolved notes can trigger one additional full-source review request. A note is cleared only when the reviewer model supplies a source quote that the code verifies on the cited page; the original note and resolution evidence remain in the exported catalog and compiled pack. This automated check is not human approval or a guarantee of semantic correctness. Larger documents retain unresolved notes for human review without this extra request.

A live local integration run with the configured GPT-6 Luna model generated 32 topic drafts from the eight-page fixture, validated their source quotes, resolved three chunk-context notes against the full source and compiled a draft pack. This verifies connectivity and workflow, not completeness or comprehension accuracy.

## Automatic language, prior calls and bounded verification

**Customer language** replaces the ambiguous **Pack language** label. Automatic mode classifies the PDF's language (one extra text-model request) and generates questions in that supported language; the prewritten example defaults to English without a request. An explicit customer-language override permits, for example, an English PDF and Kannada questions. Automatic detection is a suggestion and can be wrong; the preview shows the actual question language and voice. A PDF cannot establish a particular customer's language preference.

The builder's **Add previous-call context** accepts synthetic WAV, MP4, M4A, MP3, OGG, WebM, FLAC or AAC recordings, up to 10 minutes / 60 MB. Audio is extracted/resampled locally with a bundled FFmpeg binary into 16-bit PCM as needed; video is not sent to Prisma. Mono/stereo channels are preserved; surround audio is rejected. It splits audio into up to 25-second clips and sends them explicitly to Prisma using `indic-auto`. It does not perform automatic speaker diarization. Known stereo channels may be mapped to agent/customer; mixed speech stays unknown. Review/edit transcript text and speaker labels before asking the text model to link quotes to existing topic IDs. Every note's quote must occur in its referenced segment. Agent claims require an agent-labelled segment. If a model proposes an attributed note from an unknown segment, it is retained as unattributed discussion with a warning; conflicting known labels still fail validation. Explicit language requests must come from a customer-labelled segment; the language someone happens to speak is not enough to infer preference. This feature does not guarantee complete/accurate transcription; chunk boundaries and cross-talk may lose words.

Call context never rewrites policy clauses or awards a teach-back pass. It adds reviewer notes and can bring a topic forward within its importance tier. Required core topics come first, then high-risk topics, then standard/optional topics. Newly generated topics have a suggested importance score; all are subject to reviewer judgement. There is still no organisation-approved required core for arbitrary uploads.

At most **15 main questions** may be selected; the `+` controls and pack compiler enforce that limit. A live/browser/scripted session also permits at most **15 answer turns including retries**. If retries consume the budget before all selected topics pass, the result is human review. This is a turn cap, not a guarantee of an exact call duration. All omitted topics remain in the saved pack automatically; reviewers do not need to enter exclusion reasons.

**Call my test phone** is available after saving a reviewed pack, or in Voice verification. See `telephony/README.md` for the separate backend and configuration helper. Phone calls now default to Twilio Gather transcription with Gnani Timbre voice; Prisma remains in browser voice and optional prior-call uploads. Trial packs are limited to 3 topics and a conservative callback budget. Optional `PHONE_STT_MODE=prisma_record` requires Record access and is blocked on trial accounts. Trial routing/custom answer URL acceptance still requires a live test. See `telephony/TESTING.md` for the staged evaluation plan. No real call was made during implementation. Typical agent desktops already support dialling/call management (for example [Twilio Flex Dialpad](https://www.twilio.com/docs/flex/admin-guide/setup/voice/dialpad)); which system a particular Gnani customer uses requires that customer's integration details.

For the full test suite including phone integration mocks, install `requirements-call.txt` and run `python -m unittest discover -s tests -v`.

PDF text extraction runs locally. Topic drafting processes up to three independent sections concurrently, preserving source order and validating every source quote. Completed sections and catalogs are cached within the current browser session; repeating the same document, language, model and configuration reuses them. Changing those inputs regenerates the relevant results. The UI shows generation time and cache reuse. For OpenAI GPT-6 Luna, document drafting uses `reasoning_effort=none` to reduce latency; comprehension scoring is unchanged. Optional `DOCUMENT_WORKERS` (1–4, default 3) and `DOCUMENT_REASONING_EFFORT` override document processing settings. Drafts still require human review; quote matching does not establish completeness or semantic accuracy.

Topic drafting on the official OpenAI endpoint with GPT-4o, GPT-4.1, GPT-5 or GPT-6 families uses strict structured outputs to enforce rubric field types and list limits. Other compatible endpoints retain JSON mode with local validation. Source quotes are still checked against PDF text, and strict format does not prove factual interpretation. Invalid rubric errors identify the field and item count; facts are never silently truncated.

Generated customer-facing text is screened per topic for high-confidence language drift using a local detector; original source quotations are excluded. Short text, Hinglish transliteration, and Hindi/Marathi distinctions remain imperfect and require native-speaker review. Older uploaded drafts must be regenerated after validation changes.

Prior-call transcription defaults to sequential requests; the internal helper supports up to three concurrent requests for controlled tests. The UI always uses one request, indic-auto language detection and unknown channel roles. It reuses completed results in the current session, keyed by audio, language and credential identity. Clips prefer a short quiet boundary near the 25-second limit without dropping frames. The UI always requests indic-auto language detection. PDF extraction and converted audio are reused on interface reruns. The single **Sort topics using this call** action automatically transcribes, makes a transcript cleanup/role-inference request, excludes unknown turns and makes a context/related-topic request. It cannot hear the audio, verify speaker identity or recover missing words. Original chunk timings are retained; automatically inferred roles are explicitly marked model-inferred and unverified, never reviewer-confirmed. Validation rejects omitted/duplicated source words and changed numeric digits or recognised negation; it does not prove semantic equivalence. Policy/script text is not supplied to cleanup.

Topic-priority analysis uses only reviewed agent/customer-labelled turns. Unknown-speaker turns are excluded from the model input and retained with the original transcript in the context record. If every turn is unknown, analysis stops before an API request and asks for role review.

Call-context linking now selects stable transcript evidence IDs; the application retrieves verbatim quotes and speaker labels. Only minimal reviewed turn metadata is sent, avoiding confusion between audio chunk IDs and filtered turn indices. Legacy quote responses can have an index repaired only when the exact quote occurs in one included turn; invented or ambiguous evidence remains rejected.

After reviewed-call analysis, the model may suggest up to three closely related existing topics per directly evidenced topic, using indexed rubric facts and a condition/exception/prerequisite/consequence/same-rule relationship. Shared generic words alone are not sufficient in the instructions. Relationships are model suggestions, not proof that the customer discussed those topics. Direct call context ranks first, related context second, and unaffected topics third. Required/risk tiers and priority scores break ties within those groups; required topics remain mandatory regardless of position. Library cards show why they moved; saved selected packs use the same order. Unselected call-related topics are highlighted but never added automatically. Re-analyse the reviewed context to obtain new relationship suggestions; PDF regeneration is not required.

The prior-call UI now contains upload and one sorting action. Channel mapping, recording-language and concurrency dropdowns and the synthetic-upload checkbox were removed. There are no intermediate transcription, suggestion, confirmation or apply controls. A collapsed details panel shows labelled working turns and offers a raw/analysis download. Call-context results report direct and related topic counts, and explain when no additional close matches are found.

The one-click pipeline caches converted audio, successful Prisma clips, role-cleanup results and context results within the session. Cache identity includes audio and relevant model/credential configuration; the context stage also includes the topic library. Failure retains the previous library, and the next explicit Sort action resumes completed stages without automatic retries. Unknown turns are excluded from the working transcript and context input, but retained as raw/excluded metadata.
