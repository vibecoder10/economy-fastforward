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


def _load_openai_key() -> None:
    """Find and load OPENAI_API_KEY from .env files.

    Searches for .env files in multiple locations, tries dotenv first,
    then falls back to manual parsing. Looks for both .env and
    .env.production files.
    """
    # Already set and valid? Skip.
    existing = os.environ.get("OPENAI_API_KEY", "")
    if existing and not existing.startswith("sk-xxxxx"):
        return

    # Collect candidate .env file paths
    candidates: list[Path] = []
    current = Path(__file__).resolve().parent
    for _ in range(10):
        candidates.append(current / ".env")
        candidates.append(current / ".env.production")
        if current.parent == current:
            break
        current = current.parent

    # Also check common deployment paths
    for extra in [
        Path.home() / ".env",
        Path("/home/clawd/projects/economy-fastforward/.env"),
        Path("/home/clawd/.env"),
    ]:
        candidates.append(extra)

    # Try dotenv on each candidate
    for env_file in candidates:
        if env_file.exists():
            try:
                load_dotenv(env_file, override=True)
                key = os.environ.get("OPENAI_API_KEY", "")
                if key and not key.startswith("sk-xxxxx"):
                    return
            except Exception:
                pass

    # Dotenv failed — try manual parse on each candidate
    for env_file in candidates:
        if not env_file.exists():
            continue
        try:
            for line in env_file.read_text().splitlines():
                line = line.strip()
                if line.startswith("#") or "=" not in line:
                    continue
                k, _, v = line.partition("=")
                if k.strip() == "OPENAI_API_KEY":
                    v = v.strip().strip("'").strip('"')
                    if v and not v.startswith("sk-xxxxx"):
                        os.environ["OPENAI_API_KEY"] = v
                        return
        except Exception:
            continue


_load_openai_key()


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
    # Ensure API key is available
    _load_openai_key()
    api_key = os.environ.get("OPENAI_API_KEY", "")
    if not api_key or api_key.startswith("sk-xxxxx"):
        # Build diagnostic info
        diag_lines = [
            "OPENAI_API_KEY not found or still set to placeholder.",
            f"  Searched from: {Path(__file__).resolve()}",
            f"  Home dir: {Path.home()}",
            f"  CWD: {Path.cwd()}",
        ]
        # Show which .env files exist and what they contain for this key
        project_env = Path(__file__).resolve().parent.parent.parent.parent / ".env"
        for p in [project_env, Path.home() / ".env"]:
            if p.exists():
                try:
                    for line in p.read_text().splitlines():
                        if "OPENAI_API_KEY" in line and not line.strip().startswith("#"):
                            val = line.partition("=")[2].strip()
                            masked = val[:8] + "..." if len(val) > 8 else val
                            diag_lines.append(f"  Found in {p}: {masked}")
                except Exception:
                    pass
        diag_lines.append("")
        diag_lines.append("FIX: SSH into the VPS and run:")
        diag_lines.append(f"  nano {project_env}")
        diag_lines.append("  Replace 'OPENAI_API_KEY=sk-xxxxx' with your real OpenAI API key.")
        raise RuntimeError("\n".join(diag_lines))

    # Check cache — but invalidate if the audio file has changed.
    # Without this check, regenerated voiceovers (new MP3 with same
    # filename) silently reuse the OLD transcription, causing the
    # render to play the wrong audio content.
    if cache_dir is not None:
        cache_file = Path(cache_dir) / "whisper_raw.json"
        meta_file = Path(cache_dir) / "whisper_cache_meta.json"
        audio_p = Path(audio_path)
        audio_size = audio_p.stat().st_size if audio_p.exists() else 0
        audio_mtime = audio_p.stat().st_mtime if audio_p.exists() else 0

        cache_valid = False
        if cache_file.exists() and meta_file.exists():
            try:
                meta = json.loads(meta_file.read_text())
                if (meta.get("audio_size") == audio_size
                        and meta.get("audio_mtime") == audio_mtime
                        and meta.get("audio_path") == str(audio_p.resolve())):
                    cache_valid = True
            except Exception:
                pass

        if cache_valid:
            raw = load_whisper_raw(cache_file)
            return extract_words(raw)

    # Transcribe via OpenAI Whisper API
    raw = transcribe_api(audio_path)

    # Cache the result with metadata for invalidation
    if cache_dir is not None:
        save_whisper_raw(raw, Path(cache_dir) / "whisper_raw.json")
        meta_file = Path(cache_dir) / "whisper_cache_meta.json"
        audio_p = Path(audio_path)
        meta = {
            "audio_path": str(audio_p.resolve()),
            "audio_size": audio_p.stat().st_size if audio_p.exists() else 0,
            "audio_mtime": audio_p.stat().st_mtime if audio_p.exists() else 0,
        }
        meta_file.write_text(json.dumps(meta))

    return extract_words(raw)
