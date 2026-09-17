"""Kie source discovery returns leads only; fetched pages own the evidence."""
from __future__ import annotations

import asyncio
import copy
import ipaddress
import json
import math
import socket
import httpx
from urllib.parse import urlsplit, urlunsplit

from error_utils import user_facing

MODEL = "gpt-5-2"
ENDPOINT = "https://api.kie.ai/gpt-5-2/v1/chat/completions"
USD_PER_CREDIT = 0.005  # Same configured conversion as the existing Kie adapters.

_MISSING_FIELD_NEEDS = {
    "intended_role": "the original mission, design objective, or problem the machine was meant to address (not classification, launch, or commissioning alone)",
    "design": "a documented engineering decision or configuration",
    "actual_use": "documented operations, testing, or training",
    "outcome": "a documented consequence, fate, or lasting result",
}


class SourceDiscoveryError(RuntimeError):
    """Stop the research chain without entering the legacy card-repair loop."""

    def __init__(self, message: str, *, code: str = "source_search_failed", retryable: bool = False,
                 attempts: int = 0, next_action: str = "resume", receipt: dict | None = None,
                 machine: str | None = None):
        super().__init__(message)
        self.code = code
        self.retryable = retryable
        self.attempts = attempts
        self.next_action = next_action
        self.receipt = receipt or {}
        self.stage = "research"
        self.machine = machine


_MAX_RESPONSE_CONTENT = 24_000
_MAX_USAGE_SERIALIZED = 4_000


def _error(message: str, *, code: str, retryable: bool, attempts: int, machine: str,
           receipt: dict | None = None, next_action: str = "resume") -> SourceDiscoveryError:
    return SourceDiscoveryError(user_facing(message), code=code, retryable=retryable,
                                attempts=attempts, next_action=next_action, receipt=receipt,
                                machine=machine)


async def _checkpoint(state: dict, callback, *, machine: str) -> None:
    """Durably save a credential-free snapshot; a failed save must stop the operation."""
    if callback is None:
        return
    try:
        accepted = await callback(copy.deepcopy(state))
    except Exception as exc:
        raise _error("Source-search checkpoint failed; saved operation must be reconciled before retrying.", code="checkpoint",
                     retryable=True, attempts=int(state.get("attempts", 0)), machine=machine,
                     receipt=state.get("receipt", {})) from exc
    if accepted is False:
        raise _error("Source-search checkpoint failed; saved operation must be reconciled before retrying.", code="checkpoint",
                     retryable=True, attempts=int(state.get("attempts", 0)), machine=machine,
                     receipt=state.get("receipt", {}))


async def _persist_failure(state: dict, callback, error: SourceDiscoveryError, *, machine: str) -> None:
    """Make a typed terminal/retry outcome replayable before it leaves this adapter."""
    state["status"] = "error"
    state["error"] = {
        "code": error.code, "retryable": error.retryable, "attempts": error.attempts,
        "next_action": error.next_action, "receipt": copy.deepcopy(error.receipt),
        "stage": error.stage, "machine": error.machine,
    }
    await _checkpoint(state, callback, machine=machine)


def _restored_error(state: dict, machine: str) -> SourceDiscoveryError | None:
    saved = state.get("error")
    if not isinstance(saved, dict):
        return None
    return _error("Saved Kie source-search outcome requires the recorded next action.",
                  code=str(saved.get("code") or "source_search_failed"),
                  retryable=bool(saved.get("retryable")), attempts=int(saved.get("attempts") or state.get("attempts") or 0),
                  machine=str(saved.get("machine") or machine), receipt=saved.get("receipt") or state.get("receipt") or {},
                  next_action=str(saved.get("next_action") or "review"))


def _content_from_data(data: object) -> str:
    """Accept only the provider's documented text content forms, never arbitrary prose fields."""
    try:
        content = data["choices"][0]["message"]["content"]
    except (KeyError, IndexError, TypeError):
        raise ValueError("Missing message content")
    if isinstance(content, str):
        return content.strip()
    if isinstance(content, list):
        blocks = []
        for block in content:
            if not isinstance(block, dict) or block.get("type") not in {"text", "output_text"}:
                continue
            text = block.get("text")
            if isinstance(text, str):
                blocks.append(text)
        if blocks:
            return "\n".join(blocks).strip()
    raise ValueError("Unsupported message content")


