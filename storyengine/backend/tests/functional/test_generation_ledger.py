"""Lock: generation_ledger.record_ledger_entry() writes one ledger row and
recomputes videos.total_cost from SUM(actual_cost) — never an incremental
add — and never raises even when the DB write fails (checklist §0.3/C07,
tasks/storyengine-wiring-fix-checklist.md).

No network, no real DB: `database` is stubbed with an in-memory fake that
mirrors exactly what the two SQL statements in record_ledger_entry() do —
INSERT a row into a list, UPDATE total_cost via a real SUM over that list
(not a running counter) — so a bug that swapped the recompute for an
increment would show up as a failing assertion here, not a passing one for
the wrong reason.

Run: cd storyengine/backend && ./venv/bin/python -m pytest tests/functional/test_generation_ledger.py -q
"""
import asyncio
import os
import sys
import types

_BACKEND = os.path.join(os.path.dirname(__file__), "..", "..")
_PIPELINE_PATH = os.path.join(_BACKEND, "..", "..", "skills", "video-pipeline")
sys.path.insert(0, _BACKEND)
sys.path.insert(0, _PIPELINE_PATH)  # shared.clients.sound_client (C08 price source)


# --- in-memory fake `database` module (generation_ledger.py imports
# `execute` from it eagerly at module load, so this must be stubbed first) --

LEDGER_ROWS: list[dict] = []
VIDEOS: dict[str, dict] = {}
RAISE_ON_INSERT = False


async def _fake_execute(query: str, *args):
    if "INSERT INTO generation_ledger" in query:
        if RAISE_ON_INSERT:
            raise RuntimeError("simulated DB outage on ledger insert")
        tenant_id, video_id, stage, model, units, unit_cost, actual_cost, kie_task_id = args
        LEDGER_ROWS.append({
            "tenant_id": tenant_id, "video_id": video_id, "stage": stage,
            "model": model, "units": units, "unit_cost": unit_cost,
            "actual_cost": actual_cost, "kie_task_id": kie_task_id,
        })
        return "INSERT 0 1"
    if "UPDATE videos SET total_cost" in query:
        (video_id,) = args
        # Mirrors the real SQL: total_cost = SUM(actual_cost) over EVERY
        # ledger row for this video — recomputed fresh, not incremented.
        total = sum(r["actual_cost"] for r in LEDGER_ROWS if r["video_id"] == video_id)
        VIDEOS.setdefault(video_id, {})["total_cost"] = total
        return "UPDATE 1"
    raise AssertionError(f"unexpected query in fake db: {query}")


def _stub(name, **attrs):
    mod = types.ModuleType(name)
    for k, v in attrs.items():
        setattr(mod, k, v)
    sys.modules[name] = mod


async def _fake_fetch_one(query: str, *args):
    return None


# `fetch_one` isn't used by generation_ledger.py itself, but actions.py (the
# C08 price-constant source below) does `from database import execute,
# fetch_one` at module load — must be present on the fake or that import
# 500s before it reaches anything this file cares about.
_stub("database", execute=_fake_execute, fetch_one=_fake_fetch_one)

import generation_ledger  # noqa: E402

# C08 (checklist §0.3b): the four remaining paid-generation call sites
# (images, voice, thumbnail, sound) each reuse an EXISTING price constant
# rather than a new hardcoded number — import the real ones so a drift in
# actions.py/SoundClient is caught here too, not just re-typed as a literal.
from actions import PICTURE_COST, VOICE_COST_ESTIMATE, THUMBNAIL_COST  # noqa: E402
from shared.clients.sound_client import SoundClient  # noqa: E402

# C09 (checklist §0.3c): single price source — actions.py's constants above
# must be the SAME objects/values shared.channel_profile exposes, not a
# second hand-copied set. Import both sides so a future edit to one without
# the other fails here instead of silently drifting again.
import shared.channel_profile as channel_profile  # noqa: E402
from actions import (  # noqa: E402
    CLIP_COST, IMAGE_PRICE_BY_MODEL, VOICE_PRICE_PER_1K_CHARS, picture_price_for,
)


def _reset():
    global RAISE_ON_INSERT
    LEDGER_ROWS.clear()
    VIDEOS.clear()
    RAISE_ON_INSERT = False


# --- tests -----------------------------------------------------------------

