"""Storyboard grid extraction — crop panels from grids, then upscale via AI.

Two-step approach:
1. PIL pixel-crop: guaranteed correct positioning (row/col never wrong)
2. Nano Banana upscale: enhance each cropped panel to full resolution

Falls back to PIL-only if no image client is available.
"""

import asyncio
import io
import logging
from typing import Optional

from PIL import Image

from storage import download_bytes, upload_bytes, upload_from_url

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# PIL cropping (always correct)
# ---------------------------------------------------------------------------

def crop_panels(img: Image.Image, rows: int = 3, cols: int = 3) -> list[Image.Image]:
    """Crop a grid image into individual panels in reading order."""
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


# ---------------------------------------------------------------------------
# Main extraction: PIL crop → upload → optional AI upscale
# ---------------------------------------------------------------------------

async def extract_grid(
    grid_url: str,
    video_id: str,
    scene: int,
    beat: int,
    panel_offset: int = 0,
    image_client=None,
    rows: int = 3,
    cols: int = 3,
) -> list[dict]:
    """Extract panels from a grid: PIL crop for accuracy, AI upscale for quality.

    Step 1: Download grid → PIL crop into individual panels (guaranteed correct)
    Step 2: Upload each cropped panel to Supabase Storage
    Step 3: If image_client available, upscale each panel via Nano Banana

    Args:
        grid_url: URL of the storyboard grid image
        video_id: Video UUID for storage path
        scene: Scene number (1-indexed)
        beat: Beat/grid number within the scene (1-indexed)
        panel_offset: Starting image_index offset for asset mapping
        image_client: Optional ImageClient for AI upscaling
        rows: Number of rows in the grid (default 3)
        cols: Number of columns in the grid (default 3)

    Returns:
        List of dicts with {image_index, panel_url} for each extracted panel
    """
    # Step 1: Download and crop
    raw = await download_bytes(grid_url)
    img = Image.open(io.BytesIO(raw))
    panels = crop_panels(img, rows=rows, cols=cols)

    total = rows * cols
    logger.info(
        "Scene %d beat %d: cropped %d panels (%dx%d px each) from %dx%d grid",
        scene, beat, len(panels),
        img.width // cols, img.height // rows,
        cols, rows,
    )

    # Step 2: Upload cropped panels to storage
    results = []
    for i, panel in enumerate(panels):
        image_index = panel_offset + i + 1  # 1-indexed
        path = f"{video_id}/extracted/S{scene}-B{beat}-P{i}.png"
        panel_bytes = image_to_bytes(panel)
        panel_url = await upload_bytes(panel_bytes, path)
        results.append({"image_index": image_index, "panel_url": panel_url})

    # Step 3: AI upscale if image client available
    if image_client:
        logger.info(
            "Scene %d beat %d: upscaling %d panels via Nano Banana",
            scene, beat, len(results),
        )

        async def _upscale_one(panel_result: dict, index: int) -> Optional[dict]:
            prompt = (
                "Upscale this image to high resolution. "
                "Do NOT alter, reinterpret, or modify the image in any way. "
                "Keep the exact same composition, pose, expression, colors, "
                "and details. Only increase resolution and clarity."
            )
            try:
                result = await image_client.generate_scene_image(
                    prompt=prompt,
                    reference_image_url=panel_result["panel_url"],
                )
                if not result or not result.get("url"):
                    logger.warning("Upscale failed for panel %d, keeping original", index)
                    return panel_result

                # Persist upscaled version, overwriting the cropped one
                path = f"{video_id}/extracted/S{scene}-B{beat}-P{index}.png"
                upscaled_url = await upload_from_url(result["url"], path)
                return {"image_index": panel_result["image_index"], "panel_url": upscaled_url}
            except Exception as e:
                logger.error("Upscale error for panel %d: %s", index, e)
                return panel_result  # Keep original crop on failure

        # Upscale in batches of 3
        upscaled_results = []
        for batch_start in range(0, len(results), 3):
            batch_items = results[batch_start:batch_start + 3]
            batch_indices = list(range(batch_start, batch_start + len(batch_items)))
            tasks = [_upscale_one(item, idx) for item, idx in zip(batch_items, batch_indices)]
            batch_results = await asyncio.gather(*tasks, return_exceptions=True)
            for j, br in enumerate(batch_results):
                if isinstance(br, Exception):
                    logger.error("Upscale exception: %s", br)
                    upscaled_results.append(batch_items[j])  # Keep original
                elif br is not None:
                    upscaled_results.append(br)

        logger.info(
            "Scene %d beat %d: %d/%d panels upscaled",
            scene, beat, len(upscaled_results), len(results),
        )
        return upscaled_results

    return results


# Backwards compatibility aliases
extract_grid_pil = extract_grid
extract_grid_ai = extract_grid
