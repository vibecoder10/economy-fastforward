"""Upload-path quota wiring without network, provider, or database calls."""
import asyncio
import os
import sys
import types

from PIL import Image

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..")))

import youtube_publish  # noqa: E402


VIDEO = "video-1"
TENANT = "tenant-1"


def _install(monkeypatch, *, thumbnail_succeeded: bool, quota_ok: bool = True):
    calls = {"reservations": [], "releases": [], "downloads": 0, "uploads": 0}

    async def fake_fetch_one(query, *args):
        if "FROM videos WHERE id" in query:
            return {
                "video_title": "Quota Test",
                "final_video_url": "https://storage/video.mp4",
                "thumbnail_url": "https://storage/thumb.jpg",
                "seo_description": "Description",
                "seo_tags": "one,two",
                "seo_category_id": "27",
            }
        if "FROM channel_profiles" in query:
            return {
                "youtube_refresh_token": "token",
                "youtube_channel_name": "Channel",
            }
        raise AssertionError(query)

    reservation = {
        "tracked": True,
        "day": None,
        "general_units": 50,
        "video_uploads": 1,
        "released": False,
    }

    async def fake_reserve(*, has_thumbnail):
        calls["reservations"].append(has_thumbnail)
        return quota_ok, {
            "exhausted_bucket": "video_uploads",
            "video_uploads": {"used": 100, "limit": 100},
            "reservation": reservation,
        }

    async def fake_release(reservation_arg, *, release_upload, release_general):
        calls["releases"].append((reservation_arg, release_upload, release_general))

    async def fake_download(url, dest):
        calls["downloads"] += 1
        if "thumb" in url:
            Image.new("RGB", (1280, 720), "blue").save(dest, format="PNG")

    def fake_upload(*args):
        calls["uploads"] += 1
        return {
            "youtube_video_id": "yt123",
            "youtube_url": "https://youtube.test/watch?v=yt123",
            "thumbnail_succeeded": thumbnail_succeeded,
        }

    async def fake_execute(*args):
        return "UPDATE 1"

    monkeypatch.setattr(youtube_publish, "fetch_one", fake_fetch_one)
    monkeypatch.setattr(youtube_publish, "reserve_upload", fake_reserve)
    monkeypatch.setattr(youtube_publish, "reserve_thumbnail", fake_reserve)
    monkeypatch.setattr(youtube_publish, "release_upload_reservation", fake_release)
    monkeypatch.setattr(youtube_publish, "_download_to_local", fake_download)
    monkeypatch.setattr(youtube_publish, "_do_youtube_upload", fake_upload)
    monkeypatch.setattr(youtube_publish, "execute", fake_execute)
    return calls


def test_upload_preflight_reserves_one_upload_and_thumbnail_general_units(monkeypatch):
    calls = _install(monkeypatch, thumbnail_succeeded=True)
    result = asyncio.run(youtube_publish.upload_video_to_youtube(VIDEO, TENANT))
    assert calls["reservations"] == [True]
    assert calls["releases"][0][1:] == (False, False)
    assert result["youtube_video_id"] == "yt123"


def test_failed_thumbnail_releases_only_thumbnail_units(monkeypatch):
    calls = _install(monkeypatch, thumbnail_succeeded=False)
    asyncio.run(youtube_publish.upload_video_to_youtube(VIDEO, TENANT))
    assert calls["releases"][0][1:] == (False, True)
    assert calls["uploads"] == 1


def test_quota_refusal_happens_before_download_or_upload(monkeypatch):
    calls = _install(monkeypatch, thumbnail_succeeded=False, quota_ok=False)
    result = asyncio.run(youtube_publish.upload_video_to_youtube(VIDEO, TENANT))
    assert result["quota_exceeded"] is True
    assert "video upload quota" in result["error"]
    assert calls["downloads"] == 0
    assert calls["uploads"] == 0
    assert calls["releases"] == []


def test_result_seam_reports_thumbnail_success_and_failure():
    succeeded = youtube_publish._youtube_upload_result("yt1", True)
    failed = youtube_publish._youtube_upload_result("yt2", False)
    assert succeeded["thumbnail_succeeded"] is True
    assert failed["thumbnail_succeeded"] is False
    assert succeeded["youtube_url"].endswith("yt1")


def test_do_youtube_upload_propagates_thumbnail_result_via_pure_seam(monkeypatch):
    outcomes = iter((True, False))

    def fake_impl(*args):
        return youtube_publish._youtube_upload_result("yt-direct", next(outcomes))

    monkeypatch.setattr(youtube_publish, "_do_youtube_upload_impl", fake_impl)
    args = ("token", "video.mp4", "thumb.jpg", "title", "description", [], "27",
            "unlisted", False)
    assert youtube_publish._do_youtube_upload(*args)["thumbnail_succeeded"] is True
    assert youtube_publish._do_youtube_upload(*args)["thumbnail_succeeded"] is False


