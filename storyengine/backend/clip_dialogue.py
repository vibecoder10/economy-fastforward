"""Dialogue-aware clip helpers — the 💬 cards SPEAK.

A card (assets row) whose sentence_text contains one of the scene's tagged
dialogue lines becomes a SPEAKING clip, generated audio-first: InfiniteTalk
(image_client.generate_talking_video) takes an image plus the segment's
ElevenLabs line and generates the mouth FROM the waveform — sync is inherent.
(The earlier Grok+mux approach guessed the timing and missed in both
directions; see lessons 2026-06-12 pt 8/9.)

THE IMAGE IS A SPEAKER CLOSE-UP, NOT THE FULL PANEL: on multi-character
panels the audio-driven models animate the most prominent face — Ryan
watched Tom mouth Lisa's line while Lisa stood frozen. So we locate the
named speaker with one cheap vision call, crop the panel around them
(a dialogue cut-in, standard shot grammar), and hand the single-subject
crop to the model: with one face in frame it cannot pick the wrong one.
Crops are cached on the dialogue segment (speaker_crop_url — which also
puts them on the media-proxy allowlist via dialogue_segments::text).

Narration cards stay silent motion clips; the renderer narrates over them.
Matching mirrors the frontend badge logic (VideoClipsTab.norm): the tagger
keeps spoken words verbatim, so normalized containment pairs lines with
cards without any extra model calls.
"""

import asyncio
import io
import json
import logging
import os
import re
import subprocess
import tempfile
from typing import Optional

from database import fetch_all, fetch_one, execute

logger = logging.getLogger(__name__)


def norm(s: Optional[str]) -> str:
    return re.sub(r"\s+", " ", re.sub(r"[^a-z0-9 ]+", " ", (s or "").lower())).strip()


async def load_dialogue_lines(video_id: str, tenant_id) -> dict:
    """scene -> ordered dialogue segments ({speaker, text, audio_url, duration})."""
    rows = await fetch_all(
        "SELECT scene, dialogue_segments FROM scripts WHERE video_id = $1 AND tenant_id = $2",
        video_id, tenant_id,
    )
    out: dict = {}
    for r in rows:
        raw = r.get("dialogue_segments")
        if isinstance(raw, str):
            try:
                raw = json.loads(raw)
            except ValueError:
                raw = None
        if not raw:
            continue
        lines = [s for s in raw if s.get("type") == "dialogue" and (s.get("text") or "").strip()]
        if lines:
            out[r["scene"]] = lines
    return out


def match_lines(sentence_text: Optional[str], scene_lines: Optional[list]) -> list:
    """Dialogue lines whose spoken words appear inside this card's sentence."""
    text = norm(sentence_text)
    if not text or not scene_lines:
        return []
    matched = []
    for line in scene_lines:
        lt = norm(line.get("text"))
        if lt and (lt in text or text in lt):
            matched.append(line)
    return matched


def speaking_prompt(lines: list) -> str:
    """Guidance for the audio-driven generator: WHO speaks, in what mood."""
    line = lines[0]
    speaker = line.get("speaker") or "The character"
    return (
        f'{speaker} speaks the line "{line["text"]}" with natural mouth movement '
        "and a matching expression. Other characters react subtly but do not "
        "talk. Keep the characters, art style and scene exactly as shown in the image."
    )


_DRIVE_ID = re.compile(r"[?&]id=([\w-]+)|/d/([\w-]+)")


def drive_file_id(url: Optional[str]) -> Optional[str]:
    m = _DRIVE_ID.search(url or "")
    return (m.group(1) or m.group(2)) if m else None


async def download_drive(url: Optional[str]) -> Optional[bytes]:
    """Authorized Drive download — public links degrade into HTML (lessons)."""
    fid = drive_file_id(url)
    if not fid:
        return None
    from routes.media import _download_via_drive_api
    try:
        return await asyncio.to_thread(_download_via_drive_api, fid)
    except Exception as e:
        logger.warning("drive download failed (%s): %s", fid, str(e)[:120])
        return None


