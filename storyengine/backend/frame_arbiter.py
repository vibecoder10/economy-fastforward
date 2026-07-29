"""Frame Arbiter judge call (D5 chunk A3, storyengine/FRAME-ARBITER-PLAN.md)
+ neighbor-frame continuity check (D5 chunk A4, folded into the same call —
the plan folds A4 into A3's judge call rather than a second pass).

Reuse base (as the plan directs): static_docu.py's ``_download_image_b64``
(self-fetch -> base64) is imported directly here, not re-implemented, so a
future fix to the download/size-limit path lands once for both callers.
Vision model is ``CLAUDE_MODELS["anthropic"]["smart"]`` (claude-sonnet-4-6
today) — the same single source every other Claude call site in this
backend reads from (static_docu.py, producer_prompt.py, etc. — see
shared/channel_profile.py's own docstring, C35).

Every paid call:
  1. Checked against A1's ``arbiter_budget_check`` BEFORE it fires — never
     audited after (DoC #3). A budget breach short-circuits before any
     download or network call.
  2. Metered as a frame_qa ``generation_ledger`` row (A1's
     ``record_frame_qa_entry``) for EVERY real vision call that actually
     fires, regardless of verdict — money spent is money spent, whether the
     frame turned out clean or not.
  3. Fails closed on any download/transport/parse failure: no finding is
     ever invented, an explicit ``skipped`` status is returned instead
     (mirrors static_docu._vision_confirms: an HTTP-level failure must
     never silently become a clean verdict, nor a fabricated defect).
  4. Only recorded via A2's ``record_finding`` when the verdict IS one of
     the three defect buckets (MODEL_DEFECT/AUTHORING_DEFECT/
     TASTE_QUESTION) — a clean "OK" verdict still costs money and still
     gets ledgered, but leaves no fingerprint row (there's nothing to
     remember it by).

Classification guidance the judge prompt itself states, verbatim from the
plan's chunk A3 spec: pixels disobeyed a CORRECT prompt -> MODEL_DEFECT
(the ONLY bucket that may ever reach ``redraw_shot`` — A5, not built here);
the prompt ITSELF authored the flaw -> AUTHORING_DEFECT; no rule covers it
or it's a directorial preference -> TASTE_QUESTION.

A4 (neighbor continuity) is not a second call — it's extra rubric lines in
the SAME vision request, with up to 2 neighbor frame images (previous/next
in draw order) attached alongside the frame under judgment, covering:
axis/screen-direction continuity against the scene's own [AXIS | ...]
contract (coverage.py's ``parse_axis_line`` format — read-only vocabulary
match, this module has ZERO runtime dependency on coverage.py and never
edits it, DoC #7); facing-law consistency across the set (rule 5g's
vocabulary: a close shot (MCU/CU/ECU), a speaking master, or a REACTION
angle needs the face legible to camera or an explicit look-back — see
coverage.py's ``_carries_facing_law``/``_FACE_TO_CAMERA_RE``/
``_LOOK_BACK_RE`` for the identical vocabulary this rubric borrows in
prose, never imports in code); duplicate-setup detection (two adjacent
near-identical compositions read as a dead cut even when their prompts
differ); and obvious style/palette drift versus the neighbor(s).

Pure library — no pipeline hook. A6 wires this behind a flag; nothing in
the product calls this module yet.
"""
from __future__ import annotations

import re
import sys
from pathlib import Path
from typing import Any, Awaitable, Callable, Optional

import httpx

from arbiter_fingerprints import CLASSIFICATIONS, fingerprint_key, record_finding
from database import fetch_all
from frame_arbiter_budget import FRAME_QA_STAGE, arbiter_budget_check, record_frame_qa_entry
from quality_rules import compose_rules_text, list_all_rules
from static_docu import _download_image_b64  # noqa: E402 - reuse, see module docstring

_PIPELINE_PATH = Path(__file__).resolve().parents[2] / "skills" / "video-pipeline"
if str(_PIPELINE_PATH) not in sys.path:
    sys.path.insert(0, str(_PIPELINE_PATH))

from shared.channel_profile import CLAUDE_MODELS  # noqa: E402

VISION_MODEL = CLAUDE_MODELS["anthropic"]["smart"]

# Published Anthropic per-token rates for claude-sonnet-4-6 ($/token) — the
# "smart" tier this judge call uses (see VISION_MODEL above). Sourced from
# Anthropic's own published pricing (checked live via the claude-api skill's
# rate table in the same session that wrote this file: $3.00 input / $15.00
# output per 1M tokens) — NOT a guess, and NOT the flat per-image estimates
# IMAGE_PRICE_BY_MODEL etc. carry for picture-generation stages, a different
# pricing model entirely. A vision JUDGMENT call is billed like any other
# Claude Messages API call: input + output tokens, read from the response's
# own usage block (usage_cost below), never estimated ahead of time.
_SONNET_INPUT_PRICE_PER_TOKEN = 3.00 / 1_000_000
_SONNET_OUTPUT_PRICE_PER_TOKEN = 15.00 / 1_000_000

# Pre-call quote handed to A1's arbiter_budget_check BEFORE the real call
# fires (the guard needs an honest number to check against; the REAL bill
# is read back from usage_cost() after the call and is what actually gets
# ledgered). Sized from the priced spike's measured actual cost (see the
# chunk report) with headroom — a single judge call has landed well under
# this in every live measurement so far.
DEFAULT_QUOTE = 0.02

# D5 chunk A3b pre-call quotes — replaces the disproven "N frames x
# DEFAULT_QUOTE" math (A3's live spike: $0.0196/frame x ~10 frames/scene =
# ~$0.18, which alone eats most of frame_arbiter_budget.FRAME_QA_SCENE_CAP's
# $0.25). One scene-batch call (all frames + prompts + set context in a
# single multimodal message) measures well under $0.07 in the A3b live
# evals (see the chunk report for the exact figure) — sized here with
# headroom over that measurement, same "honest pre-call quote, real cost
# read back from usage after" contract judge_frame already uses.
DEFAULT_SCENE_QUOTE = 0.07
# One storyboard-sheet image is a single grid picture, not N separate
# frames — cheaper input, and the reply is a handful of per-panel verdict
# blocks instead of up to ten. Sized from the same live-eval measurement
# (see chunk report) with headroom.
DEFAULT_BOARD_QUOTE = 0.03

# "OK" is deliberately NOT one of A2's three defect buckets
# (arbiter_fingerprints.CLASSIFICATIONS) — a clean frame still costs money
# and still gets metered on the ledger, but there is nothing to remember
# about it, so it never reaches record_finding. Kept as an explicit
# sentinel so callers can tell "judged, and it's fine" apart from "we
# could not judge this at all" (a skipped result).
NO_FINDING = "OK"

_ALL_VERDICTS = CLASSIFICATIONS | {NO_FINDING}


_JUDGE_SYSTEM = (
    "You are the Frame Arbiter, a strict but fair quality judge for an AI "
    "video pipeline's drawn storyboard frames. You look at ONE frame (plus "
    "up to two of its scene neighbors for continuity context only) and "
    "decide whether it needs a human's attention."
)


