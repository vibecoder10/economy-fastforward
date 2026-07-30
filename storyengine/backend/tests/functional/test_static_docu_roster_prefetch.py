"""Tests for chunks C3 + C3b (2026-07-21): roster-time reference-photo
prefetch, and batching the Wikimedia calls that back it.

Problem being solved: static_docu.generate_static_images_for_video (C1, see
test_static_docu_reference_fail_closed.py) discovers whether a machine even
HAS a findable reference photo at IMAGE GENERATION time — after script and
voice money is already spent — and a burst of per-machine Wikimedia lookups
mid-generation is exactly what triggered live rate-limit cooldowns on the
VPS.

C3 fix: the instant a static-docu video's machine roster is LOCKED (research
completion), prefetch_roster_references walks every roster machine, runs the
SAME candidate chain _one_scene uses (_gather_reference_candidates), and
writes static_reference_cache — so generation later always hits a warm
cache. dispatch_roster_prefetch is the fire-and-forget hook both research-
completion seams (the paid `research` verb and the free `submit_research`
MCP ingest) call.

C3b fix: _api_issued_thumbs_batch resolves MANY files' thumb URLs in a
handful of batched imageinfo calls (up to 50 titles per call) instead of one
call per file per width rung. find_article_images and find_commons_photos
(the multi-file paths) now use it; _api_issued_thumb (single file) delegates
to it with a 1-element list.

Run:
    cd storyengine/backend && ./venv/bin/python -m pytest \
        tests/functional/test_static_docu_roster_prefetch.py -q
"""
import asyncio
import os
import sys
import uuid
from pathlib import Path

import pytest

_BACKEND = os.path.join(os.path.dirname(__file__), "..", "..")
sys.path.insert(0, os.path.abspath(_BACKEND))

_REPO_ROOT = Path(__file__).resolve().parents[4]
_PIPELINE_ROOT = _REPO_ROOT / "skills" / "video-pipeline"
if str(_PIPELINE_ROOT) not in sys.path:
    sys.path.insert(0, str(_PIPELINE_ROOT))

import static_docu  # noqa: E402
import research_ingest  # noqa: E402


class _FakeResp:
    def __init__(self, body):
        self._body = body

    def json(self):
        return self._body

    def raise_for_status(self):
        pass


@pytest.fixture(autouse=True)
def _fast_wm_get(monkeypatch):
    """Same passthrough as test_static_docu_reference_fail_closed.py — skip
    the real politeness throttle, irrelevant to what these tests check."""
    async def _passthrough(c, url, **kwargs):
        return await c.get(url, **kwargs)
    monkeypatch.setattr(static_docu, "_wm_get", _passthrough)


class _ClientCM:
    """Wraps a fake client so `async with httpx.AsyncClient(...) as c:` works."""

    def __init__(self, inner):
        self._inner = inner

    async def __aenter__(self):
        return self._inner

    async def __aexit__(self, *a):
        return False


# ---------------------------------------------------------------------------
# 1. C3b — batched imageinfo helper: many files resolve in a handful of
#    calls, not one call per file per width rung.
# ---------------------------------------------------------------------------

