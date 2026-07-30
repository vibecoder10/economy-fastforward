"""Unit tests for shared.clients.image_model_router — the ONE resolver that
turns a video's `image_model_override` into an actual ImageClient call,
shared by storyengine/backend/scripts/coverage_to_app.py (redo_characters,
generate_storyboard_sheet_for_scene, redraw_asset_image) and the legacy
pipeline_executor.py `run_image_variants` path.

No network: a FakeImageClient records which method was called with which
args instead of hitting Kie. See storyengine-wiring-fix-checklist.md §0.1
("the Pictures model select writes image_model_override, but the live path
ignores it") — these tests are the trace-level proof that the override now
reaches the generation call, AND that the untouched default (no override)
path calls the exact same methods with the exact same arguments as before
this fix (so existing videos render byte-identically).
"""
import asyncio

from shared.clients.image_model_router import (
    VALID_IMAGE_MODELS,
    generate_scene_image_for_model,
)


class FakeImageClient:
    """Records every call; `plan` maps method name -> return value (or a list
    of return values consumed in order, for methods called more than once)."""

    SCENE_MODEL = "nano-banana-2"  # mirrors ImageClient.SCENE_MODEL

    def __init__(self, plan: dict):
        self.plan = dict(plan)
        self.calls: list[tuple[str, tuple, dict]] = []

    def _consume(self, name):
        val = self.plan.get(name)
        if isinstance(val, list):
            return val.pop(0) if val else None
        return val

    # C16c: every method below now accepts `task_id_out` (an optional list
    # the caller appends the provider's Kie taskId into — same fresh-box-
    # per-call pattern as generate_video's task_id_out, see image_client.py).
    # FakeImageClient appends a deterministic fake id per method so tests can
    # assert the box picked up the id from whichever attempt succeeded.

    async def generate_scene_image_zimage(self, prompt, aspect_ratio="16:9", task_id_out=None):
        self.calls.append(("generate_scene_image_zimage", (prompt,), {"aspect_ratio": aspect_ratio}))
        if task_id_out is not None:
            task_id_out.append("task-zimage")
        return self._consume("generate_scene_image_zimage")

    async def generate_with_reference(self, prompt, reference_image_url, aspect_ratio="16:9",
                                       resolution="1K", task_id_out=None, fail_info_out=None):
        self.calls.append(("generate_with_reference", (prompt, reference_image_url),
                            {"aspect_ratio": aspect_ratio}))
        if task_id_out is not None:
            task_id_out.append("task-with-reference")
        result = self._consume("generate_with_reference")
        # C25a-fix-nano-sheets: mirrors generate_thumbnail_gpt2's fail_info_out
        # fixture convention below — 'generate_with_reference_fail_info' is the
        # opt-in key for tests asserting on a nano-path failure signature.
        if result is None and fail_info_out is not None:
            info = self._consume("generate_with_reference_fail_info")
            if info is not None:
                fail_info_out.append(info)
        return result

    async def generate_and_wait(self, prompt, aspect_ratio="16:9", model=None, task_id_out=None,
                                 fail_info_out=None):
        self.calls.append(("generate_and_wait", (prompt,), {"aspect_ratio": aspect_ratio, "model": model}))
        if task_id_out is not None:
            task_id_out.append("task-and-wait")
        urls = self._consume("generate_and_wait")
        if urls is None and fail_info_out is not None:
            info = self._consume("generate_and_wait_fail_info")
            if info is not None:
                fail_info_out.append(info)
        return urls

    async def generate_thumbnail_gpt2(self, prompt, reference_image_url, aspect_ratio="16:9",
                                       resolution="2K", task_id_out=None, fail_info_out=None):
        self.calls.append(("generate_thumbnail_gpt2", (prompt, reference_image_url),
                            {"aspect_ratio": aspect_ratio, "resolution": resolution}))
        if task_id_out is not None:
            task_id_out.append("task-thumbnail-gpt2")
        result = self._consume("generate_thumbnail_gpt2")
        # C25a-fix8: mirrors the real poll_for_completion contract — fail_info_out
        # gets populated on a FAILED call, same as task_id_out gets populated on
        # a successful one. `plan["generate_thumbnail_gpt2_fail_info"]` is an
        # opt-in test fixture key (a dict, or a list of dicts consumed in the
        # same order as the method's own return values) for tests that need to
        # assert what the caller does with a specific failure signature.
        if result is None and fail_info_out is not None:
            info = self._consume("generate_thumbnail_gpt2_fail_info")
            if info is not None:
                fail_info_out.append(info)
        return result

    async def generate_scene_image_gpt(self, prompt, reference_image_url, aspect_ratio="16:9",
                                        resolution="2K", task_id_out=None):
        self.calls.append(("generate_scene_image_gpt", (prompt, reference_image_url),
                            {"aspect_ratio": aspect_ratio, "resolution": resolution}))
        if task_id_out is not None:
            task_id_out.append("task-scene-image-gpt")
        return self._consume("generate_scene_image_gpt")


