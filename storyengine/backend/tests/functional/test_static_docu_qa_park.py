"""Tests for the static-docu QA park fix (2026-07-22): a render that fails
post-generation QA twice is PARKED for operator review, never deleted.

The old reject path in `_one_scene` (generate_static_images_for_video) ran
`DELETE FROM assets WHERE id=...` when both the initial render and its one
retry failed `_render_matches_reference` — destroying paid renders on the
QA judge's word alone. PROVEN costly live on 2026-07-22: a QA-wording bug
(fixed in C2h) rejected 12 CORRECT renders and the DELETE destroyed all 12
(~$0.36 of paid generations, gone).

Fix (static_docu.py `_one_scene` + routes/pipeline.py):
- The double-reject path now KEEPS the asset row: status='qa_rejected',
  image_url NULL (render_static.py only ships rows with image_url IS NOT
  NULL, so a parked render can never leak into a video), drive_image_url =
  the render self-hosted to durable storage (falling back to the ephemeral
  provider URL only if hosting fails — still better than losing it).
- `_bounded`'s exception cleanup no longer sweeps up deliberately parked
  rows (qa_rejected / blocked_no_reference both carry image_url NULL by
  design).
- POST /api/pipeline/static-qa-approve/{asset_id} is the human YES: flips
  the parked row to status='done' and promotes drive_image_url to
  image_url, putting it back in render_static.py's shippable set.

Run:
    cd storyengine/backend && ./venv/bin/python -m pytest \
        tests/functional/test_static_docu_qa_park.py -q
"""
import os
import sys
import uuid

import pytest

_BACKEND = os.path.join(os.path.dirname(__file__), "..", "..")
sys.path.insert(0, os.path.abspath(_BACKEND))

import static_docu  # noqa: E402

# Pre-import for the same reason the C2f/C2g/C2h test files do: anthropic's
# _base_client.py subclasses httpx.AsyncClient at MODULE IMPORT time, so it
# must finish loading before any test monkeypatches httpx.AsyncClient to a
# fake callable.
import shared.clients.image_client as image_client_mod  # noqa: E402

REF_HOSTED = "https://storage.example/ref_cached.jpg"
REF_SOURCE = "https://commons.example/Boeing_XB-15.jpg"
RENDER_1 = "https://kie.example/render1.png"
RENDER_2 = "https://kie.example/render2.png"
DURABLE = "https://storage.example/durable.png"


class _ClientCM:
    """Wraps a fake client so `async with httpx.AsyncClient(...) as c:` works."""

    def __init__(self, inner):
        self._inner = inner

    async def __aenter__(self):
        return self._inner

    async def __aexit__(self, *a):
        return False


class _FakeDownloadResp:
    def __init__(self, content):
        self.content = content

    def raise_for_status(self):
        pass