class _BatchWMClient:
    """Models a candidate set of 3 files, each resolving at a DIFFERENT
    width rung: A resolves immediately at 1600, B needs to fall to 1024,
    and C never resolves at a static rung and needs the dynamic last rung
    (true width 700 -> target 420)."""

    RAW = {
        "A": "https://upload.wikimedia.org/wikipedia/commons/a/1/A.jpg",
        "B": "https://upload.wikimedia.org/wikipedia/commons/b/2/B.jpg",
        "C": "https://upload.wikimedia.org/wikipedia/commons/c/3/C.jpg",
    }

    def __init__(self):
        self.calls = []

    async def get(self, url, params=None, **kwargs):
        params = params or {}
        self.calls.append(dict(params))
        titles = params.get("titles", "")
        requested = [t[len("File:"):] for t in titles.split("|") if t]

        if "iiurlwidth" in params:
            width = params["iiurlwidth"]
            pages = {}
            for i, fname in enumerate(requested):
                if fname == "A.jpg" and width <= 1600:
                    thumb = f"https://upload.wikimedia.org/wikipedia/commons/thumb/a/1/A.jpg/{width}px-A.jpg"
                    pages[str(i)] = {"title": f"File:{fname}", "imageinfo": [{"thumburl": thumb}]}
                elif fname == "B.jpg" and width <= 1024:
                    thumb = f"https://upload.wikimedia.org/wikipedia/commons/thumb/b/2/B.jpg/{width}px-B.jpg"
                    pages[str(i)] = {"title": f"File:{fname}", "imageinfo": [{"thumburl": thumb}]}
                elif fname == "C.jpg" and width == 420:
                    thumb = f"https://upload.wikimedia.org/wikipedia/commons/thumb/c/3/C.jpg/{width}px-C.jpg"
                    pages[str(i)] = {"title": f"File:{fname}", "imageinfo": [{"thumburl": thumb}]}
                else:
                    # Dead zone: MediaWiki echoes the raw url back, never a thumb.
                    pages[str(i)] = {"title": f"File:{fname}",
                                     "imageinfo": [{"thumburl": self.RAW[fname[0]]}]}
            return _FakeResp({"query": {"pages": pages}})

        # iiprop=size query (the dynamic last rung's true-width lookup).
        pages = {}
        for i, fname in enumerate(requested):
            if fname == "C.jpg":
                pages[str(i)] = {"title": f"File:{fname}", "imageinfo": [{"width": 700}]}
        return _FakeResp({"query": {"pages": pages}})


@pytest.mark.asyncio
async def test_batched_thumbs_resolve_many_files_in_few_calls():
    c = _BatchWMClient()
    raw_urls = list(_BatchWMClient.RAW.values())
    result = await static_docu._api_issued_thumbs_batch(c, raw_urls)

    assert "1600px-A.jpg" in result[_BatchWMClient.RAW["A"]]
    assert "1024px-B.jpg" in result[_BatchWMClient.RAW["B"]]
    assert "420px-C.jpg" in result[_BatchWMClient.RAW["C"]]

    # The whole point of C3b: a 3-file candidate set spanning 3 different
    # resolution rungs (A at 1600, B needing the 1024 rung, C needing the
    # full ladder + the dynamic last rung) must resolve in ONE BATCHED call
    # per rung actually needed (7 here: 5 static + 1 size + 1 dynamic),
    # never one call PER FILE per rung (a naive per-file walk would cost
    # 1 + 3 + 7 = 11 calls minimum for this exact scenario, and up to
    # 3 * 6 = 18 in the worst case).
    assert len(c.calls) <= 7, f"expected <=7 batched calls, got {len(c.calls)}: {c.calls}"

    # Every call must have queried more than one title at once (batching,
    # not one-file-per-call) for at least the first rung, where all 3 files
    # are still pending.
    first_call_titles = c.calls[0]["titles"].split("|")
    assert len(first_call_titles) == 3


@pytest.mark.asyncio
async def test_api_issued_thumb_single_file_still_works_via_batch_delegate():
    """C3b must not regress the single-file path — _api_issued_thumb still
    returns a thumb url when it delegates to the batched helper with a
    1-element list."""
    c = _BatchWMClient()
    result = await static_docu._api_issued_thumb(c, _BatchWMClient.RAW["B"])
    assert result is not None
    assert "1024px-B.jpg" in result


