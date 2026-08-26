"""Tests for chunk G24 (2026-08-03): the static-docu reference hunt now
consults the video's OWN verified roster reference photo before ever
web-hunting Wikipedia/Commons.

Root cause (live, video d2e37cd6-521a-43aa-a14d-ce096a783c1e — "Every
British Aircraft Carrier Class Ever Built"): the roster stage had already
verified real photos for 22/23 machines (static_reference_cache, written by
prefetch_roster_references at research-lock time), but 9 scene rows still
landed `blocked_no_reference` at the PICTURES stage. LAYER 0 in `_one_scene`
(the direct `static_reference_cache` lookup) keys on
`_machine_key(THIS SCENE's own LLM-derived "machine" label)` —
`_scene_subjects` derives that label from the scene's narration text alone,
with no access to the roster, so a short natural guess ("HMS Eagle") almost
never equals a roster entry's compound bookkeeping display name ("HMS Eagle
(1918) Eagle"), let alone a ship-class entry's genuinely unsearchable glued
string ("Lend-Lease escort carriers Ruler class (US-built)"). 7 of the 9
blocked scenes were exactly this: a roster machine WITH a verified cache
row, blocked only because the scene's own guessed label missed LAYER 0's
exact-key lookup. The other 2 (CVA-01, scenes 9+13) are correctly,
permanently blocked — the class was cancelled before any hull was laid
down, so no photograph can ever exist.

Fix: `_roster_entry_for_scene_machine` (static_docu.py) resolves a scene's
own machine/aliases to exactly one roster entry by reusing `_page_matches`
against the roster entry's own name+aliases text — ambiguous (0 or 2+ hits)
returns None, the SAME fail-closed rule pipeline_executor.py's
`_locked_roster_item_for_machine`/`_roster_index_for_identity` already use
for the real "Lend-Lease escort carriers Attacker/Ruler class" collision
and the real "CVA-01 class" vs "Audacious class / Malta class" collision
(both normalize to the same `_normalized_unit_code`, CVA01). A resolved
roster photo is NEVER trusted blindly: it still runs through
`_vision_confirms` (trusted_source=True, since nothing reaches
static_reference_cache without already clearing that same check once) before
ever being accepted as the scene's reference.

Run:
    cd storyengine/backend && ./venv/bin/python -m pytest \
        tests/functional/test_static_docu_roster_reference_layer.py -q
"""
import os
import sys
import uuid
from pathlib import Path

import pytest

_BACKEND = os.path.join(os.path.dirname(__file__), "..", "..")
sys.path.insert(0, os.path.abspath(_BACKEND))

_REPO_ROOT = Path(__file__).resolve().parents[4]
_PIPELINE_ROOT = _REPO_ROOT / "skills" / "video-pipeline"
if str(_PIPELINE_ROOT) not in sys.path:
    sys.path.insert(0, str(_PIPELINE_ROOT))

import static_docu  # noqa: E402
import pipeline_executor as pe  # noqa: E402


# ---------------------------------------------------------------------------
# The real roster shapes from video d2e37cd6 ("Every British Aircraft
# Carrier Class Ever Built") — the exact live collision this fix must
# resolve safely. Reused verbatim (not simplified) across the tests below so
# the collision-safety assertions are grounded in the real data, not a toy.
# ---------------------------------------------------------------------------