def usage_cost(usage: Optional[dict]) -> float:
    """Real dollar cost of one vision call, read straight off the API
    response's own usage block — never estimated, never the pre-call
    DEFAULT_QUOTE. Rounded the same way generation_ledger's other cost
    writers round (small, stable precision, not raw float noise)."""
    usage = usage or {}
    input_tokens = int(usage.get("input_tokens") or 0)
    output_tokens = int(usage.get("output_tokens") or 0)
    return round(
        input_tokens * _SONNET_INPUT_PRICE_PER_TOKEN
        + output_tokens * _SONNET_OUTPUT_PRICE_PER_TOKEN,
        6,
    )


def _rubric_prompt(frame: dict, neighbors: list, rules_text: str, axis_line: Optional[str]) -> str:
    """Assembles the judge's rubric text: (a) the frame's own stored
    image_prompt (prompt-obedience check), (b) the tenant's active
    quality_rules (empty when none configured — same as
    quality_rules.compose_rules_text's empty-list behavior), (c) A4's
    neighbor-continuity rubric lines. Pure text assembly, no I/O."""
    prompt = (frame.get("image_prompt") or "").strip()
    shot_type = frame.get("shot_type") or "?"
    image_index = frame.get("image_index")
    lines = [
        f"FRAME UNDER JUDGMENT: image_index={image_index}, shot_type={shot_type}.",
        "The FIRST image attached is this frame. Any additional attached "
        "images are its immediate scene neighbors (previous/next frame in "
        "draw order), for continuity comparison ONLY — never judge a "
        "neighbor on its own merits, only in relation to the first image.",
        "",
        "ITS OWN STORED IMAGE PROMPT (what the model was asked to draw):",
        prompt or "(no prompt on file)",
    ]
    if axis_line:
        lines += ["", f"SCENE AXIS CONTRACT (rule 5d): {axis_line}"]
    if rules_text:
        lines += ["", "ACTIVE QUALITY RULES for this tenant:", rules_text]
    lines += [
        "",
        "JUDGE THIS FRAME against THREE things:",
        "1. PROMPT OBEDIENCE — does the picture actually match its own "
        "prompt above: facing/eyeline direction, framing size (WS/MS/MCU/"
        "CU/ECU), which subject(s) appear, and the set dressing described? "
        "A close shot (MCU/CU/ECU), a speaking master, or a shot whose "
        "prompt reads an emotion off the face must show the face legible "
        "to camera (three-quarter or face-to-camera) OR an explicit "
        "look-back — eyeline alone (\"looking frame-left/right\") with the "
        "face simply turned away is a FACING LAW violation unless the "
        "shot is explicitly tagged an INSERT (a no-faces detail shot).",
        "2. ACTIVE QUALITY RULES — does the frame violate any rule listed "
        "above (empty section above means no tenant-specific rules apply).",
        "3. NEIGHBOR CONTINUITY (compare against the attached neighbor "
        "image(s), if any) — screen-direction/axis continuity per the "
        "axis contract above; facing-law consistency across the set; "
        "DUPLICATE-SETUP: does this frame read as the SAME composition "
        "(same framing, same pose, same background) as an adjacent "
        "neighbor despite the two prompts describing different shots or "
        "beats — a dead cut; and any obvious style/palette drift versus "
        "the neighbor(s).",
        "",
        "CLASSIFY exactly one of these four, using this law:",
        "- MODEL_DEFECT: the prompt above is CORRECT/reasonable, but the "
        "pixels disobeyed it (wrong facing, wrong framing, missing/extra "
        "subject, drifted set/style, or an unintended duplicate of a "
        "neighbor's composition).",
        "- AUTHORING_DEFECT: the pixels actually match what the PROMPT "
        "asked for, but the prompt itself authored the flaw (e.g. it "
        "never asked for a face-to-camera cue on a close emotional shot, "
        "or two neighboring prompts genuinely describe near-identical "
        "framing).",
        "- TASTE_QUESTION: something reads off but no rule above covers "
        "it and it's a directorial preference call, not a clear defect.",
        "- OK: no defect worth a human's attention.",
        "",
        "Reply in EXACTLY this format, one field per line, nothing else:",
        "CLASSIFICATION: <MODEL_DEFECT|AUTHORING_DEFECT|TASTE_QUESTION|OK>",
        "FAILURE_CLASS: <short_snake_case_tag, or NONE if CLASSIFICATION is OK>",
        "RULE_ID: <a quality-rule id from the list above if one applies, else NONE>",
        "RUBRIC_LEVEL: <hard_gate|warn|guidance>",
        "DECISIVE_FRAGMENT: <the exact phrase from the prompt or rule this "
        "verdict turns on, or NONE>",
        "DESCRIPTION: <one or two plain sentences a human reviewer can act on>",
    ]
    return "\n".join(lines)


_VERDICT_FIELD_RE = re.compile(
    r"^(CLASSIFICATION|FAILURE_CLASS|RULE_ID|RUBRIC_LEVEL|DECISIVE_FRAGMENT|DESCRIPTION|NEW_VS_PREVIOUS):\s*(.*)$",
    re.IGNORECASE,
)
_SNAKE_RE = re.compile(r"[^a-z0-9]+")


def _normalize_failure_class(raw: str) -> str:
    return _SNAKE_RE.sub("_", (raw or "").strip().lower()).strip("_") or "unspecified"


def _none_or(v: Optional[str]) -> Optional[str]:
    v = (v or "").strip()
    return None if not v or v.upper() == "NONE" else v


def parse_verdict(text: str) -> Optional[dict]:
    """Deterministic field parser for the judge's structured reply. Returns
    None (fail closed — the caller treats this as a skipped/unparseable
    result, never a fabricated verdict) when CLASSIFICATION is missing or
    not one of the four recognized values. Exposed (not underscored) so
    unit tests can exercise the parser directly against crafted reply
    text, without a network call.

    ``NEW_VS_PREVIOUS`` (D5 chunk A3b) is OPTIONAL — judge_frame's own
    single-frame prompt never asks for it, only the scene-batch/board
    rubrics do (see their own reply-format instructions). Forcing this
    into the OUTPUT SCHEMA, not just a soft "compare adjacent frames"
    instruction, is what actually made the model do the comparison work:
    a live eval run where the rubric only ASKED for adjacent-pair
    reasoning (never requiring it as a written field) missed the 101/102
    duplicate pose entirely — see the chunk report."""
    fields: dict[str, str] = {}
    for line in (text or "").splitlines():
        m = _VERDICT_FIELD_RE.match(line.strip())
        if m:
            fields[m.group(1).upper()] = m.group(2).strip()
    classification = (fields.get("CLASSIFICATION") or "").strip().upper()
    if classification not in _ALL_VERDICTS:
        return None
    return {
        "classification": classification,
        "failure_class": _normalize_failure_class(fields.get("FAILURE_CLASS") or classification),
        "rule_id": _none_or(fields.get("RULE_ID")),
        "rubric_level": (fields.get("RUBRIC_LEVEL") or "guidance").strip().lower(),
        "decisive_prompt_fragment": _none_or(fields.get("DECISIVE_FRAGMENT")),
        "description": (fields.get("DESCRIPTION") or "").strip(),
        "new_vs_previous": _none_or(fields.get("NEW_VS_PREVIOUS")),
    }


