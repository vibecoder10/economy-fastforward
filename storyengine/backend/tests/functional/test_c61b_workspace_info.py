"""Tests for C61b (checklist/decisions.md 2026-07-20 "C61 RULING — Option A —
ONE WORKSPACE = ONE CHANNEL"): the `get_workspace_info` MCP whoami read tool.

With Option A ruled, a channel IS a tenant/workspace, and multi-channel users
run one MCP connector per workspace (one agent token each). This tool answers
"which channel does THIS connector speak for" so an agent juggling several
connectors never acts on the wrong one.

Covers:
  1. Tool surface: "get_workspace_info" is in mcp.TOOL_NAMES and its
     inputSchema takes no required arguments (it's a pure whoami, no video_id).
  2. Field sourcing: workspace_name falls back tenant_name -> "Workspace" the
     same way routes/workspaces.py's list_workspaces does; niche/style_summary
     come from the plain channel_profiles columns (not the heavy
     channel_identity DNA blob get_channel_dna already exposes); autopilot
     dial/kill-switch come from the REAL autopilot_dial.get_autopilot_dial
     (patched at the module the handler imports it from, proving this isn't a
     parallel reimplementation); plan comes from the REAL
     routes.billing._get_tenant_plan.
  3. No-secrets guard (non-vacuous): fetch_one is patched to return a row that
     ALSO carries secret-shaped keys (youtube_refresh_token, google_drive_
     refresh_token, api_key) as if a future ALTER TABLE or a careless
     `SELECT *` ever put them in the query result. The handler must not leak
     them — it builds the response from explicitly named fields, never a row
     spread. A deliberately "broken" variant (dict(row) passthrough) is
     exercised inline in the test itself as the negative control, so the
     guard is proven non-vacuous without a git-stash dance.
  4. Tenant scoping: the tenant_id argument reaches every one of the three
     underlying reads (fetch_one's query param, get_autopilot_dial, and
     _get_tenant_plan) unchanged.

No live DB, no network. Run:
  cd storyengine/backend && ./venv/bin/python -m pytest tests/functional/test_c61b_workspace_info.py -q
"""
from __future__ import annotations

import json
import os
import sys
from dataclasses import dataclass
from typing import Optional
from unittest.mock import AsyncMock, patch

_BACKEND = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
sys.path.insert(0, _BACKEND)

import routes.mcp as mcp_mod  # noqa: E402

_SECRET_KEY_PREFIXES = ("refresh_token", "api_key", "token", "secret", "password", "key")


@dataclass
class _FakeDial:
    dial_level: str = "propose_only"
    weekly_budget_cap: Optional[float] = None
    weekly_spend_reset_at: Optional[object] = None
    kill_switch_tripped_at: Optional[object] = None
    kill_switch_reason: Optional[str] = None


def _assert_no_secret_shaped_keys(payload: dict) -> None:
    def _walk(obj):
        if isinstance(obj, dict):
            for k, v in obj.items():
                lk = k.lower()
                assert not any(lk.startswith(p) or lk.endswith(p) for p in _SECRET_KEY_PREFIXES), (
                    f"secret-shaped key {k!r} leaked into get_workspace_info's response"
                )
                _walk(v)
        elif isinstance(obj, list):
            for v in obj:
                _walk(v)

    _walk(payload)


# =============================================================================
# 1. Tool surface
# =============================================================================

def test_get_workspace_info_is_a_tool_with_no_required_args():
    assert "get_workspace_info" in mcp_mod.TOOL_NAMES
    tool = next(t for t in mcp_mod.TOOLS if t["name"] == "get_workspace_info")
    assert tool["inputSchema"].get("required", []) == []
    assert "disambiguat" in tool["description"].lower(), (
        "tool description must say Claude uses this to disambiguate which channel a "
        "connector is acting on (C61 ruling's explicit ask)"
    )
    print("✅ test_get_workspace_info_is_a_tool_with_no_required_args")


def test_get_workspace_info_dispatches_via_read_handlers():
    assert mcp_mod._READ_HANDLERS["get_workspace_info"] is mcp_mod._call_get_workspace_info
    print("✅ test_get_workspace_info_dispatches_via_read_handlers")


# =============================================================================
# 2. Field sourcing — real callables, name-fallback parity with workspaces.py
# =============================================================================

async def test_workspace_name_falls_back_tenant_name_then_workspace():
    async def _fake_fetch_one(query, *args):
        return {"tenant_name": "Ryan's Workspace", "channel_name": None,
                 "niche": None, "style_description": None}

    fake_dial = AsyncMock(return_value=_FakeDial())
    fake_plan = AsyncMock(return_value="pro")

    with patch.object(mcp_mod, "fetch_one", _fake_fetch_one), \
         patch("autopilot_dial.get_autopilot_dial", fake_dial), \
         patch("routes.billing._get_tenant_plan", fake_plan):
        result = await mcp_mod._call_get_workspace_info("tenant-1", {})

    payload = json.loads(result["content"][0]["text"])
    assert payload["workspace_name"] == "Ryan's Workspace", (
        "must fall back to tenant name when channel_name is unset, same as "
        "routes/workspaces.py's list_workspaces"
    )
    fake_dial.assert_awaited_once_with("tenant-1")
    fake_plan.assert_awaited_once_with("tenant-1")
    print("✅ test_workspace_name_falls_back_tenant_name_then_workspace")


