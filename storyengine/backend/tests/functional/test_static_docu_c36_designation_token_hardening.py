"""Tests for chunk C36 (2026-07-29): closing a confirmed correctness hole in
the static-documentary reference-photo trust chain, verified live against
real Wikipedia.

THE BUG, in three parts (see static_docu.py's _designation_token_in_title,
find_wikipedia_lead_images, and _vision_confirms docstrings for the full
narrative):

  A. `_page_matches` tested a machine's designation token (`_designation_
     token`, e.g. "91" from "HMS Ark Royal (91)") against a Wikipedia page
     title with a raw, unfloored substring test. "No. 91 Squadron RAF" is a
     REAL Wikipedia article (a WWII RAF fighter squadron with its own
     aircraft photo) whose title contains "91" — so the roster machine
     "HMS Ark Royal (91)" could mark that squadron's photo as trusted.

  B. The exact same unfloored substring test was independently duplicated
     one call earlier, in find_wikipedia_lead_images's own `trusted`
     computation — so fixing only _page_matches would have left the bug
     alive at the upstream call site.

  C. `_vision_confirms` discarded the model's identification entirely for
     trusted candidates, looking only at hard-reject keyword lists. A reply
     of "NO, this is a Supermarine Spitfire fighter aircraft, not a ship"
     contains no hard-reject keyword, so a trusted-but-wrong candidate
     passed regardless of what the model said.

THE FIX:
  1/2/3. `_designation_token_in_title` is now the ONE shared, floored
     (>=3 chars, matching _commons_title_matches), word-boundary-anchored
     check used by BOTH _page_matches and find_wikipedia_lead_images — so
     the two can't drift apart again.
  4. `_vision_confirms` now rejects a trusted candidate whenever the model's
     reply opens with an explicit NO, in addition to the existing hard-
     reject keyword lists. An ambiguous/uncertain reply (no leading NO, no
     hard-reject keyword) still passes for a trusted candidate — provenance
     still excuses a weak model's failure to POSITIVELY identify an obscure
     machine, it just can no longer override an explicit negative ID.

Run:
    cd storyengine/backend && ./venv/bin/python -m pytest \
        tests/functional/test_static_docu_c36_designation_token_hardening.py -q
"""
import os
import sys

import pytest

_BACKEND = os.path.join(os.path.dirname(__file__), "..", "..")
sys.path.insert(0, os.path.abspath(_BACKEND))

import static_docu  # noqa: E402

# Same import-ordering fix as test_static_docu_c2f_vision_gate_fixes.py: force
# the real `anthropic` SDK to finish loading before any httpx monkeypatching.
import shared.clients.image_client  # noqa: E402,F401


# ---------------------------------------------------------------------------
# Shared fakes (vision-model mocking — same shape as
# test_static_docu_c2f_vision_gate_fixes.py, duplicated here so this file
# stays self-contained and never needs another chunk's test file to pass).
# ---------------------------------------------------------------------------

class _FakeJsonResp:
    def __init__(self, body, status_code=200):
        self._body = body
        self.status_code = status_code

    def json(self):
        return self._body

    def raise_for_status(self):
        pass


class _FakeImageResp:
    def __init__(self, content=b"\xff\xd8\xff" + b"0" * 32, status_code=200,
                 content_type="image/jpeg"):
        self.content = content
        self.status_code = status_code
        self.headers = {"content-type": content_type}


class _FakeVisionHttpClient:
    """Scripts _vision_confirms's `.post()` (model reply) calls; `.get()`
    (image download) always succeeds with a fake small JPEG."""

    def __init__(self, replies):
        self._replies = list(replies)
        self.calls = 0

    async def get(self, url, **kwargs):
        return _FakeImageResp()

    async def post(self, url, headers=None, json=None, **kwargs):
        self.calls += 1
        if not self._replies:
            raise AssertionError("post() called more times than scripted")
        item = self._replies.pop(0)
        if isinstance(item, Exception):
            raise item
        return _FakeJsonResp(item)


class _ClientCM:
    def __init__(self, inner):
        self._inner = inner

    async def __aenter__(self):
        return self._inner

    async def __aexit__(self, *a):
        return False


def _install_vision_fakes(monkeypatch, replies, anthropic_key="fake-anthropic-key"):
    fake_client = _FakeVisionHttpClient(replies)

    async def fake_get_secret(name, *a, **k):
        if name == "anthropic_api_key":
            return anthropic_key
        return None

    monkeypatch.setattr(static_docu.httpx, "AsyncClient",
                        lambda *a, **k: _ClientCM(fake_client))
    import vault
    monkeypatch.setattr(vault, "get_secret", fake_get_secret)
    return fake_client


