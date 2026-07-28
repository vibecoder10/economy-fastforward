"""Tests for the static-docu QA park fix (2026-07-22): a render that fails
post-generation QA twice is PARKED for operator review, never deleted.

The old reject path in `_one_scene` (generate_static_images_for_video) ran
`DELETE FROM assets WHERE id=...` when both the initial render and its one
retry failed `_render_matches_reference` — destroying paid renders on the
QA judge's word alone. PROVEN costly live on 2026-07-22: a QA-wording bug
(fixed in C2h) rejected 12 CORRECT renders and the DELETE destroyed all 12
(~$0.36 of paid generations, gone).

Fix (static_docu.py `_one_scene` + routes/pipeline.py):
- The pipeline runs UNATTENDED, so a double reject is first sent to an
  automated tie-breaker: `_arbiter_confirms_render`, an independently
  worded second-opinion judge (its own prompt framing, MATCH/MISMATCH
  vocabulary instead of YES/NO) whose failure modes can't correlate with a
  wording bug in the primary judge. Arbiter says MATCH -> the rejection is
  overruled and the render ships, stamped "[qa: arbiter-approved after
  double reject]" in image_prompt for the audit trail. The arbiter fails
  CLOSED everywhere, including keyless — an arbiter that can't see the
  images must never overrule a rejection.
- Only when QA AND the arbiter agree does the scene fail — and then the
  row is KEPT: status='qa_rejected', image_url NULL (render_static.py only
  ships rows with image_url IS NOT NULL, so a parked render can never leak
  into a video), drive_image_url = the render self-hosted to durable
  storage (falling back to the ephemeral provider URL only if hosting
  fails — still better than losing it).
- `_bounded`'s exception cleanup no longer sweeps up deliberately parked
  rows (qa_rejected / blocked_no_reference both carry image_url NULL by
  design).
- POST /api/pipeline/static-qa-approve/{asset_id} is the rare-case manual
  back-door: flips a parked row to status='done' and promotes
  drive_image_url to image_url, putting it back in render_static.py's
  shippable set.

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

from test_static_docu_c2f_vision_gate_fixes import (  # noqa: E402
    _anthropic_body,
    _install_vision_fakes,
)

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


def _pipeline_env(monkeypatch, *, verdicts, gen_urls, upload_raises=False,
                  arbiter_verdicts=(), isolate_single_view=True,
                  docu_module=None, image_client_module=None):
    """Fake DB + provider world for generate_static_images_for_video, modeled
    on test_static_docu_reference_fail_closed. One scene, a CACHED verified
    reference (so no Wikimedia lookup layers run), a scripted sequence of
    generation URLs, QA verdicts, and arbiter verdicts (exhausted -> False,
    matching the arbiter's own fail-closed contract). No network, no real DB
    anywhere."""
    video_id = str(uuid.uuid4())
    tenant_id = str(uuid.uuid4())
    docu_module = docu_module or static_docu
    image_client_module = image_client_module or image_client_mod
    if isolate_single_view:
        # These tests isolate the per-view QA/parking contract. The separate
        # three-view contract suite exercises orchestration across all views.
        monkeypatch.setattr(docu_module, "STATIC_VIEW_PLANS",
                            docu_module.STATIC_VIEW_PLANS[:1])
        monkeypatch.setattr(docu_module, "STATIC_VIEWS_TARGET", 1)
        monkeypatch.setattr(docu_module, "STATIC_VIEWS_MINIMUM", 1)

    env = {
        "video_id": video_id,
        "tenant_id": tenant_id,
        "assets": {},        # row_id -> dict of column values
        "queries": [],       # every execute() SQL string, in order
        "uploads": [],       # upload_bytes storage paths
        "downloads": [],     # URLs fetched via httpx
        "qa_calls": [],      # (render_url, ref_url) per _render_matches_reference
        "arbiter_calls": [],  # (render_url, ref_url) per _arbiter_confirms_render
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
                "drive_image_url": args[12], "image_prompt": None,
                "image_index": args[4], "shot_type": args[6],
                "caption": args[11],
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
                    '"caption_specs": ["Wingspan 149 ft"], '
                    '"detail_focus": "four-engine wing", '
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

    remaining_arbiter = list(arbiter_verdicts)

    async def fake_arbiter(tid, render_url, ref_url, machine, aliases=None):
        env["arbiter_calls"].append((render_url, ref_url))
        return remaining_arbiter.pop(0) if remaining_arbiter else False

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

    monkeypatch.setattr(docu_module, "fetch_one", fake_fetch_one)
    monkeypatch.setattr(docu_module, "fetch_all", fake_fetch_all)
    monkeypatch.setattr(docu_module, "execute", fake_execute)
    monkeypatch.setattr(docu_module, "_render_matches_reference", fake_render_matches)
    monkeypatch.setattr(docu_module, "_arbiter_confirms_render", fake_arbiter)
    monkeypatch.setattr(docu_module, "upload_bytes", fake_upload_bytes)
    monkeypatch.setattr(docu_module.httpx, "AsyncClient", _http_factory)

    import vault
    monkeypatch.setattr(vault, "get_secret", fake_get_secret)
    import kie_unified
    monkeypatch.setattr(kie_unified, "get_text_client_for_tenant",
                        fake_get_text_client_for_tenant)
    monkeypatch.setattr(image_client_module.ImageClient, "generate_scene_image_gpt",
                        fake_generate)

    # Money-safety fix (C56): generate_static_images_for_video now calls
    # actions.budget_refusal before every real GPT Image 2 call and
    # generation_ledger.record_ledger_entry after each one. This suite's
    # DB stub above only covers docu_module's own fetch_one/fetch_all/
    # execute, not the SEPARATE database bindings actions.py and
    # generation_ledger.py imported at THEIR OWN module-load time — left
    # real here, they'd hit an actual DB connection attempt and blow up
    # every scene as a generic exception (_bounded's per-scene try/except
    # swallowing it into a silent "failed", not a loud test error). None of
    # these tests are about the spend cap (see test_money_safety_gaps_c56.py
    # for that), so default to "never refuse, ledger writes are no-ops" —
    # every existing assertion here keeps testing exactly what it tested
    # before this fix.
    #
    # Import actions/generation_ledger HERE, fresh, rather than at this
    # test file's own module scope: tests/conftest.py's IsolatedModule gives
    # every test FILE its own private sys.modules['actions'] (repo modules
    # are evicted and re-imported per file, see conftest.py's _is_shared_
    # cacheable). A module-level `import actions` captured in THIS file
    # would be the wrong object when _pipeline_env is called from a
    # DIFFERENT file (test_static_docu_three_view_contract.py imports this
    # helper) — static_docu.py's `from actions import budget_refusal` would
    # resolve against that OTHER file's isolated copy, silently missing this
    # patch and hitting a real DB call. A fresh import at call time always
    # resolves the CALLING test's own isolated module.
    import actions as _actions_mod
    import generation_ledger as _ledger_mod

    env["ledger_calls"] = []

    async def fake_budget_refusal(tenant_id, video_id, quote, label="this generation"):
        return None

    async def fake_record_ledger_entry(**kwargs):
        env["ledger_calls"].append(kwargs)

    monkeypatch.setattr(_actions_mod, "budget_refusal", fake_budget_refusal)
    monkeypatch.setattr(_ledger_mod, "record_ledger_entry", fake_record_ledger_entry)
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
    assert env["uploads"] == [f"{env['video_id']}/static/S01_01_qa_rejected.png"]

    # Both generations and both QA checks actually ran (unchanged flow), and
    # the arbiter got its say on the newest render before the park.
    assert len(env["gen_prompts"]) == 2
    assert [c[0] for c in env["qa_calls"]] == [RENDER_1, RENDER_2]
    assert [c[0] for c in env["arbiter_calls"]] == [RENDER_2]

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
    still ships status='done' with image_url set to the durable copy, and
    the arbiter is never consulted."""
    env = _pipeline_env(monkeypatch, verdicts=[True], gen_urls=[RENDER_1])

    result = await static_docu.generate_static_images_for_video(
        env["video_id"], env["tenant_id"])

    assert result["status"] == "completed"
    row = _the_row(env)
    assert row["status"] == "done"
    assert row["image_url"] == DURABLE
    assert env["uploads"] == [f"{env['video_id']}/static/S01_01.png"]
    assert env["arbiter_calls"] == []
    assert "[qa:" not in row["image_prompt"], (
        "a first-try pass must not carry the arbiter audit stamp")


# ---------------------------------------------------------------------------
# 2. The automated tie-breaker. The pipeline runs unattended — a double QA
#    reject goes to _arbiter_confirms_render (independently worded second
#    opinion) instead of dead-ending on a human. MATCH -> ship with an audit
#    stamp; MISMATCH -> park (covered by the tests above, whose arbiter
#    default is False).
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_arbiter_overrules_double_reject_and_ships(monkeypatch):
    env = _pipeline_env(monkeypatch, verdicts=[False, False],
                        gen_urls=[RENDER_1, RENDER_2],
                        arbiter_verdicts=[True])

    result = await static_docu.generate_static_images_for_video(
        env["video_id"], env["tenant_id"])

    assert result["status"] == "completed"
    row = _the_row(env)
    assert row["status"] == "done"
    assert row["image_url"] == DURABLE
    # Shipped through the NORMAL success path (durable S01_01.png copy), from
    # the newest render, judged against the verified reference.
    assert env["uploads"] == [f"{env['video_id']}/static/S01_01.png"]
    assert env["downloads"][-1] == RENDER_2
    assert env["arbiter_calls"] == [(RENDER_2, REF_HOSTED)]
    # Audit trail: the row says the arbiter shipped it.
    assert row["image_prompt"].startswith(f"[ref: {REF_SOURCE}] ")
    assert "[qa: arbiter-approved after double reject]" in row["image_prompt"]


@pytest.mark.asyncio
async def test_arbiter_judges_first_render_when_retry_generation_failed(monkeypatch):
    """Retry GENERATION produced nothing — the first render is the only paid
    artifact, so that's what the arbiter judges and ships on MATCH."""
    env = _pipeline_env(monkeypatch, verdicts=[False],
                        gen_urls=[RENDER_1, None],
                        arbiter_verdicts=[True])

    result = await static_docu.generate_static_images_for_video(
        env["video_id"], env["tenant_id"])

    assert result["status"] == "completed"
    row = _the_row(env)
    assert row["status"] == "done"
    assert env["arbiter_calls"] == [(RENDER_1, REF_HOSTED)]
    assert "[qa: arbiter-approved after double reject]" in row["image_prompt"]


# ---------------------------------------------------------------------------
# 3. _arbiter_confirms_render — unit tests, via the same scripted vision
#    fakes the C2f/C2h files use. The whole point of the arbiter is
#    INDEPENDENCE from the primary judge: its own framing and its own
#    MATCH/MISMATCH vocabulary, and fail-CLOSED everywhere (keyless
#    included) because a False parks a render while a false True ships a
#    wrong machine.
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_arbiter_match_returns_true(monkeypatch):
    _install_vision_fakes(monkeypatch, [
        _anthropic_body("MATCH, same shape, wing form and tail configuration"),
    ])
    assert await static_docu._arbiter_confirms_render(
        "tenant-1", "https://example.com/render.png",
        "https://example.com/ref.jpg", "Boeing XB-15") is True


@pytest.mark.asyncio
async def test_arbiter_mismatch_returns_false(monkeypatch):
    """MISMATCH must parse as a rejection — including that the word
    'mismatch' itself must never satisfy the ^match parse."""
    _install_vision_fakes(monkeypatch, [
        _anthropic_body("MISMATCH, image 2 shows a different aircraft type"),
    ])
    assert await static_docu._arbiter_confirms_render(
        "tenant-1", "https://example.com/render.png",
        "https://example.com/ref.jpg", "Boeing XB-15") is False


@pytest.mark.asyncio
async def test_arbiter_requires_its_own_vocabulary(monkeypatch):
    """A YES-style reply (the PRIMARY judge's vocabulary) must not pass the
    arbiter — vocabulary separation is what keeps the two judges' parsing
    failure modes uncorrelated."""
    _install_vision_fakes(monkeypatch, [
        _anthropic_body("YES, same aircraft type and configuration"),
    ])
    assert await static_docu._arbiter_confirms_render(
        "tenant-1", "https://example.com/render.png",
        "https://example.com/ref.jpg", "Boeing XB-15") is False


@pytest.mark.asyncio
async def test_arbiter_render_ness_does_not_reject(monkeypatch):
    _install_vision_fakes(monkeypatch, [
        _anthropic_body("MATCH — image 2 is clearly a rendered illustration, "
                        "but it shows the same machine type as image 1"),
    ])
    assert await static_docu._arbiter_confirms_render(
        "tenant-1", "https://example.com/render.png",
        "https://example.com/ref.jpg", "Boeing XB-15") is True


@pytest.mark.asyncio
async def test_arbiter_empty_render_hard_rejected_even_on_match(monkeypatch):
    _install_vision_fakes(monkeypatch, [
        _anthropic_body("MATCH, although image 2 appears mostly blank"),
    ])
    assert await static_docu._arbiter_confirms_render(
        "tenant-1", "https://example.com/render.png",
        "https://example.com/ref.jpg", "Boeing XB-15") is False


@pytest.mark.asyncio
async def test_arbiter_transport_failure_fails_closed(monkeypatch):
    """Non-200 from the model API, twice: the rejection must STAND (render
    parks) — never a silent overrule on an API failure."""
    from test_static_docu_c2f_vision_gate_fixes import _FakeResp
    fake_client = _install_vision_fakes(monkeypatch, [
        _FakeResp({"error": "nope"}, status_code=400),
        _FakeResp({"error": "nope"}, status_code=400),
    ])
    assert await static_docu._arbiter_confirms_render(
        "tenant-1", "https://example.com/render.png",
        "https://example.com/ref.jpg", "Boeing XB-15") is False
    assert fake_client.calls == 2, "must retry exactly once, then fail closed"


@pytest.mark.asyncio
async def test_arbiter_keyless_fails_closed_unlike_primary_judges(monkeypatch):
    """No provider key at all: the primary judges fail OPEN on this config
    gap, but the arbiter must fail CLOSED — an arbiter that can't see the
    images must never overrule a rejection. (Unreachable in practice: with
    no key the primary judge already passed everything.)"""
    _install_vision_fakes(monkeypatch, [], anthropic_key=None)

    import vault

    async def fake_get_secret(name, *a, **k):
        return None  # neither anthropic_api_key nor kie_ai_api_key

    monkeypatch.setattr(vault, "get_secret", fake_get_secret)

    assert await static_docu._arbiter_confirms_render(
        "tenant-1", "https://example.com/render.png",
        "https://example.com/ref.jpg", "Boeing XB-15") is False


@pytest.mark.asyncio
async def test_arbiter_aliases_included_in_prompt(monkeypatch):
    fake_client = _install_vision_fakes(monkeypatch, [
        _anthropic_body("MATCH, same machine"),
    ])
    captured = {}
    orig_post = fake_client.post

    async def spy_post(url, headers=None, json=None, **kwargs):
        captured["json"] = json
        return await orig_post(url, headers=headers, json=json, **kwargs)

    monkeypatch.setattr(fake_client, "post", spy_post)

    await static_docu._arbiter_confirms_render(
        "tenant-1", "https://example.com/render.png",
        "https://example.com/ref.jpg", "Douglas XB-42 Mixmaster",
        aliases=["XB-42"])

    content = captured["json"]["messages"][0]["content"]
    assert "XB-42" in content[0]["text"]
    # Same two-image structural contract as the primary judge: reference
    # first, render second, both base64.
    image_blocks = [b for b in content if b["type"] == "image"]
    assert len(image_blocks) == 2


# ---------------------------------------------------------------------------
# 4. render_static.py exclusion tripwire: parking relies on the stitcher
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
# 5. POST /api/pipeline/static-qa-approve/{asset_id} — the rare-case manual
#    back-door (the automated path is the arbiter above). Route wiring +
#    tenant scoping, same TestClient shape as
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
