"""Shared pytest configuration for storyengine/backend tests.

This file does three jobs:

1. Adds the backend root to sys.path so test files can import backend modules.

2. Refuses to run on Python < 3.10 with one clear message. 26 test files use
   3.10+ syntax like `str | None`; on Python 3.9 they explode into a wall of
   collection errors that hides the real signal.

3. Isolates each test file's import-time side effects. Many test files stub
   sys.modules (fake `database`, `vault`, `storage`, ...) or mutate os.environ
   at module level so they can import their module-under-test without a live
   DB or real API keys. pytest imports every test file up front in a single
   process, so without isolation the first file's stubs leak into every later
   file: files that pass standalone fail in a full run (the 2026-07-15
   reconciliation measured ~225 such failures). The IsolatedModule below
   snapshots sys.modules, os.environ and sys.path around each test file's
   import, puts the shared state back right after the import finishes, and
   re-applies that file's own changes only while that file's tests run. Every
   file therefore imports and runs in the same world it sees standalone,
   regardless of run order.
"""
import asyncio
import os
import sys
import types

import pytest

# ---------------------------------------------------------------------------
# 1. import path
# ---------------------------------------------------------------------------
_BACKEND_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _BACKEND_ROOT not in sys.path:
    sys.path.insert(0, _BACKEND_ROOT)


# ---------------------------------------------------------------------------
# 2. interpreter guard
# ---------------------------------------------------------------------------
def pytest_configure(config):
    if sys.version_info < (3, 10):
        raise pytest.UsageError(
            "storyengine backend tests need Python 3.10+ (many files use "
            f"`str | None` syntax); this interpreter is {sys.version.split()[0]}.\n"
            "Run them with the backend venv instead:\n"
            "  cd storyengine/backend && ./venv/bin/python -m pytest tests/ -q\n"
            "Create the venv once with:\n"
            "  python3.11 -m venv venv && ./venv/bin/pip install "
            "-r requirements.txt -r requirements-test.txt"
        )
    # The isolation below overrides pytest.Module._getobj. If a pytest upgrade
    # ever renames that internal, fail loudly instead of silently running
    # without isolation (which would bring the cross-file pollution back).
    if not hasattr(pytest.Module, "_getobj"):
        raise pytest.UsageError(
            "tests/conftest.py: pytest.Module._getobj is gone in this pytest "
            "version; the per-file state isolation in conftest.py needs "
            "updating before the suite can give a trustworthy signal."
        )


# ---------------------------------------------------------------------------
# 3. per-file state isolation
# ---------------------------------------------------------------------------
_MISSING = object()

# Everything under the repo (backend source, skills/video-pipeline/shared,
# ...) is "first-party": test files import these against their own stubs, so
# they must be evicted after each file and re-imported fresh by the next one.
# The venv lives inside the backend dir, so carve it out explicitly.
_REPO_ROOT = os.path.realpath(
    os.path.dirname(os.path.dirname(_BACKEND_ROOT))
) + os.sep
_VENV_ROOT = os.path.realpath(sys.prefix) + os.sep


def _is_real_module(mod):
    """True for genuinely imported modules (stdlib, site-packages, repo
    source). False for hand-made stubs (bare types.ModuleType shells,
    MagicMock, SimpleNamespace) that tests inject into sys.modules."""
    if not isinstance(mod, types.ModuleType):
        return False
    if isinstance(getattr(mod, "__file__", None), str):
        return True
    return getattr(mod, "__spec__", None) is not None


def _is_shared_cacheable(mod):
    """True for modules safe to leave in sys.modules for the whole run:
    real stdlib / site-packages modules. Repo modules and stubs are not -
    each test file must get a fresh import against its own stubs."""
    if not _is_real_module(mod):
        return False
    f = getattr(mod, "__file__", None)
    if isinstance(f, str):
        p = os.path.realpath(f)
        return p.startswith(_VENV_ROOT) or not p.startswith(_REPO_ROOT)
    # No __file__: builtin, frozen, or namespace package. Namespace packages
    # rooted inside the repo must be evicted like any other repo module.
    for p in list(getattr(mod, "__path__", []) or []):
        rp = os.path.realpath(str(p))
        if rp.startswith(_REPO_ROOT) and not rp.startswith(_VENV_ROOT):
            return False
    return True


class _FileDelta:
    """What one test file's module-level code did to shared state."""

    def __init__(self):
        self.mods_added = {}    # name -> module the file expects at run time
        self.mods_changed = {}  # name -> (original, file's replacement)
        self.mods_removed = {}  # name -> original the file deleted
        self.env_added = {}     # key -> file's value
        self.env_changed = {}   # key -> (original, file's value)
        self.env_removed = {}   # key -> original value
        self.path_after = None  # sys.path as the file's import left it


