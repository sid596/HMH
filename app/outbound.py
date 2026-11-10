"""Explicit, server-to-server outbound calls to one configured test destination."""
import os
import uuid
import httpx
import streamlit as st
from streamlit.errors import StreamlitSecretNotFoundError
from urllib.parse import urlsplit


def call_setting(name):
    """Read current Streamlit secrets before process environment defaults."""
    try:
        value = st.secrets.get(name, os.getenv(name, ""))
    except (StreamlitSecretNotFoundError, FileNotFoundError):
        value = os.getenv(name, "")
    return str(value).strip()


def health_error(status_code):
    if status_code == 401:
        return "Backend rejected the call token (HTTP 401). The Streamlit HMH_CALL_API_TOKEN must match the running backend's token."
    if status_code == 404:
        return "Backend health endpoint returned HTTP 404. The tunnel may be offline or HMH_CALL_API_URL points to the wrong service."
    if status_code in (502, 503, 504):
        return f"Tunnel/backend unavailable (HTTP {status_code}). Check that the call server is listening on the port forwarded by ngrok."
    return f"Backend health request returned HTTP {status_code}. Check the tunnel and backend logs; this is not necessarily a token error."


def render_outbound(pack):
    with st.expander("Call my test phone",expanded=False):
        st.write("Start a separate verification call using this saved pack. It speaks with Timbre and assesses answers against the same reviewed topics. Phone speech recognition uses Twilio Gather by default; browser voice uses Prisma.")
        st.info("Phone demo: Twilio transcribes answers; Gnani Timbre speaks. Prisma is not used for phone listening in Gather mode. Trial demo packs should contain at most 3 topics.")
        st.caption("Maximum 15 questions including retries. Answer after the question finishes, then pause. This version does not support interrupting the AI. Phone and recording charges are billed by Twilio.")
        reviewed=bool(pack.get("review_record",{}).get("reviewer")) and 1 <= len(pack.get("clauses",[])) <= 15
        api=call_setting("HMH_CALL_API_URL").rstrip("/")
        token=call_setting("HMH_CALL_API_TOKEN")
        if api:
            endpoint=urlsplit(api)
            st.caption("Backend address: " + str(endpoint.hostname or "invalid URL") + (endpoint.path or ""))
        ready=False
        if not reviewed:
            st.info("Save a reviewed demo pack in the builder before calling.")
        if not api or not token:
            st.info("Call backend is not connected. Run scripts/configure_calls.py locally, start the separate call server, and connect its public HTTPS URL. Streamlit alone cannot answer Twilio callbacks.")
        else:
            try:
                response=httpx.get(api+"/health",headers={"Authorization":"Bearer "+token,"ngrok-skip-browser-warning":"true"},timeout=5)
                if response.status_code!=200:
                    st.error(health_error(response.status_code))
                else:
                    status=response.json()
                    ready=status.get("ready",False)
                    limit=status.get("max_topics",15)
                    if isinstance(limit,int) and len(pack.get("clauses",[]))>limit:
                        ready=False
                        st.warning(f"This pack has {len(pack['clauses'])} topics. Your phone account allows at most {limit} topics per demo call. Return to the builder, remove topics and save the smaller pack.")
                    if not ready:
                        if status.get("missing"):
                            st.info("Backend still needs: "+", ".join(status["missing"]))
                        if status.get("configuration_issue"):st.error(status["configuration_issue"])
            except (httpx.HTTPError,ValueError):
                st.info("Call backend is not reachable. Start it and check HMH_CALL_API_URL.")
        consent=st.checkbox("Call my configured test phone now. I agree to synthetic answer transcription and the provider's call charges.",key="outbound_consent")
        active=st.session_state.get("outbound_call_active",False)
        if st.button("Call my test phone",type="primary",disabled=not ready or not reviewed or not consent or active):
            request_id=uuid.uuid4().hex
            st.session_state.outbound_call_id=request_id
            st.session_state.outbound_call_active=True
            try:
                response=httpx.post(api+"/calls",headers={"Authorization":"Bearer "+token},
                    json={"request_id":request_id,"pack":pack},timeout=15)
                if response.status_code==200:
                    st.success("Preparing the opening audio, then calling your configured phone. Do not click again while this request is active.")
                else:
                    st.session_state.outbound_call_active=False
                    detail=None
                    try:
                        detail=response.json().get("detail")
                    except ValueError:
                        pass
                    safe_prefixes=("Use at most 3 topics", "A test call is already active", "This demo allows at most", "Save a reviewed demo pack", "The phone pack needs", "Missing backend settings:", "Twilio trial blocks")
                    if isinstance(detail,str) and detail.startswith(safe_prefixes) and len(detail)<600:
                        st.error("Call was not started: " + detail)
                    else:
                        st.error(f"Call request rejected (HTTP {response.status_code}). Check backend configuration and active-call status.")
            except httpx.HTTPError:
                st.warning("Could not confirm setup. Use Refresh call status before trying again; the request may have been accepted.")
        call_id=st.session_state.get("outbound_call_id")
        if call_id and api and token:
            if st.button("Refresh call status"):
                try:
                    response=httpx.get(api+"/calls/"+call_id,headers={"Authorization":"Bearer "+token},timeout=5)
                    if response.status_code==200:
                        status=response.json()
                        st.write("Call: **"+status["phase"]+"** · Verification: **"+status["verification_status"]+"**")
                        st.caption(f"{status['checks_passed']} checks passed · {status['answer_turns']} / 15 answer turns used")
                        if status.get("error"):st.warning(status["error"])
                        if status["phase"] in {"completed","failed","cancelled"}:
                            st.session_state.outbound_call_active=False
                    else:
                        st.warning("Status unavailable. Check backend and Twilio logs before redialling.")
                except (httpx.HTTPError,ValueError):
                    st.warning("Could not fetch call status. Check your connection.")
            if st.button("End test call",disabled=not active):
                try:
                    response=httpx.post(api+"/calls/"+call_id+"/cancel",headers={"Authorization":"Bearer "+token},timeout=10)
                    if response.status_code==200:
                        st.session_state.outbound_call_active=False
                        st.success("Call ended or preparation cancelled.")
                    else:st.error("Could not confirm hangup. End it from your phone or Twilio console.")
                except httpx.HTTPError:
                    st.error("Could not confirm hangup. End it from your phone or Twilio console.")
