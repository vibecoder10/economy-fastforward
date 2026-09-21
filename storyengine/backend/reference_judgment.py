"""Schema-bound, checkpointed reference-photo judgments.

This module deliberately knows nothing about provider credentials or candidate
selection.  Its caller supplies the already assembled multimodal ``content``
and provider connection details; the durable checkpoint prevents an interrupted
or malformed comparison from spending more than two requests for that exact
review.
"""
from __future__ import annotations

import asyncio
import hashlib
import json
import os
import tempfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import httpx


_TOOL_NAME = "submit_reference_review"
KIE_LUNA_MODEL = "gpt-5-6-luna"
_LUNA_INSTRUCTIONS = ("You are a careful reviewer of historical reference photographs. "
                      "Follow the user's instructions exactly and return only the requested structured result.")
_CORRECTION = (
    "Your previous response could not be accepted. Return the complete review "
    "using the required schema exactly. Do not omit candidates or scores."
)


def _failure(code: str, reason: str, **flags):
    # The selection module remains the public owner of this typed error.  Lazy
    # importing avoids its database imports when this helper is merely loaded.
    from reference_selection import SelectionFailure
    return SelectionFailure(code, reason, **flags)


def judgment_schema(candidate_ids: list[str]) -> dict[str, Any]:
    """Return the provider schema corresponding exactly to validate_judgment."""
    evidence = {
        "type": "object", "additionalProperties": False,
        "required": ["url", "quote"],
        "properties": {"url": {"type": "string"}, "quote": {"type": "string"}},
    }
    identity = {
        "type": "object", "additionalProperties": False,
        "required": ["status", "reason", "evidence"],
        "properties": {
            "status": {"type": "string", "enum": ["confirmed", "uncertain", "rejected"]},
            "reason": {"type": "string"},
            "evidence": {"type": "array", "items": evidence},
        },
    }
    scores = {
        "type": "object", "additionalProperties": False,
        "required": ["coverage", "features", "sharpness", "unobstructed", "perspective"],
        "properties": {name: {"type": "integer", "enum": [0, 1, 2, 3, 4, 5]}
                       for name in ("coverage", "features", "sharpness", "unobstructed", "perspective")},
    }
    candidate = {
        "type": "object", "additionalProperties": False,
        "required": ["id", "identity", "usable", "scores", "view", "reason", "limitations"],
        "properties": {
            "id": {"type": "string", "enum": candidate_ids},
            "identity": identity,
            "usable": {"type": "boolean"},
            "scores": scores,
            "view": {"type": "string", "enum": ["side", "three_quarter", "front", "rear", "top", "other"]},
            "reason": {"type": "string"},
            "limitations": {"type": "array", "items": {"type": "string"}},
        },
    }
    return {
        "type": "object", "additionalProperties": False,
        "required": ["candidates"],
        "properties": {"candidates": {"type": "array", "items": candidate}},
    }


