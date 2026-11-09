import unittest
import httpx
from engine.provider_errors import ModelRequestError, check_model_response

class ProviderErrorTests(unittest.TestCase):
    def test_invalid_key_has_actionable_message_but_no_secret(self):
        response = httpx.Response(401, json={"error": {"code": "invalid_api_key", "message": "Incorrect key: sk-test-super-secret"}})
        with self.assertRaises(ModelRequestError) as caught:
            check_model_response(response)
        message = str(caught.exception)
        self.assertIn("HTTP 401", message)
        self.assertIn("SCORER_API_KEY", message)
        self.assertNotIn("sk-test-super-secret", message)

    def test_billing_is_not_misreported_as_transient_rate_limit(self):
        response = httpx.Response(429, json={"error": {"code": "insufficient_quota"}})
        with self.assertRaises(ModelRequestError) as caught:
            check_model_response(response)
        self.assertIn("billing", str(caught.exception))
        self.assertIn("Retrying alone", str(caught.exception))

    def test_unknown_error_body_never_reaches_ui(self):
        response = httpx.Response(400, json={"error": {"code": "sk-secret-in-error-code", "message": "private prompt"}})
        with self.assertRaises(ModelRequestError) as caught:
            check_model_response(response)
        self.assertIn("provider_error", str(caught.exception))
        self.assertNotIn("sk-secret", str(caught.exception))
        self.assertNotIn("private prompt", str(caught.exception))

    def test_plaintext_error_is_safe(self):
        response = httpx.Response(502, text="secret upstream debugging details")
        with self.assertRaises(ModelRequestError) as caught:
            check_model_response(response)
        self.assertNotIn("upstream debugging", str(caught.exception))

    def test_success_does_not_raise(self):
        self.assertIsNone(check_model_response(httpx.Response(200, json={"ok":True})))