@pytest.mark.asyncio
async def test_batched_thumbs_demux_uses_mediawiki_normalized_map():
    """MediaWiki normalizes requested titles (first-letter capitalization,
    underscore->space) and returns pages under the NORMALIZED title, with a
    query.normalized [{from, to}] map as the authoritative answer key. A
    multi-title batch where one title normalizes in a way the heuristic
    would NOT predict ("File:xb-35_test.jpg" -> "File:Xb-35 test.jpg" —
    case-changed, so _file_title_to_key's verbatim-echo match fails) must
    still map the thumb back to the right raw URL via the normalized map."""
    RAW_PLAIN = "https://upload.wikimedia.org/wikipedia/commons/a/1/A.jpg"
    RAW_WEIRD = "https://upload.wikimedia.org/wikipedia/commons/x/9/xb-35_test.jpg"

    class _NormalizingClient:
        def __init__(self):
            self.calls = []

        async def get(self, url, params=None, **kwargs):
            params = params or {}
            self.calls.append(dict(params))
            requested = [t for t in params.get("titles", "").split("|") if t]
            assert "iiurlwidth" in params  # both resolve at the first rung
            width = params["iiurlwidth"]
            body = {"query": {"pages": {}}}
            normalized = []
            for i, req in enumerate(requested):
                if req == "File:xb-35_test.jpg":
                    # MediaWiki rewrites the title and answers under the
                    # NORMALIZED form only.
                    normalized.append({"from": req, "to": "File:Xb-35 test.jpg"})
                    body["query"]["pages"][str(i)] = {
                        "title": "File:Xb-35 test.jpg",
                        "imageinfo": [{"thumburl":
                            "https://upload.wikimedia.org/wikipedia/commons/"
                            f"thumb/x/9/Xb-35_test.jpg/{width}px-Xb-35_test.jpg"}],
                    }
                else:
                    body["query"]["pages"][str(i)] = {
                        "title": req,
                        "imageinfo": [{"thumburl":
                            "https://upload.wikimedia.org/wikipedia/commons/"
                            f"thumb/a/1/A.jpg/{width}px-A.jpg"}],
                    }
            if normalized:
                body["query"]["normalized"] = normalized
            return _FakeResp(body)

    c = _NormalizingClient()
    result = await static_docu._api_issued_thumbs_batch(c, [RAW_PLAIN, RAW_WEIRD])

    # Multi-title batch (2 titles in one call), so the single-title
    # unambiguous path can't be what saved us.
    assert len(c.calls[0]["titles"].split("|")) == 2
    assert result[RAW_PLAIN] is not None and "px-A.jpg" in result[RAW_PLAIN]
    assert result[RAW_WEIRD] is not None
    assert "px-Xb-35_test.jpg" in result[RAW_WEIRD]


@pytest.mark.asyncio
async def test_batched_thumbs_never_returns_non_thumb_url():
    """A file that never clears any rung (and has no usable true width) must
    resolve to None, not the raw/echoed url."""
    class _NeverResolves(_BatchWMClient):
        async def get(self, url, params=None, **kwargs):
            params = params or {}
            self.calls.append(dict(params))
            titles = params.get("titles", "")
            requested = [t[len("File:"):] for t in titles.split("|") if t]
            if "iiurlwidth" in params:
                pages = {str(i): {"title": f"File:{f}",
                                  "imageinfo": [{"thumburl": "https://upload.wikimedia.org/wikipedia/commons/z/z/Z.jpg"}]}
                         for i, f in enumerate(requested)}
                return _FakeResp({"query": {"pages": pages}})
            return _FakeResp({"query": {"pages": {}}})  # size query: no width ever comes back

    c = _NeverResolves()
    result = await static_docu._api_issued_thumbs_batch(c, [_BatchWMClient.RAW["A"]])
    assert result[_BatchWMClient.RAW["A"]] is None


# ---------------------------------------------------------------------------
# 2. C3 — prefetch_roster_references: happy path, miss path, resilience.
# ---------------------------------------------------------------------------

def _static_docu_video_row(video_id, roster):
    return {
        "id": video_id,
        "render_mode": "static_docu",
        "research_payload": {
            "documentary_style": "designed_vs_used",
            "unit_roster": roster,
        },
    }