def _split_labeled_blocks(text: str, marker: str) -> dict[str, str]:
    """Splits a multi-verdict reply (one ``===MARKER <key>===`` header per
    item, e.g. ``===FRAME 108===`` or ``===PANEL 3===``) into
    ``{key: block_body}``. Pure text, no I/O — shared by
    ``judge_scene_batch`` (marker="FRAME") and ``judge_board_sheet``
    (marker="PANEL") so the field-level parsing underneath both reuses the
    exact same ``parse_verdict`` this module already has tests for, instead
    of a second parser copy that could drift.

    Returns {} for text with NO recognized markers at all (empty reply, a
    refusal, garbage) — the caller must then treat every item as
    unparseable/skipped, never invent a verdict. This is the fail-closed
    guarantee the eval harness's scorer depends on: a judge call that
    returns nothing scores 0 known-defects-found, not an accidental pass."""
    pattern = re.compile(rf"===\s*{re.escape(marker)}\s+([^=\n]+?)\s*===", re.IGNORECASE)
    matches = list(pattern.finditer(text or ""))
    blocks: dict[str, str] = {}
    for i, m in enumerate(matches):
        key = m.group(1).strip()
        start = m.end()
        end = matches[i + 1].start() if i + 1 < len(matches) else len(text or "")
        blocks[key] = (text or "")[start:end].strip()
    return blocks


# Named failure-class vocabulary (D5 chunk A3b, "tune the rubric prompt").
# A3's live test cleanly named only 1 of 3 known defects and missed the
# 101/102 duplicate-pose entirely — the working theory (see the chunk
# report) is that a per-frame call with no scene-wide context has nothing
# to compare against, and an unnamed rubric leaves "what counts as a
# defect" underspecified. Each entry below is deliberately a (tag,
# definition, one CONCRETE example) triple, not just a tag list — reused
# verbatim in both the scene-batch and board rubrics so the judge sees the
# identical vocabulary at both stations.
_FAILURE_CLASS_VOCAB = """\
NAMED FAILURE CLASSES (use these snake_case tags in FAILURE_CLASS when they apply; use a different short tag only when none of these genuinely fit):
- facing_law_violation: EITHER (a) a close shot (MCU/CU/ECU), a speaking master, or a shot whose prompt reads an emotion off the face shows the face turned away from camera with no explicit look-back cue and no INSERT tag, OR (b) the prompt states a specific gaze/screen-direction word (e.g. "looking frame-right", "looking frame-left", "staring upward") and the drawn eyeline/gaze clearly points a DIFFERENT direction — this counts even when the face is otherwise visible to camera; a visible face pointed the wrong way is still a facing violation, not a pass. Example: the prompt says "looking frame-right" but the drawn gaze points down-left or straight at camera instead.
- duplicate_setup: two frames/panels in this batch — not necessarily adjacent — read as the SAME composition (same framing, same pose, same background, same beat) despite different prompts or captions describing different shots. Example: three consecutive frames are all captioned as different beats (a sleepy unmoving stare, a tight eyes-only close-up, a standing whisper) but all three are actually drawn as the identical "palm pressed flat to glass, looking up and out" pose and framing — the 2nd and 3rd add nothing new over the 1st.
- rogue_figure: a second character or figure appears ANYWHERE in the image — including a small, partial, background, reflected, or through-a-window/doorway figure — that the frame's own stored prompt never asked for, at a beat whose prompt describes only one character. Example: a background pod/room visible through a window shows a clearly-rendered person standing or posed inside it, even though the scene's only established character is elsewhere in the frame. Scan backgrounds/reflections/windows deliberately, don't just look at the main subject — but ONLY flag a figure you can actually see: a body, a face, or an unambiguous humanoid silhouette. Do NOT flag an empty room, pod, or window as containing a figure — furniture, shadows, reflections, and lighting patterns are not people; if you are not confident it is a rendered person, it is not a finding. An empty background room is the expected default, not evidence of a removed figure.
- set_bleed: the drawn background/environment does not match the set the spec assigns to this frame/panel — objects or architecture from a DIFFERENT named location appear instead. Example: a shot spec'd for a small glass pod interior is drawn inside a large ornate theater with rows of chairs.
- staging_drift: two panels that a BOARD SHEET's own spec explicitly marks as the SAME camera setup (same setup letter/label, "copy the framing exactly") do not actually match each other's framing, distance, or body position. This class is for BOARD SHEETS specifically (where the spec states the repeat-setup law in writing) — for individual scene frames with no such explicit "repeat this setup" instruction, do not use staging_drift for an interpretive difference in pose/expression/exact camera height; that is not a finding at all unless it contradicts a concrete, stated fact (see the calibration line below).\
"""

_CALIBRATION_LINE = (
    "CALIBRATION AGAINST FALSE POSITIVES: only flag what you can name "
    "specifically by pointing at a concrete visual detail — an object, a "
    "body part, a background element, a stated direction/count/location — "
    "that contradicts the prompt/spec or a sibling frame/panel. Generic "
    "consistency unease, a vague sense that \"something feels off\", or a "
    "bare preference about mood/palette with no concrete named object is "
    "NOT a finding — mark that frame/panel OK. Also do NOT flag a frame for "
    "reading a mood/intensity ADJECTIVE slightly differently than you would "
    "have imagined it (e.g. \"eyes just opening\" drawn as more or less "
    "sleepy than you expected) — that is an interpretation call, not a "
    "defect, UNLESS it contradicts a concrete stated fact (which subject "
    "appears, which direction they face, what framing size, what object is "
    "in the set)."
)


async def _call_vision(
    tenant_id: str,
    content: list,
    *,
    max_tokens: int = 400,
    system: str = _JUDGE_SYSTEM,
) -> Optional[dict]:
    """One vision round-trip. Returns the parsed response JSON body, or
    None on ANY failure (no key configured, transport error, non-200) —
    fail closed, same bucket static_docu._vision_confirms uses for a
    failed attempt. Never raises. DIRECT Anthropic first (the Kie gateway
    injects tool configuration that derails vision replies into meta-talk
    about tools — same reasoning as static_docu._vision_confirms), Kie's
    Claude gateway as the fallback when no direct key is configured.

    ``max_tokens``/``system`` are overridable (D5 chunk A3b) — a
    scene-batch call replies with one verdict block per frame (needs more
    room than a single-frame 400-token reply) and the board station uses
    its own system preamble; both still go through this one call site so
    the fail-closed/fallback contract above only has to be written once."""
    from vault import get_secret

    akey = await get_secret("anthropic_api_key", tenant_id)
    try:
        async with httpx.AsyncClient(timeout=90.0) as c:
            if akey:
                r = await c.post(
                    "https://api.anthropic.com/v1/messages",
                    headers={
                        "x-api-key": akey,
                        "anthropic-version": "2023-06-01",
                        "Content-Type": "application/json",
                    },
                    json={
                        "model": VISION_MODEL,
                        "max_tokens": max_tokens,
                        "system": system,
                        "messages": [{"role": "user", "content": content}],
                    },
                )
            else:
                key = await get_secret("kie_ai_api_key", tenant_id)
                if not key:
                    return None  # keyless — caller treats as skipped, no finding invented
                import os

                kie_claude_url = os.getenv(
                    "KIE_CLAUDE_BASE_URL", "https://api.kie.ai/claude"
                ).rstrip("/") + "/v1/messages"
                r = await c.post(
                    kie_claude_url,
                    headers={"Authorization": f"Bearer {key}", "Content-Type": "application/json"},
                    json={
                        "model": CLAUDE_MODELS["kie"]["smart"],
                        "max_tokens": max_tokens,
                        "system": system,
                        "messages": [{"role": "user", "content": content}],
                    },
                )
    except Exception:  # noqa: BLE001 — transport failure: fail closed, never raise
        return None
    if r.status_code != 200:
        return None
    try:
        return r.json()
    except Exception:  # noqa: BLE001
        return None