_ATTACKER = {
    "name": "Attacker class (US-built)",
    "designation": "Lend-Lease escort carriers",
    "role": "US-built Bogue-class escort carriers operated by Royal Navy under Lend-Lease",
    "years": "Transferred 1942-1943, returned to US 1946",
    "status": "production",
    "built_count": "Approximately 8 ships of Attacker group transferred",
}
_RULER = {
    "name": "Ruler class (US-built)",
    "designation": "Lend-Lease escort carriers",
    "role": "US-built Casablanca-class escort carriers operated by Royal Navy under Lend-Lease",
    "years": "Transferred 1943-1944, returned to US 1946",
    "status": "production",
    "built_count": "Approximately 23 ships transferred",
}
_EAGLE = {
    "name": "Eagle",
    "designation": "HMS Eagle (1918)",
    "role": "Converted from incomplete Chilean battleship, large fleet carrier",
    "years": "Laid down 1913 as battleship, converted 1918-1924, commissioned April 1924",
    "status": "converted",
    "built_count": "1 ship converted",
}
_CVA01_PREDECESSORS = {
    "name": "Audacious class / Malta class",
    "designation": "CVA-01 predecessors",
    "role": "Large fleet carriers, four laid down 1942-1943, three cancelled on slips, one completed as HMS Eagle (1951)",
    "years": "Eagle (R05) laid down 1942, commissioned October 1951",
    "status": "cancelled-built",
    "built_count": "1 ship completed (Eagle R05), 3 cancelled on slips",
}
_CVA01_CLASS = {
    "name": "CVA-01 class",
    "designation": "CVA-01 Queen Elizabeth class (1960s design)",
    "role": "Large fleet carrier cancelled 1966, would have been first British angled-deck purpose-built carrier",
    "years": "Designed 1963-1966, cancelled by Defence White Paper February 1966",
    "status": "cancelled-built",
    "built_count": "0 ships built, cancelled February 1966 before construction",
}
_UNICORN = {"name": "Unicorn", "designation": "HMS Unicorn (I72)"}
_ARK_ROYAL_1937 = {
    "name": "Ark Royal (1937)",
    "designation": "HMS Ark Royal (91)",
    "role": "First modern British fleet carrier with armored hangar and two-hangar design",
    "years": "Laid down 1935, commissioned November 1938",
    "status": "production",
    "built_count": "1 ship",
}
_INVINCIBLE = {
    "name": "Invincible class",
    "designation": "Invincible, Illustrious, Ark Royal (R07)",
    "role": "Through-deck cruisers/light STOVL carriers for Sea Harrier and helicopters",
    "years": "Invincible commissioned July 1980, Illustrious June 1982, Ark Royal November 1985",
    "status": "production",
    "built_count": "3 ships",
}
_HERMES_1924 = {
    "name": "Hermes",
    "designation": "HMS Hermes (95)",
    "role": "World's first purpose-designed aircraft carrier laid down as such",
    "years": "Laid down January 1918, commissioned February 1924",
    "status": "production",
    "built_count": "1 ship",
}
_CENTAUR = {
    "name": "Centaur class",
    "designation": "Centaur, Albion, Bulwark, Hermes (R12)",
    "role": "Intermediate fleet carriers, evolved from light fleet design with stronger structure",
    "years": "Centaur commissioned September 1953, Albion May 1954, Bulwark November 1954, Hermes November 1959",
    "status": "production",
    "built_count": "4 ships",
}
_ACTIVITY = {
    "name": "Activity class",
    "designation": "HMS Activity (D94)",
    "role": "Converted refrigerated cargo ship, used for training and ferry duties",
    "years": "Converted 1942, commissioned September 1942",
    "status": "converted",
    "built_count": "1 ship converted",
}


def _video_row(video_id: str, roster: list) -> dict:
    return {
        "id": video_id,
        "video_title": "Every British Aircraft Carrier Class Ever Built",
        "aspect": "16:9",
        "render_mode": "static_docu",
        "research_payload": {
            "documentary_style": "designed_vs_used",
            "unit_roster": roster,
        },
    }


def _roster_entries(roster: list) -> list:
    """The real accessor _one_scene itself uses — never hand-roll the
    name/alias derivation in a test, or a drift between the two would be
    invisible."""
    video = _video_row("v", roster)
    return pe._machine_documentary_hold_roster_entries(video)


def _cache_key_for(item: dict) -> str:
    return static_docu._machine_key(pe._unit_display_name(item))


# ---------------------------------------------------------------------------
# Part 1 — _roster_entry_for_scene_machine: pure-function resolution +
# collision safety (mirrors pipeline_executor's own G21b/G22 fail-closed
# rule, applied here to the alias-derived roster shape).
# ---------------------------------------------------------------------------

