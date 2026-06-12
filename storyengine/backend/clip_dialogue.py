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
import json
import logging
import os
import re
import subprocess
import tempfile
from typing import Optional

from database import fetch_all

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
    """Grok direction for a speaking shot (validated live in the lip test)."""
    parts = [
        f'{(l.get("speaker") or "The character")} speaks with clear natural mouth '
        f'movement, saying: "{l["text"]}"'
        for l in lines
    ]
    spoken = ". Then ".join(parts)
    return (
        f"{spoken}. Expressive face, natural small gestures, gentle camera hold. "
        "Keep the characters, art style and scene exactly as shown in the image."
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


async def mux_voice(clip_bytes: bytes, voice_bytes_list: list) -> bytes:
    """Replace the clip's Grok-invented audio with the character line(s).

    No -shortest: the clip keeps its full length and the line simply ends —
    the renderer owns precise timing later.
    """
    def _sync() -> bytes:
        with tempfile.TemporaryDirectory() as td:
            clip = os.path.join(td, "clip.mp4")
            out = os.path.join(td, "out.mp4")
            with open(clip, "wb") as f:
                f.write(clip_bytes)
            voices = []
            for i, vb in enumerate(voice_bytes_list):
                vp = os.path.join(td, f"v{i}.mp3")
                with open(vp, "wb") as f:
                    f.write(vb)
                voices.append(vp)
            if len(voices) == 1:
                _run_ffmpeg(["-i", clip, "-i", voices[0], "-map", "0:v", "-map", "1:a",
                             "-c:v", "copy", "-c:a", "aac", out])
            else:
                inputs: list = []
                for vp in voices:
                    inputs += ["-i", vp]
                fc = "".join(f"[{i + 1}:a]" for i in range(len(voices))) + \
                     f"concat=n={len(voices)}:v=0:a=1[a]"
                _run_ffmpeg(["-i", clip, *inputs, "-filter_complex", fc,
                             "-map", "0:v", "-map", "[a]", "-c:v", "copy", "-c:a", "aac", out])
            with open(out, "rb") as f:
                return f.read()

    return await asyncio.to_thread(_sync)


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
