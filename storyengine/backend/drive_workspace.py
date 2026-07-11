"""Idempotent, app-owned Google Drive workspace for StoryEngine videos.

This is deliberately separate from the creator OAuth Script <-> Drive feature in
routes/videos.py.  Workspaces use the service GoogleClient used by media storage.
Drive failures are allowed to propagate here; callers that are lifecycle hooks use
``sync_video_workspace_fail_soft`` so pipeline/database work is never blocked.
"""

from __future__ import annotations

import asyncio
import json
import logging
from typing import Any, Callable, Optional

from database import execute, fetch_all, fetch_one, get_pool

logger = logging.getLogger(__name__)
FOLDER_MIME = "application/vnd.google-apps.folder"
DOC_MIME = "application/vnd.google-apps.document"


def _display(value: Any) -> str:
    if isinstance(value, dict):
        nested = value.get("unit") or value.get("machine")
        if nested:
            return _display(nested)
        name = str(value.get("name") or value.get("title") or "").strip()
        code = str(value.get("designation") or value.get("code") or "").strip()
        return f"{code} {name}".strip() if code and code.lower() not in name.lower() else name or code
    return str(value or "").strip()


def _payload(value: Any) -> dict:
    if isinstance(value, dict):
        return value
    if isinstance(value, str) and value.strip():
        try:
            parsed = json.loads(value)
            return parsed if isinstance(parsed, dict) else {}
        except (TypeError, ValueError):
            return {"research": value}
    return {}


def _machine_roster_text(title: str, research: dict) -> str:
    roster = research.get("unit_roster") or research.get("machine_roster") or []
    lines = ["Machine Roster", title, ""]
    if isinstance(roster, list) and roster:
        lines.extend(f"{i}. {_display(item)}" for i, item in enumerate(roster, 1) if _display(item))
    else:
        lines.append("Roster will appear here after machine research is complete.")
    return "\n".join(lines).rstrip() + "\n"


def _research_text(title: str, research: dict) -> str:
    lines = ["Research", title, ""]
    if not research:
        lines.append("Research will appear here after the research stage is complete.")
    else:
        for key, value in research.items():
            if value in (None, "", [], {}):
                continue
            heading = str(key).replace("_", " ").title()
            lines.extend([heading, json.dumps(value, ensure_ascii=False, indent=2) if isinstance(value, (dict, list)) else str(value), ""])
    return "\n".join(lines).rstrip() + "\n"


def _workspace_folder_name(title: str, video_id: str) -> str:
    """Keep folder names readable while guaranteeing one folder per video."""
    return f"{title} — {video_id[:8]}"


def _script_text(title: str, video_script: str, scenes: list[dict]) -> str:
    lines = ["Script", title, ""]
    if scenes:
        for index, scene in enumerate(scenes, 1):
            number = scene.get("scene") if scene.get("scene") is not None else index
            lines.extend([f"Scene {number}", str(scene.get("scene_text") or "").strip(), ""])
    elif video_script.strip():
        lines.append(video_script.strip())
    else:
        lines.append("Script will appear here after the scripting stage is complete.")
    return "\n".join(lines).rstrip() + "\n"


def _format_requests(text: str) -> list[dict]:
    """Apply stable title/subtitle/heading styles after a whole-body refresh."""
    requests: list[dict] = []
    offset = 1
    for index, line in enumerate(text.splitlines(keepends=True)):
        stripped = line.rstrip("\n")
        end = offset + len(line)
        style: Optional[str] = None
        if index == 0:
            style = "TITLE"
        elif index == 1:
            style = "SUBTITLE"
        elif stripped and (stripped.startswith("Scene ") or (index > 1 and len(stripped) < 80 and not stripped[0].isdigit())):
            style = "HEADING_2"
        if style:
            requests.append({"updateParagraphStyle": {
                "range": {"startIndex": offset, "endIndex": end},
                "paragraphStyle": {"namedStyleType": style},
                "fields": "namedStyleType",
            }})
        offset = end
    return requests


def _ensure_named_folder(client: Any, parent_id: str, name: str) -> str:
    found = client.search_folder(name, parent_id=parent_id)
    return found["id"] if found else client.create_folder(name, parent_id=parent_id)["id"]


def _upsert_doc(client: Any, folder_id: str, name: str, text: str) -> str:
    existing = client.search_file(name, folder_id)
    if existing and existing.get("mimeType") == DOC_MIME:
        doc_id = existing["id"]
    else:
        created = client.create_document(name, folder_id)
        doc_id = created.get("id")
        if not doc_id:
            raise RuntimeError(f"Google Docs unavailable while creating {name}")
    if not client.replace_document_body(doc_id, text):
        raise RuntimeError(f"Google Docs unavailable while refreshing {name}")
    formatting = _format_requests(text)
    if formatting:
        client.docs_service.documents().batchUpdate(
            documentId=doc_id, body={"requests": formatting}
        ).execute()
    return doc_id


