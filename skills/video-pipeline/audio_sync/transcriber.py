"""
Whisper transcription via the OpenAI API.

Produces word-level timestamps for the entire narration audio file.
Uses the hosted OpenAI Whisper API exclusively — no local model.
"""

from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any

from dotenv import load_dotenv


def _find_and_load_env() -> None:
    """Walk up from this file to find and load the project .env."""
    current = Path(__file__).resolve().parent
    for _ in range(10):
        env_file = current / ".env"
        if env_file.exists():
            load_dotenv(env_file, override=True)
            return
        if current.parent == current:
            break
        current = current.parent


_find_and_load_env()


# ---------------------------------------------------------------------------
# Public types
# ---------------------------------------------------------------------------

class WordTimestamp:
    """A single transcribed word with start/end seconds."""

    __slots__ = ("word", "start", "end")

    def __init__(self, word: str, start: float, end: float) -> None:
        self.word = word
        self.start = start
        self.end = end

    def to_dict(self) -> dict:
        return {"word": self.word, "start": self.start, "end": self.end}

    def __repr__(self) -> str:
        return f"WordTimestamp({self.word!r}, {self.start:.2f}, {self.end:.2f})"


# ---------------------------------------------------------------------------
# OpenAI Whisper API transcription
# ---------------------------------------------------------------------------

def transcribe_api(audio_path: str) -> dict[str, Any]:
    """
    Transcribe audio via the OpenAI Whisper API (hosted, no GPU needed).

    Cost: ~$0.006/min of audio.  A 25-min video ~ $0.15.

    Requires ``OPENAI_API_KEY`` env var.

    Returns:
        Dict with ``words`` list of ``{word, start, end}`` dicts.
    """
    try:
        import openai
    except ImportError as exc:
        raise RuntimeError(
            "openai package not installed. Run `pip install openai`."
        ) from exc

    api_key = os.environ.get("OPENAI_API_KEY")
    if not api_key or api_key.startswith("sk-xxxxx"):
        raise RuntimeError(
            "OPENAI_API_KEY not configured. "
            "Set your real key in .env (project root) or as an environment variable."
        )

    client = openai.OpenAI(api_key=api_key)

    with open(audio_path, "rb") as f:
        result = client.audio.transcriptions.create(
            model="whisper-1",
            file=f,
            response_format="verbose_json",
            timestamp_granularities=["word"],
        )

    return result.model_dump() if hasattr(result, "model_dump") else dict(result)


# ---------------------------------------------------------------------------
# Word extraction
# ---------------------------------------------------------------------------

def extract_words(raw_result: dict[str, Any]) -> list[WordTimestamp]:
    """
    Normalise Whisper API output into a flat list of WordTimestamp objects.
    """
    words: list[WordTimestamp] = []

    # API format — flat list at top level
    if "words" in raw_result and isinstance(raw_result["words"], list):
        for w in raw_result["words"]:
            words.append(WordTimestamp(
                word=w.get("word", "").strip(),
                start=float(w.get("start", 0)),
                end=float(w.get("end", 0)),
            ))
        return words

    # Fallback: words nested in segments (older API response format)
    for segment in raw_result.get("segments", []):
        for w in segment.get("words", []):
            words.append(WordTimestamp(
                word=w.get("word", "").strip(),
                start=float(w.get("start", 0)),
                end=float(w.get("end", 0)),
            ))

    return words


# ---------------------------------------------------------------------------
# Persist / load helpers
# ---------------------------------------------------------------------------

def save_whisper_raw(raw_result: dict[str, Any], output_path: str | Path) -> Path:
    """Write the raw Whisper JSON to disk (backup)."""
    output_path = Path(output_path)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    with open(output_path, "w") as f:
        json.dump(raw_result, f, indent=2, default=str)
    return output_path


def load_whisper_raw(path: str | Path) -> dict[str, Any]:
    """Load a previously saved raw Whisper JSON."""
    with open(path) as f:
        return json.load(f)


# ---------------------------------------------------------------------------
# Main entry-point
# ---------------------------------------------------------------------------

def transcribe(
    audio_path: str,
    *,
    cache_dir: str | Path | None = None,
    **_kwargs,
) -> list[WordTimestamp]:
    """
    Transcribe audio via the OpenAI Whisper API and return word timestamps.

    If *cache_dir* is provided, the raw Whisper JSON is saved there as
    ``whisper_raw.json`` and subsequent calls with the same *cache_dir*
    will load from cache instead of re-transcribing.

    Args:
        audio_path: Path to the narration audio file.
        cache_dir: Optional directory for caching Whisper output.

    Returns:
        Flat list of WordTimestamp objects.
    """
    # Verify API key is available before doing anything
    api_key = os.environ.get("OPENAI_API_KEY", "")
    if not api_key or api_key.startswith("sk-xxxxx"):
        _find_and_load_env()
        api_key = os.environ.get("OPENAI_API_KEY", "")
    if not api_key or api_key.startswith("sk-xxxxx"):
        raise RuntimeError(
            "OPENAI_API_KEY not found. Cannot transcribe without the API key. "
            "Set it in your .env file at the project root."
        )

    # Check cache first
    if cache_dir is not None:
        cache_file = Path(cache_dir) / "whisper_raw.json"
        if cache_file.exists():
            raw = load_whisper_raw(cache_file)
            return extract_words(raw)

    # Transcribe via OpenAI Whisper API
    raw = transcribe_api(audio_path)

    # Cache the result
    if cache_dir is not None:
        save_whisper_raw(raw, Path(cache_dir) / "whisper_raw.json")

    return extract_words(raw)
