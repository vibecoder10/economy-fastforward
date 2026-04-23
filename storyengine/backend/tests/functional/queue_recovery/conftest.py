"""Shared fixtures for queue recovery tests.

Mocks heavy dependencies (asyncpg, database) so tests can run
without a live DB or the full dependency tree. Uses a function-scoped
(per-test) fixture with full sys.modules save/restore so mocks don't
bleed between tests or into other test files.
"""
import sys
import pytest
from pathlib import Path
from unittest.mock import MagicMock, AsyncMock

# Ensure backend is on sys.path for imports
backend_dir = str(Path(__file__).parent.parent.parent)
if backend_dir not in sys.path:
    sys.path.insert(0, backend_dir)

_MOCKED_MODULES = [
    "asyncpg", "database", "error_utils", "status_map", "vault",
    "extraction", "storage", "supabase_adapter", "auth",
    "logging_config", "rate_limit",
    "shared", "shared.clients", "shared.clients.anthropic_client",
    "shared.clients.google_client", "shared.clients.slack_client",
    "shared.clients.image_client", "shared.clients.elevenlabs_client",
    "shared.clients.gemini_client", "shared.clients.deterministic_splitter",
    "orchestrator", "orchestrator.pipeline_constants", "orchestrator.pipeline_config",
]

# Modules that import from _MOCKED_MODULES at their own module level.
# These must also be evicted from sys.modules after each test so they
# don't retain stale references to the mocked objects (e.g.
# pipeline_executor.humanize_error bound to the mock lambda).
# routes.pipeline imports error_utils/database/status_map directly, so
# it must also be evicted to avoid contaminating tests that check real behaviour.
_EVICT_AFTER_TEST = [
    "pipeline_executor", "task_store", "worker", "job_queue",
    "routes", "routes.pipeline",
]


@pytest.fixture(autouse=True)
def _install_heavy_mocks():
    """Install mocks for heavy deps; restore sys.modules after each test.

    Preserves module-attribute state to avoid contaminating tests that
    check real behavior of error_utils, status_map, etc.
    """
    # Save original sys.modules state
    originals = {k: sys.modules.get(k) for k in _MOCKED_MODULES}
    # Save original attributes on modules that already exist (to avoid
    # mutating real module objects with our lambda patches)
    orig_attrs: dict = {}

    # Install MagicMock for modules not yet in sys.modules
    for mod_name in _MOCKED_MODULES:
        if mod_name not in sys.modules:
            sys.modules[mod_name] = MagicMock()

    # Configure database mock async helpers
    _db_mock = sys.modules["database"]
    _db_mock.fetch_one = AsyncMock(return_value=None)
    _db_mock.fetch_all = AsyncMock(return_value=[])
    _db_mock.execute = AsyncMock(return_value="UPDATE 0")
    _db_mock.get_pool = AsyncMock()
    _db_mock.close_pool = AsyncMock()

    # Configure error_utils — save + patch only if it's already a real module
    _eu = sys.modules["error_utils"]
    if hasattr(_eu, "humanize_error"):
        orig_attrs[("error_utils", "humanize_error")] = _eu.humanize_error
    _eu.humanize_error = lambda msg, **kw: str(msg) if msg else ""

    # Configure status_map mock
    _sm = sys.modules["status_map"]
    for attr in ("to_supabase", "to_pipeline", "get_next_status_supabase",
                 "is_at_or_past_stage", "get_bot_name", "STAGE_BOT_MAP"):
        if hasattr(_sm, attr):
            orig_attrs[("status_map", attr)] = getattr(_sm, attr)
    _sm.to_supabase = lambda x: x
    _sm.to_pipeline = lambda x: x
    _sm.get_next_status_supabase = lambda x: x
    _sm.is_at_or_past_stage = lambda *a: True
    _sm.get_bot_name = lambda x: x
    _sm.STAGE_BOT_MAP = {}

    yield

    # Restore patched attributes on existing module objects
    for (mod_name, attr), val in orig_attrs.items():
        mod = sys.modules.get(mod_name)
        if mod is not None:
            setattr(mod, attr, val)

    # Evict modules that bound mocked symbols at import time so
    # subsequent tests in other files get fresh re-imports.
    for mod_name in _EVICT_AFTER_TEST:
        sys.modules.pop(mod_name, None)

    # Restore sys.modules for mocked dependencies
    for mod_name, original in originals.items():
        if original is None:
            sys.modules.pop(mod_name, None)
        else:
            sys.modules[mod_name] = original
