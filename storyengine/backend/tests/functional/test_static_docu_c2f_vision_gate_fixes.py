"""Tests for chunk C2f (2026-07-21): 4 real bugs a 61-call live dry-run
against the real 23-machine roster exposed in the reference-verification
gate (_vision_confirms / _gather_reference_candidates in static_docu.py):

1. Hard-reject SUBSTRING matching false-matched "person" inside "supersonic"
   (S19 Convair B-58 — a genuine photo wrongly rejected — and cost S20
   XB-70 an extra candidate too). Fixed: word-boundary (\\b...\\b) matching.

2. TRUSTED candidates (own-article provenance) still required the model to
   spontaneously NAME the machine — impossible for an obscure never-built
   prototype, and a haiku-tier model misidentified genuine XB-15/B-21
   lead-image photos live ("a B-17", "a B-2"). Fixed: trusted candidates
   bypass identification and are rejected ONLY on hard signals (flat media /
   wrong content), never on a wrong guess.

3. UNTRUSTED prompt wording was loose ("...or a closely related variant"),
   letting a modern B-52H photo pass as the XB-52/YB-52 prototype live (S16/
   S17). Fixed: the question now explicitly demands THIS SPECIFIC variant —
   a different variant of the same family is NO.

4. Candidate ORDERING: a designation-token match (the file's own name
   carries the machine's designation, e.g. "XB-35.jpg") only got token-trust
   promotion from Commons search hits, not lead/article images, AND wasn't
   sorted first — so a correct token-matched file (e.g.
   "File:Boeing_XB-52_in_flight.jpg") could sit behind an earlier,
   loosely-trusted lookalike and never get tried (S8 XB-35, S16/S17 XB-52/
   YB-52). Fixed: token-trust applies to every source, and the final
   candidate list is sorted token-matched-first.

Plus: transport failures (exception or empty reply) now FAIL CLOSED (one
retry, then rejected) instead of silently returning "verified" — 23/23
URL-source calls 400'd live and the old code treated that as a pass.

Run:
    cd storyengine/backend && ./venv/bin/python -m pytest \
        tests/functional/test_static_docu_c2f_vision_gate_fixes.py -q
"""
import os
import sys

import pytest

_BACKEND = os.path.join(os.path.dirname(__file__), "..", "..")
sys.path.insert(0, os.path.abspath(_BACKEND))

import static_docu  # noqa: E402

# Force the real `anthropic` SDK (imported transitively via
# shared.clients.image_client -> shared.clients.anthropic_client) to finish
# loading NOW, with the real httpx.AsyncClient class still intact. Anthropic's
# _base_client.py subclasses httpx.AsyncClient at module IMPORT time
# (`class _DefaultAsyncHttpxClient(httpx.AsyncClient)`) — if that first
# import instead happens lazily inside _vision_confirms AFTER a test has
# already monkeypatched httpx.AsyncClient to a fake callable, the subclass
# statement itself blows up with a confusing TypeError. Pre-importing here
# (before any monkeypatching below) sidesteps that entirely.
import shared.clients.image_client  # noqa: E402,F401


# ---------------------------------------------------------------------------
# Shared fakes
# ---------------------------------------------------------------------------

class _FakeResp:
    def __init__(self, body):
        self._body = body

    def json(self):
        return self._body


class _FakeHttpClient:
    """Stands in for httpx.AsyncClient inside _vision_confirms. `replies` is
    a list of callables/exceptions/strings consumed one per `.post()` call —
    lets a test script "attempt 1 fails, attempt 2 succeeds" behavior and
    assert exactly how many attempts were made."""

    def __init__(self, replies):
        self._replies = list(replies)
        self.calls = 0

    async def post(self, url, headers=None, json=None, **kwargs):
        self.calls += 1
        if not self._replies:
            raise AssertionError("post() called more times than scripted")
        item = self._replies.pop(0)
        if isinstance(item, Exception):
            raise item
        return _FakeResp(item)


class _ClientCM:
    """`async with httpx.AsyncClient(...) as c:` wrapper around a fake."""

    def __init__(self, inner):
        self._inner = inner

    async def __aenter__(self):
        return self._inner

    async def __aexit__(self, *a):
        return False


def _install_vision_fakes(monkeypatch, replies, anthropic_key="fake-anthropic-key"):
    """Wires get_secret (anthropic key present -> direct-Anthropic branch)
    and httpx.AsyncClient to the scripted fake client. Returns the fake
    client so tests can assert on `.calls`."""
    fake_client = _FakeHttpClient(replies)

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


# ---------------------------------------------------------------------------
# 1. Word-boundary hard-reject matching (bug: "person" substring-matched
#    inside "supersonic").
# ---------------------------------------------------------------------------

