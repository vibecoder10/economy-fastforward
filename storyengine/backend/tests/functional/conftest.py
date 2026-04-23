"""Shared fixtures for queue recovery tests.

Mocks heavy dependencies (asyncpg, database) so tests can run
without a live DB or the full dependency tree.
"""
import sys
from pathlib import Path
from unittest.mock import MagicMock, AsyncMock

# Ensure backend is on sys.path for imports
backend_dir = str(Path(__file__).parent.parent.parent)
if backend_dir not in sys.path:
    sys.path.insert(0, backend_dir)

# Mock heavy modules that aren't available in test env
for mod_name in [
    "asyncpg", "database", "error_utils", "status_map", "vault",
    "extraction", "storage", "supabase_adapter", "auth",
    "logging_config", "rate_limit",
    "shared", "shared.clients", "shared.clients.anthropic_client",
    "shared.clients.google_client", "shared.clients.slack_client",
    "shared.clients.image_client", "shared.clients.elevenlabs_client",
    "shared.clients.gemini_client", "shared.clients.deterministic_splitter",
    "orchestrator", "orchestrator.pipeline_constants", "orchestrator.pipeline_config",
]:
    if mod_name not in sys.modules:
        sys.modules[mod_name] = MagicMock()

# Ensure database mock has the async helpers
_db_mock = sys.modules["database"]
_db_mock.fetch_one = AsyncMock(return_value=None)
_db_mock.fetch_all = AsyncMock(return_value=[])
_db_mock.execute = AsyncMock(return_value="UPDATE 0")
_db_mock.get_pool = AsyncMock()
_db_mock.close_pool = AsyncMock()

# Ensure error_utils has humanize_error
sys.modules["error_utils"].humanize_error = lambda msg, **kw: str(msg) if msg else ""

# Ensure status_map has required functions
_sm = sys.modules["status_map"]
_sm.to_supabase = lambda x: x
_sm.to_pipeline = lambda x: x
_sm.get_next_status_supabase = lambda x: x
_sm.is_at_or_past_stage = lambda *a: True
_sm.get_bot_name = lambda x: x
_sm.STAGE_BOT_MAP = {}