def _run(coro):
    return asyncio.run(coro)


def test_valid_image_models_matches_known_good_values():
    # The exact 3 values the Pictures selector writes (ScenesWorkspaceTab L1121-1126).
    assert VALID_IMAGE_MODELS == {"nano-banana-2", "gpt-image-2", "z-image"}


# --- default / unset / 'gpt-image-2' override: the PRE-EXISTING behavior, unchanged ---

def test_default_no_override_with_refs_calls_gpt_thumbnail_unchanged():
    """This is byte-for-byte what coverage_to_app.py's 3 call sites did before this
    fix: `generate_thumbnail_gpt2(prompt, refs, aspect, resolution=resolution)`."""
    ic = FakeImageClient({"generate_thumbnail_gpt2": {"url": "https://img/gpt.png", "model": "gpt-image-2"}})
    url, model = _run(generate_scene_image_for_model(
        ic, None, "a prompt", reference_urls=["ref1", "ref2"], aspect_ratio="16:9", resolution="2K"))
    assert url == "https://img/gpt.png"
    assert model == "gpt-image-2"
    assert ic.calls == [("generate_thumbnail_gpt2", ("a prompt", ["ref1", "ref2"]),
                          {"aspect_ratio": "16:9", "resolution": "2K"})]


def test_default_no_override_without_refs_calls_gpt_text_to_image_unchanged():
    """No refs -> generate_scene_image_gpt(prompt, None, aspect, resolution=resolution).

    The default resolution is "1K", NOT "2K". This assertion said "2K" and had
    been failing ever since generate_scene_image_for_model's default was
    lowered on 2026-07-21 (Ryan: "we dont need a 2k gpt image... downgrade it
    to 1k so its cheaper"). The old 2K default silently made per-shot redraws,
    character 4-view sheets, image variants and storyboard sheets cost ~2x the
    batch pictures run, which already drew at 1K explicitly.

    So this test was arguing to double the image bill. Pinned to 1K on
    2026-07-30 so it defends that cost decision instead of contradicting it.
    A caller that genuinely needs 2K must ask for it explicitly."""
    ic = FakeImageClient({"generate_scene_image_gpt": {"url": "https://img/gpt2.png", "model": "gpt-image-2"}})
    url, model = _run(generate_scene_image_for_model(ic, "", "a prompt", aspect_ratio="16:9"))
    assert url == "https://img/gpt2.png"
    assert model == "gpt-image-2"
    assert ic.calls == [("generate_scene_image_gpt", ("a prompt", None), {"aspect_ratio": "16:9", "resolution": "1K"})]


def test_gpt_image_2_explicit_override_behaves_like_default():
    ic = FakeImageClient({"generate_scene_image_gpt": {"url": "https://img/gpt3.png", "model": "gpt-image-2"}})
    url, model = _run(generate_scene_image_for_model(ic, "gpt-image-2", "p", aspect_ratio="16:9"))
    assert (url, model) == ("https://img/gpt3.png", "gpt-image-2")