def test_resolves_ruler_scene_to_ruler_entry_not_attacker():
    """(c) name-collision safety: 'Attacker class (US-built)' and 'Ruler
    class (US-built)' share the exact same designation prefix ('Lend-Lease
    escort carriers') and even the same _normalized_unit_code — only the
    word 'ruler' vs 'attacker' distinguishes them. A scene about HMS Ruler
    must resolve to the Ruler entry ONLY."""
    entries = _roster_entries([_ATTACKER, _RULER, _UNICORN])
    match = static_docu._roster_entry_for_scene_machine(entries, "HMS Ruler", [])
    assert match is not None
    assert match["name"] == pe._unit_display_name(_RULER)


def test_resolves_attacker_scene_to_attacker_entry_not_ruler():
    """The mirror image of the test above — the same collision pair, the
    other machine."""
    entries = _roster_entries([_ATTACKER, _RULER, _UNICORN])
    match = static_docu._roster_entry_for_scene_machine(entries, "HMS Attacker", [])
    assert match is not None
    assert match["name"] == pe._unit_display_name(_ATTACKER)


def test_scene17_activity_with_escort_carrier_alias_resolves():
    """G24b live repro (video d2e37cd6, scene 17, 2026-08-04): the scene
    guessed 'HMS Activity (D94)' — the roster's own designation, verbatim —
    yet _roster_entry_for_scene_machine returned None and the scene landed
    blocked, even though a roster-verified photo sat in
    static_reference_cache under 'hmsactivityd94activityclass' the whole
    time (the session worked around it by hand-seeding an alias cache key).

    Mechanism (established by running the REAL functions against the REAL
    23-entry live roster): the guess alone resolves fine; the kill shot is
    any scene ALIAS carrying 'escort carrier' — natural for an escort
    carrier — whose word 'escort' also word-overlaps BOTH 'Lend-Lease
    escort carriers …' entries, inflating one true hit to three and
    tripping the exactly-one rule. Shared bookkeeping words must not be
    allowed to spoil a guess that names one entry uniquely ('activity',
    'd94' each match the Activity entry and it alone)."""
    entries = _roster_entries([_ACTIVITY, _ATTACKER, _RULER, _UNICORN])
    match = static_docu._roster_entry_for_scene_machine(
        entries, "HMS Activity (D94)",
        ["HMS Activity", "Activity class escort carrier"])
    assert match is not None
    assert match["name"] == pe._unit_display_name(_ACTIVITY)


def test_scene22_ruler_class_escort_carrier_guess_resolves_to_ruler():
    """G24b live repro (video d2e37cd6, scene 22, 2026-08-04): the scene
    guessed 'Ruler-class Escort Carrier' — no aliases needed to break it.
    'ruler' matches only the Ruler entry, but 'escort' word-overlaps both
    Lend-Lease entries, so the old exactly-one rule saw two hits and
    fail-closed to None despite a verified cache row under the Ruler
    entry's compound key. 'ruler' is unique to one entry across the whole
    roster — that discriminating evidence must win over the shared
    bookkeeping word that can't tell the siblings apart."""
    entries = _roster_entries([_ACTIVITY, _ATTACKER, _RULER, _UNICORN])
    match = static_docu._roster_entry_for_scene_machine(
        entries, "Ruler-class Escort Carrier", [])
    assert match is not None
    assert match["name"] == pe._unit_display_name(_RULER)


def test_generic_lend_lease_guess_stays_ambiguous():
    """The G21b collision guard the fix must NOT weaken: a guess made of
    ONLY the words the two Lend-Lease siblings share ('Lend-Lease escort
    carrier') carries no evidence unique to either entry — it must stay
    fail-closed None, never silently pick Attacker or Ruler."""
    entries = _roster_entries([_ACTIVITY, _ATTACKER, _RULER, _UNICORN])
    match = static_docu._roster_entry_for_scene_machine(
        entries, "Lend-Lease escort carrier", [])
    assert match is None


def test_guess_naming_both_siblings_stays_ambiguous():
    """A guess whose words discriminate for TWO different entries at once
    ('Attacker and Ruler escort groups') is genuinely ambiguous — two
    unique-evidence winners is still not one, and must return None."""
    entries = _roster_entries([_ACTIVITY, _ATTACKER, _RULER, _UNICORN])
    match = static_docu._roster_entry_for_scene_machine(
        entries, "Attacker and Ruler escort groups", [])
    assert match is None