@pytest.mark.asyncio
async def test_prefetch_happy_path_writes_cache_and_never_calls_image_client(monkeypatch):
    """A machine with a findable, vision-confirmed photo must end up cached
    — and the image-generation client must NEVER be touched by prefetch;
    this stage only sources and verifies the REFERENCE photo, not the final
    studio render."""
    import shared.clients.image_client as image_client_mod

    video_id = str(uuid.uuid4())
    tenant_id = str(uuid.uuid4())
    roster = ["Boeing XB-15", "Northrop XB-35", "Convair YB-60"]
    video_row = _static_docu_video_row(video_id, roster)

    cache_writes = []

    async def fake_fetch_one(query, *args):
        if "FROM videos" in query:
            return dict(video_row)
        if "FROM static_reference_cache" in query:
            return None  # nothing cached yet -> must run the lookup chain
        return None

    async def fake_execute(query, *args):
        if "INSERT INTO static_reference_cache" in query:
            cache_writes.append(args)
        return None

    async def fake_lead_images(names, limit=3):
        return [{"url": f"https://en.wikipedia.org/thumb/{names[0]}.jpg",
                 "page": names[0], "trusted": True}]

    async def fake_article_images(names, limit=5):
        return []

    async def fake_commons_photos(query, limit=3):
        return []

    async def fake_host_reference(url, vid, tid, tag):
        return f"https://storage.example/{tag}.jpg"

    async def fake_vision_confirms(tid, image_url, machine, aliases=None, trusted_source=False, facts=None, source_label=None):
        return True  # every candidate passes

    generate_calls = []

    async def _must_not_generate(self, *a, **k):
        generate_calls.append((a, k))
        raise AssertionError(
            "prefetch_roster_references must NEVER call the image "
            "generation client — it only sources/verifies REFERENCE photos")

    monkeypatch.setattr(static_docu, "fetch_one", fake_fetch_one)
    monkeypatch.setattr(static_docu, "execute", fake_execute)
    monkeypatch.setattr(static_docu, "find_wikipedia_lead_images", fake_lead_images)
    monkeypatch.setattr(static_docu, "find_article_images", fake_article_images)
    monkeypatch.setattr(static_docu, "find_commons_photos", fake_commons_photos)
    monkeypatch.setattr(static_docu, "_host_reference", fake_host_reference)
    monkeypatch.setattr(static_docu, "_vision_confirms", fake_vision_confirms)
    monkeypatch.setattr(image_client_mod.ImageClient, "generate_scene_image_gpt", _must_not_generate)

    result = await static_docu.prefetch_roster_references(video_id, tenant_id)

    assert not generate_calls, "image generation must never be attempted by prefetch"
    assert result["status"] == "completed"
    assert result["roster_count"] == 3
    assert result["verified"] == 3
    assert result["missed"] == 0
    assert len(cache_writes) == 3
    for args in cache_writes:
        tenant_arg, machine_key_arg, machine_arg, hosted_arg, source_arg = args
        assert tenant_arg == tenant_id
        assert hosted_arg.startswith("https://storage.example/roster")
        assert machine_arg in roster


@pytest.mark.asyncio
async def test_prefetch_miss_path_no_cache_row_no_exception(monkeypatch):
    """Every lookup layer comes up empty -> the machine must be recorded as
    a MISS (no cache row written), and the sweep must complete without
    raising — this is the roster-time analogue of C1's fail-closed law."""
    video_id = str(uuid.uuid4())
    tenant_id = str(uuid.uuid4())
    roster = ["Boeing XB-15", "Northrop XB-35", "Convair YB-60"]
    video_row = _static_docu_video_row(video_id, roster)

    cache_writes = []

    async def fake_fetch_one(query, *args):
        if "FROM videos" in query:
            return dict(video_row)
        if "FROM static_reference_cache" in query:
            return None
        return None

    async def fake_execute(query, *args):
        if "INSERT INTO static_reference_cache" in query:
            cache_writes.append(args)
        return None

    async def _empty(*a, **k):
        return []

    monkeypatch.setattr(static_docu, "fetch_one", fake_fetch_one)
    monkeypatch.setattr(static_docu, "execute", fake_execute)
    monkeypatch.setattr(static_docu, "find_wikipedia_lead_images", _empty)
    monkeypatch.setattr(static_docu, "find_article_images", _empty)
    monkeypatch.setattr(static_docu, "find_commons_photos", _empty)

    result = await static_docu.prefetch_roster_references(video_id, tenant_id)

    assert result["status"] == "completed"
    assert result["roster_count"] == 3
    assert result["verified"] == 0
    assert result["missed"] == 3
    assert cache_writes == []