def test_default_path_surfaces_internal_gpt_to_nano_fallback_truthfully():
    """generate_scene_image_gpt can itself silently fall back to nano-banana-2 on a
    content-policy block; the resolver must report the TRUE model, not assume gpt."""
    ic = FakeImageClient({"generate_scene_image_gpt": {"url": "https://img/nano-fallback.png", "model": "nano-banana-2"}})
    url, model = _run(generate_scene_image_for_model(ic, None, "p", aspect_ratio="16:9"))
    assert (url, model) == ("https://img/nano-fallback.png", "nano-banana-2")


def test_unrecognized_override_falls_back_to_default_gpt_path():
    ic = FakeImageClient({"generate_scene_image_gpt": {"url": "https://img/x.png", "model": "gpt-image-2"}})
    url, model = _run(generate_scene_image_for_model(ic, "made-up-model", "p", aspect_ratio="16:9"))
    assert (url, model) == ("https://img/x.png", "gpt-image-2")


# --- 'z-image' override ---

def test_zimage_override_success_never_touches_gpt():
    ic = FakeImageClient({"generate_scene_image_zimage": {"url": "https://img/z.png"}})
    url, model = _run(generate_scene_image_for_model(
        ic, "z-image", "p", reference_urls=["ref1"], aspect_ratio="9:16"))
    assert (url, model) == ("https://img/z.png", "z-image")
    assert [c[0] for c in ic.calls] == ["generate_scene_image_zimage"]
    assert ic.calls[0][2]["aspect_ratio"] == "9:16"


def test_zimage_override_falls_back_to_gpt_on_failure():
    ic = FakeImageClient({
        "generate_scene_image_zimage": None,  # z-image failed
        "generate_thumbnail_gpt2": {"url": "https://img/fallback.png", "model": "gpt-image-2"},
    })
    url, model = _run(generate_scene_image_for_model(
        ic, "z-image", "p", reference_urls=["ref1"], aspect_ratio="16:9"))
    assert (url, model) == ("https://img/fallback.png", "gpt-image-2")
    assert [c[0] for c in ic.calls] == ["generate_scene_image_zimage", "generate_thumbnail_gpt2"]


# --- 'nano-banana-2' override ---

def test_nano_override_with_refs_uses_generate_with_reference():
    ic = FakeImageClient({"generate_with_reference": {"url": "https://img/nano.png"}})
    url, model = _run(generate_scene_image_for_model(
        ic, "nano-banana-2", "p", reference_urls=["ref1", "ref2"], aspect_ratio="16:9"))
    assert (url, model) == ("https://img/nano.png", "nano-banana-2")
    assert ic.calls[0][0] == "generate_with_reference"
    assert ic.calls[0][1] == ("p", ["ref1", "ref2"])


def test_nano_override_without_refs_uses_generate_and_wait_with_scene_model():
    # generate_and_wait itself returns a list[str] of URLs — wrap it in an extra
    # list so FakeImageClient's "list = sequence of per-call return values"
    # convention pops that whole list back out for the single call made here.
    ic = FakeImageClient({"generate_and_wait": [["https://img/nano2.png"]]})
    url, model = _run(generate_scene_image_for_model(ic, "nano-banana-2", "p", aspect_ratio="16:9"))
    assert (url, model) == ("https://img/nano2.png", "nano-banana-2")
    assert ic.calls[0] == ("generate_and_wait", ("p",), {"aspect_ratio": "16:9", "model": "nano-banana-2"})


def test_nano_override_falls_back_to_gpt_on_failure():
    ic = FakeImageClient({
        "generate_with_reference": None,
        "generate_thumbnail_gpt2": {"url": "https://img/fallback2.png", "model": "gpt-image-2"},
    })
    url, model = _run(generate_scene_image_for_model(
        ic, "nano-banana-2", "p", reference_urls=["ref1"], aspect_ratio="16:9"))
    assert (url, model) == ("https://img/fallback2.png", "gpt-image-2")
    assert [c[0] for c in ic.calls] == ["generate_with_reference", "generate_thumbnail_gpt2"]


