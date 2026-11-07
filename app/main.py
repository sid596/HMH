from pathlib import Path
import sys
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import json
import os
import streamlit as st
from engine.core import Session, load_pack
from engine.conversation import Conversation
from engine.localization import PROFILES, localized_pack
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
st.caption("Teach-back verification • Synthetic product and customer scenarios • English, Hindi, Hinglish, Marathi and Kannada")
st.write("A recorded yes is only the beginning. Ask customers to explain key terms in their own words, then route unresolved confusion to a person.")
with st.sidebar:
    st.header("Session setup")
    mode = st.selectbox("Assessment mode", ["Voice conversation", "Scripted walkthrough"], disabled="session" in st.session_state)
    st.caption("Scripted mode uses predefined answers and evidence; it does not evaluate speech or arbitrary text.")
    language = st.selectbox("Prisma language hint", ["hi-IN", "en-IN", "mr-IN", "kn-IN", "indic-auto"], disabled="session" in st.session_state)
    tts_language = st.selectbox("Speaking language", list(PROFILES), format_func=lambda code: PROFILES[code]["label"], disabled="session" in st.session_state)
    profile = PROFILES[tts_language]
    voice = profile["voice"]
    pack = localized_pack(tts_language)
    st.caption(f"Voice: {voice} · {profile['persona']} · Timbre v2.5")
    st.caption("Speaking language selects the matching script and voice. Listening language controls how your answer is transcribed; it does not translate the script.")
    st.write("Gnani key: " + ("configured" if os.getenv("GNANI_API_KEY") else "missing"))
    st.write("Semantic scorer: " + ("configured" if os.getenv("SCORER_API_KEY") and os.getenv("SCORER_MODEL") else "missing"))
    if st.button("Reset session"):
        for key in list(st.session_state):
            del st.session_state[key]
        st.rerun()
    with st.expander("Rubric and policy"):
        st.json(pack)
        st.write("Confidence gate: 0.85 (provisional, uncalibrated). Two retries. Low confidence or exhausted retries → human review.")

st.warning("Draft rubric and translations: native-speaker review pending. All amounts and terms are invented. This demo cannot certify legal consent or prove understanding.")
if "session" not in st.session_state:
    st.info(pack["disclosure"])
    ready = all(os.getenv(k) for k in ("GNANI_API_KEY", "SCORER_API_KEY", "SCORER_MODEL"))
    if mode == "Voice conversation":
        st.write(f"{voice} asks aloud. Tap the microphone, answer in your own words, then stop recording. Assessment and the next spoken response happen automatically.")
        st.caption("Allow microphone access. If your browser blocks automatic playback, press play on the audio player. Keep each synthetic answer under 30 seconds.")
        if not ready:
            st.info("Configure GNANI_API_KEY, SCORER_API_KEY and SCORER_MODEL in Streamlit Secrets to start voice conversation.")
    label = "Start conversation" if mode == "Voice conversation" else "Start disclosed demo session"
    if st.button(label, type="primary", disabled=mode == "Voice conversation" and not ready):
        if mode == "Voice conversation":
            conversation = Conversation(pack, ROOT / "data", language, tts_language, voice)
            st.session_state.conversation = conversation
            st.session_state.session = conversation.session
        else:
            st.session_state.session = Session(pack, ROOT / "data", "scripted")
        st.rerun()
    st.stop()

session = st.session_state.session
pack = session.pack
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
    if session.mode == "scripted":
        persona = st.selectbox("Synthetic response", ["nods_along", "attentive", "partial", "misconception"])
        answer, evidence = fixture_evidence(c, persona)
        st.write(f"Customer: {answer}")
        if st.button("Run scripted assessment", type="primary"):
            session.submit(answer, evidence, source="scripted_fixture")
            st.rerun()
    else:
        conversation = st.session_state.conversation
        turn = conversation.turn
        st.caption("Tap the mic to start and stop your answer. Use a fictional customer response; no personal information.")
        recording = st.audio_input("Your answer", sample_rate=16000, key=f"recording_{turn}")
        if recording is not None:
            with st.spinner("Listening with Prisma and checking your understanding…"):
                changed = conversation.receive(recording.getvalue(), transcribe, score)
            if changed:
                st.rerun()
        if conversation.error:
            st.error(f"Could not complete {conversation.error['stage']} ({conversation.error['type']}). No pass was recorded. Record again, retry, or refer to a human.")
            if recording is not None and st.button("Retry this answer"):
                with st.spinner("Retrying…"):
                    changed = conversation.receive(recording.getvalue(), transcribe, score, retry=True)
                if changed:
                    st.rerun()
        if conversation.history:
            last = conversation.history[-1]
            st.write("You said: " + last["answer"])
            st.caption("Understanding: " + last["verdict"].replace("_", " "))
    if st.button("Stop and refer to a human"):
        session.status = "human_review"
        session.audit.append("session_finished", status="human_review", reason="manual_referral")
        st.rerun()

if "conversation" in st.session_state:
    conversation = st.session_state.conversation
    with st.spinner(f"{conversation.voice} is preparing a response…"):
        spoken = conversation.speak(synthesize)
    if spoken is None:
        st.error("Voice audio could not be generated. You can read the question above or retry the voice.")
        if st.button("Retry voice playback"):
            conversation.speak(synthesize, retry=True)
            st.rerun()
    else:
        # A fresh turn mounts a fresh player. Ordinary reruns retain the same audio.
        st.audio(spoken, format="audio/wav", autoplay=True)
        st.caption(f"{conversation.voice} · If playback is blocked by your browser, press play.")

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