def test_sdk_adapter_reports_real_thumbnail_set_success_and_failure(
    monkeypatch, tmp_path
):
    """Execute the real adapter with a fully mocked Google SDK.

    This fails if the adapter stops assigning thumbnail_succeeded=True after
    thumbnails().set(...).execute() succeeds.
    """
    thumbnail = tmp_path / "thumb.jpg"
    thumbnail.write_bytes(b"fake-jpeg")

    credential_args = []

    class FakeCredentials:
        def __init__(self, **kwargs):
            credential_args.append(kwargs)

        def refresh(self, request):
            pass

    class FakeRequest:
        pass

    class FakeMedia:
        def __init__(self, *args, **kwargs):
            pass

    class FakeInsert:
        def next_chunk(self):
            return None, {"id": "yt-sdk"}

    class FakeVideos:
        def insert(self, **kwargs):
            return FakeInsert()

    class FakeThumbnailSet:
        def __init__(self, should_fail):
            self.should_fail = should_fail

        def execute(self):
            if self.should_fail:
                raise RuntimeError("thumbnail rejected")
            return {"ok": True}

    class FakeThumbnails:
        def __init__(self, should_fail):
            self.should_fail = should_fail

        def set(self, **kwargs):
            return FakeThumbnailSet(self.should_fail)

    class FakeYouTube:
        def __init__(self, should_fail):
            self.should_fail = should_fail

        def videos(self):
            return FakeVideos()

        def thumbnails(self):
            return FakeThumbnails(self.should_fail)

    credentials_module = types.ModuleType("google.oauth2.credentials")
    credentials_module.Credentials = FakeCredentials
    requests_module = types.ModuleType("google.auth.transport.requests")
    requests_module.Request = FakeRequest
    http_module = types.ModuleType("googleapiclient.http")
    http_module.MediaFileUpload = FakeMedia

    monkeypatch.setitem(sys.modules, "google.oauth2.credentials", credentials_module)
    monkeypatch.setitem(sys.modules, "google.auth.transport.requests", requests_module)
    monkeypatch.setitem(sys.modules, "googleapiclient.http", http_module)
    monkeypatch.setenv("YOUTUBE_OAUTH_CLIENT_ID", "youtube-client")
    monkeypatch.setenv("YOUTUBE_OAUTH_CLIENT_SECRET", "youtube-secret")
    monkeypatch.setenv("GOOGLE_OAUTH_CLIENT_ID", "google-client")
    monkeypatch.setenv("GOOGLE_OAUTH_CLIENT_SECRET", "google-secret")

    def run(should_fail):
        discovery_module = types.ModuleType("googleapiclient.discovery")
        discovery_module.build = lambda *args, **kwargs: FakeYouTube(should_fail)
        monkeypatch.setitem(
            sys.modules, "googleapiclient.discovery", discovery_module
        )
        attempt_state = {"video_insert_attempted": False}
        result = youtube_publish._do_youtube_upload_impl(
            "token",
            "video.mp4",
            str(thumbnail),
            "title",
            "description",
            [],
            "27",
            "unlisted",
            False,
            attempt_state,
        )
        assert attempt_state["video_insert_attempted"] is True
        return result

    assert run(False)["thumbnail_succeeded"] is True
    assert run(True)["thumbnail_succeeded"] is False
    assert {args["client_id"] for args in credential_args} == {"youtube-client"}
    assert {args["client_secret"] for args in credential_args} == {"youtube-secret"}


def test_no_videos_insert_attempt_releases_entire_reservation(monkeypatch):
    calls = _install(monkeypatch, thumbnail_succeeded=False)

    def fail_before_wire(*args):
        raise youtube_publish.YouTubeUploadAttemptError(
            "credential setup failed", video_insert_attempted=False
        )

    monkeypatch.setattr(youtube_publish, "_do_youtube_upload", fail_before_wire)
    try:
        asyncio.run(youtube_publish.upload_video_to_youtube(VIDEO, TENANT))
        assert False, "expected upload failure"
    except youtube_publish.YouTubeUploadAttemptError:
        pass
    assert calls["releases"][0][1:] == (True, True)


def test_attempted_videos_insert_keeps_upload_but_releases_thumbnail(monkeypatch):
    calls = _install(monkeypatch, thumbnail_succeeded=False)

    def fail_after_wire(*args):
        raise youtube_publish.YouTubeUploadAttemptError(
            "YouTube rejected upload", video_insert_attempted=True
        )

    monkeypatch.setattr(youtube_publish, "_do_youtube_upload", fail_after_wire)
    try:
        asyncio.run(youtube_publish.upload_video_to_youtube(VIDEO, TENANT))
        assert False, "expected upload failure"
    except youtube_publish.YouTubeUploadAttemptError:
        pass
    assert calls["releases"][0][1:] == (False, True)