def _sync_drive(client: Any, video: dict, scenes: list[dict]) -> dict:
    video_id = str(video["id"])
    title = (video.get("video_title") or "Untitled").strip() or "Untitled"
    folder_name = _workspace_folder_name(title, video_id)
    folder_id = video.get("drive_folder_id")
    if folder_id:
        # Video id is the canonical identity; keep the one persisted folder and
        # rename it when a title changes instead of creating another title match.
        client.drive_service.files().update(fileId=folder_id, body={"name": folder_name}, fields="id, name").execute()
    else:
        workspace_root = getattr(client, "workspace_root_folder_id", None) or client.parent_folder_id
        folder = client.get_or_create_folder(folder_name, parent_id=workspace_root)
        folder_id = folder["id"]

    images_id = _ensure_named_folder(client, folder_id, "Images")
    final_id = _ensure_named_folder(client, folder_id, "Final Video")
    research = _payload(video.get("research_payload"))
    docs = {
        # Stable filenames prevent a title edit from creating stale duplicates.
        "machine_roster": _upsert_doc(client, folder_id, "01 — Machine Roster", _machine_roster_text(title, research)),
        "research": _upsert_doc(client, folder_id, "02 — Research", _research_text(title, research)),
        "script": _upsert_doc(client, folder_id, "03 — Script", _script_text(title, str(video.get("script") or ""), scenes)),
    }
    return {
        "video_id": video_id,
        "folder_id": folder_id,
        "folder_link": f"https://drive.google.com/drive/folders/{folder_id}",
        "folders": {"images": images_id, "final_video": final_id},
        "docs": docs,
    }


async def _sync_video_workspace_unlocked(
    video_id: str,
    tenant_id: Optional[str] = None,
    *,
    client_factory: Optional[Callable[[], Any]] = None,
) -> dict:
    """Create or refresh one video's canonical workspace, without duplicates."""
    params: list[Any] = [video_id]
    tenant_clause = ""
    if tenant_id:
        params.append(tenant_id)
        tenant_clause = " AND tenant_id = $2"
    video = await fetch_one(
        "SELECT id, tenant_id, video_title, research_payload, script, final_video_url, drive_folder_id "
        f"FROM videos WHERE id = $1{tenant_clause} AND deleted_at IS NULL",
        *params,
    )
    if not video:
        raise LookupError("Video not found")
    owner = str(video.get("tenant_id") or tenant_id or "")
    scenes = await fetch_all(
        "SELECT scene, scene_text FROM scripts WHERE video_id = $1 AND tenant_id = $2 "
        "ORDER BY scene NULLS FIRST, created_at",
        video_id, owner,
    )
    if client_factory is None:
        from storage import _get_google_client
        client_factory = _get_google_client
    result = await asyncio.to_thread(_sync_drive, client_factory(), video, scenes)
    await execute(
        "UPDATE videos SET drive_folder_id = $1, drive_folder_link = $2, updated_at = now() "
        "WHERE id = $3 AND tenant_id = $4",
        result["folder_id"], result["folder_link"], video_id, owner,
    )
    return result


async def sync_video_workspace(
    video_id: str,
    tenant_id: Optional[str] = None,
    *,
    client_factory: Optional[Callable[[], Any]] = None,
) -> dict:
    """Serialize first syncs per video, then create or refresh the workspace.

    The PostgreSQL advisory lock closes the race where two workers both search
    Drive before either has persisted ``drive_folder_id``. Tests that inject a
    fake client call the unlocked implementation directly.
    """
    if client_factory is not None:
        return await _sync_video_workspace_unlocked(
            video_id, tenant_id, client_factory=client_factory
        )

    pool = await get_pool()
    async with pool.acquire() as conn:
        await conn.execute(
            "SELECT pg_advisory_lock(hashtextextended($1, 0))", str(video_id)
        )
        try:
            return await _sync_video_workspace_unlocked(video_id, tenant_id)
        finally:
            await conn.execute(
                "SELECT pg_advisory_unlock(hashtextextended($1, 0))", str(video_id)
            )


async def sync_video_workspace_fail_soft(video_id: str, tenant_id: Optional[str] = None) -> Optional[dict]:
    """Lifecycle-hook wrapper: Drive outages never fail video/pipeline work."""
    try:
        return await sync_video_workspace(video_id, tenant_id)
    except Exception as exc:  # noqa: BLE001 - intentionally fail-soft boundary
        logger.warning("Drive workspace sync failed for video %s: %s", video_id, str(exc)[:240])
        return None