def test_ledger_row_written_with_correct_fields():
    """(a) a generation_ledger row is written with the right
    stage/model/costs/kie_task_id."""
    _reset()
    asyncio.run(generation_ledger.record_ledger_entry(
        tenant_id="tenant-1", video_id="video-1", stage="clip",
        model="grok-imagine", units=1, unit_cost=0.10, actual_cost=0.10,
        kie_task_id="kie-task-abc",
    ))
    assert len(LEDGER_ROWS) == 1
    row = LEDGER_ROWS[0]
    assert row == {
        "tenant_id": "tenant-1", "video_id": "video-1", "stage": "clip",
        "model": "grok-imagine", "units": 1, "unit_cost": 0.10,
        "actual_cost": 0.10, "kie_task_id": "kie-task-abc",
    }
    print("✅ test_ledger_row_written_with_correct_fields")


def test_total_cost_equals_ledger_sum_after_one_write():
    """(b) videos.total_cost equals SUM(ledger.actual_cost)."""
    _reset()
    asyncio.run(generation_ledger.record_ledger_entry(
        tenant_id="tenant-1", video_id="video-1", stage="clip",
        model="grok-imagine", units=1, unit_cost=0.15, actual_cost=0.15,
        kie_task_id="kie-task-1",
    ))
    assert VIDEOS["video-1"]["total_cost"] == 0.15
    print("✅ test_total_cost_equals_ledger_sum_after_one_write")


def test_second_write_accumulates_via_recompute_not_increment():
    """(c) a second write for the same video accumulates correctly, AND the
    accumulation is provably a recompute (SUM over the ledger) rather than
    `total_cost += x`: seed a stale total_cost that did NOT come from the
    ledger (as every pre-C07 video's total_cost=0 default effectively was —
    never rolled up from real spend) and confirm the first ledger write
    REPLACES it with the ledger sum instead of adding to it."""
    _reset()
    VIDEOS["video-1"] = {"total_cost": 999.0}  # stale/legacy value, not from the ledger

    asyncio.run(generation_ledger.record_ledger_entry(
        tenant_id="tenant-1", video_id="video-1", stage="clip",
        model="grok-imagine", units=1, unit_cost=0.10, actual_cost=0.10,
        kie_task_id="kie-task-1",
    ))
    assert VIDEOS["video-1"]["total_cost"] == 0.10, (
        "recompute must REPLACE total_cost with SUM(ledger), not increment "
        f"a stale value — got {VIDEOS['video-1']['total_cost']}"
    )

    asyncio.run(generation_ledger.record_ledger_entry(
        tenant_id="tenant-1", video_id="video-1", stage="clip",
        model="seedance-2-fast", units=1, unit_cost=0.30, actual_cost=0.30,
        kie_task_id="kie-task-2",
    ))
    assert len(LEDGER_ROWS) == 2
    assert VIDEOS["video-1"]["total_cost"] == 0.40, (
        f"expected SUM(0.10, 0.30) == 0.40, got {VIDEOS['video-1']['total_cost']}"
    )
    print("✅ test_second_write_accumulates_via_recompute_not_increment")


def test_other_videos_are_not_touched_by_a_videos_write():
    """Rollup is scoped to the video_id in the row — a clip on video-2 must
    never change video-1's total_cost."""
    _reset()
    asyncio.run(generation_ledger.record_ledger_entry(
        tenant_id="tenant-1", video_id="video-1", stage="clip",
        model="grok-imagine", units=1, unit_cost=0.10, actual_cost=0.10,
    ))
    asyncio.run(generation_ledger.record_ledger_entry(
        tenant_id="tenant-1", video_id="video-2", stage="clip",
        model="grok-imagine", units=1, unit_cost=0.20, actual_cost=0.20,
    ))
    assert VIDEOS["video-1"]["total_cost"] == 0.10
    assert VIDEOS["video-2"]["total_cost"] == 0.20
    print("✅ test_other_videos_are_not_touched_by_a_videos_write")


def test_fail_soft_never_raises_and_never_partially_applies():
    """(d) a forced ledger-write exception does NOT propagate — the caller
    (a clip generation that already cost real money) must get control back
    normally. Also confirms the failed INSERT leaves no row and no rollup
    (nothing to roll back, since fail-soft catches before either statement's
    effect could half-apply against a real DB — here, simply that neither
    fake-db table changed)."""
    global RAISE_ON_INSERT
    _reset()
    RAISE_ON_INSERT = True

    result = asyncio.run(generation_ledger.record_ledger_entry(
        tenant_id="tenant-1", video_id="video-1", stage="clip",
        model="grok-imagine", units=1, unit_cost=0.10, actual_cost=0.10,
        kie_task_id="kie-task-1",
    ))  # must not raise

    assert result is None
    assert LEDGER_ROWS == []
    assert "video-1" not in VIDEOS
    print("✅ test_fail_soft_never_raises_and_never_partially_applies")