def _bounded_safe_text(value: object, api_key: str) -> str:
    """Keep diagnostic response text bounded and ensure provider echoes cannot retain our key."""
    text = str(value or "")
    if api_key:
        text = text.replace(api_key, "[redacted]")
    return text[:_MAX_RESPONSE_CONTENT]


def _bounded_usage(value: object, api_key: str) -> object:
    """Usage is provider metadata, but still bound it before durable storage."""
    try:
        encoded = json.dumps(value, ensure_ascii=False, separators=(",", ":"))
    except (TypeError, ValueError):
        return None
    return json.loads(_bounded_safe_text(encoded[:_MAX_USAGE_SERIALIZED], api_key)) if len(encoded) <= _MAX_USAGE_SERIALIZED else {"truncated": True}


def _response_shape(data: object) -> dict:
    known = ("id", "code", "msg", "usage", "credits_consumed", "choices")
    shape = {"top_level_keys": [key for key in known if isinstance(data, dict) and key in data], "content_type": "missing"}
    try:
        content = data["choices"][0]["message"]["content"]
        shape["content_type"] = "text" if isinstance(content, str) else "blocks" if isinstance(content, list) else type(content).__name__
    except (KeyError, IndexError, TypeError):
        pass
    return shape


def _parse_rows(content: object) -> list:
    if not isinstance(content, str) or not content.strip():
        raise ValueError("Empty source response")
    text = content.strip()
    if text.startswith("```"):
        lines = text.splitlines()
        if len(lines) < 3 or not lines[-1].strip().startswith("```"):
            raise ValueError("Truncated fenced JSON")
        text = "\n".join(lines[1:-1]).strip()
    value = json.loads(text)
    if isinstance(value, list):
        return value
    if isinstance(value, dict) and isinstance(value.get("sources"), list):
        return value["sources"]
    raise ValueError("Expected a JSON array or sources object")


def _sanitized_missing_fields(missing_fields: list[str] | None) -> list[str]:
    return list(dict.fromkeys(
        field for field in (missing_fields or [])
        if isinstance(field, str) and field in _MISSING_FIELD_NEEDS
    ))


def _sanitized_query(prompt: str) -> str:
    """Store a bounded, single-line discovery query without request credentials."""
    return " ".join(str(prompt or "").split())[:6000]


def public_source_url(value: object) -> str | None:
    if not isinstance(value, str):
        return None
    try:
        url = urlsplit(value.strip())
        host = (url.hostname or "").lower()
        if url.scheme not in {"https", "http"} or url.username or url.password or url.port not in {None, 80, 443}:
            return None
        if "." not in host or host.endswith((".local", ".localhost", ".internal")):
            return None
        if host == "grokipedia.com" or host.endswith(".grokipedia.com"):
            return None
        try:
            if not ipaddress.ip_address(host).is_global:
                return None
        except ValueError:
            pass
        return value.strip()
    except ValueError:
        return None


async def guard_public_request(request) -> None:
    """Check every fetch and redirect, including hostnames resolving internally."""
    url = public_source_url(str(request.url))
    if not url:
        raise ValueError("Source URL is not public")
    parts = urlsplit(url)
    addresses = await asyncio.get_running_loop().getaddrinfo(
        parts.hostname, parts.port or (443 if parts.scheme == "https" else 80), type=socket.SOCK_STREAM,
    )
    if not addresses or any(not ipaddress.ip_address(row[4][0]).is_global for row in addresses):
        raise ValueError("Source host does not resolve to a public address")


