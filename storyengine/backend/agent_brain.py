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


TOOL_DOC = (
    "TOOLS you can call (one per turn) to LOOK at the video before deciding:\n"
    '- {"tool":"actions"} — every runnable verb with its real cost and what\'s blocked (and why)\n'
    '- {"tool":"script","args":{"scene":<int or null>}} — read the script (one scene or all)\n'
    '- {"tool":"shots","args":{"scene":<int or null>}} — every shot: has picture? has clip? flagged?\n'
    '- {"tool":"prompt","args":{"surface":"image|motion|thumbnail","scene":<int|null>,"index":<int|null>}} — read a generation prompt\n'
    '- {"tool":"history"} — recent stage transitions (what ran, what failed, when)\n'
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
    return f"Unknown tool '{name}'."


# --- the loop ----------------------------------------------------------------

def _decision_schema() -> str:
    # Identical to the legacy classifier's output so downstream code is unchanged.
    return (
        '{"kind":"read|action|prompt",'
        '"verb":"script|characters|storyboards|images|voice|animate|sound|thumbnail|render|research|seo|'
        'upload|approve_cast|approve_environments|skip_environments|lock|unlock|drive_push|drive_sync|build|none",'
        '"surface":"image|motion|thumbnail|script|null",'
        '"op":"view|suggest|rewrite|null",'
        '"scene":<int or null>,"index":<int or null>,'
        '"change":"<for action edits: a concrete instruction; else empty>",'
        '"direction":"<for prompt rewrite: the enhancement instruction; else empty>",'
        '"length_min":<int or null>,'
        '"answer":"<for read: a specific, friendly answer grounded in what you SAW>",'
        '"reply":"<for action: one friendly sentence; for none: a clarifying question>",'
        '"confidence":<0.0-1.0>}'
    )


async def run_copilot_brain(client, model_for_call, tenant_id, video_id,
                            summary: dict, message: str, ui_context: dict,
                            summary_line: str) -> Optional[dict]:
    """Multi-step look-then-decide. Returns the classifier-shaped decision dict,
    or None so the caller falls back to the one-shot classifier."""
    from producer_prompt import _extract_json

    system = (
        "You are the in-app co-pilot AGENT for ONE video. The creator can (a) ASK a question, "
        "(b) tell you to RUN a production step, or (c) work on a generation PROMPT. You have READ "
        "tools — use them to ground yourself in the video's ACTUAL state before deciding; never "
        "guess numbers you could look up. You cannot run anything yourself: paid work always goes "
        "through a confirm card after you decide.\n\n"
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
        "skip_environments=approvals; lock/unlock=freeze the story; drive_push / drive_sync=script to/from Google "
        "Drive; build=run the whole pipeline to the next checkpoint ('build it', 'finish it', 'keep going', "
        "'do it all'). PROMPT work (kind=prompt) when they discuss a prompt itself: set surface, op "
        "(view|suggest|rewrite), scene/index (use the currently-viewing shot for 'this'), and direction.\n\n"
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
