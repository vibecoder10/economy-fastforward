"""Tests for C15 (checklist §1.2, tasks/storyengine-wiring-fix-checklist.md):
the conversational door's itemized quote — "Scene 12 is your reveal — Veo
Quality ($1.25); Grok elsewhere. Total $4.20 vs $25 all-premium"
(tasks/storyengine-copilot-ux-map.md §1).

Three layers:

1. `actions.cost_breakdown()` — groups the SAME per-row resolved prices
   `actions._routed_clip_costs`/`estimate_cost` already sum (one resolver,
   no parallel math): the itemized lines must sum to EXACTLY the total
   `estimate_cost` returns for the identical (verb, scene) call, on a mixed
   video (override row + routed row + a NULL-routed fallback row). Also
   checks the all-premium comparison figure and that hero (premium-tier)
   scenes carry their own `routing_reason` verbatim, never re-derived.
2. `actions.guardrail_note()` — the channel-look phrasing the copilot uses,
   pinned against the exact wording the checklist/UX map quote.
3. `routes.chat._confirm_card()` — the itemized `breakdown` field rides the
   card payload when present, and is omitted entirely (byte-identical to
   the pre-C15 card shape) when there's nothing to itemize.

Same monkeypatch pattern as test_c13_clip_model_routing.py (real `actions`
module, `fetch_all` monkeypatched — no live DB).

Run: cd storyengine/backend && ./venv/bin/python -m pytest tests/functional/test_c15_itemized_cost_breakdown.py -q
"""
import asyncio
import os
import sys

_BACKEND = os.path.join(os.path.dirname(__file__), "..", "..")
_PIPELINE_PATH = os.path.join(_BACKEND, "..", "..", "skills", "video-pipeline")
sys.path.insert(0, os.path.abspath(_BACKEND))
sys.path.insert(0, os.path.abspath(_PIPELINE_PATH))

import actions  # noqa: E402
import routes.chat as chat_route  # noqa: E402
from shared.channel_profile import MODEL_REGISTRY  # noqa: E402

TENANT = "tenant-1"
VIDEO = "video-1"

GROK_PRICE = MODEL_REGISTRY["grok-imagine"].cost_per_clip[min(MODEL_REGISTRY["grok-imagine"].cost_per_clip)]
VEO_QUALITY_PRICE = MODEL_REGISTRY["veo-3.1-quality"].cost_per_clip[8]


def _summary(**over):
    base = {
        "title": "T", "status": "ready_for_video_generation", "length_min": 5,
        "model": "grok-imagine", "scenes": 3, "boards": 3, "voiced": 3,
        "max_scene": 3, "pics": 3, "clips": 0, "cast": 0, "spent": 0.0,
        "render_style": None,
    }
    base.update(over)
    return base


# A mixed-routing video (checklist §1.2 example): one ordinary scene stays on
# the channel default (Grok), one scene's routed Grok recommendation is
# manually overridden to Veo Quality (C14 override wins), one scene is
# routed straight to Veo Quality as the shot plan's own "reveal" pick, and
# one legacy row carries no routing at all (falls back to the video model).
_MIXED_ROWS = [
    {"scene": 3, "routed_model": "grok-imagine", "model_override": None,
     "routing_reason": "ordinary scene, animated channel → draft tier (draft)"},
    {"scene": 7, "routed_model": "grok-imagine", "model_override": "veo-3.1-quality",
     "routing_reason": "ordinary scene, animated channel → draft tier (draft)"},
    {"scene": 12, "routed_model": "veo-3.1-quality", "model_override": None,
     "routing_reason": "reveal scene, realistic channel → hero tier (premium)"},
    {"scene": 20, "routed_model": None, "model_override": None, "routing_reason": None},
]


def _patch_rows(monkeypatch, rows):
    async def fake_fetch_all(query, *args):
        assert "FROM assets" in query and "routed_model" in query and "routing_reason" in query
        return rows
    monkeypatch.setattr(actions, "fetch_all", fake_fetch_all)


# ---------------------------------------------------------------------------
# 1. actions.cost_breakdown() — one resolver, itemized sum == estimate_cost's total
# ---------------------------------------------------------------------------

