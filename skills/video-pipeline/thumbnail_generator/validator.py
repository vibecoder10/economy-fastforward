"""Post-generation validation for EFF thumbnails.

Validates thumbnail dimensions, aspect ratio, and orientation.
Flags images for manual review when automated checks fail.
"""

from PIL import Image


def validate_thumbnail(image_path: str) -> tuple[bool, dict]:
    """Validate thumbnail dimensions and aspect ratio.

    Args:
        image_path: Path to the generated thumbnail image file.

    Returns:
        Tuple of (passes_all_checks: bool, check_results: dict).
        check_results maps check name -> bool.
    """
    img = Image.open(image_path)
    w, h = img.size

    checks = {
        "aspect_ratio_16_9": abs((w / h) - (16 / 9)) < 0.05,
        "min_width_1280": w >= 1280,
        "min_height_720": h >= 720,
        "is_landscape": w > h,
    }

    return all(checks.values()), checks