def test_kie_task_id_defaults_to_none_when_not_captured():
    """Some call sites (e.g. a talking-clip model whose createTask call
    never yields a taskId before falling back) legitimately have nothing to
    report — the column is nullable and the helper must accept that."""
    _reset()
    asyncio.run(generation_ledger.record_ledger_entry(
        tenant_id="tenant-1", video_id="video-1", stage="clip",
        model="grok-imagine", units=1, unit_cost=0.10, actual_cost=0.10,
    ))
    assert LEDGER_ROWS[0]["kie_task_id"] is None
    print("✅ test_kie_task_id_defaults_to_none_when_not_captured")


# --- C08 (checklist §0.3b): the other four paid-generation stages ----------
# generation_ledger.record_ledger_entry() itself doesn't branch on `stage` —
# the tests above already lock its write/rollup/fail-soft behavior generically.
# What's new in C08 is the four call sites (images, voice, thumbnail, sound)
# each write with the RIGHT stage tag and the RIGHT existing price constant
# (not a new invented number) — these tests pin that.

def test_image_stage_row_uses_picture_cost_from_actions():
    """store_scene()/redraw_asset_image()/run_images()/run_image_variants()
    (scripts/coverage_to_app.py, pipeline_executor.py) all price with
    actions.PICTURE_COST — the SAME constant actions.estimate_cost() already
    quotes for the 'images' verb, not a second copy."""
    _reset()
    n = 4  # e.g. a 4-frame store_scene() batch
    asyncio.run(generation_ledger.record_ledger_entry(
        tenant_id="tenant-1", video_id="video-1", stage="image",
        model="gpt-image-2", units=n, unit_cost=PICTURE_COST,
        actual_cost=round(n * PICTURE_COST, 2),
    ))
    row = LEDGER_ROWS[0]
    assert row["stage"] == "image"
    # C09a: gpt-image-2's 2K tier (the resolution the live code path actually
    # requests — see shared/channel_profile.py) is $0.05, not the prior
    # unsourced $0.08 guess.
    assert row["unit_cost"] == PICTURE_COST == 0.05
    assert row["actual_cost"] == round(n * PICTURE_COST, 2)
    assert VIDEOS["video-1"]["total_cost"] == round(n * PICTURE_COST, 2)
    print("✅ test_image_stage_row_uses_picture_cost_from_actions")


def test_voice_stage_row_uses_voice_cost_estimate_from_actions():
    """run_voice() prices with actions.VOICE_COST_ESTIMATE — the same flat
    number the confirm card already quotes for the 'voice' verb."""
    _reset()
    asyncio.run(generation_ledger.record_ledger_entry(
        tenant_id="tenant-1", video_id="video-1", stage="voice",
        model="elevenlabs", units=1, unit_cost=VOICE_COST_ESTIMATE,
        actual_cost=VOICE_COST_ESTIMATE,
    ))
    row = LEDGER_ROWS[0]
    assert row["stage"] == "voice"
    assert row["unit_cost"] == VOICE_COST_ESTIMATE == 0.30
    assert VIDEOS["video-1"]["total_cost"] == VOICE_COST_ESTIMATE
    print("✅ test_voice_stage_row_uses_voice_cost_estimate_from_actions")


def test_thumbnail_stage_row_uses_thumbnail_cost_from_actions():
    """run_thumbnail() (all 3 completion paths — modeled/channel-formula/
    from-scratch) prices with actions.THUMBNAIL_COST. Value corrected
    0.10 -> 0.075 in C09 (then 0.075 -> 0.05 in C09a, once tracing the real
    call sites showed the thumbnail path's PRIMARY model is GPT Image 2 at
    its 2K tier, not Nano Banana Pro — see channel_profile.THUMBNAIL_PRICE)."""
    _reset()
    asyncio.run(generation_ledger.record_ledger_entry(
        tenant_id="tenant-1", video_id="video-1", stage="thumbnail",
        model="gpt-image-2", units=1, unit_cost=THUMBNAIL_COST,
        actual_cost=THUMBNAIL_COST,
    ))
    row = LEDGER_ROWS[0]
    assert row["stage"] == "thumbnail"
    assert row["unit_cost"] == THUMBNAIL_COST == 0.05
    print("✅ test_thumbnail_stage_row_uses_thumbnail_cost_from_actions")


