import os
from pathlib import Path
import hashlib
import streamlit as st
from engine.call_context import wav_segments, transcribe_recording, analyse_context
from voice.gnani import transcribe


def recording_panel(catalog):
    with st.expander("Add previous-call context", expanded=False):
        st.write("Upload a synthetic agent/customer call to identify questions and possible confusion. Policy wording remains the source of truth.")
        upload = st.file_uploader("Prior call recording (16-bit WAV, up to 10 minutes)",type=["wav"],max_upload_size=60,key="prior_call_audio")
        mapping = st.selectbox("Speaker channels",["unknown","agent_left","customer_left"],
            format_func=lambda k:{"unknown":"Mono/mixed or unknown speakers","agent_left":"Stereo: agent left, customer right","customer_left":"Stereo: customer left, agent right"}[k])
        st.caption("Channel labels must be known from the recording setup. Mixed audio does not provide reliable agent/customer labels. Chunk boundaries can affect recognition.")
        synthetic = st.checkbox("This is a synthetic test conversation; I may upload it to Gnani and the configured text-model provider.",key="call_context_permission")
        if not os.getenv("GNANI_API_KEY"):
            st.info("Configure GNANI_API_KEY to transcribe a recording.")
        if upload is not None:
            try:
                count=len(wav_segments(upload.getvalue(),mapping))
                st.caption(f"{count} Prisma request(s) to transcribe, then 1 text-model request to link it to topics.")
                if st.button("Transcribe previous call",disabled=not synthetic or not os.getenv("GNANI_API_KEY")):
                    bar=st.progress(0,text="Transcribing synthetic call…")
                    try:
                        transcript=transcribe_recording(upload.getvalue(),transcribe,mapping,
                            progress=lambda n,total:bar.progress(n/total,text=f"Transcribed {n}/{total} clips"))
                        st.session_state.prior_transcript=transcript
                        st.success("Transcript ready. Check the text and speaker labels below before linking it to topics.")
                    except Exception as exc:
                        st.error(f"Transcription stopped ({type(exc).__name__}). No call context was accepted.")
            except ValueError as exc:
                st.error(str(exc))
        transcript=st.session_state.get("prior_transcript")
        if transcript:
            import json
            st.caption("Edit recognised text or speaker labels if needed. Labels: agent, customer, unknown. Keep timing fields unchanged.")
            edited=st.text_area("Review transcript segments (JSON)",value=json.dumps(transcript["segments"],ensure_ascii=False,indent=2),height=200,key="prior_transcript_editor:"+transcript["sha256"])
            if st.button("Use reviewed call context",disabled=not synthetic):
                try:
                    segments=json.loads(edited)
                    if not isinstance(segments,list) or not segments or any(not isinstance(s,dict) or s.get("speaker") not in {"agent","customer","unknown"} or not isinstance(s.get("text"),str) for s in segments):
                        raise ValueError("Each segment needs text and an agent/customer/unknown label")
                    reviewed={**transcript,"segments":segments,"speaker_attribution":"reviewer_supplied"}
                    with st.spinner("Linking call evidence to policy topics…"):
                        result=analyse_context(catalog,reviewed)
                    st.session_state.catalog=result
                    st.rerun()
                except Exception as exc:
                    st.error(str(exc) if isinstance(exc,ValueError) else f"Context analysis failed ({type(exc).__name__}). No new context was accepted.")
        context=catalog.get("call_context")
        if context:
            st.success(f"{len(context['notes'])} source-linked call notes added. Discussion never counts as a teach-back pass.")
            if context["preferred_language"]:
                st.info("Explicit language preference found: "+context["preferred_language"]+". Choose that customer language when generating the pack.")
            for note in context["notes"]:
                st.write(f"**{note['topic_id']} · {note['kind'].replace('_',' ')} · {note['speaker']}**")
                st.write(note["observation"])
                st.caption("Transcript evidence: "+note["quote"])
