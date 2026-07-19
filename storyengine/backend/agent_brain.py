"""The copilot's agent brain (PARITY-PLAN Phase 6).

Replaces the one-shot classify-and-fire with a small tool-using loop: the model
can READ the video (state, script, shots, prompts, recent history) across up to
MAX_STEPS turns before it decides. Its decision comes back in the SAME shape the
old classifier returned ({kind, verb, scene, change, ...}), so everything
downstream — the legality gate, the cost estimate, the one-tap confirm card —
is unchanged. Money never moves inside the brain: paid work still exits through
the confirm flow in routes/chat.py.

Works with any plain text client (client.generate) via a JSON protocol:
each model turn returns ONE object — {"tool": name, "args": {...}} to look at
something, or {"final": {...classifier dict...}} to decide. On ANY failure the
caller falls back to the legacy one-shot classifier, so the brain can only ever
make the copilot smarter, not break it.

C15d (one director voice + data reach): this loop's system prompt now
prepends producer_prompt.DIRECTOR_VOICE — the SAME personality core the home
producer speaks in — so the in-video copilot sounds like one director, not a
second, thinner voice. It also gets a channel_data read tool (backed by
channel_briefs.py, the same brief builders the home producer's "what should
I make next" uses) so it can answer channel-level questions from inside a
video, not just this-video questions. Its op/verb classification, confidence
gating, and JSON decision schema are unchanged.
"""

from __future__ import annotations

import json
import logging
from typing import Any, Optional

import actions
from database import fetch_all, fetch_one

logger = logging.getLogger(__name__)

MAX_STEPS = 5
_TRUNC = 2600  # per-tool-result cap so the loop can't blow the context


# --- tools -------------------------------------------------------------------

async def _tool_state(tenant_id, video_id, summary) -> str:
    """Everything runnable right now: verb, cost, blocked reason."""
    lines = []
    for verb, cfg in actions.ACTIONS.items():
        blocked = actions.blocked_reason(verb, summary)
        _cost, cost_text = await actions.estimate_cost(tenant_id, video_id, verb, None, summary)
        lines.append(f"- {verb}: {cfg['label']} · {cost_text}" + (f" · BLOCKED: {blocked}" if blocked else " · runnable"))
    return "\n".join(lines)


async def _tool_script(tenant_id, video_id, scene: Optional[int]) -> str:
    if scene is not None:
        rows = await fetch_all(
            "SELECT scene, scene_text FROM scripts WHERE video_id=$1 AND tenant_id=$2 AND scene=$3",
            video_id, tenant_id, scene)
    else:
        rows = await fetch_all(
            "SELECT scene, scene_text FROM scripts WHERE video_id=$1 AND tenant_id=$2 "
            "AND scene IS NOT NULL ORDER BY scene", video_id, tenant_id)
    if not rows:
        return "No script scenes yet."
    out = []
    for r in rows:
        txt = (r.get("scene_text") or "").strip()
        out.append(f"SCENE {r['scene']}: {txt[:400]}{'…' if len(txt) > 400 else ''}")
    return "\n".join(out)


async def _tool_shots(tenant_id, video_id, scene: Optional[int]) -> str:
    q = ("SELECT scene, image_index, (image_url IS NOT NULL) AS has_pic, "
         "(video_clip_url IS NOT NULL) AS has_clip, extraction_flags "
         "FROM assets WHERE video_id=$1 AND tenant_id=$2")
    args: list[Any] = [video_id, tenant_id]
    if scene is not None:
        q += " AND scene=$3"
        args.append(scene)
    q += " ORDER BY scene, image_index"
    rows = await fetch_all(q, *args)
    if not rows:
        return "No shots (asset rows) yet."
    out = []
    for r in rows[:80]:
        flags = r.get("extraction_flags")
        out.append(f"S{r.get('scene')}.{r.get('image_index')}: "
                   f"{'pic' if r.get('has_pic') else 'NO pic'}, "
                   f"{'clip' if r.get('has_clip') else 'no clip'}"
                   + (" [flagged crop]" if flags else ""))
    if len(rows) > 80:
        out.append(f"...and {len(rows) - 80} more")
    return "\n".join(out)


async def _tool_prompt(tenant_id, video_id, surface: str, scene: Optional[int], index: Optional[int]) -> str:
    if surface == "thumbnail":
        row = await fetch_one("SELECT thumbnail_prompt FROM videos WHERE id=$1 AND tenant_id=$2",
                              video_id, tenant_id)
        return (row or {}).get("thumbnail_prompt") or "No thumbnail prompt set."
    col = "image_prompt" if surface == "image" else "video_prompt"
    row = await fetch_one(
        f"SELECT {col} AS p FROM assets WHERE video_id=$1 AND tenant_id=$2 "
        "AND ($3::int IS NULL OR scene=$3) AND ($4::int IS NULL OR image_index=$4) "
        "ORDER BY scene, image_index LIMIT 1",
        video_id, tenant_id, scene, index)
    return (row or {}).get("p") or f"No {surface} prompt found for that shot."


