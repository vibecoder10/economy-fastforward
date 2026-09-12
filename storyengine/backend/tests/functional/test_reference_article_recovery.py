"""Focused coverage for bounded multi-article reference-photo recovery."""

import os
import sys

import pytest

_BACKEND = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
sys.path.insert(0, _BACKEND)

import static_docu  # noqa: E402


class _Response:
    def __init__(self, pages):
        self._pages = pages

    def raise_for_status(self):
        return None

    def json(self):
        return {"query": {"pages": self._pages}}


@pytest.mark.asyncio
async def test_later_exact_alias_article_can_supply_photo(monkeypatch):
    resolved = {
        "Nairana class": "Nairana-class escort carrier",
        "HMS Nairana": "HMS Nairana (D05)",
    }

    async def fake_resolve(_client, name):
        return resolved.get(name)

    async def fake_wm_get(_client, _url, *, params):
        if params["titles"] == "Nairana-class escort carrier":
            return _Response({
                "1": {"title": "File:Nairana class diagram.svg", "imageinfo": [{
                    "url": "https://upload.invalid/diagram.svg", "width": 1200, "height": 800,
                }]},
                "2": {"title": "File:Nairana crest.jpg", "imageinfo": [{
                    "url": "https://upload.invalid/crest.jpg", "width": 1200, "height": 800,
                }]},
            })
        return _Response({
            "3": {"title": "File:HMS Nairana D05 underway.jpg", "imageinfo": [{
                "url": "https://upload.invalid/nairana.jpg", "width": 1600, "height": 900,
            }]},
        })

    async def fake_thumbs(_client, raw_urls):
        return {raw: f"https://thumb.invalid/{raw.rsplit('/', 1)[-1]}" for raw in raw_urls}

    monkeypatch.setattr(static_docu, "_resolve_article_title", fake_resolve)
    monkeypatch.setattr(static_docu, "_wm_get", fake_wm_get)
    monkeypatch.setattr(static_docu, "_api_issued_thumbs_batch", fake_thumbs)

    rows = await static_docu.find_article_images(
        ["Nairana class", "HMS Nairana"], limit=5,
    )

    assert rows == [{
        "url": "https://thumb.invalid/nairana.jpg",
        "page": "HMS Nairana (D05)",
        "file_title": "File:HMS Nairana D05 underway.jpg",
    }]


@pytest.mark.asyncio
async def test_repeated_article_and_url_are_deduplicated(monkeypatch):
    async def fake_resolve(_client, name):
        return {
            "Activity": "HMS Activity",
            "HMS Activity": "hms activity",
            "D94": "Activity-class escort carrier",
        }.get(name)

    async def fake_wm_get(_client, _url, *, params):
        title = params["titles"]
        shared = {"title": "File:HMS Activity D94.jpg", "imageinfo": [{
            "url": "https://upload.invalid/activity.jpg", "width": 1400, "height": 900,
        }]}
        extra = {"title": "File:HMS Activity flight deck.jpg", "imageinfo": [{
            "url": "https://upload.invalid/deck.jpg", "width": 1400, "height": 900,
        }]}
        return _Response({"1": shared, **({"2": extra} if title.startswith("Activity-class") else {})})

    async def fake_thumbs(_client, raw_urls):
        assert raw_urls.count("https://upload.invalid/activity.jpg") == 1
        return {raw: f"https://thumb.invalid/{raw.rsplit('/', 1)[-1]}" for raw in raw_urls}

    monkeypatch.setattr(static_docu, "_resolve_article_title", fake_resolve)
    monkeypatch.setattr(static_docu, "_wm_get", fake_wm_get)
    monkeypatch.setattr(static_docu, "_api_issued_thumbs_batch", fake_thumbs)

    rows = await static_docu.find_article_images(
        ["Activity", "HMS Activity", "D94"], limit=5,
    )

    assert [row["url"] for row in rows] == [
        "https://thumb.invalid/activity.jpg",
        "https://thumb.invalid/deck.jpg",
    ]
    assert rows[0]["page"] == "HMS Activity"


@pytest.mark.asyncio
async def test_article_recovery_bounds_names_articles_candidates_and_results(monkeypatch):
    resolve_calls = []
    article_calls = []
    thumb_batches = []

    async def fake_resolve(_client, name):
        resolve_calls.append(name)
        return f"Article {name}"

    async def fake_wm_get(_client, _url, *, params):
        title = params["titles"]
        article_calls.append(title)
        pages = {}
        for index in range(6):
            pages[str(index)] = {
                "title": f"File:{title}-{index}.jpg",
                "imageinfo": [{
                    "url": f"https://upload.invalid/{title}-{index}.jpg",
                    "width": 1200,
                    "height": 800,
                }],
            }
        return _Response(pages)

    async def fake_thumbs(_client, raw_urls):
        thumb_batches.append(list(raw_urls))
        return {raw: raw.replace("upload.invalid", "thumb.invalid") for raw in raw_urls}

    monkeypatch.setattr(static_docu, "_resolve_article_title", fake_resolve)
    monkeypatch.setattr(static_docu, "_wm_get", fake_wm_get)
    monkeypatch.setattr(static_docu, "_api_issued_thumbs_batch", fake_thumbs)

    rows = await static_docu.find_article_images(
        ["one", "two", "three", "four", "five", "six"], limit=3,
    )

    assert resolve_calls == ["one", "two", "three", "four"]
    assert article_calls == ["Article one", "Article two", "Article three", "Article four"]
    assert len(thumb_batches) == 1
    assert len(thumb_batches[0]) == 12  # four articles * limit candidates
    assert len(rows) == 3
    assert [row["page"] for row in rows] == ["Article one", "Article two", "Article three"]
