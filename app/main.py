from pathlib import Path
import sys
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import json
import os
import streamlit as st
from engine.core import Session, load_pack
from engine.scorer import score, fixture_evidence
from voice.gnani import transcribe, synthesize

ROOT = Path(__file__).resolve().parents[1]
secrets_path = ROOT / ".hmh-secrets.json"
if secrets_path.exists():
    for key, value in json.loads(secrets_path.read_text()).items():
        if key in {"GNANI_API_KEY", "SCORER_API_KEY", "SCORER_MODEL", "SCORER_BASE_URL"}:
            os.environ.setdefault(key, value)
st.set_page_config(page_title="Haan Matlab Haan", page_icon="🗣️", layout="wide")
st.title("Haan Matlab Haan")
st.caption("Teach-back verification • Synthetic product and customer scenarios • Hindi–English prototype")
st.write("A recorded yes is only the beginning. Ask customers to explain key terms in their own words, then route unresolved confusion to a person.")
pack = load_pack(ROOT / "packs/fictional_savings_v1.json")
with st.sidebar:
    st.header("Session setup")
    mode = st.selectbox("Assessment mode", ["Scripted walkthrough", "Live semantic scorer"], disabled="session" in st.session_state)
    st.caption("Scripted mode uses predefined answers and evidence; it does not evaluate speech or arbitrary text.")
    language = st.selectbox("Prisma language hint", ["hi-IN", "en-IN", "mr-IN", "kn-IN", "indic-auto"])
    voice = st.text_input("Timbre voice", "Nalini", help="Use a voice supported for your selected language in the Gnani console.")
    st.write("Gnani key: " + ("configured" if os.getenv("GNANI_API_KEY") else "missing"))
    st.write("Semantic scorer: " + ("configured" if os.getenv("SCORER_API_KEY") and os.getenv("SCORER_MODEL") else "missing"))
    if st.button("Reset session"):
        for key in list(st.session_state):
            del st.session_state[key]
        st.rerun()
    with st.expander("Rubric and policy"):
        st.json(pack)
        st.write("Confidence gate: 0.85 (provisional, uncalibrated). Two retries. Low confidence or exhausted retries → human review.")

st.warning("Draft rubric: human review pending. All amounts and terms are invented. This demo cannot certify legal consent or prove understanding.")
if "session" not in st.session_state:
    st.info(pack["disclosure"])
    if st.button("Start disclosed demo session", type="primary"):
        st.session_state.session = Session(pack, ROOT / "data", "scripted" if mode == "Scripted walkthrough" else "live")
        st.rerun()
    st.stop()

session = st.session_state.session
st.progress(len(session.results) / len(pack["clauses"]))
st.caption(f"Session {session.audit.session_id} · Rubric {pack['pack_version']}")
if session.status != "active":
    if session.status == "human_review":
        st.error("Human review required. Verification has stopped; consent has not been accepted.")
    else:
        st.success("Demo teach-back checks passed. This is a draft-rubric demonstration, not valid consent.")
else:
    c = session.clause
    st.subheader(f"{session.index + 1}. {c['title']}")
    st.caption(f"Attempt {session.attempt + 1} of 3 · Critical clause")
    explanation = c["fallback_explain"] if session.attempt >= 2 else c["explain"]
    st.write(explanation)
    st.info(c["question"])
    if st.button("Speak disclosure and prompt with Timbre" if not session.results and session.attempt == 0 else "Speak prompt with Timbre"):
        try:
            text = explanation + " " + c["question"]
            if not session.results and session.attempt == 0:
                text = pack["disclosure"] + " " + text
            with st.spinner("Synthesizing with Timbre…"):
                audio = synthesize(text, language=language, voice=voice)
            st.audio(audio, format="audio/wav")
            session.audit.append("tts_generated", clause_id=c["id"], text=text, language=language, voice=voice)
        except Exception as exc:
            st.error(f"Speech generation failed ({type(exc).__name__}). Check local configuration and API access.")
            session.audit.append("tts_failed", error_type=type(exc).__name__)

    if session.mode == "scripted":
        persona = st.selectbox("Synthetic response", ["nods_along", "attentive", "partial", "misconception"])
        answer, evidence = fixture_evidence(c, persona)
        st.write(f"Customer: {answer}")
        if st.button("Run scripted assessment", type="primary"):
            session.submit(answer, evidence, source="scripted_fixture")
            st.rerun()
    else:
        st.caption("Use synthetic customer speech only. Do not upload real calls or personal information. Prisma transcripts are the scorer's input and can contain recognition errors.")
        audio = st.audio_input("Record a synthetic teach-back response", key=f"audio_{session.index}_{session.attempt}")
        if st.button("Transcribe recording with Prisma", disabled=audio is None):
            try:
                with st.spinner("Transcribing with Prisma…"):
                    result = transcribe(audio.getvalue(), language=language)
                st.session_state["transcript"] = result["transcript"]
                st.session_state["transcript_metadata"] = {k: v for k, v in result.items() if k != "transcript"}
                session.audit.append("transcription", clause_id=c["id"], transcript=result["transcript"], metadata=st.session_state["transcript_metadata"])
            except Exception as exc:
                st.error(f"Transcription failed ({type(exc).__name__}). No answer was accepted.")
                session.audit.append("transcription_failed", error_type=type(exc).__name__)
        typed = st.checkbox("Use typed synthetic answer instead of voice")
        if typed:
            answer = st.text_area("Typed teach-back", key=f"typed_{session.index}_{session.attempt}")
        else:
            answer = st.session_state.get("transcript", "")
            st.write("Prisma heard: " + (answer or "No transcript yet"))
        if st.button("Assess teach-back", type="primary", disabled=not answer.strip()):
            try:
                with st.spinner("Assessing against rubric…"):
                    evidence = score(answer, c)
                session.submit(answer, evidence, source="typed" if typed else "prisma",
                               transcript_metadata=None if typed else st.session_state.get("transcript_metadata"))
                st.session_state.pop("transcript", None)
                st.session_state.pop("transcript_metadata", None)
                st.rerun()
            except Exception as exc:
                session.audit.append("assessment_failed", clause_id=c["id"], error_type=type(exc).__name__)
                st.error(f"Assessment failed ({type(exc).__name__}). No pass was recorded. Retry or refer to a human.")
    if st.button("Stop and refer to a human"):
        session.status = "human_review"
        session.audit.append("session_finished", status="human_review", reason="manual_referral")
        st.rerun()

with st.expander("Audit trail / receipt", expanded=session.status != "active"):
    records = session.audit.records()
    for record in records:
        if record["event"] == "assessment":
            p = record["payload"]
            st.write(f"{p['clause_id']} · {p['evidence']['verdict']} → {p['action']}")
            st.caption(p["evidence"]["rationale"])
    st.download_button("Download JSON audit receipt", json.dumps(records, indent=2, ensure_ascii=False),
                       file_name=f"hmh-{session.audit.session_id}.json", mime="application/json")
    st.caption("Local append-only writer with linked hashes. Files can still be modified by someone with disk access; this is not immutable storage.")