async def judge_frame(
    tenant_id: str,
    video_id: str,
    scene: Optional[int],
    frame: dict,
    neighbors: Optional[list] = None,
    *,
    rules_text: str = "",
    axis_line: Optional[str] = None,
    budget_check: Callable[..., Awaitable] = arbiter_budget_check,
    ledger_write: Optional[Callable[..., Awaitable]] = None,
    record_finding_fn: Callable[..., Awaitable] = record_finding,
    projected_cost: float = DEFAULT_QUOTE,
) -> dict:
    """One vision judgment on one frame — budget-gated, ledger-metered,
    fingerprint-recorded. See the module docstring for the full contract.

    ``ledger_write`` defaults to A1's ``record_frame_qa_entry`` but is a
    passed-in callable/flag (per the chunk spec) so tests never touch a
    real DB — same dependency-injection convention A1/A2's own test suites
    use for their DB boundary (monkeypatch the module-level name, or here,
    pass a fake directly).

    Returns a dict. Skipped shape: ``{"skipped": True, "reason": ...,
    "image_index": ...}``. Judged shape: ``{"skipped": False,
    "image_index", "shot_type", "neighbor_indices", "classification",
    "failure_class", "rule_id", "rubric_level", "decisive_prompt_fragment",
    "description", "cost", "usage"}`` plus ``"fingerprint_record"`` when
    the verdict was a real defect (not OK)."""
    image_index = frame.get("image_index")

    # 1. Budget check FIRST — before any download or network call fires.
    breach = await budget_check(tenant_id, video_id, scene, projected_cost)
    if breach:
        return {"skipped": True, "reason": "budget", "breach": breach, "image_index": image_index}

    # 2. Self-fetch the frame's own image (static_docu's reused pattern).
    img = await _download_image_b64(frame.get("image_url"))
    if img is None:
        return {"skipped": True, "reason": "download_failed", "image_index": image_index}
    media_type, b64_data = img
    content: list = [
        {"type": "image", "source": {"type": "base64", "media_type": media_type, "data": b64_data}},
    ]

    # 3. A4: attach up to 2 neighbor images (best-effort — a neighbor that
    #    fails to download is simply omitted, never fails the whole call).
    neighbor_indices: list = []
    for n in (neighbors or [])[:2]:
        nimg = await _download_image_b64((n or {}).get("image_url"))
        if nimg is not None:
            n_media, n_b64 = nimg
            content.append({"type": "image", "source": {"type": "base64", "media_type": n_media, "data": n_b64}})
            neighbor_indices.append((n or {}).get("image_index"))

    content.append({"type": "text", "text": _rubric_prompt(frame, neighbors or [], rules_text, axis_line)})

    body = await _call_vision(tenant_id, content)
    if body is None:
        return {"skipped": True, "reason": "vision_error", "image_index": image_index}

    text = " ".join(
        b.get("text", "") for b in (body.get("content") or []) if b.get("type") == "text"
    ).strip()
    parsed = parse_verdict(text)
    if parsed is None:
        return {"skipped": True, "reason": "unparseable_reply", "image_index": image_index, "raw": text[:500]}

    usage = body.get("usage") or {}
    cost = usage_cost(usage)
    writer = ledger_write or record_frame_qa_entry
    is_finding = parsed["classification"] != NO_FINDING
    fp_key = fingerprint_key(parsed["rule_id"], parsed["failure_class"]) if is_finding else None
    await writer(
        tenant_id=tenant_id, video_id=video_id, scene=scene, model=VISION_MODEL,
        units=1, unit_cost=cost, actual_cost=cost, fingerprint=fp_key,
    )

    finding = {
        "skipped": False,
        "image_index": image_index,
        "shot_type": frame.get("shot_type"),
        "neighbor_indices": neighbor_indices,
        "classification": parsed["classification"],
        "failure_class": parsed["failure_class"],
        "rule_id": parsed["rule_id"],
        "rubric_level": parsed["rubric_level"],
        "decisive_prompt_fragment": parsed["decisive_prompt_fragment"],
        "description": parsed["description"],
        "cost": cost,
        "usage": usage,
    }
    if is_finding:
        # Only MODEL_DEFECT/AUTHORING_DEFECT/TASTE_QUESTION ever reach
        # record_finding — an "OK" verdict has nothing to remember (A2's
        # own pre-flight rejects any classification outside its three
        # buckets, so this call can never smuggle NO_FINDING through).
        record = await record_finding_fn(
            tenant_id, rule_id=parsed["rule_id"], stage=FRAME_QA_STAGE,
            failure_class=parsed["failure_class"], classification=parsed["classification"],
        )
        finding["fingerprint_record"] = record
    return finding


async def _fetch_scene_frames(tenant_id: str, video_id: str, scene: int) -> list[dict]:
    """Real drawn frames for one (video_id, scene) — the coverage/
    storyboard pipeline's rows in ``assets`` (confirmed against real call
    sites: routes/chat.py, routes/videos.py). Never the static_docu 3-image
    path — that writes rows too, but coverage_to_app.store_scene's rows are
    the shape THIS module judges; both live in the same table, distinguished
    by ``generation_method``, not queried here since coverage rows are what
    a (video_id, scene) lookup with ``status='done'`` naturally returns for
    a coverage-shaped video."""
    return await fetch_all(
        "SELECT image_index, shot_type, image_prompt, image_url FROM assets "
        "WHERE tenant_id = $1 AND video_id = $2 AND scene = $3 "
        "AND status = 'done' AND image_url IS NOT NULL "
        "ORDER BY image_index",
        tenant_id, video_id, scene,
    )


def _scene_frame_header(order: int, frame: dict) -> str:
    return f"IMAGE {order}: image_index={frame.get('image_index')}, shot_type={frame.get('shot_type') or '?'}."


