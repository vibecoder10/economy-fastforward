"""Structured JSON logging for StoryEngine backend.

Replaces print() with structured logs. Every entry is a single JSON line
with timestamp, level, module, and optional context fields (tenant_id, etc.).
"""

import json
import logging
import os
import time
from collections import defaultdict
from datetime import datetime, timezone

from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request


class StructuredFormatter(logging.Formatter):
    """JSON log formatter with contextual fields."""

    def format(self, record: logging.LogRecord) -> str:
        entry: dict = {
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "level": record.levelname,
            "message": record.getMessage(),
            "module": record.module,
        }
        for field in ("tenant_id", "video_id", "stage", "duration_ms"):
            val = getattr(record, field, None)
            if val is not None:
                entry[field] = val
        if record.exc_info and record.exc_info[0]:
            entry["exception"] = self.formatException(record.exc_info)
        return json.dumps(entry)


def setup_logging() -> logging.Logger:
    """Configure structured logging for the application.

    Returns the 'storyengine' logger for use across the backend.
    """
    root = logging.getLogger()
    root.setLevel(logging.INFO)

    # Remove any existing handlers (avoid duplicates on reload)
    root.handlers.clear()

    fmt = StructuredFormatter()

    console = logging.StreamHandler()
    console.setFormatter(fmt)
    root.addHandler(console)

    log_path = os.getenv("LOG_FILE", "/tmp/storyengine-structured.log")
    try:
        fh = logging.FileHandler(log_path)
        fh.setFormatter(fmt)
        root.addHandler(fh)
    except OSError:
        pass  # File logging optional (e.g., read-only FS)

    # Quiet noisy libraries
    for name in ("asyncpg", "httpx", "httpcore", "uvicorn.access", "watchfiles"):
        logging.getLogger(name).setLevel(logging.WARNING)

    return logging.getLogger("storyengine")


# ---------------------------------------------------------------------------
# Error rate tracking
# ---------------------------------------------------------------------------

_error_counts: dict[str, int] = defaultdict(int)
_error_window_start: float = time.time()
_ERROR_WINDOW = 300  # 5 minutes
_ERROR_THRESHOLD = 10


def track_error() -> None:
    """Increment error counter and warn if threshold exceeded."""
    global _error_window_start
    now = time.time()
    if now - _error_window_start > _ERROR_WINDOW:
        _error_counts.clear()
        _error_window_start = now
    _error_counts["total"] = _error_counts.get("total", 0) + 1
    if _error_counts["total"] == _ERROR_THRESHOLD:
        logger.warning(
            "Error rate threshold exceeded: %d errors in 5 minutes",
            _ERROR_THRESHOLD,
        )


# Module-level logger — import this in other modules
logger = setup_logging()


# ---------------------------------------------------------------------------
# Request logging middleware
# ---------------------------------------------------------------------------


class RequestLoggingMiddleware(BaseHTTPMiddleware):
    """Log every request with timing and tenant context."""

    async def dispatch(self, request: Request, call_next):
        path = request.url.path
        if path in ("/api/health", "/api/health/detailed"):
            return await call_next(request)

        start = time.time()
        response = await call_next(request)
        duration_ms = round((time.time() - start) * 1000, 1)

        # Best-effort tenant extraction (no error on failure)
        tenant_id = None
        auth = request.headers.get("authorization", "")
        if auth.startswith("Bearer "):
            import jwt as pyjwt

            try:
                payload = pyjwt.decode(
                    auth[7:],
                    os.getenv("SESSION_SECRET", ""),
                    algorithms=["HS256"],
                )
                tid = payload.get("tenant_id")
                tenant_id = str(tid)[:8] if tid else None
            except Exception:
                pass

        extra: dict = {"duration_ms": duration_ms}
        if tenant_id:
            extra["tenant_id"] = tenant_id

        msg = "%s %s → %d (%.0fms)"
        args = (request.method, path, response.status_code, duration_ms)

        if response.status_code >= 500:
            track_error()
            logger.error(msg, *args, extra=extra)
        elif response.status_code >= 400:
            logger.warning(msg, *args, extra=extra)
        else:
            logger.info(msg, *args, extra=extra)

        return response
