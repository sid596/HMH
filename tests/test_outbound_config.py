import os
import unittest
from unittest.mock import patch
from app.outbound import call_setting, health_error

class OutboundConfigurationTests(unittest.TestCase):
    def test_streamlit_secret_overrides_stale_environment_and_trims_whitespace(self):
        with patch.dict(os.environ, {"HMH_CALL_API_TOKEN":"old-process-value"}), patch("app.outbound.st.secrets", {"HMH_CALL_API_TOKEN":"  current-secret\n"}):
            self.assertEqual(call_setting("HMH_CALL_API_TOKEN"), "current-secret")

    def test_environment_fallback(self):
        with patch.dict(os.environ, {"HMH_CALL_API_URL":" http://127.0.0.1:8000 "}), patch("app.outbound.st.secrets", {}):
            self.assertEqual(call_setting("HMH_CALL_API_URL"), "http://127.0.0.1:8000")

    def test_tunnel_errors_are_not_reported_as_token_rejections(self):
        self.assertIn("rejected the call token", health_error(401))
        self.assertIn("HTTP 404", health_error(404))
        self.assertIn("unavailable", health_error(502))
        self.assertNotIn("rejected the call token", health_error(403))
