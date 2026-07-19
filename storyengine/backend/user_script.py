"""Creator-supplied scripts ("use this script for a video").

Takes the creator's own script text (a dropped PDF, pasted text, a queue item)
and installs it on a video VERBATIM: split into scenes, persisted exactly the
way the modeled-script path persists generated scripts (videos.script + one
scripts row per scene + dialogue tagging), and marked script_source =
'user_supplied' so run_script skips generation and nothing second-guesses
their words — no retention grading, no factual gate. The creator's word is
final.

Checklist C46d adds the OTHER external door, ``accept_external_script``: an
agent/MCP-submitted script (C47's future ``submit_script`` tool, and any
current agent-authored path) is NOT the creator's own verbatim text, so it
does not get ``set_user_script``'s bypass — it faces the SAME quality-rules
critic a platform-generated script faces (decisions.md 2026-07-19
MCP-economics entry: "the rules engine is the trust boundary that makes
externally-written content safe to accept"). See that function's docstring
for the accept/reject design.
"""

from __future__ import annotations

import json
import logging
import re

from database import execute, fetch_one
# Single Claude tier source (checklist §3.4 / C35) — see shared.channel_profile.
from actions import claude_model_for_direct_client

logger = logging.getLogger(__name__)

# Matches the modeled path's per-scene narration size so voice pacing and the
# downstream per-scene machinery see familiar scene lengths (~45-60s spoken).
TARGET_WORDS_PER_SCENE = 120
# Same Kie-roster voice default the modeled path stamps on scripts rows.
DEFAULT_VOICE_ID = "1SM7GgM6IMuvQlz2BwM3"


def split_scenes_explicit(text: str) -> list[dict]:
    """Scenes the CREATOR marked: @@@SCENE n@@@ sentinels or 'SCENE 1' / 'ACT 2'
    heading lines. Empty list when the script carries no explicit breaks —
    explicit marks always win over any automatic splitting."""
    from pipeline_executor import PipelineExecutor

    text = (text or "").strip()
    if not text:
        return []
    if re.search(r"@@@\s*SCENE\s*\d+\s*@@@", text, re.IGNORECASE):
        return PipelineExecutor._parse_modeled_scenes(text)
    headed = re.sub(
        r"(?mi)^\s*(?:SCENE|ACT)\s+(\d+)\s*[:.\-]?\s*$", r"@@@SCENE \1@@@", text
    )
    if "@@@SCENE" in headed:
        return PipelineExecutor._parse_modeled_scenes(headed)
    return []


def split_scenes_paragraphs(text: str) -> list[dict]:
    """The dumb-but-safe fallback: group paragraphs into scenes of
    ~TARGET_WORDS_PER_SCENE words."""
    text = (text or "").strip()
    if not text:
        return []
    paras = [p.strip() for p in re.split(r"\n\s*\n", text) if p.strip()]
    scenes, cur, cur_words = [], [], 0
    for p in paras:
        cur.append(p)
        cur_words += len(p.split())
        if cur_words >= TARGET_WORDS_PER_SCENE:
            scenes.append({"scene": len(scenes) + 1, "text": "\n\n".join(cur)})
            cur, cur_words = [], 0
    if cur:
        scenes.append({"scene": len(scenes) + 1, "text": "\n\n".join(cur)})
    return scenes


def split_scenes(text: str) -> list[dict]:
    """Synchronous split: explicit creator marks, else paragraph grouping.
    (set_user_script additionally tries the semantic model split in between.)"""
    return split_scenes_explicit(text) or split_scenes_paragraphs(text)


# Semantic split only echoes the script back with markers, so cap the size it
# attempts (longer scripts fall back to paragraph grouping).
SEMANTIC_MAX_CHARS = 24_000


