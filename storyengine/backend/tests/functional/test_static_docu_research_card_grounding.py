"""Tests for the research-card facts / subject-planner grounding fix (G25,
live incident 2026-08-04: video d2e37cd6, scene 19 "Nairana class" / HMS
Nairana & HMS Vindex, Port Line conversions).

Root cause: `_scene_subjects`'s `facts` block is built ONLY from
research_payload's `fact_sheet` / `character_dossier` / `headline` keys. The
machine-documentary (DVsU/Anton) format never populates those — its real,
sourced research lives per-machine in `machine_research_cards`. Scene 19's
own narration carries zero numeric specs, so with no research facts to fall
back on either, the planner had nothing to build `caption_specs` from,
returned `[]`, and `_one_scene`'s metadata gate bounced the scene forever.

Fix (static_docu.py):
- `_scene_subjects` / `_scene_subjects_chunk` gained two additive, optional
  parameters (`video_id`, `roster_entries`) — omitting them (every existing
  caller before this fix, and every non-machine-documentary static-docu
  video) reproduces the exact pre-fix prompt byte-for-byte.
- When supplied, `_research_card_facts_by_scene` resolves each scene's own
  machine POSITIONALLY (`roster_entries[scene - 1]` — the same 1:1 scene <->
  roster-index mapping `pipeline_executor.py`'s `_run_static_script_hold`
  uses to save each machine's script paragraph: `scene = roster.index(
  machine) + 1`, the ONLY script-writing path for this render mode) and
  reads that machine's `machine_research_cards` row straight from the table
  (the source of truth — a video's persisted `research_payload.
  unit_research_cards` can be stale/incomplete relative to it).
- `_machine_facts_for_planner` builds a compact, sourced-fact digest from
  the roster entry's own coarse facts (role/years/status/built_count) plus
  the card's `timeframe`/`visual_identity`/any `evidence_segments[].claim`
  whose `numeric_tokens` is non-empty — attached INLINE with that segment's
  own listing text (never pooled across a chunk's other machines).

Run:
    cd storyengine/backend && ./venv/bin/python -m pytest \
        tests/functional/test_static_docu_research_card_grounding.py -q
"""
import json
import os
import sys

import pytest

_BACKEND = os.path.join(os.path.dirname(__file__), "..", "..")
sys.path.insert(0, os.path.abspath(_BACKEND))

import static_docu  # noqa: E402

# Pre-import for the same reason every other static_docu test file does:
# anthropic's _base_client.py subclasses httpx.AsyncClient at MODULE IMPORT
# time, so it must finish loading before any test monkeypatches
# httpx.AsyncClient to a fake callable (via test_static_docu_qa_park's
# _pipeline_env, used below for the end-to-end test).
import shared.clients.image_client as image_client_mod  # noqa: E402

from test_static_docu_qa_park import _pipeline_env  # noqa: E402

# The real roster item for video d2e37cd6's scene 19 (verified live via
# `se db` against the production roster/card before writing this fix).
ROSTER_ENTRY_RAW = {
    "name": "Nairana class",
    "role": "Converted merchant ships, escort carriers for convoy protection",
    "years": "Nairana commissioned December 1943, Vindex March 1943 [Hobbs 2015]",
    "status": "converted",
    "built_count": "2 ships converted [Hobbs 2015]",
    "designation": "Nairana, Vindex",
}

# Trimmed shape of the real machine_research_cards row for roster_index 19.
CARD = {
    "unit": "Nairana, Vindex Nairana class",
    "timeframe": (
        "Ships Cover papers for the Vindex class escort carriers cover the "
        "period June 1942 to May 1948."
    ),
    "visual_identity": (
        "Identified by the class's flight deck, hangar, arrestor wires, and lift."
    ),
    "evidence_segments": [
        {
            "kind": "original_problem",
            "claim": "In July 1942 the Admiralty requisitioned three merchant hulls.",
            "numeric_tokens": ["1942", "three"],
        },
        {
            # No numeric_tokens — must NEVER be treated as a sourced spec.
            "kind": "engineering_decision",
            "claim": "Aircraft facilities comprised the exact same flight deck, hangar, arrestor wires and lift.",
            "numeric_tokens": [],
        },
    ],
}

