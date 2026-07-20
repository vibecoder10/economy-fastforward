"""Tests for C25a-fix5 (2026-07-20): Kie-facing media-proxy URLs carry a
cosmetic ".png" extension suffix.

Why: some Kie model input validators reject URLs without a recognizable file
extension. That exact failure was already fixed once for InfiniteTalk (commit
10d232e5: "Media proxy accepts a cosmetic extension suffix (Kie validators
want one)" + pipeline_executor.py's `_with_ext` helper for the clip path),
but `_kie_fetchable_url()` in shared/clients/image_client.py — the single
choke point that builds `input_urls`/`image_input` reference URLs for every
image-to-image call — never got it. Prod evidence 2026-07-20 (video
cd5d2883-427e-4bfb-854d-8849d025d444, tenant 44ecc95a): gpt-image-2-
image-to-image tasks with 3 extension-less tokened proxy URLs failed with
failCode 400 "The current content could not be processed" WITHOUT Kie ever
fetching the URLs (our access log shows zero fetches; the URLs themselves
curl fine) — i.e. rejected at input validation, the InfiniteTalk signature.

Invariants pinned (all git-stash-sensitive: stash the image_client.py change
and the .png assertions below fail):
1. Signed URL shape: `/api/media/drive/<id>.png?token=<jwt>` — the ".png"
   sits on the PATH, BEFORE the ?token= query. Appending it after the query
   would corrupt the JWT (see pipeline_executor.py `_with_ext`'s docstring:
   "...?token=eyJ...XYZ.png" fails to decode).
2. Unsigned URL (tenant_id=None, the standalone non-tenant callers) ends
   with ".png" too — the Kie validator doesn't care about tenancy.
3. The proxy route genuinely strips the cosmetic suffix before resolving
   the file id (routes/media.py::serve_drive_file) — otherwise this suffix
   would be a 404-generator, not a fix.

Same stub pattern as test_c25a_fix2_internal_media_signing.py: stub
`database` before importing routes.media, no live DB, no network.

Run:
    cd storyengine/backend && ./venv/bin/python -m pytest tests/functional/test_c25a_fix5_extension_suffix.py -q
"""
import os
import re
import sys
import types
import uuid
from pathlib import Path

import jwt as pyjwt

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

os.environ.setdefault("SESSION_SECRET", "test-secret-only-for-c25a-fix5")
os.environ.setdefault("PUBLIC_MEDIA_BASE", "https://storyengine.dev")

from shared.clients.image_client import _kie_fetchable_url  # noqa: E402

SECRET = os.environ["SESSION_SECRET"]
TENANT = str(uuid.uuid4())
FILE_ID = "1UbJtjJP9emPWRil6pqXlkEIrUGEKLRmw"
DRIVE_URL = f"https://drive.google.com/uc?export=download&id={FILE_ID}"


# ---------------------------------------------------------------------------
# 1. Signed URL: .png on the path, BEFORE ?token=, token still a valid JWT.
# ---------------------------------------------------------------------------

def test_signed_url_has_png_before_token_query():
    url = _kie_fetchable_url(DRIVE_URL, TENANT)
    path, sep, query = url.partition("?")
    assert sep == "?", f"signed URL must carry a query string: {url}"
    assert path == f"https://storyengine.dev/api/media/drive/{FILE_ID}.png", (
        f"path must end with .png (before the query), got: {path}"
    )
    # The suffix must not have corrupted the token: it still decodes.
    token = query.split("token=", 1)[1]
    payload = pyjwt.decode(token, SECRET, algorithms=["HS256"])
    assert payload["tenant_id"] == TENANT
    assert payload["purpose"] == "media"


# ---------------------------------------------------------------------------
# 2. Unsigned URL (no tenant): .png suffix, no query at all.
# ---------------------------------------------------------------------------

def test_unsigned_url_ends_with_png():
    url = _kie_fetchable_url(DRIVE_URL, None)
    assert url == f"https://storyengine.dev/api/media/drive/{FILE_ID}.png"


def test_unsigned_default_arg_ends_with_png():
    url = _kie_fetchable_url(DRIVE_URL)
    assert url.endswith(".png") and "?" not in url


# ---------------------------------------------------------------------------
# 3. Non-Drive URLs still pass through untouched (no suffix bolted on).
# ---------------------------------------------------------------------------

def test_non_drive_url_gets_no_suffix():
    other = "https://cdn.kie.ai/some/temp/file.webp"
    assert _kie_fetchable_url(other, TENANT) == other
    assert _kie_fetchable_url(other, None) == other


# ---------------------------------------------------------------------------
# 4. The proxy route strips the cosmetic suffix — source lock on the exact
#    regex, so a future edit can't turn every generated URL into a 404.
# ---------------------------------------------------------------------------

def test_serve_drive_file_strips_cosmetic_extension():
    src = (Path(_BACKEND).resolve() / "routes" / "media.py").read_text()
    m = re.search(
        r'file_id = _re\.sub\(r"\\\.\((?P<exts>[^)]+)\)\$", "", file_id', src)
    assert m, (
        "routes/media.py::serve_drive_file must strip the cosmetic extension "
        "suffix before resolving the file id — without it, the .png suffix "
        "_kie_fetchable_url now appends would 404 every image reference"
    )
    assert "png" in m.group("exts"), f"suffix-strip regex lost png: {m.group('exts')}"
