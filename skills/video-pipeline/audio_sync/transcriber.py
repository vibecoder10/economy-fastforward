"""
Whisper transcription — local model or OpenAI API.

Produces word-level timestamps for the entire narration audio file.
"""

from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any

from .config import DEFAULT_WHISPER_MODEL


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
# Local Whisper transcription
# ---------------------------------------------------------------------------

def transcribe_local(
    audio_path: str,
    model_size: str = DEFAULT_WHISPER_MODEL,
) -> dict[str, Any]:
    """
    Transcribe audio with the local ``openai-whisper`` package.

    Args:
        audio_path: Path to .mp3 / .wav narration file.
        model_size: One of ``tiny``, ``base``, ``small``, ``medium``, ``large``.

    Returns:
        Raw Whisper result dict (segments + word timestamps).
    """
    try:
        import whisper  # type: ignore[import-untyped]
    except ImportError as exc:
        raise RuntimeError(
            "Local whisper not installed. "
            "Run `pip install openai-whisper` or use transcribe_api()."
        ) from exc

    model = whisper.load_model(model_size)
    result = model.transcribe(
        audio_path,
        word_timestamps=True,
        language="en",
        condition_on_previous_text=True,
    )
    return result


# ---------------------------------------------------------------------------
# OpenAI Whisper API transcription
# ---------------------------------------------------------------------------

def transcribe_api(audio_path: str) -> dict[str, Any]:
    """
    Transcribe audio via the OpenAI Whisper API (hosted, no GPU needed).

    Cost: ~$0.006/min of audio.  A 25-min video ≈ $0.15.

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

    client = openai.OpenAI()

    with open(audio_path, "rb") as f:
        result = client.audio.transcriptions.create(
            model="whisper-1",
            file=f,
            response_format="verbose_json",
            timestamp_granularities=["word"],
        )

    return result.model_dump() if hasattr(result, "model_dump") else dict(result)


# ---------------------------------------------------------------------------
# Unified extraction
# ---------------------------------------------------------------------------

def extract_words(raw_result: dict[str, Any]) -> list[WordTimestamp]:
    """
    Normalise Whisper output (local or API) into a flat list of
    :class:`WordTimestamp` objects.

    Local Whisper nests words inside ``segments[].words[]``.
    The API returns a flat ``words[]`` list at top level.
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

    # Local whisper format — words nested in segments
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
# Convenience entry-point
# ---------------------------------------------------------------------------

def transcribe(
    audio_path: str,
    *,
    use_api: bool = False,
    model_size: str = DEFAULT_WHISPER_MODEL,
    cache_dir: str | Path | None = None,
) -> list[WordTimestamp]:
    """
    High-level entry point: transcribe audio and return word timestamps.

    If *cache_dir* is provided, the raw Whisper JSON is saved there as
    ``whisper_raw.json`` and subsequent calls with the same *cache_dir*
    will load from cache instead of re-transcribing.

    Args:
        audio_path: Path to the narration audio file.
        use_api: If ``True``, use the OpenAI hosted API instead of a
            local model.
        model_size: Local model size (ignored when *use_api* is ``True``).
        cache_dir: Optional directory for caching Whisper output.

    Returns:
        Flat list of :class:`WordTimestamp` objects.
    """
    # Check cache
    if cache_dir is not None:
        cache_file = Path(cache_dir) / "whisper_raw.json"
        if cache_file.exists():
            raw = load_whisper_raw(cache_file)
            return extract_words(raw)

    # Transcribe — prefer API when OPENAI_API_KEY is available
    if use_api or os.environ.get("OPENAI_API_KEY"):
        raw = transcribe_api(audio_path)
    else:
        raw = transcribe_local(audio_path, model_size=model_size)

    # Cache
    if cache_dir is not None:
        save_whisper_raw(raw, Path(cache_dir) / "whisper_raw.json")

    return extract_words(raw)