def _scene_rubric_prompt(frames: list[dict], rules_text: str, axis_line: Optional[str]) -> str:
    """Assembles the ONE rubric text block for a whole-scene batch call
    (D5 chunk A3b — replaces per-frame judge_frame calls, see the module
    docstring's cost note). The frame images themselves are NOT embedded
    here — each is its own content block, preceded by its own
    ``_scene_frame_header`` label, so the model can point at "IMAGE 3" and
    the parser can map that straight back to a real image_index.

    Folds in A4's neighbor-continuity concept but widens it: instead of
    only comparing a frame to its immediate draw-order neighbor (the shape
    that let 101/102's duplicate pose slip past A3's live test — 101's own
    neighbor pair was 100/102, and the duplicate was between 101 and 103,
    two frames apart), every frame here sees every OTHER frame's own
    header. The adjacent-pair instruction below is still the disciplined
    per-pair reasoning step (per the chunk spec) but is explicitly not the
    only distance the model may compare across."""
    lines = [
        f"{len(frames)} FRAMES from the SAME scene were attached above, each "
        "preceded by its own IMAGE n / image_index label, in draw order. "
        "Judge them together, as one continuous scene, not as N unrelated "
        "pictures.",
        "",
        "EACH FRAME'S OWN STORED PROMPT (what the model was asked to draw), in the same IMAGE n order:",
    ]
    for i, f in enumerate(frames, 1):
        prompt = (f.get("image_prompt") or "").strip() or "(no prompt on file)"
        lines.append(f"{_scene_frame_header(i, f)} STORED PROMPT: {prompt}")
    if axis_line:
        lines += ["", f"SCENE AXIS CONTRACT (rule 5d): {axis_line}"]
    if rules_text:
        lines += ["", "ACTIVE QUALITY RULES for this tenant:", rules_text]
    lines += [
        "",
        "JUDGE EACH FRAME against THREE things:",
        "1. PROMPT OBEDIENCE — does the picture actually match its own "
        "prompt above: facing/eyeline direction, framing size (WS/MS/MCU/"
        "CU/ECU), which subject(s) appear, and the set dressing described? "
        "A close shot (MCU/CU/ECU), a speaking master, or a shot whose "
        "prompt reads an emotion off the face must show the face legible "
        "to camera (three-quarter or face-to-camera) OR an explicit "
        "look-back — eyeline alone (\"looking frame-left/right\") with the "
        "face simply turned away is a FACING LAW violation unless the "
        "shot is explicitly tagged an INSERT (a no-faces detail shot).",
        "2. ACTIVE QUALITY RULES — does the frame violate any rule listed "
        "above (empty section above means no tenant-specific rules apply).",
        "3. ADJACENT-PAIR COMPARISON (mandatory, do this for every "
        "consecutive pair IMAGE 1<->2, 2<->3, ... in your own reasoning "
        "before you answer): for each pair, name what NEW information the "
        "SECOND frame adds over the first — a new angle, a new action, a "
        "new set detail, a new emotional beat. If you cannot name anything "
        "new, the second frame of that pair is a near-identical repeat of "
        "the first — flag the LATER frame as a duplicate-setup defect on "
        "the classifying-frame's own verdict block, even when the two "
        "frames are not literally adjacent in the scene and even when "
        "their stored prompts describe different shots. Also check every "
        "OTHER frame in the batch, not only immediate neighbors, for the "
        "same near-identical-composition problem — screen-direction/axis "
        "continuity per the axis contract above and facing-law consistency "
        "across the set apply scene-wide too, and any obvious style/"
        "palette drift versus the rest of the batch.",
        "",
        _FAILURE_CLASS_VOCAB,
        "",
        _CALIBRATION_LINE,
        "",
        "CLASSIFY exactly one of these four PER FRAME, using this law:",
        "- MODEL_DEFECT: the prompt above is CORRECT/reasonable, but the "
        "pixels disobeyed it (wrong facing, wrong framing, missing/extra "
        "subject, drifted set/style, or an unintended duplicate of "
        "another frame's composition).",
        "- AUTHORING_DEFECT: the pixels actually match what the PROMPT "
        "asked for, but the prompt itself authored the flaw (e.g. it "
        "never asked for a face-to-camera cue on a close emotional shot, "
        "or two prompts in this batch genuinely describe near-identical "
        "framing on purpose).",
        "- TASTE_QUESTION: something reads off but no rule above covers "
        "it and it's a directorial preference call, not a clear defect.",
        "- OK: no defect worth a human's attention.",
        "PRIORITY when a frame is BOTH a duplicate of another frame's "
        "composition AND arguably disobeys its own prompt in some other "
        "way (wrong framing size, gaze direction, etc.): if this frame's "
        "actual drawn content matches ANOTHER frame in the batch better "
        "than it matches its OWN stored prompt, that is the MORE SPECIFIC "
        "and more useful diagnosis — classify it duplicate_setup, not a "
        "narrower framing/facing complaint, even if that narrower "
        "complaint is also technically true.",
        "",
        f"Reply with EXACTLY {len(frames)} blocks, one per frame, in IMAGE "
        "1..N order, each block in this exact format and nothing else "
        "outside the blocks. NEW_VS_PREVIOUS is REQUIRED and is not "
        "optional commentary — it is where you do the adjacent-pair "
        "comparison work instruction 3 above asked for, in writing, before "
        "you commit to a classification for this frame; do not skip it or "
        "leave it generic:",
        "===FRAME <image_index>===",
        "NEW_VS_PREVIOUS: <for IMAGE 1, write FIRST_FRAME. For every other "
        "frame, name the SPECIFIC new visual information this frame adds "
        "over the immediately preceding frame in the batch — a new angle, "
        "action, set detail, or beat. If you cannot name anything "
        "concretely new, write exactly: DUPLICATE OF IMAGE <n> — and that "
        "MUST drive this frame's classification below.>",
        "CLASSIFICATION: <MODEL_DEFECT|AUTHORING_DEFECT|TASTE_QUESTION|OK>",
        "FAILURE_CLASS: <short_snake_case_tag, or NONE if CLASSIFICATION is OK>",
        "RULE_ID: <a quality-rule id from the list above if one applies, else NONE>",
        "RUBRIC_LEVEL: <hard_gate|warn|guidance>",
        "DECISIVE_FRAGMENT: <the exact phrase from the prompt this verdict turns on, or NONE>",
        "DESCRIPTION: <one or two plain sentences naming the actual concrete defect a human reviewer can act on — never vague>",
    ]
    return "\n".join(lines)


def parse_scene_verdicts(text: str, frames: list[dict]) -> dict[Any, Optional[dict]]:
    """Maps the scene-batch reply's ``===FRAME <image_index>===`` blocks
    back onto each frame's real ``image_index``, running each block's body
    through the SAME ``parse_verdict`` field parser judge_frame already
    uses (never a second, possibly-drifted parser). A frame whose
    image_index has no matching block, or whose block doesn't parse to a
    recognized classification, maps to None — the caller treats that as
    skipped/unparseable for that one frame, never an invented verdict.
    Exposed (not underscored) so the eval harness/tests can exercise this
    directly against crafted reply text."""
    blocks = _split_labeled_blocks(text, "FRAME")
    result: dict[Any, Optional[dict]] = {}
    for f in frames:
        idx = f.get("image_index")
        body = blocks.get(str(idx))
        result[idx] = parse_verdict(body) if body else None
    return result