async def semantic_split(tenant_id, text: str) -> Optional[list[dict]]:
    """One model call inserts @@@SCENE n@@@ markers at natural beat boundaries
    (one machine / one story beat / one location per scene), guided by the
    channel's locked segmentation when there is one.

    VERBATIM-GUARDED: the script text after splitting must equal the original
    word for word (markers aside). If the model changed, dropped, or added
    ANYTHING, return None and let the caller fall back — an automatic split is
    never allowed to rewrite the creator's script."""
    text = (text or "").strip()
    if not text or len(text) > SEMANTIC_MAX_CHARS:
        return None
    try:
        from kie_unified import get_text_client_for_tenant
        client = await get_text_client_for_tenant(tenant_id)
    except Exception as e:  # noqa: BLE001 — no key/client -> fallback splitter
        logger.warning("[user_script] semantic split unavailable: %s", str(e)[:150])
        return None

    hint = ""
    try:
        from channel_format import get_channel_format
        fmt, _locked = await get_channel_format(tenant_id)
        seg = (fmt or {}).get("segmentation")
        if seg:
            hint = f"\n- This channel's episodes are structured as: {seg}. Break scenes to match."
    except Exception:  # noqa: BLE001
        pass

    prompt = (
        "Insert scene markers into this video script for production. Rules:\n"
        "- Reproduce the script EXACTLY as given — do not add, remove, or change a single word.\n"
        "- Put a line containing only @@@SCENE 1@@@ at the VERY START, then a @@@SCENE n@@@ "
        "line before each new scene (n = 2, 3, ...).\n"
        "- A scene is ONE coherent beat: one subject, machine, product, location, or story "
        "moment. When the script moves to a new subject (the next machine in a review, a new "
        "story beat), start a new scene.\n"
        "- Aim for scenes a narrator reads in 30–90 seconds (~75–220 words); split an "
        "over-long beat at its most natural pause."
        + hint +
        "\n- Output ONLY the marked-up script, nothing else.\n\nSCRIPT:\n" + text
    )
    model = claude_model_for_direct_client(client)
    kwargs = {"model": model} if model else {}
    try:
        raw = await client.generate(prompt=prompt, max_tokens=16000, temperature=0.2, **kwargs)
    except Exception as e:  # noqa: BLE001
        logger.warning("[user_script] semantic split call failed: %s", str(e)[:200])
        return None

    from pipeline_executor import PipelineExecutor
    scenes = PipelineExecutor._parse_modeled_scenes(raw or "")
    if not scenes:
        return None

    def _norm(s: str) -> str:
        return re.sub(r"\W+", "", s).lower()

    if _norm("".join(s["text"] for s in scenes)) != _norm(text):
        logger.warning("[user_script] semantic split altered the words — using fallback splitter")
        return None
    return scenes


async def set_user_script(tenant_id, video_id: str, text: str) -> dict:
    """Install the creator's script on a video verbatim. Returns
    {"scenes": n, "status": <new video status>}. Raises ValueError on
    unusable input or a missing video."""
    video = await fetch_one(
        "SELECT * FROM videos WHERE id = $1 AND tenant_id = $2 AND deleted_at IS NULL",
        video_id, tenant_id,
    )
    if not video:
        raise ValueError("Video not found")
    # Split priority: the creator's own marks always win; unmarked scripts get
    # the semantic model split (one beat per scene, verbatim-guarded); the
    # word-count paragraph splitter is the fail-soft floor.
    scenes = split_scenes_explicit(text)
    if not scenes:
        scenes = await semantic_split(tenant_id, text)
    if not scenes:
        scenes = split_scenes_paragraphs(text)
    if not scenes:
        raise ValueError("No usable script text")

    from pipeline_executor import PipelineExecutor

    full_script = "\n\n".join(s["text"].strip() for s in scenes)
    new_status = PipelineExecutor._skip_disabled_next(dict(video), "ready_for_voice")
    await execute(
        """UPDATE videos SET script = $1, script_source = 'user_supplied',
               script_validation = $2, status = $3, updated_at = now()
           WHERE id = $4 AND tenant_id = $5""",
        full_script,
        json.dumps({"passed": True, "checks": [
            {"name": "user_supplied", "passed": True,
             "detail": "Creator-supplied script used verbatim — generation, grading, and factual gates skipped"}]}),
        new_status, video_id, tenant_id,
    )
    await execute("DELETE FROM scripts WHERE video_id = $1 AND tenant_id = $2", video_id, tenant_id)
    for i, scene in enumerate(scenes, start=1):
        await execute(
            """INSERT INTO scripts (tenant_id, video_id, scene, scene_text, title, script_status, voice_id)
               VALUES ($1, $2, $3, $4, $5, 'Create', $6)""",
            tenant_id, video_id, i, scene["text"].strip(),
            video.get("video_title"), DEFAULT_VOICE_ID,
        )

    # Same unattended dialogue tagging every script path gets; best-effort.
    try:
        from dialogue_intelligence import tag_video_dialogue
        await tag_video_dialogue(video_id, tenant_id)
    except Exception as e:  # noqa: BLE001
        logger.warning("[user_script] dialogue tagging failed for %s: %s", video_id, str(e)[:200])

    return {"scenes": len(scenes), "status": new_status}