async def _tool_history(tenant_id, video_id) -> str:
    rows = await fetch_all(
        "SELECT from_status, to_status, triggered_by, created_at FROM stage_transitions "
        "WHERE video_id=$1 AND tenant_id=$2 ORDER BY created_at DESC LIMIT 12",
        video_id, tenant_id)
    if not rows:
        return "No stage history."
    return "\n".join(
        f"{str(r.get('created_at'))[:16]}: {r.get('from_status')} -> {r.get('to_status')} ({r.get('triggered_by')})"
        for r in rows)


async def _tool_channel_data(tenant_id) -> str:
    """The SAME data-backed briefs the home producer uses for "what should I
    make next" / "how's my channel doing" (C15d: one director voice + data
    reach) — the strongest UNMODELED competitor winners (scored), this
    creator's own published-video analytics, and proven patterns the channel
    has learned. One shared implementation (channel_briefs.py) so the home
    chat and this in-video copilot can never disagree. Tenant-scoped, and
    each section is already fail-soft (a DB error there returns '' — see
    channel_briefs.py) so this never breaks the turn; if every section is
    empty (no data synced yet), say so plainly rather than returning ''."""
    from channel_briefs import _learnings_brief, _next_to_make_brief, _own_performance_brief
    parts = [
        await _next_to_make_brief(tenant_id),
        await _own_performance_brief(tenant_id),
        await _learnings_brief(tenant_id),
    ]
    text = "".join(p for p in parts if p).strip()
    return text or "No channel performance or competitor data available yet."


async def _tool_cost(tenant_id, video_id, summary) -> str:
    """Real ledgered spend so far, grouped by stage (checklist §0.3d / C10
    conversational door) — grounds "how much has this cost?" in the SAME
    generation_ledger table the cost chip's drawer reads
    (routes/videos.py::get_video_ledger), so the chat answer and the UI can
    never disagree. Also quotes what finishing adds, via the same estimator
    the "build" confirm card uses."""
    rows = await fetch_all(
        "SELECT stage, actual_cost FROM generation_ledger WHERE video_id=$1 AND tenant_id=$2",
        video_id, tenant_id)
    _remaining_cost, remaining_text = await actions.estimate_cost(
        tenant_id, video_id, "build", None, summary)
    if not rows:
        return f"No spend recorded yet — nothing paid has run. Next step: {remaining_text}."
    by_stage: dict[str, float] = {}
    for r in rows:
        stage = r.get("stage") or "other"
        by_stage[stage] = round(by_stage.get(stage, 0.0) + float(r.get("actual_cost") or 0), 2)
    total = round(sum(by_stage.values()), 2)
    breakdown = ", ".join(
        f"{stage} ${cost:.2f}" for stage, cost in sorted(by_stage.items(), key=lambda kv: -kv[1])
    )
    tail = ""
    if _remaining_cost > 0:
        tail = f" Finishing adds ~{remaining_text.lstrip('~')}"
        # C15: itemize what's left the same way the "finish it" confirm card
        # does — cheap to add (same estimator, one extra call) and never
        # worth failing this read over, so any error just drops the
        # itemization and keeps the plain "Finishing adds ~$X" tail.
        try:
            model_breakdown = await actions.cost_breakdown(tenant_id, video_id, "build", None, summary)
        except Exception:  # noqa: BLE001 — read-only nicety, never break "how much has this cost?"
            model_breakdown = None
        if model_breakdown and model_breakdown.get("lines"):
            parts = [f'{ln["count"]}×{ln["display_name"]} ${ln["subtotal"]:.2f}' for ln in model_breakdown["lines"]]
            tail += " (" + " + ".join(parts) + ")"
        tail += "."
    return f"Actual spend so far ${total:.2f}: {breakdown}.{tail}"


