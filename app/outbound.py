"""Explicit, server-to-server outbound calls to one configured test destination."""
import os
import uuid
import httpx
import streamlit as st


def render_outbound(pack):
    with st.expander("Call my test phone",expanded=False):
        st.write("Start a separate verification call using this saved pack. It speaks with Timbre, listens with Prisma, and assesses answers against the same reviewed topics.")
        st.info("Twilio trial currently blocks the Record/Stream features needed to send phone audio to Prisma. The full Gnani phone conversation requires an account with those features enabled.")
        st.caption("Maximum 15 questions including retries. This first phone version waits for your answer after a beep; it does not support interrupting the AI. Phone and recording charges are billed by Twilio.")
        reviewed=bool(pack.get("review_record",{}).get("reviewer")) and 1 <= len(pack.get("clauses",[])) <= 15
        api=os.getenv("HMH_CALL_API_URL","").rstrip("/")
        token=os.getenv("HMH_CALL_API_TOKEN","")
        ready=False
        if not reviewed:
            st.info("Save a reviewed demo pack in the builder before calling.")
        if not api or not token:
            st.info("Call backend is not connected. Run scripts/configure_calls.py locally, start the separate call server, and connect its public HTTPS URL. Streamlit alone cannot answer Twilio callbacks.")
        else:
            try:
                response=httpx.get(api+"/health",headers={"Authorization":"Bearer "+token},timeout=5)
                if response.status_code!=200:
                    st.error("Call backend authentication failed or the endpoint is incorrect.")
                else:
                    status=response.json()
                    ready=status.get("ready",False)
                    if not ready:
                        st.info("Backend still needs: "+", ".join(status.get("missing",[])))
                        if status.get("configuration_issue"):st.error(status["configuration_issue"])
            except (httpx.HTTPError,ValueError):
                st.info("Call backend is not reachable. Start it and check HMH_CALL_API_URL.")
        consent=st.checkbox("Call my configured test phone now. I agree to synthetic answer recording and the provider's call charges.",key="outbound_consent")
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
                    st.error("Call was not started. Check backend configuration and active-call status.")
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