def _pipeline_env(monkeypatch, *, verdicts, gen_urls, upload_raises=False):
    """Fake DB + provider world for generate_static_images_for_video, modeled
    on test_static_docu_reference_fail_closed. One scene, a CACHED verified
    reference (so no Wikimedia lookup layers run), a scripted sequence of
    generation URLs and QA verdicts. No network, no real DB anywhere."""
    video_id = str(uuid.uuid4())
    tenant_id = str(uuid.uuid4())

    env = {
        "video_id": video_id,
        "tenant_id": tenant_id,
        "assets": {},        # row_id -> dict of column values
        "queries": [],       # every execute() SQL string, in order
        "uploads": [],       # upload_bytes storage paths
        "downloads": [],     # URLs fetched via httpx
        "qa_calls": [],      # (render_url, ref_url) per _render_matches_reference
        "gen_prompts": [],   # prompt per generate_scene_image_gpt call
    }

    async def fake_fetch_one(query, *args):
        if "FROM videos" in query:
            return {"id": video_id, "video_title": "Test Video",
                    "aspect": "16:9", "research_payload": None}
        if "FROM static_reference_cache" in query:
            return {"hosted_url": REF_HOSTED, "source_url": REF_SOURCE}
        return None

    async def fake_fetch_all(query, *args):
        if "FROM scripts" in query:
            return [{"scene": 1,
                     "scene_text": "The Boeing XB-15 was the largest bomber "
                                   "of its day."}]
        return []

    async def fake_execute(query, *args):
        env["queries"].append(query)
        if "INSERT INTO assets" in query:
            env["assets"][args[0]] = {
                "status": "generating", "image_url": None,
                "drive_image_url": None, "image_prompt": None,
            }
        elif "UPDATE assets SET drive_image_url" in query:
            env["assets"].setdefault(args[0], {})["drive_image_url"] = args[1]
        elif "UPDATE assets SET status='qa_rejected'" in query:
            row = env["assets"].setdefault(args[0], {})
            row["status"] = "qa_rejected"
            row["image_url"] = None
            row["drive_image_url"] = args[1]
            row["image_prompt"] = args[2]
        elif "UPDATE assets SET image_url=$2" in query:
            row = env["assets"].setdefault(args[0], {})
            row["status"] = "done"
            row["image_url"] = args[1]
            row["drive_image_url"] = args[1]
            row["image_prompt"] = args[2]
        elif "DELETE FROM assets WHERE id=" in query:
            env["assets"].pop(args[0], None)
        return None

    async def fake_get_secret(name, *a, **k):
        return "fake-kie-key-for-test" if name == "kie_ai_api_key" else None

    class _FakeTextClient:
        async def generate(self, **kwargs):
            return ('[{"scene": 1, "machine": "Boeing XB-15", "aliases": [], '
                    '"caption_title": "XB-15", '
                    '"caption_sub": "Prototype • US Army • canceled", '
                    '"search_query": "Boeing XB-15 bomber"}]')

    async def fake_get_text_client_for_tenant(tid):
        return _FakeTextClient()

    remaining_urls = list(gen_urls)

    async def fake_generate(self, prompt, ref_url, aspect_ratio="16:9",
                            allow_fallback=False, resolution="1K"):
        env["gen_prompts"].append(prompt)
        u = remaining_urls.pop(0) if remaining_urls else None
        return {"url": u} if u else {}

    remaining_verdicts = list(verdicts)

    async def fake_render_matches(tid, render_url, ref_url, machine, aliases=None):
        env["qa_calls"].append((render_url, ref_url))
        return remaining_verdicts.pop(0) if remaining_verdicts else False

    class _FakeHttp:
        async def get(self, url, **kwargs):
            env["downloads"].append(url)
            return _FakeDownloadResp(b"\x89PNG" + b"x" * 40)

    def _http_factory(*a, **k):
        return _ClientCM(_FakeHttp())

    async def fake_upload_bytes(data, path, mime, tid):
        env["uploads"].append(path)
        if upload_raises:
            raise RuntimeError("storage down")
        return DURABLE

    monkeypatch.setattr(static_docu, "fetch_one", fake_fetch_one)
    monkeypatch.setattr(static_docu, "fetch_all", fake_fetch_all)
    monkeypatch.setattr(static_docu, "execute", fake_execute)
    monkeypatch.setattr(static_docu, "_render_matches_reference", fake_render_matches)
    monkeypatch.setattr(static_docu, "upload_bytes", fake_upload_bytes)
    monkeypatch.setattr(static_docu.httpx, "AsyncClient", _http_factory)

    import vault
    monkeypatch.setattr(vault, "get_secret", fake_get_secret)
    import kie_unified
    monkeypatch.setattr(kie_unified, "get_text_client_for_tenant",
                        fake_get_text_client_for_tenant)
    monkeypatch.setattr(image_client_mod.ImageClient, "generate_scene_image_gpt",
                        fake_generate)
    return env


def _the_row(env):
    assert len(env["assets"]) == 1, (
        f"expected the scene's asset row to survive, got {env['assets']}")
    return next(iter(env["assets"].values()))