def test_every_attempt_failing_returns_none_none():
    ic = FakeImageClient({"generate_scene_image_zimage": None, "generate_scene_image_gpt": None})
    url, model = _run(generate_scene_image_for_model(ic, "z-image", "p", aspect_ratio="16:9"))
    assert (url, model) == (None, None)


# --- C16c: task_id_out threading (S7-5 HIGH — generation_ledger dedup index
# needs a real provider task id to have teeth beyond the clip stage). Callers
# (redraw_asset_image, run_image_variants) pass a fresh box per call and read
# box[0] into record_ledger_entry's kie_task_id — these tests pin that the
# router actually threads the box down to whichever branch runs. ------------

def test_task_id_out_reaches_default_gpt_thumbnail_path():
    ic = FakeImageClient({"generate_thumbnail_gpt2": {"url": "https://img/gpt.png", "model": "gpt-image-2"}})
    box: list = []
    _run(generate_scene_image_for_model(
        ic, None, "p", reference_urls=["ref1"], aspect_ratio="16:9", task_id_out=box))
    assert box == ["task-thumbnail-gpt2"]


def test_task_id_out_reaches_default_gpt_text_to_image_path():
    ic = FakeImageClient({"generate_scene_image_gpt": {"url": "https://img/x.png", "model": "gpt-image-2"}})
    box: list = []
    _run(generate_scene_image_for_model(ic, "", "p", aspect_ratio="16:9", task_id_out=box))
    assert box == ["task-scene-image-gpt"]


def test_task_id_out_reaches_zimage_path():
    ic = FakeImageClient({"generate_scene_image_zimage": {"url": "https://img/z.png"}})
    box: list = []
    _run(generate_scene_image_for_model(ic, "z-image", "p", aspect_ratio="16:9", task_id_out=box))
    assert box == ["task-zimage"]


def test_task_id_out_reaches_nano_with_reference_path():
    ic = FakeImageClient({"generate_with_reference": {"url": "https://img/nano.png"}})
    box: list = []
    _run(generate_scene_image_for_model(
        ic, "nano-banana-2", "p", reference_urls=["ref1"], aspect_ratio="16:9", task_id_out=box))
    assert box == ["task-with-reference"]


def test_task_id_out_reaches_nano_generate_and_wait_path():
    ic = FakeImageClient({"generate_and_wait": [["https://img/nano2.png"]]})
    box: list = []
    _run(generate_scene_image_for_model(ic, "nano-banana-2", "p", aspect_ratio="16:9", task_id_out=box))
    assert box == ["task-and-wait"]


def test_task_id_out_accumulates_across_fallback_but_box0_is_first_attempt():
    """z-image fails (its own task id still lands in the box — a task WAS
    created even though the poll/URL extraction failed) then falls back to
    gpt thumbnail (a second, different task id appends). box[0] — the FIRST
    attempt's task id — is the convention record_ledger_entry callers read
    (same as the clip path's task_id_box[0]); this test documents that the
    box is an append-only trace of every attempt, not just the winner."""
    ic = FakeImageClient({
        "generate_scene_image_zimage": None,
        "generate_thumbnail_gpt2": {"url": "https://img/fallback.png", "model": "gpt-image-2"},
    })
    box: list = []
    url, model = _run(generate_scene_image_for_model(
        ic, "z-image", "p", reference_urls=["ref1"], aspect_ratio="16:9", task_id_out=box))
    assert (url, model) == ("https://img/fallback.png", "gpt-image-2")
    assert box == ["task-zimage", "task-thumbnail-gpt2"]
    assert box[0] == "task-zimage"  # what a caller reading box[0] would record


def test_task_id_out_is_none_safe_when_caller_does_not_pass_it():
    """Existing callers (coverage_to_app's store_scene batch path, etc.) that
    never pass task_id_out must be completely unaffected — no TypeError, no
    behavior change."""
    ic = FakeImageClient({"generate_scene_image_gpt": {"url": "https://img/x.png", "model": "gpt-image-2"}})
    url, model = _run(generate_scene_image_for_model(ic, "", "p", aspect_ratio="16:9"))
    assert (url, model) == ("https://img/x.png", "gpt-image-2")


