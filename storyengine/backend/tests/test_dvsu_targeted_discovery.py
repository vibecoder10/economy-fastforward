"""Offline contracts for semantic DVSU targeted source discovery."""
from __future__ import annotations

import asyncio
import json
from types import SimpleNamespace
from unittest.mock import AsyncMock

import httpx

import factual_source_search as search


MACHINE = "SS-2 USS Plunger"
TITLE = "Every US Submarine Class Ever Built"


def _client(rows):
    return SimpleNamespace(post=AsyncMock(return_value=httpx.Response(200, json={
        "id": "targeted-1",
        "choices": [{"message": {"content": json.dumps(rows)}}],
    })))


def test_targeted_missing_fields_expand_to_historical_evidence_needs():
    client = _client([{"title": "Archive", "exact_source_url": "https://archive.example/plunger"}])

    _leads, receipt = asyncio.run(search.discover_sources(
        client, "test-key", TITLE, MACHINE,
        missing_fields=["intended_role", "design", "unknown", "intended_role"],
    ))

    prompt = client.post.await_args.kwargs["json"]["messages"][0]["content"]
    assert "original mission, design objective, or problem" in prompt
    assert "not classification, launch, or commissioning alone" in prompt
    assert "documented engineering decision or configuration" in prompt
    assert "Missing research fields to prioritize" not in prompt
    assert receipt["missing_fields"] == ["intended_role", "design"]
    assert receipt["query"] == " ".join(prompt.split())


def test_class_or_generation_lead_requires_explicit_locked_machine_linkage():
    client = _client([{"title": "Class history", "exact_source_url": "https://archive.example/class"}])

    asyncio.run(search.discover_sources(client, "test-key", TITLE, MACHINE, missing_fields=["actual_use"]))

    prompt = client.post.await_args.kwargs["json"]["messages"][0]["content"]
    assert "explicitly names the exact locked machine" in prompt
    assert "never assume a class or generation fact applies" in prompt


def test_default_discovery_and_receipt_keep_public_leads_only():
    client = _client([
        {"title": "First", "exact_source_url": "https://archive.example/one"},
        {"title": "Duplicate", "exact_source_url": "https://archive.example/one"},
        {"title": "Private", "exact_source_url": "http://127.0.0.1/private"},
        {"title": "PDF", "exact_source_url": "https://archive.example/report.pdf", "pdf_page": 7},
        {"title": "Third", "exact_source_url": "https://archive.example/three"},
        {"title": "Fourth", "exact_source_url": "https://archive.example/four"},
        {"title": "Fifth", "exact_source_url": "https://archive.example/five"},
        {"title": "Sixth", "exact_source_url": "https://archive.example/six"},
        {"title": "Seventh", "exact_source_url": "https://archive.example/seven"},
    ])

    leads, receipt = asyncio.run(search.discover_sources(client, "test-key", TITLE, MACHINE))

    assert [lead["url"] for lead in leads] == [
        "https://archive.example/one", "https://archive.example/report.pdf#page=7",
        "https://archive.example/three", "https://archive.example/four",
        "https://archive.example/five", "https://archive.example/six",
    ]
    assert receipt["missing_fields"] == []
    assert receipt["lead_urls"] == [lead["url"] for lead in leads]
    assert "Target these current evidence needs" not in receipt["query"]
    assert client.post.await_count == 1