# ---------------------------------------------------------------------------
# 1. Double QA reject PARKS the paid render — the core fix. The row survives
#    with status='qa_rejected', image_url NULL (kept out of render_static's
#    image_url IS NOT NULL shippable set), and drive_image_url pointing at
#    the render re-hosted on durable storage.
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_double_qa_reject_parks_render_instead_of_deleting(monkeypatch):
    env = _pipeline_env(monkeypatch, verdicts=[False, False],
                        gen_urls=[RENDER_1, RENDER_2])

    result = await static_docu.generate_static_images_for_video(
        env["video_id"], env["tenant_id"])

    # The scene still counts as FAILED for the batch (nothing shipped)…
    assert result["status"] == "failed"
    assert "1" in result["error"]

    # …but the paid render was parked, not destroyed.
    assert not any("DELETE FROM assets WHERE id=" in q for q in env["queries"]), (
        "the reject path must never delete the paid render's row")
    row = _the_row(env)
    assert row["status"] == "qa_rejected"
    assert row["image_url"] is None, (
        "parked renders must stay out of render_static.py's shippable set")
    assert row["drive_image_url"] == DURABLE

    # The RETRY render (the newest paid attempt) is what gets parked, hosted
    # under a qa_rejected-tagged storage path.
    assert env["downloads"][-1] == RENDER_2
    assert env["uploads"] == [f"{env['video_id']}/static/S01_qa_rejected.png"]

    # Both generations and both QA checks actually ran (unchanged flow).
    assert len(env["gen_prompts"]) == 2
    assert [c[0] for c in env["qa_calls"]] == [RENDER_1, RENDER_2]

    # The operator sees WHICH prompt produced the parked render: the retry's
    # (it carries the reproduce-exactly emphasis), prefixed with the ref.
    assert row["image_prompt"].startswith(f"[ref: {REF_SOURCE}] ")
    assert "Reproduce the machine" in row["image_prompt"]


@pytest.mark.asyncio
async def test_park_survives_hosting_failure_with_provider_url(monkeypatch):
    """Durable re-hosting is best-effort: if storage is down, the row must
    still be parked with the ephemeral provider URL — losing durability
    beats losing the render (and the row) entirely."""
    env = _pipeline_env(monkeypatch, verdicts=[False, False],
                        gen_urls=[RENDER_1, RENDER_2], upload_raises=True)

    result = await static_docu.generate_static_images_for_video(
        env["video_id"], env["tenant_id"])

    assert result["status"] == "failed"
    row = _the_row(env)
    assert row["status"] == "qa_rejected"
    assert row["image_url"] is None
    assert row["drive_image_url"] == RENDER_2


@pytest.mark.asyncio
async def test_failed_retry_generation_parks_first_render(monkeypatch):
    """First render rejected, retry GENERATION comes back empty: the first
    render is the only paid artifact — park that one (with its own prompt,
    not the never-used retry prompt)."""
    env = _pipeline_env(monkeypatch, verdicts=[False],
                        gen_urls=[RENDER_1, None])

    result = await static_docu.generate_static_images_for_video(
        env["video_id"], env["tenant_id"])

    assert result["status"] == "failed"
    assert len(env["qa_calls"]) == 1, "no second QA call when the retry produced nothing"
    row = _the_row(env)
    assert row["status"] == "qa_rejected"
    assert row["drive_image_url"] == DURABLE
    assert env["downloads"][-1] == RENDER_1
    assert "Reproduce the machine" not in row["image_prompt"]


@pytest.mark.asyncio
async def test_qa_pass_still_ships_done(monkeypatch):
    """Regression guard: the happy path is untouched — a first-try QA pass
    still ships status='done' with image_url set to the durable copy."""
    env = _pipeline_env(monkeypatch, verdicts=[True], gen_urls=[RENDER_1])

    result = await static_docu.generate_static_images_for_video(
        env["video_id"], env["tenant_id"])

    assert result["status"] == "completed"
    row = _the_row(env)
    assert row["status"] == "done"
    assert row["image_url"] == DURABLE
    assert env["uploads"] == [f"{env['video_id']}/static/S01.png"]


# ---------------------------------------------------------------------------
# 2. render_static.py exclusion tripwire: parking relies on the stitcher
#    selecting image_url IS NOT NULL. If that WHERE clause ever changes,
#    parked (image_url NULL) renders could leak into shipped videos — fail
#    loudly here instead.
# ---------------------------------------------------------------------------

def test_render_static_only_ships_rows_with_image_url():
    src_path = os.path.join(os.path.abspath(_BACKEND), "render_static.py")
    with open(src_path) as f:
        src = f.read()
    assert "image_url IS NOT NULL" in src, (
        "render_static.py must keep excluding image_url-NULL rows, or parked "
        "qa_rejected renders would leak into shipped videos")


# ---------------------------------------------------------------------------
# 3. POST /api/pipeline/static-qa-approve/{asset_id} — the human YES. Route
#    wiring + tenant scoping, same TestClient shape as
#    test_static_docu_seed_reference.py.
# ---------------------------------------------------------------------------

