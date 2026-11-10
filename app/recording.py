import os
import hashlib
import streamlit as st
import httpx
from engine.call_context import transcribe_recording, analyse_context, suggest_transcript_review
from voice.gnani import transcribe
from engine.audio_import import normalize_recording


def recording_panel(catalog):
    with st.expander("Add previous-call context", expanded=False):
        st.write("Upload a synthetic agent/customer call to identify questions and possible confusion. Policy wording remains the source of truth.")
        upload = st.file_uploader("Prior call recording (audio/video, up to 10 minutes)",type=["wav","mp4","m4a","mp3","ogg","webm","flac","aac"],max_upload_size=60,key="prior_call_audio")
        st.caption("Upload your recording directly. HMH extracts the audio and converts it locally when needed; video is not sent to Prisma. Maximum 60 MB / 10 minutes.")
        mapping="unknown"
        listening_language="indic-auto"
        workers=1
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
                if st.button("Transcribe previous call",disabled=not os.getenv("GNANI_API_KEY")):
                    bar=st.progress(0,text="Transcribing synthetic call…")
                    try:
                        transcript=transcribe_recording(audio,transcribe,mapping,language=listening_language,max_workers=workers,cache=st.session_state.setdefault("prisma_clip_cache",{}),
                            progress=lambda n,total:bar.progress(n/total,text=f"Transcribed {n}/{total} clips"))
                        transcript["original_sha256"]=audio_hash
                        transcript["source_filename"]=upload.name
                        st.session_state.prior_transcript=transcript
                        st.session_state.pop("transcript_suggestions",None)
                        st.success("Transcript ready. Check the text and speaker labels below before linking it to topics.")
                    except httpx.HTTPStatusError as exc:
                        status=exc.response.status_code
                        actions={429:"Gnani limited request traffic or quota. Check credits/limits, and retry explicitly after waiting.",
                            401:"Gnani rejected the API key. Check GNANI_API_KEY in Streamlit Secrets.",
                            403:"Gnani denied this request. Check account permissions and credits.",
                            400:"Gnani rejected the audio or automatic language setting. Check its dashboard for details.",
                            413:"Gnani rejected the clip size."}
                        st.error(f"Prisma transcription rejected (HTTP {status}). "+actions.get(status,"Gnani returned a service error. Check its dashboard and retry explicitly later."))
                        st.caption("Successful clips remain cached in this session. No automatic retry was made; no partial call context was accepted.")
                    except Exception as exc:
                        st.error(f"Transcription stopped ({type(exc).__name__}). No call context was accepted.")
            except ValueError as exc:
                st.error(str(exc))
        transcript=st.session_state.get("prior_transcript")
        if transcript:
            import json
            editor_key="prior_transcript_editor:"+transcript["sha256"]+hashlib.sha256(json.dumps(transcript["segments"],sort_keys=True).encode()).hexdigest()[:10]
            edited=st.session_state.get(editor_key,json.dumps(transcript["segments"],ensure_ascii=False,indent=2))
            labelled=sum(s.get("speaker") in {"agent","customer"} for s in transcript["segments"])
            if not labelled:
                st.caption("Assign speaker turns in Review transcript below before sorting.")
            if st.button("Sort topics using this call"):
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
            with st.expander("Review transcript and speaker suggestions",expanded=False):
                if st.session_state.get("normalized_prior_audio"):
                    st.audio(st.session_state.normalized_prior_audio[1],format="audio/wav")
                if st.button("Suggest speaker turns and transcript cleanup",disabled=not os.getenv("SCORER_API_KEY") or not os.getenv("SCORER_MODEL")):
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
                        st.session_state.prior_transcript={**transcript,"segments":[{**s,"role_origin":"reviewer_confirmed_model_suggestion" if s["speaker"]!="unknown" else "reviewer_reviewed_role_unknown"} for s in proposed],"raw_transcript":suggestions["raw_transcript"],"speaker_attribution":"reviewer_confirmed_suggestions"}
                        st.session_state.pop("transcript_suggestions",None)
                        st.rerun()
                st.caption("Edit recognised text or speaker labels if needed. Labels: agent, customer, unknown. Keep timing fields unchanged.")
                edited=st.text_area("Review transcript segments (JSON)",value=json.dumps(transcript["segments"],ensure_ascii=False,indent=2),height=200,key=editor_key)
        context=catalog.get("call_context")
        if context:
            st.success(f"{len(context['notes'])} source-linked call notes added. Discussion never counts as a teach-back pass.")
            direct_ids={n["topic_id"] for n in context["notes"] if n["kind"]!="mentioned"}
            related_ids={r["topic_id"] for r in context.get("related_topics",[])}-direct_ids
            st.caption(f"Priority summary: {len(direct_ids)} directly linked topics · {len(related_ids)} related topics. Sorting stays within required/risk tiers.")
            if direct_ids and not related_ids:
                st.caption("No additional close matches were identified. Several parts of this concern may already be grouped in one topic; unrelated topics are not boosted.")
            excluded_count=len(context["transcript"].get("excluded_unknown_segments",[]))
            if excluded_count:st.caption(f"Excluded {excluded_count} unknown-speaker turns from prioritisation; original text retained in the context record.")
            if context["preferred_language"]:
                st.info("Explicit language preference found: "+context["preferred_language"]+". Choose that customer language when generating the pack.")
            with st.expander("Why these topics were prioritised",expanded=False):
                for note in context["notes"]:
                    st.write(f"**{note['topic_id']} · {note['kind'].replace('_',' ')} · {note['speaker']}**")
                    st.write(note["observation"])
                    if note.get("attribution_warning"):st.caption(note["attribution_warning"])
                    st.caption("Transcript evidence: "+note["quote"])
