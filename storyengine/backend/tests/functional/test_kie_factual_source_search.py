import asyncio
import json
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

import httpx
import pytest

import factual_source_search as search
import pipeline_executor as pe
import source_discovery_journal as journal_module
from factual_machine_research import factual_package_contract_warnings


MACHINE = "General Dynamics FB-111A Aardvark"


class _MemoryJournal:
    def __init__(self):
        self.state = {}
        self.snapshots = []

    async def checkpoint(self, state):
        self.state.clear()
        self.state.update(state)
        self.snapshots.append(dict(state))
        return True


@pytest.fixture(autouse=True)
def durable_source_context(monkeypatch):
    async def open_journal(*_args):
        return _MemoryJournal()

    async def not_cancelled(*_args):
        return False

    monkeypatch.setattr(journal_module.SourceDiscoveryJournal, "open", open_journal)
    monkeypatch.setattr("cancel_registry.is_cancel_requested", not_cancelled)


def _with_durable_video(executor, machine):
    executor._get_video = AsyncMock(return_value={
        "render_mode": "static_docu", "max_spend": 10, "total_cost": 0,
        "research_payload": {"documentary_style": "dvsu", "unit_roster": [machine]},
    })
    return executor


def response(rows=None, **extra):
    return httpx.Response(200, json={
        "id": "search-123", "credits_consumed": 0.32,
        "choices": [{"message": {"content": json.dumps(rows if rows is not None else [
            {"title": "Museum aircraft", "exact_source_url": "https://www.sacmuseum.org/aircraft/fb-111a"},
        ])}}], **extra,
    })


@pytest.mark.parametrize("url", [
    "http://127.0.0.1/admin", "http://169.254.169.254/latest", "http://localhost/a",
    "https://user:pass@example.com/a", "file:///etc/passwd", "https://host.internal/a",
    "https://example.com:8001/a", "https://grokipedia.com/page/FB111",
])
def test_private_or_non_source_urls_are_rejected(url):
    assert search.public_source_url(url) is None


def test_redirect_host_resolving_to_private_address_is_rejected():
    async def run():
        loop = asyncio.get_running_loop()
        with patch.object(loop, "getaddrinfo", AsyncMock(return_value=[(2, 1, 6, "", ("10.0.0.1", 80))])):
            with pytest.raises(ValueError, match="public address"):
                await search.guard_public_request(httpx.Request("GET", "https://public-looking.example/a"))
    asyncio.run(run())


def test_application_error_inside_http_200_is_not_success():
    client = SimpleNamespace(post=AsyncMock(return_value=httpx.Response(200, json={"code": 500, "msg": "Network error"})))
    with pytest.raises(search.SourceDiscoveryError, match="temporarily unavailable"):
        asyncio.run(search.discover_sources(client, "test-key", "Every bomber", MACHINE))
    assert client.post.await_count == 1


def test_model_prose_is_never_returned_as_raw_evidence():
    client = SimpleNamespace(post=AsyncMock(return_value=response([
        {"title": "Museum", "exact_source_url": "https://museum.example/a", "raw_content": "Invented evidence"},
        {"title": "duplicate", "exact_source_url": "https://museum.example/a"},
        {"title": "private", "exact_source_url": "http://127.0.0.1"},
    ])))
    leads, receipt = asyncio.run(search.discover_sources(client, "test-key", "Every bomber", MACHINE))
    assert len(leads) == 1 and "raw_content" not in leads[0]
    assert receipt["request_id"] == "search-123" and receipt["credits_consumed"] == 0.32
    assert client.post.call_args.kwargs["json"]["tools"][0]["function"]["name"] == "web_search"


@pytest.mark.parametrize("text,passes", [
    ("The FB-111A was a strategic bomber operated by Strategic Air Command.", True),
    ("The F-111F aircraft flew tactical strike missions.", False),
])
def test_real_gather_routes_factual_research_to_kie_and_only_copies_fetched_text(text, passes):
    executor = object.__new__(pe.PipelineExecutor)
    executor.tenant_id = "tenant-1"
    _with_durable_video(executor, MACHINE)
    executor._fetch_source_text = AsyncMock(return_value=text)
    executor._fetch_source_fallback_text = AsyncMock(return_value=("", ""))
    with patch.object(pe, "get_secret", AsyncMock(return_value="test-key")) as secret, \
         patch.object(httpx.AsyncClient, "post", AsyncMock(return_value=response())) as post:
        package = asyncio.run(executor._gather_verified_machine_source_package(
            "Every US Strategic Bomber", MACHINE, {"machine_script_contract": "factual_100_v1"}, video_id="video",
        ))
    secret.assert_awaited_once_with("kie_ai_api_key", "tenant-1")
    assert post.await_count == (1 if passes else 2)
    assert post.call_args.args[0] == search.ENDPOINT
    assert (not factual_package_contract_warnings(MACHINE, package)) is passes
    assert package["source_discovery"]["credits_consumed"] == 0.32
    assert len(package["source_discovery_requests"]) == (1 if passes else 2)
    if passes:
        assert package["candidate_excerpts"][0]["text"] == text
        assert package["candidate_excerpts"][0]["source_capture_method"] == "fetched_page"


def test_factual_route_without_kie_key_does_not_spend_on_tavily():
    executor = object.__new__(pe.PipelineExecutor)
    executor.tenant_id = "tenant-1"
    _with_durable_video(executor, "SS-212 through SS-284 Gato class")
    with patch.object(pe, "get_secret", AsyncMock(return_value=None)) as secret:
        with pytest.raises(search.SourceDiscoveryError, match="Missing Kie"):
            asyncio.run(executor._gather_verified_machine_source_package(
                "Every bomber", MACHINE, {"machine_script_contract": "factual_100_v1"},
            ))
    secret.assert_awaited_once_with("kie_ai_api_key", "tenant-1")