# --- C25a-fix8: fail_info_out threading (storyboard sheet dispatch needs the
# raw failCode/failMsg/creditsConsumed to detect the specific OpenAI content-
# filter rejection signature and retry with a different header). -----------

def test_fail_info_out_reaches_default_gpt_thumbnail_path_on_failure():
    """A REAL (credit-consuming) failure — not the zero-cost filter class —
    never re-rolls (see the Change-2 re-roll section below for that), so this
    stays the original single-attempt shape: exactly 1 generate_thumbnail_gpt2
    call, its failure detail lands in fail_info_out once. C25a-fix-gpt-reroll
    (2026-07-21) also means a real failure now falls back to nano-banana-2
    immediately (see test_credit_consuming_failure_falls_back_to_nano_
    immediately below for that in isolation) — this fixture leaves
    generate_with_reference unplanned (returns None), so the end result stays
    (None, None), same as before that change landed."""
    ic = FakeImageClient({
        "generate_thumbnail_gpt2": None,
        "generate_thumbnail_gpt2_fail_info": {
            "failCode": "500", "failMsg": "some real production error", "creditsConsumed": 1.2,
        },
    })
    box: list = []
    url, model = _run(generate_scene_image_for_model(
        ic, None, "p", reference_urls=["ref1"], aspect_ratio="16:9", fail_info_out=box))
    assert (url, model) == (None, None)
    assert box == [{"failCode": "500", "failMsg": "some real production error", "creditsConsumed": 1.2}]
    assert [c[0] for c in ic.calls] == ["generate_thumbnail_gpt2", "generate_with_reference"]


def test_fail_info_out_untouched_on_success():
    ic = FakeImageClient({"generate_thumbnail_gpt2": {"url": "https://img/gpt.png", "model": "gpt-image-2"}})
    box: list = []
    _run(generate_scene_image_for_model(
        ic, None, "p", reference_urls=["ref1"], aspect_ratio="16:9", fail_info_out=box))
    assert box == []


def test_fail_info_out_is_none_safe_when_caller_does_not_pass_it():
    """Existing callers (coverage_to_app's store_scene batch path, redraw_
    asset_image, etc.) that never pass fail_info_out must be completely
    unaffected — no TypeError, no behavior change, on success OR failure."""
    ic = FakeImageClient({
        "generate_thumbnail_gpt2": None,
        "generate_thumbnail_gpt2_fail_info": {"failCode": "400", "failMsg": "x", "creditsConsumed": 0.0},
    })
    url, model = _run(generate_scene_image_for_model(
        ic, None, "p", reference_urls=["ref1"], aspect_ratio="16:9"))
    assert (url, model) == (None, None)


# ---------------------------------------------------------------------------
# C25a-fix-nano-sheets (2026-07-21): no_gpt_fallback — the ONLY caller-facing
# change to the nano-banana-2 branch. When True, a failed nano attempt
# returns (None, None) directly instead of walking into _gpt_default — the
# mechanism storyboard sheets (coverage_to_app.py's _draw_board) rely on to
# stay off GPT Image 2's OpenAI-filtered endpoint entirely. The end-to-end
# proof (real router + real coverage_to_app.py call sites) lives in
# storyengine/backend/tests/functional/test_c25a_fix7_gpt_sheet_ref_cap.py —
# these are the router-level unit pins for the flag itself.
# ---------------------------------------------------------------------------

def test_no_gpt_fallback_keeps_failed_nano_from_reaching_gpt():
    ic = FakeImageClient({"generate_with_reference": None})  # nano fails, nothing else planned
    url, model = _run(generate_scene_image_for_model(
        ic, "nano-banana-2", "p", reference_urls=["ref1"], aspect_ratio="16:9",
        no_gpt_fallback=True))
    assert (url, model) == (None, None)
    assert [c[0] for c in ic.calls] == ["generate_with_reference"]  # never touched a GPT method