TOOL_DOC = (
    "TOOLS you can call (one per turn) to LOOK at the video before deciding:\n"
    '- {"tool":"actions"} — every runnable verb with its real cost and what\'s blocked (and why)\n'
    '- {"tool":"script","args":{"scene":<int or null>}} — read the script (one scene or all)\n'
    '- {"tool":"shots","args":{"scene":<int or null>}} — every shot: has picture? has clip? flagged?\n'
    '- {"tool":"prompt","args":{"surface":"image|motion|thumbnail","scene":<int|null>,"index":<int|null>}} — read a generation prompt\n'
    '- {"tool":"history"} — recent stage transitions (what ran, what failed, when)\n'
    '- {"tool":"cost"} — REAL ledgered spend so far, broken down by stage (use this for "how much has this cost?", not the "actions" cost estimates)\n'
    '- {"tool":"channel_data"} — this CHANNEL\'s data (not just this video): scored unmodeled competitor '
    'winners ("what should I make next?"), this creator\'s own published-video analytics ("how are my videos '
    'doing?"), and proven patterns the channel has learned ("what works for us?")\n'
)


async def _run_tool(name: str, args: dict, tenant_id, video_id, summary) -> str:
    if name == "actions":
        return await _tool_state(tenant_id, video_id, summary)
    if name == "script":
        return await _tool_script(tenant_id, video_id, args.get("scene"))
    if name == "shots":
        return await _tool_shots(tenant_id, video_id, args.get("scene"))
    if name == "prompt":
        return await _tool_prompt(tenant_id, video_id, args.get("surface") or "image",
                                  args.get("scene"), args.get("index"))
    if name == "history":
        return await _tool_history(tenant_id, video_id)
    if name == "cost":
        return await _tool_cost(tenant_id, video_id, summary)
    if name == "channel_data":
        return await _tool_channel_data(tenant_id)
    return f"Unknown tool '{name}'."


# --- the loop ----------------------------------------------------------------

def _decision_schema() -> str:
    # Identical to the legacy classifier's output so downstream code is unchanged.
    return (
        '{"kind":"read|action|prompt|show|remember|forget",'
        '"verb":"script|characters|storyboards|images|voice|animate|draft_pass|finalize|sound|thumbnail|'
        'render|research|seo|upload|approve_cast|approve_environments|skip_environments|approve_scene|'
        'lock|unlock|drive_push|drive_sync|advance|build|none",'
        '"surface":"image|motion|thumbnail|script|null",'
        '"op":"view|suggest|rewrite|null",'
        '"scene":<int or null>,"index":<int or null>,'
        '"change":"<for action edits: a concrete instruction; for remember: the instruction VERBATIM; for '
        'forget: their reference to which one; else empty>",'
        '"direction":"<for prompt rewrite: the enhancement instruction; else empty>",'
        '"length_min":<int or null>,'
        '"scope":"channel|video (only meaningful for kind=remember; default channel)",'
        '"answer":"<for read: a specific, friendly answer grounded in what you SAW>",'
        '"reply":"<for action: one friendly sentence; for none: a clarifying question>",'
        '"confidence":<0.0-1.0>}'
    )