@pytest.mark.asyncio
async def test_prefetch_one_machine_exception_does_not_kill_the_sweep(monkeypatch):
    """One machine's candidate-lookup blowing up with an exception must not
    abort the rest of the roster — it's recorded as a miss and the sweep
    continues to the next machine."""
    video_id = str(uuid.uuid4())
    tenant_id = str(uuid.uuid4())
    roster = ["Boeing XB-15", "Northrop XB-35", "Convair YB-60"]
    video_row = _static_docu_video_row(video_id, roster)

    cache_writes = []

    async def fake_fetch_one(query, *args):
        if "FROM videos" in query:
            return dict(video_row)
        if "FROM static_reference_cache" in query:
            return None
        return None

    async def fake_execute(query, *args):
        if "INSERT INTO static_reference_cache" in query:
            cache_writes.append(args)
        return None

    async def fake_lead_images(names, limit=3):
        if names[0] == "Boeing XB-15":
            raise RuntimeError("simulated Wikimedia blowup for XB-15")
        return [{"url": f"https://en.wikipedia.org/thumb/{names[0]}.jpg",
                 "page": names[0], "trusted": True}]

    async def _empty(*a, **k):
        return []

    async def fake_host_reference(url, vid, tid, tag):
        return f"https://storage.example/{tag}.jpg"

    async def fake_vision_confirms(*a, **k):
        return True

    monkeypatch.setattr(static_docu, "fetch_one", fake_fetch_one)
    monkeypatch.setattr(static_docu, "execute", fake_execute)
    monkeypatch.setattr(static_docu, "find_wikipedia_lead_images", fake_lead_images)
    monkeypatch.setattr(static_docu, "find_article_images", _empty)
    monkeypatch.setattr(static_docu, "find_commons_photos", _empty)
    monkeypatch.setattr(static_docu, "_host_reference", fake_host_reference)
    monkeypatch.setattr(static_docu, "_vision_confirms", fake_vision_confirms)

    result = await static_docu.prefetch_roster_references(video_id, tenant_id)

    assert result["status"] == "completed"
    assert result["roster_count"] == 3
    assert result["missed"] == 1    # XB-15 blew up
    assert result["verified"] == 2  # XB-35 and YB-60 still got cached
    assert len(cache_writes) == 2
    cached_machines = {args[2] for args in cache_writes}
    assert cached_machines == {"Northrop XB-35", "Convair YB-60"}


@pytest.mark.asyncio
async def test_prefetch_skips_video_with_no_locked_roster(monkeypatch):
    """A video that isn't a locked-roster static-docu documentary yet (or
    isn't static_docu at all) must be a clean no-op, not an error."""
    video_id = str(uuid.uuid4())
    tenant_id = str(uuid.uuid4())

    async def fake_fetch_one(query, *args):
        if "FROM videos" in query:
            return {"id": video_id, "render_mode": "coverage", "research_payload": None}
        return None

    monkeypatch.setattr(static_docu, "fetch_one", fake_fetch_one)

    result = await static_docu.prefetch_roster_references(video_id, tenant_id)

    assert result["status"] == "skipped"


# ---------------------------------------------------------------------------
# 2b. 2026-07-29 fix: ship-class roster entries whose glued display name
# (designation + name, via pipeline_executor._unit_display_name) is
# unsearchable now get found through a derived ALIAS instead. Real misses
# from "Every British Aircraft Carrier Class Ever Built" (2026-07-27, video
# d2e37cd6-521a-43aa-a14d-ce096a783c1e): 6 of 23 roster machines never got a
# verified reference photo. 4 of those 6 are genuinely searchable and are
# reproduced here; the other 2 (a never-built design, and one that likely
# failed the vision check rather than the search) are NOT reproduced since
# aliases can't fix either of those.
# ---------------------------------------------------------------------------