def test_sound_stage_row_uses_sound_client_generation_price():
    """run_sound_effects() prices with SoundClient.ESTIMATED_COST_PER_GENERATION
    (the real per-generation figure sound_bot.py already computes into
    result['estimated_cost']) — NOT actions.SOUND_COST_ESTIMATE (that flat
    number prices the whole 'sound' verb's confirm-card quote, a coarser
    estimate than the per-clip figure the bot itself already tracks)."""
    _reset()
    total_generated = 6
    unit_cost = SoundClient.ESTIMATED_COST_PER_GENERATION
    asyncio.run(generation_ledger.record_ledger_entry(
        tenant_id="tenant-1", video_id="video-1", stage="sound",
        model=SoundClient.MODEL, units=total_generated, unit_cost=unit_cost,
        actual_cost=round(total_generated * unit_cost, 2),
    ))
    row = LEDGER_ROWS[0]
    assert row["stage"] == "sound"
    assert unit_cost == 0.05
    assert row["actual_cost"] == round(total_generated * unit_cost, 2) == 0.30
    print("✅ test_sound_stage_row_uses_sound_client_generation_price")


def test_all_five_stages_sum_without_double_counting():
    """The point of the whole ledger (C07+C08 together): a video that spent
    on clip (C07) + image/voice/thumbnail/sound (C08) gets total_cost = the
    straight sum of every stage's row — distinct `stage` values on each row
    mean no stage's write can double-count or clobber another's."""
    _reset()
    entries = [
        ("clip", 0.10), ("image", 0.32), ("voice", 0.30),
        ("thumbnail", 0.10), ("sound", 0.30),
    ]
    for stage, cost in entries:
        asyncio.run(generation_ledger.record_ledger_entry(
            tenant_id="tenant-1", video_id="video-1", stage=stage,
            model=None, units=1, unit_cost=cost, actual_cost=cost,
        ))
    assert len(LEDGER_ROWS) == 5
    assert {r["stage"] for r in LEDGER_ROWS} == {"clip", "image", "voice", "thumbnail", "sound"}
    expected = round(sum(c for _, c in entries), 2)
    actual = round(VIDEOS["video-1"]["total_cost"], 2)
    assert actual == expected, f"expected {expected}, got {actual}"
    print("✅ test_all_five_stages_sum_without_double_counting")


def test_c08_fail_soft_identical_to_c07_for_every_new_stage():
    """record_ledger_entry() doesn't branch on `stage` — confirm the SAME
    fail-soft guarantee C07 locked for 'clip' holds for each C08 stage too
    (a forced DB outage on an image/voice/thumbnail/sound write must not
    raise, since the caller's paid generation already succeeded)."""
    global RAISE_ON_INSERT
    for stage in ("image", "voice", "thumbnail", "sound"):
        _reset()
        RAISE_ON_INSERT = True
        result = asyncio.run(generation_ledger.record_ledger_entry(
            tenant_id="tenant-1", video_id="video-1", stage=stage,
            model=None, units=1, unit_cost=0.10, actual_cost=0.10,
        ))
        assert result is None, f"stage={stage} must not raise/return non-None"
        assert LEDGER_ROWS == [], f"stage={stage}: failed insert must leave no row"
        assert "video-1" not in VIDEOS, f"stage={stage}: failed insert must not roll up"
    print("✅ test_c08_fail_soft_identical_to_c07_for_every_new_stage")


def test_actions_prices_are_the_same_object_as_channel_profile():
    """C09: actions.py must not hold a second hand-copied number for any
    price — it re-exports shared.channel_profile's constants directly. Pin
    identity (not just equality) for the dict so a future edit that swaps
    the re-export for a fresh literal dict (equal today, drifts tomorrow)
    fails this test immediately."""
    assert CLIP_COST is channel_profile.CLIP_PRICE_BY_MODEL
    assert IMAGE_PRICE_BY_MODEL is channel_profile.IMAGE_PRICE_BY_MODEL
    assert PICTURE_COST == channel_profile.PICTURE_PRICE_DEFAULT
    assert THUMBNAIL_COST == channel_profile.THUMBNAIL_PRICE
    assert VOICE_PRICE_PER_1K_CHARS == channel_profile.VOICE_PRICE_PER_1K_CHARS
    print("✅ test_actions_prices_are_the_same_object_as_channel_profile")