def test_pennant_guess_resolves_when_words_and_token_both_fail():
    """The other 'HMS <name> (<pennant>)' shape from the same live roster:
    'HMS Ark Royal (91)' has NO word/token evidence at all — '91' is under
    _designation_token_in_title's 3-char floor (C36's own guard), 'royal'
    is a generic word, 'ark' is under the 4-char word floor. Only machine-
    key containment can identify it: 'hmsarkroyal91' sits inside exactly
    one entry key ('hmsarkroyal91arkroyal1937') across the whole roster —
    the Invincible-class sibling that ALSO carries an Ark Royal (R07) never
    contains the pennant-bearing prefix."""
    entries = _roster_entries([_ARK_ROYAL_1937, _INVINCIBLE, _UNICORN])
    match = static_docu._roster_entry_for_scene_machine(
        entries, "HMS Ark Royal (91)", [])
    assert match is not None
    assert match["name"] == pe._unit_display_name(_ARK_ROYAL_1937)


def test_bare_shared_ship_name_stays_ambiguous():
    """Containment must NOT let a bare shared name pick a winner: the
    roster genuinely holds two HMS Hermes (the 1924 carrier, and Hermes
    R12 inside the Centaur class) and two Ark Royals (1937, and R07 inside
    the Invincible class). Without a pennant the guess is genuinely
    ambiguous and must stay None — only the digit-bearing form may resolve
    ('HMS Hermes (95)' names the 1924 ship alone)."""
    entries = _roster_entries(
        [_HERMES_1924, _CENTAUR, _ARK_ROYAL_1937, _INVINCIBLE, _UNICORN])
    assert static_docu._roster_entry_for_scene_machine(
        entries, "HMS Hermes", []) is None
    assert static_docu._roster_entry_for_scene_machine(
        entries, "HMS Ark Royal", []) is None
    match = static_docu._roster_entry_for_scene_machine(
        entries, "HMS Hermes (95)", [])
    assert match is not None
    assert match["name"] == pe._unit_display_name(_HERMES_1924)


def test_resolves_short_guess_to_compound_roster_display_name():
    """The exact shape that broke LAYER 0's direct cache lookup: a scene's
    short natural guess ('HMS Eagle') vs the roster's compound bookkeeping
    display name ('HMS Eagle (1918) Eagle')."""
    entries = _roster_entries([_EAGLE, _RULER, _UNICORN])
    match = static_docu._roster_entry_for_scene_machine(entries, "HMS Eagle", [])
    assert match is not None
    assert match["name"] == pe._unit_display_name(_EAGLE)


def test_cva01_scenes_stay_ambiguous_never_built_and_predecessor_collide():
    """(b)-adjacent collision safety: 'CVA-01 class' (never built — the
    actual cancelled programme) and 'Audacious class / Malta class' (its
    predecessor, one hull of which WAS completed) both name 'CVA-01' in
    their own text and both normalize to the same _normalized_unit_code
    (CVA01) — a real, live collision. A bare 'CVA-01' scene guess must NOT
    silently pick one; resolving ambiguously to None is what keeps this
    machine correctly, permanently blocked rather than borrowing a
    predecessor's photo for a ship that never existed."""
    entries = _roster_entries([_CVA01_PREDECESSORS, _CVA01_CLASS, _UNICORN])
    match = static_docu._roster_entry_for_scene_machine(entries, "CVA-01", [])
    assert match is None


def test_no_match_for_unrelated_machine_returns_none():
    entries = _roster_entries([_ATTACKER, _RULER, _UNICORN])
    match = static_docu._roster_entry_for_scene_machine(
        entries, "Supermarine Spitfire", [])
    assert match is None


def test_empty_roster_returns_none():
    assert static_docu._roster_entry_for_scene_machine([], "HMS Ruler", []) is None


# ---------------------------------------------------------------------------
# Part 2 — full generate_static_images_for_video(): the roster reference
# layer wired into the actual reference hunt (order, and which of
# _host_reference/_vision_confirms fire).
# ---------------------------------------------------------------------------

