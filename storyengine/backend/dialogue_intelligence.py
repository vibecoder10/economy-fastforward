"""Dialogue intelligence — detect and tag performed character dialogue.

The north-star is unattended channel automation: some reference channels
perform character dialogue (kids' animation: 'Lisa says: "Oh no!"'), others
are pure voiceover essays. Nothing here is a manual flag — a Claude pass
decides per video, and only dialogue-mode videos get the performance
treatment (narrator pauses, character lines voiced separately, Grok lip
movement). Narration-only channels flow through completely unchanged.

Persists:
  videos.dialogue_mode           'character_dialogue' | 'narration_only'
  scripts.dialogue_segments      ordered [{type, speaker?, text, ...}] per scene
  video_characters.voice_name    Kie/ElevenLabs roster voice cast per character
"""

import json
import logging
from typing import Optional

from database import fetch_all, fetch_one, execute

logger = logging.getLogger(__name__)

# U3 — voice-less pipeline flow for dialogue-format videos (PocoAPoco shape).
# Auto-skip fires only when the script is MAJORITY performed dialogue by word
# share: a narrated documentary that merely quotes a source line or two (DvsU
# shape) must never cross this bar, even though it's tagged
# dialogue_mode='character_dialogue' for those quoted lines. 0.8 keeps a
# couple of narrator sentences (title card, closing beat) from disqualifying
# a true two-hander scene while still holding a hard line against
# mostly-narrated content.
DIALOGUE_MAJORITY_THRESHOLD = 0.8


def _parse_stage_list(val) -> Optional[list]:
    """Parse the pipeline_stages JSONB column — asyncpg may hand it back as a
    list or a JSON string depending on codecs. Local copy of
    routes.videos._parse_stage_plan's logic (kept import-free here to avoid a
    routes -> service circular import)."""
    if val is None:
        return None
    if isinstance(val, list):
        return val or None
    if isinstance(val, str):
        try:
            result = json.loads(val)
            return result if isinstance(result, list) and result else None
        except (json.JSONDecodeError, ValueError):
            return None
    return None

# Kie's ElevenLabs roster (docs.kie.ai/market/elevenlabs/text-to-speech-
# multilingual-v2): the API takes the voice ID; off-roster ids are rejected.
# Curated character-casting subset — preview any voice at
# https://static.aiquickdraw.com/elevenlabs/voice/<id>.mp3
VOICE_ROSTER = [
    {"name": "Finn",     "id": "vBKc2FfBKJfcZNyEt1n6", "description": "Youthful, eager, energetic — boy/young male"},
    {"name": "Kuon",     "id": "B8gJV1IhpuegLxdpXFOE", "description": "Cheerful, clear and steady — young male"},
    {"name": "Emma",     "id": "pPdl9cQBQq4p6mRkZy2Z", "description": "Adorable and upbeat — young girl"},
    {"name": "Hope",     "id": "uYXf8XasLslADfZ2MB4u", "description": "Bubbly and girly — girl/teen"},
    {"name": "Brittney", "id": "kPzsL2i3teMYv0FxEYQ6", "description": "Fun, youthful, informative — young woman"},
    {"name": "Tiffany",  "id": "6aDn1KB0hjpdcocrUkmq", "description": "Natural and welcoming — warm motherly woman"},
    {"name": "Allison",  "id": "1wGbFxmAM3Fgw63G1zZJ", "description": "Calm and soothing — gentle adult woman"},
    {"name": "Bella",    "id": "hpp4J3VqNfWAUOO0d1Us", "description": "Professional, bright, warm — doctor/expert woman"},
    {"name": "Cassidy",  "id": "56AoDkrOh6qfVPDXZ7Pt", "description": "Crisp, direct, clear — professional woman"},
    {"name": "Brian",    "id": "nPczCjzI2devNBz1zQrb", "description": "Deep, resonant, comforting — father-type man"},
    {"name": "Mark",     "id": "1SM7GgM6IMuvQlz2BwM3", "description": "Casual, relaxed, light — everyday adult man"},
    {"name": "Benjamin", "id": "LruHrtVF6PSyGItzMNHS", "description": "Deep, warm, calming — older man"},
    {"name": "Marshal",  "id": "nzeAacJi50IvxcyDnMXa", "description": "Friendly, funny professor — quirky teacher"},
]
VOICE_ID_BY_NAME = {v["name"]: v["id"] for v in VOICE_ROSTER}


