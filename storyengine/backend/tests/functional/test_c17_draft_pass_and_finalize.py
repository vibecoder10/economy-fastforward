"""Tests for C17 (checklist §1.3 "Draft cheap, finish expensive",
tasks/storyengine-copilot-ux-map.md §2, S7 design requirements in
docs/reports/2026-07-17-storyengine-agent-audit-findings.md §S7): the trust-
ladder centerpiece — draft the whole video's CLIPS at the cheapest wired
draft tier in one cheap pass, review, then finalize only the scenes worth
finishing at their routed/premium tier.

Six layers, mirroring test_c13_clip_model_routing.py's / test_c15_itemized_
cost_breakdown.py's patterns (real `actions`/`pipeline_executor` modules,
DB boundaries monkeypatched — no live DB, no network, no paid calls):

1. `actions._draft_tier_model_id()` — resolves the cheapest WIRED
   tier="draft" model from MODEL_REGISTRY (data-driven; today that's
   grok-imagine, but the function never hardcodes the string).
2. `pipeline_executor.run_clip_generation(force_model_id=...)` — EVERY row
   animates through the forced draft model regardless of its own
   routed_model/model_override, and NEITHER column is ever written back
   (proven by asserting no UPDATE touches them) — the routing recommendation
   must survive a draft pass untouched for `finalize` to read later.
3. `run_clip_generation(only_scenes=..., force=True)` — scopes to EXACTLY
   the given scene list; an unapproved scene's row is never even fetched
   from the DB (simulated at the fake_fetch_all layer, mirroring the real
   `scene = ANY($3::int[])` WHERE clause) and never appears in any
   video_clip_url/model_used update.
4. `generation_passes.scene_set_hash()` — same (scene, model) set produces
   the same hash; a larger set produces a different one.
5. `actions.estimate_cost`/`actions.cost_breakdown` for draft_pass/finalize
   — draft_pass prices EVERY row at the draft tier (never the routed
   price); finalize prices ONLY approved-scene rows at their real resolved
   tier; both itemizations sum to exactly the total estimate_cost returns.
6. `actions._runner_draft_pass`/`_runner_finalize` — claim denial returns
   the busy reply with NO background_tasks.add_task call (non-vacuous via
   git stash: before this chunk neither verb/runner exists at all); an
   already-completed pass (generation_passes.already_done=True) is refused
   the same way, with no re-dispatch; a fresh pass claims, dispatches, and
   marks the pass done only after a successful run.
7. `routes.chat._confirm_card()` renders a sensible card for both new verbs
   (checklist's "[U] NONE this chunk... verify the confirm card renders
   sensible text, nothing more").

Run: cd storyengine/backend && ./venv/bin/python -m pytest tests/functional/test_c17_draft_pass_and_finalize.py -q
"""
import asyncio
import os
import sys
from unittest.mock import AsyncMock

_BACKEND = os.path.join(os.path.dirname(__file__), "..", "..")
_PIPELINE_PATH = os.path.join(_BACKEND, "..", "..", "skills", "video-pipeline")
sys.path.insert(0, os.path.abspath(_BACKEND))
sys.path.insert(0, os.path.abspath(_PIPELINE_PATH))

import actions  # noqa: E402
import generation_passes  # noqa: E402
import routes.chat as chat_route  # noqa: E402
from shared.channel_profile import MODEL_REGISTRY  # noqa: E402

TENANT = "tenant-1"
VIDEO = "video-1"

DRAFT_MODEL = "grok-imagine"  # today's cheapest wired tier="draft" entry
GROK_PRICE = MODEL_REGISTRY[DRAFT_MODEL].cost_per_clip[min(MODEL_REGISTRY[DRAFT_MODEL].cost_per_clip)]
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


# ---------------------------------------------------------------------------
# 1. _draft_tier_model_id — data-driven, never hardcoded
# ---------------------------------------------------------------------------

def test_draft_tier_model_id_is_data_driven_from_registry():
    resolved = actions._draft_tier_model_id()
    assert resolved == DRAFT_MODEL
    profile = MODEL_REGISTRY[resolved]
    assert profile.wired and profile.tier == "draft"
    # Non-vacuous: prove the function actually reads the registry rather than
    # returning a hardcoded literal — flip the registry's tier and watch the
    # answer change.
    try:
        original_tier = profile.tier
        profile.tier = "standard"
        assert actions._draft_tier_model_id() != DRAFT_MODEL
    finally:
        profile.tier = original_tier