async def judge_scene_batch(
    tenant_id: str,
    video_id: str,
    scene: int,
    *,
    fetch_frames: Callable[..., Awaitable[list]] = _fetch_scene_frames,
    axis_line: Optional[str] = None,
    budget_check: Callable[..., Awaitable] = arbiter_budget_check,
    ledger_write: Optional[Callable[..., Awaitable]] = None,
    record_finding_fn: Callable[..., Awaitable] = record_finding,
    download_image: Optional[Callable[..., Awaitable]] = None,
    call_vision: Optional[Callable[..., Awaitable]] = None,
    projected_cost: float = DEFAULT_SCENE_QUOTE,
) -> dict:
    """D5 chunk A3b redesign: ONE vision call judges every frame in the
    scene together (prompts + set/axis context + every frame image, in a
    single multimodal message) instead of A3's one-call-per-frame loop —
    both because the per-frame cost alone ate the $0.25/scene cap (see
    module docstring) and because full-scene context is what actually lets
    the judge compare a frame against every OTHER frame in the batch, not
    just its immediate draw-order neighbor (the shape that missed the
    101/102 duplicate in A3's live test).

    ``download_image``/``call_vision`` are DI seams (default to the real
    ``_download_image_b64``/``_call_vision``) so tests and the eval harness
    never touch the network — same convention judge_frame's own
    budget_check/ledger_write/record_finding_fn params already use.

    Returns ``{"skipped": True, "reason": ..., "findings": [...]}`` on any
    fail-closed path (no frames, budget breach, every download failed,
    vision transport error) — ``findings`` is still populated with one
    skipped dict per known frame so a caller iterating findings never has
    to special-case the top-level skip. On success: ``{"skipped": False,
    "cost", "usage", "findings": [...]}`` where each finding dict has the
    same shape ``judge_frame`` returns (skipped-or-judged, classification/
    failure_class/rule_id/rubric_level/decisive_prompt_fragment/
    description, plus fingerprint_record when it's a real defect) so any
    existing caller of judge_frame's finding shape reads this one for
    free."""
    frames = await fetch_frames(tenant_id, video_id, scene)
    if not frames:
        return {"skipped": True, "reason": "no_frames", "findings": []}

    breach = await budget_check(tenant_id, video_id, scene, projected_cost)
    if breach:
        return {
            "skipped": True, "reason": "budget", "breach": breach,
            "findings": [{"skipped": True, "reason": "budget", "image_index": f.get("image_index")} for f in frames],
        }

    rules = await list_all_rules(tenant_id, active_only=True)
    rules_text, _ = compose_rules_text(rules or [])

    downloader = download_image or _download_image_b64
    content: list = []
    included: list[dict] = []
    for f in frames:
        img = await downloader(f.get("image_url"))
        if img is None:
            continue  # best-effort — a frame that fails to download is simply omitted from the batch, never fatal to the whole call
        media_type, b64 = img
        included.append(f)
        content.append({"type": "text", "text": _scene_frame_header(len(included), f)})
        content.append({"type": "image", "source": {"type": "base64", "media_type": media_type, "data": b64}})

    if not included:
        return {
            "skipped": True, "reason": "download_failed",
            "findings": [{"skipped": True, "reason": "download_failed", "image_index": f.get("image_index")} for f in frames],
        }

    content.append({"type": "text", "text": _scene_rubric_prompt(included, rules_text, axis_line)})

    vision_caller = call_vision or _call_vision
    # ~230 tokens/verdict block (raised from 130 in the first live A3b eval
    # run, see the chunk report: the REQUIRED NEW_VS_PREVIOUS field plus
    # the DESCRIPTION field's real observed length blew straight through
    # the old 130/frame estimate — a 10-frame batch hit the ceiling
    # mid-block on frame 10, and the LAST frame's own verdict came back
    # truncated/unparseable. A judge response that gets cut off is
    # functionally the same failure as an empty reply (fails closed,
    # never invents a partial verdict) but it is a preventable, wasted
    # failure — this budget is sized with real headroom over the measured
    # per-frame length instead of a guess.
    max_tokens = max(600, min(4000, 230 * len(included) + 500))
    body = await vision_caller(tenant_id, content, max_tokens=max_tokens)
    if body is None:
        return {
            "skipped": True, "reason": "vision_error",
            "findings": [{"skipped": True, "reason": "vision_error", "image_index": f.get("image_index")} for f in frames],
        }

    text = " ".join(
        b.get("text", "") for b in (body.get("content") or []) if b.get("type") == "text"
    ).strip()
    usage = body.get("usage") or {}
    cost = usage_cost(usage)
    writer = ledger_write or record_frame_qa_entry
    # ONE ledger row for the whole call — money spent on the call is real
    # regardless of how many (if any) of the N frames turned out to have a
    # finding, same "meter every real call, verdict or not" law judge_frame
    # uses. Multiple frames in one call can carry DIFFERENT fingerprints,
    # so (unlike judge_frame's single-frame row) this row's own
    # ``fingerprint`` column is left None — each real per-frame defect
    # still reaches record_finding_fn below with its own fingerprint; only
    # the ledger row's optional traceability tag is call-level here, not
    # per-defect. A5/A6 can split this into per-fingerprint rows later if
    # the ledger-grouped spend-trend view (FRAME-ARBITER-PLAN.md's success
    # metric) needs it; not required for this chunk's gate.
    await writer(
        tenant_id=tenant_id, video_id=video_id, scene=scene, model=VISION_MODEL,
        units=1, unit_cost=cost, actual_cost=cost, fingerprint=None,
    )

    verdicts = parse_scene_verdicts(text, included)
    included_indices = {f.get("image_index") for f in included}

    findings = []
    for f in frames:
        idx = f.get("image_index")
        if idx not in included_indices:
            findings.append({"skipped": True, "reason": "download_failed", "image_index": idx})
            continue
        parsed = verdicts.get(idx)
        if parsed is None:
            findings.append({"skipped": True, "reason": "unparseable_reply", "image_index": idx})
            continue
        is_finding = parsed["classification"] != NO_FINDING
        finding = {
            "skipped": False,
            "image_index": idx,
            "shot_type": f.get("shot_type"),
            "classification": parsed["classification"],
            "failure_class": parsed["failure_class"],
            "rule_id": parsed["rule_id"],
            "rubric_level": parsed["rubric_level"],
            "decisive_prompt_fragment": parsed["decisive_prompt_fragment"],
            "description": parsed["description"],
            "new_vs_previous": parsed.get("new_vs_previous"),
        }
        if is_finding:
            record = await record_finding_fn(
                tenant_id, rule_id=parsed["rule_id"], stage=FRAME_QA_STAGE,
                failure_class=parsed["failure_class"], classification=parsed["classification"],
            )
            finding["fingerprint_record"] = record
        findings.append(finding)

    return {"skipped": False, "cost": cost, "usage": usage, "findings": findings}


# =============================================================================
# Board station (D5 chunk A3b, Ryan's 2026-07-29 ruling): the arbiter's
# PRIMARY gate judges the $0.05 storyboard SHEET before any final frame ever
# generates — angles, character facing, and set correctness are cheap to
# catch and fix here (one sheet regen) versus expensive to catch downstream
# (many individual frame redraws). Frame-level judging (judge_scene_batch
# above) remains the secondary catch for whatever still slips through.
# =============================================================================

