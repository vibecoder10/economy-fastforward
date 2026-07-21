"""Tests for the static_docu reference-repair fix (chunk C1, 2026-07-21).

Three defects made static_docu.py invent fictional aircraft for obscure
never-built prototypes (XB-35, YB-49, YB-35, YB-60):

1. `_api_issued_thumb` only tried widths 1600 and (original_width - 1).
   MediaWiki echoes the RAW url back (never issues a /thumb/) whenever the
   requested width sits close to the true original width — common for
   archival scans ~1300-2000px wide — so BOTH attempts failed for these four
   machines and a correct photo got silently dropped. Fixed: a descending
   width ladder (1600, 1280, 1024, 800, 640) that accepts the first width
   that actually gets a /thumb/ issued.

2. Commons search hits were always tagged trusted=False, and untrusted
   candidates only passed `_vision_confirms` if the model spontaneously
   NAMED the designation — impossible for an obscure prototype. Fixed: a
   Commons hit whose FILE TITLE itself carries the designation token (e.g.
   "xb35" in "Northrop_XB-35_11-300.jpg") is promoted to trusted, and
   `_vision_confirms` now supplies the machine name and asks a direct
   YES/NO instead of requiring spontaneous naming.

3. FAIL-OPEN: when no reference was found, the code generated a TEXT-TO-
   IMAGE guess anyway and shipped it status='done' with only a log warning.
   Fixed: FAIL CLOSED — zero verified candidates means NO generation call is
   made; the scene is persisted as status='blocked_no_reference' (image_url
   and drive_image_url both NULL) and returned as a failed scene id, exactly
   like every other failure path in this function.

These tests are git-stash-sensitive for tests 1-2 below: `git stash` the
static_docu.py fix and each fails (see the module docstring's stash-proof
evidence in the C1 handoff report for the captured before/after output).

Run:
    cd storyengine/backend && ./venv/bin/python -m pytest \
        tests/functional/test_static_docu_reference_fail_closed.py -q
"""
import os
import sys
from pathlib import Path

import pytest

_BACKEND = os.path.join(os.path.dirname(__file__), "..", "..")
sys.path.insert(0, os.path.abspath(_BACKEND))

_REPO_ROOT = Path(__file__).resolve().parents[4]
_PIPELINE_ROOT = _REPO_ROOT / "skills" / "video-pipeline"
if str(_PIPELINE_ROOT) not in sys.path:
    sys.path.insert(0, str(_PIPELINE_ROOT))

import static_docu  # noqa: E402


# ---------------------------------------------------------------------------
# Shared fakes — no network, no DB, no real provider calls anywhere below.
# ---------------------------------------------------------------------------

class _FakeResp:
    def __init__(self, body):
        self._body = body

    def json(self):
        return self._body

    def raise_for_status(self):
        pass


class _FakeWMClient:
    """Stands in for the httpx.AsyncClient `_wm_get`/`_api_issued_thumb` are
    handed. Models the REAL MediaWiki behavior confirmed live for these four
    machines: a request for a width close to the original's true width (here
    1543px, matching XB-35.jpg) gets the RAW url echoed back — no /thumb/ —
    while a comfortably smaller width gets a real /thumb/ issued."""

    ORIGINAL_WIDTH = 1543
    RAW_URL = "https://upload.wikimedia.org/wikipedia/commons/a/b/XB-35.jpg"

    def __init__(self):
        self.calls = []

    async def get(self, url, params=None, **kwargs):
        params = params or {}
        self.calls.append(dict(params))
        if "iiurlwidth" in params:
            w = params["iiurlwidth"]
            if w < 1280:
                thumb = (f"https://upload.wikimedia.org/wikipedia/commons/"
                         f"thumb/a/b/XB-35.jpg/{w}px-XB-35.jpg")
                return _FakeResp(
                    {"query": {"pages": {"1": {"imageinfo": [{"thumburl": thumb}]}}}})
            # Close to (or above) the true original width — MediaWiki
            # refuses to issue a thumb and just echoes the raw url.
            return _FakeResp(
                {"query": {"pages": {"1": {"imageinfo": [{"thumburl": self.RAW_URL}]}}}})
        # The OLD code's second branch: a plain size pre-check (iiprop=size,
        # no iiurlwidth) to compute "original_width - 1". Only the PRE-fix
        # code path ever sends this shape.
        return _FakeResp(
            {"query": {"pages": {"1": {"imageinfo": [{"width": self.ORIGINAL_WIDTH}]}}}})