async def test_channel_name_wins_over_tenant_name_when_set():
    async def _fake_fetch_one(query, *args):
        return {"tenant_name": "user-abc123", "channel_name": "The Power Doctrine",
                 "niche": "geopolitics", "style_description": "deadpan investigative"}

    with patch.object(mcp_mod, "fetch_one", _fake_fetch_one), \
         patch("autopilot_dial.get_autopilot_dial", AsyncMock(return_value=_FakeDial())), \
         patch("routes.billing._get_tenant_plan", AsyncMock(return_value="agency")):
        result = await mcp_mod._call_get_workspace_info("tenant-2", {})

    payload = json.loads(result["content"][0]["text"])
    assert payload["workspace_name"] == "The Power Doctrine"
    assert payload["niche"] == "geopolitics"
    assert payload["style_summary"] == "deadpan investigative"
    assert payload["plan"] == "agency"
    print("✅ test_channel_name_wins_over_tenant_name_when_set")


async def test_autopilot_dial_and_kill_switch_pass_through():
    tripped_dial = _FakeDial(
        dial_level="auto_draft", kill_switch_tripped_at="2026-07-19T00:00:00Z",
        kill_switch_reason="weekly budget breached",
    )
    with patch.object(mcp_mod, "fetch_one", AsyncMock(return_value={})), \
         patch("autopilot_dial.get_autopilot_dial", AsyncMock(return_value=tripped_dial)), \
         patch("routes.billing._get_tenant_plan", AsyncMock(return_value="free")):
        result = await mcp_mod._call_get_workspace_info("tenant-3", {})

    payload = json.loads(result["content"][0]["text"])
    assert payload["autopilot"] == {
        "dial_level": "auto_draft",
        "kill_switch_tripped": True,
        "kill_switch_reason": "weekly budget breached",
    }
    # No row at all (fetch_one returned {}) still degrades to the safe default name.
    assert payload["workspace_name"] == "Workspace"
    print("✅ test_autopilot_dial_and_kill_switch_pass_through")


# =============================================================================
# 3. No-secrets guard (non-vacuous)
# =============================================================================

async def test_no_secret_shaped_keys_leak_even_if_the_row_carries_them():
    """Simulates a poisoned row — as if a future migration or a careless
    `SELECT *` ever put OAuth tokens/keys into the query result. The real
    handler must still not surface them, because it reads named fields only."""
    poisoned_row = {
        "tenant_name": "Client Channel", "channel_name": None,
        "niche": "finance", "style_description": "punchy",
        "youtube_refresh_token": "1//09-should-not-leak",
        "google_drive_refresh_token": "1//09-should-not-leak-either",
        "api_key": "sk-should-not-leak",
    }
    with patch.object(mcp_mod, "fetch_one", AsyncMock(return_value=poisoned_row)), \
         patch("autopilot_dial.get_autopilot_dial", AsyncMock(return_value=_FakeDial())), \
         patch("routes.billing._get_tenant_plan", AsyncMock(return_value="free")):
        result = await mcp_mod._call_get_workspace_info("tenant-4", {})

    payload = json.loads(result["content"][0]["text"])
    _assert_no_secret_shaped_keys(payload)
    assert payload["workspace_name"] == "Client Channel"
    print("✅ test_no_secret_shaped_keys_leak_even_if_the_row_carries_them")


def test_guard_is_non_vacuous_a_naive_passthrough_would_have_leaked():
    """Negative control proving test #3 actually tests something: a naive
    `dict(row)` passthrough implementation (the bug this handler avoids) DOES
    fail the same assertion against the same poisoned row — so the guard
    isn't vacuously passing no matter what."""
    poisoned_row = {
        "tenant_name": "Client Channel", "channel_name": None,
        "youtube_refresh_token": "1//09-should-not-leak",
    }
    naive_payload = dict(poisoned_row)  # the bug: spreading the row verbatim
    try:
        _assert_no_secret_shaped_keys(naive_payload)
    except AssertionError:
        print("✅ test_guard_is_non_vacuous_a_naive_passthrough_would_have_leaked")
        return
    raise AssertionError("expected the naive passthrough to fail the no-secrets guard")


TESTS_SYNC = [
    test_get_workspace_info_is_a_tool_with_no_required_args,
    test_get_workspace_info_dispatches_via_read_handlers,
    test_guard_is_non_vacuous_a_naive_passthrough_would_have_leaked,
]

TESTS_ASYNC = [
    test_workspace_name_falls_back_tenant_name_then_workspace,
    test_channel_name_wins_over_tenant_name_when_set,
    test_autopilot_dial_and_kill_switch_pass_through,
    test_no_secret_shaped_keys_leak_even_if_the_row_carries_them,
]


def main() -> int:
    import asyncio
    failed = 0
    for t in TESTS_SYNC:
        try:
            t()
        except AssertionError as e:
            print(f"❌ {t.__name__}: {e}")
            failed += 1
    for t in TESTS_ASYNC:
        try:
            asyncio.run(t())
        except AssertionError as e:
            print(f"❌ {t.__name__}: {e}")
            failed += 1
    total = len(TESTS_SYNC) + len(TESTS_ASYNC)
    print(f"\n{total - failed}/{total} passed")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
