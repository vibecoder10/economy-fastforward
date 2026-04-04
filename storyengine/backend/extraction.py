"""Storyboard grid extraction — extract panels from 3x3 grids via Nano Banana AI.

Sends each grid image to Nano Banana 2 with positional instructions
("extract ROW X COLUMN Y") to get clean, upscaled individual panels.
Falls back to PIL-based pixel cropping if no image client is available.
"""

import asyncio
import io
import logging
from typing import Optional

from PIL import Image

from storage import download_bytes, upload_bytes, upload_from_url

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Grid layout detection (shared by both AI and PIL paths)
# ---------------------------------------------------------------------------

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


async def detect_grid_layout_from_url(grid_url: str) -> tuple[int, int]:
    """Download just enough to detect grid dimensions."""
    raw = await download_bytes(grid_url)
    img = Image.open(io.BytesIO(raw))
    return detect_grid_layout(img)


# ---------------------------------------------------------------------------
# AI extraction via Nano Banana 2
# ---------------------------------------------------------------------------

async def extract_grid_ai(
    grid_url: str,
    video_id: str,
    scene: int,
    beat: int,
    panel_offset: int = 0,
    image_client=None,
    rows: int = 3,
    cols: int = 3,
) -> list[dict]:
    """Extract panels from a grid image using Nano Banana AI.

    Sends the grid image with positional instructions to extract each cell.
    Produces cleaner, upscaled individual panels compared to pixel cropping.

    Args:
        grid_url: URL of the storyboard grid image
        video_id: Video UUID for storage path
        scene: Scene number (1-indexed)
        beat: Beat/grid number within the scene (1-indexed)
        panel_offset: Starting image_index offset for asset mapping
        image_client: ImageClient instance with generate_scene_image()
        rows: Number of rows in the grid (default 3)
        cols: Number of columns in the grid (default 3)

    Returns:
        List of dicts with {image_index, panel_url} for each extracted panel
    """
    if image_client is None:
        raise ValueError("image_client is required for AI extraction")

    total = rows * cols
    logger.info(
        "Scene %d beat %d: extracting %d panels (%dx%d) via Nano Banana AI",
        scene, beat, total, cols, rows,
    )

    async def _extract_one(row: int, col: int, index: int) -> Optional[dict]:
        prompt = (
            f"Attached you'll find a {rows}x{cols} grid, with {rows} rows "
            f"and {cols} columns. I want you to extract just the still from "
            f"ROW {row} COLUMN {col}"
        )
        try:
            result = await image_client.generate_scene_image(
                prompt=prompt,
                reference_image_url=grid_url,
            )
            if not result or not result.get("url"):
                logger.warning("Failed to extract scene %d beat %d row %d col %d", scene, beat, row, col)
                return None

            # Persist temp URL to Supabase Storage
            image_index = panel_offset + index + 1  # 1-indexed
            path = f"{video_id}/extracted/S{scene}-B{beat}-P{index}.png"
            panel_url = await upload_from_url(result["url"], path)
            logger.info("  Extracted S%d-B%d row %d col %d → %s", scene, beat, row, col, path)
            return {"image_index": image_index, "panel_url": panel_url}
        except Exception as e:
            logger.error("Error extracting scene %d beat %d row %d col %d: %s", scene, beat, row, col, e)
            return None

    # Build tasks in reading order (left-to-right, top-to-bottom)
    tasks = []
    for r in range(1, rows + 1):
        for c in range(1, cols + 1):
            index = (r - 1) * cols + (c - 1)
            tasks.append(_extract_one(r, c, index))

    # Run in batches of 3 to avoid rate-limiting
    results = []
    for batch_start in range(0, len(tasks), 3):
        batch = tasks[batch_start:batch_start + 3]
        batch_results = await asyncio.gather(*batch, return_exceptions=True)
        for br in batch_results:
            if isinstance(br, Exception):
                logger.error("Panel extraction exception: %s", br)
            elif br is not None:
                results.append(br)

    logger.info(
        "Scene %d beat %d: extracted %d/%d panels via AI",
        scene, beat, len(results), total,
    )
    return results


# ---------------------------------------------------------------------------
# PIL fallback (pixel cropping)
# ---------------------------------------------------------------------------

def crop_panels(img: Image.Image) -> list[Image.Image]:
    """Crop a grid image into individual panels via pixel math.

    Detects layout automatically and returns panels in reading order
    (left-to-right, top-to-bottom).
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


async def extract_grid_pil(
    grid_url: str,
    video_id: str,
    scene: int,
    beat: int,
    panel_offset: int = 0,
) -> list[dict]:
    """PIL-based fallback: download grid, crop pixels, upload each panel."""
    raw = await download_bytes(grid_url)
    img = Image.open(io.BytesIO(raw))

    cols, rows = detect_grid_layout(img)
    panels = crop_panels(img)
    logger.info(
        "Scene %d beat %d: %dx%d grid → %d panels (%dx%d px each) [PIL fallback]",
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


# Keep original name as alias for backwards compatibility
extract_grid = extract_grid_pil