async def locate_speaker(image_bytes: bytes, speaker: str, description: str,
                         tenant_id) -> Optional[tuple]:
    """One vision call: where is the named character in this panel?

    Returns (x, y, w, h) as fractions of the image, or None when the
    character can't be found (caller falls back to the full panel).
    """
    import base64 as _b64
    try:
        from PIL import Image
        img = Image.open(io.BytesIO(image_bytes))
        scale = min(1.0, 768 / max(img.size))
        small = img.resize((int(img.width * scale), int(img.height * scale)))
        buf = io.BytesIO()
        small.convert("RGB").save(buf, format="JPEG", quality=80)

        from routes.model_video import _call_claude, _resolve_claude_creds
        creds = await _resolve_claude_creds(str(tenant_id))
        if not creds:
            return None
        content = [
            {"type": "image", "source": {"type": "base64", "media_type": "image/jpeg",
                                         "data": _b64.b64encode(buf.getvalue()).decode()}},
            {"type": "text", "text": (
                f"Find the character {speaker} in this animated scene"
                + (f" ({description[:200]})" if description else "") + ". "
                "Give a box that tightly contains this character (head to feet if "
                "visible) as PERCENTAGES of the image: left, top, width, height. "
                "If the character is not in the image, answer NONE. "
                "End with exactly: FINAL: <left>,<top>,<width>,<height> or FINAL: NONE")},
        ]
        reply = await _call_claude(content, creds, tier="fast", max_tokens=400)
        m = re.search(r"FINAL:\s*([\d.]+)\s*,\s*([\d.]+)\s*,\s*([\d.]+)\s*,\s*([\d.]+)", reply or "")
        if not m:
            return None
        x, y, w, h = (float(v) / 100.0 for v in m.groups())
        if w < 0.03 or h < 0.03 or x >= 1 or y >= 1:
            return None
        return (max(0.0, x), max(0.0, y), min(w, 1.0), min(h, 1.0))
    except Exception as e:
        logger.warning("locate_speaker failed for %s: %s", speaker, str(e)[:120])
        return None


def crop_speaker(image_bytes: bytes, bbox: tuple, pad: float = 0.22,
                 min_px: int = 512) -> bytes:
    """Cut the dialogue close-up: speaker bbox + breathing room, upscaled if
    tiny (cartoon panels survive 2x fine)."""
    from PIL import Image
    img = Image.open(io.BytesIO(image_bytes)).convert("RGB")
    W, H = img.size
    x, y, w, h = bbox
    px, py = w * pad, h * pad
    left = max(0, int((x - px) * W))
    top = max(0, int((y - py) * H))
    right = min(W, int((x + w + px) * W))
    bottom = min(H, int((y + h + py) * H))
    crop = img.crop((left, top, right, bottom))
    if min(crop.size) < min_px:
        scale = min_px / min(crop.size)
        crop = crop.resize((int(crop.width * scale), int(crop.height * scale)), Image.LANCZOS)
    out = io.BytesIO()
    crop.save(out, format="PNG")
    return out.getvalue()


async def stash_speaker_crop(video_id: str, tenant_id, scene: int,
                             line_text: str, crop_url: str) -> None:
    """Cache the crop on its dialogue segment — reused on Redo, and being in
    dialogue_segments puts the file on the media-proxy allowlist."""
    row = await fetch_one(
        "SELECT id, dialogue_segments FROM scripts WHERE video_id = $1 AND tenant_id = $2 AND scene = $3",
        video_id, tenant_id, scene,
    )
    if not row:
        return
    raw = row.get("dialogue_segments")
    segs = json.loads(raw) if isinstance(raw, str) else (raw or [])
    target = norm(line_text)
    changed = False
    for s in segs:
        if s.get("type") == "dialogue" and norm(s.get("text")) == target:
            s["speaker_crop_url"] = crop_url
            changed = True
    if changed:
        await execute(
            "UPDATE scripts SET dialogue_segments = $1, updated_at = now() WHERE id = $2",
            json.dumps(segs), row["id"],
        )


def _run_ffmpeg(args: list) -> None:
    proc = subprocess.run(["ffmpeg", "-y", "-v", "error", *args], capture_output=True, timeout=120)
    if proc.returncode != 0:
        raise RuntimeError(f"ffmpeg failed: {proc.stderr.decode(errors='replace')[:300]}")


async def strip_audio(clip_bytes: bytes) -> bytes:
    """Silence a narration clip — Grok always bakes in invented audio."""
    def _sync() -> bytes:
        with tempfile.TemporaryDirectory() as td:
            clip = os.path.join(td, "clip.mp4")
            out = os.path.join(td, "out.mp4")
            with open(clip, "wb") as f:
                f.write(clip_bytes)
            _run_ffmpeg(["-i", clip, "-c:v", "copy", "-an", out])
            with open(out, "rb") as f:
                return f.read()

    return await asyncio.to_thread(_sync)
