"""Sentence-level utilities for image/audio alignment."""

import re
import tempfile
import httpx
from typing import List, Dict, Optional


def get_audio_duration(audio_url: str) -> Optional[float]:
    """Fetch audio file and return duration in seconds.

    Args:
        audio_url: URL to an audio file (mp3, wav, etc.)

    Returns:
        Duration in seconds, or None if unable to determine
    """
    try:
        from mutagen.mp3 import MP3
        from mutagen import MutagenError

        # Download audio to temp file
        response = httpx.get(audio_url, timeout=30.0, follow_redirects=True)
        response.raise_for_status()

        with tempfile.NamedTemporaryFile(suffix=".mp3", delete=False) as tmp:
            tmp.write(response.content)
            tmp_path = tmp.name

        # Get duration using mutagen
        try:
            audio = MP3(tmp_path)
            duration = audio.info.length
            return duration
        except MutagenError:
            return None
        finally:
            import os
            os.unlink(tmp_path)

    except Exception as e:
        print(f"    Warning: Could not get audio duration: {e}")
        return None


# Known abbreviations that should NOT trigger sentence splits
_ABBREVIATIONS = {
    'U.S.', 'U.K.', 'E.U.', 'U.N.', 'U.S.S.',
    'Dr.', 'Mr.', 'Mrs.', 'Ms.', 'Jr.', 'Sr.', 'St.', 'Gen.', 'Gov.', 'Sen.', 'Rep.', 'Sgt.', 'Col.', 'Adm.',
    'vs.', 'etc.', 'i.e.', 'e.g.', 'approx.', 'est.',
}

# Sentinel character used to protect abbreviation periods during splitting
_SENTINEL = "\x00"


def split_into_sentences(text: str) -> List[str]:
    """Split text into sentences, preserving abbreviations and initials.

    Handles:
    - Known abbreviations (U.S., Dr., etc.) — not split
    - Single-letter initials (Gerald R. Ford) — not split
    - Decimal numbers ($13.5 billion) — not split
    - Em-dash interrupted sentences — not split

    Args:
        text: The full scene narration text

    Returns:
        List of sentences
    """
    # Normalize whitespace (convert newlines to spaces)
    normalized = " ".join(text.split())

    # Protect abbreviations, initials, and decimals from sentence splitting
    protected = normalized

    # 1. Known abbreviations (longest first to avoid partial matches)
    for abbr in sorted(_ABBREVIATIONS, key=len, reverse=True):
        protected = protected.replace(abbr, abbr.replace('.', _SENTINEL))

    # 2. Single-letter initials: "R. Ford", "J. Kennedy" (capital + period + space + capital)
    protected = re.sub(r'(?<=[A-Z])\.(?=\s[A-Z])', _SENTINEL, protected)

    # 3. Decimal numbers: "$13.5", "3.2%", "100,000.5"
    protected = re.sub(r'(?<=\d)\.(?=\d)', _SENTINEL, protected)

    # Standard sentence splitting on .!? followed by whitespace
    pattern = r'([.!?]["\'\u201d\u2019]?)\s+'
    marked = re.sub(pattern, r'\1|||SPLIT|||', protected)
    sentences = marked.split('|||SPLIT|||')

    # Restore sentinel chars to periods and clean up
    sentences = [s.replace(_SENTINEL, '.').strip() for s in sentences if s.strip()]

    return sentences


def estimate_sentence_duration(sentence: str, words_per_minute: float = None) -> float:
    """Estimate how long a sentence takes to speak.

    Args:
        sentence: The sentence text
        words_per_minute: Speaking rate. Defaults to pipeline_config.SPEAKING_RATE_WPS * 60.

    Returns:
        Duration in seconds
    """
    if words_per_minute is None:
        try:
            from pipeline_config import VideoConfig
            words_per_minute = VideoConfig.SPEAKING_RATE_WPS * 60  # Convert WPS to WPM
        except ImportError:
            words_per_minute = 150  # 2.5 WPS * 60
    word_count = len(sentence.split())
    # Convert to seconds: words / (words/minute) * 60
    duration = (word_count / words_per_minute) * 60
    
    # Minimum 2 seconds, maximum 20 seconds per sentence
    return max(2.0, min(20.0, duration))


def analyze_scene_for_images(scene_text: str) -> List[Dict]:
    """Analyze a scene and break it into sentence-level segments for image generation.
    
    Args:
        scene_text: The full scene narration
        
    Returns:
        List of dicts with:
            - sentence_index: int
            - sentence_text: str
            - duration_seconds: float
            - cumulative_start: float (start time within scene)
    """
    sentences = split_into_sentences(scene_text)
    
    results = []
    cumulative_time = 0.0
    
    for i, sentence in enumerate(sentences):
        duration = estimate_sentence_duration(sentence)
        
        results.append({
            "sentence_index": i + 1,
            "sentence_text": sentence,
            "duration_seconds": round(duration, 1),
            "cumulative_start": round(cumulative_time, 1),
        })
        
        cumulative_time += duration
    
    return results


def get_target_image_count(sentences: List[Dict], target_duration_per_image: float = 10.0) -> int:
    """Calculate ideal number of images based on total duration.
    
    Args:
        sentences: Output from analyze_scene_for_images
        target_duration_per_image: Target seconds per image (default 10s)
        
    Returns:
        Recommended number of images (min 4, max 10)
    """
    if not sentences:
        return 6  # Default
    
    total_duration = sum(s["duration_seconds"] for s in sentences)
    ideal_count = round(total_duration / target_duration_per_image)
    
    # Clamp between 4 and 10
    return max(4, min(10, ideal_count))


# Example usage / test
if __name__ == "__main__":
    test_text = """The $12 trillion wealth transfer is already happening. While most Americans struggle with inflation, a small group is positioning themselves to capture generational wealth. This isn't speculation. It's mathematics. The Federal Reserve's own data shows the pattern clearly. By 2030, the largest intergenerational wealth transfer in human history will be complete. The question is: will you be on the receiving end, or watching from the sidelines?"""
    
    analysis = analyze_scene_for_images(test_text)
    
    print("Sentence Analysis:")
    print("-" * 60)
    for item in analysis:
        print(f"[{item['sentence_index']}] ({item['duration_seconds']}s) {item['sentence_text'][:50]}...")
    
    total = sum(s["duration_seconds"] for s in analysis)
    print(f"\nTotal duration: {total:.1f}s")
    print(f"Sentence count: {len(analysis)}")
    print(f"Recommended images: {get_target_image_count(analysis)}")
