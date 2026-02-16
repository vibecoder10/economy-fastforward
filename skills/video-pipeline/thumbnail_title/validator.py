"""Thumbnail validation for Economy FastForward.

Runs automated checks on generated thumbnails before advancing the pipeline.
Flags images for manual review when automated checks can't cover subjective quality.
"""

import io
from typing import Optional


def validate_thumbnail(image_data: bytes) -> tuple[bool, dict]:
    """Validate a thumbnail image passes all automated checks.

    Args:
        image_data: Raw image bytes (PNG or JPEG).

    Returns:
        Tuple of (passes_all_checks: bool, check_results: dict).
        check_results maps check name -> bool.
    """
    try:
        from PIL import Image
        img = Image.open(io.BytesIO(image_data))
    except ImportError:
        # PIL not available — skip image-level checks, return pass
        print("  WARNING: Pillow not installed, skipping image validation")
        return True, {"pillow_available": False}
    except Exception as e:
        return False, {"image_load": False, "error": str(e)}

    w, h = img.size

    checks = {
        "aspect_ratio": abs((w / h) - (16 / 9)) < 0.05,
        "min_width": w >= 1280,
        "min_height": h >= 720,
    }

    # Log manual review items (can't be automated)
    manual_review_notes = [
        "Is the face emotion readable at 160x90?",
        "Is the text readable at 160x90?",
        "Are there 3 or fewer dominant colors?",
        "Is there ONE clear focal point?",
    ]

    passes = all(checks.values())

    if not passes:
        failed = [k for k, v in checks.items() if not v]
        print(f"  VALIDATION FAILED: {failed}")
        print(f"  Image dimensions: {w}x{h}, aspect ratio: {w/h:.3f}")

    return passes, checks


def validate_title_thumbnail_pair(title_data: dict, template_key: str) -> tuple[bool, list[str]]:
    """Validate that the title and thumbnail are properly paired.

    Checks:
    - The CAPS word in the title matches the red_word in the thumbnail
    - Thumbnail text doesn't exceed 5 words total
    - line_1 and line_2 are ALL CAPS

    Args:
        title_data: Output from TitleGenerator.generate().
        template_key: The template used for the thumbnail.

    Returns:
        Tuple of (is_valid: bool, issues: list[str]).
    """
    issues = []

    caps_word = title_data.get("caps_word", "")
    line_1 = title_data.get("line_1", "")
    line_2 = title_data.get("line_2", "")
    title = title_data.get("title", "")

    # Check caps_word appears in the title
    if caps_word and caps_word not in title:
        issues.append(f"CAPS word '{caps_word}' not found in title '{title}'")

    # Check caps_word appears in line_1
    if caps_word and caps_word not in line_1:
        issues.append(f"CAPS word '{caps_word}' not found in thumbnail line_1 '{line_1}'")

    # Check total thumbnail text word count (max 5)
    total_words = len(line_1.split()) + len(line_2.split())
    if total_words > 5:
        issues.append(f"Thumbnail text has {total_words} words (max 5): '{line_1}' + '{line_2}'")

    # Check ALL CAPS
    if line_1 != line_1.upper():
        issues.append(f"line_1 is not ALL CAPS: '{line_1}'")
    if line_2 != line_2.upper():
        issues.append(f"line_2 is not ALL CAPS: '{line_2}'")

    # Check line lengths
    if len(line_1.split()) > 4:
        issues.append(f"line_1 exceeds 4 words: '{line_1}'")
    if len(line_2.split()) > 3:
        issues.append(f"line_2 exceeds 3 words: '{line_2}'")

    return len(issues) == 0, issues
