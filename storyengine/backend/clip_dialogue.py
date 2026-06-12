"""Dialogue-aware clip helpers — the 💬 cards SPEAK.

A card (assets row) whose sentence_text contains one of the scene's tagged
dialogue lines becomes a SPEAKING clip: the Grok prompt directs the character
to mouth the line, and the segment's ElevenLabs voice (synthesized by
dialogue_voice) replaces Grok's invented audio — the approved recipe from the
lisa-dialogue-test (decisions.md 2026-06-12). Narration cards stay silent
motion clips; the renderer lays real narration over them later.

Matching mirrors the frontend badge logic (VideoClipsTab.norm): the tagger
keeps spoken words verbatim, so normalized containment pairs lines with cards
without any extra model calls.
"""

import asyncio
import base64
import json
import logging
import os
import re
import subprocess
import tempfile
from typing import Optional

from database import fetch_all

logger = logging.getLogger(__name__)

# When onset detection fails, lead the voice in by this much — characters
# almost never mouth words in Grok's very first frames.
DEFAULT_SPEECH_LEAD_SECONDS = 0.8


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
    """Grok direction for a speaking shot (validated live in the lip test)."""
    parts = [
        f'{(l.get("speaker") or "The character")} speaks with clear natural mouth '
        f'movement, saying: "{l["text"]}"'
        for l in lines
    ]
    spoken = ". Then ".join(parts)
    return (
        f"{spoken}. The character starts speaking right away. Expressive face, "
        "natural small gestures, gentle camera hold. Keep the characters, art "
        "style and scene exactly as shown in the image."
    )


_DRIVE_ID = re.compile(r"[?&]id=([\w-]+)|/d/([\w-]+)")


def _drive_file_id(url: Optional[str]) -> Optional[str]:
    m = _DRIVE_ID.search(url or "")
    return (m.group(1) or m.group(2)) if m else None


async def download_voice(url: Optional[str]) -> Optional[bytes]:
    """Authorized Drive download — public links degrade into HTML (lessons)."""
    fid = _drive_file_id(url)
    if not fid:
        return None
    from routes.media import _download_via_drive_api
    try:
        return await asyncio.to_thread(_download_via_drive_api, fid)
    except Exception as e:
        logger.warning("voice download failed (%s): %s", fid, str(e)[:120])
        return None


def _run_ffmpeg(args: list) -> None:
    proc = subprocess.run(["ffmpeg", "-y", "-v", "error", *args], capture_output=True, timeout=120)
    if proc.returncode != 0:
        raise RuntimeError(f"ffmpeg failed: {proc.stderr.decode(errors='replace')[:300]}")


async def mux_voice(clip_bytes: bytes, voice_bytes_list: list, delay_seconds: float = 0.0) -> bytes:
    """Replace the clip's Grok-invented audio with the character line(s).

    delay_seconds shifts the voice to when the mouth actually starts moving
    (Grok decides when the character speaks — sometimes after walking them
    into frame). No -shortest: the clip keeps its full length and the line
    simply ends — the renderer owns precise timing later.
    """
    def _sync() -> bytes:
        with tempfile.TemporaryDirectory() as td:
            clip = os.path.join(td, "clip.mp4")
            out = os.path.join(td, "out.mp4")
            with open(clip, "wb") as f:
                f.write(clip_bytes)
            inputs: list = []
            for i, vb in enumerate(voice_bytes_list):
                vp = os.path.join(td, f"v{i}.mp3")
                with open(vp, "wb") as f:
                    f.write(vb)
                inputs += ["-i", vp]
            n = len(voice_bytes_list)
            if n == 1:
                src = "[1:a]"
                chain = ""
            else:
                src = "[c]"
                chain = "".join(f"[{i + 1}:a]" for i in range(n)) + f"concat=n={n}:v=0:a=1[c];"
            ms = int(round(max(0.0, delay_seconds) * 1000))
            tail = f"{src}adelay={ms}:all=1[a]" if ms > 0 else f"{src}anull[a]"
            _run_ffmpeg(["-i", clip, *inputs, "-filter_complex", chain + tail,
                         "-map", "0:v", "-map", "[a]", "-c:v", "copy", "-c:a", "aac", out])
            with open(out, "rb") as f:
                return f.read()

    return await asyncio.to_thread(_sync)


def _extract_onset_frames(clip_bytes: bytes, fps: float = 2.0, max_frames: int = 10,
                          width: int = 320) -> list:
    """Timestamped small JPEGs from the clip's first seconds, for vision."""
    with tempfile.TemporaryDirectory() as td:
        clip = os.path.join(td, "c.mp4")
        with open(clip, "wb") as f:
            f.write(clip_bytes)
        pattern = os.path.join(td, "f%03d.jpg")
        _run_ffmpeg(["-i", clip, "-vf", f"fps={fps},scale={width}:-2",
                     "-frames:v", str(max_frames), "-q:v", "5", pattern])
        out = []
        for i in range(1, max_frames + 1):
            p = os.path.join(td, f"f{i:03d}.jpg")
            if os.path.exists(p):
                with open(p, "rb") as f:
                    out.append(((i - 1) / fps, f.read()))
        return out


async def detect_speech_onset(clip_bytes: bytes, speaker: str, tenant_id,
                              clip_seconds: float = 6.0) -> Optional[float]:
    """Watch the clip: at which second does the speaker's mouth start talking?

    Grok times the speech itself — S2.1 walked Lisa into frame for ~2s while
    her line played over an empty shot. One cheap Haiku-vision pass per
    dialogue clip aligns the mux to the actual mouth movement instead of
    guessing a fixed offset. Returns None on any failure (caller falls back
    to DEFAULT_SPEECH_LEAD_SECONDS).
    """
    try:
        frames = await asyncio.to_thread(_extract_onset_frames, clip_bytes)
        if not frames:
            return None
        from routes.model_video import _call_claude, _resolve_claude_creds
        creds = await _resolve_claude_creds(str(tenant_id))
        if not creds:
            return None
        content: list = []
        for t, jb in frames:
            content.append({"type": "text", "text": f"t={t:.1f}s"})
            content.append({"type": "image", "source": {
                "type": "base64", "media_type": "image/jpeg",
                "data": base64.b64encode(jb).decode()}})
        content.append({"type": "text", "text": (
            f"These are timestamped frames from an animated clip in which {speaker} "
            f"speaks a line out loud. I need the moment {speaker}'s MOUTH starts the "
            "line, to sync audio.\n\n"
            f"For each frame, state {speaker}'s mouth: not-visible / closed / open-talking.\n"
            "Rules:\n"
            f"- Running, entering the frame, or reacting with a closed mouth is NOT talking.\n"
            "- Only a clearly OPEN mouth, as if mid-word, counts.\n"
            "- The character usually settles into place BEFORE speaking — when torn "
            "between two frames, pick the LATER one.\n"
            f"- If {speaker} is already mid-word in the earliest frames, answer 0.\n\n"
            "After the per-frame list, end with exactly: FINAL: <number of seconds>")})
        reply = await _call_claude(content, creds, tier="fast", max_tokens=800)
        m = re.search(r"FINAL:\s*([0-9]+(?:\.[0-9]+)?)", reply or "")
        if not m:
            return None
        onset = float(m.group(1))
        return onset if 0 <= onset <= clip_seconds else None
    except Exception as e:
        logger.warning("speech onset detection failed: %s", str(e)[:150])
        return None


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
