"""Tests for C36 (checklist §3.3 item 4, tasks/storyengine-wiring-fix-
checklist.md): the copilot classifier's confidence gating (agent_brain /
COPILOT_CONFIDENCE) had no telemetry — a misfire was invisible, and there
was no data to tune the 0.55 threshold with. Smallest useful fix: log +
store the classification confidence and chosen op, reusing the existing
`bot_activity` table (no new table — every other bot already writes rows
there) rather than building a dashboard this chunk.

Two layers:

1. `routes.chat._log_classification_confidence()` — writes ONE
   `bot_activity` row per classified turn (bot_name='copilot_classifier',
   a compact key=value message carrying kind/verb/confidence/source/gated),
   and never raises even when the write itself fails (telemetry must not
   break a chat turn).
2. Source lock: `_handle_copilot` actually calls it, right after the
   classifier decision is unpacked (kind/verb/conf) and BEFORE the
   confidence gate branches on it — so every turn is recorded, not just the
   ones that pass the gate.

Non-vacuous: `_log_classification_confidence` doesn't exist at all before
C36 (confirmed via `git stash`).

Run: cd storyengine/backend && ./venv/bin/python -m pytest tests/functional/test_c36_confidence_telemetry.py -q
"""
import asyncio
import os
import sys
from unittest.mock import patch

_BACKEND = os.path.join(os.path.dirname(__file__), "..", "..")
sys.path.insert(0, os.path.abspath(_BACKEND))

import routes.chat as chat_route  # noqa: E402

TENANT = "tenant-1"
VIDEO = "video-1"


def test_log_classification_confidence_writes_one_bot_activity_row():
    executed = []

    async def fake_execute(query, *args):
        executed.append((query, args))
        return "INSERT 0 1"

    with patch.object(chat_route, "execute", fake_execute):
        asyncio.run(chat_route._log_classification_confidence(
            TENANT, VIDEO, kind="action", verb="animate", confidence=0.42,
            source="brain", gated=True,
        ))

    assert len(executed) == 1
    query, args = executed[0]
    assert "INSERT INTO bot_activity" in query
    assert "copilot_classifier" in query
    tenant_arg, video_arg, message = args
    assert tenant_arg == TENANT
    assert video_arg == VIDEO
    assert "kind=action" in message
    assert "verb=animate" in message
    assert "confidence=0.420" in message
    assert "source=brain" in message
    assert "gated=True" in message
    print("✅ test_log_classification_confidence_writes_one_bot_activity_row")


def test_log_classification_confidence_records_ungated_legacy_turns_too():
    executed = []

    async def fake_execute(query, *args):
        executed.append((query, args))
        return "INSERT 0 1"

    with patch.object(chat_route, "execute", fake_execute):
        asyncio.run(chat_route._log_classification_confidence(
            TENANT, VIDEO, kind="read", verb="none", confidence=0.91,
            source="legacy", gated=False,
        ))

    message = executed[0][1][2]
    assert "source=legacy" in message
    assert "gated=False" in message
    print("✅ test_log_classification_confidence_records_ungated_legacy_turns_too")


def test_log_classification_confidence_fails_soft():
    async def boom(*a, **k):
        raise RuntimeError("db is down")

    with patch.object(chat_route, "execute", boom):
        # Must not raise -- a broken telemetry write can never break a chat turn.
        asyncio.run(chat_route._log_classification_confidence(
            TENANT, VIDEO, kind="action", verb="images", confidence=0.7,
            source="brain", gated=False,
        ))
    print("✅ test_log_classification_confidence_fails_soft")


def test_handle_copilot_calls_confidence_logger_before_the_gate():
    """Source lock: the classifier's kind/verb/conf must be logged BEFORE the
    `if verb not in COPILOT_ACTIONS or conf < COPILOT_CONFIDENCE` gate, so a
    turn that gets stuck in the clarify-loop is recorded too -- that's the
    exact case the checklist calls out ("misfires are invisible")."""
    src = open(os.path.join(_BACKEND, "routes", "chat.py")).read()
    body = src.split("async def _handle_copilot(")[1]
    log_pos = body.index("_log_classification_confidence(")
    gate_pos = body.index("if verb not in COPILOT_ACTIONS or conf < COPILOT_CONFIDENCE")
    assert log_pos < gate_pos, "confidence must be logged before the gate branches on it"
    print("✅ test_handle_copilot_calls_confidence_logger_before_the_gate")


if __name__ == "__main__":
    test_log_classification_confidence_writes_one_bot_activity_row()
    test_log_classification_confidence_records_ungated_legacy_turns_too()
    test_log_classification_confidence_fails_soft()
    test_handle_copilot_calls_confidence_logger_before_the_gate()
    print("All C36 confidence-telemetry tests passed!")