def test_normalize_thumbnail_converts_large_source_to_jpeg_under_youtube_limit(tmp_path):
    source = tmp_path / "source.png"
    destination = tmp_path / "normalized.jpg"
    Image.effect_noise((2400, 1800), 100).save(source, format="PNG")
    assert source.stat().st_size > youtube_publish._YOUTUBE_THUMBNAIL_MAX_BYTES

    youtube_publish._normalize_thumbnail(str(source), str(destination))

    assert destination.stat().st_size < youtube_publish._YOUTUBE_THUMBNAIL_MAX_BYTES
    with Image.open(destination) as normalized:
        assert normalized.format == "JPEG"
        assert normalized.mode == "RGB"


def test_thumbnail_set_retries_transient_failures_then_succeeds(monkeypatch, tmp_path):
    thumbnail = tmp_path / "thumb.jpg"
    thumbnail.write_bytes(b"jpeg")
    calls = []

    class TransientError(RuntimeError):
        status_code = 503

    class Request:
        def execute(self):
            calls.append("execute")
            if len(calls) < 3:
                raise TransientError("temporarily unavailable")
            return {"ok": True}

    class Thumbnails:
        def set(self, **kwargs):
            return Request()

    class YouTube:
        def thumbnails(self):
            return Thumbnails()

    sleeps = []
    result = youtube_publish._set_youtube_thumbnail(
        YouTube(), "yt-existing", str(thumbnail), lambda *a, **k: object(),
        sleep=lambda seconds: sleeps.append(seconds),
    )

    assert result == {"thumbnail_succeeded": True, "thumbnail_error": None}
    assert calls == ["execute", "execute", "execute"]
    assert sleeps == [0.25, 0.5]


def test_thumbnail_set_returns_actionable_error_after_permanent_failure(tmp_path):
    thumbnail = tmp_path / "thumb.jpg"
    thumbnail.write_bytes(b"jpeg")

    class Request:
        def execute(self):
            raise RuntimeError("image exceeds provider limit")

    class Thumbnails:
        def set(self, **kwargs):
            return Request()

    class YouTube:
        def thumbnails(self):
            return Thumbnails()

    result = youtube_publish._set_youtube_thumbnail(
        YouTube(), "yt-existing", str(thumbnail), lambda *a, **k: object(),
        sleep=lambda _seconds: None,
    )

    assert result["thumbnail_succeeded"] is False
    assert "image exceeds provider limit" in result["thumbnail_error"]
    assert "YouTube video yt-existing" in result["thumbnail_error"]


def test_thumbnail_download_failure_persists_video_id_as_partial(monkeypatch):
    calls = {"execute": [], "releases": []}

    async def fake_fetch_one(query, *args):
        if "FROM videos WHERE id" in query:
            return {
                "video_title": "Partial Test",
                "final_video_url": "https://storage/video.mp4",
                "thumbnail_url": "https://storage/thumb.png",
                "seo_description": "Description",
                "seo_tags": "one,two",
                "seo_category_id": "27",
                "youtube_video_id": None,
                "youtube_url": None,
            }
        return {"youtube_refresh_token": "token", "youtube_channel_name": "Channel"}

    async def fake_reserve(*, has_thumbnail):
        return True, {"reservation": {"tracked": False, "general_units": 50}}

    async def fake_release(reservation, *, release_upload, release_general):
        calls["releases"].append((release_upload, release_general))

    async def fake_download(url, dest):
        if "thumb" in url:
            raise RuntimeError("thumbnail source denied")

    def fake_upload(*args):
        assert args[2] is None
        return youtube_publish._youtube_upload_result("yt-partial", False)

    async def fake_execute(query, *args):
        calls["execute"].append((query, args))

    monkeypatch.setattr(youtube_publish, "fetch_one", fake_fetch_one)
    monkeypatch.setattr(youtube_publish, "reserve_upload", fake_reserve)
    monkeypatch.setattr(youtube_publish, "release_upload_reservation", fake_release)
    monkeypatch.setattr(youtube_publish, "_download_to_local", fake_download)
    monkeypatch.setattr(youtube_publish, "_do_youtube_upload", fake_upload)
    monkeypatch.setattr(youtube_publish, "execute", fake_execute)

    result = asyncio.run(youtube_publish.upload_video_to_youtube(VIDEO, TENANT))

    assert result["youtube_video_id"] == "yt-partial"
    assert result["thumbnail_succeeded"] is False
    assert "thumbnail source denied" in result["partial_error"]
    update_query, update_args = calls["execute"][0]
    assert "upload_status=$3" in update_query
    assert update_args[2] == "thumbnail_failed"
    assert calls["releases"] == [(False, True)]