class _FakeTextClient:
    """Stands in for the Claude client _scene_subjects uses to plan each
    scene's machine/aliases. `reply` is the raw JSON array text."""

    def __init__(self, reply: str):
        self.reply = reply
        self.calls = 0

    async def generate(self, **kwargs):
        self.calls += 1
        return self.reply


def _install_generation_stop(monkeypatch):
    """Let generate_static_images_for_video run all the way through
    reference resolution, then stop cleanly at the budget-cap gate — the
    FIRST check inside the per-view generation loop, well after ref_url is
    already decided. This tests the reference hunt end-to-end without
    needing to mock the image-generation/QA machinery beneath it."""
    import actions

    async def _always_refuses(tenant_id, video_id, quote_cost, item_label="this generation"):
        return "budget cap reached (test stub)"

    monkeypatch.setattr(actions, "budget_refusal", _always_refuses)


def _install_common_fakes(monkeypatch, video_row, scene_text, machine, aliases=None,
                          cache_rows=None, fail_on_web_hunt=True):
    """Shared harness for the end-to-end tests below. `cache_rows` is
    {machine_key: {"hosted_url", "source_url"}}. When `fail_on_web_hunt` is
    True (the roster-hit tests), the web-hunt functions raise if ever
    called — the whole point of the fix is that they must NOT be needed."""
    cache_rows = cache_rows or {}
    db_rows = {"assets": {}}
    calls = {"host_reference": [], "vision_confirms": [], "cache_lookups": [],
             "cache_queries": [], "cache_writes": []}

    async def fake_fetch_one(query, *args):
        if "FROM videos" in query:
            return dict(video_row)
        if "FROM static_reference_cache" in query:
            mkey = args[1]
            calls["cache_lookups"].append(mkey)
            row = cache_rows.get(mkey)
            requested_kind = "photo" if "reference_kind='photo'" in query else (
                "design" if "reference_kind='design'" in query else None)
            calls["cache_queries"].append((requested_kind, mkey))
            row_kind = (row or {}).get("reference_kind", "photo")
            return dict(row) if row and requested_kind == row_kind else None
        return None

    async def fake_fetch_all(query, *args):
        if "FROM scripts" in query:
            return [{"scene": 1, "scene_text": scene_text}]
        return []

    async def fake_execute(query, *args):
        if "INSERT INTO assets" in query:
            row_id = args[0]
            db_rows["assets"][row_id] = {
                "status": "generating", "image_url": None, "drive_image_url": None,
            }
        elif "UPDATE assets SET drive_image_url" in query:
            row_id, val = args[0], args[1]
            db_rows["assets"].setdefault(row_id, {})["drive_image_url"] = val
        elif "UPDATE assets SET status='blocked_no_reference'" in query:
            row_id = args[0]
            row = db_rows["assets"].setdefault(row_id, {})
            row["status"] = "blocked_no_reference"
            row["image_url"] = None
            row["drive_image_url"] = None
        elif "UPDATE assets SET status='budget_capped'" in query:
            row_id = args[0]
            db_rows["assets"].setdefault(row_id, {})["status"] = "budget_capped"
        elif "INSERT INTO static_reference_cache" in query:
            calls["cache_writes"].append(args)
        elif "DELETE FROM assets WHERE id=" in query:
            db_rows["assets"].pop(args[0], None)
        return None

    async def _unexpected_web_hunt(*a, **k):
        raise AssertionError(
            "web-hunt function must not be called — a roster reference "
            "photo was already available")

    async def _empty_web_hunt(*a, **k):
        return []

    web_hunt = _unexpected_web_hunt if fail_on_web_hunt else _empty_web_hunt
    monkeypatch.setattr(static_docu, "find_wikipedia_lead_images", web_hunt)
    monkeypatch.setattr(static_docu, "find_article_images", web_hunt)
    monkeypatch.setattr(static_docu, "find_commons_photos", web_hunt)

    async def fake_host_reference(url, vid, tid, tag):
        calls["host_reference"].append((url, tag))
        return f"https://storage.example/{tag}.jpg"

    async def fake_vision_confirms(tenant_id, image_url, m, aliases=None,
                                   trusted_source=False, facts=None, source_label=None):
        calls["vision_confirms"].append({
            "image_url": image_url, "machine": m, "aliases": aliases,
            "trusted_source": trusted_source, "facts": facts,
            "source_label": source_label,
        })
        return True

    monkeypatch.setattr(static_docu, "_host_reference", fake_host_reference)
    monkeypatch.setattr(static_docu, "_vision_confirms", fake_vision_confirms)

    aliases_json = ", ".join(f'"{a}"' for a in (aliases or []))
    reply = (
        f'[{{"scene": 1, "machine": "{machine}", "aliases": [{aliases_json}], '
        f'"caption_title": "{machine}", '
        f'"caption_sub": "Royal Navy • 1943-1946", '
        f'"caption_specs": ["Displacement 11000 tons"], '
        f'"detail_focus": "overall hull geometry", '
        f'"search_query": "{machine}"}}]'
    )
    fake_client = _FakeTextClient(reply)

    async def fake_get_text_client_for_tenant(tenant_id):
        return fake_client

    async def fake_get_secret(name, *a, **k):
        if name == "kie_ai_api_key":
            return "fake-kie-key"
        return None

    import kie_unified
    import vault
    monkeypatch.setattr(kie_unified, "get_text_client_for_tenant",
                        fake_get_text_client_for_tenant)
    monkeypatch.setattr(vault, "get_secret", fake_get_secret)
    monkeypatch.setattr(static_docu, "fetch_one", fake_fetch_one)
    monkeypatch.setattr(static_docu, "fetch_all", fake_fetch_all)
    monkeypatch.setattr(static_docu, "execute", fake_execute)

    _install_generation_stop(monkeypatch)

    return db_rows, calls


