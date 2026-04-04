"""Storyboard grid extraction — crop 3x3 grids into individual panels.

Downloads storyboard grid images, detects layout (3x3, 3x2, etc.),
crops individual panels, uploads each to Supabase Storage, and updates
the assets table with permanent panel URLs.
"""

import io
import logging
from PIL import Image

from storage import download_bytes, upload_bytes

logger = logging.getLogger(__name__)


def detect_grid_layout(img: Image.Image) -> tuple[int, int]:
    """Detect grid layout (cols, rows) from image dimensions.

    Standard Kie.ai grids:
    - 3x3: ~1024x1024 (aspect ~1.0)
    - 3x2: wider than tall (aspect > 1.3)
    - 2x3: taller than wide (aspect < 0.7)

    Returns:
        (cols, rows) tuple
    """
    aspect = img.width / img.height
    if aspect > 1.3:
        return (3, 2)
    elif aspect < 0.7:
        return (2, 3)
    else:
        return (3, 3)


def crop_panels(img: Image.Image) -> list[Image.Image]:
    """Crop a grid image into individual panels.

    Detects layout automatically and returns panels in reading order
    (left-to-right, top-to-bottom).

    Returns:
        List of cropped PIL Image objects
    """
    cols, rows = detect_grid_layout(img)
    panel_w = img.width // cols
    panel_h = img.height // rows
    panels = []

    for row in range(rows):
        for col in range(cols):
            x = col * panel_w
            y = row * panel_h
            panel = img.crop((x, y, x + panel_w, y + panel_h))
            panels.append(panel)

    return panels


def image_to_bytes(img: Image.Image) -> bytes:
    """Convert PIL Image to PNG bytes."""
    buf = io.BytesIO()
    img.save(buf, format="PNG")
    return buf.getvalue()


async def extract_grid(
    grid_url: str,
    video_id: str,
    scene: int,
    beat: int,
    panel_offset: int = 0,
) -> list[dict]:
    """Download a grid image, crop into panels, upload each to storage.

    Args:
        grid_url: URL of the storyboard grid image
        video_id: Video UUID for storage path
        scene: Scene number (1-indexed)
        beat: Beat/grid number within the scene (1-indexed)
        panel_offset: Starting image_index offset for asset mapping

    Returns:
        List of dicts with {image_index, panel_url} for each extracted panel
    """
    raw = await download_bytes(grid_url)
    img = Image.open(io.BytesIO(raw))

    cols, rows = detect_grid_layout(img)
    panels = crop_panels(img)
    logger.info(
        "Scene %d beat %d: %dx%d grid → %d panels (%dx%d px each)",
        scene, beat, cols, rows, len(panels),
        img.width // cols, img.height // rows,
    )

    results = []
    for i, panel in enumerate(panels):
        image_index = panel_offset + i + 1  # 1-indexed
        path = f"{video_id}/extracted/S{scene}-B{beat}-P{i}.png"
        panel_bytes = image_to_bytes(panel)
        panel_url = await upload_bytes(panel_bytes, path)
        results.append({"image_index": image_index, "panel_url": panel_url})

    return results