def test_existing_video_retries_thumbnail_without_video_insert(monkeypatch, tmp_path):
    calls = {"download_urls": [], "thumbnail_ids": [], "releases": [], "execute": []}

    async def fake_fetch_one(query, *args):
        if "FROM videos WHERE id" in query:
            return {
                "video_title": "Retry Test",
                "final_video_url": "https://storage/video.mp4",
                "thumbnail_url": "https://storage/thumb.png",
                "seo_description": "Description",
                "seo_tags": "one,two",
                "seo_category_id": "27",
                "youtube_video_id": "yt-existing",
                "youtube_url": "https://youtube.test/watch?v=yt-existing",
            }
        return {"youtube_refresh_token": "token", "youtube_channel_name": "Channel"}

    async def fake_reserve(*, has_thumbnail):
        return True, {"reservation": {"tracked": False, "general_units": 50}}

    async def fake_reserve_thumbnail():
        return True, {"reservation": {"tracked": False, "general_units": 50}}

    async def fake_release(reservation, *, release_upload, release_general):
        calls["releases"].append((release_upload, release_general))

    async def fake_download(url, dest):
        calls["download_urls"].append(url)
        Image.new("RGB", (1280, 720), "red").save(dest, format="PNG")

    def fake_thumbnail(refresh_token, youtube_video_id, thumb_path):
        calls["thumbnail_ids"].append(youtube_video_id)
        return {"thumbnail_succeeded": True, "thumbnail_error": None}

    def forbidden_upload(*args):
        raise AssertionError("existing YouTube video must not call videos.insert")

    async def fake_execute(query, *args):
        calls["execute"].append((query, args))

    monkeypatch.setattr(youtube_publish, "fetch_one", fake_fetch_one)
    monkeypatch.setattr(youtube_publish, "reserve_upload", fake_reserve)
    monkeypatch.setattr(youtube_publish, "reserve_thumbnail", fake_reserve_thumbnail)
    monkeypatch.setattr(youtube_publish, "release_upload_reservation", fake_release)
    monkeypatch.setattr(youtube_publish, "_download_to_local", fake_download)
    monkeypatch.setattr(youtube_publish, "_do_youtube_thumbnail", fake_thumbnail)
    monkeypatch.setattr(youtube_publish, "_do_youtube_upload", forbidden_upload)
    monkeypatch.setattr(youtube_publish, "execute", fake_execute)

    result = asyncio.run(youtube_publish.upload_video_to_youtube(VIDEO, TENANT))

    assert result["thumbnail_succeeded"] is True
    assert calls["download_urls"] == ["https://storage/thumb.png"]
    assert calls["thumbnail_ids"] == ["yt-existing"]
    assert calls["releases"] == [(False, False)]
    assert any(args[2] == "uploaded" for _, args in calls["execute"])


def test_force_new_upload_uses_videos_insert_even_when_existing_id_is_saved(monkeypatch):
    calls = {"upload": 0, "thumbnail": 0}

    async def fake_fetch_one(query, *args):
        if "FROM videos WHERE id" in query:
            return {
                "video_title": "Force Test",
                "final_video_url": "https://storage/video.mp4",
                "thumbnail_url": None,
                "seo_description": "Description",
                "seo_tags": "one,two",
                "seo_category_id": "27",
                "youtube_video_id": "yt-existing",
                "youtube_url": "https://youtube.test/watch?v=yt-existing",
            }
        return {"youtube_refresh_token": "token", "youtube_channel_name": "Channel"}

    async def fake_reserve(*, has_thumbnail):
        return True, {"reservation": {"tracked": False, "general_units": 0}}

    async def fake_release(*args, **kwargs):
        return None

    async def fake_download(url, dest):
        return None

    def fake_upload(*args):
        calls["upload"] += 1
        return youtube_publish._youtube_upload_result("yt-new", False)

    def fake_thumbnail(*args):
        calls["thumbnail"] += 1
        return {"thumbnail_succeeded": True, "thumbnail_error": None}

    async def fake_execute(*args):
        return None

    monkeypatch.setattr(youtube_publish, "fetch_one", fake_fetch_one)
    monkeypatch.setattr(youtube_publish, "reserve_upload", fake_reserve)
    monkeypatch.setattr(youtube_publish, "release_upload_reservation", fake_release)
    monkeypatch.setattr(youtube_publish, "_download_to_local", fake_download)
    monkeypatch.setattr(youtube_publish, "_do_youtube_upload", fake_upload)
    monkeypatch.setattr(youtube_publish, "_do_youtube_thumbnail", fake_thumbnail)
    monkeypatch.setattr(youtube_publish, "execute", fake_execute)

    result = asyncio.run(youtube_publish.upload_video_to_youtube(
        VIDEO, TENANT, force_new_upload=True
    ))

    assert result["youtube_video_id"] == "yt-new"
    assert calls == {"upload": 1, "thumbnail": 0}