@pytest.mark.asyncio
async def test_roster_photo_used_as_reference_no_web_hunt(monkeypatch):
    """(a) The primary regression test: a roster machine ALREADY has a
    verified photo (static_reference_cache, keyed on the roster's own
    compound display name) but this scene's own LLM-derived label ("HMS
    Ruler") misses that exact key — LAYER 0's direct lookup. The roster
    layer must resolve the scene to the Ruler roster entry, reuse its
    ALREADY-hosted photo (no _host_reference re-fetch — it's already on our
    storage), run it through _vision_confirms (trusted_source=True), and
    never touch the web-hunt functions at all."""
    video_id = str(uuid.uuid4())
    tenant_id = str(uuid.uuid4())
    roster = [_ATTACKER, _RULER, _UNICORN]
    video_row = _video_row(video_id, roster)
    ruler_mkey = _cache_key_for(_RULER)
    scene_mkey = static_docu._machine_key("HMS Ruler")
    assert ruler_mkey != scene_mkey, "test is only meaningful if the keys differ"

    cache_rows = {
        ruler_mkey: {
            "hosted_url": "https://storage.example/roster_ruler.jpg",
            "source_url": "https://en.wikipedia.org/wiki/Ruler-class_escort_carrier",
        },
    }

    db_rows, calls = _install_common_fakes(
        monkeypatch, video_row,
        scene_text=(
            "roughly twenty-three Bogue-class hulls were transferred to the "
            "Royal Navy under Lend-Lease and reclassified as the Ruler "
            "class. HMS Ruler herself began as a mercantile hull."
        ),
        machine="HMS Ruler",
        cache_rows=cache_rows,
        fail_on_web_hunt=True,
    )

    result = await static_docu.generate_static_images_for_video(video_id, tenant_id)

    # LAYER 0 (the scene's own key) tried and missed FIRST, LAYER 0b (the
    # roster's key, resolved to the Ruler entry alone — never Attacker's)
    # tried and hit SECOND. Exactly these two lookups, in this order — no
    # redundant or out-of-order cache reads.
    assert calls["cache_lookups"] == [scene_mkey, ruler_mkey]

    # The roster's ALREADY-hosted photo is reused directly — never re-fetched.
    assert calls["host_reference"] == []

    # Exactly one vision check, against the roster's cached photo, trusted.
    assert len(calls["vision_confirms"]) == 1
    vc = calls["vision_confirms"][0]
    assert vc["image_url"] == "https://storage.example/roster_ruler.jpg"
    assert vc["trusted_source"] is True
    assert vc["machine"] == "HMS Ruler"

    # Never even looked at the Attacker entry's cache row.
    attacker_mkey = _cache_key_for(_ATTACKER)
    assert attacker_mkey not in calls["cache_lookups"]

    # The resolved photo is now ALSO cached under the scene's own key, for
    # a faster LAYER-0 hit on any future re-run of this exact scene.
    scene_writes = [c for c in calls["cache_writes"] if c[1] == scene_mkey]
    assert len(scene_writes) == 1
    assert scene_writes[0][3] == "https://storage.example/roster_ruler.jpg"

    # Reference resolution succeeded — the run only stops later, at the
    # budget-cap stub every view hits well past the reference gate, so the
    # top-level result is still "failed" (no view was ever actually
    # rendered) but for a COMPLETELY different, unrelated reason than a
    # missing reference: every asset row must show budget_capped, never
    # blocked_no_reference, and every row's drive_image_url must be the
    # roster's own hosted photo.
    assert result["status"] == "failed"
    assert db_rows["assets"], "expected at least one asset row"
    for row in db_rows["assets"].values():
        assert row["status"] == "budget_capped"
        assert row["status"] != "blocked_no_reference"
        assert row["drive_image_url"] == "https://storage.example/roster_ruler.jpg"