@pytest.fixture(autouse=True)
def _fast_wm_get(monkeypatch):
    """Skip the real _wm_get's politeness throttle/retry (1.5s+ per call,
    real 429/403 handling) — irrelevant to what these tests check and would
    make the suite slow. A plain passthrough is enough with the fakes above,
    which never return a non-2xx status."""
    async def _passthrough(c, url, **kwargs):
        return await c.get(url, **kwargs)
    monkeypatch.setattr(static_docu, "_wm_get", _passthrough)


# ---------------------------------------------------------------------------
# 1. _api_issued_thumb width ladder.
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_api_issued_thumb_ladder_falls_through_to_1024():
    """widths >=1280 must echo the raw url (per the fake); 1024 is the first
    width that gets a real /thumb/ issued. The fixed ladder must return that
    thumb url instead of giving up."""
    c = _FakeWMClient()
    result = await static_docu._api_issued_thumb(c, _FakeWMClient.RAW_URL)
    assert result is not None
    assert "/thumb/" in result
    assert "1024px-XB-35.jpg" in result


@pytest.mark.asyncio
async def test_api_issued_thumb_ladder_tries_widths_in_descending_order():
    c = _FakeWMClient()
    await static_docu._api_issued_thumb(c, _FakeWMClient.RAW_URL)
    widths_tried = [p["iiurlwidth"] for p in c.calls if "iiurlwidth" in p]
    assert widths_tried == [1600, 1280, 1024]


@pytest.mark.asyncio
async def test_api_issued_thumb_returns_none_when_nothing_ever_clears():
    """Every rung of the ladder still echoes the raw url (simulated by a
    client that always answers >=1280-style), and even the size query gives
    no usable width — must give up cleanly, not raise, and not return a
    non-thumb url."""
    class _AlwaysRaw(_FakeWMClient):
        async def get(self, url, params=None, **kwargs):
            params = params or {}
            self.calls.append(dict(params))
            return _FakeResp(
                {"query": {"pages": {"1": {"imageinfo": [{"thumburl": self.RAW_URL}]}}}})

    result = await static_docu._api_issued_thumb(_AlwaysRaw(), _FakeWMClient.RAW_URL)
    assert result is None


@pytest.mark.asyncio
async def test_api_issued_thumb_dynamic_last_rung_for_small_original():
    """An 800px-wide original (old 1940s archival scan) sits in MediaWiki's
    "too close to original, no thumb issued" dead zone at EVERY static rung
    (1600/1280/1024/800/640 all echo the raw url). The fix's dynamic last
    rung must then query the true size and get a real /thumb/ issued at
    floor(800 * 0.6) = 480 — and the size query must only happen AFTER all
    static rungs failed, not up front."""
    class _SmallOriginal(_FakeWMClient):
        ORIGINAL_WIDTH = 800
        RAW_URL = ("https://upload.wikimedia.org/wikipedia/commons/"
                   "c/d/Small_archival_scan.jpg")

        async def get(self, url, params=None, **kwargs):
            params = params or {}
            self.calls.append(dict(params))
            if "iiurlwidth" in params:
                w = params["iiurlwidth"]
                if w == 480:
                    thumb = (f"https://upload.wikimedia.org/wikipedia/commons/"
                             f"thumb/c/d/Small_archival_scan.jpg/"
                             f"{w}px-Small_archival_scan.jpg")
                    return _FakeResp({"query": {"pages": {"1": {
                        "imageinfo": [{"thumburl": thumb}]}}}})
                # Every static rung is in the dead zone for this original.
                return _FakeResp({"query": {"pages": {"1": {
                    "imageinfo": [{"thumburl": self.RAW_URL}]}}}})
            # iiprop=size query — the dynamic rung's true-width lookup.
            return _FakeResp({"query": {"pages": {"1": {
                "imageinfo": [{"width": self.ORIGINAL_WIDTH}]}}}})

    c = _SmallOriginal()
    result = await static_docu._api_issued_thumb(c, _SmallOriginal.RAW_URL)
    assert result is not None
    assert "/thumb/" in result
    assert "480px-Small_archival_scan.jpg" in result

    widths_tried = [p["iiurlwidth"] for p in c.calls if "iiurlwidth" in p]
    assert widths_tried == [1600, 1280, 1024, 800, 640, 480]
    # The size query (iiprop=size, no iiurlwidth) must come AFTER all five
    # static rungs and BEFORE the final dynamic request.
    size_query_positions = [i for i, p in enumerate(c.calls)
                            if "iiurlwidth" not in p]
    assert size_query_positions == [5]


