import asyncio
import json
import sys
from pathlib import Path

# audit_roster_selection imports shared.* lazily; only pipeline_executor puts
# skills/video-pipeline on sys.path, so a standalone run needs it explicitly.
sys.path.insert(0, str(Path(__file__).resolve().parents[3] / "skills" / "video-pipeline"))

import roster_selection
from roster_coverage import audit_roster_selection


def _payload(count: int) -> dict:
    return {
        "unit_roster": [{"name": f"Machine {index}"} for index in range(count)],
        "roster_selection": {"version": 1, "settings": {"duration_minutes": count, "minutes_per_machine": 1}},
    }


def test_selection_search_budget_is_bounded_by_roster_size():
    assert roster_selection.selection_search_budget(_payload(20)) == 24
    assert roster_selection.selection_search_budget(_payload(1)) == 12
    assert roster_selection.selection_search_budget(_payload(100)) == 40


def test_selection_fingerprint_includes_search_budget(monkeypatch):
    payload = _payload(20)
    before = roster_selection.selection_fingerprint("Every Example Ever Built", payload)
    monkeypatch.setattr(roster_selection, "selection_search_budget", lambda _payload: 25)
    assert roster_selection.selection_fingerprint("Every Example Ever Built", payload) != before


def test_selection_audit_uses_roster_sized_search_budget():
    class Client:
        async def generate(self, **kwargs):
            self.kwargs = kwargs
            return json.dumps({
                "passed": True,
                "sources": [
                    {"url": "https://history.navy.mil/a", "supports": "identity"},
                    {"url": "https://archives.gov/b", "supports": "identity"},
                ],
                "findings": [],
                "summary": "Verified",
            })

    client = Client()
    result = asyncio.run(audit_roster_selection(client, "Every Example Ever Built", _payload(20)))
    assert result["passed"] is True
    assert client.kwargs["tools"][0]["max_uses"] == 24