@pytest.mark.asyncio
async def test_scene22_shape_reuses_roster_photo_end_to_end(monkeypatch):
    """G24b end-to-end: the exact scene-22 live shape ('Ruler-class Escort
    Carrier', shared word 'escort' overlapping both Lend-Lease siblings)
    must now flow through LAYER 0b — resolve to the Ruler entry alone, reuse
    its cached verified photo, pass it through _vision_confirms, and never
    touch the web hunt. Before this fix the resolver returned None here and
    the scene fell through to a web hunt it didn't need (live: to
    blocked_no_reference, dodged only by hand-seeding alias cache keys)."""
    video_id = str(uuid.uuid4())
    tenant_id = str(uuid.uuid4())
    roster = [_ACTIVITY, _ATTACKER, _RULER, _UNICORN]
    video_row = _video_row(video_id, roster)
    ruler_mkey = _cache_key_for(_RULER)
    scene_mkey = static_docu._machine_key("Ruler-class Escort Carrier")
    assert ruler_mkey != scene_mkey

    cache_rows = {
        ruler_mkey: {
            "hosted_url": "https://storage.example/roster_ruler.jpg",
            "source_url": "https://en.wikipedia.org/wiki/Ruler-class_escort_carrier",
        },
    }

    db_rows, calls = _install_common_fakes(
        monkeypatch, video_row,
        scene_text=(
            "The Ruler class was the largest single group of escort "
            "carriers in Royal Navy service, twenty-three Casablanca-type "
            "hulls transferred under Lend-Lease."
        ),
        machine="Ruler-class Escort Carrier",
        cache_rows=cache_rows,
        fail_on_web_hunt=True,
    )

    result = await static_docu.generate_static_images_for_video(video_id, tenant_id)

    assert calls["cache_lookups"] == [scene_mkey, ruler_mkey]
    assert calls["host_reference"] == []
    assert len(calls["vision_confirms"]) == 1
    vc = calls["vision_confirms"][0]
    assert vc["image_url"] == "https://storage.example/roster_ruler.jpg"
    assert vc["trusted_source"] is True
    assert result["status"] == "failed"  # budget-cap stub, well past the reference gate
    for row in db_rows["assets"].values():
        assert row["status"] == "budget_capped"
        assert row["drive_image_url"] == "https://storage.example/roster_ruler.jpg"


