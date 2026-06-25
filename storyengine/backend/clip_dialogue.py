"""Dialogue-aware clip helpers — the 💬 cards SPEAK.

A card (assets row) whose sentence_text contains one of the scene's tagged
dialogue lines becomes a SPEAKING clip: Grok animates the FULL PANEL with a
speaking prompt (scene, motion, every character preserved), then the
segment's ElevenLabs line replaces Grok's invented audio with a small fixed
lead. Lip-sync is deliberately LOOSE — Ryan's call after touring the
alternatives (decisions.md 2026-06-12): per-clip alignment can't beat Grok's
self-timed performances, audio-driven models either animate the wrong face
on multi-character panels (InfiniteTalk full-panel) or destroy scene
continuity (portrait cut-ins), and Kie hosts no video lip-RETARGETING model.
Scene continuity outranks mouth precision in this format.

Narration cards stay silent motion clips; the renderer narrates over them.
Matching mirrors the frontend badge logic (VideoClipsTab.norm): the tagger
keeps spoken words verbatim, so normalized containment pairs lines with
cards without any extra model calls.
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

# Voice lead-in over a Grok speaking clip: characters rarely mouth words in
# the very first frames, and a voice that lands at-or-after the mouth reads
# far better than one that runs ahead of it.
DIALOGUE_VOICE_LEAD_SECONDS = 0.5


# --- Dynamic clip length for speaking shots ---------------------------------
# A speaking clip has to be long enough to hold the whole spoken line, or Grok
# cuts the line off mid-word at the clip's end. Grok speaks at roughly 2.8
# words/sec (measured: S-02.104 said 14 words in 5.0s). We size a touch slower
# so we never undershoot, then add a fixed buffer so the last word plus a beat
# of silence fits. Both knobs are env-tunable without a code change.
SPEAKING_WORDS_PER_SEC = float(os.getenv("GROK_WORDS_PER_SEC", "2.5"))
SPEECH_BUFFER_SECONDS = float(os.getenv("GROK_SPEECH_BUFFER", "1.0"))

# Coverage motion prompts embed the spoken line as: <Name> says <manner>: "line"
_SPOKEN_RE = re.compile(r'says\b[^:"\n]*:\s*"([^"]+)"', re.IGNORECASE)


def spoken_word_count(prompt_or_text: Optional[str]) -> int:
    """Words Grok will SPEAK in a prompt that embeds dialogue as
    `<Name> says <manner>: "line"`. Returns 0 for a motion-only (silent) shot."""
    return sum(len(s.split()) for s in _SPOKEN_RE.findall(prompt_or_text or ""))


def speech_seconds(words: int) -> float:
    """Seconds Grok needs to speak `words`, with headroom so nothing is cut."""
    if words <= 0:
        return 0.0
    return words / SPEAKING_WORDS_PER_SEC + SPEECH_BUFFER_SECONDS


def pick_clip_duration(need_seconds: float, durations: list) -> int:
    """Smallest available tier that holds `need_seconds`; the longest tier if
    none fit (a too-long line is better slightly clipped than missing tiers)."""
    tiers = sorted({int(d) for d in (durations or [6])})
    for d in tiers:
        if d + 0.25 >= need_seconds:
            return d
    return tiers[-1]


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
    """Dialogue lines whose spoken words appear inside this card's sentence.

    Sentence-level: a tagged line can span card boundaries (S1.3 carried
    'It is a baby bird.' while 'Something is wrong.' fell on the next card —
    whole-line matching missed it and Grok improvised different words), so a
    line matches when ANY of its sentences (3+ words) appears in the card.
    """
    text = norm(sentence_text)
    if not text or not scene_lines:
        return []
    matched = []
    for line in scene_lines:
        lt = norm(line.get("text"))
        if not lt:
            continue
        if lt in text or text in lt:
            matched.append(line)
            continue
        for sent in re.split(r"[.!?]+", line.get("text") or ""):
            ns = norm(sent)
            if ns and len(ns.split()) >= 3 and ns in text:
                matched.append(line)
                break
    return matched


# A dialogue line can span cards (sentence-level match_lines), so a speaking
# card may be a CUTAWAY where the speaker is off-screen — S1.4 is Tom's
# "Something is wrong." over a ground-level bird close-up. Naming the speaker
# summoned him: Grok walked the whole boy into frame (verified twice on live
# frames). Grok has the pixels, so IT judges visibility; we just forbid the
# summon. Inert when the speaker is actually in shot.
OFF_SCREEN_SPEAKER_RULE = (
    "STRICT: if the speaker is not visible in the image, their voice comes "
    "from OFF-SCREEN — never add them or any new person to the scene. Keep "
    "the framing and everything visible exactly as shown."
)


def native_speaking_prompt(lines: list, card_text: Optional[str]) -> str:
    """Grok-native voices: Grok speaks the lines itself, so the EXACT words
    go in the prompt — only the words this card actually covers (a line can
    span cards; feeding the whole line makes Grok say the neighbor card's
    half too)."""
    parts = []
    for l in lines:
        speaker = l.get("speaker") or "The character"
        # Use the sentences of this line that appear on THIS card.
        text = norm(card_text)
        covered = [s.strip() for s in re.split(r"(?<=[.!?])\s+", l.get("text") or "")
                   if s.strip() and norm(s) and norm(s) in text]
        words = " ".join(covered) if covered else l["text"]
        parts.append(f'{speaker} says exactly these words, clearly and in character: "{words}"')
    spoken = ". Then ".join(parts)
    return (
        f"{spoken}. The words must be spoken exactly as written — no other "
        "dialogue, no narration. Natural expression and small gestures. "
        + OFF_SCREEN_SPEAKER_RULE
    )


CUTAWAY_PREFIX = (
    "STRICT: this is a cutaway shot with NO PEOPLE. Never show a person, "
    "face or body — animate only the scene, objects or animal exactly as "
    "shown. At most a hand or foot may enter the frame edge. "
)
NO_NEW_PEOPLE_PREFIX = (
    "STRICT: do not add any person or character who is not already visible "
    "in the image. If someone is only implied at the frame edge (shoes, "
    "feet, a hand, a shadow), they stay exactly that — never walk them into "
    "frame, never reveal their face or body. "
)


def motion_guard(image_prompt: Optional[str], sentence_text: Optional[str],
                 cast_names: str) -> str:
    """People-rule prefix for a NON-SPEAKING card's motion prompt.

    Cutaway (no cast name anywhere in the shot text) → absolute NO PEOPLE.
    Everything else → nobody NEW. The weaker rule exists because the name
    check can't catch the S1.4 class: "Tom's sneakers at frame edge —
    implied presence without face" names Tom, yet Grok walked the whole boy
    into frame. Blank shot text (extraction rows with no prompt or
    sentence) is NO signal, not a no-cast signal — orphan panels must not
    get a NO PEOPLE directive over a doctor close-up.
    """
    shot_text = f"{image_prompt or ''} {sentence_text or ''}".lower()
    if not cast_names or not shot_text.strip():
        return NO_NEW_PEOPLE_PREFIX
    has_cast = any(n.strip() and n.strip().lower() in shot_text
                   for n in cast_names.split(","))
    return NO_NEW_PEOPLE_PREFIX if has_cast else CUTAWAY_PREFIX


def speaking_prompt(lines: list) -> str:
    """Grok direction for a full-scene speaking shot."""
    parts = [
        f'{(l.get("speaker") or "The character")} speaks with clear natural mouth '
        f'movement, saying: "{l["text"]}"'
        for l in lines
    ]
    spoken = ". Then ".join(parts)
    return (
        f"{spoken}. The character starts speaking right away. Expressive face, "
        "natural small gestures; other characters react subtly but do not talk. "
        "Keep the characters, art style and scene exactly as shown in the image. "
        + OFF_SCREEN_SPEAKER_RULE
    )


_DRIVE_ID = re.compile(r"[?&]id=([\w-]+)|/d/([\w-]+)")


async def download_voice(url: Optional[str]) -> Optional[bytes]:
    """Authorized Drive download — public links degrade into HTML (lessons)."""
    m = _DRIVE_ID.search(url or "")
    fid = (m.group(1) or m.group(2)) if m else None
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


async def mux_voice(clip_bytes: bytes, voice_bytes_list: list, delay_seconds: float = 0.0,
                    bed_gain: float = 0.0) -> bytes:
    """Lay the character line(s) over the clip.

    delay_seconds gives the voice its lead-in. bed_gain > 0 keeps the clip's
    ORIGINAL audio underneath at that volume — Grok's ambience (birdsong,
    garden air) stays as the bed instead of dead silence around the line.
    No -shortest: the clip keeps its full length; the renderer owns timing.
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
            line = f"{src}adelay={ms}:all=1[ln];" if ms > 0 else f"{src}anull[ln];"
            if bed_gain > 0:
                # duration=longest, NOT first: Grok sometimes returns a
                # near-empty audio stub and 'first' truncated the whole mix
                # to 0.05s (live finding — the line vanished).
                mix = (f"[0:a]volume={bed_gain}[bed];"
                       "[bed][ln]amix=inputs=2:duration=longest:normalize=0[a]")
            else:
                mix = "[ln]anull[a]"
            _run_ffmpeg(["-i", clip, *inputs, "-filter_complex", chain + line + mix,
                         "-map", "0:v", "-map", "[a]", "-c:v", "copy", "-c:a", "aac", out])
            with open(out, "rb") as f:
                return f.read()

    return await asyncio.to_thread(_sync)


async def duck_audio(clip_bytes: bytes, gain: float = 0.3) -> bytes:
    """Turn the clip's invented audio into a quiet ambience bed.

    Full strip left narration clips DEAD silent ('no background sounds' —
    Ryan); Grok's birdsong/garden air at low volume reads alive, and the
    renderer mixes real narration and music over it later.
    """
    def _sync() -> bytes:
        with tempfile.TemporaryDirectory() as td:
            clip = os.path.join(td, "clip.mp4")
            out = os.path.join(td, "out.mp4")
            with open(clip, "wb") as f:
                f.write(clip_bytes)
            _run_ffmpeg(["-i", clip, "-filter_complex", f"[0:a]volume={gain}[a]",
                         "-map", "0:v", "-map", "[a]", "-c:v", "copy", "-c:a", "aac", out])
            with open(out, "rb") as f:
                return f.read()

    return await asyncio.to_thread(_sync)
