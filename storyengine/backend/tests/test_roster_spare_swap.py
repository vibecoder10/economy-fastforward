"""A machine with no usable photo never stops the video (2026-09-25).

"Most Hated Helicopters" failed its photo gather on "Missing verified images:
Kamov Ka-22". Now a miss runs a wider second search, and a machine still
without a photo is swapped for the best spare the roster list call picked.
"""
import json
from unittest.mock import AsyncMock

import pytest

import reference_sources as sources
import static_docu
from roster_images import roster_fingerprint


def _video(roster, spares, contract="factual_100_v1"):
    return {
        "id": "video-1", "video_title": "Most Hated Helicopters", "render_mode": "static_docu",
        "research_payload": {
            "documentary_style": "dvsu", "machine_script_contract": contract,
            "unit_roster": roster, "recommended_final_roster": [row["machine"] for row in roster],
            "roster_candidate_overflow": spares,
        },
    }


ROSTER = [{"machine": "UH-1 Iroquois", "act_number": 1}, {"machine": "Kamov Ka-22", "act_number": 2},
          {"machine": "CH-53 Sea Stallion", "act_number": 3}]


@pytest.fixture
def saved(monkeypatch):
    writes = []

    async def execute(query, *args):
        writes.append((query, args))
        return "UPDATE 1"
    monkeypatch.setattr(static_docu, "execute", execute)
    return writes


@pytest.mark.asyncio
async def test_photoless_machine_is_swapped_for_a_same_act_spare(monkeypatch, saved):
    spares = [{"machine": "S-58", "act_number": 1}, {"machine": "Mi-24 Hind", "act_number": 2}, {"machine": "OH-6"}]
    tried = []

    async def gather(tenant_id, video_id, entry, index):
        tried.append((entry["name"], index))
        return "verified"
    monkeypatch.setattr(static_docu, "_gather_one_photo", gather)

    fingerprint = await static_docu._swap_in_spares(_video(ROSTER, spares), "tenant-1", ["Kamov Ka-22"])

    assert tried == [("Mi-24 Hind", 1)]  # same act first, at the missing machine's slot
    query, args = saved[0]
    assert "research_payload->'unit_roster' = $4::jsonb" in query  # an edit made meanwhile wins
    payload = json.loads(args[0])
    assert [row["machine"] for row in payload["unit_roster"]] == ["UH-1 Iroquois", "Mi-24 Hind", "CH-53 Sea Stallion"]
    assert payload["unit_roster"][1]["act_number"] == 2
    assert payload["recommended_final_roster"] == ["UH-1 Iroquois", "Mi-24 Hind", "CH-53 Sea Stallion"]
    assert payload["roster_candidate_overflow"] == [{"machine": "S-58", "act_number": 1}, {"machine": "OH-6"}]
    assert payload["roster_swaps"] == [{"index": 1, "removed": "Kamov Ka-22", "spare": "Mi-24 Hind", "outcome": "swapped"}]
    assert json.loads(args[3]) == ROSTER
    assert fingerprint == roster_fingerprint(["UH-1 Iroquois", "Mi-24 Hind", "CH-53 Sea Stallion"])


@pytest.mark.asyncio
async def test_a_spare_without_a_photo_is_used_up_and_the_next_one_tried(monkeypatch, saved):
    spares = [{"machine": "S-58"}, {"machine": "OH-6"}]
    monkeypatch.setattr(static_docu, "_gather_one_photo",
                        AsyncMock(side_effect=lambda t, v, entry, i: "missing" if entry["name"] == "S-58" else "cached"))

    fingerprint = await static_docu._swap_in_spares(_video(ROSTER, spares), "tenant-1", ["Kamov Ka-22"])

    payload = json.loads(saved[0][1][0])
    assert payload["unit_roster"][1] == {"machine": "OH-6", "act_number": 2}
    assert payload["roster_candidate_overflow"] == []
    assert [swap["outcome"] for swap in payload["roster_swaps"]] == ["no_photo", "swapped"]
    assert fingerprint


@pytest.mark.asyncio
async def test_spares_used_up_keeps_the_roster_and_the_gather_fails_as_before(monkeypatch, saved):
    monkeypatch.setattr(static_docu, "_gather_one_photo", AsyncMock(return_value="missing"))

    fingerprint = await static_docu._swap_in_spares(_video(ROSTER, [{"machine": "S-58"}]), "tenant-1", ["Kamov Ka-22"])

    assert fingerprint is None
    payload = json.loads(saved[0][1][0])
    assert payload["unit_roster"] == ROSTER
    assert payload["roster_swaps"] == [{"index": 1, "removed": "Kamov Ka-22", "spare": "S-58", "outcome": "no_photo"}]


@pytest.mark.asyncio
async def test_legacy_roster_or_no_spares_never_swaps(monkeypatch, saved):
    gather = AsyncMock(return_value="verified")
    monkeypatch.setattr(static_docu, "_gather_one_photo", gather)

    assert await static_docu._swap_in_spares(_video(ROSTER, [{"machine": "S-58"}], contract=None),
                                             "tenant-1", ["Kamov Ka-22"]) is None
    assert await static_docu._swap_in_spares(_video(ROSTER, []), "tenant-1", ["Kamov Ka-22"]) is None
    gather.assert_not_awaited()
    assert saved == []


@pytest.mark.asyncio
async def test_a_miss_runs_the_wider_search_before_giving_up(monkeypatch):
    monkeypatch.setattr(static_docu, "fetch_one", AsyncMock(return_value=None))
    calls = []

    async def prefetch(tenant_id, video_id, machine, index, aliases=None, facts=None, wide=False):
        calls.append(wide)
        return wide
    monkeypatch.setattr(static_docu, "_prefetch_one_machine", prefetch)

    entry = {"name": "Kamov Ka-22", "aliases": ["Ka-22 Vintokryl"], "facts": {}}
    assert await static_docu._gather_one_photo("tenant-1", "video-1", entry, 1) == "verified"
    assert calls == [False, True]


def test_wide_queries_search_every_name_alone_unquoted():
    queries = sources._wide_queries("Kamov Ka-22", ["Kamov Ka-22", "Ka-22 Vintokryl (1959)"], {"subject": "helicopter"})
    assert queries == ["Kamov Ka-22 helicopter", "Ka-22 Vintokryl helicopter"]
    assert not any('"' in query for query in queries)


@pytest.mark.asyncio
async def test_wide_pass_skips_the_already_failed_article_photos(monkeypatch):
    monkeypatch.setattr(sources, "_article_sources", AsyncMock(return_value={
        "context": [], "images": [{"image_url": "https://upload.wikimedia.org/a/Article.jpg"}]}))
    searched = []

    async def find(query, limit=3):
        searched.append((query, limit))
        return [{"url": "https://upload.wikimedia.org/b/Wide.jpg", "title": "File:Wide.jpg"}]
    monkeypatch.setattr(sources, "find_commons_photos", find)
    monkeypatch.setattr(sources, "_commons_metadata", AsyncMock(return_value={}))

    out = await sources.collect_candidates("Kamov Ka-22", facts={"subject": "helicopter"}, wide=True)

    assert searched == [("Kamov Ka-22 helicopter", 6)]
    assert [c["image_url"] for c in out] == ["https://upload.wikimedia.org/b/Wide.jpg"]