def test_has_keyword_does_not_false_match_person_inside_supersonic():
    assert static_docu._has_keyword(
        "yes, this is a supersonic aircraft in flight",
        static_docu._WRONG_CONTENT_KEYWORDS) is False


def test_has_keyword_matches_person_as_a_whole_word():
    assert static_docu._has_keyword(
        "no, this shows a person standing next to the aircraft",
        static_docu._WRONG_CONTENT_KEYWORDS) is True


@pytest.mark.asyncio
async def test_vision_confirms_passes_supersonic_reply_untrusted(monkeypatch):
    """End-to-end: an untrusted candidate, model replies YES and the reason
    text contains "supersonic" — must PASS (not falsely rejected for
    containing "person" as a substring)."""
    _install_vision_fakes(monkeypatch, [
        _anthropic_body("YES, this shows a supersonic aircraft in flight"),
    ])
    result = await static_docu._vision_confirms(
        "tenant-1", "https://example.com/b58.jpg", "Convair B-58 Hustler",
        trusted_source=False)
    assert result is True


@pytest.mark.asyncio
async def test_vision_confirms_rejects_person_reply_untrusted(monkeypatch):
    _install_vision_fakes(monkeypatch, [
        _anthropic_body("YES, but it shows a person standing in the frame"),
    ])
    result = await static_docu._vision_confirms(
        "tenant-1", "https://example.com/photo.jpg", "Convair B-58 Hustler",
        trusted_source=False)
    assert result is False


# ---------------------------------------------------------------------------
# 2. Trusted candidates bypass identification — hard-reject signals only.
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_trusted_candidate_accepted_despite_misidentification(monkeypatch):
    """A trusted candidate (own-article provenance) whose model reply
    misidentifies the machine ("this is a B-17") but contains no hard-reject
    keyword must be ACCEPTED — provenance outranks a wrong guess."""
    _install_vision_fakes(monkeypatch, [
        _anthropic_body("NO, this looks like a B-17 Flying Fortress to me"),
    ])
    result = await static_docu._vision_confirms(
        "tenant-1", "https://example.com/xb15.jpg", "Boeing XB-15",
        trusted_source=True)
    assert result is True


@pytest.mark.asyncio
async def test_trusted_candidate_still_rejected_on_hard_signal(monkeypatch):
    """Provenance never excuses a flat/non-photo or clearly-wrong-content
    image — a trusted candidate whose reply says it's a diagram must still
    be rejected."""
    _install_vision_fakes(monkeypatch, [
        _anthropic_body("NO, this is a diagram / blueprint, not a photograph"),
    ])
    result = await static_docu._vision_confirms(
        "tenant-1", "https://example.com/xb15.jpg", "Boeing XB-15",
        trusted_source=True)
    assert result is False


# ---------------------------------------------------------------------------
# 3. Untrusted candidates still require strict, variant-specific YES.
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_untrusted_yes_accepted(monkeypatch):
    _install_vision_fakes(monkeypatch, [
        _anthropic_body("YES, this is the requested prototype aircraft"),
    ])
    result = await static_docu._vision_confirms(
        "tenant-1", "https://example.com/xb52.jpg", "Boeing XB-52",
        trusted_source=False)
    assert result is True


@pytest.mark.asyncio
async def test_untrusted_no_rejected(monkeypatch):
    """A model correctly recognizing this is a different variant (e.g. a
    modern B-52H photo offered for the XB-52 prototype) must be rejected —
    this is the S16/S17 regression case."""
    _install_vision_fakes(monkeypatch, [
        _anthropic_body("NO, this is a production B-52H, a different variant"),
    ])
    result = await static_docu._vision_confirms(
        "tenant-1", "https://example.com/b52h.jpg", "Boeing XB-52",
        trusted_source=False)
    assert result is False


# ---------------------------------------------------------------------------
# 3b. Transport failure fails CLOSED: retry once, then rejected.
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_transport_exception_retries_once_then_fails_closed(monkeypatch):
    fake_client = _install_vision_fakes(monkeypatch, [
        RuntimeError("connection reset"),
        RuntimeError("connection reset"),
    ])
    result = await static_docu._vision_confirms(
        "tenant-1", "https://example.com/photo.jpg", "Boeing XB-15",
        trusted_source=False)
    assert result is False
    assert fake_client.calls == 2, "must retry exactly once (2 total attempts)"


