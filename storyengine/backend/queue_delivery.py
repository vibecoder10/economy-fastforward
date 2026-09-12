"""Fail-closed delivery of a rendered queue video to one exact YouTube channel."""

from __future__ import annotations

import asyncio
import json
from datetime import datetime, timezone

import httpx

from database import execute, fetch_one
from youtube_oauth_config import get_youtube_oauth_credentials
from youtube_owner_api import fetch_channel_summary, refresh_access_token

PROCESSING_POLL_ATTEMPTS = 31
PROCESSING_POLL_SECONDS = 30


async def _owner_context(refresh_token: str) -> tuple[str, str] | None:
    oauth = get_youtube_oauth_credentials()
    if oauth.missing_env:
        return None
    access_token = await refresh_access_token(
        oauth.client_id, oauth.client_secret, refresh_token
    )
    if not access_token:
        return None
    async with httpx.AsyncClient(timeout=15.0) as client:
        summary = await fetch_channel_summary(client, access_token)
    channel_id = str((summary or {}).get("channel_id") or "").strip()
    return (access_token, channel_id) if channel_id else None


async def _video_readback(access_token: str, youtube_video_id: str) -> dict | None:
    """Read one owner-visible video including its owning channel and privacy."""
    async with httpx.AsyncClient(timeout=15.0) as client:
        response = await client.get(
            "https://www.googleapis.com/youtube/v3/videos",
            params={
                "part": "snippet,status,processingDetails",
                "id": youtube_video_id,
                "maxResults": 1,
            },
            headers={"Authorization": f"Bearer {access_token}"},
        )
    if response.status_code != 200:
        return None
    items = response.json().get("items") or []
    if not items:
        return None
    item = items[0]
    return {
        "youtube_video_id": str(item.get("id") or "").strip(),
        "channel_id": str(item.get("snippet", {}).get("channelId") or "").strip(),
        "privacy": str(item.get("status", {}).get("privacyStatus") or "").strip(),
        "upload_status": item.get("status", {}).get("uploadStatus"),
        "processing_status": item.get("processingDetails", {}).get("processingStatus"),
        "processing_failure": (item.get("processingDetails", {}).get("processingFailureReason")
                               or item.get("status", {}).get("failureReason")
                               or item.get("status", {}).get("rejectionReason")),
    }


async def _save_receipt(video_id: str, tenant_id: str, receipt: dict) -> None:
    await execute(
        "UPDATE videos SET queue_delivery_receipt=$1::jsonb, updated_at=now() "
        "WHERE id=$2 AND tenant_id=$3",
        json.dumps(receipt),
        video_id,
        tenant_id,
    )


async def _upload_unlisted(
    video_id: str, tenant_id: str, expected_channel_id: str
) -> dict:
    # Local import keeps this helper safe to import from actions.py, because
    # youtube_publish itself imports one actions configuration function.
    from youtube_publish import upload_video_to_youtube

    return await upload_video_to_youtube(
        video_id,
        tenant_id,
        privacy="unlisted",
        force_new_upload=False,
        expected_channel_id=expected_channel_id,
    )


