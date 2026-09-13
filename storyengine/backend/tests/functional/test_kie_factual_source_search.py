import asyncio
import json
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

import httpx
import pytest

import factual_source_search as search
import pipeline_executor as pe
from factual_machine_research import factual_package_contract_warnings


MACHINE = "General Dynamics FB-111A Aardvark"


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
    executor._fetch_source_text = AsyncMock(return_value=text)
    executor._fetch_source_fallback_text = AsyncMock(return_value=("", ""))
    with patch.object(pe, "get_secret", AsyncMock(return_value="test-key")) as secret, \
         patch.object(httpx.AsyncClient, "post", AsyncMock(return_value=response())) as post:
        package = asyncio.run(executor._gather_verified_machine_source_package(
            "Every US Strategic Bomber", MACHINE, {"machine_script_contract": "factual_100_v1"},
        ))
    secret.assert_awaited_once_with("kie_ai_api_key", "tenant-1")
    assert post.await_count == 1
    assert post.call_args.args[0] == search.ENDPOINT
    assert (not factual_package_contract_warnings(MACHINE, package)) is passes
    assert package["source_discovery"]["credits_consumed"] == 0.32
    if passes:
        assert package["candidate_excerpts"][0]["text"] == text
        assert package["candidate_excerpts"][0]["source_capture_method"] == "fetched_page"


def test_factual_route_without_kie_key_does_not_spend_on_tavily():
    executor = object.__new__(pe.PipelineExecutor)
    executor.tenant_id = "tenant-1"
    with patch.object(pe, "get_secret", AsyncMock(return_value=None)) as secret:
        with pytest.raises(search.SourceDiscoveryError, match="Missing Kie"):
            asyncio.run(executor._gather_verified_machine_source_package(
                "Every bomber", MACHINE, {"machine_script_contract": "factual_100_v1"},
            ))
    secret.assert_awaited_once_with("kie_ai_api_key", "tenant-1")