def test_no_gpt_fallback_false_by_default_unchanged_behavior():
    """Every OTHER caller (PICTURES via an explicit nano-banana-2 override)
    never passes no_gpt_fallback and keeps the pre-existing GPT-fallback
    behavior — same assertion as test_nano_override_falls_back_to_gpt_on_
    failure above, pinned again here explicitly against the default value."""
    ic = FakeImageClient({
        "generate_with_reference": None,
        "generate_thumbnail_gpt2": {"url": "https://img/fallback.png", "model": "gpt-image-2"},
    })
    url, model = _run(generate_scene_image_for_model(
        ic, "nano-banana-2", "p", reference_urls=["ref1"], aspect_ratio="16:9"))
    assert (url, model) == ("https://img/fallback.png", "gpt-image-2")
    assert [c[0] for c in ic.calls] == ["generate_with_reference", "generate_thumbnail_gpt2"]


def test_no_gpt_fallback_irrelevant_on_nano_success():
    """no_gpt_fallback only matters on FAILURE — a successful nano draw
    returns normally whether the flag is set or not."""
    ic = FakeImageClient({"generate_with_reference": {"url": "https://img/nano.png"}})
    url, model = _run(generate_scene_image_for_model(
        ic, "nano-banana-2", "p", reference_urls=["ref1"], aspect_ratio="16:9",
        no_gpt_fallback=True))
    assert (url, model) == ("https://img/nano.png", "nano-banana-2")


def test_fail_info_out_reaches_nano_with_reference_path_on_failure():
    """C25a-fix-nano-sheets: fail_info_out now also threads through the nano
    path (generate_with_reference), not just the GPT one — the sheet ladder
    needs Kie's real failCode/creditsConsumed to classify a nano failure the
    same way it already classified GPT ones."""
    ic = FakeImageClient({
        "generate_with_reference": None,
        "generate_with_reference_fail_info": {
            "failCode": "500", "failMsg": "Internal Error, Please try again later.",
            "creditsConsumed": 0.0,
        },
    })
    box: list = []
    url, model = _run(generate_scene_image_for_model(
        ic, "nano-banana-2", "p", reference_urls=["ref1"], aspect_ratio="16:9",
        no_gpt_fallback=True, fail_info_out=box))
    assert (url, model) == (None, None)
    assert box == [{"failCode": "500", "failMsg": "Internal Error, Please try again later.",
                     "creditsConsumed": 0.0}]


def test_fail_info_out_reaches_nano_generate_and_wait_path_on_failure():
    ic = FakeImageClient({
        "generate_and_wait": None,
        "generate_and_wait_fail_info": {
            "failCode": "400", "failMsg": "image fetch failed.", "creditsConsumed": 0,
        },
    })
    box: list = []
    url, model = _run(generate_scene_image_for_model(
        ic, "nano-banana-2", "p", aspect_ratio="16:9", no_gpt_fallback=True, fail_info_out=box))
    assert (url, model) == (None, None)
    assert box == [{"failCode": "400", "failMsg": "image fetch failed.", "creditsConsumed": 0}]


# ---------------------------------------------------------------------------
# C25a-fix-gpt-reroll (2026-07-21): _gpt_default's refs branch (the real
# per-shot PICTURES path) now re-rolls GPT up to 2 FREE extra times when a
# failure is the deterministic, zero-cost content-filter rejection, before
# falling back to nano-banana-2 — mirrors the sheet ladder's own free-re-roll
# reasoning (OpenAI's filter is a coin flip near its threshold) without any
# sleep (single-image cadence). A REAL (credit-consuming) failure skips
# straight to nano on the first attempt, same immediacy as before this
# change (see test_fail_info_out_reaches_default_gpt_thumbnail_path_on_
# failure above for that case in the fail_info_out context).
# ---------------------------------------------------------------------------