def _anthropic_body(text: str) -> dict:
    return {"content": [{"type": "text", "text": text}]}


@pytest.fixture(autouse=True)
def _fast_wm_get(monkeypatch):
    """Skip the real politeness throttle/retry wrapper for these tests —
    same passthrough used elsewhere (test_static_docu_roster_prefetch.py) so
    a fake httpx client's .get() is called directly."""
    async def _passthrough(c, url, **kwargs):
        return await c.get(url, **kwargs)
    monkeypatch.setattr(static_docu, "_wm_get", _passthrough)


# ---------------------------------------------------------------------------
# Part A/1/2/3: _designation_token_in_title — floor + boundary anchor.
# ---------------------------------------------------------------------------

def test_two_char_pennant_token_below_floor_never_matches():
    """'91' (from 'HMS Ark Royal (91)') and '95' (from 'HMS Hermes (95)')
    are both 2 characters — below the >=3 floor — so they must never match,
    even against the exact live collision title."""
    assert static_docu._designation_token("HMS Ark Royal (91) Ark Royal (1937)") == "91"
    assert static_docu._designation_token_in_title("91", "No. 91 Squadron RAF") is False
    assert static_docu._designation_token("HMS Hermes (95) Hermes") == "95"
    assert static_docu._designation_token_in_title("95", "No. 95 Squadron RAF") is False


def test_three_char_pennant_token_clears_floor_and_matches_own_page():
    """'d48' (from 'HMS Campania (D48)') is 3 chars — clears the floor — and
    must still match its OWN real article title (a floor alone must not
    break the genuine case)."""
    assert static_docu._designation_token("HMS Campania (D48) Campania class") == "d48"
    assert static_docu._designation_token_in_title("d48", "HMS Campania (D48)") is True


def test_boundary_anchor_rejects_token_embedded_in_longer_run():
    """A length floor alone is NOT sufficient (D48/F61-style pennant numbers
    clear >=3 easily) — the match must also be boundary-anchored so a short
    token can't match as a bare fragment glued inside a longer, unrelated
    alphanumeric run once spaces are stripped for comparison. 'd48' must NOT
    match inside 'D489' (a different, longer designation that merely starts
    with the same 3 characters)."""
    assert static_docu._designation_token_in_title(
        "d48", "Squadron D489 Detachment") is False
    # But a real word-bounded occurrence of the same token still matches.
    assert static_docu._designation_token_in_title(
        "d48", "Squadron D48 Detachment") is True


def test_digit_token_still_matches_true_own_page():
    """Regression guard: the floor/anchor must not break genuine matches for
    the worked examples in the bug report."""
    assert static_docu._designation_token_in_title(
        "b52", "Boeing B-52 Stratofortress") is True
    assert static_docu._designation_token("Boeing B-52 Stratofortress") == "b52"


# ---------------------------------------------------------------------------
# Part A: _page_matches — the exact "No. 91 Squadron RAF" collision.
# ---------------------------------------------------------------------------

def test_page_matches_no_longer_collides_with_raf_squadron():
    """THE verified live collision: 'HMS Ark Royal (91)' must NOT be
    considered to match the real, unrelated Wikipedia article
    'No. 91 Squadron RAF' just because '91' appears in both."""
    assert static_docu._page_matches(
        "HMS Ark Royal (91) Ark Royal (1937)", [], "No. 91 Squadron RAF"
    ) is False


def test_page_matches_still_confirms_genuine_own_article():
    """The fix must not break the genuine case: the ship's own real article
    title still matches."""
    assert static_docu._page_matches(
        "HMS Ark Royal (91) Ark Royal (1937)", [],
        "HMS Ark Royal (91) Ark Royal (1937)"
    ) is True
    assert static_docu._page_matches(
        "HMS Campania (D48) Campania class", [], "HMS Campania (D48)"
    ) is True


# ---------------------------------------------------------------------------
# Part B: find_wikipedia_lead_images — the SAME collision, one call earlier
# (the duplicated trust computation). This proves the fix at BOTH sites, not
# just the downstream one.
# ---------------------------------------------------------------------------

class _RAFSquadronWMClient:
    """Models Wikipedia's pageimages API returning the unrelated 'No. 91
    Squadron RAF' article (with its own aircraft lead image) for whatever
    designation query is asked — the live fuzzy-match failure mode."""

    async def get(self, url, params=None, **kwargs):
        return _FakeJsonResp({
            "query": {
                "pages": {
                    "123": {
                        "title": "No. 91 Squadron RAF",
                        "thumbnail": {
                            "source": "https://upload.wikimedia.org/wikipedia/"
                                      "commons/thumb/a/b/Spitfire.jpg/"
                                      "1600px-Spitfire.jpg",
                        },
                    }
                }
            }
        })


