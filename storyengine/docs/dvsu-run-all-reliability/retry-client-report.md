# Single-submit client evidence

- Added backward-compatible `no_resubmit=False` to `AnthropicClient.generate`.
- With `no_resubmit=True`, requests use a per-request `with_options(max_retries=0)` client and make one direct create or gateway stream call. It bypasses the outer transient retry loop and empty-content retry; an empty response fails after that one request.
- The shared default client and normal retry behavior are unchanged. `complete_response` is refused in single-submit mode because continuation can make multiple requests.

Verification: `backend/venv/bin/python -m pytest backend/tests/test_anthropic_no_resubmit.py -q` — 6 passed. Full output: `retry-client-tests.log`.