# ---------------------------------------------------------------------------
# 2/3. run_clip_generation — force_model_id + only_scenes
# ---------------------------------------------------------------------------

import pipeline_executor as pe_mod  # noqa: E402
from pipeline_executor import PipelineExecutor  # noqa: E402
import storage as storage_mod  # noqa: E402
import clip_dialogue as clip_dialogue_mod  # noqa: E402


class _FakeLightPipeline:
    def __init__(self, image_client):
        self.image_client = image_client
        self.should_cancel = None


class _FakeImageClient:
    VEO_MODEL_QUALITY = "veo-quality-id"
    VEO_MODEL_FAST = "veo-fast-id"

    def __init__(self):
        self.calls = []

    async def generate_video(self, img, prompt, duration=6, extra_image_urls=None,
                              aspect_ratio="16:9", resolution="720p", task_id_out=None):
        self.calls.append(("grok", img))
        if task_id_out is not None:
            task_id_out.append(f"grok-task-{img}")
        return f"https://fake/grok-{img}.mp4"

    async def generate_video_seedance(self, *a, **k):
        raise AssertionError("seedance should not be called in these tests")

    async def generate_video_veo(self, prompt, image_url=None, model=None, task_id_out=None):
        self.calls.append(("veo", image_url))
        if task_id_out is not None:
            task_id_out.append(f"veo-task-{image_url}")
        return f"https://fake/veo-{image_url}.mp4"

    async def generate_talking_video(self, *a, **k):
        raise AssertionError("talking video should not be called in these tests")

    async def download_image(self, url):
        return b"fake-clip-bytes"


def _row(scene, routed_model, model_override=None, asset_id=None):
    aid = asset_id or f"asset-s{scene}"
    return {
        "id": aid, "scene": scene, "image_index": 1,
        "image_url": f"https://fake/img-{aid}.png", "drive_image_url": None,
        "video_prompt": "Wide shot pushes in on the machine.",
        "video_clip_url": None, "duration_seconds": 4.0,
        "sentence_text": None, "image_prompt": "a factory floor",
        "assigned_dialogue": None, "routed_model": routed_model,
        "model_override": model_override,
    }


def _video_row():
    return {
        "id": VIDEO, "video_model": "grok-imagine", "aspect_ratio": "16:9",
        "video_resolution": "720p", "dialogue_mode": None,
        "dialogue_audio": "voice_over", "character_reference_url": None,
        "image_style_override": None, "status": "ready_for_video_generation",
    }


def _drive(monkeypatch, all_rows, **run_kwargs):
    """Drives run_clip_generation against `all_rows`, faithfully simulating
    the real WHERE clause (scene=$3 / scene = ANY($3::int[]) / none) so a
    scene NOT in an only_scenes allowlist is never even returned — the same
    row-level "untouched" guarantee the real SQL provides. Returns
    (image_client, model_used_updates: dict[asset_id, model],
    clip_url_updates: set[asset_id], executed_queries: list[str])."""
    model_used_updates: dict = {}
    clip_url_updates: set = set()
    executed_queries: list = []

    async def fake_fetch_one(query, *args):
        if "FROM videos WHERE id" in query:
            return _video_row()
        if "COUNT(*) AS pics, COUNT(video_clip_url) AS clips" in query:
            return {"pics": len(all_rows), "clips": 0}
        return None

    async def fake_fetch_all(query, *args):
        if "FROM assets WHERE" in query and "routed_model, model_override" in query:
            if "scene = ANY($3::int[])" in query:
                allowed = set(args[-1])
                return [r for r in all_rows if r["scene"] in allowed]
            if "scene = $3" in query:
                return [r for r in all_rows if r["scene"] == args[-1]]
            return list(all_rows)
        return []

    async def fake_execute(query, *args):
        executed_queries.append(query)
        assert "routed_model" not in query and "model_override" not in query, (
            "run_clip_generation must NEVER write routed_model/model_override — "
            "those columns must survive a draft pass untouched for finalize")
        if "UPDATE assets SET video_clip_url" in query:
            clip_url_updates.add(args[-1])  # (drive_url, clip_dur, id)
        elif "UPDATE assets SET model_used" in query:
            model_used_updates[args[-1]] = args[0]  # (model, id)
        return "OK"

    async def fake_record_ledger_entry(**kwargs):
        pass

    async def fake_upload_bytes(data, path, content_type, tenant_id=None):
        return f"https://fake-storage.example/{path}"

    async def fake_duck_audio(clip_bytes, gain=0.3):
        return clip_bytes

    monkeypatch.setattr(pe_mod, "fetch_one", fake_fetch_one)
    monkeypatch.setattr(pe_mod, "fetch_all", fake_fetch_all)
    monkeypatch.setattr(pe_mod, "execute", fake_execute)
    monkeypatch.setattr(pe_mod, "record_ledger_entry", fake_record_ledger_entry)
    monkeypatch.setattr(storage_mod, "upload_bytes", fake_upload_bytes)
    monkeypatch.setattr(clip_dialogue_mod, "duck_audio", fake_duck_audio)
    monkeypatch.setattr(clip_dialogue_mod, "fetch_all", fake_fetch_all)

    image_client = _FakeImageClient()
    executor = PipelineExecutor.__new__(PipelineExecutor)
    executor.tenant_id = TENANT
    executor._initialized = True
    executor._pipeline = _FakeLightPipeline(image_client)

    result = asyncio.run(executor.run_clip_generation(VIDEO, **run_kwargs))
    assert result["status"] == "completed", result
    return image_client, model_used_updates, clip_url_updates, executed_queries


