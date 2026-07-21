"""Single source of truth for turning a video's `image_model_override`
("nano-banana-2" | "gpt-image-2" | "z-image" | None/"") into the ImageClient
call that actually draws the image — and for reporting back which model
ACTUALLY produced the pixels, so callers can persist the truth on the asset
row instead of assuming GPT (see storyengine-wiring-fix-checklist.md §0.1,
"the Pictures model select writes image_model_override, but the live path
ignores it").

Used by BOTH of the app's model-selecting call sites so there is exactly ONE
place that decides what an override means — no duplicated branching:
  - storyengine/backend/scripts/coverage_to_app.py
      (redo_characters, generate_storyboard_sheet_for_scene, redraw_asset_image)
  - storyengine/backend/pipeline_executor.py (PipelineExecutor.run_image_variants,
      the legacy Airtable-driven image-variant regen path)

Contract (Ryan's explicit rule): GPT Image 2 is ALWAYS the default (no
override, unrecognized override, or override == 'gpt-image-2') AND the
fallback when an EXPLICIT z-image / nano-banana-2 choice fails or comes back
empty. This mirrors ImageClient.generate_scene_image_gpt's own existing
GPT-then-nano content-policy ladder, which the default branch defers to
completely unchanged.

ONE deliberate exception (Ryan's ruling, 2026-07-21 — "previews move OFF the
filtered endpoint entirely"): storyboard SHEETS are cheap, throwaway 6-panel
composite previews judged by OpenAI's OUTPUT-STAGE moderation on the whole
composite at once — one borderline panel poisons the board, so cooking/
prop-heavy scenes ground through the retry ladder forever. Sheets now draw
UNCONDITIONALLY on nano-banana-2 (no OpenAI moderation stage at all),
ignoring the video's image_model_override entirely — that override still
governs only the real per-shot PICTURES path (run_coverage / redraw_asset_
image / run_image_variants), where GPT stays the default because it's
statistically safe there (single-frame judgment, small prompts). See
`no_gpt_fallback` below: sheet callers (coverage_to_app.py's _draw_board) also
pass `no_gpt_fallback=True` so a failed nano draw never silently reintroduces
the filtered endpoint this exception exists to avoid.
"""
from __future__ import annotations

from typing import Optional

from orchestrator.pipeline_constants import Models

# The 3 values the Pictures selector writes (ScenesWorkspaceTab.tsx L1121-1126).
VALID_IMAGE_MODELS = {"nano-banana-2", "gpt-image-2", Models.IMAGE_ZIMAGE}


def _urls(reference_urls) -> list:
    """Normalize a single URL / list / None into a clean list of truthy URLs."""
    if not reference_urls:
        return []
    if isinstance(reference_urls, (list, tuple)):
        return [r for r in reference_urls if r]
    return [reference_urls]


def _url_of(res) -> Optional[str]:
    if isinstance(res, dict):
        return res.get("url")
    return res or None


def _is_zero_cost_filter_reject(fail_info: Optional[dict]) -> bool:
    """True for Kie/OpenAI's deterministic, ZERO-COST content-filter
    rejection (failCode 400's "could not be processed" / "may violate ...
    content policies", or failCode 422's "flagged as sensitive"), with ~0
    credits consumed (None counts as 0 — the reject fires before real
    generation starts, so nothing is spent). Mirrors
    storyengine/backend/scripts/coverage_to_app.py's `_sheet_filter_reject`
    predicate EXACTLY (same two failCode classes, same message keywords,
    same 0-credit guard) — but reimplemented locally rather than imported,
    because this shared client must stay import-clean of backend code (see
    module docstring's call-site list: pipeline_executor.py and skills/
    video-pipeline callers have no backend on their path).

    Gates the free GPT re-roll below (C25a-fix-gpt-reroll, 2026-07-21): a
    rejection in this exact class costs nothing to retry, because OpenAI's
    image filter is non-deterministic near its threshold (the same coin-flip
    behavior the sheet ladder already exploits). A REAL (credit-consuming)
    failure must never re-roll here — that would burn money chasing a prompt
    that isn't the (free) coin-flip kind."""
    if not fail_info:
        return False
    code = str(fail_info.get("failCode") or "").strip()
    if code not in ("400", "422"):
        return False
    credits = fail_info.get("creditsConsumed")
    if credits not in (0, 0.0, None):
        return False
    msg = (fail_info.get("failMsg") or "").lower()
    return (
        ("could not be processed" in msg)
        or ("content polic" in msg)
        or ("violat" in msg)
        or ("flagged as sensitive" in msg)
        or ("sensitive" in msg)
    )