# Deliberately no digits anywhere in the narration — the exact live shape
# ("Scene 19's narration is the only one with zero numeric specs").
SCENE_TEXT_NO_NUMBERS = (
    "The Admiralty requisitioned merchant hulls still on the stocks and had "
    "them completed as escort carriers, standardizing their flight deck, "
    "hangar and lift."
)


# ---------------------------------------------------------------------------
# Pure-function unit tests for _machine_facts_for_planner — no I/O.
# ---------------------------------------------------------------------------

def _roster_entry(facts_overrides=None):
    facts = {
        "role": ROSTER_ENTRY_RAW["role"],
        "years": ROSTER_ENTRY_RAW["years"],
        "status": ROSTER_ENTRY_RAW["status"],
        "built_count": ROSTER_ENTRY_RAW["built_count"],
    }
    if facts_overrides is not None:
        facts = facts_overrides
    return {"name": "Nairana class", "aliases": [], "never_built": False, "facts": facts}


def test_machine_facts_for_planner_combines_roster_and_card_facts():
    text = static_docu._machine_facts_for_planner(_roster_entry(), CARD)

    assert "built count: 2 ships converted [Hobbs 2015]" in text
    assert "timeframe: Ships Cover papers" in text
    assert "visual identity: Identified by the class's flight deck" in text
    assert "sourced numeric claims: In July 1942 the Admiralty requisitioned three merchant hulls." in text
    # The numeric_tokens-less claim must never surface as a "sourced" spec.
    assert "Aircraft facilities comprised" not in text


def test_machine_facts_for_planner_degrades_gracefully_without_a_card():
    """No card yet (or this roster slot's card never resolved) -> roster-
    entry facts only, never a crash."""
    text = static_docu._machine_facts_for_planner(_roster_entry(), None)
    assert "built count: 2 ships converted" in text
    assert "timeframe" not in text
    assert "visual identity" not in text


def test_machine_facts_for_planner_empty_entry_and_card_returns_empty_string():
    assert static_docu._machine_facts_for_planner(None, None) == ""
    assert static_docu._machine_facts_for_planner({}, {}) == ""


# ---------------------------------------------------------------------------
# _research_card_facts_by_scene: positional scene -> roster_entries[scene-1]
# resolution, reading the machine_research_cards TABLE (not the possibly
# stale research_payload).
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_research_card_facts_by_scene_short_circuits_without_roster(monkeypatch):
    """No locked machine roster (the ordinary static-docu path) -> zero DB
    calls, empty dict — this fix must be a complete no-op for that format."""

    async def fail_fetch_all(query, *args):
        raise AssertionError("must not query machine_research_cards without a roster")

    monkeypatch.setattr(static_docu, "fetch_all", fail_fetch_all)

    out = await static_docu._research_card_facts_by_scene(
        "tenant", "video", [{"scene": 1, "scene_text": "x"}], [])
    assert out == {}