def test_breakdown_sums_to_exactly_the_same_total_estimate_cost_returns(monkeypatch):
    _patch_rows(monkeypatch, _MIXED_ROWS)

    cost, cost_text = asyncio.run(actions.estimate_cost(TENANT, VIDEO, "animate", None, _summary()))
    breakdown = asyncio.run(actions.cost_breakdown(TENANT, VIDEO, "animate", None, _summary()))

    assert breakdown is not None
    # Non-vacuous: prove this is genuinely a MIXED plan (>1 model), not a
    # trivial single-line itemization of the same flat number.
    assert len(breakdown["lines"]) == 2
    assert breakdown["total"] == cost, (
        f"itemized total {breakdown['total']} must equal estimate_cost's own total {cost} "
        "— they must share one resolver, not drift apart")
    assert round(sum(ln["subtotal"] for ln in breakdown["lines"]), 2) == breakdown["total"], (
        "the itemized lines must sum to EXACTLY the displayed total")
    assert cost_text == f"~${breakdown['total']:.2f}"

    by_model = {ln["model_id"]: ln for ln in breakdown["lines"]}
    # scene 3 (grok, unrouted-override) + scene 20 (NULL -> video-level grok fallback)
    assert by_model["grok-imagine"]["count"] == 2
    assert by_model["grok-imagine"]["subtotal"] == round(2 * GROK_PRICE, 2)
    assert by_model["grok-imagine"]["tier"] == "draft"
    # scene 7 (override wins over its own Grok routing) + scene 12 (routed straight to Veo Quality)
    assert by_model["veo-3.1-quality"]["count"] == 2
    assert by_model["veo-3.1-quality"]["subtotal"] == round(2 * VEO_QUALITY_PRICE, 2)
    assert by_model["veo-3.1-quality"]["tier"] == "premium"


def test_all_premium_comparison_prices_every_row_at_the_flagship_tier(monkeypatch):
    """The "$4.20 vs $25 all-premium" figure: len(rows) * the cheapest wired
    premium-tier per-clip price (veo-3.1-quality, $1.25 — its only duration
    tier) — illustrative only, never the real charged total."""
    _patch_rows(monkeypatch, _MIXED_ROWS)
    breakdown = asyncio.run(actions.cost_breakdown(TENANT, VIDEO, "animate", None, _summary()))
    assert breakdown["all_premium_total"] == round(4 * VEO_QUALITY_PRICE, 2)
    assert breakdown["all_premium_total"] > breakdown["total"], (
        "a mixed/cheap plan must always compare favorably against all-premium")


def test_hero_scenes_carry_routing_reason_verbatim_not_rederived(monkeypatch):
    _patch_rows(monkeypatch, _MIXED_ROWS)
    breakdown = asyncio.run(actions.cost_breakdown(TENANT, VIDEO, "animate", None, _summary()))
    heroes = {h["scene"]: h for h in breakdown["hero_scenes"]}
    assert set(heroes) == {7, 12}
    # scene 12 kept its own shot-plan-time reason string, byte-identical.
    assert heroes[12]["reason"] == "reveal scene, realistic channel → hero tier (premium)"
    assert heroes[12]["display_name"] == "Veo 3.1 Quality"
    # scene 7's row also carries a (stale, pre-override) reason — still surfaced
    # verbatim, since the override doesn't rewrite routing_reason.
    assert heroes[7]["reason"] == "ordinary scene, animated channel → draft tier (draft)"


def test_uniform_plan_has_one_line_and_no_hero_scenes(monkeypatch):
    """A video where every not-yet-clipped row resolves to the SAME model
    (the common case — no routing has diverged anything) itemizes to one
    line and flags no hero scenes, so the copilot has nothing extra to
    call out beyond the plain cost line."""
    rows = [
        {"scene": 1, "routed_model": "grok-imagine", "model_override": None, "routing_reason": "r1"},
        {"scene": 2, "routed_model": None, "model_override": None, "routing_reason": None},
    ]
    _patch_rows(monkeypatch, rows)
    breakdown = asyncio.run(actions.cost_breakdown(TENANT, VIDEO, "animate", None, _summary()))
    assert len(breakdown["lines"]) == 1
    assert breakdown["hero_scenes"] == []


