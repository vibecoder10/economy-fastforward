#!/usr/bin/env python3
"""Run DVSU Call 3 for ONE locked machine, on the VPS, with the agent LLM relay.

Runs PipelineExecutor.run_one_machine_research - the exact method behind the app's
POST /api/pipeline/machine-research-one - in its own process, so it can wait as long as the
relay needs (that HTTP route is synchronous and would hold the request open). The tenant's
`tenants.agent_llm_relay` flag makes every model call park in agent_llm_requests; answer
them with the MCP tools list_pending_llm_requests / answer_llm_request. Re-running after a
timeout or a restart replays every answer already given.

Usage (on the VPS, via se run; SE_ROOT = the storyengine/ dir holding .env and backend/):
  SE_ROOT=$HOME/projects/economy-fastforward/storyengine \
    $SE_ROOT/backend/venv/bin/python3 relay_drive_one_machine.py <tenant_id> <video_id> "<machine>"
"""
import asyncio
import json
import os
import sys
from pathlib import Path

ROOT = Path(os.environ.get("SE_ROOT") or Path(__file__).resolve().parents[1])


def load_env() -> None:
    env = ROOT / ".env"
    if not env.exists():
        return
    for raw in env.read_text().splitlines():
        line = raw.strip()
        if line and not line.startswith("#") and "=" in line:
            key, value = line.split("=", 1)
            os.environ.setdefault(key.strip(), value.strip().strip("\"'"))


async def main(tenant_id: str, video_id: str, machine: str) -> int:
    load_env()
    sys.path.insert(0, str(ROOT / "backend"))
    from pipeline_executor import PipelineExecutor

    print(f"[drive] tenant={tenant_id} video={video_id} machine={machine!r}", flush=True)
    result = await PipelineExecutor(tenant_id).run_one_machine_research(video_id, machine)
    card = result.get("research_card") or {}
    summary = {
        "status": result.get("status"),
        "machine": result.get("machine"),
        "error": result.get("error"),
        "card_passed": (card.get("research_summary") or {}).get("passed"),
        "script_brief_passed": (card.get("script_brief_readiness") or {}).get("passed"),
        "provenance": card.get("provenance_status"),
    }
    print("[drive] RESULT " + json.dumps(summary, default=str), flush=True)
    return 0 if result.get("status") in ("completed", "success", "ok") else 1


if __name__ == "__main__":
    if len(sys.argv) != 4:
        sys.exit(__doc__)
    sys.exit(asyncio.run(main(*sys.argv[1:])))