def _ship_class_roster_video(video_id: str) -> dict:
    """The 4 genuinely-searchable misses from the live roster, as structured
    unit_roster entries (not the flat glued strings the old prefetch path
    was stuck with)."""
    roster_items = [
        {"name": "Attacker class (US-built)", "designation": "Lend-Lease escort carriers"},
        {"name": "Ruler class (US-built)", "designation": "Lend-Lease escort carriers"},
        {"name": "Audacious class / Malta class", "designation": "CVA-01 predecessors"},
        {"name": "Archer class / Empire Mac-Ship conversions", "designation": "CAM ships and MAC ships"},
    ]
    return {
        "id": video_id,
        "render_mode": "static_docu",
        "research_payload": {
            "documentary_style": "designed_vs_used",
            "unit_roster": roster_items,
        },
    }


@pytest.mark.asyncio
async def test_prefetch_finds_ship_class_misses_via_derived_aliases(monkeypatch):
    """A Wikipedia lookup that only ever matches a real, bare class/member-
    ship name — never the glued designation+name display string
    ("Lend-Lease escort carriers Attacker class (US-built)") — must still
    find and verify every one of the 4 machines, because
    prefetch_roster_references now derives and passes real aliases
    (pipeline_executor._machine_documentary_hold_roster_entries /
    _unit_roster_aliases) through to _prefetch_one_machine ->
    _gather_reference_candidates. Before this fix, _prefetch_one_machine
    called `_gather_reference_candidates(machine, None, machine)` — no
    aliases ever reached the lookup, so all 4 of these would have missed."""
    video_id = str(uuid.uuid4())
    tenant_id = str(uuid.uuid4())
    video_row = _ship_class_roster_video(video_id)

    # Real Wikipedia article titles for these classes — reachable only via
    # the bare split alias, never the full glued display string.
    alias_hits = {
        "Attacker class (US-built)": ("https://en.wikipedia.org/thumb/Attacker.jpg", "Attacker-class escort carrier"),
        "Ruler class (US-built)": ("https://en.wikipedia.org/thumb/Ruler.jpg", "Ruler-class escort carrier"),
        "Audacious class": ("https://en.wikipedia.org/thumb/Audacious.jpg", "Audacious-class aircraft carrier"),
        "Malta class": ("https://en.wikipedia.org/thumb/Malta.jpg", "Malta-class aircraft carrier"),
        "Archer class": ("https://en.wikipedia.org/thumb/Archer.jpg", "Archer-class escort carrier"),
        "Empire Mac-Ship conversions": ("https://en.wikipedia.org/thumb/EmpireMac.jpg", "MAC ship"),
    }

    cache_writes = []
    lookup_calls = []

    async def fake_fetch_one(query, *args):
        if "FROM videos" in query:
            return dict(video_row)
        if "FROM static_reference_cache" in query:
            return None
        return None

    async def fake_execute(query, *args):
        if "INSERT INTO static_reference_cache" in query:
            cache_writes.append(args)
        return None

    async def fake_lead_images(names, limit=3):
        lookup_calls.append(list(names))
        for n in names:
            if n in alias_hits:
                url, page = alias_hits[n]
                return [{"url": url, "page": page, "trusted": True}]
        return []

    async def fake_article_images(names, limit=5):
        return []

    async def fake_commons_photos(query, limit=3):
        return []

    async def fake_host_reference(url, vid, tid, tag):
        return f"https://storage.example/{tag}.jpg"

    async def fake_vision_confirms(tid, image_url, machine, aliases=None, trusted_source=False, facts=None, source_label=None):
        return True

    monkeypatch.setattr(static_docu, "fetch_one", fake_fetch_one)
    monkeypatch.setattr(static_docu, "execute", fake_execute)
    monkeypatch.setattr(static_docu, "find_wikipedia_lead_images", fake_lead_images)
    monkeypatch.setattr(static_docu, "find_article_images", fake_article_images)
    monkeypatch.setattr(static_docu, "find_commons_photos", fake_commons_photos)
    monkeypatch.setattr(static_docu, "_host_reference", fake_host_reference)
    monkeypatch.setattr(static_docu, "_vision_confirms", fake_vision_confirms)

    result = await static_docu.prefetch_roster_references(video_id, tenant_id)

    assert result["status"] == "completed"
    assert result["roster_count"] == 4
    assert result["verified"] == 4, f"expected all 4 to verify via alias, got: {result}"
    assert result["missed"] == 0
    assert len(cache_writes) == 4

    # Prove the alias was actually offered to the lookup, not just that the
    # sweep happened to pass some other way — every lookup call's `names`
    # list must have included at least one split alias beyond the raw
    # glued display name.
    glued_names = {
        "Lend-Lease escort carriers Attacker class (US-built)",
        "Lend-Lease escort carriers Ruler class (US-built)",
        "CVA-01 predecessors Audacious class / Malta class",
        "CAM ships and MAC ships Archer class / Empire Mac-Ship conversions",
    }
    for names in lookup_calls:
        assert names[0] in glued_names  # machine itself is always names[0]
        assert len(names) > 1, "aliases must have been passed alongside the machine name"