async def deliver_queue_video(
    video_id: str, tenant_id: str, expected_channel_id: str
) -> dict:
    """Upload or resume one video and complete only after owner API readback.

    The caller must supply the channel ID snapshotted at title-list intake.
    This function never requests public visibility and never forces a new upload.
    """
    expected_channel_id = str(expected_channel_id or "").strip()
    if not expected_channel_id:
        return {"status": "blocked", "error": "Delivery channel ID is missing."}

    row = await fetch_one(
        "SELECT status, youtube_video_id, youtube_url, upload_status, "
        "queue_delivery_receipt "
        "FROM videos WHERE id=$1 AND tenant_id=$2",
        video_id,
        tenant_id,
    )
    if not row:
        return {"status": "failed", "error": "Video not found."}
    profile = await fetch_one(
        "SELECT youtube_refresh_token, youtube_channel_id FROM channel_profiles "
        "WHERE tenant_id=$1",
        tenant_id,
    )
    refresh_token = str((profile or {}).get("youtube_refresh_token") or "").strip()
    saved_channel_id = str((profile or {}).get("youtube_channel_id") or "").strip()
    if not refresh_token:
        return {"status": "blocked", "error": "No YouTube channel is connected."}
    if saved_channel_id != expected_channel_id:
        return {
            "status": "blocked",
            "error": "Saved YouTube channel does not match the delivery target.",
        }

    try:
        owner = await _owner_context(refresh_token)
    except Exception as exc:
        return {
            "status": "blocked",
            "error": f"Could not verify the YouTube owner: {exc}",
        }
    if not owner:
        return {"status": "blocked", "error": "Could not verify the YouTube owner."}
    access_token, live_channel_id = owner
    if live_channel_id != expected_channel_id:
        return {
            "status": "blocked",
            "error": "Connected YouTube owner does not match the delivery target.",
        }

    youtube_video_id = str(row.get("youtube_video_id") or "").strip()
    # A completed prior upload needs readback only. A saved thumbnail failure is
    # safe to retry because the publisher targets this exact existing ID.
    if not youtube_video_id or row.get("upload_status") != "uploaded":
        try:
            uploaded = await _upload_unlisted(
                video_id, tenant_id, expected_channel_id
            )
        except Exception as exc:
            # The publisher's durable marker determines whether a later call may
            # insert. Report a blocked operation here instead of allowing an
            # orchestration retry to guess that creation is safe.
            attempted = bool(getattr(exc, "video_insert_attempted", False))
            return {
                "status": "blocked" if attempted else "failed",
                "error": str(exc),
            }
        if uploaded.get("error"):
            return {
                "status": "blocked" if uploaded.get("blocked") else "failed",
                "error": uploaded["error"],
                "youtube_video_id": uploaded.get("youtube_video_id"),
            }
        if uploaded.get("partial_error"):
            return {
                "status": "failed",
                "error": uploaded["partial_error"],
                "youtube_video_id": uploaded.get("youtube_video_id"),
            }
        youtube_video_id = str(uploaded.get("youtube_video_id") or "").strip()
        if not youtube_video_id:
            # The publisher normally returns it; reread the immediately-persisted
            # provider identity before deciding the operation is incomplete.
            refreshed = await fetch_one(
                "SELECT youtube_video_id FROM videos WHERE id=$1 AND tenant_id=$2",
                video_id,
                tenant_id,
            )
            youtube_video_id = str(
                (refreshed or {}).get("youtube_video_id") or ""
            ).strip()
    if not youtube_video_id:
        return {"status": "blocked", "error": "YouTube video ID was not saved."}

    # An accepted insert is not a playable delivery. Poll only the saved ID;
    # retries resume this readback and never create another upload.
    for attempt in range(PROCESSING_POLL_ATTEMPTS):
        try:
            observed = await _video_readback(access_token, youtube_video_id)
        except Exception as exc:
            observed = None
            readback_error = str(exc)
        else:
            readback_error = "Owner readback did not confirm the expected unlisted video."
        receipt = {
            "status": "verification_failed",
            "channel_id": expected_channel_id,
            "privacy": "unlisted",
            "youtube_video_id": youtube_video_id,
        }
        if not observed or (
            observed.get("youtube_video_id") != youtube_video_id
            or observed.get("channel_id") != expected_channel_id
            or observed.get("privacy") != "unlisted"
        ):
            receipt["error"] = readback_error
            await _save_receipt(video_id, tenant_id, receipt)
            return {"status": "blocked", "error": readback_error,
                    "youtube_video_id": youtube_video_id}
        processing = observed.get("processing_status")
        upload_status = observed.get("upload_status")
        if processing == "succeeded" and upload_status == "processed":
            break
        receipt.update(processing_status=processing, upload_status=upload_status)
        if processing in {"failed", "terminated"} or upload_status in {"failed", "rejected", "deleted"}:
            reason = observed.get("processing_failure") or processing or upload_status
            receipt.update(status="processing_failed", error=f"YouTube processing did not succeed: {reason}")
            await _save_receipt(video_id, tenant_id, receipt)
            return {"status": "blocked", "error": receipt["error"],
                    "youtube_video_id": youtube_video_id}
        receipt.update(status="processing_pending", error="Waiting for YouTube video processing")
        await _save_receipt(video_id, tenant_id, receipt)
        if attempt + 1 < PROCESSING_POLL_ATTEMPTS:
            await asyncio.sleep(PROCESSING_POLL_SECONDS)
    else:
        return {"status": "pending", "error": "YouTube processing timeout; retry will check the same saved video ID.",
                "youtube_video_id": youtube_video_id}

    receipt = {
        "status": "verified",
        "channel_id": expected_channel_id,
        "privacy": "unlisted",
        "youtube_video_id": youtube_video_id,
        "verified_at": datetime.now(timezone.utc).isoformat(),
        "upload_status": "processed",
        "processing_status": "succeeded",
    }
    prior_status = str(row.get("status") or "").strip()
    final_status = prior_status if prior_status in {"published", "done"} else "uploaded_draft"
    await execute(
        "UPDATE videos SET queue_delivery_receipt=$1::jsonb, "
        "upload_status='uploaded', status=$2, updated_at=now() "
        "WHERE id=$3 AND tenant_id=$4",
        json.dumps(receipt),
        final_status,
        video_id,
        tenant_id,
    )
    return {
        "status": "completed",
        "youtube_video_id": youtube_video_id,
        "youtube_url": row.get("youtube_url")
        or f"https://www.youtube.com/watch?v={youtube_video_id}",
        "channel_id": expected_channel_id,
        "privacy": "unlisted",
        "receipt": receipt,
    }