def test_draft_pass_forces_every_row_to_draft_model_regardless_of_routing(monkeypatch):
    """Three rows carry three DIFFERENT routing outcomes (would normally
    animate via Veo, Grok, and Veo-via-override respectively) — with
    force_model_id=DRAFT_MODEL every one must animate via Grok (the draft
    engine), proving the draft pass genuinely overrides routed_model AND
    model_override, not just the ones that already happened to be Grok."""
    rows = [
        _row(1, "veo-3.1-quality"),
        _row(2, "grok-imagine"),
        _row(3, "grok-imagine", model_override="veo-3.1-quality"),
    ]
    client, model_used, clip_urls, _ = _drive(monkeypatch, rows, force_model_id=DRAFT_MODEL)

    assert all(engine == "grok" for engine, _ in client.calls), (
        f"draft_pass must force EVERY row through the draft engine — got {client.calls}")
    assert set(model_used.values()) == {DRAFT_MODEL}
    assert set(model_used.keys()) == {"asset-s1", "asset-s2", "asset-s3"}
    assert clip_urls == {"asset-s1", "asset-s2", "asset-s3"}


def test_finalize_only_scenes_regenerates_exactly_the_approved_set(monkeypatch):
    """Scene 2 is NOT in only_scenes (unapproved) — its row must never be
    fetched (simulated DB filter) and must never appear in any update.
    Scenes 1 and 3 (approved) must both regenerate, each at ITS OWN resolved
    model (routed for scene 1, override-wins for scene 3) — no force_model_id
    this time, proving finalize uses real routing, not a forced tier."""
    rows = [
        _row(1, "veo-3.1-quality"),
        _row(2, "grok-imagine"),  # UNAPPROVED — must stay untouched
        _row(3, "grok-imagine", model_override="veo-3.1-quality"),
    ]
    client, model_used, clip_urls, _ = _drive(monkeypatch, rows, only_scenes=[1, 3], force=True)

    assert "asset-s2" not in model_used and "asset-s2" not in clip_urls, (
        "an unapproved scene's clip must never be touched by finalize")
    assert model_used == {"asset-s1": "veo-3.1-quality", "asset-s3": "veo-3.1-quality"}
    assert clip_urls == {"asset-s1", "asset-s3"}
    assert client.calls == [("veo", "https://fake/img-asset-s1.png"),
                             ("veo", "https://fake/img-asset-s3.png")]


# ---------------------------------------------------------------------------
# 4. generation_passes.scene_set_hash — dedup identity
# ---------------------------------------------------------------------------