async def discover_sources(client, api_key: str, title: str, machine: str, *, subject: str | None = None,
                           attempted_urls: list[str] | None = None,
                           excluded_hosts: list[str] | None = None,
                           missing_fields: list[str] | None = None, operation_state: dict | None = None,
                           checkpoint=None, guard=None) -> tuple[list[dict], dict]:
    """Discover public source leads, optionally using a caller-owned durable operation journal.

    Durable retries are deliberately available only when both hooks are supplied: without
    them this retains the historical single provider call and never silently resubmits.
    """
    subject = str(subject or machine).strip()
    prior = list(dict.fromkeys(str(url).strip() for url in (attempted_urls or []) if str(url).strip()))
    blocked = list(dict.fromkeys(str(host).strip() for host in (excluded_hosts or []) if str(host).strip()))
    requested_fields = _sanitized_missing_fields(missing_fields)
    prompt = (
        f"Use web search to find 6 real source pages specifically about the subject {subject!r} "
        f"(locked roster identity: {machine!r}) "
        f"for a factual documentary titled {title!r}. Prefer official government, manufacturer, "
        "museum and archive history/fact-sheet pages. Specifically find the original intended role or problem, "
        "distinctive engineering decisions, actual operational/training/testing use, and fate or lasting consequence. "
        "Prioritize exact-machine service histories over designer biographies and repeated component lists. "
        "A launch or commissioning date alone does not establish actual use. Seek evidence of the designed-versus-used "
        "relationship without assuming there was a reversal. Include supported production and memorable details where available. "
        "A class or generation history is usable only when it explicitly names the exact locked machine and states how the claim applies; "
        "never assume a class or generation fact applies to this machine. "
        "Match the exact aircraft variant or named vessel; do not substitute "
        "a related model. Prefer substantive article pages over photo-gallery listings. "
        "Return only a compact JSON array of objects with title and exact_source_url, plus optional pdf_page "
        "when the source is a PDF and its relevant page is known. pdf_page must be a positive page number. "
        "Use original source URLs, never invented URLs or AI encyclopedias. No prose or excerpts."
        + (" Target these current evidence needs: " + "; ".join(
            _MISSING_FIELD_NEEDS[field] for field in requested_fields
        ) + "." if requested_fields else "")
    )
    if prior:
        prompt += " Do not repeat these already attempted URLs: " + ", ".join(prior[:24]) + "."
    if blocked:
        prompt += " Avoid these hosts because they produced no readable capture: " + ", ".join(blocked[:12]) + "."
    durable = operation_state is not None and checkpoint is not None and guard is not None
    state = operation_state if operation_state is not None else {}
    state.setdefault("operation", "kie_source_discovery")
    state.setdefault("stage", "research")
    state.setdefault("machine", machine)
    state.setdefault("attempts", 0)
    state.setdefault("transient_attempts", 0)
    state.setdefault("malformed_attempts", 0)
    saved_status = state.get("status")
    if saved_status == "completed" and isinstance(state.get("leads"), list):
        return state["leads"], state.get("metadata", {})
    if saved_status == "parsed" and isinstance(state.get("leads"), list):
        # A crash after the parsed checkpoint must never spend again. Promote it
        # only after its saved result is already complete enough to return.
        state["status"] = "completed"
        await _checkpoint(state, checkpoint if durable else None, machine=machine)
        return state["leads"], state.get("metadata", {})
    if saved_status == "error":
        restored = _restored_error(state, machine)
        if restored is not None:
            raise restored
    if saved_status in {"submitted", "uncertain", "reconciliation_required"}:
        state["status"] = "reconciliation_required"
        receipt = state.get("receipt", {})
        raise _error("Kie source search submission is unconfirmed and needs reconciliation before another call.",
                     code="reconciliation_required", retryable=False, attempts=int(state["attempts"]),
                     machine=machine, receipt=receipt, next_action="reconcile")

    # A durable received record may be recovered locally. Provider status is
    # intentionally kept in the receipt so account failures are never parsed as
    # an empty body and accidentally retried.
    if saved_status == "received":
        saved_receipt = state.get("receipt") or {}
        saved_http = saved_receipt.get("status_code")
        saved_code = saved_receipt.get("provider_code")
        saved_msg = str(saved_receipt.get("provider_message") or "").lower()
        if saved_http in {401, 403} or saved_code in {401, 403}:
            error = _error("Kie API key needs attention. Update it in Settings, then resume; completed research is saved.", code="account_auth", retryable=False, attempts=int(state["attempts"]), machine=machine, receipt=saved_receipt, next_action="review")
            await _persist_failure(state, checkpoint if durable else None, error, machine=machine)
            raise error
        if saved_http == 402 or saved_code == 402 or any(word in saved_msg for word in ("credit", "balance", "insufficient")):
            error = _error("Kie is out of credits. Add credits, then resume; completed research is saved.", code="account_credits", retryable=False, attempts=int(state["attempts"]), machine=machine, receipt=saved_receipt, next_action="review")
            await _persist_failure(state, checkpoint if durable else None, error, machine=machine)
            raise error
        saved_transient = saved_http == 429 or (isinstance(saved_http, int) and saved_http >= 500) or saved_code == 429 or (isinstance(saved_code, int) and saved_code >= 500)
        if saved_transient:
            if durable and not saved_receipt.get("transient_retry_counted") and int(state["transient_attempts"]) < 2 and int(state["attempts"]) < 4:
                state["transient_attempts"] = int(state["transient_attempts"]) + 1
                saved_receipt["transient_retry_counted"] = True
                state["status"] = "retrying"
                await _checkpoint(state, checkpoint, machine=machine)
                saved_status = "retrying"
            else:
                error = _error("Kie source search is temporarily unavailable. Completed research is saved; schedule a retry.", code="http_transient", retryable=True, attempts=int(state["attempts"]), machine=machine, receipt=saved_receipt, next_action="schedule_retry")
                await _persist_failure(state, checkpoint if durable else None, error, machine=machine)
                raise error
        if not saved_transient and ((isinstance(saved_http, int) and saved_http >= 400) or (isinstance(saved_code, int) and saved_code not in {200})):
            error = _error("Kie source search returned a permanent provider error. Review the saved response before another operation.", code="http_error", retryable=False, attempts=int(state["attempts"]), machine=machine, receipt=saved_receipt, next_action="review")
            await _persist_failure(state, checkpoint if durable else None, error, machine=machine)
            raise error

    request = {"query": _sanitized_query(prompt), "endpoint": ENDPOINT, "model": MODEL, "search_tool": "web_search"}
    state["request"] = request
    data = None
    content = (state.get("response_content", (state.get("receipt") or {}).get("body"))
               if saved_status == "received" else None)
    while content is None:
        if not durable:
            max_attempts = 1
        else:
            max_attempts = 4
        if int(state["attempts"]) >= max_attempts:
            error = _error("Kie source search retry limit reached. Review the saved response before another operation.",
                         code="retry_limit", retryable=False, attempts=int(state["attempts"]), machine=machine,
                         receipt=state.get("receipt", {}), next_action="review")
            await _persist_failure(state, checkpoint if durable else None, error, machine=machine)
            raise error
        if durable:
            try:
                allowed = await guard(copy.deepcopy(state))
            except Exception as exc:
                raise _error("Source research guard stopped the provider call.", code="guard", retryable=False,
                             attempts=int(state["attempts"]), machine=machine, receipt=state.get("receipt", {})) from exc
            if allowed is False:
                raise _error("Source research guard stopped the provider call.", code="guard", retryable=False,
                             attempts=int(state["attempts"]), machine=machine, receipt=state.get("receipt", {}))
        state["attempts"] = int(state["attempts"]) + 1
        state["status"] = "submitted"
        await _checkpoint(state, checkpoint if durable else None, machine=machine)
        try:
            response = await client.post(ENDPOINT, headers={"Authorization": "Bearer " + api_key}, json={
                "messages": [{"role": "user", "content": prompt}],
                "tools": [{"type": "function", "function": {"name": "web_search"}}],
                "stream": False,
            }, timeout=120)
        except Exception as exc:
            # A connect failure is the narrow case where no HTTP request was submitted.
            if isinstance(exc, httpx.ConnectError):
                state["receipt"] = {"transport": type(exc).__name__, "request": request}
                if durable and int(state["transient_attempts"]) < 2 and int(state["attempts"]) < 4:
                    state["transient_attempts"] = int(state["transient_attempts"]) + 1
                    state["status"] = "retrying"
                    await _checkpoint(state, checkpoint, machine=machine)
                    continue
                state["status"] = "error"
                await _checkpoint(state, checkpoint if durable else None, machine=machine)
                raise _error("Kie source search could not connect. Completed research is saved; schedule a retry.",
                             code="transport_preconnect", retryable=True, attempts=int(state["attempts"]),
                             machine=machine, receipt=state["receipt"], next_action="schedule_retry") from exc
            # We cannot prove whether an HTTP transport failure reached the provider.
            state["status"] = "reconciliation_required"
            state["receipt"] = {"transport": type(exc).__name__, "request": request}
            await _checkpoint(state, checkpoint if durable else None, machine=machine)
            raise _error("Kie source search did not return a confirmed result. Completed research is saved; reconcile before retrying.",
                         code="transport_uncertain", retryable=False, attempts=int(state["attempts"]), machine=machine,
                         receipt=state["receipt"], next_action="reconcile") from exc
        try:
            data = response.json()
        except Exception:
            data = None
        raw_content = ""
        if isinstance(data, dict):
            try:
                raw_content = _content_from_data(data)
            except ValueError:
                raw_content = ""
        diagnostic_body = raw_content
        if not raw_content:
            diagnostic_body = getattr(response, "text", "")
        finish_reason = None
        try:
            finish_reason = data["choices"][0].get("finish_reason")
        except (KeyError, IndexError, TypeError, AttributeError):
            pass
        receipt = {"status_code": getattr(response, "status_code", None),
                   "request_id": data.get("id") if isinstance(data, dict) else None,
                   "usage": _bounded_usage(data.get("usage") if isinstance(data, dict) else None, api_key),
                   "credits_consumed": data.get("credits_consumed") if isinstance(data, dict) else None,
                   "provider_code": data.get("code") if isinstance(data, dict) else None,
                   "provider_message": _bounded_safe_text(data.get("msg") if isinstance(data, dict) else "", api_key)[:600],
                   "body": _bounded_safe_text(diagnostic_body, api_key), "body_truncated": len(str(diagnostic_body or "")) > _MAX_RESPONSE_CONTENT,
                   "response_bytes": len(str(diagnostic_body or "")), "finish_reason": finish_reason,
                   "response_shape": _response_shape(data)}
        state.setdefault("receipts", []).append(copy.deepcopy(receipt))
        state.update({"status": "received", "receipt": receipt, "response_content": raw_content})
        await _checkpoint(state, checkpoint if durable else None, machine=machine)
        content = state["response_content"]
        code = data.get("code") if isinstance(data, dict) else None
        raw = str(data.get("msg") or "").lower() if isinstance(data, dict) else ""
        status = getattr(response, "status_code", 0)
        if status >= 400 or code not in {None, 200}:
            if status in {401, 403} or code in {401, 403}:
                error = _error("Kie API key needs attention. Update it in Settings, then resume; completed research is saved.", code="account_auth", retryable=False, attempts=int(state["attempts"]), machine=machine, receipt=receipt, next_action="review")
                await _persist_failure(state, checkpoint if durable else None, error, machine=machine)
                raise error
            if status == 402 or code == 402 or any(word in raw for word in ("credit", "balance", "insufficient")):
                error = _error("Kie is out of credits. Add credits, then resume; completed research is saved.", code="account_credits", retryable=False, attempts=int(state["attempts"]), machine=machine, receipt=receipt, next_action="review")
                await _persist_failure(state, checkpoint if durable else None, error, machine=machine)
                raise error
            transient = status == 429 or status >= 500 or code == 429 or (isinstance(code, int) and code >= 500)
            if durable and transient and int(state["transient_attempts"]) < 2 and int(state["attempts"]) < 4:
                state["transient_attempts"] = int(state["transient_attempts"]) + 1
                receipt["transient_retry_counted"] = True
                state["status"] = "retrying"
                await _checkpoint(state, checkpoint, machine=machine)
                content = None
                continue
            error = _error("Kie source search is temporarily unavailable. Completed research is saved; retry to resume.", code="http_transient" if transient else "http_error", retryable=transient, attempts=int(state["attempts"]), machine=machine, receipt=receipt, next_action="schedule_retry" if transient else "review")
            await _persist_failure(state, checkpoint if durable else None, error, machine=machine)
            raise error
    if state.get("receipt", {}).get("body_truncated"):
        error = _error("Kie source search response was truncated before it could be parsed.", code="truncated", retryable=True, attempts=int(state["attempts"]), machine=machine, receipt=state["receipt"], next_action="schedule_retry")
        await _persist_failure(state, checkpoint if durable else None, error, machine=machine)
        raise error
    if state.get("receipt", {}).get("finish_reason") == "length":
        error = _error("Kie source search generation ended at its length limit before a complete source list was returned.", code="truncated", retryable=False, attempts=int(state["attempts"]), machine=machine, receipt=state["receipt"], next_action="review")
        await _persist_failure(state, checkpoint if durable else None, error, machine=machine)
        raise error
    try:
        rows = _parse_rows(content)
    except (TypeError, ValueError, json.JSONDecodeError) as exc:
        if durable and int(state["malformed_attempts"]) < 1 and int(state["attempts"]) < 4:
            state["malformed_attempts"] = int(state["malformed_attempts"]) + 1
            state["status"] = "retrying"
            await _checkpoint(state, checkpoint, machine=machine)
            state.pop("response_content", None)
            content = None
            # Re-enter the network loop without duplicating the parser below.
            return await discover_sources(client, api_key, title, machine, subject=subject, attempted_urls=attempted_urls,
                                          excluded_hosts=excluded_hosts, missing_fields=missing_fields,
                                          operation_state=state, checkpoint=checkpoint, guard=guard)
        error_code = "empty" if not content else "truncated" if str(content).lstrip().startswith(("[", "{")) else "malformed"
        error = _error("Kie source search returned no usable source list. Review the saved response before another operation.", code=error_code, retryable=False, attempts=int(state["attempts"]), machine=machine, receipt=state.get("receipt", {}), next_action="review")
        await _persist_failure(state, checkpoint if durable else None, error, machine=machine)
        raise error from exc
    leads = []
    seen = set()
    for row in rows[:12]:
        if not isinstance(row, dict):
            continue
        url = public_source_url(row.get("exact_source_url"))
        supplied_page = row.get("pdf_page")
        if supplied_page is not None:
            if isinstance(supplied_page, bool) or not isinstance(supplied_page, int) or not 0 < supplied_page <= 10_000:
                continue
            parts = urlsplit(url) if url else None
            existing = parts.fragment if parts else ""
            expected = f"page={supplied_page}"
            if existing and existing != expected:
                continue
            if url and not existing:
                url = urlunsplit((parts.scheme, parts.netloc, parts.path, parts.query, expected))
        if url and url not in seen:
            seen.add(url)
            leads.append({"url": url, "title": str(row.get("title") or url)[:300], "_query": prompt})
        if len(leads) >= 6:
            break
    if not leads:
        error = _error("Kie source search returned no public source links. Completed research is saved.", code="no_results", retryable=False,
                       attempts=int(state["attempts"]), machine=machine,
                       receipt=state.get("receipt", {}), next_action="review")
        await _persist_failure(state, checkpoint if durable else None, error, machine=machine)
        raise error
    persisted_receipt = state.get("receipt", {})
    credits = persisted_receipt.get("credits_consumed")
    try:
        credits = float(credits) if credits is not None else None
        if credits is not None and (not math.isfinite(credits) or credits < 0):
            credits = None
    except (TypeError, ValueError):
        credits = None
    metadata = {
        "provider": "kie", "model": MODEL, "request_id": persisted_receipt.get("request_id"),
        "credits_consumed": credits, "usage": persisted_receipt.get("usage"),
        "lead_count": len(leads), "search_tool": "web_search", "subject": subject,
        "query": _sanitized_query(prompt), "missing_fields": requested_fields,
        "lead_urls": [lead["url"] for lead in leads],
        "operation": {"status": "completed", "attempts": int(state["attempts"]),
                      "receipt": copy.deepcopy(persisted_receipt),
                      "receipts": copy.deepcopy(state.get("receipts", []))},
    }
    state.update({"status": "parsed", "leads": leads, "metadata": metadata})
    await _checkpoint(state, checkpoint if durable else None, machine=machine)
    state["status"] = "completed"
    await _checkpoint(state, checkpoint if durable else None, machine=machine)
    return leads, metadata
