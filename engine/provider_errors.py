"""Actionable provider diagnostics without exposing keys, prompts or raw bodies."""

class ModelRequestError(RuntimeError):
    def __init__(self, status, code, action):
        self.status, self.code, self.action = status, code, action
        super().__init__(f"Text-model request rejected (HTTP {status}, {code}). {action}")


def check_model_response(response):
    if response.is_success:
        return
    try:
        error = response.json().get("error", {})
        if not isinstance(error, dict):
            error = {}
    except (ValueError, AttributeError):
        error = {}
    raw_code = error.get("code")
    allowed_codes = {
        "invalid_api_key", "model_not_found", "insufficient_quota", "rate_limit_exceeded",
        "billing_hard_limit_reached", "project_spend_limit_exceeded", "organization_spend_limit_exceeded",
        "credit_balance_exhausted", "usage_limit_reached", "unsupported_parameter", "invalid_value",
        "context_length_exceeded", "permission_denied", "country_not_supported", "slow_down",
    }
    code = raw_code if isinstance(raw_code, str) and raw_code in allowed_codes else "provider_error"
    status = response.status_code
    if status == 401 or code == "invalid_api_key":
        action = ("The text-model provider did not accept SCORER_API_KEY. Replace it with a valid key "
                  "for SCORER_BASE_URL; a Gnani key cannot authenticate to OpenAI. "
                  "Save and restart/reboot this app. Do not share the key in chat or GitHub.")
    elif code in {"insufficient_quota", "billing_hard_limit_reached", "credit_balance_exhausted", "usage_limit_reached",
                   "project_spend_limit_exceeded", "organization_spend_limit_exceeded"}:
        action = "Check credits, billing and spend limits for the text-model project. Gnani credits do not fund this provider. Retrying alone will not restore quota."
    elif status == 429:
        action = "The text-model provider is limiting request traffic. Wait and retry explicitly, or check the project's rate limits."
    elif status == 404 or code == "model_not_found":
        action = "Check SCORER_MODEL and SCORER_BASE_URL, and confirm that this key's project can access that model."
    elif status == 403:
        action = "Check model permissions, project access and provider availability for this account."
    elif status == 400:
        action = "The provider rejected the request format. Check that this model and endpoint support Chat Completions with JSON-object responses."
    elif status >= 500:
        action = "The text-model provider reported a service error. Retry explicitly later."
    else:
        action = "Check the text-model provider's dashboard and the configured endpoint."
    # Never include response.text, headers, request URL, or the provider's raw
    # message: authentication errors can repeat the rejected API key there.
    raise ModelRequestError(status, code, action)
