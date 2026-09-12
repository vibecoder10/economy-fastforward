"""Queue YouTube delivery safety contracts; no provider or database calls."""

import asyncio
import json
import os
import sys
from unittest.mock import AsyncMock
import pytest

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..")))

import queue_delivery  # noqa: E402
import youtube_publish  # noqa: E402


VIDEO = "video-1"
TENANT = "tenant-1"
CHANNEL = "UC_expected"


def test_exact_saved_channel_mismatch_blocks_before_upload(monkeypatch):
    async def fetch_one(query, *args):
        if "FROM videos" in query:
            return {"status": "rendered", "youtube_video_id": None, "youtube_url": None,
                    "upload_status": None, "queue_delivery_receipt": None}
        return {"youtube_refresh_token": "refresh", "youtube_channel_id": "UC_wrong"}

    upload = AsyncMock()
    monkeypatch.setattr(queue_delivery, "fetch_one", fetch_one)
    monkeypatch.setattr(queue_delivery, "_upload_unlisted", upload)

    result = asyncio.run(queue_delivery.deliver_queue_video(VIDEO, TENANT, CHANNEL))

    assert result["status"] == "blocked"
    upload.assert_not_awaited()


def test_saved_video_is_read_back_without_another_upload(monkeypatch):
    async def fetch_one(query, *args):
        if "FROM videos" in query:
            return {"status": "uploaded_draft", "youtube_video_id": "yt-existing", "youtube_url": None,
                    "upload_status": "uploaded", "queue_delivery_receipt": None}
        return {"youtube_refresh_token": "refresh", "youtube_channel_id": CHANNEL}

    execute = AsyncMock(return_value="UPDATE 1")
    upload = AsyncMock()
    monkeypatch.setattr(queue_delivery, "fetch_one", fetch_one)
    monkeypatch.setattr(queue_delivery, "execute", execute)
    monkeypatch.setattr(
        queue_delivery, "_owner_context", AsyncMock(return_value=("access", CHANNEL))
    )
    monkeypatch.setattr(
        queue_delivery,
        "_video_readback",
        AsyncMock(return_value={
            "youtube_video_id": "yt-existing",
            "channel_id": CHANNEL,
            "privacy": "unlisted",
        }),
    )
    monkeypatch.setattr(queue_delivery, "_upload_unlisted", upload)

    result = asyncio.run(queue_delivery.deliver_queue_video(VIDEO, TENANT, CHANNEL))

    assert result["status"] == "completed"
    assert result["privacy"] == "unlisted"
    upload.assert_not_awaited()
    receipt = json.loads(execute.await_args.args[1])
    assert receipt["status"] == "verified"
    assert receipt["channel_id"] == CHANNEL


@pytest.mark.parametrize("saved_status", ["video_created", "thumbnail_failed"])
def test_interrupted_thumbnail_is_resumed_before_delivery_completes(monkeypatch, saved_status):
    async def fetch_one(query, *args):
        if "FROM videos" in query:
            return {"status": "uploaded_draft", "youtube_video_id": "yt-existing", "upload_status": saved_status}
        return {"youtube_refresh_token": "refresh", "youtube_channel_id": CHANNEL}
    upload = AsyncMock(return_value={"youtube_video_id": "yt-existing", "partial_error": "Thumbnail still missing"})
    readback = AsyncMock()
    monkeypatch.setattr(queue_delivery, "fetch_one", fetch_one)
    monkeypatch.setattr(queue_delivery, "_owner_context", AsyncMock(return_value=("access", CHANNEL)))
    monkeypatch.setattr(queue_delivery, "_upload_unlisted", upload)
    monkeypatch.setattr(queue_delivery, "_video_readback", readback)
    result = asyncio.run(queue_delivery.deliver_queue_video(VIDEO, TENANT, CHANNEL))
    assert result["status"] == "failed"
    upload.assert_awaited_once_with(VIDEO, TENANT, CHANNEL)
    readback.assert_not_awaited()


def test_missing_authoritative_readback_never_completes(monkeypatch):
    async def fetch_one(query, *args):
        if "FROM videos" in query:
            return {"status": "uploaded_draft", "youtube_video_id": "yt-existing", "youtube_url": None,
                    "upload_status": "uploaded", "queue_delivery_receipt": None}
        return {"youtube_refresh_token": "refresh", "youtube_channel_id": CHANNEL}

    execute = AsyncMock(return_value="UPDATE 1")
    monkeypatch.setattr(queue_delivery, "fetch_one", fetch_one)
    monkeypatch.setattr(queue_delivery, "execute", execute)
    monkeypatch.setattr(
        queue_delivery, "_owner_context", AsyncMock(return_value=("access", CHANNEL))
    )
    monkeypatch.setattr(queue_delivery, "_video_readback", AsyncMock(return_value=None))

    result = asyncio.run(queue_delivery.deliver_queue_video(VIDEO, TENANT, CHANNEL))

    assert result["status"] == "blocked"
    receipt = json.loads(execute.await_args.args[1])
    assert receipt["status"] == "verification_failed"