@pytest.mark.asyncio
async def test_api_issued_thumb_dynamic_rung_floors_at_320():
    """A tiny original (e.g. 400px) must be asked for max(320, 400*0.6)=320,
    never something below the floor."""
    class _TinyOriginal(_FakeWMClient):
        RAW_URL = ("https://upload.wikimedia.org/wikipedia/commons/"
                   "e/f/Tiny_photo.jpg")

        async def get(self, url, params=None, **kwargs):
            params = params or {}
            self.calls.append(dict(params))
            if "iiurlwidth" in params:
                if params["iiurlwidth"] == 320:
                    return _FakeResp({"query": {"pages": {"1": {
                        "imageinfo": [{"thumburl":
                            "https://upload.wikimedia.org/wikipedia/commons/"
                            "thumb/e/f/Tiny_photo.jpg/320px-Tiny_photo.jpg"}]}}}})
                return _FakeResp({"query": {"pages": {"1": {
                    "imageinfo": [{"thumburl": self.RAW_URL}]}}}})
            return _FakeResp({"query": {"pages": {"1": {
                "imageinfo": [{"width": 400}]}}}})

    c = _TinyOriginal()
    result = await static_docu._api_issued_thumb(c, _TinyOriginal.RAW_URL)
    assert result is not None and "320px-Tiny_photo.jpg" in result
    widths_tried = [p["iiurlwidth"] for p in c.calls if "iiurlwidth" in p]
    assert widths_tried[-1] == 320


# ---------------------------------------------------------------------------
# 2. Commons designation-token trust promotion.
# ---------------------------------------------------------------------------

def test_commons_title_matches_promotes_designation_hit():
    assert static_docu._commons_title_matches(
        "Northrop XB-35", [], "Northrop XB-35 11-300.jpg") is True


def test_commons_title_matches_rejects_unrelated_file():
    assert static_docu._commons_title_matches(
        "Northrop XB-35", [], "B-2 Spirit stealth bomber over California.jpg") is False


def test_commons_title_matches_checks_aliases_too():
    # The file title carries the ALIAS's designation token ("yb35"), not the
    # primary machine name's ("xb35") — the alias check alone must promote it.
    assert static_docu._commons_title_matches(
        "Northrop XB-35", ["YB-35"], "Northrop_YB-35_flying_wing.jpg") is True


def test_commons_title_matches_excludes_short_two_char_token():
    # A degenerate 2-char designation token (e.g. bare "B2") must not be
    # trusted just because it happens to appear inside a file name — the
    # >=3 char floor exists precisely to stop this kind of false match.
    assert static_docu._commons_title_matches("B2", [], "b2.jpg") is False


@pytest.mark.asyncio
async def test_find_commons_photos_returns_title_alongside_url(monkeypatch):
    """find_commons_photos must now return {"url", "title"} dicts (not bare
    url strings) so _one_scene can check the designation token against the
    Commons file title."""
    class _CommonsClient:
        def __init__(self):
            self.n = 0

        async def get(self, url, params=None, **kwargs):
            params = params or {}
            action_list = params.get("list")
            if action_list == "search":
                return _FakeResp({"query": {"search": [
                    {"title": "File:Northrop_XB-35_11-300.jpg"},
                ]}})
            # imageinfo lookup for the search hit
            return _FakeResp({"query": {"pages": {"1": {
                "title": "File:Northrop_XB-35_11-300.jpg",
                "imageinfo": [{
                    "width": 1600, "height": 1200,
                    "url": "https://upload.wikimedia.org/wikipedia/commons/a/b/x.jpg",
                    "thumburl": "https://upload.wikimedia.org/wikipedia/commons/"
                                "thumb/a/b/x.jpg/1600px-x.jpg",
                }],
            }}}})

    def _factory(*a, **k):
        return _ClientCM(_CommonsClient())
    monkeypatch.setattr(static_docu.httpx, "AsyncClient", _factory)

    out = await static_docu.find_commons_photos("Northrop XB-35 bomber")
    assert out, "expected at least one candidate"
    assert isinstance(out[0], dict)
    assert out[0]["title"] == "File:Northrop_XB-35_11-300.jpg"
    assert "/thumb/" in out[0]["url"]


class _ClientCM:
    """Wraps a fake client so `async with httpx.AsyncClient(...) as c:` works
    (find_commons_photos/find_article_images open their own client, unlike
    _api_issued_thumb which receives one)."""

    def __init__(self, inner):
        self._inner = inner

    async def __aenter__(self):
        return self._inner

    async def __aexit__(self, *a):
        return False