_BOARD_JUDGE_SYSTEM = (
    "You are the Frame Arbiter's board station — the PRIMARY quality gate "
    "for an AI video pipeline. You look at ONE storyboard sheet (a grid of "
    "hand-drawn panels for one beat of a scene) against its own written "
    "spec, BEFORE any final frame is ever generated. Catching a set, "
    "angle, or facing problem here costs one cheap sheet regeneration; "
    "missing it costs many expensive individual frame redraws later."
)

_BOARD_SETUP_RE = re.compile(r"\(SETUP\s+([A-Za-z0-9-]+)(?:\s*[—-]\s*([^)]+))?\)")
_BOARD_PANEL_RE = re.compile(r"\[(\d+)\]\s*(.+?)(?=\n\[\d+\]|\nCONSTRAINTS:|\Z)", re.DOTALL)
_BOARD_FIXED_SET_RE = re.compile(r"FIXED SET.*?:\s*(.*?)\n\n\S", re.DOTALL)
_BOARD_SHEET_HEADER_RE = re.compile(r"storyboard sheet\s+(\d+)\s+of\s+\d+", re.IGNORECASE)


def _parse_sheet_panels(spec_text: str, sheet_index: int) -> tuple[Optional[str], list[dict]]:
    """Pure text parser for the ``scenes.storyboard_prompts`` column's raw
    per-beat spec (the shape ``coverage_to_app.py`` persists — see its own
    "persists every board's full header+body" comment). Read-only: this
    module has ZERO write dependency on the storyboard-generation code,
    same DoC #7 boundary FRAME-ARBITER-PLAN.md holds for coverage.py.

    Returns ``(fixed_set_text, panels)`` for the block whose own header
    reads "storyboard sheet {sheet_index} of N" — ``fixed_set_text`` is the
    sheet's default/primary location description (applies to every panel
    unless a panel's own SETUP parenthetical names a different location,
    e.g. ``(SETUP A — ELITE VIEWING HALL)`` overriding the sheet's pod
    default). Returns ``(None, [])`` when no block matches — the caller
    treats a spec-less sheet as unjudgeable, never guesses a spec.

    Each panel dict: ``{"panel": int, "label": str, "setup": str,
    "expected_set": str, "brief": str}``. ``expected_set`` is the panel's
    own override when present, else the sheet's fixed_set_text."""
    if not spec_text:
        return None, []
    blocks = re.split(r"---\s*BEAT\s+\d+\s*---", spec_text)
    target_block = None
    for block in blocks:
        m = _BOARD_SHEET_HEADER_RE.search(block)
        if m and int(m.group(1)) == sheet_index:
            target_block = block
            break
    if target_block is None:
        return None, []

    fixed_set_match = _BOARD_FIXED_SET_RE.search(target_block)
    fixed_set = fixed_set_match.group(1).strip() if fixed_set_match else None

    panels: list[dict] = []
    for pm in _BOARD_PANEL_RE.finditer(target_block):
        panel_num = int(pm.group(1))
        body = pm.group(2).strip()
        setup_m = _BOARD_SETUP_RE.search(body)
        setup = setup_m.group(1).strip() if setup_m else "?"
        override = setup_m.group(2).strip() if (setup_m and setup_m.group(2)) else None
        # Label = whatever precedes the first em-dash/hyphen run before the
        # "(SETUP ...)" parenthetical (e.g. "M1 WS", "M3 ANGLE INSERT").
        dash_m = re.match(r"^(.*?)[—-]+\s*\(SETUP", body)
        label = dash_m.group(1).strip() if dash_m else body[:20].strip()
        panels.append({
            "panel": panel_num,
            "label": label,
            "setup": setup,
            "expected_set": override or fixed_set or "(no set spec found)",
            "brief": body,
        })
    return fixed_set, panels


def _board_rubric_prompt(panels: list[dict], fixed_set: Optional[str]) -> str:
    """Assembles the board station's rubric text — per-panel set
    correctness, facing law, angle/sequence readability, and duplicate-
    panel detection, using the exact same failure-class vocabulary and
    false-positive calibration line the scene-batch rubric uses (D5 A3b's
    "same classification law" requirement)."""
    lines = [
        f"THIS SHEET HAS {len(panels)} PANELS, laid out in a grid, each "
        "carrying its own small printed panel-number label strip beneath "
        "it — match panels to the spec below by that printed number, left "
        "to right, top to bottom.",
    ]
    if fixed_set:
        lines += ["", f"DEFAULT SET FOR THIS SHEET (applies to every panel unless a panel below names a different location): {fixed_set}"]
    lines += ["", "PER-PANEL SPEC, IN PRINTED-NUMBER ORDER:"]
    for p in panels:
        lines.append(
            f"PANEL {p['panel']} ({p['label']}, setup {p['setup']}) — expected set: {p['expected_set']}. Brief: {p['brief']}"
        )
    lines += [
        "",
        "JUDGE THIS SHEET against FOUR things, per panel:",
        "1. PER-PANEL SET CORRECTNESS — does the panel's drawn background/"
        "environment actually match its EXPECTED SET above? Name concrete "
        "objects/architecture you can see that belong to the WRONG "
        "location if it's wrong (this is the set_bleed failure class "
        "below) — a panel spec'd for one location drawn inside a "
        "completely different one is the single most expensive mistake "
        "this gate exists to catch, because fixing it here is one cheap "
        "sheet regen instead of many downstream frame redraws.",
        "2. CHARACTER FACING per the facing law — a close panel (MCU/CU/"
        "ECU), a panel described as a performance/speaking beat, or one "
        "whose brief reads an emotion off the face must show the face "
        "legible to camera (three-quarter or face-to-camera) or an "
        "explicit look-back, unless it's tagged NEUTRAL or INSERT.",
        "3. ANGLE/SEQUENCE READABILITY — panels sharing the same SETUP "
        "letter are specified as the SAME frozen camera position, copied "
        "exactly (same framing, same distance, same body position) with "
        "only the expression/gesture/caption changing between them. "
        "Flag any panel that breaks that repeated-setup law.",
        "4. DUPLICATE-PANEL DETECTION (mandatory, do this for every "
        "consecutive pair in your own reasoning before you answer): name "
        "what NEW information each panel adds over the previous one. Two "
        "panels with different SETUP letters/briefs that nonetheless read "
        "as the identical composition is a duplicate_setup defect.",
        "",
        _FAILURE_CLASS_VOCAB,
        "",
        _CALIBRATION_LINE,
        "",
        "CLASSIFY exactly one of these four PER PANEL, using this law:",
        "- MODEL_DEFECT: the spec above is CORRECT/reasonable, but the "
        "drawn panel disobeyed it (wrong set, wrong facing, wrong framing, "
        "missing/extra subject, or an unintended duplicate of another "
        "panel).",
        "- AUTHORING_DEFECT: the panel actually matches what its own "
        "brief asked for, but the brief/spec itself authored the flaw.",
        "- TASTE_QUESTION: something reads off but no rule above covers "
        "it and it's a directorial preference call, not a clear defect.",
        "- OK: no defect worth a human's attention.",
        "",
        f"Reply with EXACTLY {len(panels)} blocks, one per panel, in "
        "PANEL 1..N printed-number order, each block in this exact format "
        "and nothing else outside the blocks. NEW_VS_PREVIOUS is REQUIRED "
        "— it is where you do rule 4's duplicate-panel comparison work in "
        "writing before you commit to a classification:",
        "===PANEL <panel_number>===",
        "NEW_VS_PREVIOUS: <for PANEL 1, write FIRST_PANEL. For every other "
        "panel, name the SPECIFIC new visual information this panel adds "
        "over the immediately preceding panel — a new angle, action, or "
        "expression. If you cannot name anything concretely new, write "
        "exactly: DUPLICATE OF PANEL <n> — and that MUST drive this "
        "panel's classification below.>",
        "CLASSIFICATION: <MODEL_DEFECT|AUTHORING_DEFECT|TASTE_QUESTION|OK>",
        "FAILURE_CLASS: <short_snake_case_tag, or NONE if CLASSIFICATION is OK>",
        "RULE_ID: NONE",
        "RUBRIC_LEVEL: <hard_gate|warn|guidance>",
        "DECISIVE_FRAGMENT: <the exact phrase from the panel's brief this verdict turns on, or NONE>",
        "DESCRIPTION: <one or two plain sentences naming the actual concrete defect a human reviewer can act on — never vague>",
    ]
    return "\n".join(lines)


