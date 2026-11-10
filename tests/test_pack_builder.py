from copy import deepcopy
import unittest
from unittest.mock import Mock
from engine.pack_builder import sample_catalog, compile_pack, generate_catalog, validate_topics, chunks

class PackBuilderTests(unittest.TestCase):
    def test_required_core_cannot_be_omitted(self):
        catalog = sample_catalog("en-IN")
        with self.assertRaisesRegex(ValueError, "Required"):
            compile_pack(catalog, {"contribution"}, "Demo reviewer", {})

    def test_exclusion_needs_no_reason_and_optional_reason_is_preserved(self):
        catalog = sample_catalog("mr-IN")
        selected = {"contribution", "returns", "early_exit"}
        no_reason = compile_pack(catalog, selected, "Demo reviewer")
        self.assertIsNone(no_reason["review_record"]["excluded_topics"][0]["reason"])
        self.assertEqual(no_reason["review_record"]["excluded_topics"][0]["selection_status"], "not_selected")
        pack = compile_pack(catalog, selected, "Demo reviewer", {"cancellation": "Reviewed separately in the demo"})
        self.assertEqual(len(pack["clauses"]), 3)
        self.assertEqual(pack["language"], "mr-IN")
        self.assertEqual(pack["approval"]["status"], "draft")
        self.assertEqual(pack["review_record"]["excluded_topics"][0]["id"], "cancellation")
        self.assertEqual(len(pack["review_record"]["catalog_snapshot"]), 4)
        self.assertTrue(all(c["critical"] for c in pack["clauses"]))

    def test_unresolved_details_prevent_runnable_pack(self):
        catalog = sample_catalog("en-IN")
        catalog["unresolved"] = ["Customer-specific premium missing"]
        with self.assertRaisesRegex(ValueError, "Resolve"):
            compile_pack(catalog, {t["id"] for t in catalog["topics"]}, "Reviewer", {})

    def test_fabricated_quote_rejected(self):
        catalog = sample_catalog("en-IN")
        topic = deepcopy(catalog["topics"][0])
        topic["sources"][0]["quote"] = "This quote is not in the actual document at all."
        with self.assertRaisesRegex(ValueError, "quote"):
            validate_topics({"topics": [topic], "unresolved": []}, catalog["document"]["pages"])

    def test_generator_does_not_assign_mandatory_status(self):
        catalog = sample_catalog("en-IN")
        caller = Mock(return_value={"topics": deepcopy(catalog["topics"]), "unresolved": []})
        result = generate_catalog(catalog["document"], "en-IN", caller=caller)
        self.assertEqual(len(result["topics"]), 4)
        self.assertFalse(any(t["required"] for t in result["topics"]))
        self.assertEqual(caller.call_count, 1)

    def test_long_pages_are_not_silently_truncated(self):
        doc = {"pages": [{"page":1, "text":"abc "*20000}, {"page":2,"text":"last page"}]}
        batches = chunks(doc)
        reconstructed = "".join(p["text"] for b in batches for p in b)
        self.assertEqual(reconstructed, "".join(p["text"] for p in doc["pages"]))

    def test_two_parts_on_same_page_validate_both(self):
        catalog = sample_catalog("en-IN")
        topic = catalog["topics"][0]
        source = topic["sources"][0]
        validate_topics({"topics":[topic], "unresolved":[]}, [{"page":1,"text":source["quote"]}, {"page":1,"text":"More text on that same page."}])

    def test_json_mode_explicitly_requests_json_even_for_plain_system_prompt(self):
        import os
        import httpx
        from unittest.mock import patch
        from engine.pack_builder import model_json
        response = httpx.Response(200, json={"choices":[{"message":{"content":"{\"ok\":true}"}}]})
        with patch.dict(os.environ, {"SCORER_API_KEY":"unit-test-key", "SCORER_MODEL":"gpt-6-luna"}), patch("httpx.post", return_value=response) as post:
            self.assertEqual(model_json("Extract topics.", {"language":"English"}), {"ok":True})
            request = post.call_args.kwargs["json"]
            self.assertEqual(request["response_format"], {"type":"json_object"})
            self.assertIn("JSON", request["messages"][0]["content"])

    def test_missing_context_flag_requires_real_full_source_evidence_to_clear(self):
        from engine.pack_builder import resolve_source_issues
        catalog = sample_catalog("en-IN")
        issues = ["Schedule missing from this chunk", "A genuinely unspecified customer detail"]
        quote = catalog["document"]["pages"][0]["text"]
        caller = Mock(return_value={"resolved":[{"issue_index":0,"sources":[{"page":1,"quote":quote}]}]})
        remaining, resolved = resolve_source_issues(catalog["document"], issues, caller)
        self.assertEqual(remaining, [issues[1]])
        self.assertEqual(resolved[0]["issue"], issues[0])
        caller.return_value = {"resolved":[{"issue_index":0,"sources":[{"page":1,"quote":"A fabricated source passage does not count"}]}]}
        with self.assertRaises(ValueError):
            resolve_source_issues(catalog["document"], issues, caller)

    def test_parallel_sections_and_session_cache_preserve_order_and_isolation(self):
        from threading import Barrier
        barrier = Barrier(3)
        base = sample_catalog("en-IN")
        template = base["topics"][0]
        quote = template["sources"][0]["quote"]
        document = {"sha256":"parallel-fixture", "name":"fixture", "pages":[
            {"page":n,"text":quote + " " + "x"*5200} for n in range(1,4)]}
        calls = []
        def caller(system, payload):
            page = payload["pages"][0]["page"]
            calls.append(page)
            barrier.wait(timeout=5)
            topic = deepcopy(template)
            topic["title"] = f"Topic {page}"
            topic["sources"] = [{"page":page,"quote":quote}]
            return {"topics":[topic],"unresolved":[]}
        cache = {}
        first = generate_catalog(document,"en-IN",caller=caller,cache=cache,max_workers=3)
        self.assertEqual([t["title"] for t in first["topics"]],["Topic 1","Topic 2","Topic 3"])
        first["topics"][0]["title"] = "Modified outside cache"
        second = generate_catalog(document,"en-IN",caller=caller,cache=cache,max_workers=3)
        self.assertEqual(len(calls),3)
        self.assertTrue(second["performance"]["cache_hit"])
        self.assertEqual(second["topics"][0]["title"],"Topic 1")

    def test_fast_document_setting_is_scoped_to_supported_provider_and_model(self):
        import os
        from unittest.mock import patch
        from engine.pack_builder import document_reasoning_effort
        with patch.dict(os.environ,{"SCORER_MODEL":"gpt-6-luna", "SCORER_BASE_URL":"https://api.openai.com/v1"},clear=True):
            self.assertEqual(document_reasoning_effort(),"none")
            with patch.dict(os.environ,{"SCORER_BASE_URL":"https://example.com/v1"}):
                self.assertIsNone(document_reasoning_effort())
            with patch.dict(os.environ,{"SCORER_MODEL":"another-model"}):
                self.assertIsNone(document_reasoning_effort())

    def test_failed_section_has_safe_actionable_error_and_keeps_valid_sections(self):
        from engine.pack_builder import TopicValidationError
        base=sample_catalog('en-IN')
        quote=base['topics'][0]['sources'][0]['quote']
        doc={'sha256':'invalid-section-fixture','name':'fixture','pages':[
            {'page':n,'text':quote+' '+'x'*5200} for n in (1,2)]}
        def caller(system,payload):
            page=payload['pages'][0]['page']
            topic=deepcopy(base['topics'][0]);topic['sources']=[{'page':page,'quote':quote}]
            if page==2:topic['sources'][0]['quote']='An invented quote which is absent from the page'
            return {'topics':[topic],'unresolved':[]}
        cache={}
        with self.assertRaisesRegex(TopicValidationError,'Pages 2: A generated source quote'):
            generate_catalog(doc,'en-IN',caller=caller,cache=cache)
        self.assertEqual(len([k for k in cache if ':batch:' in k]),1)
        self.assertFalse(any(':catalog:' in k for k in cache))

    def test_language_detection_uses_supplied_excerpt_id_without_quote_copying(self):
        from engine.pack_builder import detect_document_language, TopicValidationError
        document=sample_catalog("en-IN")["document"]
        caller=Mock(return_value={"language":"en-IN","evidence_id":0})
        self.assertEqual(detect_document_language(document,caller),"en-IN")
        caller.return_value={"language":"en-IN","evidence_id":99}
        with self.assertRaises(TopicValidationError):detect_document_language(document,caller)
        caller.return_value={"language":"unsupported","evidence_id":0}
        with self.assertRaises(TopicValidationError):detect_document_language(document,caller)

    def test_explicit_english_does_not_call_language_detection(self):
        from unittest.mock import patch
        catalog=sample_catalog("en-IN")
        caller=Mock(return_value={"topics":deepcopy(catalog["topics"]),"unresolved":[]})
        with patch("engine.pack_builder.detect_document_language",side_effect=AssertionError("Must skip detection")):
            result=generate_catalog(catalog["document"],"en-IN",caller=caller)
        self.assertEqual(result["language"],"en-IN")