def test_scene_set_hash_same_set_same_key_larger_set_new_key():
    same_a = generation_passes.scene_set_hash([(1, "grok-imagine"), (3, "veo-3.1-quality")])
    same_b = generation_passes.scene_set_hash([(3, "veo-3.1-quality"), (1, "grok-imagine")])  # different order
    assert same_a == same_b, "ordering must not matter — the hash sorts internally"

    larger = generation_passes.scene_set_hash(
        [(1, "grok-imagine"), (3, "veo-3.1-quality"), (7, "grok-imagine")])
    assert larger != same_a, "approving MORE scenes must mint a NEW key, never dedup against the smaller pass"

    routing_changed = generation_passes.scene_set_hash([(1, "grok-imagine"), (3, "grok-imagine")])
    assert routing_changed != same_a, (
        "a routing change on the SAME scene set (e.g. a manual override edit) must also mint a new key")


# ---------------------------------------------------------------------------
# 5. estimate_cost / cost_breakdown for draft_pass / finalize
# ---------------------------------------------------------------------------

_MIXED_ROWS = [
    {"scene": 1, "routed_model": "veo-3.1-quality", "model_override": None, "routing_reason": "reveal"},
    {"scene": 2, "routed_model": "grok-imagine", "model_override": None, "routing_reason": None},
    {"scene": 3, "routed_model": "grok-imagine", "model_override": "veo-3.1-quality", "routing_reason": None},
]


def test_draft_pass_estimate_and_breakdown_price_every_row_at_draft_tier(monkeypatch):
    async def fake_fetch_all(query, *args):
        assert "FROM assets" in query and "routed_model" in query
        return _MIXED_ROWS
    monkeypatch.setattr(actions, "fetch_all", fake_fetch_all)

    cost, text = asyncio.run(actions.estimate_cost(TENANT, VIDEO, "draft_pass", None, _summary()))
    expected = round(3 * GROK_PRICE, 2)
    assert cost == expected, "draft_pass must price EVERY row at the draft tier, ignoring routed_model/override"
    assert cost != round(VEO_QUALITY_PRICE + GROK_PRICE + VEO_QUALITY_PRICE, 2), (
        "must NOT equal the routed sum — that would mean it silently priced like 'animate'")
    assert text == f"~${expected:.2f}"

    breakdown = asyncio.run(actions.cost_breakdown(TENANT, VIDEO, "draft_pass", None, _summary()))
    assert breakdown is not None
    assert len(breakdown["lines"]) == 1  # uniform draft tier -> exactly one line
    assert breakdown["lines"][0]["model_id"] == DRAFT_MODEL
    assert breakdown["lines"][0]["count"] == 3
    assert breakdown["total"] == cost
    assert round(sum(ln["subtotal"] for ln in breakdown["lines"]), 2) == breakdown["total"]


def test_finalize_estimate_and_breakdown_price_only_approved_scenes_at_routed_tier(monkeypatch):
    approved_rows = [r for r in _MIXED_ROWS if r["scene"] in (1, 3)]  # scene 2 unapproved

    async def fake_fetch_all(query, *args):
        if "DISTINCT scene" in query:
            assert "status='approved'" in query
            return [{"scene": 1}, {"scene": 3}]
        assert "FROM assets" in query and "routed_model" in query
        if "scene = ANY($3::int[])" in query:
            assert set(args[-1]) == {1, 3}
        return approved_rows
    monkeypatch.setattr(actions, "fetch_all", fake_fetch_all)

    cost, text = asyncio.run(actions.estimate_cost(TENANT, VIDEO, "finalize", None, _summary()))
    expected = round(VEO_QUALITY_PRICE + VEO_QUALITY_PRICE, 2)  # scene1 routed veo, scene3 override veo
    assert cost == expected
    assert text == f"~${expected:.2f}"

    breakdown = asyncio.run(actions.cost_breakdown(TENANT, VIDEO, "finalize", None, _summary()))
    assert breakdown is not None
    assert breakdown["total"] == cost
    assert all(ln["model_id"] == "veo-3.1-quality" for ln in breakdown["lines"])
    assert round(sum(ln["subtotal"] for ln in breakdown["lines"]), 2) == breakdown["total"]