# ---------------------------------------------------------------------------
# 3. FAIL CLOSED — no verified reference means no generation, ever.
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_no_verified_reference_blocks_instead_of_generating(monkeypatch):
    """All lookup layers (cache, lead image, article images, Commons) come up
    empty -> the scene must be BLOCKED, never handed to the image generator.
    This is the core regression test for defect #3 (the old FAIL-OPEN path
    that generated text-to-image and shipped status='done')."""
    import uuid
    import shared.clients.image_client as image_client_mod

    video_id = str(uuid.uuid4())
    tenant_id = str(uuid.uuid4())

    db_rows = {
        "assets": {},  # row_id -> dict of column values
    }

    async def fake_fetch_one(query, *args):
        if "FROM videos" in query:
            return {"id": video_id, "video_title": "Test Video",
                     "aspect": "16:9", "research_payload": None}
        if "FROM static_reference_cache" in query:
            return None  # no cached reference -> must run the lookup layers
        return None

    async def fake_fetch_all(query, *args):
        if "FROM scripts" in query:
            return [{"scene": 1,
                      "scene_text": "The Northrop XB-35 flying wing bomber never "
                                    "entered production."}]
        return []

    async def fake_execute(query, *args):
        if "INSERT INTO assets" in query:
            row_id = args[0]
            db_rows["assets"][row_id] = {
                "status": "generating", "image_url": None, "drive_image_url": None,
            }
        elif "UPDATE assets SET drive_image_url" in query:
            row_id, val = args[0], args[1]
            db_rows["assets"].setdefault(row_id, {})["drive_image_url"] = val
        elif "UPDATE assets SET status='blocked_no_reference'" in query:
            row_id = args[0]
            row = db_rows["assets"].setdefault(row_id, {})
            row["status"] = "blocked_no_reference"
            row["image_url"] = None
            row["drive_image_url"] = None
        elif "DELETE FROM assets WHERE id=" in query:
            db_rows["assets"].pop(args[0], None)
        return None

    async def fake_get_secret(name, *a, **k):
        if name == "kie_ai_api_key":
            return "fake-kie-key-for-test"
        return None  # no anthropic key -> _vision_confirms would fall open,
        # but it must never even be CALLED in this test (no candidates).

    class _FakeTextClient:
        async def generate(self, **kwargs):
            return ('[{"scene": 1, "machine": "Northrop XB-35", "aliases": [], '
                    '"caption_title": "XB-35", '
                    '"caption_sub": "Flying wing bomber • USAAF • 1946-1949", '
                    '"search_query": "Northrop XB-35 bomber"}]')

    async def fake_get_text_client_for_tenant(tenant_id):
        return _FakeTextClient()

    async def _empty_lead_images(names, limit=3):
        return []

    async def _empty_article_images(names, limit=5):
        return []

    async def _empty_commons_photos(query, limit=3):
        return []

    generate_calls = []

    async def _must_not_generate(self, *a, **k):
        generate_calls.append((a, k))
        raise AssertionError(
            "generate_scene_image_gpt must NEVER be called when no verified "
            "reference exists — reference-free generation must be impossible")

    monkeypatch.setattr(static_docu, "fetch_one", fake_fetch_one)
    monkeypatch.setattr(static_docu, "fetch_all", fake_fetch_all)
    monkeypatch.setattr(static_docu, "execute", fake_execute)
    monkeypatch.setattr(static_docu, "find_wikipedia_lead_images", _empty_lead_images)
    monkeypatch.setattr(static_docu, "find_article_images", _empty_article_images)
    monkeypatch.setattr(static_docu, "find_commons_photos", _empty_commons_photos)

    import vault
    monkeypatch.setattr(vault, "get_secret", fake_get_secret)
    import kie_unified
    monkeypatch.setattr(kie_unified, "get_text_client_for_tenant",
                        fake_get_text_client_for_tenant)
    monkeypatch.setattr(image_client_mod.ImageClient, "generate_scene_image_gpt",
                        _must_not_generate)

    result = await static_docu.generate_static_images_for_video(video_id, tenant_id)

    assert not generate_calls, "image generation must not have been attempted"
    assert result["status"] == "failed"
    assert "1" in result["error"]  # scene 1 reported as the failed scene id

    assert len(db_rows["assets"]) == 1
    row = next(iter(db_rows["assets"].values()))
    assert row["status"] == "blocked_no_reference"
    assert row["image_url"] is None
    assert row["drive_image_url"] is None
