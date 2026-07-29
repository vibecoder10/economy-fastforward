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
    r"^(CLASSIFICATION|FAILURE_CLASS|RULE_ID|RUBRIC_LEVEL|DECISIVE_FRAGMENT|DESCRIPTION):\s*(.*)$",
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
    text, without a network call."""
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
    }


async def _call_vision(tenant_id: str, content: list) -> Optional[dict]:
    """One vision round-trip. Returns the parsed response JSON body, or
    None on ANY failure (no key configured, transport error, non-200) —
    fail closed, same bucket static_docu._vision_confirms uses for a
    failed attempt. Never raises. DIRECT Anthropic first (the Kie gateway
    injects tool configuration that derails vision replies into meta-talk
    about tools — same reasoning as static_docu._vision_confirms), Kie's
    Claude gateway as the fallback when no direct key is configured."""
    from vault import get_secret

    akey = await get_secret("anthropic_api_key", tenant_id)
    try:
        async with httpx.AsyncClient(timeout=60.0) as c:
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
                        "max_tokens": 400,
                        "system": _JUDGE_SYSTEM,
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
                        "max_tokens": 400,
                        "system": _JUDGE_SYSTEM,
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
) -> list[dict]:
    """Judge every frame in one scene — one vision call per frame, each
    with its immediate draw-order neighbors attached for A4's continuity
    check. Returns one finding/skip dict per frame, in draw order.

    Reads the tenant's active quality_rules ONCE for the whole batch (a
    plain DB read, not a paid call) rather than once per frame."""
    frames = await fetch_frames(tenant_id, video_id, scene)
    rules = await list_all_rules(tenant_id, active_only=True)
    rules_text, _ = compose_rules_text(rules or [])

    findings = []
    for i, frame in enumerate(frames):
        neighbors = []
        if i > 0:
            neighbors.append(frames[i - 1])
        if i < len(frames) - 1:
            neighbors.append(frames[i + 1])
        findings.append(await judge_frame(
            tenant_id, video_id, scene, frame, neighbors,
            rules_text=rules_text, axis_line=axis_line,
            budget_check=budget_check, ledger_write=ledger_write,
            record_finding_fn=record_finding_fn,
        ))
    return findings
