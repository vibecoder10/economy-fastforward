"""Manual roster-reference selection delegation and route boundaries.

The manual endpoint delegates the supplied image and optional source page to
the public source-grounded selector. It must never revive retired host/vision
helpers or accept a machine outside the saved roster.

routes/pipeline.py's POST /api/pipeline/roster-seed-reference/{video_id} is
the thin HTTP door onto that function — tenant-scoped like every other
pipeline route (the video lookup's WHERE clause), so a wrong-tenant caller
gets the SAME 404 a missing video would, not a leak of another tenant's
data.

Run:
    cd storyengine/backend && ./venv/bin/python -m pytest \
        tests/functional/test_static_docu_seed_reference.py -q
"""
import os
import sys
import uuid

import pytest

_BACKEND = os.path.join(os.path.dirname(__file__), "..", "..")
sys.path.insert(0, os.path.abspath(_BACKEND))

import static_docu  # noqa: E402

@pytest.fixture(autouse=True)
def _selector_seam(monkeypatch):
    import reference_selection
    calls = []
    async def selected(tenant_id, video_id, machine, roster_index, aliases=None, facts=None, **kwargs):
        calls.append((tenant_id, video_id, machine, roster_index, aliases, facts, kwargs))
        return {"status": "selected", "selected": {"hosted_url": "https://storage.example/selected.jpg", "image_url": kwargs.get("manual_url")}}
    monkeypatch.setattr(reference_selection, "select_reference", selected)
    async def video_row(*args, **kwargs):
        return {"render_mode": "static_docu", "research_payload": {"documentary_style": "dvsu", "unit_roster": ["Boeing XB-15", "Northrop XB-35", "Convair YB-60"]}}
    monkeypatch.setattr(static_docu, "fetch_one", video_row)
    yield calls


# ---------------------------------------------------------------------------
# 1. static_docu.seed_reference_from_url — unit tests
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_seed_reference_delegates_saved_machine_to_selector(monkeypatch, _selector_seam):
    """Manual input forwards saved-roster aliases/facts and source-page context."""
    video_id = str(uuid.uuid4())
    tenant_id = str(uuid.uuid4())
    machine = "Boeing XB-15"

    async def retired(*args, **kwargs):
        raise AssertionError("retired host/vision helper must not run")
    monkeypatch.setattr(static_docu, "_host_reference", retired)
    monkeypatch.setattr(static_docu, "_vision_confirms", retired)

    result = await static_docu.seed_reference_from_url(
        video_id, tenant_id, machine, "https://example.com/xb15.jpg", source_page_url="https://example.com/archive")

    assert result["status"] == "verified"
    assert result["hosted_url"] == "https://storage.example/selected.jpg"
    assert result["source_url"] == "https://example.com/xb15.jpg"

    assert _selector_seam == [(tenant_id, video_id, machine, 0, [], {}, {
        "manual_url": "https://example.com/xb15.jpg", "source_page_url": "https://example.com/archive"})]


@pytest.mark.asyncio
async def test_seed_reference_vision_rejects_no_cache_row_written(monkeypatch):
    """When the vision check says NO (wrong machine, not a real photo), the
    function must report a rejection and NEVER write a cache row — a bad
    photo must not silently become the machine's trusted reference."""
    video_id = str(uuid.uuid4())
    tenant_id = str(uuid.uuid4())
    machine = "Northrop XB-35"

    cache_writes = []

    async def fake_ensure_schema():
        pass

    async def fake_host_reference(url, vid, tid, tag):
        return f"https://storage.example/{tag}.jpg"

    async def fake_vision_confirms(tid, image_url, mach, aliases=None, trusted_source=False, facts=None, source_label=None):
        return False  # wrong machine / not a real photo

    async def fake_execute(query, *args):
        if "INSERT INTO static_reference_cache" in query:
            cache_writes.append(args)
        return None

    monkeypatch.setattr(static_docu, "_ensure_ref_cache_schema", fake_ensure_schema)
    monkeypatch.setattr(static_docu, "_host_reference", fake_host_reference)
    monkeypatch.setattr(static_docu, "_vision_confirms", fake_vision_confirms)
    monkeypatch.setattr(static_docu, "execute", fake_execute)
    import reference_selection
    async def rejected(*args, **kwargs):
        return {"status": "needs_review", "reason_code": "wrong_identity", "reason": "Wrong machine"}
    monkeypatch.setattr(reference_selection, "select_reference", rejected)

    result = await static_docu.seed_reference_from_url(
        video_id, tenant_id, machine, "https://example.com/wrong-plane.jpg")

    assert result["status"] == "rejected"
    assert "reason" in result and result["reason"]
    assert cache_writes == []


@pytest.mark.asyncio
async def test_seed_reference_unreachable_url_rejected_no_cache_row(monkeypatch):
    """A URL _host_reference can't fetch (unreachable, too small, blocked)
    must be reported as a rejection, not raise — and must never write a
    cache row or reach the vision check."""
    video_id = str(uuid.uuid4())
    tenant_id = str(uuid.uuid4())
    machine = "Convair YB-60"

    cache_writes = []
    vision_calls = []

    async def fake_ensure_schema():
        pass

    async def fake_host_reference(url, vid, tid, tag):
        return None  # fetch failed

    async def fake_vision_confirms(*a, **k):
        vision_calls.append(1)
        return True

    async def fake_execute(query, *args):
        if "INSERT INTO static_reference_cache" in query:
            cache_writes.append(args)
        return None

    monkeypatch.setattr(static_docu, "_ensure_ref_cache_schema", fake_ensure_schema)
    monkeypatch.setattr(static_docu, "_host_reference", fake_host_reference)
    monkeypatch.setattr(static_docu, "_vision_confirms", fake_vision_confirms)
    monkeypatch.setattr(static_docu, "execute", fake_execute)
    import reference_selection
    async def rejected(*args, **kwargs):
        return {"status": "error", "reason_code": "fetch_failed", "reason": "Unreachable"}
    monkeypatch.setattr(reference_selection, "select_reference", rejected)

    result = await static_docu.seed_reference_from_url(
        video_id, tenant_id, machine, "https://example.com/dead-link.jpg")

    assert result["status"] == "rejected"
    assert cache_writes == []
    assert vision_calls == [], "a fetch failure must short-circuit before the vision check"


