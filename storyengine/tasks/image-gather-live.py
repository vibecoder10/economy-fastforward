"""One guarded gather request and compact provider-state readback."""
import json
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

import httpx

ROOT = Path(__file__).resolve().parents[1]
VIDEO = "44dbf2b2-a27a-47ea-a608-4c31c906be9a"
TENANT = "561b872d-7b73-45e3-9c44-7f30c3566eda"


def timestamp():
    return datetime.now(timezone.utc).isoformat()


token = subprocess.run([str(ROOT / "scripts/se.sh"), "token"], capture_output=True, text=True, check=True).stdout.strip()
with httpx.Client(base_url="https://storyengine.dev", headers={"Authorization": "Bearer " + token, "X-Active-Tenant": TENANT}, timeout=90) as client:
    def get(path):
        response = client.get(path)
        response.raise_for_status()
        return response.json()

    task = get("/api/pipeline/task/" + VIDEO)
    video = get("/api/videos/" + VIDEO)
    video = video.get("video", video)
    payload = video.get("research_payload") or {}
    if isinstance(payload, str):
        payload = json.loads(payload)
    dashboard = get("/api/pipeline/roster-dashboard/" + VIDEO)
    if len(sys.argv) > 1 and sys.argv[1] == "gather":
        receipt = ROOT / "tasks/image-gather-request.json"
        assert not receipt.exists(), "A gather request was already attempted; reconcile its receipt."
        assert task.get("status") not in {"running", "pending", "queued"}, "This video already has active work."
        assert get("/api/health")["active_work"]["total"] == 0, "Production has active work."
        assert (payload.get("roster_selection") or {}).get("status") == "completed"
        assert (payload.get("unit_roster_validation") or {}).get("passed") is True
        assert len(payload.get("unit_roster") or []) == 20
        receipt.write_text(json.dumps({"at": timestamp(), "video": VIDEO, "outcome": "unknown"}))
        response = client.post("/api/pipeline/roster-images/" + VIDEO)
        receipt.write_text(json.dumps({"at": timestamp(), "video": VIDEO, "http": response.status_code, "response": response.json()}, indent=2))
        print(receipt.read_text())
        response.raise_for_status()
    else:
        refs = [{"machine": row.get("machine"), **(row.get("reference") or {})} for row in dashboard.get("units", [])]
        result = {"at": timestamp(), "task": task, "video_status": video.get("status"),
                  "roster_count": len(payload.get("unit_roster") or []),
                  "roster_status": (payload.get("roster_selection") or {}).get("status"),
                  "images": payload.get("roster_images"), "references": refs,
                  "ready_cards": dashboard.get("ready"), "saved_card_count": len(payload.get("unit_research_cards") or []),
                  "history_counts": [len((row.get("payload") or {}).get("unit_roster") or []) for row in payload.get("roster_selection_history", [])]}
        (ROOT / "tasks/image-gather-live-latest.json").write_text(json.dumps(result, indent=2))
        with (ROOT / "tasks/image-gather-progress.jsonl").open("a") as handle:
            handle.write(json.dumps(result) + "\n")
        if len(sys.argv) > 1 and sys.argv[1] == "compact":
            state = result.get("images") or {}
            print(json.dumps({"at": result["at"], "task": task.get("status"),
                              "images": {key: state.get(key) for key in ("status", "total", "processed", "verified")},
                              "missing_checked": [{"machine": r["machine"], "reason": r.get("reason_code")} for r in refs if r.get("reason_code")],
                              "cards": result["saved_card_count"], "history": result["history_counts"]}))
        else:
            print(json.dumps({**{key: value for key, value in result.items() if key != "references"}, "verified_refs": sum(row.get("status") == "verified" for row in refs)}, indent=2))