async def _claude(prompt: str, tenant_id, tier: str = "fast", max_tokens: int = 4000) -> str:
    from routes.model_video import _call_claude, _resolve_claude_creds
    creds = await _resolve_claude_creds(str(tenant_id))
    return await _call_claude(prompt, creds, tier=tier, max_tokens=max_tokens)


def _parse_json(text: str) -> dict:
    """Extract the first JSON object from a model reply."""
    start = text.find("{")
    end = text.rfind("}")
    if start == -1 or end <= start:
        raise ValueError(f"No JSON in reply: {text[:200]}")
    return json.loads(text[start:end + 1])


async def detect_dialogue_mode(script_text: str, tenant_id) -> str:
    """One smart look at the whole script: performed dialogue or pure voiceover?"""
    reply = await _claude(
        "You analyze YouTube scripts for a video automation pipeline.\n\n"
        "Decide whether this script PERFORMS character dialogue — characters who "
        "speak lines that should be acted on screen (e.g. attributed quotes like "
        "'Lisa says: \"Oh no!\"', back-and-forth conversation) — or whether it is "
        "a pure narrator/voiceover script (essay, documentary, listicle) where any "
        "quotes are just the narrator quoting sources.\n\n"
        f"SCRIPT:\n{script_text[:12000]}\n\n"
        'Reply with ONLY JSON: {"dialogue_mode": "character_dialogue" | "narration_only", "reason": "<one sentence>"}',
        tenant_id, tier="smart", max_tokens=300,
    )
    mode = _parse_json(reply).get("dialogue_mode", "narration_only")
    return mode if mode in ("character_dialogue", "narration_only") else "narration_only"


async def segment_scene(scene_text: str, cast_names: list[str], tenant_id) -> list[dict]:
    """Split one scene into an ordered performance timeline.

    Dialogue segments carry ONLY the spoken line (the attribution phrase
    'Lisa says:' is dropped — the video shows Lisa speaking instead).
    Everything else stays narration, words preserved verbatim.
    """
    reply = await _claude(
        "Split this video scene into an ORDERED performance timeline for a "
        "narrator + on-screen speaking characters.\n\n"
        "Rules:\n"
        "- type 'dialogue': a line a character speaks out loud. text = the spoken "
        "words ONLY (no quotes, no 'X says'). speaker = the character's name"
        + (f" (cast: {', '.join(cast_names)})" if cast_names else "")
        + ". Infer the speaker from context when the attribution is implicit.\n"
        "- The attribution phrase itself ('Lisa says:', 'asks Tom') is DROPPED — "
        "it appears in neither narration nor dialogue.\n"
        "- type 'narration': every other sentence, VERBATIM — do not rewrite, "
        "merge, reorder or summarize anything.\n"
        "- Preserve the original order exactly.\n\n"
        f"SCENE:\n{scene_text}\n\n"
        'Reply with ONLY JSON: {"segments": [{"type": "narration", "text": "..."}, '
        '{"type": "dialogue", "speaker": "Lisa", "text": "..."}]}',
        tenant_id, tier="smart", max_tokens=4000,
    )
    segments = _parse_json(reply).get("segments", [])
    cleaned = []
    for seg in segments:
        text = (seg.get("text") or "").strip()
        if not text:
            continue
        entry = {"type": "dialogue" if seg.get("type") == "dialogue" else "narration", "text": text}
        if entry["type"] == "dialogue":
            entry["speaker"] = (seg.get("speaker") or "").strip() or "Narrator"
        cleaned.append(entry)
    if not cleaned:
        raise ValueError("Segmentation returned no segments")
    # Sanity: the timeline should retain most of the scene's words (attributions
    # legitimately disappear, so ~60% floor rather than equality).
    if sum(len(s["text"].split()) for s in cleaned) < 0.6 * max(1, len(scene_text.split())):
        raise ValueError("Segmentation lost too much of the scene text")
    return cleaned