async def _gpt_default(image_client, prompt, refs, aspect_ratio, resolution, task_id_out=None,
                        fail_info_out=None, no_nano_fallback=False):
    """The default path: GPT Image 2 (image-to-image via generate_thumbnail_gpt2
    when refs exist, else generate_scene_image_gpt's own text-to-image +
    content-policy-aware nano-banana-2 fallback).

    REFS branch (C25a-fix-gpt-reroll, 2026-07-21 — "GPT stays for the real
    per-shot pictures... and already has an automatic nano fallback", Ryan's
    ruling): generate_thumbnail_gpt2 has no internal retry of its own, so
    this now re-rolls it here — up to 2 FREE extra attempts (3 total) when a
    failure is the deterministic, zero-cost content-filter rejection
    (_is_zero_cost_filter_reject) — before falling back to nano-banana-2 via
    generate_with_reference. A REAL (credit-consuming) failure skips the
    re-roll and falls back to nano on the FIRST attempt, same immediacy as
    generate_scene_image_gpt's own no-refs ladder below. This is SINGLE-IMAGE
    cadence (pictures, one call at a time) — no sleep between attempts, unlike
    the sheet ladder's paced re-rolls (coverage_to_app.py's _draw_board),
    which pause deliberately to decorrelate a flaky moderation coin flip
    across a much larger, slower composite draw.

    fail_info_out: threaded into EVERY refs-branch GPT attempt (append, don't
    assign — same convention as task_id_out) so a caller watching it sees one
    entry per attempt, same as task_id_out's append-only trace. Also threaded
    into the nano fallback call so a caller can see why nano failed too, if
    it comes to that.

    No-refs branch: unchanged — generate_scene_image_gpt already owns its own
    internal content-policy-aware nano fallback and is out of scope here.

    no_nano_fallback (Ryan's ruling 2026-07-21 evening, reversing the morning's
    nano-sheets ruling after seeing the results): when True, GPT exhaustion
    returns (None, None) instead of falling back to nano-banana-2 — nano's
    character consistency was ruled unacceptable ("none of them are consistent
    with their characters"), so a caller that would rather surface a clean
    failure (storyboard sheets and their error-chip + per-board redo UX) than
    accept a nano draw sets this. Refs branch only; the no-refs branch's
    internal fallback lives inside generate_scene_image_gpt and no sheet/
    picture caller reaches it without refs."""
    if refs:
        last_fail: Optional[dict] = None
        for attempt in range(3):
            probe: list = []
            res = await image_client.generate_thumbnail_gpt2(
                prompt, refs, aspect_ratio, resolution=resolution, task_id_out=task_id_out,
                fail_info_out=probe)
            url = _url_of(res)
            if url:
                return url, "gpt-image-2"
            last_fail = probe[-1] if probe else None
            if fail_info_out is not None and last_fail is not None:
                fail_info_out.append(last_fail)
            if attempt < 2 and _is_zero_cost_filter_reject(last_fail):
                print(f"      ⟳ GPT filter re-roll {attempt + 1}/2 (zero-cost content-filter "
                      "rejection, retrying free)…")
                continue
            break
        if no_nano_fallback:
            print("      ❌ GPT Image 2 exhausted — no nano fallback for this caller, "
                  "surfacing the failure.")
            return None, None
        print("      ↩️  GPT Image 2 exhausted — falling back to nano-banana-2…")
        res = await image_client.generate_with_reference(
            prompt, refs, aspect_ratio=aspect_ratio, resolution=resolution, task_id_out=task_id_out,
            fail_info_out=fail_info_out)
        url = _url_of(res)
        return (url, "nano-banana-2") if url else (None, None)
    res = await image_client.generate_scene_image_gpt(
        prompt, None, aspect_ratio, resolution=resolution, task_id_out=task_id_out)
    url = _url_of(res)
    if not url:
        return None, None
    # generate_scene_image_gpt may itself have silently fallen back to
    # nano-banana-2 on a content-policy block — trust its own report if present.
    model_used = res.get("model", "gpt-image-2") if isinstance(res, dict) else "gpt-image-2"
    return url, model_used


