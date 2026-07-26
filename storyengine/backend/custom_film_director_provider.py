"""Production single-request text adapters for Custom Film direction.

Every ``execute_once`` invocation issues exactly one provider request. There is
no transport retry, tool fallback, streaming reconnect, or hidden repair. The
caller must durably claim the operation before invoking this module.
"""

from __future__ import annotations

import asyncio
import json
import os
from collections.abc import Mapping
from typing import Any

from actions import CLAUDE_MODELS
from custom_film_contract import CustomFilmContractError
from kie_unified import AnthropicDirectClient, KieClaudeClient, _extract_text

DIRECTOR_MODEL = CLAUDE_MODELS["anthropic"]["smart"]
MAX_DIRECTOR_INPUT_BYTES = 200_000
TOKEN_RATE_ENV = "CUSTOM_FILM_DIRECTOR_TOKEN_RATES_JSON"
NANOUSD_PER_CENT = 10_000_000

PROVIDER_RATE_KEYS = ("anthropic", "kie")
RATE_KEYS = ("input_nusd_per_token", "output_nusd_per_token")


def _provider_error(message: str) -> CustomFilmContractError:
    return CustomFilmContractError(
        f"{message}; no additional director attempt is authorized"
    )


def configured_token_rates() -> dict[str, dict[str, int]]:
    """Load exact deployment-owned token rates in nano-USD per token."""
    raw = os.getenv(TOKEN_RATE_ENV, "").strip()
    if not raw:
        raise _provider_error(
            f"Custom Film director token rates are not configured in {TOKEN_RATE_ENV}"
        )
    try:
        parsed = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise _provider_error(
            "Custom Film director token rates are invalid JSON"
        ) from exc
    if not isinstance(parsed, Mapping) or set(parsed) != set(PROVIDER_RATE_KEYS):
        raise _provider_error(
            "Custom Film director token rate providers are incomplete"
        )
    normalized: dict[str, dict[str, int]] = {}
    for provider in PROVIDER_RATE_KEYS:
        rates = parsed[provider]
        if not isinstance(rates, Mapping) or set(rates) != set(RATE_KEYS):
            raise _provider_error(
                f"Custom Film director {provider} token rates are incomplete"
            )
        normalized[provider] = {}
        for key in RATE_KEYS:
            value = rates[key]
            if type(value) is not int or not 1 <= value <= 1_000_000:
                raise _provider_error(
                    f"Custom Film director {provider} {key} is invalid"
                )
            normalized[provider][key] = value
    return normalized


def maximum_operation_cents(
    *,
    max_tokens: int,
    provider: str,
    rates: Mapping[str, Mapping[str, int]] | None = None,
) -> int:
    """Return the hard whole-cent ceiling for one capped request."""
    if type(max_tokens) is not int or not 1 <= max_tokens <= 8_192:
        raise _provider_error("Custom Film director output token cap is invalid")
    configured = dict(rates or configured_token_rates())
    if provider not in configured:
        raise _provider_error("Custom Film director provider rate is unavailable")
    rate = configured[provider]
    maximum_nusd = MAX_DIRECTOR_INPUT_BYTES * int(
        rate["input_nusd_per_token"]
    ) + max_tokens * int(rate["output_nusd_per_token"])
    return (maximum_nusd + NANOUSD_PER_CENT - 1) // NANOUSD_PER_CENT


def _field(value: Any, key: str) -> Any:
    if isinstance(value, Mapping):
        return value.get(key)
    return getattr(value, key, None)


def _usage(response: Any) -> tuple[int, int]:
    usage = _field(response, "usage")
    input_tokens = _field(usage, "input_tokens")
    output_tokens = _field(usage, "output_tokens")
    if (
        type(input_tokens) is not int
        or input_tokens < 0
        or type(output_tokens) is not int
        or output_tokens < 0
    ):
        raise _provider_error("Custom Film director provider usage is incomplete")
    return input_tokens, output_tokens


class ProductionSingleAttemptTextClient:
    """Adapt the resolved tenant client without inheriting its retry helpers."""

    def __init__(
        self,
        client: AnthropicDirectClient | KieClaudeClient,
        *,
        rates: Mapping[str, Mapping[str, int]] | None = None,
    ):
        if isinstance(client, AnthropicDirectClient):
            self.provider = "anthropic"
        elif isinstance(client, KieClaudeClient):
            self.provider = "kie"
        else:
            raise _provider_error("Custom Film director text client is unsupported")
        self.client = client
        self.rates = dict(rates or configured_token_rates())

    async def execute_once(
        self,
        *,
        operation: Mapping[str, Any],
        prompt: str,
        system_prompt: str,
        max_tokens: int,
    ) -> Mapping[str, Any]:
        request_bytes = len(prompt.encode("utf-8")) + len(system_prompt.encode("utf-8"))
        if request_bytes > MAX_DIRECTOR_INPUT_BYTES:
            raise _provider_error("Custom Film director request exceeds its input cap")
        allowed_cents = maximum_operation_cents(
            max_tokens=max_tokens,
            provider=self.provider,
            rates=self.rates,
        )
        if int(operation.get("unit_max_cents") or -1) < allowed_cents:
            raise _provider_error(
                "Custom Film director price book does not cover this request"
            )

        kwargs = {
            "model": DIRECTOR_MODEL,
            "max_tokens": max_tokens,
            "temperature": 0,
            "messages": [{"role": "user", "content": prompt}],
            "system": system_prompt,
        }
        if self.provider == "kie":
            # create_message_async performs one POST when tools are absent.
            response = await self.client.create_message_async(**kwargs)
        else:
            # The SDK call itself is the one provider request. Do not call the
            # wrapper's generate helper because it discards usage metadata.
            # Anthropic's default SDK client retries transports; create an
            # explicit zero-retry client for this authorization boundary.
            from anthropic import Anthropic

            def _anthropic_request() -> Any:
                with Anthropic(
                    api_key=self.client.api_key,
                    max_retries=0,
                ) as zero_retry_client:
                    return zero_retry_client.messages.create(**kwargs)

            response = await asyncio.to_thread(_anthropic_request)

        text = _extract_text(response)
        request_id = _field(response, "id")
        model = _field(response, "model")
        raw_finish_reason = _field(response, "stop_reason") or _field(
            response, "finish_reason"
        )
        finish_reason = (
            "stop" if raw_finish_reason in {"end_turn", "stop"} else raw_finish_reason
        )
        input_tokens, output_tokens = _usage(response)
        if (
            not text
            or not isinstance(request_id, str)
            or not request_id.strip()
            or not isinstance(model, str)
            or not model.strip()
            or not isinstance(finish_reason, str)
            or not finish_reason.strip()
        ):
            raise _provider_error("Custom Film director provider receipt is incomplete")
        rate = self.rates[self.provider]
        actual_cost_nusd = input_tokens * int(
            rate["input_nusd_per_token"]
        ) + output_tokens * int(rate["output_nusd_per_token"])
        actual_cost_cents = (
            actual_cost_nusd + NANOUSD_PER_CENT - 1
        ) // NANOUSD_PER_CENT
        return {
            "request_id": request_id,
            "model": model,
            "attempt_count": 1,
            "input_tokens": input_tokens,
            "output_tokens": output_tokens,
            "actual_cost_nusd": actual_cost_nusd,
            "actual_cost_cents": actual_cost_cents,
            "finish_reason": finish_reason,
            "text": text,
        }