async def _revert_auto_skip(video: dict, video_id: str, result: dict) -> None:
    """P5 fix: undo what THIS detector set, when its own conclusion no
    longer supports it.

    skip_voice_source (migration 116) tracks provenance. Only a row this
    detector itself flipped to true ('auto') is eligible to flip back —
    a creator's explicit skip (GuidedNextStep's button, PATCH
    dialogue_audio='grok_native', a reduced create-form stage plan — all
    stamped 'manual') and any legacy row (source NULL, pre-dates this
    column) are never touched here.
    """
    if not video.get("skip_voice") or video.get("skip_voice_source") != "auto":
        return
    await execute(
        "UPDATE videos SET skip_voice = false, skip_voice_source = NULL, updated_at = now() WHERE id = $1",
        video_id,
    )
    result["voice_auto_restored"] = True


async def tag_video_dialogue(video_id: str, tenant_id) -> dict:
    """The full intelligence pass: detect mode, then tag every scene.

    Idempotent and safe to re-run; narration-only videos just get the mode
    stamp and are otherwise untouched.

    U3: for a video that turns out MAJORITY performed dialogue (see
    DIALOGUE_MAJORITY_THRESHOLD — PocoAPoco shape, not a narrated documentary
    that merely quotes a line or two), also auto-sets skip_voice=true (and
    skip_voice_source='auto') in the same pass. Clip generation already
    auto-chains the per-segment TTS/STS that render's clock needs
    (pipeline_executor.py run_dialogue_voice auto-chain during Animate)
    whenever a scene is unvoiced, so the separate Script&Voice "Generate
    Voice" step is redundant for this shape. Guarded: never for static_docu
    (render_mode or tenant static format — voice IS the narration there),
    and never overrides a creator who explicitly kept 'voice' in this
    video's pipeline_stages.

    P5: the auto-set is now BIDIRECTIONAL with this same detector's own
    conclusion. If a later pass on this video (script regenerated into
    something narration-heavy, say) concludes it no longer qualifies —
    mode != character_dialogue, or dialogue_share drops back under the
    majority threshold — and skip_voice was set by THIS detector
    (skip_voice_source == 'auto'), it gets flipped back to false so voice
    (and the character_dialogue-gated Animate auto-chain, and render) work
    again without a manual fix. A creator's own explicit skip
    (skip_voice_source == 'manual', or a legacy NULL row) is never touched.
    """
    video = await fetch_one(
        "SELECT id, script, dialogue_audio, render_mode, skip_voice, skip_voice_source, pipeline_stages "
        "FROM videos WHERE id = $1 AND tenant_id = $2",
        video_id, tenant_id,
    )
    if not video or not (video.get("script") or "").strip():
        raise ValueError("No script to analyze — write the script first.")

    mode = await detect_dialogue_mode(video["script"], tenant_id)
    await execute(
        "UPDATE videos SET dialogue_mode = $1, updated_at = now() WHERE id = $2",
        mode, video_id,
    )
    if mode != "character_dialogue":
        result = {"dialogue_mode": mode, "scenes_tagged": 0}
        await _revert_auto_skip(video, video_id, result)
        return result

    cast_rows = await fetch_all(
        "SELECT name FROM video_characters WHERE video_id = $1 ORDER BY sort",
        video_id,
    )
    cast_names = [r["name"] for r in cast_rows]

    scenes = await fetch_all(
        "SELECT id, scene, scene_text FROM scripts WHERE video_id = $1 AND tenant_id = $2 ORDER BY scene",
        video_id, tenant_id,
    )
    tagged = 0
    dialogue_lines = 0
    dialogue_words = 0
    total_words = 0
    for sc in scenes:
        text = (sc.get("scene_text") or "").strip()
        if not text:
            continue
        segments = await segment_scene(text, cast_names, tenant_id)
        await execute(
            "UPDATE scripts SET dialogue_segments = $1, updated_at = now() WHERE id = $2",
            json.dumps(segments), sc["id"],
        )
        tagged += 1
        for s in segments:
            words = len(s["text"].split())
            total_words += words
            if s["type"] == "dialogue":
                dialogue_lines += 1
                dialogue_words += words

    result = {"dialogue_mode": mode, "scenes_tagged": tagged, "dialogue_lines": dialogue_lines}

    # Fail-safe: no segments at all (nothing tagged, or every scene came back
    # empty) means we have no evidence this is majority-dialogue — keep voice
    # rather than guess.
    if total_words == 0:
        return result

    dialogue_share = dialogue_words / total_words
    result["dialogue_share"] = dialogue_share
    if dialogue_share < DIALOGUE_MAJORITY_THRESHOLD:
        await _revert_auto_skip(video, video_id, result)
        return result

    if video.get("skip_voice"):
        return result  # already skipped and still qualifies — nothing to flip

    from static_docu import static_mode_for_tenant, STATIC_RENDER_MODE
    if (video.get("render_mode") or "") == STATIC_RENDER_MODE:
        return result
    try:
        if await static_mode_for_tenant(tenant_id):
            return result
    except Exception:  # noqa: BLE001 — detection must never block tagging
        return result

    stages = _parse_stage_list(video.get("pipeline_stages"))
    if stages and "voice" in stages:
        return result  # creator explicitly kept the voice stage — don't override

    await execute(
        "UPDATE videos SET skip_voice = true, skip_voice_source = 'auto', updated_at = now() WHERE id = $1",
        video_id,
    )
    result["voice_auto_skipped"] = True
    return result