@pytest.mark.asyncio
async def test_seed_reference_unknown_roster_machine_never_calls_selector(_selector_seam):
    result = await static_docu.seed_reference_from_url(
        "video", "tenant", "Unknown machine", "https://example.com/image.jpg")
    assert result == {"status": "rejected", "reason_code": "invalid_machine",
                      "reason": "Choose a machine from this video's saved roster."}
    assert _selector_seam == []


# ---------------------------------------------------------------------------
# 2. POST /api/pipeline/roster-seed-reference/{video_id} — route wiring + auth
# ---------------------------------------------------------------------------

def _build_client(monkeypatch, *, tenant_for_video: str, seed_result=None, seed_error=None, active=False):
    """A minimal FastAPI app carrying just the pipeline router, with the
    tenant dependency overridden and the video lookup faked to only match
    ONE tenant — the same tenant-scoping shape every real route uses
    (WHERE ... AND tenant_id = $2), so a wrong-tenant call gets exactly the
    404 a missing video would."""
    from fastapi import FastAPI
    from fastapi.testclient import TestClient
    from auth import get_tenant_id
    import routes.pipeline as pipeline_route

    video_id = "11111111-1111-1111-1111-111111111111"

    async def fake_fetch_one(query, *args):
        if "FROM videos" in query:
            requested_tenant = args[-1] if args else None
            if requested_tenant == tenant_for_video:
                return {"id": video_id, "render_mode": "static_docu"}
            return None  # wrong tenant -> video not found, same as a real WHERE clause
        return None

    monkeypatch.setattr(pipeline_route, "fetch_one", fake_fetch_one)
    async def task_active(*args):
        return active
    monkeypatch.setattr(pipeline_route, "_is_task_active", task_active)

    async def fake_seed(vid, tid, machine, url, source_page_url=None):
        if seed_error:
            raise seed_error
        return seed_result or {"status": "verified", "hosted_url": "https://storage.example/x.jpg", "source_url": url}

    import static_docu as static_docu_mod
    monkeypatch.setattr(static_docu_mod, "seed_reference_from_url", fake_seed)

    app = FastAPI()
    app.include_router(pipeline_route.router)
    return app, video_id, TestClient

async def _false():
    return False


def test_seed_reference_route_happy_path(monkeypatch):
    app, video_id, TestClient = _build_client(
        monkeypatch, tenant_for_video="tenant-A",
        seed_result={"status": "verified", "hosted_url": "https://storage.example/seed.jpg",
                     "source_url": "https://example.com/photo.jpg"},
    )
    from auth import get_tenant_id
    app.dependency_overrides[get_tenant_id] = lambda: "tenant-A"
    client = TestClient(app)

    resp = client.post(
        f"/api/pipeline/roster-seed-reference/{video_id}",
        json={"machine": "Boeing XB-15", "url": "https://example.com/photo.jpg"},
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["status"] == "verified"
    assert body["hosted_url"] == "https://storage.example/seed.jpg"


def test_seed_reference_route_wrong_tenant_rejected(monkeypatch):
    """A caller authenticated as a DIFFERENT tenant than the one that owns
    the video must be rejected — same 404 shape as a video that doesn't
    exist, never a peek at another tenant's data."""
    app, video_id, TestClient = _build_client(monkeypatch, tenant_for_video="tenant-A")
    from auth import get_tenant_id
    app.dependency_overrides[get_tenant_id] = lambda: "tenant-B"  # wrong tenant
    client = TestClient(app)

    resp = client.post(
        f"/api/pipeline/roster-seed-reference/{video_id}",
        json={"machine": "Boeing XB-15", "url": "https://example.com/photo.jpg"},
    )
    assert resp.status_code == 404


def test_seed_reference_route_requires_machine_and_url(monkeypatch):
    app, video_id, TestClient = _build_client(monkeypatch, tenant_for_video="tenant-A")
    from auth import get_tenant_id
    app.dependency_overrides[get_tenant_id] = lambda: "tenant-A"
    client = TestClient(app)

    resp = client.post(
        f"/api/pipeline/roster-seed-reference/{video_id}",
        json={"machine": "", "url": ""},
    )
    assert resp.status_code == 400


def test_seed_reference_route_active_work_returns_409_without_seeding(monkeypatch):
    calls = []
    app, video_id, TestClient = _build_client(monkeypatch, tenant_for_video="tenant-A", active=True)
    import static_docu as static_docu_mod
    async def must_not_seed(*args, **kwargs):
        calls.append(args)
        raise AssertionError("seed must be blocked while active work exists")
    monkeypatch.setattr(static_docu_mod, "seed_reference_from_url", must_not_seed)
    from auth import get_tenant_id
    app.dependency_overrides[get_tenant_id] = lambda: "tenant-A"
    response = TestClient(app).post(f"/api/pipeline/roster-seed-reference/{video_id}",
                                    json={"machine": "Boeing XB-15", "url": "https://example.com/photo.jpg"})
    assert response.status_code == 409
    assert calls == []