@pytest.mark.asyncio
async def test_research_card_facts_by_scene_resolves_positionally(monkeypatch):
    """Scene 19's machine is roster_entries[18] — resolved by POSITION, not
    by any name the (not-yet-run) planner might guess."""
    roster_entries = (
        [{"name": f"Padding {i}", "aliases": [], "never_built": False, "facts": {}}
         for i in range(1, 19)]
        + [{"name": "Nairana class", "aliases": [], "never_built": False,
            "facts": {"built_count": ROSTER_ENTRY_RAW["built_count"]}}]
    )
    assert len(roster_entries) == 19

    captured_args = {}

    async def fake_fetch_all(query, *args):
        assert "FROM machine_research_cards" in query
        captured_args["args"] = args
        return [{"roster_index": 19, "card": json.dumps(CARD)}]

    monkeypatch.setattr(static_docu, "fetch_all", fake_fetch_all)

    out = await static_docu._research_card_facts_by_scene(
        "tenant-1", "video-1", [{"scene": 19, "scene_text": SCENE_TEXT_NO_NUMBERS}],
        roster_entries)

    assert captured_args["args"] == ("tenant-1", "video-1", [19])
    assert 19 in out
    assert out[19].startswith("Nairana class — ")
    assert "built count: 2 ships converted" in out[19]
    assert "timeframe: Ships Cover papers" in out[19]


# ---------------------------------------------------------------------------
# (a) End-to-end: a scene whose narration has no numbers, but whose machine
# card carries sourced facts, gets those facts in the planner prompt and
# passes _one_scene's metadata gate (fake client asserting prompt content).
# ---------------------------------------------------------------------------

class _GroundedTextClient:
    """Fake Claude text client that proves it actually SAW the injected
    research-card facts: it only returns a populated caption_sub/
    caption_specs when the prompt carries the SOURCED RESEARCH marker —
    mirroring the real contract, since the narration itself has nothing to
    build them from (the live bug)."""

    def __init__(self):
        self.prompts: list[str] = []

    async def generate(self, **kwargs):
        prompt = kwargs["prompt"]
        self.prompts.append(prompt)
        if "SOURCED RESEARCH FOR THIS SEGMENT'S MACHINE" not in prompt:
            return json.dumps([{
                "scene": 1, "machine": "Nairana class", "aliases": [],
                "caption_title": "Nairana class", "caption_sub": "",
                "caption_specs": [], "detail_focus": "overall machine geometry",
                "search_query": "Nairana class escort carrier",
            }])
        return json.dumps([{
            "scene": 1,
            "machine": "Nairana class",
            "aliases": ["HMS Nairana", "HMS Vindex"],
            "caption_title": "Nairana class",
            "caption_sub": "Royal Navy • 1942-1948",
            "caption_specs": ["2 ships converted", "Requisitioned 1942"],
            "detail_focus": "flight deck, hangar, arrestor wires and lift",
            "search_query": "Nairana class escort carrier",
        }])


@pytest.mark.asyncio
async def test_scene_with_no_narration_numbers_gets_card_facts_and_passes_gate(
    monkeypatch,
):
    env = _pipeline_env(
        monkeypatch, verdicts=[True], gen_urls=["https://kie.example/render1.png"],
        image_client_module=image_client_mod, docu_module=static_docu,
    )

    roster = [
        dict(ROSTER_ENTRY_RAW),
        {"name": "HMS Campania (D48) Campania class", "status": "converted",
         "built_count": "1 ship converted"},
        {"name": "HMS Unicorn (I72) Unicorn", "status": "built",
         "built_count": "1 ship completed"},
    ]
    research_payload = {"documentary_style": "designed_vs_used", "unit_roster": roster}

    async def fake_fetch_one(query, *args):
        if "FROM videos" in query:
            return {"id": env["video_id"], "video_title": "Test Video",
                    "aspect": "16:9", "render_mode": "static_docu",
                    "research_payload": research_payload}
        if "FROM static_reference_cache" in query:
            return {"hosted_url": "https://storage.example/ref.jpg",
                    "source_url": "https://commons.example/ref.jpg"}
        return None

    async def fake_fetch_all(query, *args):
        if "FROM scripts" in query:
            return [{"scene": 1, "scene_text": SCENE_TEXT_NO_NUMBERS}]
        if "FROM machine_research_cards" in query:
            assert args[2] == [1]
            return [{"roster_index": 1, "card": json.dumps(CARD)}]
        if "SELECT id, status, image_url, caption FROM assets" in query:
            return []
        return []

    monkeypatch.setattr(static_docu, "fetch_one", fake_fetch_one)
    monkeypatch.setattr(static_docu, "fetch_all", fake_fetch_all)

    fake_client = _GroundedTextClient()
    import kie_unified

    async def fake_get_text_client_for_tenant(tid):
        return fake_client

    monkeypatch.setattr(
        kie_unified, "get_text_client_for_tenant", fake_get_text_client_for_tenant)

    result = await static_docu.generate_static_images_for_video(
        env["video_id"], env["tenant_id"])

    # The prompt actually carried this segment's own machine's sourced facts.
    assert len(fake_client.prompts) == 1
    prompt = fake_client.prompts[0]
    assert "SOURCED RESEARCH FOR THIS SEGMENT'S MACHINE" in prompt
    assert "Nairana class" in prompt
    assert "built count: 2 ships converted [Hobbs 2015]" in prompt
    assert "flight deck, hangar, arrestor wires" in prompt
    assert "In July 1942 the Admiralty requisitioned three merchant hulls." in prompt
    # The other two roster machines' facts must never leak into scene 1's block.
    assert "1 ship converted" not in prompt
    assert "1 ship completed" not in prompt

    # And with those facts available, the scene cleared the metadata gate and
    # actually generated + shipped — the live bug's scene never got this far.
    assert result["status"] == "completed"
    assert len(env["assets"]) == 1
    row = next(iter(env["assets"].values()))
    assert row["status"] == "done"
    assert row["image_url"] is not None


