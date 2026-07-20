"""Tests for C25a-fix2 (hotfix on top of C25a, tasks/... 2026-07-20): C25a
locked `routes/media.py::serve_drive_file` behind a tenant-scoped `?token=`
and updated the handful of internal producers it knew about (pipeline_executor
.py's talking-clip path, routes/characters.py + routes/environments.py's
vision fetches). It MISSED the one choke point every image-to-image call in
the app funnels through: `shared.clients.image_client._kie_fetchable_url()`,
called by `ImageClient.generate_scene_image` / `generate_with_reference` /
`generate_thumbnail_gpt2` to turn a Drive reference URL into a Kie-fetchable
proxy URL. Because `ImageClient` was never told its tenant, that proxy URL
carried no token — Kie's createTask fetch got a 401, and single-image redraw
(`POST /api/pipeline/redraw-image/{video_id}`) plus every coverage/storyboard
draw with a cast/environment reference broke in prod on 2026-07-20.

Two things must now both be true:
1. `_kie_fetchable_url(url, tenant_id)` mints a `mint_media_token(tenant_id)`
   and appends it as `?token=` — same token shape (`purpose: media`,
   `tenant_id` claim, HS256/SESSION_SECRET) `routes/media.py::mint_media_token`
   already defines and `pipeline_executor.py`'s `_proxy_url` / `routes/
   characters.py`'s `_fetch_image_bytes` already mint the same way.
2. `_kie_fetchable_url(url, None)` (no known tenant — the pre-C25a shape,
   still used by skills/video-pipeline's standalone non-tenant scripts)
   keeps returning an unsigned URL — this fix must not break those callers.

Same stub pattern as test_c25a_media_tenant_auth.py: stub `database` before
importing routes.media (module-level `from database import fetch_one` binds a
name on routes.media itself), no live DB, no network.

Run:
    cd storyengine/backend && ./venv/bin/python -m pytest tests/functional/test_c25a_fix2_internal_media_signing.py -q
"""
import os
import re
import sys
import types
import uuid
from pathlib import Path

import jwt as pyjwt
import pytest

_BACKEND = os.path.join(os.path.dirname(__file__), "..", "..")
sys.path.insert(0, os.path.abspath(_BACKEND))

_REPO_ROOT = Path(__file__).resolve().parents[4]
_PIPELINE_ROOT = _REPO_ROOT / "skills" / "video-pipeline"
if str(_PIPELINE_ROOT) not in sys.path:
    sys.path.insert(0, str(_PIPELINE_ROOT))


def _stub(name, **attrs):
    mod = types.ModuleType(name)
    for k, v in attrs.items():
        setattr(mod, k, v)
    sys.modules[name] = mod


async def _boom(*a, **k):
    raise AssertionError("pure tests must not touch runtime services")


_stub("database", fetch_one=_boom, fetch_all=_boom, execute=_boom)

os.environ.setdefault("SESSION_SECRET", "test-secret-only-for-c25a-fix2")
os.environ.setdefault("PUBLIC_MEDIA_BASE", "https://storyengine.dev")

import routes.media as media  # noqa: E402
from shared.clients.image_client import _kie_fetchable_url, ImageClient  # noqa: E402

SECRET = os.environ["SESSION_SECRET"]
TENANT_A = str(uuid.uuid4())
TENANT_B = str(uuid.uuid4())
DRIVE_URL = "https://drive.google.com/uc?export=download&id=1UbJtjJP9emPWRil6pqXlkEIrUGEKLRmw"


# ---------------------------------------------------------------------------
# 1. _kie_fetchable_url signs the proxy URL for a KNOWN tenant.
# ---------------------------------------------------------------------------

def test_kie_fetchable_url_signs_with_tenant_token():
    url = _kie_fetchable_url(DRIVE_URL, TENANT_A)
    # C25a-fix5: the path carries a cosmetic ".png" suffix (Kie input
    # validators reject extension-less URLs); it lands BEFORE ?token=.
    assert url.startswith("https://storyengine.dev/api/media/drive/1UbJtjJP9emPWRil6pqXlkEIrUGEKLRmw.png?token=")
    token = url.split("?token=", 1)[1]
    payload = pyjwt.decode(token, SECRET, algorithms=["HS256"])
    assert payload["tenant_id"] == TENANT_A
    assert payload["purpose"] == "media"


def test_kie_fetchable_url_token_is_tenant_scoped_not_shared():
    """A token minted for tenant A must not silently resolve to tenant B —
    the whole point of C25a's tenant-scoped allowlist."""
    url_a = _kie_fetchable_url(DRIVE_URL, TENANT_A)
    token_a = url_a.split("?token=", 1)[1]
    payload = pyjwt.decode(token_a, SECRET, algorithms=["HS256"])
    assert payload["tenant_id"] != TENANT_B