async def run_copilot_brain(client, model_for_call, tenant_id, video_id,
                            summary: dict, message: str, ui_context: dict,
                            summary_line: str) -> Optional[dict]:
    """Multi-step look-then-decide. Returns the classifier-shaped decision dict,
    or None so the caller falls back to the one-shot classifier."""
    from producer_prompt import DIRECTOR_VOICE, _extract_json

    system = (
        "You are the in-app co-pilot AGENT for ONE video — the SAME director as the studio's home "
        "producer, not a different voice.\n\n"
        + DIRECTOR_VOICE + "\n\n"
        "The creator can (a) ASK a question, "
        "(b) tell you to RUN a production step, (c) work on a generation PROMPT, or (d) ask to SEE "
        "the actual pictures/storyboards for a scene. You have READ "
        "tools — use them to ground yourself in the video's ACTUAL state before deciding; never "
        "guess numbers you could look up. You cannot run anything yourself: paid work always goes "
        "through a confirm card after you decide (approve_scene is free, so it runs immediately).\n\n"
        + summary_line + "\n"
        + (f"They are currently viewing scene {ui_context.get('scene')}"
           + (f", image {ui_context.get('index')}" if ui_context.get("index") else "")
           + ".\n" if ui_context.get("scene") else "")
        + f'\nThe creator said: "{message}"\n\n'
        + TOOL_DOC + "\n"
        "VERB MEANINGS (for the final decision): script=rewrite the whole script; characters=design/redesign the CAST "
        "(never map cast requests to script); storyboards=cheap single-sheet preview; images=the real per-shot "
        "pictures; animate=ONE scene's clips (give the scene); research=fact-find the topic; seo=YouTube "
        "title/description/tags; upload=publish the RENDERED video; approve_cast / approve_environments / "
        "skip_environments=whole-video approvals; approve_scene=approve/lock ONE scene's pictures ('approve "
        "scene 2', 'these look good, lock it in' while viewing a scene — give the scene, free, no confirm "
        "needed); lock/unlock=freeze the story; drive_push / drive_sync=script to/from Google "
        "Drive; advance=skip the CURRENT stage/gate and move on ('skip this step', 'skip research', 'move on') — "
        "and the script verb skips research automatically when they ask for the script early; "
        "build=run the whole pipeline to the next checkpoint ('build it', 'finish it', 'keep going', "
        "'do it all'); draft_pass=animate EVERY scene on the CHEAP draft-tier model in one pass, before real "
        "money is spent ('draft the whole video', 'rough cut', 'let me see it first', 'draft it cheap') — "
        "different from 'animate everything'/build, which is REAL (routed/premium) quality; "
        "finalize=regenerate ONLY the already-approved scenes (approve_scene) at their real routed/premium "
        "quality ('finalize the approved scenes', 'finish the ones I approved') — no scene number needed, it "
        "always means whichever scenes are currently approved; if none are approved yet it still classifies "
        "as finalize (the runner explains there's nothing to finalize). PROMPT work (kind=prompt) when they "
        "discuss the generation PROMPT TEXT itself: set "
        "surface, op (view|suggest|rewrite), scene/index (use the currently-viewing shot for 'this'), and "
        "direction. SHOW work (kind=show) when they want to SEE the actual pictures/storyboards for a scene "
        "('show me scene 2's boards', 'let me see scene 3's pictures') — NOT the prompt text; give the scene "
        "(use the currently-viewing one for 'this scene' with no number named).\n"
        "REMEMBER work (kind=remember) when they give a STANDING instruction meant to stick across future "
        "conversations and videos, not just answering this one ask — 'always...', 'never...', 'remember "
        "that...', 'from now on...'. Put their instruction VERBATIM in change (never paraphrase it). Set "
        "scope='video' only when it's clearly specific to THIS video; default scope='channel' (they said "
        "always/never/from now on, or it's a general fact about them/their channel).\n"
        "FORGET work (kind=forget) when they say 'forget that', 'forget #N', or 'forget the one about...'. Put "
        "their reference (a number, 'that'/'last', or the closest matching text) in change. If they instead "
        "ASK what you remember ('what do you remember about me/this channel?'), answer that as kind=read from "
        "any STANDING PREFERENCES you were given above — don't use kind=remember or kind=forget for a plain "
        "listing question.\n"
        "CHANNEL-LEVEL questions (kind=read) that reach beyond THIS video — 'what should I make next?', "
        "'how are my videos doing?'/'how's the channel?', 'what works for us?' — call the channel_data tool "
        "before answering; never guess or invent a stat. If it comes back with 'No channel performance or "
        "competitor data available yet', say that plainly instead of making something up.\n\n"
        "Each turn, return ONE JSON object and NOTHING else. Either call a tool:\n"
        '  {"tool":"<name>","args":{...}}\n'
        "or decide:\n"
        '  {"final":' + _decision_schema() + "}\n"
        "Look before you leap, but don't dawdle: simple requests (e.g. 'redo the thumbnail') should be "
        "decided immediately with no tool calls. Use at most " + str(MAX_STEPS - 1) + " tool calls."
    )

    convo = system
    for _step in range(MAX_STEPS):
        kw: dict[str, Any] = {"prompt": convo, "max_tokens": 900, "temperature": 0.2}
        if model_for_call:
            kw["model"] = model_for_call
        raw = await client.generate(**kw)
        try:
            data = json.loads(_extract_json(raw))
        except Exception:  # noqa: BLE001 — malformed turn: give up, caller falls back
            logger.warning("agent_brain: unparseable turn: %.200s", raw)
            return None
        if isinstance(data, dict) and data.get("final"):
            final = data["final"]
            return final if isinstance(final, dict) else None
        # Legacy-shaped answer without the wrapper — accept it as final.
        if isinstance(data, dict) and data.get("kind"):
            return data
        if isinstance(data, dict) and data.get("tool"):
            name = str(data.get("tool"))
            args = data.get("args") or {}
            try:
                result = await _run_tool(name, args if isinstance(args, dict) else {}, tenant_id, video_id, summary)
            except Exception as e:  # noqa: BLE001 — a broken tool shouldn't kill the turn
                result = f"Tool error: {e}"
            convo += f"\n\nTOOL RESULT ({name}):\n{str(result)[:_TRUNC]}\n\nNext JSON:"
            continue
        logger.warning("agent_brain: unrecognized turn shape: %.200s", raw)
        return None
    # Out of steps without a decision — let the legacy classifier handle it.
    return None