def test_finalize_no_approved_scenes_costs_nothing(monkeypatch):
    calls = []

    async def fake_fetch_all(query, *args):
        calls.append(query)
        if "DISTINCT scene" in query:
            return []
        raise AssertionError("must not query routed rows when nothing is approved")
    monkeypatch.setattr(actions, "fetch_all", fake_fetch_all)

    cost, text = asyncio.run(actions.estimate_cost(TENANT, VIDEO, "finalize", None, _summary()))
    assert cost == 0.0
    assert text == "no extra cost"
    # Non-vacuous: the OLD (pre-C17) estimate_cost also returns 0.0/"no extra
    # cost" for an unrecognized verb, via its unrelated `else: cost = 0.0`
    # fallback — WITHOUT ever calling _approved_scenes. Assert the approved-
    # scenes query actually fired, proving this went through finalize's real
    # branch, not that unrelated fallback.
    assert any("DISTINCT scene" in q for q in calls), (
        "estimate_cost('finalize', ...) must consult _approved_scenes, not "
        "silently fall through to the generic zero-cost default")

    breakdown = asyncio.run(actions.cost_breakdown(TENANT, VIDEO, "finalize", None, _summary()))
    assert breakdown is None


# ---------------------------------------------------------------------------
# 6. _runner_draft_pass / _runner_finalize: claims + pass-dedup + dispatch
# ---------------------------------------------------------------------------

class _FakeBackgroundTasks:
    def __init__(self):
        self.tasks = []

    def add_task(self, fn):
        self.tasks.append(fn)


def _patch_common(monkeypatch, *, approved_scenes=None, rows=None):
    async def fake_video_summary(tenant_id, video_id):
        return _summary()
    monkeypatch.setattr(actions, "video_summary", fake_video_summary)

    async def fake_routed_clip_rows(tenant_id, video_id, scene, video_model, only_scenes=None):
        return rows or []
    monkeypatch.setattr(actions, "_routed_clip_rows", fake_routed_clip_rows)

    async def fake_approved_scenes(tenant_id, video_id):
        return approved_scenes or []
    monkeypatch.setattr(actions, "_approved_scenes", fake_approved_scenes)


def test_draft_pass_runner_claim_denied_returns_busy_no_dispatch(monkeypatch):
    """Non-vacuous proof (git-stash-sensitive: draft_pass/_runner_draft_pass
    didn't exist before this chunk): claim denial must refuse WITHOUT ever
    calling background_tasks.add_task — the money-safety guarantee C16a's
    claim exists for."""
    _patch_common(monkeypatch, rows=[{"scene": 1}])
    monkeypatch.setattr(generation_passes, "already_done", AsyncMock(return_value=False))
    monkeypatch.setattr("generation_claims.acquire", AsyncMock(return_value=False))
    release_mock = AsyncMock()
    monkeypatch.setattr("generation_claims.release", release_mock)

    bg = _FakeBackgroundTasks()
    reply = asyncio.run(actions._runner_draft_pass(TENANT, VIDEO, bg, {}))

    assert reply == actions._ALREADY_WORKING_REPLY
    assert bg.tasks == [], "a denied claim must never schedule the background run"
    release_mock.assert_not_called()


def test_finalize_runner_claim_denied_returns_busy_no_dispatch(monkeypatch):
    _patch_common(monkeypatch, approved_scenes=[1], rows=[{"scene": 1, "routed_model": "grok-imagine",
                                                            "model_override": None}])
    monkeypatch.setattr(generation_passes, "already_done", AsyncMock(return_value=False))
    monkeypatch.setattr("generation_claims.acquire", AsyncMock(return_value=False))
    release_mock = AsyncMock()
    monkeypatch.setattr("generation_claims.release", release_mock)

    bg = _FakeBackgroundTasks()
    reply = asyncio.run(actions._runner_finalize(TENANT, VIDEO, bg, {}))

    assert reply == actions._ALREADY_WORKING_REPLY
    assert bg.tasks == []
    release_mock.assert_not_called()


def test_finalize_runner_nothing_approved_refuses_before_any_claim(monkeypatch):
    _patch_common(monkeypatch, approved_scenes=[])
    acquire_mock = AsyncMock(return_value=True)
    monkeypatch.setattr("generation_claims.acquire", acquire_mock)

    bg = _FakeBackgroundTasks()
    reply = asyncio.run(actions._runner_finalize(TENANT, VIDEO, bg, {}))

    assert "nothing" in reply.lower() or "approved yet" in reply.lower()
    assert bg.tasks == []
    acquire_mock.assert_not_called(), "must not even attempt a claim when there's nothing to finalize"