_DELTAS = {}  # test file realpath -> _FileDelta


class IsolatedModule(pytest.Module):
    """A pytest Module that imports the test file inside a state bracket."""

    def _getobj(self):
        pre_mods = dict(sys.modules)
        pre_env = dict(os.environ)
        pre_path = list(sys.path)
        try:
            return super()._getobj()
        finally:
            self._se_capture_and_restore(pre_mods, pre_env, pre_path)

    def _se_capture_and_restore(self, pre_mods, pre_env, pre_path):
        delta = _FileDelta()
        my_file = os.path.realpath(str(self.path))

        # Keep the just-imported test module (and its package ancestors) in
        # sys.modules - pytest and plugins may look it up by name later.
        kept = set()
        for name, mod in list(sys.modules.items()):
            if name in pre_mods:
                continue
            f = getattr(mod, "__file__", None)
            if isinstance(f, str) and os.path.realpath(f) == my_file:
                kept.add(name)
                while "." in name:
                    name = name.rsplit(".", 1)[0]
                    kept.add(name)

        for name in list(sys.modules.keys()):
            mod = sys.modules[name]
            if name not in pre_mods:
                if name in kept or _is_shared_cacheable(mod):
                    continue
                delta.mods_added[name] = mod
                del sys.modules[name]
            elif mod is not pre_mods[name]:
                delta.mods_changed[name] = (pre_mods[name], mod)
                sys.modules[name] = pre_mods[name]
        for name, mod in pre_mods.items():
            if name not in sys.modules:
                delta.mods_removed[name] = mod
                sys.modules[name] = mod

        for key in list(os.environ.keys()):
            val = os.environ[key]
            if key not in pre_env:
                delta.env_added[key] = val
                del os.environ[key]
            elif val != pre_env[key]:
                delta.env_changed[key] = (pre_env[key], val)
                os.environ[key] = pre_env[key]
        for key, val in pre_env.items():
            if key not in os.environ:
                delta.env_removed[key] = val
                os.environ[key] = val

        delta.path_after = list(sys.path)
        sys.path[:] = pre_path

        _DELTAS[my_file] = delta


def pytest_pycollect_makemodule(module_path, parent):
    return IsolatedModule.from_parent(parent, path=module_path)


@pytest.fixture(autouse=True, scope="module")
def _se_file_state(request):
    """Re-applies the current test file's import-time stubs and env for the
    duration of its tests, then puts shared state back for the next file."""
    try:
        my_file = os.path.realpath(request.module.__file__)
    except Exception:
        yield
        return
    delta = _DELTAS.get(my_file)
    if delta is None:
        yield
        return

    saved_mods = {}
    saved_env = {}
    saved_path = list(sys.path)

    def _set_mod(name, mod):
        saved_mods[name] = sys.modules.get(name, _MISSING)
        sys.modules[name] = mod

    for name, mod in delta.mods_added.items():
        _set_mod(name, mod)
    for name, (_orig, repl) in delta.mods_changed.items():
        _set_mod(name, repl)
    for name in delta.mods_removed:
        saved_mods[name] = sys.modules.pop(name, _MISSING)

    for key, val in delta.env_added.items():
        saved_env[key] = os.environ.get(key, _MISSING)
        os.environ[key] = val
    for key, (_orig, val) in delta.env_changed.items():
        saved_env[key] = os.environ.get(key, _MISSING)
        os.environ[key] = val
    for key in delta.env_removed:
        saved_env[key] = os.environ.pop(key, _MISSING)

    if delta.path_after is not None:
        sys.path[:] = delta.path_after

    # Event-loop state is shared too: an earlier file's asyncio.run() or
    # pytest-asyncio teardown leaves the policy marked "loop was set, then
    # cleared", which makes legacy asyncio.get_event_loop() callers raise
    # RuntimeError. Give every file the virgin policy it sees standalone.
    asyncio.set_event_loop_policy(None)

    before_keys = set(sys.modules)
    try:
        yield
    finally:
        # Evict anything non-shareable the tests imported lazily at run time
        # (a repo module imported inside a test would otherwise stay cached,
        # bound to this file's stubs, and poison a later file).
        for name in list(sys.modules.keys()):
            if name not in before_keys and not _is_shared_cacheable(
                sys.modules[name]
            ):
                del sys.modules[name]
        for name, val in saved_mods.items():
            if val is _MISSING:
                sys.modules.pop(name, None)
            else:
                sys.modules[name] = val
        for key, val in saved_env.items():
            if val is _MISSING:
                os.environ.pop(key, None)
            else:
                os.environ[key] = val
        sys.path[:] = saved_path
        asyncio.set_event_loop_policy(None)
