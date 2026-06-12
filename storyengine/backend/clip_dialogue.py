"""Dialogue-aware clip helpers — the 💬 cards SPEAK.

A card (assets row) whose sentence_text contains one of the scene's tagged
dialogue lines becomes a SPEAKING clip, generated audio-first: InfiniteTalk
(image_client.generate_talking_video) takes the panel image plus the
segment's ElevenLabs line and generates the mouth FROM the waveform — sync
is inherent. (The earlier Grok+mux approach guessed the timing and missed in
both directions; see lessons 2026-06-12 pt 8/9.) Narration cards stay silent
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
    """Guidance for the audio-driven generator: WHO speaks, in what mood."""
    line = lines[0]
    speaker = line.get("speaker") or "The character"
    return (
        f'{speaker} speaks the line "{line["text"]}" with natural mouth movement '
        "and a matching expression. Other characters react subtly but do not "
        "talk. Keep the characters, art style and scene exactly as shown in the image."
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