@pytest.mark.asyncio
async def test_prefetch_one_machine_without_aliases_still_misses_the_glued_name(monkeypatch):
    """Sanity check on the OLD behavior this fix replaces: calling
    _prefetch_one_machine with no aliases (the pre-fix call shape) against a
    lookup that only matches the bare class name must still MISS — this is
    what proves the aliases, not some other change, are what made the test
    above pass."""
    video_id = str(uuid.uuid4())
    tenant_id = str(uuid.uuid4())
    machine = "Lend-Lease escort carriers Attacker class (US-built)"

    async def fake_lead_images(names, limit=3):
        if "Attacker class (US-built)" in names:
            return [{"url": "https://en.wikipedia.org/thumb/Attacker.jpg",
                     "page": "Attacker-class escort carrier", "trusted": True}]
        return []

    async def fake_article_images(names, limit=5):
        return []

    async def fake_commons_photos(query, limit=3):
        return []

    monkeypatch.setattr(static_docu, "find_wikipedia_lead_images", fake_lead_images)
    monkeypatch.setattr(static_docu, "find_article_images", fake_article_images)
    monkeypatch.setattr(static_docu, "find_commons_photos", fake_commons_photos)

    # No aliases (aliases=None) — the exact call shape _prefetch_one_machine
    # used before this fix.
    candidates = await static_docu._gather_reference_candidates(machine, None, machine)
    assert candidates == [], "without aliases, the glued display name must still miss"

    # With the derived alias, the same lookup finds it.
    candidates_with_alias = await static_docu._gather_reference_candidates(
        machine, ["Attacker class (US-built)", "Lend-Lease escort carriers"], machine)
    assert len(candidates_with_alias) == 1


# ---------------------------------------------------------------------------
# 3. Research-hook dispatch: static_docu -> task dispatched; non-static -> not.
# ---------------------------------------------------------------------------

def test_dispatch_roster_prefetch_schedules_task_for_static_docu(monkeypatch):
    scheduled = []

    def fake_create_task(coro):
        scheduled.append(coro)
        coro.close()  # never actually run it — this test only checks dispatch
        return object()

    monkeypatch.setattr(asyncio, "create_task", fake_create_task)

    result = static_docu.dispatch_roster_prefetch(
        {"render_mode": "static_docu"}, "vid-1", "ten-1")

    assert result is True
    assert len(scheduled) == 1


def test_dispatch_roster_prefetch_skips_non_static_video(monkeypatch):
    scheduled = []

    def fake_create_task(coro):
        scheduled.append(coro)
        coro.close()
        return object()

    monkeypatch.setattr(asyncio, "create_task", fake_create_task)

    result = static_docu.dispatch_roster_prefetch(
        {"render_mode": "coverage"}, "vid-1", "ten-1")

    assert result is False
    assert scheduled == []


