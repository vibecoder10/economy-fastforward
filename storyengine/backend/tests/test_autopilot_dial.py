"""Unit tests for autopilot_dial.py (checklist C50, P4.2-a — the typed
read accessor for migration 107's dial columns on autopilot_config).

Same convention as tests/test_quality_rules.py / tests/test_channel_patterns.py:
module-level fetch_one is monkeypatched to a fake DB, no live Supabase call.
"""

import asyncio

import autopilot_dial as ad


def test_defaults_when_row_missing(monkeypatch):
    """A tenant with no autopilot_config row at all gets the same
    'propose_only, no cap, not tripped' defaults as today's behavior."""
    async def fake_fetch_one(query, *args):
        return None

    monkeypatch.setattr(ad, "fetch_one", fake_fetch_one)
    dial = asyncio.run(ad.get_autopilot_dial("tenant-missing"))
    assert dial.dial_level == "propose_only"
    assert dial.weekly_budget_cap is None
    assert dial.weekly_spend_reset_at is None
    assert dial.kill_switch_tripped_at is None
    assert dial.kill_switch_reason is None


def test_defaults_when_row_exists_but_dial_level_is_none(monkeypatch):
    """A pre-migration-107 row (columns just added, value still whatever the
    migration's DEFAULT stamped) should never surface a None/empty dial_level
    — falls back to 'propose_only'."""
    async def fake_fetch_one(query, *args):
        return {
            "dial_level": None, "weekly_budget_cap": None,
            "weekly_spend_reset_at": None, "kill_switch_tripped_at": None,
            "kill_switch_reason": None,
        }

    monkeypatch.setattr(ad, "fetch_one", fake_fetch_one)
    dial = asyncio.run(ad.get_autopilot_dial("tenant-x"))
    assert dial.dial_level == "propose_only"


def test_returns_stored_values_for_present_row(monkeypatch):
    captured = {}

    async def fake_fetch_one(query, *args):
        captured["query"] = query
        captured["args"] = args
        return {
            "dial_level": "auto_draft",
            "weekly_budget_cap": "150.50",
            "weekly_spend_reset_at": "2026-07-14T00:00:00+00:00",
            "kill_switch_tripped_at": "2026-07-18T12:00:00+00:00",
            "kill_switch_reason": "weekly budget cap breached",
        }

    monkeypatch.setattr(ad, "fetch_one", fake_fetch_one)
    dial = asyncio.run(ad.get_autopilot_dial("tenant-y"))
    assert captured["args"] == ("tenant-y",)
    assert "WHERE tenant_id = $1" in captured["query"]
    assert dial.dial_level == "auto_draft"
    assert dial.weekly_budget_cap == 150.50
    assert dial.weekly_spend_reset_at == "2026-07-14T00:00:00+00:00"
    assert dial.kill_switch_tripped_at == "2026-07-18T12:00:00+00:00"
    assert dial.kill_switch_reason == "weekly budget cap breached"


def test_weekly_budget_cap_zero_is_not_treated_as_missing(monkeypatch):
    """0 is a valid (if odd) cap value — must not collapse to None (that
    would be indistinguishable from "no cap set")."""
    async def fake_fetch_one(query, *args):
        return {
            "dial_level": "propose_only", "weekly_budget_cap": 0,
            "weekly_spend_reset_at": None, "kill_switch_tripped_at": None,
            "kill_switch_reason": None,
        }

    monkeypatch.setattr(ad, "fetch_one", fake_fetch_one)
    dial = asyncio.run(ad.get_autopilot_dial("tenant-z"))
    assert dial.weekly_budget_cap == 0.0