def test_no_shot_plan_yet_returns_none_same_guard_as_estimate_cost(monkeypatch):
    """Money invariant #3 (C13): before any pictures exist there is no shot
    plan to itemize — must not even query the assets table."""
    async def fail_fetch_all(query, *args):
        raise AssertionError("must not query per-row routing before a shot plan exists")
    monkeypatch.setattr(actions, "fetch_all", fail_fetch_all)

    breakdown = asyncio.run(actions.cost_breakdown(
        TENANT, VIDEO, "build", None, _summary(status="ready_for_video_generation", pics=0, scenes=5)))
    assert breakdown is None


def test_empty_scene_scoped_quote_returns_none(monkeypatch):
    """A per-scene quote with zero matching rows (estimate_cost's own
    4-clip guess branch) has nothing real to itemize."""
    async def fake_fetch_all(query, *args):
        return []
    monkeypatch.setattr(actions, "fetch_all", fake_fetch_all)

    breakdown = asyncio.run(actions.cost_breakdown(TENANT, VIDEO, "animate", 5, _summary()))
    assert breakdown is None


def test_non_animate_build_verbs_return_none(monkeypatch):
    async def fail_fetch_all(query, *args):
        raise AssertionError("no per-clip routing exists for a non-clip verb")
    monkeypatch.setattr(actions, "fetch_all", fail_fetch_all)

    for verb in ("script", "voice", "thumbnail", "render", "images"):
        assert asyncio.run(actions.cost_breakdown(TENANT, VIDEO, verb, None, _summary())) is None


# ---------------------------------------------------------------------------
# 2. actions.guardrail_note() — the channel-look phrasing (pinned wording)
# ---------------------------------------------------------------------------

def test_guardrail_note_animated_channel():
    assert actions.guardrail_note("animated") == (
        "channel is set to Animated, so everything stays on Grok.")


def test_guardrail_note_realistic_channel():
    assert actions.guardrail_note("realistic") == (
        "channel is set to Realistic, so shots route across the photoreal lineup.")


def test_guardrail_note_no_style_declared():
    assert actions.guardrail_note(None) == "no channel look set — using your default model."
    assert actions.guardrail_note("") == "no channel look set — using your default model."


# ---------------------------------------------------------------------------
# 3. routes.chat._confirm_card() — additive `breakdown` field, fail-safe absent
# ---------------------------------------------------------------------------

def test_confirm_card_carries_breakdown_when_present():
    breakdown = {
        "lines": [{"model_id": "grok-imagine", "display_name": "Grok Imagine",
                   "tier": "draft", "count": 2, "subtotal": round(2 * GROK_PRICE, 2)}],
        "total": round(2 * GROK_PRICE, 2), "all_premium_total": round(2 * VEO_QUALITY_PRICE, 2),
        "hero_scenes": [],
    }
    card = chat_route._confirm_card("animate", None, f"~${round(2 * GROK_PRICE, 2):.2f}", breakdown)
    assert card["breakdown"] == breakdown


def test_confirm_card_omits_breakdown_key_entirely_when_absent():
    """No breakdown arg (the pre-C15 call shape) -> the EXACT pre-C15 card
    dict, no `breakdown` key at all — an old frontend build must see
    byte-identical payloads."""
    card = chat_route._confirm_card("script", None, "~$0.02")
    assert "breakdown" not in card
    assert card == {
        "id": "confirm_action", "label": "Write the script", "type": "single",
        "options": [
            {"value": "yes", "label": "Do it · ~$0.02"},
            {"value": "no", "label": "Cancel"},
        ],
    }


def test_confirm_card_omits_breakdown_when_it_has_no_lines():
    """A breakdown dict that resolved to nothing itemizable (defensive —
    cost_breakdown itself returns None in this case, but the card builder
    must not choke on an empty one either) is dropped the same way."""
    card = chat_route._confirm_card("animate", 3, "~$0.09", {"lines": [], "total": 0, "all_premium_total": None, "hero_scenes": []})
    assert "breakdown" not in card


if __name__ == "__main__":
    import inspect
    mod = sys.modules[__name__]
    test_fns = [obj for name, obj in vars(mod).items()
                if name.startswith("test_") and inspect.isfunction(obj)]
    for fn in test_fns:
        params = inspect.signature(fn).parameters
        if "monkeypatch" in params:
            print(f"skipping {fn.__name__} (needs pytest's monkeypatch fixture — run via pytest)")
            continue
        fn()
    print(f"✅ {len(test_fns)} test functions found — run via pytest for full coverage")
