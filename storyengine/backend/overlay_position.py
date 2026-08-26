"""Choose the least-occupied lower corner for a documentary info card."""

from pathlib import Path

from PIL import Image, ImageFilter, UnidentifiedImageError


RENDER_WIDTH = 1920
RENDER_HEIGHT = 1080
OVERLAY_SIDE_MARGIN = 76
OVERLAY_BOTTOM_MARGIN = 68
OVERLAY_CARD_WIDTH = 940
OVERLAY_CARD_HEIGHT = 230
EDGE_THRESHOLD = 32


def card_rectangles() -> tuple[tuple[int, int, int, int], tuple[int, int, int, int]]:
    """Return the left and right card footprints in render-frame pixels."""
    top = RENDER_HEIGHT - OVERLAY_BOTTOM_MARGIN - OVERLAY_CARD_HEIGHT
    bottom = RENDER_HEIGHT - OVERLAY_BOTTOM_MARGIN
    left = (
        OVERLAY_SIDE_MARGIN,
        top,
        OVERLAY_SIDE_MARGIN + OVERLAY_CARD_WIDTH,
        bottom,
    )
    right = (
        RENDER_WIDTH - OVERLAY_SIDE_MARGIN - OVERLAY_CARD_WIDTH,
        top,
        RENDER_WIDTH - OVERLAY_SIDE_MARGIN,
        bottom,
    )
    return left, right


def _edge_occupancy(edges: Image.Image, rectangle: tuple[int, int, int, int]) -> int:
    histogram = edges.crop(rectangle).histogram()
    return sum(histogram[EDGE_THRESHOLD + 1 :])


def choose_overlay_position(image_path, view_index: int) -> str:
    """Choose the card corner with fewer subject edges in its footprint."""
    path = Path(image_path)
    try:
        with Image.open(path) as source:
            frame = source.convert("L").resize(
                (RENDER_WIDTH, RENDER_HEIGHT),
                Image.Resampling.LANCZOS,
            )
            edges = frame.filter(ImageFilter.FIND_EDGES)
    except (OSError, ValueError, UnidentifiedImageError) as exc:
        raise RuntimeError(
            f"Unable to analyze overlay position for {path}: {exc}"
        ) from exc

    left_rect, right_rect = card_rectangles()
    left_occupancy = _edge_occupancy(edges, left_rect)
    right_occupancy = _edge_occupancy(edges, right_rect)
    if left_occupancy < right_occupancy:
        return "bottom_left"
    if right_occupancy < left_occupancy:
        return "bottom_right"
    return "bottom_left" if view_index % 2 else "bottom_right"
