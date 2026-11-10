import os
from pathlib import Path
import hashlib
import streamlit as st
from engine.call_context import wav_segments, transcribe_recording, analyse_context, suggest_transcript_review
from voice.gnani import transcribe
from engine.audio_import import normalize_recording


def recording_panel(catalog):
    with st.expander("Add previous-call context", expanded=False):
        st.write("Upload a synthetic agent/customer call to identify questions and possible confusion. Policy wording remains the source of truth.")
        upload = st.file_uploader("Prior call recording (audio/video, up to 10 minutes)",type=["wav","mp4","m4a","mp3","ogg","webm","flac","aac"],max_upload_size=60,key="prior_call_audio")
        st.caption("Upload your recording directly. HMH extracts the audio and converts it locally when needed; video is not sent to Prisma. Maximum 60 MB / 10 minutes.")
        mapping = st.selectbox("Speaker channels",["unknown","agent_left","customer_left"],
            format_func=lambda k:{"unknown":"Mono/mixed or unknown speakers","agent_left":"Stereo: agent left, customer right","customer_left":"Stereo: customer left, agent right"}[k])
        st.caption("Channel labels must be known from the recording setup. Mixed audio does not provide reliable agent/customer labels. Chunk boundaries can affect recognition.")
        listening_language=st.selectbox("Recording language",["indic-auto","en-IN","hi-IN","mr-IN","kn-IN"],help="Choose the main spoken language when known. Auto detection can be less reliable on short or mixed clips.")
        synthetic = st.checkbox("This is a synthetic test conversation; I may upload it to Gnani and the configured text-model provider.",key="call_context_permission")
        if not os.getenv("GNANI_API_KEY"):
            st.info("Configure GNANI_API_KEY to transcribe a recording.")
        if upload is not None:
            try:
                original=upload.getvalue()
                audio_hash=hashlib.sha256(original).hexdigest()
                cached=st.session_state.get("normalized_prior_audio")
                if not cached or cached[0]!=audio_hash:
                    if cached:
                        st.session_state.pop("prior_transcript",None)
                        st.session_state.pop("transcript_suggestions",None)
                    with st.spinner("Preparing recording audio…"):
                        cached=(audio_hash,normalize_recording(original))
                    st.session_state.normalized_prior_audio=cached
                audio=cached[1]
                clip_key=audio_hash+":"+mapping
                cached_clips=st.session_state.get("prior_clip_count")
                if not cached_clips or cached_clips[0]!=clip_key:
                    cached_clips=(clip_key,len(wav_segments(audio,mapping)))
                    st.session_state.prior_clip_count=cached_clips
                count=cached_clips[1]
                st.caption(f"{count} Prisma request(s), processed up to 3 at a time, then 1 text-model request to link it to topics.")
                if st.button("Transcribe previous call",disabled=not synthetic or not os.getenv("GNANI_API_KEY")):
                    bar=st.progress(0,text="Transcribing synthetic call…")
                    try:
                        transcript=transcribe_recording(audio,transcribe,mapping,language=listening_language,cache=st.session_state.setdefault("prisma_clip_cache",{}),
                            progress=lambda n,total:bar.progress(n/total,text=f"Transcribed {n}/{total} clips"))
                        transcript["original_sha256"]=audio_hash
                        transcript["source_filename"]=upload.name
                        st.session_state.prior_transcript=transcript
                        st.session_state.pop("transcript_suggestions",None)
                        st.success("Transcript ready. Check the text and speaker labels below before linking it to topics.")
                    except Exception as exc:
                        st.error(f"Transcription stopped ({type(exc).__name__}). No call context was accepted.")
            except ValueError as exc:
                st.error(str(exc))
        transcript=st.session_state.get("prior_transcript")
        if transcript:
            import json
            st.caption(f"Transcription: {transcript.get('performance',{}).get('seconds','—')} seconds. Raw output is preserved; text cleanup cannot recover words missing from the audio transcription.")
            if st.session_state.get("normalized_prior_audio"):
                st.audio(st.session_state.normalized_prior_audio[1],format="audio/wav")
            if st.button("Suggest speaker turns and transcript cleanup",disabled=not synthetic or not os.getenv("SCORER_API_KEY") or not os.getenv("SCORER_MODEL")):
                try:
                    with st.spinner("Suggesting transcript edits and speaker roles…"):
                        st.session_state.transcript_suggestions=suggest_transcript_review(transcript)
                except Exception as exc:
                    st.error(str(exc) if isinstance(exc,ValueError) else f"Assisted review failed ({type(exc).__name__}). Raw transcript retained.")
            suggestions=st.session_state.get("transcript_suggestions")
            if suggestions:
                suggestion_key=hashlib.sha256(json.dumps(suggestions,sort_keys=True).encode()).hexdigest()[:12]
                st.info("Suggested roles are inferred from text, not verified voices. Listen above and check corrections. Time ranges refer to original chunks, not precise speaker boundaries.")
                proposed=st.data_editor(suggestions["segments"],num_rows="fixed",
                    disabled=["start_seconds","end_seconds","raw_text","source_segment_index","role_origin","review_note"],
                    column_config={"speaker":st.column_config.SelectboxColumn(options=["agent","customer","unknown"],required=True)},
                    key="suggestion_table:"+suggestion_key)
                confirmed=st.checkbox("I checked these suggested edits and speaker labels against the recording.",key="confirm_transcript_suggestions:"+suggestion_key)
                if st.button("Apply reviewed suggestions",disabled=not confirmed):
                    st.session_state.prior_transcript={**transcript,"segments":[{**s,"role_origin":"reviewer_confirmed_model_suggestion"} for s in proposed],"raw_transcript":suggestions["raw_transcript"],"speaker_attribution":"reviewer_confirmed_suggestions"}
                    st.session_state.pop("transcript_suggestions",None)
                    st.rerun()
            st.caption("Edit recognised text or speaker labels if needed. Labels: agent, customer, unknown. Keep timing fields unchanged.")
            edited=st.text_area("Review transcript segments (JSON)",value=json.dumps(transcript["segments"],ensure_ascii=False,indent=2),height=200,key="prior_transcript_editor:"+transcript["sha256"]+hashlib.sha256(json.dumps(transcript["segments"],sort_keys=True).encode()).hexdigest()[:10])
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
                if note.get("attribution_warning"):st.caption(note["attribution_warning"])
                st.caption("Transcript evidence: "+note["quote"])
