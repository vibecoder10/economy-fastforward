"""Static-documentary mode: detection + per-segment image sourcing.

A channel whose extracted identity says the format is static-image documentary
(``channel_profiles.channel_identity.visual_format`` — e.g. Designed vs Used:
archival photos held with slow Ken Burns pans, narration, no animation) gets
``videos.render_mode = 'static_docu'`` at creation. Those videos:

  * skip the animate stages entirely (their stage plan drops video+sound);
  * source ONE realistic representative image per scene instead of the
    ~36-frame coverage flow — never-built prototypes have no real footage, so
    the image is GENERATED from the segment's script (cheap: one image per
    vehicle/segment);
  * render via render_static.render_static_video (Remotion Ken Burns).
"""

import json
import re
import sys
import uuid
from pathlib import Path
from typing import Any, Optional

import httpx

from database import execute, fetch_all, fetch_one
from storage import upload_bytes

_PIPELINE_PATH = Path(__file__).resolve().parents[2] / "skills" / "video-pipeline"
if str(_PIPELINE_PATH) not in sys.path:
    sys.path.insert(0, str(_PIPELINE_PATH))

STATIC_RENDER_MODE = "static_docu"

# Fingerprints of a static-image documentary format in the extracted identity's
# free text. Deliberately conservative: only flip a channel to static mode when
# its own videos clearly are (a wrong yes silently disables animation).
_STATIC_MARKERS = ("static", "ken burns", "ken-burns", "still image", "photograph")
_MOTION_VETOES = ("animation", "animated", "3d render", "motion graphics heavy")


def is_static_visual_format(visual_format: Optional[dict]) -> bool:
    """Does this channel_identity.visual_format describe a static-image docu?"""
    if not isinstance(visual_format, dict):
        return False
    text = " ".join(
        str(visual_format.get(k) or "") for k in ("motion", "style", "segmentation")
    ).lower()
    if not any(m in text for m in _STATIC_MARKERS):
        return False
    motion = str(visual_format.get("motion") or "").lower()
    return not any(v in motion for v in _MOTION_VETOES)


async def static_mode_for_tenant(tenant_id: str) -> bool:
    """Should new videos for this tenant render as static documentaries?"""
    row = await fetch_one(
        "SELECT channel_identity FROM channel_profiles WHERE tenant_id=$1", tenant_id)
    ci = (row or {}).get("channel_identity")
    if isinstance(ci, str):
        try:
            ci = json.loads(ci)
        except (ValueError, TypeError):
            return False
    if not isinstance(ci, dict):
        return False
    return is_static_visual_format(ci.get("visual_format"))


# --- image sourcing -----------------------------------------------------------

_PROMPT_HEADER = """You write image-generation prompts for a static-image history documentary
(one photorealistic image per narration segment, held on screen with a slow pan).

For EACH numbered segment below, write ONE prompt for a single realistic
representative image of that segment's subject. Rules:
- Photorealistic archival documentary look: muted colors, film grain, sober
  institutional tone — like a period photograph or an official program photo.
  NO cartoon, NO infographic, NO text or labels in the image.
- Many subjects were never built. Depict a REALISTIC representation from the
  segment's description (a full-scale prototype in a proving ground, factory
  floor, or design bureau setting fits well). Never invent sci-fi styling.
- One clear subject, dramatic but plausible lighting, wide or medium framing
  that survives a slow pan (important detail away from the edges).
- 25-60 words each.

Channel look notes: {style_notes}

Reply with a JSON array only: [{{"scene": <n>, "prompt": "..."}}, ...]

SEGMENTS:
{segments}"""


def _parse_json_array(text: str) -> Optional[list]:
    m = re.search(r"\[.*\]", text or "", re.DOTALL)
    if not m:
        return None
    try:
        val = json.loads(m.group(0))
        return val if isinstance(val, list) else None
    except ValueError:
        return None