def test_uncertain_insert_is_marked_and_never_repeated(monkeypatch):
    state = {"upload_status": None, "insert_calls": 0}

    async def fetch_one(query, *args):
        if "FROM videos WHERE id" in query:
            return {
                "video_title": "Safety Test",
                "final_video_url": "https://storage/video.mp4",
                "thumbnail_url": None,
                "seo_description": "Description",
                "seo_tags": "one,two",
                "seo_category_id": "27",
                "youtube_video_id": None,
                "youtube_url": None,
                "upload_status": state["upload_status"],
                "queue_delivery_receipt": None,
            }
        return {
            "youtube_refresh_token": "refresh",
            "youtube_channel_name": "Channel",
            "youtube_channel_id": CHANNEL,
        }

    async def execute(query, *args):
        if "upload_status='insert_in_flight'" in query:
            state["upload_status"] = "insert_in_flight"
        if "queue_delivery_receipt=$2::jsonb" in query:
            state["upload_status"] = args[0]
        return "UPDATE 1"

    def uncertain(*args):
        state["insert_calls"] += 1
        raise youtube_publish.YouTubeUploadAttemptError(
            "connection lost after insert", video_insert_attempted=True
        )

    monkeypatch.setattr(youtube_publish, "fetch_one", fetch_one)
    monkeypatch.setattr(youtube_publish, "execute", execute)
    monkeypatch.setattr(
        youtube_publish, "_verify_expected_owner_channel",
        AsyncMock(return_value={"channel_id": CHANNEL}),
    )
    monkeypatch.setattr(
        youtube_publish, "reserve_upload",
        AsyncMock(return_value=(True, {"reservation": {"tracked": False}})),
    )
    monkeypatch.setattr(youtube_publish, "release_upload_reservation", AsyncMock())
    monkeypatch.setattr(youtube_publish, "_download_to_local", AsyncMock())
    monkeypatch.setattr(youtube_publish, "_do_youtube_video_insert", uncertain)

    try:
        asyncio.run(youtube_publish.upload_video_to_youtube(
            VIDEO, TENANT, privacy="unlisted", expected_channel_id=CHANNEL
        ))
        assert False, "expected uncertain insert failure"
    except youtube_publish.YouTubeUploadAttemptError:
        pass
    second = asyncio.run(youtube_publish.upload_video_to_youtube(
        VIDEO, TENANT, privacy="unlisted", expected_channel_id=CHANNEL
    ))

    assert state["insert_calls"] == 1
    assert state["upload_status"] == "insert_uncertain"
    assert second["blocked"] is True


def test_automatic_delivery_rejects_non_unlisted_before_lookup(monkeypatch):
    lookup = AsyncMock()
    monkeypatch.setattr(youtube_publish, "fetch_one", lookup)

    result = asyncio.run(youtube_publish.upload_video_to_youtube(
        VIDEO, TENANT, privacy="public", expected_channel_id=CHANNEL
    ))

    assert result["blocked"] is True
    lookup.assert_not_awaited()


def test_saved_id_automatic_resume_never_calls_video_insert(monkeypatch):
    async def fetch_one(query, *args):
        if "FROM videos WHERE id" in query:
            return {
                "video_title": "Resume Test",
                "final_video_url": None,
                "thumbnail_url": None,
                "seo_description": "Description",
                "seo_tags": "one,two",
                "seo_category_id": "27",
                "youtube_video_id": "yt-existing",
                "youtube_url": "https://www.youtube.com/watch?v=yt-existing",
                "upload_status": "thumbnail_failed",
                "queue_delivery_receipt": None,
            }
        return {
            "youtube_refresh_token": "refresh",
            "youtube_channel_name": "Channel",
            "youtube_channel_id": CHANNEL,
        }

    def forbidden_insert(*args):
        raise AssertionError("saved provider ID must prevent videos.insert")

    monkeypatch.setattr(youtube_publish, "fetch_one", fetch_one)
    monkeypatch.setattr(youtube_publish, "execute", AsyncMock(return_value="UPDATE 1"))
    monkeypatch.setattr(
        youtube_publish, "_verify_expected_owner_channel",
        AsyncMock(return_value={"channel_id": CHANNEL}),
    )
    monkeypatch.setattr(
        youtube_publish, "reserve_thumbnail",
        AsyncMock(return_value=(True, {"reservation": {"tracked": False}})),
    )
    monkeypatch.setattr(youtube_publish, "release_upload_reservation", AsyncMock())
    monkeypatch.setattr(youtube_publish, "_do_youtube_video_insert", forbidden_insert)

    result = asyncio.run(youtube_publish.upload_video_to_youtube(
        VIDEO, TENANT, privacy="unlisted", expected_channel_id=CHANNEL
    ))

    assert result["youtube_video_id"] == "yt-existing"