async def generate_scene_image_for_model(
    image_client,
    model_override: Optional[str],
    prompt: str,
    reference_urls=None,
    aspect_ratio: str = "16:9",
    resolution: str = "1K",
    task_id_out: Optional[list] = None,
    fail_info_out: Optional[list] = None,
    no_gpt_fallback: bool = False,
    no_nano_fallback: bool = False,
) -> tuple[Optional[str], Optional[str]]:
    # resolution defaults to "1K" (Ryan, 2026-07-21: "we dont need a 2k gpt
    # image... downgrade it to 1k so its cheaper"). The old "2K" default
    # silently made per-shot REDRAWS, character 4-view sheets, image
    # variants and storyboard sheets cost ~2x the batch pictures run, which
    # already drew at 1K explicitly. A caller that genuinely needs 2K (none
    # today — thumbnails call generate_thumbnail_gpt2 directly with their
    # own default) must now ask for it.
    """Draw ONE image honoring `model_override`. Returns (url, model_used) — the
    model actually reflected in `model_used` is what generated the pixels, which
    may differ from `model_override` when a fallback fired. Returns (None, None)
    if every attempt failed.

    - 'z-image': text-to-image only (Kie's z-image has no reference-image
      support, so cast/env reference urls are intentionally NOT sent to it —
      the caller's identity anchor is lost for this model, same as if the
      creator called it directly). Falls back to GPT Image 2 on failure.
    - 'nano-banana-2': reference-aware (generate_with_reference when refs are
      given, else the plain nano-banana-2 text-to-image call). Falls back to
      GPT Image 2 on failure — UNLESS `no_gpt_fallback` is set (see below).
    - None / '' / 'gpt-image-2' / any unrecognized value: the EXISTING default
      — see _gpt_default. Unchanged from pre-existing behavior.

    task_id_out: optional list the caller passes in to receive the Kie taskId
    of whichever attempt below succeeds (append, don't assign — same
    fresh-box-per-call pattern the clip path uses, see generate_video's
    docstring). Callers that write ONE generation_ledger row per ONE call to
    this function (redraw_asset_image, run_image_variants) can thread
    box[0] into record_ledger_entry's kie_task_id for real dedup protection
    (checklist C16c / migration 093). Batch callers that aggregate many
    images from many calls into a single ledger row should NOT pass this —
    a single task id can't honestly represent a batch (see migration 093's
    header for the full call-site audit).

    fail_info_out: optional list the caller passes in to receive Kie's raw
    failure detail dict ({"failCode", "failMsg", "creditsConsumed"}) when an
    attempt fails (append, don't assign — same convention as task_id_out, one
    entry per failed attempt). Populated by:
      - the GPT-with-refs path (generate_thumbnail_gpt2, via _gpt_default) —
        C25a-fix8 (2026-07-20), the original storyboard-sheet call shape.
      - the nano-banana-2 path (generate_with_reference / generate_and_wait)
        — C25a-fix-nano-sheets (2026-07-21), added when storyboard sheets
        moved OFF gpt-image-2 onto nano so their retry ladder (now built to
        catch nano's own Kie-infra failures — 500s, ref-fetch — rather than
        OpenAI's moderation, which nano doesn't have) keeps a real signature
        to classify instead of guessing from a bare None.

    no_gpt_fallback (C25a-fix-nano-sheets, 2026-07-21): when True AND `model`
    resolves to 'nano-banana-2', a failed nano attempt returns (None, None)
    directly instead of falling back to _gpt_default. Exists ONLY for
    storyboard sheets (coverage_to_app.py's _draw_board passes it on every
    sheet draw, always paired with the literal model "nano-banana-2") — the
    whole point of Ryan's 2026-07-21 ruling was moving sheet previews OFF
    GPT Image 2's OpenAI-filtered endpoint; without this flag, a nano failure
    would silently walk right back onto that exact endpoint via the fallback
    below. Every OTHER caller (PICTURES via an explicit nano-banana-2
    override) leaves this False and keeps the pre-existing GPT-fallback
    behavior — this is a caller-opt-in, not a change to the nano branch's
    default behavior, so the router stays the single source of truth without
    a second, divergent code path.

    no_nano_fallback (Ryan's ruling 2026-07-21 evening — sheets back on GPT,
    nano banned from them): when True AND the model resolves to the GPT
    default path, GPT exhaustion returns (None, None) instead of drawing on
    nano-banana-2. The mirror of no_gpt_fallback, one flag per fallback
    direction. Storyboard sheets pass it (their error-chip + per-board-redo
    UX prefers a clean failure over a nano draw with drifting characters);
    every other caller keeps the nano safety net (e.g. DvsU cast sheets,
    where GPT refuses kid characters and nano is the only path that lands).
    """
    refs = _urls(reference_urls)
    model = (model_override or "").strip()

    if model == Models.IMAGE_ZIMAGE:
        res = await image_client.generate_scene_image_zimage(
            prompt, aspect_ratio=aspect_ratio, task_id_out=task_id_out)
        url = _url_of(res)
        if url:
            return url, Models.IMAGE_ZIMAGE
        return await _gpt_default(image_client, prompt, refs, aspect_ratio, resolution, task_id_out,
                                   fail_info_out)

    if model == "nano-banana-2":
        if refs:
            res = await image_client.generate_with_reference(
                prompt, refs, aspect_ratio=aspect_ratio, task_id_out=task_id_out,
                fail_info_out=fail_info_out)
        else:
            urls = await image_client.generate_and_wait(
                prompt, aspect_ratio, model=image_client.SCENE_MODEL, task_id_out=task_id_out,
                fail_info_out=fail_info_out)
            res = {"url": urls[0]} if urls else None
        url = _url_of(res)
        if url:
            return url, "nano-banana-2"
        if no_gpt_fallback:
            return None, None
        return await _gpt_default(image_client, prompt, refs, aspect_ratio, resolution, task_id_out,
                                   fail_info_out)

    # default / 'gpt-image-2' / unrecognized override
    return await _gpt_default(image_client, prompt, refs, aspect_ratio, resolution, task_id_out,
                               fail_info_out, no_nano_fallback=no_nano_fallback)