# ---------------------------------------------------------------------------
# (c) Regression: ordinary scenes' planning (no roster/card facts supplied)
# is byte-for-byte unchanged.
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_scene_subjects_chunk_prompt_unchanged_without_card_facts():
    captured = {}

    class _Client:
        async def generate(self, **kwargs):
            captured["prompt"] = kwargs["prompt"]
            return json.dumps([{
                "scene": 1, "machine": "Some Machine", "aliases": [],
                "caption_title": "Some Machine", "caption_sub": "Operator • 1950",
                "caption_specs": ["Spec"], "detail_focus": "x", "search_query": "y",
            }])

    chunk = [{"scene": 1, "scene_text": "Plain narration with no card facts."}]
    out = await static_docu._scene_subjects_chunk(_Client(), None, "", chunk)

    assert out is not None
    assert "SOURCED RESEARCH FOR THIS SEGMENT'S MACHINE" not in captured["prompt"]
    assert captured["prompt"].count("[1] Plain narration with no card facts.") == 1


@pytest.mark.asyncio
async def test_scene_subjects_old_three_arg_call_style_still_works(monkeypatch):
    """Every caller of _scene_subjects before this fix (and every non-
    machine-documentary static-docu video today) passes exactly 3 positional
    args — video_id/roster_entries must default to "no card facts" so that
    call style is completely unaffected."""
    captured = {}

    class _Client:
        async def generate(self, **kwargs):
            captured.setdefault("prompts", []).append(kwargs["prompt"])
            return json.dumps([{
                "scene": 1, "machine": "Some Machine", "aliases": [],
                "caption_title": "Some Machine", "caption_sub": "Operator • 1950",
                "caption_specs": ["Spec"], "detail_focus": "x", "search_query": "y",
            }])

    import kie_unified

    async def fake_get_text_client_for_tenant(tid):
        return _Client()

    monkeypatch.setattr(
        kie_unified, "get_text_client_for_tenant", fake_get_text_client_for_tenant)

    scenes = [{"scene": 1, "scene_text": "Plain narration."}]
    subjects, unparseable = await static_docu._scene_subjects("tenant", scenes, None)

    assert unparseable == []
    assert subjects[1]["caption_sub"] == "Operator • 1950"
    assert "SOURCED RESEARCH FOR THIS SEGMENT'S MACHINE" not in captured["prompts"][0]