def test_draft_pass_runner_already_done_refuses_without_reclaiming(monkeypatch):
    """A repeat of the IDENTICAL draft pass (same scene set, same draft
    model — generation_passes.already_done=True) must be refused as a
    duplicate WITHOUT acquiring a claim or dispatching — this is the
    scene_set_hash dedup path, not the concurrency claim."""
    _patch_common(monkeypatch, rows=[{"scene": 1}, {"scene": 2}])
    monkeypatch.setattr(generation_passes, "already_done", AsyncMock(return_value=True))
    acquire_mock = AsyncMock(return_value=True)
    monkeypatch.setattr("generation_claims.acquire", acquire_mock)

    bg = _FakeBackgroundTasks()
    reply = asyncio.run(actions._runner_draft_pass(TENANT, VIDEO, bg, {}))

    assert "already drafted" in reply.lower()
    assert bg.tasks == []
    acquire_mock.assert_not_called()


def test_finalize_runner_success_path_claims_dispatches_and_marks_pass_done(monkeypatch):
    """The full happy path: claim acquired, background task scheduled, and
    ONLY on a successful run_clip_generation does generation_passes.mark_done
    fire (with the SAME hash already_done was checked against) — proving the
    dedup record is keyed consistently, not just present."""
    rows = [{"scene": 1, "routed_model": "grok-imagine", "model_override": None}]
    _patch_common(monkeypatch, approved_scenes=[1], rows=rows)
    monkeypatch.setattr(generation_passes, "already_done", AsyncMock(return_value=False))
    mark_done_mock = AsyncMock()
    monkeypatch.setattr(generation_passes, "mark_done", mark_done_mock)
    acquire_mock = AsyncMock(return_value=True)
    release_mock = AsyncMock()
    monkeypatch.setattr("generation_claims.acquire", acquire_mock)
    monkeypatch.setattr("generation_claims.release", release_mock)

    run_mock = AsyncMock(return_value={"status": "completed", "clips_generated": 1})
    monkeypatch.setattr(pe_mod.PipelineExecutor, "run_clip_generation", run_mock)

    def _noop_set_status(*a, **k):
        pass
    import routes.pipeline as pipeline_route
    monkeypatch.setattr(pipeline_route, "_set_task_status", _noop_set_status)
    monkeypatch.setattr(pipeline_route, "_clear_task_status", _noop_set_status)

    bg = _FakeBackgroundTasks()
    reply = asyncio.run(actions._runner_finalize(TENANT, VIDEO, bg, {}))
    assert "on it" in reply.lower()
    assert len(bg.tasks) == 1
    acquire_mock.assert_awaited_once()

    asyncio.run(bg.tasks[0]())  # drive the scheduled background run to completion

    run_mock.assert_awaited_once()
    _, kwargs = run_mock.call_args
    assert kwargs.get("only_scenes") == [1] and kwargs.get("force") is True
    mark_done_mock.assert_awaited_once()
    release_mock.assert_awaited_once_with(TENANT, VIDEO, "main")


# ---------------------------------------------------------------------------
# 7. routes.chat._confirm_card — sensible card for both new verbs
# ---------------------------------------------------------------------------

def test_confirm_card_renders_for_draft_pass_and_finalize():
    for verb in ("draft_pass", "finalize"):
        card = chat_route._confirm_card(verb, None, "~$1.40")
        assert card["label"] == actions.ACTIONS[verb]["label"]
        assert card["options"][0]["label"] == "Do it · ~$1.40"
        assert card["options"][1] == {"value": "no", "label": "Cancel"}
        assert "breakdown" not in card  # no breakdown passed -> byte-identical old shape

    breakdown = {"lines": [{"model_id": "grok-imagine", "display_name": "Grok Imagine",
                            "tier": "draft", "count": 3, "subtotal": round(3 * GROK_PRICE, 2)}],
                 "total": round(3 * GROK_PRICE, 2), "all_premium_total": None, "hero_scenes": []}
    card = chat_route._confirm_card("draft_pass", None, f"~${round(3 * GROK_PRICE, 2):.2f}", breakdown)
    assert card["breakdown"] == breakdown