def test_dispatch_roster_prefetch_handles_missing_video_dict(monkeypatch):
    """A None/empty video dict must be treated as non-static, not raise."""
    scheduled = []

    def fake_create_task(coro):
        scheduled.append(coro)
        coro.close()
        return object()

    monkeypatch.setattr(asyncio, "create_task", fake_create_task)

    assert static_docu.dispatch_roster_prefetch(None, "vid-1", "ten-1") is False
    assert static_docu.dispatch_roster_prefetch({}, "vid-1", "ten-1") is False
    assert scheduled == []


@pytest.mark.asyncio
async def test_accept_submitted_research_dispatches_prefetch_for_static_docu(monkeypatch):
    """The free submit_research MCP ingest seam: on a successful accept for a
    static_docu video, research_ingest.accept_submitted_research must call
    the C3 dispatch hook with this video/video_id/tenant_id."""
    import pipeline_executor

    video = {"id": "v1", "tenant_id": "t1", "video_title": "A Normal Video Title",
             "video_length_minutes": 10, "deleted_at": None, "render_mode": "static_docu"}

    async def _fake_fetch_one(query, *args):
        return dict(video)

    async def _fake_execute(query, *args):
        return "UPDATE 1"

    dispatch_calls = []

    def _fake_dispatch(video_arg, video_id_arg, tenant_id_arg):
        dispatch_calls.append((video_arg, video_id_arg, tenant_id_arg))
        return True

    fake_roster_check = {"passed": True, "complete_title": False, "warnings": [], "gaps": []}
    monkeypatch.setattr(research_ingest, "fetch_one", _fake_fetch_one)
    monkeypatch.setattr(research_ingest, "execute", _fake_execute)
    monkeypatch.setattr(pipeline_executor, "_roster_validation", lambda *a, **k: fake_roster_check)
    monkeypatch.setattr(static_docu, "dispatch_roster_prefetch", _fake_dispatch)

    result = await research_ingest.accept_submitted_research(
        "t1", "v1", {"headline": "H", "thesis": "T", "executive_hook": "E"}, source="agent:Bot",
    )

    assert result["accepted"] is True
    assert len(dispatch_calls) == 1
    assert dispatch_calls[0][1] == "v1" and dispatch_calls[0][2] == "t1"
    assert dispatch_calls[0][0].get("render_mode") == "static_docu"


@pytest.mark.asyncio
async def test_accept_submitted_research_dispatch_noop_for_non_static_video(monkeypatch):
    """Same seam, non-static video: dispatch_roster_prefetch is still called
    (the single-line hook doesn't pre-filter), but it must itself decide not
    to schedule anything — proven here via the REAL dispatch_roster_prefetch
    (not a fake), asserting no task gets created."""
    import pipeline_executor

    video = {"id": "v2", "tenant_id": "t1", "video_title": "A Normal Video Title",
             "video_length_minutes": 10, "deleted_at": None, "render_mode": "coverage"}

    async def _fake_fetch_one(query, *args):
        return dict(video)

    async def _fake_execute(query, *args):
        return "UPDATE 1"

    scheduled = []

    def fake_create_task(coro):
        scheduled.append(coro)
        coro.close()
        return object()

    fake_roster_check = {"passed": True, "complete_title": False, "warnings": [], "gaps": []}
    monkeypatch.setattr(research_ingest, "fetch_one", _fake_fetch_one)
    monkeypatch.setattr(research_ingest, "execute", _fake_execute)
    monkeypatch.setattr(pipeline_executor, "_roster_validation", lambda *a, **k: fake_roster_check)
    monkeypatch.setattr(asyncio, "create_task", fake_create_task)

    result = await research_ingest.accept_submitted_research(
        "t1", "v2", {"headline": "H", "thesis": "T", "executive_hook": "E"}, source="agent:Bot",
    )

    assert result["accepted"] is True
    assert scheduled == [], "non-static video must never schedule a prefetch task"
