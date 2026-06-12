"""Storyboard grid extraction — crop panels from grids, then upscale via AI.

Two-step approach:
1. PIL pixel-crop: guaranteed correct positioning (row/col never wrong)
2. Nano Banana upscale: enhance each cropped panel to full resolution

Falls back to PIL-only if no image client is available.
No numpy dependency — pure PIL for VPS compatibility.
"""

import asyncio
import io
import logging
from typing import Optional

from PIL import Image, ImageStat

from storage import download_bytes, upload_bytes, upload_from_url

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Grid layout detection (pure PIL)
# ---------------------------------------------------------------------------

def grid_layout_for(panel_count: int) -> tuple[int, int]:
    """The layout the storyboard bot USES when it builds a grid for N panels.

    MUST mirror skills/video-pipeline/storyboard/bot.py:_grid_layout — grids
    are generated with this exact geometry, so cropping with it is exact.
    Pixel-detection (below) is only the fallback when the count is unknown;
    it mis-read a 2x3 grid as full-width rows and produced 3-panels-in-one
    "extracted" images (bird video, scene 2).
    """
    if panel_count <= 1:
        return (1, 1)
    if panel_count <= 2:
        return (1, 2)
    if panel_count <= 3:
        return (1, 3)
    if panel_count <= 4:
        return (2, 2)
    if panel_count <= 6:
        return (2, 3)
    return (3, 3)


