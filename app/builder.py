"""Document review workspace; draft content never silently enters a customer session."""
import json
import os
from pathlib import Path
import streamlit as st
from engine.provider_errors import ModelRequestError
from engine.localization import PROFILES
from engine.pack_builder import extract_document, chunks, generate_catalog, sample_catalog, compile_pack, ranked_topics, MAX_QUESTIONS, TopicValidationError, strict_topic_output_enabled, TOPIC_PROMPT_VERSION, unresolved_issues
from app.recording import recording_panel
from app.outbound import render_outbound


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
            requested_language = st.selectbox("Customer language", ["auto"] + list(PROFILES),
                format_func=lambda code: "Automatic - use document language" if code == "auto" else PROFILES[code]["label"], key="builder_language")
            language = "en-IN" if requested_language == "auto" else requested_language
            st.caption("Automatic detects the PDF language. Selecting English or another language skips detection and sets the questions and voice.")
        fixture = Path(root) / "output/pdf/nivara_clearcare_fictional_policy.pdf"
        if fixture.exists():
            st.download_button("Download fictional insurance test PDF", fixture.read_bytes(),
                               file_name=fixture.name, mime="application/pdf")
        if source_mode == "Example product":
            scope = "sample:" + requested_language
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
                pdf_content=uploaded.getvalue()
                pdf_key=__import__("hashlib").sha256(pdf_content).hexdigest()
                cached_doc=st.session_state.get("extracted_pdf")
                if not cached_doc or cached_doc[0]!=pdf_key:
                    cached_doc=(pdf_key,extract_document(pdf_content,uploaded.name))
                    st.session_state.extracted_pdf=cached_doc
                document={**cached_doc[1],"name":uploaded.name}
            except Exception as exc:
                st.error(str(exc) if isinstance(exc, ValueError) else "The PDF could not be read. Try an unlocked text PDF.")
                return
            scope = document["sha256"] + ":" + requested_language
            requests = len(chunks(document))
            st.caption(f"{len(document['pages'])} readable pages · {requests} sections, processed in parallel. Automatic language detection and cross-reference checks may add requests. Repeated results are reused within this session.")
            configured = bool(os.getenv("SCORER_API_KEY") and os.getenv("SCORER_MODEL"))
            output_mode="strict schema" if strict_topic_output_enabled() else "JSON with local validation"
            st.caption(f"Topic engine: {TOPIC_PROMPT_VERSION} · Model: {os.getenv('SCORER_MODEL','not configured')} · {output_mode}")
            if not configured:
                st.info("Add SCORER_API_KEY and SCORER_MODEL in Streamlit Secrets to generate topics. The example workspace works without keys.")
            if st.button("Generate topic library", type="primary", disabled=not synthetic or not configured):
                bar = st.progress(0, text="Detecting language and generating topic drafts…")
                try:
                    cache = st.session_state.setdefault("topic_generation_cache",{})
                    catalog = generate_catalog(document, requested_language, cache=cache,
                        progress=lambda n,total: bar.progress(n/total, text=f"Generated topics for {n} of {total} sections"))
                    st.session_state.catalog = catalog
                    st.session_state.catalog_scope = scope
                    st.rerun()
                except ModelRequestError as exc:
                    st.error(str(exc))
                    st.caption("Generation stopped. No new library was accepted and no automatic retry was made.")
                except TopicValidationError as exc:
                    st.error("Topic generation stopped: " + str(exc))
                    st.caption("No new library was accepted. Completed sections are kept in this session; retry explicitly to regenerate failed sections.")
                except Exception as exc:
                    st.error(f"Topic generation stopped ({type(exc).__name__}). No new library was accepted. Check the document/configuration and retry explicitly.")
            if st.session_state.get("catalog_scope") != scope:
                return
    catalog = st.session_state.catalog
    old_issues=catalog["unresolved"]
    catalog["unresolved"]=unresolved_issues(old_issues)
    catalog["generation_notes"]=list(dict.fromkeys(catalog.get("generation_notes",[])+[x for x in old_issues if x not in catalog["unresolved"]]))
    if catalog["document"]["kind"] != "sample_text" and catalog.get("prompt_version") not in {TOPIC_PROMPT_VERSION,"topic-draft-10-language-guard"}:
        st.warning("This topic draft predates the latest validation checks. Generate the topic library again before reviewing or calling.")
        return
    language = catalog["language"]
    performance = catalog.get("performance")
    if performance:
        if performance["cache_hit"]:
            st.caption("Loaded saved results for this document and language. No new topic-generation requests were needed.")
        else:
            st.caption(f"Topic drafts generated in {performance['total_generation_seconds']:.1f} seconds · Source checks completed")
    st.caption(f"Question language: {PROFILES[language]['label']} · Voice: {PROFILES[language]['voice']} · Limit: 15 questions, including retries during verification")
    recording_panel(catalog)
    catalog = st.session_state.catalog
    state_key = catalog["document"]["sha256"][:12] + language + catalog["generated_at"]
    selection_key = "selected:" + state_key
    if selection_key not in st.session_state:
        st.session_state[selection_key] = {t["id"] for t in catalog["topics"] if t["required"]}
    selected = st.session_state[selection_key]
    selected.update(t["id"] for t in catalog["topics"] if t["required"])
    topics = ranked_topics(catalog)
    call_context=catalog.get("call_context",{})
    direct_ids={n["topic_id"] for n in call_context.get("notes",[]) if n["kind"]!="mentioned"}
    related=call_context.get("related_topics",[])
    by_id={t["id"]:t for t in topics}
    omitted_context=(direct_ids|{r["topic_id"] for r in related})-selected
    if omitted_context:
        st.info(f"{len(omitted_context)} call-related topics are not selected. Review the highlighted cards; they will not be asked unless added to the pack.")
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
                                 disabled=topic["required"] or (not included and len(selected)>=MAX_QUESTIONS), help="Required core topic" if topic["required"] else "Remove from pack" if included else "Add to pack", use_container_width=True):
                        if included:
                            selected.remove(topic["id"])
                        else:
                            selected.add(topic["id"])
                        st.rerun()
                if topic["id"] in direct_ids:
                    st.caption("↑ DIRECT CALL CONTEXT · Evidence found in the reviewed conversation")
                elif any(r["topic_id"]==topic["id"] for r in related):
                    for relation in related:
                        if relation["topic_id"]==topic["id"]:
                            anchor=by_id[relation["anchor_topic_id"]]
                            st.caption("↑ RELATED TO: "+anchor["title"]+" · "+relation["relationship"])
                            st.caption(relation["reason"])
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
                    for note in catalog.get("call_context",{}).get("notes",[]):
                        if note["topic_id"] == topic["id"]:
                            st.write("Prior call: " + note["observation"])
                            st.caption(note["quote"])
                    st.caption("Simpler explanation: " + topic["fallback_explain"])
        if not shown:
            st.info("No topics match these filters. Your pack selection is unchanged.")
    with preview:
        st.subheader("Your verification pack")
        st.caption(f"{len(selected)} / {MAX_QUESTIONS} questions selected. Required core first, important topics next, optional topics last.")
        st.caption(f"{PROFILES[language]['label']} · {PROFILES[language]['voice']} · selected topics only")
        if not selected:
            st.info("Add a topic with + to begin.")
        for n, topic in enumerate((t for t in topics if t["id"] in selected), 1):
            with st.container(border=True):
                st.markdown(f"**{n:02d} / {topic['title']}**")
                st.write(topic["question"])
        with st.expander("Topics not selected", expanded=False):
            excluded = [topic for topic in topics if topic["id"] not in selected]
            for topic in excluded:
                st.write("• " + topic["title"])
            if not excluded:
                st.write("Every extracted topic is included.")
            st.caption("These topics are recorded automatically in the pack. No exclusion reasons are required.")
        st.caption("Only selected topics will be checked. Passing this pack does not establish understanding of the entire document.")
        if catalog["document"]["kind"] != "sample_text":
            st.caption("No company-approved core has been configured for this uploaded document. Risk labels are model suggestions; this demo has no authenticated reviewer roles.")
        if catalog["unresolved"]:
            st.warning("Unresolved source details prevent creating a runnable pack.")
            for issue in catalog["unresolved"]:
                st.write("• " + issue)
        reviewer = st.text_input("Reviewer name", key="reviewer:" + state_key)
        checked = st.checkbox("I reviewed the source, wording and exclusions.", key="reviewed:" + state_key)
        if st.button("Save reviewed demo pack", type="primary", disabled=not checked or len(selected)>MAX_QUESTIONS or bool(catalog["unresolved"])):
            try:
                pack = compile_pack(catalog, selected, reviewer)
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
            render_outbound(pack)
    with st.expander("Document processing & provenance"):
        st.caption(catalog["coverage"])
        st.caption(f"Source: {catalog['document']['name']} · SHA-256: {catalog['document']['sha256']}")
        st.download_button("Download topic library", json.dumps(catalog, ensure_ascii=False, indent=2),
                           file_name="hmh-topic-library.json", mime="application/json")