def parse_board_verdicts(text: str, panels: list[dict]) -> dict[int, Optional[dict]]:
    """Maps the board reply's ``===PANEL <n>===`` blocks back onto each
    panel's printed number, reusing ``parse_verdict`` (same field parser
    judge_frame/judge_scene_batch use — one parser, never a drifted copy).
    A panel with no matching block, or an unparseable block, maps to None
    (fail closed)."""
    blocks = _split_labeled_blocks(text, "PANEL")
    result: dict[int, Optional[dict]] = {}
    for p in panels:
        body = blocks.get(str(p["panel"]))
        result[p["panel"]] = parse_verdict(body) if body else None
    return result


async def judge_board_sheet(
    tenant_id: str,
    video_id: str,
    scene: int,
    sheet: dict,
    *,
    download_image: Optional[Callable[..., Awaitable]] = None,
    call_vision: Optional[Callable[..., Awaitable]] = None,
    budget_check: Callable[..., Awaitable] = arbiter_budget_check,
    ledger_write: Optional[Callable[..., Awaitable]] = None,
    record_finding_fn: Callable[..., Awaitable] = record_finding,
    projected_cost: float = DEFAULT_BOARD_QUOTE,
) -> dict:
    """D5 chunk A3b, board station: ONE vision call judges a whole
    storyboard sheet (a grid image) against its own spec — per-panel set
    correctness, facing law, angle repetition, duplicate panels — BEFORE
    any frame generates (Ryan's ruling: this is the PRIMARY gate,
    judge_scene_batch is the secondary catch).

    ``sheet`` is ``{"image_url": ..., "sheet_index": int (default 1),
    "spec_text": the raw scenes.storyboard_prompts column value}``. Same
    budget-gated / ledger-metered / fingerprint-recorded / fail-closed
    contract as judge_frame and judge_scene_batch (DEFAULT_BOARD_QUOTE
    checked against the SAME frame_qa-stage caps via arbiter_budget_check
    — this chunk does not introduce a separate board_qa ledger stage; see
    the chunk report for why, and what A5/A6 should reconsider once real
    board-gate mileage exists).

    Returns ``{"skipped": True, "reason": ..., "findings": [...]}`` (fail
    closed) or ``{"skipped": False, "sheet_index", "cost", "usage",
    "findings": [...]}`` — one finding dict per panel, same field shape as
    judge_frame's."""
    sheet_index = sheet.get("sheet_index", 1)
    spec_text = sheet.get("spec_text") or ""
    fixed_set, panels = _parse_sheet_panels(spec_text, sheet_index)
    if not panels:
        return {"skipped": True, "reason": "no_panel_spec", "sheet_index": sheet_index, "findings": []}

    breach = await budget_check(tenant_id, video_id, scene, projected_cost)
    if breach:
        return {
            "skipped": True, "reason": "budget", "breach": breach, "sheet_index": sheet_index,
            "findings": [{"skipped": True, "reason": "budget", "panel": p["panel"]} for p in panels],
        }

    downloader = download_image or _download_image_b64
    img = await downloader(sheet.get("image_url"))
    if img is None:
        return {
            "skipped": True, "reason": "download_failed", "sheet_index": sheet_index,
            "findings": [{"skipped": True, "reason": "download_failed", "panel": p["panel"]} for p in panels],
        }
    media_type, b64 = img

    content: list = [
        {"type": "image", "source": {"type": "base64", "media_type": media_type, "data": b64}},
        {"type": "text", "text": _board_rubric_prompt(panels, fixed_set)},
    ]

    vision_caller = call_vision or _call_vision
    # See judge_scene_batch's own comment — raised from 130 to 230/panel
    # for the same reason (NEW_VS_PREVIOUS added real reply length).
    max_tokens = max(500, min(2200, 230 * len(panels) + 400))
    body = await vision_caller(tenant_id, content, max_tokens=max_tokens, system=_BOARD_JUDGE_SYSTEM)
    if body is None:
        return {
            "skipped": True, "reason": "vision_error", "sheet_index": sheet_index,
            "findings": [{"skipped": True, "reason": "vision_error", "panel": p["panel"]} for p in panels],
        }

    text = " ".join(
        b.get("text", "") for b in (body.get("content") or []) if b.get("type") == "text"
    ).strip()
    usage = body.get("usage") or {}
    cost = usage_cost(usage)
    writer = ledger_write or record_frame_qa_entry
    await writer(
        tenant_id=tenant_id, video_id=video_id, scene=scene, model=VISION_MODEL,
        units=1, unit_cost=cost, actual_cost=cost, fingerprint=None,
    )

    verdicts = parse_board_verdicts(text, panels)

    findings = []
    for p in panels:
        parsed = verdicts.get(p["panel"])
        if parsed is None:
            findings.append({"skipped": True, "reason": "unparseable_reply", "panel": p["panel"], "label": p["label"]})
            continue
        is_finding = parsed["classification"] != NO_FINDING
        finding = {
            "skipped": False,
            "panel": p["panel"],
            "label": p["label"],
            "expected_set": p["expected_set"],
            "classification": parsed["classification"],
            "failure_class": parsed["failure_class"],
            "rule_id": parsed["rule_id"],
            "rubric_level": parsed["rubric_level"],
            "decisive_prompt_fragment": parsed["decisive_prompt_fragment"],
            "description": parsed["description"],
            "new_vs_previous": parsed.get("new_vs_previous"),
        }
        if is_finding:
            record = await record_finding_fn(
                tenant_id, rule_id=parsed["rule_id"], stage=FRAME_QA_STAGE,
                failure_class=parsed["failure_class"], classification=parsed["classification"],
            )
            finding["fingerprint_record"] = record
        findings.append(finding)

    return {"skipped": False, "sheet_index": sheet_index, "cost": cost, "usage": usage, "findings": findings}
