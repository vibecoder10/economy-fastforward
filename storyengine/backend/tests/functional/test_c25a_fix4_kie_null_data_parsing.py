"""Tests for C25a-fix4 (2026-07-20): Kie can return HTTP 200 with a
present-but-null "data" key on an in-body failure (code != 200). A bare
`.get("data", {})` does NOT apply the default for a null value — only for a
MISSING key (tasks/lessons.md's documented present-but-NULL trap) — so the
next chained `.get(...)` used to raise `AttributeError: 'NoneType' object
has no attribute 'get'`, eating Kie's real code/msg and (for
generate_scene_image_zimage / generate_video_veo) crashing the caller.

Confirmed live 2026-07-20 on video cd5d2883-427e-4bfb-854d-8849d025d444
(tenant 44ecc95a): `generate_scene_image_zimage` crashed at
image_client.py:714 with exactly this traceback, silently swallowing why
Kie's z-image createTask failed. `generate_video_veo` (Veo 3.1 clip path)
shares the identical `.get("data", {}).get("taskId")` shape at the createTask
call and produced the identical "'NoneType' object has no attribute 'get'"
signature in prod logs.

Each test below feeds a fake `{"code": <failure>, "msg": "...", "data": None}`
Kie response through the real parsing code (no live network — httpx.AsyncClient
is monkeypatched) and asserts: (a) no exception escapes, (b) the function
returns its normal failure value (None), (c) the real code/msg gets printed
so it's no longer swallowed. These are git-stash-sensitive: `git stash` the
image_client.py / sound_client.py fix and every test below fails with the
original AttributeError instead of a clean assertion.

Run:
    cd storyengine/backend && ./venv/bin/python -m pytest tests/functional/test_c25a_fix4_kie_null_data_parsing.py -q
"""
import os
import sys
import types
from pathlib import Path

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
os.environ.setdefault("KIE_AI_API_KEY", "fake-key-for-tests")

from shared.clients.image_client import ImageClient  # noqa: E402
from shared.clients.sound_client import SoundClient  # noqa: E402


# ---------------------------------------------------------------------------
# Fake httpx.AsyncClient — returns a canned response for every post/get,
# regardless of URL, so each test controls exactly one Kie response body.
# ---------------------------------------------------------------------------

class _FakeResponse:
    def __init__(self, body, status_code=200):
        self._body = body
        self.status_code = status_code
        self.text = str(body)

    def json(self):
        return self._body

    def raise_for_status(self):
        if self.status_code >= 400:
            raise RuntimeError(f"HTTP {self.status_code}")


class _FakeAsyncClient:
    """Drop-in for `async with httpx.AsyncClient() as client:` that always
    answers with the same canned body, whether the call is POST (createTask)
    or GET (recordInfo/poll)."""

    def __init__(self, body, status_code=200):
        self._body = body
        self._status_code = status_code
        self.calls = []

    async def __aenter__(self):
        return self

    async def __aexit__(self, *a):
        return False

    async def post(self, url, **kwargs):
        self.calls.append(("POST", url))
        return _FakeResponse(self._body, self._status_code)

    async def get(self, url, **kwargs):
        self.calls.append(("GET", url))
        return _FakeResponse(self._body, self._status_code)


def _patch_httpx(monkeypatch, module, body, status_code=200):
    """Point `module`'s httpx.AsyncClient() constructor at a fake that always
    returns `body`. image_client.py and sound_client.py each do
    `import httpx` at module scope, so patch each module's own reference."""
    def _factory(*a, **k):
        return _FakeAsyncClient(body, status_code)
    monkeypatch.setattr(module.httpx, "AsyncClient", _factory)


# The exact present-but-null shape Kie sent live (code != 200, data: null).
NULL_DATA_FAILURE = {"code": 401, "msg": "Unauthorized — bad key", "data": None}


# ---------------------------------------------------------------------------
# 1. generate_scene_image_zimage — the CONFIRMED crash site (image_client.py:714).
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_generate_scene_image_zimage_survives_null_data(monkeypatch, capsys):
    import shared.clients.image_client as image_client_mod
    _patch_httpx(monkeypatch, image_client_mod, NULL_DATA_FAILURE)

    ic = ImageClient(api_key="fake-key")
    result = await ic.generate_scene_image_zimage("a red circle on white")

    assert result is None, "must return the normal failure value, not raise"
    out = capsys.readouterr().out
    assert "Unauthorized" in out or "401" in out, (
        "the real Kie code/msg must be printed, not swallowed by a crash"
    )