def _build_approve_app(monkeypatch, *, asset_row, tenant_for_asset="tenant-A"):
    from fastapi import FastAPI
    from fastapi.testclient import TestClient
    import routes.pipeline as pipeline_route

    asset_id = "22222222-2222-2222-2222-222222222222"
    executed = []

    async def fake_fetch_one(query, *args):
        if "FROM assets" in query:
            if args and args[0] == asset_id and args[-1] == tenant_for_asset:
                return dict(asset_row, id=asset_id) if asset_row else None
            return None  # wrong tenant or unknown id -> same 404 as missing
        return None

    async def fake_execute(query, *args):
        executed.append((query, args))
        return None

    monkeypatch.setattr(pipeline_route, "fetch_one", fake_fetch_one)
    monkeypatch.setattr(pipeline_route, "execute", fake_execute)

    app = FastAPI()
    app.include_router(pipeline_route.router)
    return app, asset_id, executed, TestClient


_PARKED_ROW = {
    "video_id": "11111111-1111-1111-1111-111111111111", "scene": 3,
    "status": "qa_rejected", "generation_method": "static_docu",
    "drive_image_url": DURABLE,
}


def test_approve_flips_parked_render_to_done(monkeypatch):
    app, asset_id, executed, TestClient = _build_approve_app(
        monkeypatch, asset_row=_PARKED_ROW)
    from auth import get_tenant_id
    app.dependency_overrides[get_tenant_id] = lambda: "tenant-A"
    client = TestClient(app)

    resp = client.post(f"/api/pipeline/static-qa-approve/{asset_id}")
    assert resp.status_code == 200
    body = resp.json()
    assert body["status"] == "completed"
    assert body["asset_id"] == asset_id
    assert body["scene"] == 3
    assert body["image_url"] == DURABLE

    # The flip itself: done + image_url promoted from drive_image_url, and
    # tenant-scoped in the WHERE clause like every other write.
    assert len(executed) == 1
    query, args = executed[0]
    assert "status='done'" in query
    assert "image_url=drive_image_url" in query
    assert "tenant_id" in query
    assert args == (asset_id, "tenant-A")


def test_approve_wrong_tenant_rejected(monkeypatch):
    """A caller authenticated as a DIFFERENT tenant gets the same 404 a
    missing asset would — never a peek at (or a flip of) another tenant's
    render."""
    app, asset_id, executed, TestClient = _build_approve_app(
        monkeypatch, asset_row=_PARKED_ROW)
    from auth import get_tenant_id
    app.dependency_overrides[get_tenant_id] = lambda: "tenant-B"
    client = TestClient(app)

    resp = client.post(f"/api/pipeline/static-qa-approve/{asset_id}")
    assert resp.status_code == 404
    assert executed == []


def test_approve_rejects_non_parked_asset(monkeypatch):
    """Only qa_rejected static-docu rows are approvable — a done row (or any
    other pipeline's asset) must 400, not get silently rewritten."""
    app, asset_id, executed, TestClient = _build_approve_app(
        monkeypatch, asset_row=dict(_PARKED_ROW, status="done"))
    from auth import get_tenant_id
    app.dependency_overrides[get_tenant_id] = lambda: "tenant-A"
    client = TestClient(app)

    resp = client.post(f"/api/pipeline/static-qa-approve/{asset_id}")
    assert resp.status_code == 400
    assert executed == []


def test_approve_rejects_non_static_docu_asset(monkeypatch):
    app, asset_id, executed, TestClient = _build_approve_app(
        monkeypatch, asset_row=dict(_PARKED_ROW, generation_method="coverage"))
    from auth import get_tenant_id
    app.dependency_overrides[get_tenant_id] = lambda: "tenant-A"
    client = TestClient(app)

    resp = client.post(f"/api/pipeline/static-qa-approve/{asset_id}")
    assert resp.status_code == 400
    assert executed == []


def test_approve_rejects_parked_row_without_hosted_render(monkeypatch):
    app, asset_id, executed, TestClient = _build_approve_app(
        monkeypatch, asset_row=dict(_PARKED_ROW, drive_image_url=None))
    from auth import get_tenant_id
    app.dependency_overrides[get_tenant_id] = lambda: "tenant-A"
    client = TestClient(app)

    resp = client.post(f"/api/pipeline/static-qa-approve/{asset_id}")
    assert resp.status_code == 400
    assert executed == []
