from error_utils import humanize_error
from queue_controls import provider_blocker


ERROR = "Error code: 400 - {'type': 'error', 'error': {'type': 'invalid_request_error', 'message': 'You have reached your specified API usage limits. You will regain access on 2026-10-01 at 00:00 UTC.'}, 'request_id': 'private-request-id'}"


def test_anthropic_usage_limit_keeps_action_and_reset_without_raw_provider_body():
    safe = humanize_error(ERROR)
    assert "Anthropic" in safe and "usage limit" in safe
    assert "2026-10-01" in safe and "00:00 UTC" in safe
    assert "request_id" not in safe and "private-request-id" not in safe
    blocker = provider_blocker(safe)
    assert blocker["provider"] == "Anthropic"
    assert "limit" in blocker["reason"]


def test_raw_anthropic_limit_pauses_shared_queue_without_mislabeling_credentials():
    blocker = provider_blocker(ERROR)
    assert blocker["provider"] == "Anthropic"
    assert "credentials" not in blocker["reason"]