def detect_grid_layout(img: Image.Image) -> tuple[int, int]:
    """Detect grid rows×cols by scanning for dark separator bands.

    The storyboard bot generates grids with thin (~3-5px) black separator
    lines between panels.  We check for dark bands at expected division
    points (1/2, 1/3, 2/3) in both axes.

    Uses PIL resize trick: shrink to 1px tall → column brightness profile,
    shrink to 1px wide → row brightness profile.

    Returns (rows, cols).  Falls back to (1, 1) if no separators found.
    """
    gray = img.convert("L")
    w, h = gray.size

    # Column brightness profile: resize to (w, 1) → one brightness value per column
    col_strip = list(gray.resize((w, 1)).getdata())
    # Row brightness profile: resize to (1, h) → one brightness value per row
    row_strip = list(gray.resize((1, h)).getdata())

    def _has_dark_band(profile: list, pos: int, tolerance: int = 8) -> bool:
        """True if there's a dark separator strip near *pos*.

        Uses min — a ~5px dark separator inside a wider tolerance window
        still registers even when bright panels surround it.
        """
        start = max(0, pos - tolerance)
        end = min(len(profile), pos + tolerance + 1)
        if end - start < 3:
            return False
        return min(profile[start:end]) < 30

    # --- columns ---
    has_3cols = (_has_dark_band(col_strip, w // 3) and
                 _has_dark_band(col_strip, 2 * w // 3))
    has_2cols = _has_dark_band(col_strip, w // 2)
    cols = 3 if has_3cols else (2 if has_2cols else 1)

    # --- rows ---
    has_3rows = (_has_dark_band(row_strip, h // 3) and
                 _has_dark_band(row_strip, 2 * h // 3))
    has_2rows = _has_dark_band(row_strip, h // 2)
    rows = 3 if has_3rows else (2 if has_2rows else 1)

    logger.info("Grid layout detected: %d×%d from %dx%d image", rows, cols, w, h)
    return rows, cols


def _is_padding_panel(panel: Image.Image, threshold: float = 15.0) -> bool:
    """Return True if a panel is all-black padding (mean brightness < threshold)."""
    return ImageStat.Stat(panel.convert("L")).mean[0] < threshold


# ---------------------------------------------------------------------------
# PIL cropping (always correct)
# ---------------------------------------------------------------------------

def _find_label_bar_height(img: Image.Image) -> int:
    """Detect the black label bar at the top of a panel.

    Scans rows from the top — the bar has low mean brightness (<100),
    and the image content starts where brightness jumps above 100.
    Returns the number of pixel rows to skip (the bar height).
    """
    w, h = img.size
    gray = img.convert("L")
    max_scan = min(40, h // 4)
    for y in range(max_scan):
        # Average brightness of this single row
        row = gray.crop((0, y, w, y + 1))
        if ImageStat.Stat(row).mean[0] > 100:
            return y
    return 0  # No bar detected


def crop_panels(img: Image.Image, rows: int = 3, cols: int = 3) -> list[Image.Image]:
    """Crop a grid image into individual panels, trimming label bars and borders.

    Removes:
    - Black label bars at the top of each panel (e.g. "[KF1 | LS | 12s]")
    - Black separator borders between panels (~3-5px)
    """
    panel_w = img.width // cols
    panel_h = img.height // rows
    # Trim ~1% from edges to remove black separator borders
    border_x = max(2, panel_w // 100)
    border_y = max(2, panel_h // 100)
    panels = []

    for row in range(rows):
        for col in range(cols):
            x = col * panel_w
            y = row * panel_h
            # Extract raw panel region to detect label bar
            raw_panel = img.crop((x, y, x + panel_w, y + panel_h))
            bar_h = _find_label_bar_height(raw_panel)
            # Crop: skip label bar at top, trim borders on all sides
            crop_left = x + border_x
            crop_top = y + bar_h + border_y
            crop_right = x + panel_w - border_x
            crop_bottom = y + panel_h - border_y
            panel = img.crop((crop_left, crop_top, crop_right, crop_bottom))
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
    rows: int = 0,
    cols: int = 0,
) -> list[dict]:
    """Extract panels from a grid: PIL crop for accuracy, AI upscale for quality.

    Step 1: Download grid → auto-detect layout → PIL crop into panels
    Step 2: Filter out black padding panels
    Step 3: Upload each cropped panel to Google Drive
    Step 4: If image_client available, upscale each panel via Nano Banana

    Args:
        grid_url: URL of the storyboard grid image
        video_id: Video UUID for storage path
        scene: Scene number (1-indexed)
        beat: Beat/grid number within the scene (1-indexed)
        panel_offset: Starting image_index offset for asset mapping
        image_client: Optional ImageClient for AI upscaling
        rows: Grid rows (0 = auto-detect from image)
        cols: Grid columns (0 = auto-detect from image)

    Returns:
        List of dicts with {image_index, panel_url} for each extracted panel
    """
    # Step 1: Download and detect layout
    raw = await download_bytes(grid_url)
    img = Image.open(io.BytesIO(raw))

    if rows == 0 or cols == 0:
        rows, cols = detect_grid_layout(img)

    panels = crop_panels(img, rows=rows, cols=cols)

    # Step 2: Filter out black padding panels
    real_panels = [(i, p) for i, p in enumerate(panels) if not _is_padding_panel(p)]
    if len(real_panels) < len(panels):
        logger.info(
            "Scene %d beat %d: filtered %d padding panels, keeping %d real panels",
            scene, beat, len(panels) - len(real_panels), len(real_panels),
        )

    logger.info(
        "Scene %d beat %d: cropped %d panels (%dx%d px each) from %dx%d grid",
        scene, beat, len(real_panels),
        img.width // cols, img.height // rows,
        cols, rows,
    )

    # Step 3: Upload cropped panels to storage
    results = []
    for seq, (orig_idx, panel) in enumerate(real_panels):
        image_index = panel_offset + seq + 1  # 1-indexed
        path = f"{video_id}/images/S{scene}-B{beat}-P{seq}.png"
        panel_bytes = image_to_bytes(panel)
        panel_url = await upload_bytes(panel_bytes, path)
        results.append({"image_index": image_index, "panel_url": panel_url})

    # Step 4: AI upscale if image client available
    if image_client:
        logger.info(
            "Scene %d beat %d: upscaling %d panels via Nano Banana",
            scene, beat, len(results),
        )

        async def _upscale_one(panel_result: dict, index: int) -> Optional[dict]:
            prompt = (
                "Upscale this image to high resolution. "
                "Remove any text labels like [KF1 | LS | 12s], [KF7 | MS | 9s], "
                "or similar keyframe/shot/duration overlays — cleanly paint over "
                "them with the surrounding image content. "
                "Otherwise do NOT alter the image in any way. "
                "Keep the exact same composition, pose, expression, colors, "
                "and details. Only increase resolution, clarity, and remove labels."
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
                path = f"{video_id}/images/S{scene}-B{beat}-P{index}.png"
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
