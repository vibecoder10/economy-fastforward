"""Functional test for Stage 6.4 sub-fix #5: competitor video cards
older than 7 days (hours_old > 168) render dimmed with a "stale" pill.

Why this matters: after Cycles 33-35 made age live and filterable, users
can now explicitly pull up >7d windows. Without visual de-emphasis,
stale cards mix 1:1 with fresh ones in the grid — which defeats the
point of a competitors *intelligence* view (the whole job is "what's
working NOW"). The 7-day cutoff is the same horizon the backend uses
as a relevance ceiling; pinning the number here keeps the two halves
of the product honest.

Source audit over competitors/page.tsx, same pattern as Cycle 35:
  - isStale computed from hours_old > 168 (not >= 168 — "stale" means
    "past 7 days", not "exactly 7 days")
  - isStale drives both the GlassCard visual (opacity or class) and
    the "stale" pill in the metadata row
  - The threshold is pinned literally so a typo doesn't silently move
    the cutoff to e.g. 1680 (70 days)
"""
import os
import re
import sys
from pathlib import Path

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))


def _page_tsx() -> Path:
    return (
        Path(__file__).resolve().parents[3]
        / "frontend"
        / "src"
        / "app"
        / "competitors"
        / "page.tsx"
    )


def test_page_exists():
    assert _page_tsx().exists(), f"page.tsx not at {_page_tsx()}"
    print("✅ test_page_exists")


def test_isStale_threshold_is_168h():
    """The cutoff must be exactly 168 (hours in 7 days). Not 167, not
    172, not 7 * 24. Pinning the literal avoids "clever" rewrites that
    silently shift the cutoff."""
    src = _page_tsx().read_text()
    m = re.search(
        r"const\s+isStale\s*=\s*video\.hours_old\s*!=\s*null\s*&&\s*video\.hours_old\s*>\s*168",
        src,
    )
    assert m, (
        "isStale definition not found or threshold != 168. Expected:\n"
        "  const isStale = video.hours_old != null && video.hours_old > 168;"
    )
    print("✅ test_isStale_threshold_is_168h")


def test_isStale_drives_card_visual():
    """isStale must wire to the GlassCard style or className. Either a
    style={... opacity ...} or a stale-video-card class is acceptable,
    but at least one must be present and conditioned on isStale."""
    src = _page_tsx().read_text()
    # Look for a conditional on isStale applied to the GlassCard opening
    # tag's style or className — we accept either shape
    card_open = re.search(
        r"<GlassCard\b[^>]*isStale[^>]*>",
        src,
        re.DOTALL,
    )
    assert card_open, (
        "GlassCard opening tag doesn't reference isStale — dim effect "
        "isn't wired to the card. Check the videos.map render."
    )
    block = card_open.group(0)
    # Must affect either opacity or a stale class
    opacity_wiring = re.search(r"opacity\s*:\s*0?\.\d+", block)
    class_wiring = re.search(r"stale-video-card", block)
    assert opacity_wiring or class_wiring, (
        "GlassCard references isStale but neither opacity:<n> nor a "
        "stale-video-card className is present — the dim effect has no "
        "visual output."
    )
    print("✅ test_isStale_drives_card_visual")


def test_stale_pill_rendered_when_stale():
    """When isStale is true, a 'stale' label must render somewhere in
    the metadata row — so the user understands the dim isn't a bug."""
    src = _page_tsx().read_text()
    # Accept either a text node "stale" or a label-like attribute
    pill = re.search(
        r"\{isStale\s*&&[\s\S]{0,1200}?>\s*stale\s*<",
        src,
    )
    assert pill, (
        "Missing a `{isStale && <... >stale<...>}` pill in the card "
        "metadata. Users won't know why some cards are dim."
    )
    print("✅ test_stale_pill_rendered_when_stale")


def test_stale_pill_has_tooltip_explaining_why():
    """A user hovering the 'stale' pill should get the reason ('older
    than 7 days'). Bare label with no explanation is a common UX miss.
    The title attribute is the lightest-weight way to ship this without
    pulling in a tooltip component."""
    src = _page_tsx().read_text()
    # Find the pill block, then confirm a title=... exists inside
    pill_block = re.search(
        r"\{isStale\s*&&[\s\S]{0,1200}?>\s*stale\s*<",
        src,
    )
    assert pill_block, "stale pill block not located (prereq for this test)"
    block = pill_block.group(0)
    assert re.search(r'title\s*=\s*["\{][^"\}]*7\s*days', block, re.IGNORECASE), (
        "stale pill missing a `title=\"...7 days...\"` tooltip "
        "explaining the cutoff."
    )
    print("✅ test_stale_pill_has_tooltip_explaining_why")


def test_dim_does_not_hide_card_entirely():
    """Guardrail: don't accidentally make the card invisible. Opacity
    must be >= 0.3 — anything lower is hidden-but-clickable, which is
    worse than just showing the card. If someone sets opacity:0.1 in
    a future tweak, this test catches it."""
    src = _page_tsx().read_text()
    for m in re.finditer(r"opacity\s*:\s*(0?\.\d+)", src):
        val = float(m.group(1))
        assert val >= 0.3, (
            f"Found opacity:{val} in competitors/page.tsx — too low. "
            "Stale cards should be de-emphasized, not invisible."
        )
    print("✅ test_dim_does_not_hide_card_entirely")


TESTS = [
    test_page_exists,
    test_isStale_threshold_is_168h,
    test_isStale_drives_card_visual,
    test_stale_pill_rendered_when_stale,
    test_stale_pill_has_tooltip_explaining_why,
    test_dim_does_not_hide_card_entirely,
]


def main() -> int:
    failed = 0
    for t in TESTS:
        try:
            t()
        except AssertionError as e:
            print(f"❌ {t.__name__}: {e}")
            failed += 1
        except Exception as e:
            print(f"❌ {t.__name__}: {type(e).__name__}: {e}")
            failed += 1
    print(f"\n{len(TESTS) - failed}/{len(TESTS)} passed")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