async def cast_character_voices(video_id: str, tenant_id) -> dict:
    """Assign a stable ElevenLabs roster voice to each cast member.

    The voice stays with the character for the whole video (and the saved
    project cast), so Lisa sounds like Lisa in every clip. Stores the voice
    ID (what the Kie API takes) in video_characters.voice_name.
    """
    chars = await fetch_all(
        "SELECT id, name, description, voice_name FROM video_characters WHERE video_id = $1 ORDER BY sort",
        video_id,
    )
    todo = [c for c in chars if not c.get("voice_name")]
    if not todo:
        return {"cast": 0, "casting": {}}

    # The narrator's voice is off-limits for characters — a character who
    # shares it is indistinguishable from the narrator in the turn-taking
    # timeline (live finding: Tom was cast as Mark = the narration voice).
    narrator_row = await fetch_one(
        "SELECT voice_id FROM scripts WHERE video_id = $1 AND voice_id IS NOT NULL ORDER BY scene LIMIT 1",
        video_id,
    )
    narrator_voice = ((narrator_row or {}).get("voice_id") or "").strip()
    roster = [v for v in VOICE_ROSTER if v["id"] != narrator_voice] or VOICE_ROSTER
    roster_ids = {v["name"]: v["id"] for v in roster}

    reply = await _claude(
        "Cast voices for an animated video. For each CHARACTER pick the single "
        "best-fitting VOICE from the roster (match age, gender, energy). Voices "
        "may repeat only if unavoidable.\n\n"
        "CHARACTERS:\n" + "\n".join(f"- {c['name']}: {(c.get('description') or '')[:200]}" for c in todo)
        + "\n\nVOICE ROSTER:\n" + "\n".join(f"- {v['name']}: {v['description']}" for v in roster)
        + '\n\nReply with ONLY JSON: {"casting": [{"character": "...", "voice": "<roster name>"}]}',
        tenant_id, tier="smart", max_tokens=600,
    )
    casting = {c["character"]: c["voice"] for c in _parse_json(reply).get("casting", [])}
    count = 0
    for c in todo:
        voice_id = roster_ids.get(casting.get(c["name"], ""))
        if voice_id:
            await execute(
                "UPDATE video_characters SET voice_name = $1 WHERE id = $2",
                voice_id, c["id"],
            )
            count += 1
    return {"cast": count, "casting": casting}