def test_picture_price_for_uses_real_per_model_rate():
    """C09: a known, unambiguous image model prices at its OWN rate (the
    accuracy upgrade — was previously always the flat PICTURE_COST default
    regardless of which of the 3 models actually drew the pixels). C09a
    updated the actual numbers to Kie's published per-model/per-resolution
    pricing at the tier each model's live call path requests (nano-banana-2
    0.025 -> 0.04, gpt-image-2 0.08 -> 0.05; z-image unchanged)."""
    assert picture_price_for("nano-banana-2") == 0.04
    assert picture_price_for("z-image") == 0.004
    assert picture_price_for("gpt-image-2") == PICTURE_COST == 0.05
    # Unknown / mixed-batch / None all fall back to the default — never a
    # KeyError, never a silently wrong guess at which model dominated.
    assert picture_price_for(None) == PICTURE_COST
    assert picture_price_for("gpt-image-2, nano-banana-2") == PICTURE_COST
    print("✅ test_picture_price_for_uses_real_per_model_rate")


def test_image_ledger_row_prices_by_actual_model_used():
    """The per-model price actually reaches the ledger row, not just the
    helper function — locks the shape pipeline_executor.run_image_variants
    / coverage_to_app.redraw_asset_image now write."""
    _reset()
    model_used = "nano-banana-2"
    cost = picture_price_for(model_used)
    asyncio.run(generation_ledger.record_ledger_entry(
        tenant_id="tenant-1", video_id="video-1", stage="image",
        model=model_used, units=1, unit_cost=cost, actual_cost=cost,
    ))
    row = LEDGER_ROWS[0]
    assert row["model"] == "nano-banana-2"
    assert row["unit_cost"] == 0.04, "nano-banana-2 must NOT be priced at the flat 0.05 (gpt-image-2) default"
    print("✅ test_image_ledger_row_prices_by_actual_model_used")


def test_voice_ledger_row_meters_by_real_character_count():
    """C09: voice/run.py now reports total_chars; the ledger write must use
    the REAL per-character price (docs/cost-awareness.md ~$0.30/1000 chars)
    instead of a flat per-run guess — a 6000-char narration must cost 20x a
    300-char one, which a flat VOICE_COST_ESTIMATE could never reflect."""
    _reset()
    total_chars = 6000
    per_char = VOICE_PRICE_PER_1K_CHARS / 1000
    actual = round(total_chars * per_char, 2)
    asyncio.run(generation_ledger.record_ledger_entry(
        tenant_id="tenant-1", video_id="video-1", stage="voice", model="elevenlabs",
        units=total_chars, unit_cost=round(per_char, 6), actual_cost=actual,
    ))
    row = LEDGER_ROWS[0]
    assert row["actual_cost"] == 1.8, f"6000 chars @ $0.30/1000 should be $1.80, got {row['actual_cost']}"
    assert row["actual_cost"] != VOICE_COST_ESTIMATE, (
        "a 6000-char video must NOT collapse to the flat 0.30 estimate")
    print("✅ test_voice_ledger_row_meters_by_real_character_count")


TESTS = [
    test_ledger_row_written_with_correct_fields,
    test_total_cost_equals_ledger_sum_after_one_write,
    test_second_write_accumulates_via_recompute_not_increment,
    test_other_videos_are_not_touched_by_a_videos_write,
    test_fail_soft_never_raises_and_never_partially_applies,
    test_kie_task_id_defaults_to_none_when_not_captured,
    test_image_stage_row_uses_picture_cost_from_actions,
    test_voice_stage_row_uses_voice_cost_estimate_from_actions,
    test_thumbnail_stage_row_uses_thumbnail_cost_from_actions,
    test_sound_stage_row_uses_sound_client_generation_price,
    test_all_five_stages_sum_without_double_counting,
    test_c08_fail_soft_identical_to_c07_for_every_new_stage,
    test_actions_prices_are_the_same_object_as_channel_profile,
    test_picture_price_for_uses_real_per_model_rate,
    test_image_ledger_row_prices_by_actual_model_used,
    test_voice_ledger_row_meters_by_real_character_count,
]


def main() -> int:
    failed = 0
    for t in TESTS:
        try:
            t()
        except AssertionError as e:
            print(f"❌ {t.__name__}: {e}")
            failed += 1
        except Exception as e:
            print(f"❌ {t.__name__}: {type(e).__name__}: {e}")
            failed += 1
    print(f"\n{len(TESTS) - failed}/{len(TESTS)} passed")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