@pytest.mark.asyncio
async def test_transport_empty_reply_retries_once_then_fails_closed(monkeypatch):
    """A 400-status response whose body simply has no usable content (the
    live symptom: 23/23 URL-source calls 400'd) must be treated the same as
    an exception — retry once, then rejected, never silently 'verified'."""
    fake_client = _install_vision_fakes(monkeypatch, [
        {"type": "error", "error": {"message": "bad request"}},  # no "content"
        {"type": "error", "error": {"message": "bad request"}},
    ])
    result = await static_docu._vision_confirms(
        "tenant-1", "https://example.com/photo.jpg", "Boeing XB-15",
        trusted_source=False)
    assert result is False
    assert fake_client.calls == 2


@pytest.mark.asyncio
async def test_transport_succeeds_on_retry(monkeypatch):
    """First attempt empty, second attempt a real YES — must accept using
    the SECOND attempt's answer, not give up after the first."""
    fake_client = _install_vision_fakes(monkeypatch, [
        {"type": "error", "error": {}},
        _anthropic_body("YES, this is the requested aircraft"),
    ])
    result = await static_docu._vision_confirms(
        "tenant-1", "https://example.com/photo.jpg", "Boeing XB-15",
        trusted_source=False)
    assert result is True
    assert fake_client.calls == 2


# ---------------------------------------------------------------------------
# 4. Candidate ordering: token-matched candidates sort first, and the token
#    check now applies to lead/article images too, not just Commons hits.
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_token_matched_candidate_sorts_first(monkeypatch):
    """Mixed candidate set: a Commons-search hit whose FILE NAME carries the
    designation token (the true fix target) must sort ahead of an earlier-
    discovered lead image that only earned loose page-title trust — exactly
    the S16/S17 XB-52 regression (the true XB-52 file sat at candidate #5
    behind a loosely-trusted B-52H lead image)."""
    async def fake_lead_images(names, limit=3):
        # A loosely-trusted lead image (page title overlaps on a generic
        # word) whose OWN filename does NOT carry the "xb52" token.
        return [{"url": "https://upload.wikimedia.org/wikipedia/commons/"
                        "thumb/1/2/Boeing_B-52_Stratofortress.jpg/"
                        "1024px-Boeing_B-52_Stratofortress.jpg",
                 "page": "Boeing B-52 Stratofortress", "trusted": True}]

    async def fake_article_images(names, limit=5):
        return []

    async def fake_commons_photos(query, limit=3):
        # The TRUE token-matched file — must end up FIRST despite being
        # discovered after the lead image above.
        return [{"url": "https://upload.wikimedia.org/wikipedia/commons/"
                        "thumb/3/4/Boeing_XB-52_in_flight.jpg/"
                        "1024px-Boeing_XB-52_in_flight.jpg",
                 "title": "File:Boeing_XB-52_in_flight.jpg"}]

    monkeypatch.setattr(static_docu, "find_wikipedia_lead_images", fake_lead_images)
    monkeypatch.setattr(static_docu, "find_article_images", fake_article_images)
    monkeypatch.setattr(static_docu, "find_commons_photos", fake_commons_photos)

    candidates = await static_docu._gather_reference_candidates(
        "Boeing XB-52", ["YB-52"], "Boeing XB-52 prototype")

    assert len(candidates) == 2
    first_url, first_trusted = candidates[0]
    assert "XB-52_in_flight" in first_url
    assert first_trusted is True


@pytest.mark.asyncio
async def test_lead_image_promoted_trusted_by_own_filename_token(monkeypatch):
    """S8 XB-35 regression: the article title is a generic sibling name
    ("Northrop YB-35") so _page_matches misses, but the FILE ITSELF is named
    "XB-35.jpg" — the designation-token filename check must promote it to
    trusted anyway (LAYER 1, not just Commons search)."""
    async def fake_lead_images(names, limit=3):
        return [{"url": "https://upload.wikimedia.org/wikipedia/commons/"
                        "a/b/XB-35.jpg",
                 "page": "Northrop YB-35", "trusted": True}]

    async def fake_article_images(names, limit=5):
        return []

    async def fake_commons_photos(query, limit=3):
        return []

    monkeypatch.setattr(static_docu, "find_wikipedia_lead_images", fake_lead_images)
    monkeypatch.setattr(static_docu, "find_article_images", fake_article_images)
    monkeypatch.setattr(static_docu, "find_commons_photos", fake_commons_photos)

    candidates = await static_docu._gather_reference_candidates("XB-35", [], "XB-35")
    assert len(candidates) == 1
    url, trusted = candidates[0]
    assert "XB-35.jpg" in url
    assert trusted is True, (
        "the file's own name carries the 'xb35' designation token — must be "
        "trusted even though the article title ('Northrop YB-35') doesn't "
        "name this variant")