async def _scene_prompts(tenant_id: str, scenes: list[dict],
                         style_notes: str) -> dict[int, str]:
    """One Claude call -> {scene: image prompt}. Falls back to a scene-text
    template per scene if the model reply is unusable."""
    from kie_unified import get_text_client_for_tenant

    listing = "\n\n".join(
        f"[{s['scene']}] {(s['scene_text'] or '')[:700]}" for s in scenes)
    client = await get_text_client_for_tenant(tenant_id)
    kwargs: dict[str, Any] = {
        "prompt": _PROMPT_HEADER.format(style_notes=style_notes or "none", segments=listing),
        "max_tokens": 2400,
    }
    if type(client).__name__ == "AnthropicDirectClient":
        kwargs["model"] = "claude-sonnet-4-6"
    raw = await client.generate(**kwargs)
    out: dict[int, str] = {}
    for item in _parse_json_array(raw or "") or []:
        try:
            out[int(item["scene"])] = str(item["prompt"]).strip()
        except (KeyError, TypeError, ValueError):
            continue
    for s in scenes:  # backstop: every scene gets a prompt
        if s["scene"] not in out:
            out[s["scene"]] = (
                "Photorealistic archival documentary photograph, muted colors, "
                "film grain, sober period look, single clear subject: "
                + (s["scene_text"] or "")[:300]
            )
    return out


async def generate_static_images_for_video(video_id: str, tenant_id: str,
                                           progress=None) -> dict:
    """One realistic archival image per scene, stored as the scene's asset.

    The static analogue of generate_coverage_for_video: reads scripts, writes
    assets rows (generation_method='static_docu', image_index=1, hero_shot).
    Idempotent per scene — re-running replaces that scene's static image.
    """
    def _p(msg):
        if progress:
            try:
                progress(msg)
            except Exception:  # noqa: BLE001
                pass

    from shared.clients.image_client import ImageClient
    from vault import get_secret
    import os as _os

    v = await fetch_one(
        "SELECT id, video_title, COALESCE(aspect_ratio,'16:9') AS aspect, "
        "image_style_override FROM videos "
        "WHERE id=$1 AND tenant_id=$2 AND deleted_at IS NULL", video_id, tenant_id)
    if not v:
        return {"status": "failed", "error": "video not found"}
    scenes = await fetch_all(
        "SELECT scene, scene_text FROM scripts WHERE video_id=$1 AND tenant_id=$2 "
        "AND scene IS NOT NULL AND scene_text IS NOT NULL ORDER BY scene",
        video_id, tenant_id)
    if not scenes:
        return {"status": "failed", "error": "no scenes with text yet — write the script first"}

    _p("Writing one image prompt per segment…")
    prompts = await _scene_prompts(tenant_id, scenes, v["image_style_override"] or "")

    kie_key = await get_secret("kie_ai_api_key", tenant_id) or _os.getenv("KIE_AI_API_KEY")
    if not kie_key:
        return {"status": "failed", "error": "no image key on this workspace"}
    ic = ImageClient(api_key=kie_key)

    done, failed = 0, []
    for s in scenes:
        sc = s["scene"]
        _p(f"Segment {sc}/{len(scenes)}: generating the archival image…")
        res = await ic.generate_scene_image_gpt(prompts[sc], None, aspect_ratio=v["aspect"])
        url = (res or {}).get("url")
        if not url:
            failed.append(str(sc))
            continue
        async with httpx.AsyncClient(timeout=120.0) as c:
            r = await c.get(url, follow_redirects=True)
            r.raise_for_status()
            data = r.content
        durable = await upload_bytes(
            data, f"{video_id}/static/S{sc:02d}.png", "image/png", tenant_id)
        await execute(
            "DELETE FROM assets WHERE video_id=$1 AND tenant_id=$2 AND scene=$3 "
            "AND generation_method=$4", video_id, tenant_id, sc, STATIC_RENDER_MODE)
        await execute(
            "INSERT INTO assets (id, tenant_id, video_id, scene, image_index, "
            "sentence_index, sentence_text, image_prompt, shot_type, video_title, "
            "aspect_ratio, status, image_url, drive_image_url, hero_shot, "
            "generation_method) "
            "VALUES ($1,$2,$3,$4,1,1,$5,$6,'wide',$7,$8,'done',$9,$9,true,$10)",
            str(uuid.uuid4()), tenant_id, video_id, sc,
            (s["scene_text"] or "")[:500], prompts[sc][:1000],
            v["video_title"], v["aspect"], durable, STATIC_RENDER_MODE,
        )
        done += 1
    if not done:
        return {"status": "failed",
                "error": f"no images generated (scenes failed: {', '.join(failed)})"}
    msg = f"Generated {done}/{len(scenes)} segment images"
    if failed:
        msg += f" (failed: {', '.join(failed)})"
    return {"status": "completed", "message": msg}