# ---------------------------------------------------------------------------
# 2. generate_video_veo — the Veo 3.1 clip path (image_client.py createTask
#    parse). Prod signature: "'NoneType' object has no attribute 'get'".
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_generate_video_veo_survives_null_data(monkeypatch, capsys):
    import shared.clients.image_client as image_client_mod
    _patch_httpx(monkeypatch, image_client_mod, NULL_DATA_FAILURE)

    async def _no_sleep(*a, **k):
        return None
    monkeypatch.setattr(image_client_mod.asyncio, "sleep", _no_sleep)

    ic = ImageClient(api_key="fake-key")
    result = await ic.generate_video_veo("a cat astronaut")

    assert result is None
    out = capsys.readouterr().out
    assert "NoneType" not in out, (
        "must not fall through to the generic 'Veo error: ...NoneType...' "
        "exception path — the null-data case has to be handled explicitly"
    )


# ---------------------------------------------------------------------------
# 3. poll_for_completion — the shared polling core every generate_* method
#    (nano-banana, GPT, z-image, InfiniteTalk, Grok, Seedance) funnels through.
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_poll_for_completion_survives_null_data(monkeypatch, capsys):
    import shared.clients.image_client as image_client_mod
    _patch_httpx(monkeypatch, image_client_mod, NULL_DATA_FAILURE)

    async def _no_sleep(*a, **k):
        return None
    monkeypatch.setattr(image_client_mod.asyncio, "sleep", _no_sleep)

    ic = ImageClient(api_key="fake-key")
    result = await ic.poll_for_completion("fake-task-id", max_attempts=1, poll_interval=0)

    assert result is None
    out = capsys.readouterr().out
    assert "Unauthorized" in out or "401" in out


# ---------------------------------------------------------------------------
# 4. _poll_veo_completion — Veo's own recordInfo poll (separate parse site).
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_poll_veo_completion_survives_null_data(monkeypatch, capsys):
    import shared.clients.image_client as image_client_mod
    _patch_httpx(monkeypatch, image_client_mod, NULL_DATA_FAILURE)

    async def _no_sleep(*a, **k):
        return None
    monkeypatch.setattr(image_client_mod.asyncio, "sleep", _no_sleep)

    ic = ImageClient(api_key="fake-key")
    result = await ic._poll_veo_completion("fake-task-id", max_attempts=1, poll_interval=0)

    assert result is None
    out = capsys.readouterr().out
    assert "Unauthorized" in out or "401" in out


# ---------------------------------------------------------------------------
# 5. upgrade_veo_to_1080p — same present-but-null trap on a 200 response.
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_upgrade_veo_to_1080p_survives_null_data(monkeypatch, capsys):
    import shared.clients.image_client as image_client_mod
    _patch_httpx(monkeypatch, image_client_mod, NULL_DATA_FAILURE)

    ic = ImageClient(api_key="fake-key")
    result = await ic.upgrade_veo_to_1080p("fake-task-id")

    assert result is None
    out = capsys.readouterr().out
    assert "Unauthorized" in out or "401" in out


# ---------------------------------------------------------------------------
# 6. sound_client.py — same trap family, found in the same shared/clients/
#    directory while auditing every Kie createTask/poll parse site.
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_sound_client_create_survives_null_data(monkeypatch, capsys):
    import shared.clients.sound_client as sound_client_mod
    _patch_httpx(monkeypatch, sound_client_mod, NULL_DATA_FAILURE)

    async def _no_sleep(*a, **k):
        return None
    monkeypatch.setattr(sound_client_mod.asyncio, "sleep", _no_sleep)

    sc = SoundClient(api_key="fake-key")
    result = await sc.generate_sound_effect("a door creaking")

    assert result is None
    out = capsys.readouterr().out
    assert "Unauthorized" in out or "401" in out


@pytest.mark.asyncio
async def test_sound_client_poll_survives_null_data(monkeypatch, capsys):
    import shared.clients.sound_client as sound_client_mod
    _patch_httpx(monkeypatch, sound_client_mod, NULL_DATA_FAILURE)

    async def _no_sleep(*a, **k):
        return None
    monkeypatch.setattr(sound_client_mod.asyncio, "sleep", _no_sleep)

    sc = SoundClient(api_key="fake-key")
    result = await sc._poll_for_completion("fake-task-id", max_attempts=1, poll_interval=0)

    assert result is None
    out = capsys.readouterr().out
    assert "Unauthorized" in out or "401" in out
