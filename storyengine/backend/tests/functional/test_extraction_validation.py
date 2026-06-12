"""Tests for extraction validation — the bad-crop rules (Ryan, 2026-06-12).

panel_flags is calibrated against the bird video's real panels (S2.2/S2.3/
S2.4 label leaks, S2.5 split crop, six clean negatives incl. alphabet
posters); these synthetic cases pin the same behaviours without shipping
binary fixtures. storage is stubbed; no network.

Run: python3 tests/functional/test_extraction_validation.py  (from backend dir)
"""

import asyncio
import io
import os
import random
import sys
import types

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", ".."))

_uploads: dict = {}


async def _fake_download(url):
    return _uploads[url]


async def _fake_upload(data, path, content_type=None):
    url = f"fake://{path}"
    _uploads[url] = data
    return url

sys.modules.setdefault("storage", types.SimpleNamespace(
    download_bytes=_fake_download, upload_bytes=_fake_upload, upload_from_url=None))

from PIL import Image, ImageDraw  # noqa: E402
from extraction import panel_flags, extract_grid, grid_layout_for  # noqa: E402

random.seed(7)


def _scene_panel(w=450, h=380) -> Image.Image:
    """A plausible 'scene': mid-tone noise — no uniform bands, no chip."""
    img = Image.new("L", (w, h))
    img.putdata([random.randint(70, 180) for _ in range(w * h)])
    return img.convert("RGB")


def _with_chip(img: Image.Image) -> Image.Image:
    """Burn a [KF4 | MCU | 10s] style chip into the top-left."""
    out = img.copy()
    d = ImageDraw.Draw(out)
    d.rectangle([0, 0, int(img.width * 0.38), 26], fill=(8, 8, 8))
    d.text((8, 6), "[KF4 | MCU | 10s]", fill=(245, 245, 245))
    return out


def _split_panel(img: Image.Image) -> Image.Image:
    """Two half-scenes with a white gutter through the middle (S2.5)."""
    out = img.copy()
    d = ImageDraw.Draw(out)
    x = img.width // 2
    d.rectangle([x - 4, 0, x + 4, img.height], fill=(252, 252, 252))
    return out


def test_panel_flags():
    assert panel_flags(_scene_panel()) == []
    assert panel_flags(_with_chip(_scene_panel())) == ["label_leak"]
    assert panel_flags(_split_panel(_scene_panel())) == ["gutter_split"]
    both = _split_panel(_with_chip(_scene_panel()))
    assert set(panel_flags(both)) == {"label_leak", "gutter_split"}
    print("✓ panel_flags: chip, gutter, both, clean")


def _grid(rows: int, cols: int, w=450, h=380) -> bytes:
    """Build a grid of distinct scene panels separated by black gutters."""
    gw, gh = cols * w, rows * h
    grid = Image.new("RGB", (gw, gh), (0, 0, 0))
    for r in range(rows):
        for c in range(cols):
            # inset 3px so panels are separated by black gutter lines
            p = _scene_panel(w - 6, h - 6)
            grid.paste(p, (c * w + 3, r * h + 3))
    buf = io.BytesIO()
    grid.save(buf, format="PNG")
    return buf.getvalue()


def test_self_healing_layout():
    """Cropping a 2x3 grid as 2x2 makes split panels — extract_grid must
    notice the gutter_split flags and fall back to pixel-detected layout."""
    _uploads["fake://grid"] = _grid(2, 3)
    panels = asyncio.run(extract_grid("fake://grid", "vid", 1, 1, 0, rows=2, cols=2))
    assert len(panels) == 6, f"expected 6 healed panels, got {len(panels)}"
    flagged = [p for p in panels if p.get("flags")]
    assert not flagged, f"healed crops still flagged: {flagged}"
    print("✓ extract_grid self-heals a wrong layout via gutter detection")


def test_chip_heals_at_extraction():
    """A leaked chip is trimmed off at extraction time: the stored panel is
    shorter, the flag clears, and the clean neighbour is untouched."""
    chip_grid = Image.open(io.BytesIO(_grid(1, 2)))
    w = chip_grid.width // 2
    d = ImageDraw.Draw(chip_grid)
    d.rectangle([6, 6, int(w * 0.38), 30], fill=(8, 8, 8))
    d.text((14, 12), "[KF1 | LS | 12s]", fill=(245, 245, 245))
    buf = io.BytesIO()
    chip_grid.save(buf, format="PNG")
    _uploads["fake://chipgrid"] = buf.getvalue()
    panels = asyncio.run(extract_grid("fake://chipgrid", "vid", 1, 1, 0, rows=1, cols=2))
    assert len(panels) == 2
    assert not panels[0].get("flags"), panels[0]
    assert not panels[1].get("flags"), panels[1]
    healed = Image.open(io.BytesIO(_uploads[panels[0]["panel_url"]]))
    clean = Image.open(io.BytesIO(_uploads[panels[1]["panel_url"]]))
    assert healed.height < clean.height, (healed.height, clean.height)
    print("✓ extract_grid trims leaked chips and clears the flag")


def test_untrimmable_chip_stays_flagged():
    """trim_label_chip returns None on chip-free panels — no silent crops."""
    from extraction import trim_label_chip
    assert trim_label_chip(_scene_panel()) is None
    print("✓ no-chip panels are never trimmed")


def test_layout_helper():
    assert grid_layout_for(6) == (2, 3) and grid_layout_for(9) == (3, 3)
    print("✓ grid_layout_for unchanged")


if __name__ == "__main__":
    test_panel_flags()
    test_self_healing_layout()
    test_chip_heals_at_extraction()
    test_untrimmable_chip_stays_flagged()
    test_layout_helper()
    print("\nALL 5 TESTS PASSED")