# ---------------------------------------------------------------------------
# 2. No tenant known -> unsigned URL, same as pre-C25a (standalone callers).
# ---------------------------------------------------------------------------

def test_kie_fetchable_url_no_tenant_stays_unsigned():
    url = _kie_fetchable_url(DRIVE_URL, None)
    assert url == "https://storyengine.dev/api/media/drive/1UbJtjJP9emPWRil6pqXlkEIrUGEKLRmw.png"
    assert "token=" not in url


def test_kie_fetchable_url_default_tenant_arg_is_none():
    """Backward-compat: callers that don't pass tenant_id at all (the
    pre-fix call shape) must not start erroring."""
    url = _kie_fetchable_url(DRIVE_URL)
    assert "token=" not in url


# ---------------------------------------------------------------------------
# 3. Non-Drive URLs pass through untouched either way.
# ---------------------------------------------------------------------------

def test_kie_fetchable_url_non_drive_passthrough():
    other = "https://cdn.kie.ai/some/temp/file.png"
    assert _kie_fetchable_url(other, TENANT_A) == other
    assert _kie_fetchable_url(other, None) == other


# ---------------------------------------------------------------------------
# 4. ImageClient carries tenant_id through to _kie_fetchable_url.
# ---------------------------------------------------------------------------

def test_image_client_stores_tenant_id():
    ic = ImageClient(api_key="fake-key", tenant_id=TENANT_A)
    assert ic.tenant_id == TENANT_A


def test_image_client_tenant_id_defaults_to_none():
    ic = ImageClient(api_key="fake-key")
    assert ic.tenant_id is None


def test_image_client_reference_payload_carries_a_valid_token():
    """Build the exact payload generate_thumbnail_gpt2 sends to Kie (without
    making the network call) and confirm the image_input URL it constructs
    resolves to the right tenant — this is the literal shape that 401'd in
    prod on 2026-07-20 (redraw-image / any cast-anchored generation)."""
    ic = ImageClient(api_key="fake-key", tenant_id=TENANT_A)
    refs = [DRIVE_URL]
    signed = [_kie_fetchable_url(r, ic.tenant_id) for r in refs if r][:16]
    assert len(signed) == 1
    token = signed[0].split("?token=", 1)[1]
    payload = pyjwt.decode(token, SECRET, algorithms=["HS256"])
    assert payload["tenant_id"] == TENANT_A


# ---------------------------------------------------------------------------
# 5. Every tenant-backend call site that constructs ImageClient for
#    cast/environment-anchored generation must thread tenant_id through —
#    a source-pattern lock (same style as test_kie_block_and_reaper.py /
#    test_characters.py) so a future edit can't silently reintroduce an
#    untenanted ImageClient() at these exact call sites.
# ---------------------------------------------------------------------------

def _read(rel_path: str) -> str:
    return (Path(_BACKEND).resolve() / rel_path).read_text()


def test_coverage_to_app_image_clients_carry_tenant_id():
    src = _read("scripts/coverage_to_app.py")
    constructions = re.findall(r"ImageClient\([^)]*\)", src)
    assert len(constructions) >= 6, (
        f"expected at least 6 ImageClient(...) constructions in "
        f"coverage_to_app.py, found {len(constructions)} — this test's "
        "count needs updating if call sites were added/removed"
    )
    untenanted = [c for c in constructions if "tenant_id=" not in c]
    assert not untenanted, f"ImageClient(...) missing tenant_id=: {untenanted}"


def test_static_docu_image_client_carries_tenant_id():
    src = _read("static_docu.py")
    constructions = re.findall(r"ImageClient\([^)]*\)", src)
    assert constructions, "expected at least one ImageClient(...) in static_docu.py"
    untenanted = [c for c in constructions if "tenant_id=" not in c]
    assert not untenanted, f"ImageClient(...) missing tenant_id=: {untenanted}"


def test_pipeline_executor_shared_image_client_carries_tenant_id():
    src = _read("pipeline_executor.py")
    # The one construction that backs self._pipeline.image_client (used by
    # clip dispatch, redraw-recovery, upscale, and variant generation alike).
    m = re.search(r"self\._pipeline\.image_client\s*=\s*ImageClient\([^)]*\)", src, re.S)
    assert m, "expected self._pipeline.image_client = ImageClient(...) in pipeline_executor.py"
    assert "tenant_id=self.tenant_id" in m.group(0)