# ---------------------------------------------------------------------------
# External-submission ingest gate (checklist C46d) — the seam C47's MCP
# `submit_script` tool calls, and any current agent-authored submit path.
# ---------------------------------------------------------------------------

def _normalize_external_scenes(scenes: Any) -> list[dict]:
    """Same scene SHAPE every save path in this module already enforces (see
    ``split_scenes_paragraphs``/``split_scenes_explicit`` above and
    ``PipelineExecutor._parse_modeled_scenes``): an ordered
    ``[{"scene": n, "text": str}, ...]`` list, renumbered sequentially from 1
    (an externally-submitted "scene" index is untrusted — never used as-is).
    Raises ValueError with a concrete, one-line reason per bad item so the
    submitting agent gets something it can act on, not a silent empty list."""
    if not isinstance(scenes, list) or not scenes:
        raise ValueError("scenes must be a non-empty list")
    out: list[dict] = []
    for i, item in enumerate(scenes):
        if not isinstance(item, dict):
            raise ValueError(f"scene {i + 1} is not an object with a 'text' field")
        text = str(item.get("text") or "").strip()
        if not text:
            raise ValueError(f"scene {i + 1} has no non-empty 'text'")
        out.append({"scene": len(out) + 1, "text": text})
    return out


async def accept_external_script(
    tenant_id, video_id: str, scenes: list, *, source: str = "agent_submitted",
) -> dict:
    """Ingest gate for an EXTERNALLY-SUBMITTED script — the honest boundary
    between "the creator's own words" (``set_user_script``, verbatim,
    bypasses everything) and "platform-generated" (``run_script``, graded
    AND server-edited via ``script_quality.run_critique_and_edit``'s bounded
    same-draft loop). An agent/MCP submission is neither: it is not ours to
    silently rewrite (the words are not our draft), but it is also not the
    human creator's typed-in text the "creator's word is final" contract was
    built for — so it gets the SAME critic every platform script faces,
    verdict-only, no edit loop:

      - 'pass' (including WARN/GUIDANCE-severity rule failures that never
        flip the verdict — see ``script_quality._apply_rule_severity``):
        ACCEPT. Saved through the exact scene/videos.script save path
        ``set_user_script`` above uses (same INSERT shape, same dialogue
        tagging), ``script_source`` = ``source`` (NOT 'user_supplied' —
        keeps this submission distinct from a creator's verbatim text in
        every downstream check, e.g. ``run_script``'s own
        ``script_source == 'user_supplied'`` bypass guard), status
        advances exactly like a generated script's does. Any WARN-severity
        rule failures are attached as non-blocking ``warnings``.
      - 'revise'/'regenerate' (a universal retention gate or a hard-gate
        channel rule failed): REJECT. Nothing is saved, nothing advances —
        the full rule-by-rule ``violations`` list is returned so the
        SUBMITTING AGENT can fix its own draft and resubmit. This is the
        honest boundary for agent-authored content: a human fixes their own
        prose by revising it; an agent fixes its prose by trying again with
        the concrete list of what failed. Neither needs OUR edit loop
        putting words in their mouth they didn't write, and a hard rejection
        with a naming of exactly what's wrong is a cheaper, more honest
        contract than a silent server-side rewrite of someone else's
        submission would be.

    ``source='user_supplied'`` is refused (raises ValueError) — that
    contract belongs to ``set_user_script`` alone; this function's entire
    reason to exist is running the critic external content must never
    bypass.

    Returns a dict:
      - reject: ``{"accepted": False, "verdict", "violations", "rule_verdicts"}``
      - accept: ``{"accepted": True, "verdict", "violations": [], "warnings",
        "scenes": int, "status": <new video status>}``

    Raises ``ValueError`` on a missing video, unusable scene shape, or
    ``source='user_supplied'``. Fails OPEN on a missing/broken Claude client
    (``script_quality.critique_script``'s own convention, matched here) — a
    transient config problem must not indefinitely block a submission no
    human is standing by to retry.
    """
    if source == "user_supplied":
        raise ValueError(
            "accept_external_script is not the user_supplied bypass — call "
            "set_user_script for a creator's own verbatim text"
        )
    video = await fetch_one(
        "SELECT * FROM videos WHERE id = $1 AND tenant_id = $2 AND deleted_at IS NULL",
        video_id, tenant_id,
    )
    if not video:
        raise ValueError("Video not found")

    normalized = _normalize_external_scenes(scenes)

    client = None
    try:
        from kie_unified import get_text_client_for_tenant
        client = await get_text_client_for_tenant(tenant_id)
    except Exception as e:  # noqa: BLE001 — fail open; critique_script(client=None) already fails open
        logger.warning(
            "[user_script] accept_external_script: no client for tenant %s: %s",
            str(tenant_id)[:8], str(e)[:150],
        )

    niche = ""
    try:
        from identity import build_identity_context
        identity = await build_identity_context(tenant_id, video)
        niche = identity.niche
    except Exception:  # noqa: BLE001
        niche = ""

    import quality_rules
    import script_quality

    rules_text, severity_by_rule = "", {}
    try:
        rule_rows = await quality_rules.list_all_rules(tenant_id, active_only=True)
        matched = quality_rules.active_rules_for_video(video, rule_rows)
        rules_text, severity_by_rule = quality_rules.compose_rules_text(matched)
    except Exception:  # noqa: BLE001
        rules_text, severity_by_rule = "", {}

    full_text = "\n\n".join(s["text"] for s in normalized)
    grade = await script_quality.critique_script(
        tenant_id, video_id,
        {
            "niche": niche, "title": video.get("video_title"),
            "hook": video.get("executive_hook") or video.get("hook_script"),
            "script": full_text,
        },
        rules_text=rules_text, severity_by_rule=severity_by_rule, client=client,
    )

    if grade.needs_revision:
        return {
            "accepted": False,
            "verdict": grade.verdict,
            "violations": grade.violations,
            "rule_verdicts": [rv.model_dump() for rv in grade.rule_verdicts],
        }

    warnings = [
        (rv.note.strip() or rv.rule) for rv in grade.rule_verdicts if not rv.passed
    ]

    from pipeline_executor import PipelineExecutor
    new_status = PipelineExecutor._skip_disabled_next(dict(video), "ready_for_voice")

    validation = {
        "passed": True,
        "checks": [{
            "name": "external_submission", "passed": True,
            "detail": f"Accepted from {source} — quality critic verdict: "
                      f"{grade.verdict} (score {grade.score})",
        }],
        # Same quality_critic shape run_script's own critic call writes
        # (pipeline_executor._grade_and_maybe_revise_script) so the Script
        # Validation surface (ScriptVoiceTab) renders both identically.
        "quality_critic": {
            "passed": True,
            "verdict": grade.verdict,
            "score": grade.score,
            "failing_gates": grade.failing_gates,
            "violations": [],
            "warnings": warnings,
            "rule_verdicts": [rv.model_dump() for rv in grade.rule_verdicts],
            "severity_by_rule": severity_by_rule,
            "edit_rounds": 0,
            "regenerated": False,
        },
    }
    await execute(
        """UPDATE videos SET script = $1, script_source = $2,
               script_validation = $3, status = $4, updated_at = now()
           WHERE id = $5 AND tenant_id = $6""",
        full_text, source, json.dumps(validation), new_status, video_id, tenant_id,
    )
    await execute("DELETE FROM scripts WHERE video_id = $1 AND tenant_id = $2", video_id, tenant_id)
    for sc in normalized:
        await execute(
            """INSERT INTO scripts (tenant_id, video_id, scene, scene_text, title, script_status, voice_id)
               VALUES ($1, $2, $3, $4, $5, 'Create', $6)""",
            tenant_id, video_id, sc["scene"], sc["text"], video.get("video_title"), DEFAULT_VOICE_ID,
        )

    # Same unattended dialogue tagging every script path gets; best-effort.
    try:
        from dialogue_intelligence import tag_video_dialogue
        await tag_video_dialogue(video_id, tenant_id)
    except Exception as e:  # noqa: BLE001
        logger.warning(
            "[user_script] accept_external_script: dialogue tagging failed for %s: %s",
            video_id, str(e)[:200],
        )

    return {
        "accepted": True,
        "verdict": grade.verdict,
        "violations": [],
        "warnings": warnings,
        "scenes": len(normalized),
        "status": new_status,
    }
