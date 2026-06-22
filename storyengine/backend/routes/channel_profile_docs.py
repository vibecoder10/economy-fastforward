"""Channel profile document routes."""

from datetime import datetime, timezone

from fastapi import APIRouter, BackgroundTasks, Depends, Query

from auth import get_tenant_id
from channel_profile_documents import (
    get_channel_profile_documents,
    refresh_channel_profile_documents,
)

router = APIRouter(prefix="/api/channel-profile", tags=["channel-profile-docs"])

_refresh_tasks: dict[str, dict] = {}


@router.get("/documents")
async def list_channel_profile_documents(tenant_id: str = Depends(get_tenant_id)):
    """Return profile document links and current refresh status."""
    tenant_id = str(tenant_id)
    data = await get_channel_profile_documents(tenant_id)
    data["refresh_status"] = _refresh_tasks.get(tenant_id, {"running": False, "status": "idle"})
    return data


@router.post("/documents/refresh")
async def refresh_channel_profile_documents_route(
    background_tasks: BackgroundTasks,
    transcript_limit: int = Query(default=5, ge=0, le=10),
    tenant_id: str = Depends(get_tenant_id),
):
    """Start a background refresh for profile Word docs in Google Drive."""
    tenant_id = str(tenant_id)
    current = _refresh_tasks.get(tenant_id)
    if current and current.get("running"):
        return {"status": "already_running", **current}

    _refresh_tasks[tenant_id] = {
        "running": True,
        "status": "running",
        "started_at": datetime.now(timezone.utc).isoformat(),
        "last_error": None,
    }
    background_tasks.add_task(_run_refresh, tenant_id, transcript_limit)
    return {"status": "started", **_refresh_tasks[tenant_id]}


@router.get("/documents/refresh/status")
async def channel_profile_documents_refresh_status(tenant_id: str = Depends(get_tenant_id)):
    """Return the current profile-document refresh task status."""
    return _refresh_tasks.get(str(tenant_id), {"running": False, "status": "idle"})


async def _run_refresh(tenant_id: str, transcript_limit: int):
    try:
        result = await refresh_channel_profile_documents(tenant_id, transcript_limit=transcript_limit)
        _refresh_tasks[tenant_id] = {
            "running": False,
            "status": "complete",
            "completed_at": datetime.now(timezone.utc).isoformat(),
            "last_error": None,
            "result": {
                "folder_url": result.get("folder_url"),
                "document_count": len(result.get("documents") or []),
                "transcript_backfill": result.get("transcript_backfill"),
            },
        }
    except Exception as exc:
        _refresh_tasks[tenant_id] = {
            "running": False,
            "status": "failed",
            "completed_at": datetime.now(timezone.utc).isoformat(),
            "last_error": str(exc),
        }