def _json_fingerprint(value: Any) -> Any:
    """Make request material deterministic without retaining private pixels."""
    if isinstance(value, bytes):
        return {"sha256": hashlib.sha256(value).hexdigest(), "bytes": len(value)}
    if isinstance(value, dict):
        return {str(key): _json_fingerprint(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_json_fingerprint(item) for item in value]
    if isinstance(value, (str, int, float, bool)) or value is None:
        return value
    return str(value)


def _review_root() -> Path:
    return Path(os.getenv("REFERENCE_REVIEW_DIR") or
                Path(__file__).resolve().parents[1] / "data" / "reference-reviews")


def _checkpoint_path(tenant_id: Any, video_id: Any, machine: str, provider: str, model: str,
                     schema: dict[str, Any], content: Any) -> Path:
    material = _json_fingerprint({
        "tenant_id": str(tenant_id), "video_id": str(video_id or ""), "machine": machine,
        "provider": provider, "model": model, "schema": schema, "content": content,
    })
    digest = hashlib.sha256(json.dumps(material, ensure_ascii=False, sort_keys=True,
                                        separators=(",", ":")).encode()).hexdigest()
    root = _review_root()
    root.mkdir(parents=True, exist_ok=True, mode=0o700)
    root.chmod(0o700)
    return root / f"{digest}.json"


def _read_checkpoint(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {}
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        raise _failure("invalid_review", "The saved comparison checkpoint is unreadable.") from exc
    if not isinstance(value, dict):
        raise _failure("invalid_review", "The saved comparison checkpoint is invalid.")
    return value


def _write_checkpoint(path: Path, value: dict[str, Any]) -> None:
    encoded = json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    descriptor, temporary = tempfile.mkstemp(prefix=f".{path.stem}-", suffix=".tmp", dir=path.parent)
    try:
        os.fchmod(descriptor, 0o600)
        with os.fdopen(descriptor, "w", encoding="utf-8") as handle:
            handle.write(encoded)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, path)
        path.chmod(0o600)
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _payload(provider: str, model: str, content: list[dict[str, Any]], schema: dict[str, Any], max_tokens: int) -> dict[str, Any]:
    if provider == "kie_luna":
        # Kie's Responses-style route: schema-bound output comes from text.format, not a forced tool.
        # `instructions` replaces the route's default "Codex coding agent" system prompt.
        return {"model": model, "stream": False, "max_output_tokens": max_tokens,
                "instructions": _LUNA_INSTRUCTIONS, "reasoning": {"effort": "medium"},
                "text": {"format": {"type": "json_schema", "name": _TOOL_NAME, "strict": True, "schema": schema}},
                "input": [{"role": "user", "content": content}]}
    payload = {"model": model, "max_tokens": max_tokens, "messages": [{"role": "user", "content": content}]}
    if provider == "anthropic":
        payload["output_config"] = {"format": {"type": "json_schema", "schema": schema}}
    elif provider == "kie":
        payload["tools"] = [{"name": _TOOL_NAME, "description": "Submit the complete reference review.", "input_schema": schema}]
        payload["tool_choice"] = {"type": "tool", "name": _TOOL_NAME}
    else:
        raise _failure("provider_error", "No supported vision provider is configured; identity remains unchecked.")
    return payload


def _luna_parts(body: Any) -> list[dict[str, Any]]:
    items = body.get("output") if isinstance(body, dict) else None
    return [part for item in (items if isinstance(items, list) else []) if isinstance(item, dict)
            for part in (item.get("content") if isinstance(item.get("content"), list) else [])
            if isinstance(part, dict)]


def _stop_reason(provider: str, body: Any) -> Any:
    """Normalize each provider's completion signal to the Messages-API vocabulary."""
    if not isinstance(body, dict):
        return None
    if provider != "kie_luna":
        return body.get("stop_reason")
    if any(part.get("type") == "refusal" for part in _luna_parts(body)):
        return "refusal"
    return "end_turn" if body.get("status") == "completed" else (body.get("status") or "missing")


def _parse(provider: str, body: dict[str, Any]) -> dict[str, Any]:
    if provider == "kie_luna":
        text = "".join(part.get("text", "") for part in _luna_parts(body) if part.get("type") == "output_text")
    else:
        blocks = body.get("content") if isinstance(body, dict) else None
        if not isinstance(blocks, list):
            raise ValueError("missing content")
        if provider == "kie":
            match = next((block for block in blocks if isinstance(block, dict)
                          and block.get("type") == "tool_use" and block.get("name") == _TOOL_NAME), None)
            if not isinstance(match, dict) or not isinstance(match.get("input"), dict):
                raise ValueError("missing forced tool result")
            return match["input"]
        text = "".join(block.get("text", "") for block in blocks
                       if isinstance(block, dict) and block.get("type") == "text")
    # json.loads accepts only a JSON document, never a JSON fragment in prose.
    parsed = json.loads(text)
    if not isinstance(parsed, dict):
        raise ValueError("structured result was not an object")
    return parsed


async def request_judgment(tenant_id, machine, candidates, content, provider, url, headers, model, *, video_id=None):
    """Request and checkpoint a schema-bound provider judgment.

    ``machine`` is retained in the checkpoint for diagnosis only.  The
    fingerprint scopes a missing video id to the tenant, model, content, and
    candidate pixels, so independent machines never share a review.
    """
    candidate_ids = [candidate.get("id") for candidate in candidates if isinstance(candidate, dict)]
    if len(candidate_ids) != len(candidates) or any(not isinstance(item, str) for item in candidate_ids):
        raise _failure("invalid_review", "The comparison has invalid candidate identifiers.")
    schema = judgment_schema(candidate_ids)
    path = _checkpoint_path(tenant_id, video_id, machine, provider, model, schema, content)
    checkpoint = _read_checkpoint(path)
    if checkpoint.get("status") == "terminal":
        raise _failure(checkpoint.get("terminal_code") or "invalid_review",
                       checkpoint.get("terminal_reason") or "The comparison is already terminal.")
    if checkpoint.get("result") is not None:
        try:
            from reference_selection import validate_judgment
            validate_judgment(checkpoint["result"], candidates)
        except Exception as exc:
            raise _failure("invalid_review", "The saved comparison result no longer passes validation.") from exc
        return checkpoint["result"]
    attempts = checkpoint.setdefault("attempts", [])
    if len(attempts) >= 2:
        raise _failure(checkpoint.get("terminal_code") or "invalid_review",
                       checkpoint.get("terminal_reason") or "The comparison exhausted its two saved attempts.")
    checkpoint.update({"version": 1, "machine": machine, "provider": provider, "model": model,
                       "checked_at": _now(), "status": "pending"})
    # A process can die after persisting an invalid response but before it
    # reserves the retry.  Its resumed second request must carry the same
    # concise correction as an in-process retry.
    correction = any(attempt.get("status") == "invalid_response" for attempt in attempts
                     if isinstance(attempt, dict))
    while len(attempts) < 2:
        attempt_number = len(attempts) + 1
        attempt = {"number": attempt_number, "checked_at": _now(), "max_tokens": 16000 if attempt_number == 2 else 8000,
                   "status": "reserved"}
        attempts.append(attempt)
        checkpoint["checked_at"] = _now()
        _write_checkpoint(path, checkpoint)  # Reservation is durable before any paid request.
        request_content = list(content)
        if correction:
            request_content.append({"type": "text", "text": _CORRECTION})
        try:
            async with httpx.AsyncClient(timeout=120) as client:
                response = await client.post(url, headers=headers, json=_payload(
                    provider, model, request_content, schema, attempt["max_tokens"]))
            http_status = response.status_code
            attempt["provider_response_body"] = response.text
            try:
                body = response.json()
            except (TypeError, ValueError):
                body = None
            if (http_status == 200 and provider in ("kie", "kie_luna") and isinstance(body, dict)
                    and type(body.get("code")) is int and body["code"] != 200):
                http_status = body["code"]  # Kie reports gateway failures as HTTP 200 {"code": 500, "msg": ...}
            attempt["http_status"] = http_status
            stop_reason = _stop_reason(provider, body)
            attempt["stop_reason"] = stop_reason
            if http_status in (401, 403):
                # A rejected key is fixable configuration, not a verdict on this comparison:
                # forget the checkpoint so the same review can run once the key is right.
                path.unlink(missing_ok=True)
                raise _failure("provider_error",
                               f"Vision provider rejected the API key (HTTP {http_status}); identity remains unchecked.",
                               auth_rejected=True)
            if http_status != 200:
                attempt["status"] = "http_error"
                if http_status == 429 or http_status >= 500:
                    correction = False
                    if len(attempts) < 2:
                        _write_checkpoint(path, checkpoint)
                        await asyncio.sleep(1)
                        continue
                checkpoint.update(status="terminal", terminal_code="provider_error",
                                  terminal_reason=f"Vision provider HTTP {http_status}; identity remains unchecked.")
                _write_checkpoint(path, checkpoint)
                raise _failure(checkpoint["terminal_code"], checkpoint["terminal_reason"])
            if stop_reason == "refusal":
                attempt["status"] = "refusal"
                checkpoint.update(status="terminal", terminal_code="invalid_review",
                                  terminal_reason="The vision provider refused the comparison; identity remains unchecked.")
                _write_checkpoint(path, checkpoint)
                raise _failure(checkpoint["terminal_code"], checkpoint["terminal_reason"])
            expected_stop = "tool_use" if provider == "kie" else "end_turn"
            if stop_reason != expected_stop:
                raise ValueError(f"incomplete stop_reason: {stop_reason or 'missing'}")
            parsed = _parse(provider, body)
            from reference_selection import validate_judgment
            try:
                validate_judgment(parsed, candidates)
            except Exception as exc:
                # A validator rejection is an application-format error: ask
                # once more with the same pixels and a concise correction.
                if getattr(exc, "code", None) == "invalid_review":
                    raise ValueError(str(exc)) from exc
                raise
            attempt["status"] = "accepted"
            checkpoint.update(status="complete", result=parsed, checked_at=_now())
            _write_checkpoint(path, checkpoint)
            return parsed
        except httpx.TransportError as exc:
            attempt.update(status="transport_error", error=str(exc))
            correction = False
            if len(attempts) < 2:
                _write_checkpoint(path, checkpoint)
                await asyncio.sleep(1)
                continue
            checkpoint.update(status="terminal", terminal_code="provider_error",
                              terminal_reason="The vision provider could not be reached; identity remains unchecked.")
            _write_checkpoint(path, checkpoint)
            raise _failure(checkpoint["terminal_code"], checkpoint["terminal_reason"]) from exc
        except Exception as exc:
            # validate_judgment's typed failures are terminal review failures,
            # not recoverable parsing defects.  In particular, its unsupported
            # citation path downgrades confirmation to uncertain and succeeds.
            if hasattr(exc, "code") and hasattr(exc, "reason"):
                raise
            attempt.update(status="invalid_response", error=str(exc))
            correction = True
            if len(attempts) < 2:
                _write_checkpoint(path, checkpoint)
                continue
            checkpoint.update(status="terminal", terminal_code="invalid_review",
                              terminal_reason="The provider returned an unreadable comparison; no image was selected.")
            _write_checkpoint(path, checkpoint)
            raise _failure(checkpoint["terminal_code"], checkpoint["terminal_reason"]) from exc
    raise _failure("invalid_review", "The comparison exhausted its two saved attempts.")