def test_factual_zero_exact_first_wave_gets_one_alternate_kie_wave():
    executor = object.__new__(pe.PipelineExecutor)
    executor.tenant_id = "tenant-1"
    _with_durable_video(executor, "SS-212 through SS-284 Gato class")

    async def fetched(_client, url):
        if url.endswith("alternate"):
            return "The Gato-class submarine served in the Pacific during the Second World War."
        return "An unrelated Balao-class submarine is not evidence for Gato."

    first = response([{"title": "wrong", "exact_source_url": "https://museum.example/first"}])
    second = response([{"title": "right", "exact_source_url": "https://archive.example/alternate"}])
    with patch.object(pe, "get_secret", AsyncMock(return_value="test-key")), \
         patch.object(httpx.AsyncClient, "post", AsyncMock(side_effect=[first, second])) as post:
        executor._fetch_source_text = fetched
        executor._fetch_source_fallback_text = AsyncMock(return_value=("", ""))
        package = asyncio.run(executor._gather_verified_machine_source_package(
            "Every US Submarine Class Ever Built", "SS-212 through SS-284 Gato class",
            {"machine_script_contract": "factual_100_v1"}, video_id="video",
        ))

    assert post.await_count == 2
    assert len(package["source_discovery_requests"]) == 2
    assert [row["url"] for row in package["sources"]] == ["https://archive.example/alternate"]
    assert package["candidate_excerpts"]


def test_factual_route_uses_verified_archive_fallback_when_direct_page_fails():
    executor = object.__new__(pe.PipelineExecutor)
    executor.tenant_id = "tenant-1"
    _with_durable_video(executor, MACHINE)
    text = "The FB-111A was a strategic bomber operated by Strategic Air Command."
    capture = "wayback:https://web.archive.org/web/20250101000000/https://www.sacmuseum.org/aircraft/fb-111a"
    executor._fetch_source_text = AsyncMock(return_value="")
    executor._fetch_source_fallback_text = AsyncMock(return_value=(text, capture))
    with patch.object(pe, "get_secret", AsyncMock(return_value="test-key")), \
         patch.object(httpx.AsyncClient, "post", AsyncMock(return_value=response())) as post:
        package = asyncio.run(executor._gather_verified_machine_source_package(
            "Every US Strategic Bomber", MACHINE, {"machine_script_contract": "factual_100_v1"}, video_id="video",
        ))
    assert post.await_count == 1
    executor._fetch_source_fallback_text.assert_awaited_once()
    assert package["candidate_excerpts"][0]["text"] == text
    assert package["candidate_excerpts"][0]["source_capture_method"] == capture


def test_captured_holland_html_survives_fetch_and_package_assembly():
    from pathlib import Path
    raw_html = (Path(__file__).parents[1] / "fixtures/holland-source-section.html").read_text()
    url = "https://navalunderseamuseum.org/undersea-pioneers2/"
    executor = object.__new__(pe.PipelineExecutor)
    executor.tenant_id = "tenant-1"
    _with_durable_video(executor, "SS-1 USS Holland")
    executor._fetch_source_fallback_text = AsyncMock(side_effect=AssertionError("direct source is usable"))
    with patch.object(pe, "get_secret", AsyncMock(return_value="test-key")), \
         patch.object(httpx.AsyncClient, "post", AsyncMock(return_value=response([
             {"title": "Undersea pioneers", "exact_source_url": url}
         ]))) as post, \
         patch.object(httpx.AsyncClient, "get", AsyncMock(return_value=httpx.Response(
             200, text=raw_html, headers={"content-type": "text/html"}
         ))):
        package = asyncio.run(executor._gather_verified_machine_source_package(
            "Every US Submarine Class Ever Built", "SS-1 USS Holland",
            {"machine_script_contract": "factual_100_v1"}, video_id="video",
        ))
    assert post.await_count == 1
    excerpts = package["candidate_excerpts"]
    assert "as a training submarine" in excerpts[0]["text"]
    assert excerpts[0]["source_url"] == url
    assert excerpts[0]["source_capture_method"] == "fetched_page"
    assert pe._verified_source_candidate_traceable(excerpts[0])
    assert all("USS Other" not in row["text"] for row in excerpts)


def test_context_only_first_wave_still_searches_for_exact_identity_anchor():
    ex=object.__new__(pe.PipelineExecutor)
    ex.tenant_id='tenant'
    _with_durable_video(ex, 'SS-1 USS Holland')
    async def fetch(_client,url):
        if url.endswith('context'):
            return 'USS Holland was endorsed by an admiral as a useful submarine for harbor and coast defense.'
        return 'USS Holland (SS-1) was acquired by the U.S. Navy in 1900 and served as a training submarine.'
    ex._fetch_source_text=fetch
    ex._fetch_source_fallback_text=AsyncMock(return_value=('', ''))
    with patch.object(pe,'get_secret',AsyncMock(return_value='test-key')), \
         patch.object(httpx.AsyncClient,'post',AsyncMock(side_effect=[
             response([{'title':'Historic page','exact_source_url':'https://museum.example/context'}]),
             response([{'title':'Identity anchor','exact_source_url':'https://museum.example/anchor'}]),
         ])) as post:
        package=asyncio.run(ex._gather_verified_machine_source_package(
            'Every US Submarine Class Ever Built','SS-1 USS Holland',{'machine_script_contract':'factual_100_v1'}, video_id='video'))
    assert post.await_count==2
    assert package['passed']