_FILTER_400 = {
    "failCode": "400", "failMsg": "The current content could not be processed.",
    "creditsConsumed": 0.0,
}
_REAL_FAILURE = {"failCode": "500", "failMsg": "some real production error", "creditsConsumed": 1.0}


def test_gpt_reroll_twice_then_success_on_third_roll_never_calls_nano():
    ic = FakeImageClient({
        "generate_thumbnail_gpt2": [None, None, {"url": "https://img/gpt-roll3.png", "model": "gpt-image-2"}],
        "generate_thumbnail_gpt2_fail_info": [_FILTER_400, _FILTER_400],
    })
    url, model = _run(generate_scene_image_for_model(
        ic, None, "p", reference_urls=["ref1"], aspect_ratio="16:9"))
    assert (url, model) == ("https://img/gpt-roll3.png", "gpt-image-2")
    assert [c[0] for c in ic.calls] == ["generate_thumbnail_gpt2"] * 3
    assert "generate_with_reference" not in [c[0] for c in ic.calls]


def test_gpt_three_filter_rejections_falls_back_to_nano_exactly_once():
    ic = FakeImageClient({
        "generate_thumbnail_gpt2": [None, None, None],
        "generate_thumbnail_gpt2_fail_info": [_FILTER_400, _FILTER_400, _FILTER_400],
        "generate_with_reference": {"url": "https://img/nano-after-3.png"},
    })
    url, model = _run(generate_scene_image_for_model(
        ic, None, "p", reference_urls=["ref1"], aspect_ratio="16:9"))
    assert (url, model) == ("https://img/nano-after-3.png", "nano-banana-2")
    assert [c[0] for c in ic.calls] == (
        ["generate_thumbnail_gpt2"] * 3 + ["generate_with_reference"])


def test_credit_consuming_failure_falls_back_to_nano_immediately():
    """Today's behavior preserved: a REAL (credit-consuming) GPT failure
    never re-rolls — it falls back to nano on the very first attempt, exactly
    1 GPT call + 1 nano call, same immediacy the no-refs branch
    (generate_scene_image_gpt) already had."""
    ic = FakeImageClient({
        "generate_thumbnail_gpt2": None,
        "generate_thumbnail_gpt2_fail_info": _REAL_FAILURE,
        "generate_with_reference": {"url": "https://img/nano-immediate.png"},
    })
    url, model = _run(generate_scene_image_for_model(
        ic, None, "p", reference_urls=["ref1"], aspect_ratio="16:9"))
    assert (url, model) == ("https://img/nano-immediate.png", "nano-banana-2")
    assert [c[0] for c in ic.calls] == ["generate_thumbnail_gpt2", "generate_with_reference"]


def test_gpt_reroll_fail_info_out_accumulates_one_entry_per_attempt():
    """fail_info_out is append-only across every GPT attempt (same convention
    as task_id_out) — 2 failed re-rolls before the 3rd succeeds means 2
    entries land in the caller's box, not 0 and not 3."""
    ic = FakeImageClient({
        "generate_thumbnail_gpt2": [None, None, {"url": "https://img/ok.png", "model": "gpt-image-2"}],
        "generate_thumbnail_gpt2_fail_info": [_FILTER_400, _FILTER_400],
    })
    box: list = []
    _run(generate_scene_image_for_model(
        ic, None, "p", reference_urls=["ref1"], aspect_ratio="16:9", fail_info_out=box))
    assert box == [_FILTER_400, _FILTER_400]


def test_gpt_reroll_never_fires_for_no_refs_branch():
    """The re-roll is scoped to the refs branch only — generate_scene_image_gpt
    (no refs) already owns its own separate internal ladder and must stay
    completely untouched by this change."""
    ic = FakeImageClient({
        "generate_scene_image_gpt": {"url": "https://img/text-to-image.png", "model": "gpt-image-2"},
    })
    url, model = _run(generate_scene_image_for_model(ic, None, "p", aspect_ratio="16:9"))
    assert (url, model) == ("https://img/text-to-image.png", "gpt-image-2")
    assert [c[0] for c in ic.calls] == ["generate_scene_image_gpt"]
