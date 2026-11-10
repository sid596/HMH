"""One-click recording-to-topic-priority workflow."""
import os
import json
import httpx
import streamlit as st
from engine.call_context import sort_from_recording
from engine.provider_errors import ModelRequestError
from voice.gnani import transcribe


def recording_panel(catalog):
    with st.expander('Add previous-call context',expanded=False):
        upload=st.file_uploader('Prior call recording (audio/video, up to 10 minutes)',
            type=['wav','mp4','m4a','mp3','ogg','webm','flac','aac'],max_upload_size=60,key='prior_call_audio')
        configured=all(os.getenv(k) for k in ('GNANI_API_KEY','SCORER_API_KEY','SCORER_MODEL'))
        if not configured:st.info('Configure Gnani and text-model credentials to analyse recordings.')
        if st.button('Sort topics using this call',type='primary',disabled=upload is None or not configured):
            status=st.empty()
            try:
                result=sort_from_recording(catalog,upload.getvalue(),transcribe,
                    cache=st.session_state.setdefault('recording_pipeline_cache',{}),progress=status.info)
                st.session_state.catalog=result
                st.rerun()
            except httpx.HTTPStatusError as exc:
                code=exc.response.status_code
                actions={429:'Check Gnani credits and request limits, wait, then retry.',
                         401:'Check GNANI_API_KEY in Streamlit Secrets.',
                         403:'Check Gnani account permissions and credits.',
                         400:'Gnani rejected the audio or automatic language setting.'}
                st.error(f'Prisma rejected transcription (HTTP {code}). '+actions.get(code,'Check the Gnani dashboard.'))
                st.caption('Completed stages remain cached in this session. No automatic retry was made.')
            except (ValueError,ModelRequestError) as exc:
                st.error(str(exc))
                st.caption('The previous library was retained. Completed stages remain cached for an explicit retry.')
            except Exception as exc:
                st.error(f'Recording analysis stopped ({type(exc).__name__}). The previous library was retained.')
        context=catalog.get('call_context')
        if not context:return
        direct={n['topic_id'] for n in context['notes'] if n['kind']!='mentioned'}
        related={r['topic_id'] for r in context.get('related_topics',[])}-direct
        transcript=context['transcript']
        st.success(f'Topics sorted: {len(direct)} direct concerns · {len(related)} related topics.')
        if direct and not related:
            st.caption('No additional close matches were identified; this concern may already be grouped in one topic.')
        with st.expander('Analysis details',expanded=False):
            st.caption('Speaker roles are model-inferred from text, not voice-verified or reviewer-confirmed. Times are original chunk ranges.')
            labelled=[s for s in transcript['segments'] if s.get('speaker') in {'agent','customer'}]
            st.dataframe([{'speaker':s['speaker'],'text':s['text']} for s in labelled],hide_index=True,width="stretch")
            excluded=len(transcript.get('excluded_unknown_segments',[]))
            if excluded:st.caption(f'{excluded} unknown-speaker turns were removed from the working transcript and prioritisation.')
            for note in context['notes']:
                st.write(f"**{note['topic_id']} · {note['kind'].replace('_',' ')}**")
                st.write(note['observation'])
                st.caption('Evidence: '+note['quote'])
            if context.get('preferred_language'):st.write('Explicit language preference: '+context['preferred_language'])
            st.download_button('Download analysis and raw transcript',json.dumps(context,ensure_ascii=False,indent=2),
                file_name='hmh-call-analysis.json',mime='application/json')
