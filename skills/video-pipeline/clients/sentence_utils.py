"""Sentence-level utilities for image/audio alignment."""

import re
from typing import List, Dict


def split_into_sentences(text: str) -> List[str]:
    """Split text into sentences.

    Args:
        text: The full scene narration text

    Returns:
        List of sentences
    """
    # Use a different approach: find sentence boundaries and split
    # Match sentence-ending punctuation, optionally followed by quotes
    # Then split on whitespace after these boundaries

    # First, normalize whitespace (convert newlines to spaces)
    normalized = " ".join(text.split())

    # Pattern matches: punctuation (.!?) optionally followed by closing quote
    # Then we insert a special delimiter and split on it
    # This handles: "Hello." and "Hello?" and 'Hello!'
    pattern = r'([.!?]["\'\u201d\u2019]?)\s+'
    marked = re.sub(pattern, r'\1|||SPLIT|||', normalized)

    # Split on our delimiter
    sentences = marked.split('|||SPLIT|||')

    # Filter out empty strings and clean up
    sentences = [s.strip() for s in sentences if s.strip()]

    return sentences


def estimate_sentence_duration(sentence: str, words_per_minute: float = 173) -> float:
    """Estimate how long a sentence takes to speak.
    
    Args:
        sentence: The sentence text
        words_per_minute: Speaking rate (default 173 wpm based on actual ElevenLabs output)
        
    Returns:
        Duration in seconds
    """
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