@pytest.mark.asyncio
async def test_roster_entry_matched_never_built_uses_verified_design_reference(
    monkeypatch,
):
    """(b) UPDATED (2026-08-04, Ryan's decision): a roster entry resolves
    unambiguously (no collision here — a single CVA-01 entry with no
    lookalike sibling in this roster) and is classified never_built
    (pipeline_executor._roster_entry_never_built) — this used to mean the
    scene stayed permanently blocked_no_reference, because
    prefetch_roster_references never even attempts a photo lookup for a
    never-built machine and the ordinary web hunt (Wikipedia/Commons) can
    never find one either. Route it to the verified-design reconstruction path
    instead of blocking it — the ENTIRE reference hunt (LAYER 0/0b/1/2 and
    the web hunt) is skipped outright, never even attempted, and the scene
    proceeds straight to blueprint generation. This test proves the skip:
    the web-hunt fakes are wired to raise if ever called
    (fail_on_web_hunt=True), and generation stops cleanly at the same
    budget-cap stub every other test in this file uses to observe the
    reference-resolution outcome without needing to mock image generation."""
    video_id = str(uuid.uuid4())
    tenant_id = str(uuid.uuid4())
    roster = [_CVA01_CLASS, {"name": "Boeing XB-15"}, {"name": "Northrop XB-35"}]
    video_row = _video_row(video_id, roster)

    db_rows, calls = _install_common_fakes(
        monkeypatch, video_row,
        scene_text=(
            "The staff requirement for the class was drawn up early. CVA-01 "
            "would have been the first of a two-ship class replacing the "
            "World War Two fleet carriers, with a catapult system."
        ),
        machine="CVA-01",
        cache_rows={
            static_docu._machine_key("CVA-01"): {
                "hosted_url": "https://storage.example/cva01-design.png",
                "source_url": "https://source.example/cva01-three-view.png",
                "reference_kind": "design",
            },
        },
        fail_on_web_hunt=True,  # the web hunt must never even run for this scene
    )

    result = await static_docu.generate_static_images_for_video(video_id, tenant_id)

    assert calls["host_reference"] == []  # nothing ever hosted
    assert calls["vision_confirms"] == []  # nothing ever reached vision — no reference hunt at all
    assert calls["cache_queries"] == [
        ("photo", static_docu._machine_key("CVA-01")),
        ("photo", _cache_key_for(_CVA01_CLASS)),
        ("design", static_docu._machine_key("CVA-01")),
    ]
    # The run only stops at the SAME budget-cap stub every other test here
    # uses — reference resolution is not the reason it stopped.
    assert result["status"] == "failed"
    assert db_rows["assets"], "expected asset rows for all reconstruction views"
    for row in db_rows["assets"].values():
        assert row["status"] == "budget_capped"
        assert row["status"] != "blocked_no_reference"
        assert row["drive_image_url"] == "https://storage.example/cva01-design.png"


@pytest.mark.asyncio
async def test_roster_layer_falls_through_to_web_hunt_when_no_roster_match(monkeypatch):
    """A scene whose machine guess matches NO roster entry at all (e.g. the
    subject-planner mis-fired) must still fall through to the ordinary web
    hunt — the roster layer is additive, never a replacement for it."""
    video_id = str(uuid.uuid4())
    tenant_id = str(uuid.uuid4())
    roster = [_ATTACKER, _RULER, _UNICORN]
    video_row = _video_row(video_id, roster)

    cache_rows = {
        _cache_key_for(_RULER): {
            "hosted_url": "https://storage.example/roster_ruler.jpg",
            "source_url": "https://en.wikipedia.org/wiki/Ruler-class_escort_carrier",
        },
    }

    db_rows, calls = _install_common_fakes(
        monkeypatch, video_row,
        scene_text="A completely unrelated aircraft never mentioned in the roster.",
        machine="Supermarine Spitfire",
        cache_rows=cache_rows,
        fail_on_web_hunt=False,
    )

    result = await static_docu.generate_static_images_for_video(video_id, tenant_id)

    # The web hunt (empty fakes) ran, found nothing -> correctly blocked.
    assert result["status"] == "failed"
    row = next(iter(db_rows["assets"].values()))
    assert row["status"] == "blocked_no_reference"
    # Never borrowed the Ruler roster photo for an unrelated aircraft.
    assert calls["vision_confirms"] == []
