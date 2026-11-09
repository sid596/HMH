"""Document review workspace; draft content never silently enters a customer session."""
import json
import os
from pathlib import Path
import streamlit as st
from engine.provider_errors import ModelRequestError
from engine.localization import PROFILES
from engine.pack_builder import extract_document, chunks, generate_catalog, sample_catalog, compile_pack


def open_voice():
    if "session" not in st.session_state and st.session_state.get("compiled_pack"):
        st.session_state.speaking_language = st.session_state.compiled_pack["language"]
        st.session_state.pack_choice = "My reviewed demo pack"
    st.session_state.workspace = "Voice verification"


def render_builder(root):
    st.caption("01 / PREPARE THE CONVERSATION")
    st.title("The important details.\nThe right questions.")
    st.write("Turn a document into a focused verification pack. Review the source, choose what to check, then hear the conversation in your customer's language.")
    with st.container(border=True):
        left, right = st.columns([2, 1])
        with left:
            source_mode = st.radio("Start with", ["Example product", "Upload synthetic PDF"], horizontal=True)
        with right:
            language = st.selectbox("Pack language", list(PROFILES), index=2,
                format_func=lambda code: PROFILES[code]["label"], key="builder_language")
            st.caption(f"Voice preview: {PROFILES[language]['voice']} · Timbre v2.5")
        fixture = Path(root) / "output/pdf/nivara_clearcare_fictional_policy.pdf"
        if fixture.exists():
            st.download_button("Download fictional insurance test PDF", fixture.read_bytes(),
                               file_name=fixture.name, mime="application/pdf")
        if source_mode == "Example product":
            scope = "sample:" + language
            if st.session_state.get("catalog_scope") != scope:
                st.session_state.catalog = sample_catalog(language)
                st.session_state.catalog_scope = scope
            st.caption("PREWRITTEN EXAMPLE · Four fictional topics, no document upload or AI generation. Two example core topics are required.")
        else:
            uploaded = st.file_uploader("Upload a fictional policy or product PDF", type=["pdf"], max_upload_size=20)
            st.caption("Text PDFs up to 20 MB / 300 pages. Scanned pages need OCR before upload. Extracted text is sent to your configured text-model provider only when you generate topics.")
            synthetic = st.checkbox("This document contains synthetic product/customer data and no personal information.")
            if uploaded is None:
                st.info("Choose a PDF to extract page text and generate a topic library.")
                return
            try:
                document = extract_document(uploaded.getvalue(), uploaded.name)
            except Exception as exc:
                st.error(str(exc) if isinstance(exc, ValueError) else "The PDF could not be read. Try an unlocked text PDF.")
                return
            scope = document["sha256"] + ":" + language
            requests = len(chunks(document))
            st.caption(f"{len(document['pages'])} readable pages · {requests} topic-generation request(s), plus up to 1 source-review request for documents under 60,000 text characters. Quotes are checked against their cited pages.")
            configured = bool(os.getenv("SCORER_API_KEY") and os.getenv("SCORER_MODEL"))
            if not configured:
                st.info("Add SCORER_API_KEY and SCORER_MODEL in Streamlit Secrets to generate topics. The example workspace works without keys.")
            if st.button("Generate topic library", type="primary", disabled=not synthetic or not configured):
                bar = st.progress(0, text="Reading source pages…")
                try:
                    catalog = generate_catalog(document, language,
                        progress=lambda n,total: bar.progress(n/total, text=f"Processed {n} of {total} document chunks"))
                    st.session_state.catalog = catalog
                    st.session_state.catalog_scope = scope
                    st.rerun()
                except ModelRequestError as exc:
                    st.error(str(exc))
                    st.caption("Generation stopped. No new library was accepted and no automatic retry was made.")
                except Exception as exc:
                    st.error(f"Topic generation stopped ({type(exc).__name__}). No new library was accepted. Check the document/configuration and retry explicitly.")
            if st.session_state.get("catalog_scope") != scope:
                return
    catalog = st.session_state.catalog
    state_key = catalog["document"]["sha256"][:12] + language + catalog["generated_at"]
    selection_key = "selected:" + state_key
    if selection_key not in st.session_state:
        st.session_state[selection_key] = {t["id"] for t in catalog["topics"] if t["required"]}
    selected = st.session_state[selection_key]
    selected.update(t["id"] for t in catalog["topics"] if t["required"])
    topics = catalog["topics"]
    m1,m2,m3 = st.columns(3)
    m1.metric("Topics to review", len(topics))
    m2.metric("In your pack", len(selected))
    m3.metric("Not selected", len(topics)-len(selected))
    st.divider()
    library, preview = st.columns([1.65, 1], gap="large")
    with library:
        st.subheader("Topic library")
        search = st.text_input("Search topics", placeholder="Search payments, exclusions, cancellation…")
        category = st.selectbox("Category", ["All categories"] + sorted({t["category"] for t in topics}))
        shown = 0
        for topic in topics:
            if category != "All categories" and topic["category"] != category:
                continue
            if search.casefold() not in (topic["title"] + " " + topic["summary"] + " " + topic["category"]).casefold():
                continue
            shown += 1
            with st.container(border=True):
                title, action = st.columns([5,1])
                with title:
                    status = "REQUIRED CORE" if topic["required"] else "SUGGESTED IMPORTANT" if topic["risk"] == "high" else "OPTIONAL"
                    st.caption(f"{topic['category'].upper()} · {status}")
                    st.markdown("**" + topic["title"] + "**")
                with action:
                    included = topic["id"] in selected
                    if st.button("✓" if included else "+", key="add:" + state_key + topic["id"],
                                 disabled=topic["required"], help="Required core topic" if topic["required"] else "Remove from pack" if included else "Add to pack", use_container_width=True):
                        if included:
                            selected.remove(topic["id"])
                        else:
                            selected.add(topic["id"])
                        st.rerun()
                st.write(topic["summary"])
                st.caption("Question: " + topic["question"])
                with st.expander("Source & assessment rubric"):
                    for source in topic["sources"]:
                        st.caption(("Sample text section " if catalog["document"]["kind"] == "sample_text" else "PDF page ") + str(source["page"]))
                        st.text(source["quote"])
                    st.write("Required understanding")
                    for fact in topic["must_have_facts"]:
                        st.write("• " + fact)
                    st.write("Misconceptions to catch")
                    for misconception in topic["misconceptions"]:
                        st.write("• " + misconception)
                    st.caption("Reviewer cue: " + topic["risk_reason"])
                    st.caption("Simpler explanation: " + topic["fallback_explain"])
        if not shown:
            st.info("No topics match these filters. Your pack selection is unchanged.")
    with preview:
        st.subheader("Your verification pack")
        st.caption(f"{PROFILES[language]['label']} · {PROFILES[language]['voice']} · selected topics only")
        if not selected:
            st.info("Add a topic with + to begin.")
        for n, topic in enumerate((t for t in topics if t["id"] in selected), 1):
            with st.container(border=True):
                st.markdown(f"**{n:02d} / {topic['title']}**")
                st.write(topic["question"])
        with st.expander("Not selected / omission record", expanded=False):
            reasons = {}
            for topic in topics:
                if topic["id"] not in selected:
                    reasons[topic["id"]] = st.text_input("Reason to exclude: " + topic["title"], key="exclude:" + state_key + topic["id"])
            if not reasons:
                st.write("Every extracted topic is included.")
        st.caption("Only selected topics will be checked. Passing this pack does not establish understanding of the entire document.")
        if catalog["document"]["kind"] != "sample_text":
            st.caption("No company-approved core has been configured for this uploaded document. Risk labels are model suggestions; this demo has no authenticated reviewer roles.")
        if catalog["unresolved"]:
            st.warning("Unresolved source details prevent creating a runnable pack.")
            for issue in catalog["unresolved"]:
                st.write("• " + issue)
        reviewer = st.text_input("Reviewer name", key="reviewer:" + state_key)
        checked = st.checkbox("I reviewed the source, wording and exclusions.", key="reviewed:" + state_key)
        if st.button("Save reviewed demo pack", type="primary", disabled=not checked):
            try:
                pack = compile_pack(catalog, selected, reviewer, reasons)
                path = Path(root) / "data" / "packs"
                path.mkdir(parents=True, exist_ok=True)
                (path / (pack["review_hash"] + ".json")).write_text(json.dumps(pack, ensure_ascii=False, indent=2))
                st.session_state.compiled_pack = pack
                st.success("Pack saved. It remains a demo draft with a self-attested review record.")
            except ValueError as exc:
                st.error(str(exc))
        pack = st.session_state.get("compiled_pack")
        if pack:
            st.caption(f"Saved pack: {pack['product']} · {PROFILES[pack['language']]['label']} · {len(pack['clauses'])} topics")
            st.download_button("Download saved pack + omission record", json.dumps(pack, ensure_ascii=False, indent=2),
                               file_name="hmh-reviewed-demo-pack.json", mime="application/json")
            st.button("Open voice verification →", on_click=open_voice)
    with st.expander("Document processing & provenance"):
        st.caption(catalog["coverage"])
        st.caption(f"Source: {catalog['document']['name']} · SHA-256: {catalog['document']['sha256']}")
        st.download_button("Download topic library", json.dumps(catalog, ensure_ascii=False, indent=2),
                           file_name="hmh-topic-library.json", mime="application/json")