@pytest.mark.asyncio
async def test_find_wikipedia_lead_images_does_not_trust_raf_squadron_collision(monkeypatch):
    """find_wikipedia_lead_images's OWN trust computation (duplicated from
    _page_matches — see static_docu.py C36 notes) must independently reject
    this collision, not rely on a downstream caller to catch it."""
    monkeypatch.setattr(
        static_docu.httpx, "AsyncClient",
        lambda *a, **k: _ClientCM(_RAFSquadronWMClient()))

    out = await static_docu.find_wikipedia_lead_images(
        ["HMS Ark Royal (91)", "Ark Royal"], limit=3)

    assert len(out) >= 1
    assert out[0]["page"] == "No. 91 Squadron RAF"
    assert out[0]["trusted"] is False, (
        "the '91' pennant-number token must not trust-promote an unrelated "
        "RAF squadron article just because '91' appears in its title")


# ---------------------------------------------------------------------------
# Part C: _vision_confirms — trusted_source must never override an explicit
# negative identification from the model.
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_vision_confirms_trusted_source_does_not_override_explicit_no(monkeypatch):
    """THE exact scenario from the bug report: a trusted candidate (e.g. the
    RAF squadron's Spitfire photo, wrongly marked trusted upstream) where the
    vision model's actual reply is an explicit, correct rejection. The old
    code discarded this signal entirely (no hard-reject keyword hit) and
    returned True. Must now return False."""
    _install_vision_fakes(monkeypatch, [
        _anthropic_body(
            "NO, this is a Supermarine Spitfire fighter aircraft, not a ship"),
    ])
    result = await static_docu._vision_confirms(
        "tenant-1", "https://example.com/spitfire.jpg",
        "HMS Ark Royal (91)", trusted_source=True)
    assert result is False


@pytest.mark.asyncio
async def test_vision_confirms_trusted_source_still_excuses_ambiguous_reply(monkeypatch):
    """The fix must not regress the ORIGINAL reason trusted candidates skip
    the strict YES bar: a weak model failing to positively name an obscure
    machine, without actively contradicting it, must still pass."""
    _install_vision_fakes(monkeypatch, [
        _anthropic_body("Not certain, but the silhouette looks consistent"),
    ])
    result = await static_docu._vision_confirms(
        "tenant-1", "https://example.com/xb15.jpg",
        "Boeing XB-15", trusted_source=True)
    assert result is True


@pytest.mark.asyncio
async def test_vision_confirms_untrusted_behavior_unchanged(monkeypatch):
    """Regression guard: untrusted-candidate handling (explicit YES required)
    must be completely unaffected by the trusted_source fix."""
    _install_vision_fakes(monkeypatch, [
        _anthropic_body("NO, this is a production B-52H, a different variant"),
    ])
    result = await static_docu._vision_confirms(
        "tenant-1", "https://example.com/b52h.jpg", "Boeing XB-52",
        trusted_source=False)
    assert result is False


# ---------------------------------------------------------------------------
# End-to-end: _gather_reference_candidates no longer marks the squadron
# photo trusted, so it would fall to the strict vision check instead of
# being silently hosted as verified.
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_gather_reference_candidates_demotes_raf_squadron_collision(monkeypatch):
    async def fake_lead_images(names, limit=3):
        return [{"url": "https://upload.wikimedia.org/wikipedia/commons/"
                        "thumb/a/b/Spitfire.jpg/1600px-Spitfire.jpg",
                 "page": "No. 91 Squadron RAF", "trusted": False}]

    async def fake_article_images(names, limit=5):
        return []

    async def fake_commons_photos(query, limit=3):
        return []

    monkeypatch.setattr(static_docu, "find_wikipedia_lead_images", fake_lead_images)
    monkeypatch.setattr(static_docu, "find_article_images", fake_article_images)
    monkeypatch.setattr(static_docu, "find_commons_photos", fake_commons_photos)

    candidates = await static_docu._gather_reference_candidates(
        "HMS Ark Royal (91)", ["Ark Royal"], "HMS Ark Royal aircraft carrier")

    assert len(candidates) == 1
    url, trusted = candidates[0]
    assert "Spitfire" in url
    assert trusted is False, (
        "the RAF squadron photo must reach the caller as UNTRUSTED so it "
        "still has to pass the strict vision check, not be hosted straight "
        "into static_reference_cache")
