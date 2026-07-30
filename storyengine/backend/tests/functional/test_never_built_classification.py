"""Tests for chunk C5 (2026-07-29): never-built roster detection.

WHY THIS EXISTS: some static-docu roster entries are cancelled programs or
paper projects that were NEVER PHYSICALLY COMPLETED — no photograph can
ever exist because no hardware was ever built. The live example is
"CVA-01 class", the British carrier programme cancelled in 1966 before
being laid down. Before this chunk it sat in the exact same "missing,
paste a URL" bucket as a machine that just needs another search attempt —
misleading, because no amount of retrying will ever find CVA-01 a photo.

This adds:
  - pipeline_executor._roster_entry_never_built: a conservative,
    structured-data-only classifier over a roster item's `status` +
    `built_count` fields.
  - pipeline_executor._roster_status_built_count_contradicts: the soft
    repair-warning half (contract-triangle law) for a data inconsistency
    (status says "cancelled" but built_count asserts real hardware).
  - pipeline_executor._machine_documentary_hold_roster_entries now carries
    a `never_built` bool per entry (additive).
  - static_docu.prefetch_roster_references now classifies BEFORE attempting
    any lookup, so a never-built machine never triggers a Wikimedia search
    or a paid vision call — it records REASON_NEVER_BUILT directly.

CONSERVATIVE BY DESIGN: a false "never built" verdict is worse than a
missed one (it permanently suppresses the retry affordance for a machine
whose photo may genuinely be findable). The rule requires the bare, exact
word "cancelled" for `status` — not "cancelled-built", not "built-
prototype", not anything that merely contains "cancelled" as a substring —
and refuses to classify if `built_count` contradicts it.

No network calls. Every external lookup is monkeypatched.

Run:
    cd storyengine/backend && ./venv/bin/python -m pytest \
        tests/functional/test_never_built_classification.py -q
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

_THIS_DIR = os.path.dirname(os.path.abspath(__file__))
if _THIS_DIR not in sys.path:
    sys.path.insert(0, _THIS_DIR)

import pipeline_executor as pe  # noqa: E402
import static_docu as sd  # noqa: E402

# The real, frozen 23-entry British-carrier roster shape lives in the
# protected characterization-test file — imported read-only, never edited.
from test_ship_roster_shapes import (  # noqa: E402
    SHIP_ROSTER_ENTRIES,
    SHIP_TITLE,
)


# ---------------------------------------------------------------------------
# The real 23-entry British-carrier roster, enriched with status/built_count
# (SHIP_ROSTER_ENTRIES itself carries neither field — those were added to
# the schema by this chunk's prompt work). name/designation are copied
# byte-identical from the frozen fixture; only status/built_count are new.
# Historically-grounded assignments; only CVA-01 (item 6) is the genuine
# paper cancellation the loop's "Why" section names as the live example.
# Item 8 (Audacious/Malta compound) is a deliberate trap: its status
# CONTAINS "cancelled" as a substring ("cancelled-built") but is not the
# bare word, and its built_count also carries "built" — it must NOT be
# classified as never-built even though part of the real history (the
# Malta class) genuinely was never built, because the other half
# (Audacious-class ships Eagle and Ark Royal) was.
# ---------------------------------------------------------------------------

_STATUS_BY_NAME = {
    "Courageous class": ("converted", "2 ships converted from battlecruisers"),
    "Ark Royal (1937)": ("production", "1 ship"),
    "Illustrious class": ("production", "4 ships"),
    "Attacker class (US-built)": ("production", "many ships (Lend-Lease, US-built)"),
    "Ruler class (US-built)": ("production", "many ships (Lend-Lease, US-built)"),
    "CVA-01 class": ("cancelled", None),  # the real example: no built_count field at all
    "Archer class / Empire Mac-Ship conversions": ("converted", "several ships converted"),
    "Audacious class / Malta class": (
        "cancelled-built",
        "2 ships built (Audacious class); Malta class cancelled, none built",
    ),
    "Pretoria Castle class": ("converted", "1 ship converted from a liner"),
    "Implacable class": ("production", "2 ships"),
    "Colossus class": ("production", "10 ships"),
    "Majestic class": ("production", "6 ships"),
    "Centaur class": ("production", "4 ships"),
    "Eagle (1946)": ("production", "1 ship"),
    "Ark Royal (1955)": ("production", "1 ship"),
    "Hermes (1959)": ("production", "1 ship"),
    "Invincible class": ("production", "3 ships"),
    "Queen Elizabeth class (modern)": ("production", "2 ships"),
    "Unicorn (maintenance carrier)": ("special-purpose", "1 ship"),
    "Argus (1918)": ("converted", "1 ship converted from an ocean liner hull"),
    "Furious (1917)": ("converted", "1 ship converted from a large light cruiser"),
    "Nairana class": ("production", "4 ships (escort carriers)"),
    "Vindictive (1918)": ("converted", "1 ship converted from a cruiser"),
}


def _enriched_ship_roster():
    assert set(_STATUS_BY_NAME) == {e["name"] for e in SHIP_ROSTER_ENTRIES}, (
        "status/built_count table has drifted out of sync with the frozen "
        "23-entry SHIP_ROSTER_ENTRIES fixture"
    )
    enriched = []
    for entry in SHIP_ROSTER_ENTRIES:
        status, built_count = _STATUS_BY_NAME[entry["name"]]
        item = dict(entry)
        item["status"] = status
        if built_count is not None:
            item["built_count"] = built_count
        enriched.append(item)
    return enriched


# ---------------------------------------------------------------------------
# 1. The real 23-entry roster: verdict table. CVA-01 caught, all 22 others
#    refused.
# ---------------------------------------------------------------------------

def test_never_built_verdict_table_over_real_23_ship_roster():
    roster = _enriched_ship_roster()
    assert len(roster) == 23

    verdicts = {item["name"]: pe._roster_entry_never_built(item) for item in roster}

    never_built_names = [name for name, verdict in verdicts.items() if verdict]
    assert never_built_names == ["CVA-01 class"], (
        f"Expected ONLY CVA-01 class to classify as never-built; got {never_built_names}. "
        "Verdict table:\n" + "\n".join(f"  {name!r}: {v}" for name, v in verdicts.items())
    )

    # Every other entry, including the "cancelled-built" trap compound
    # entry, must be refused.
    for name, verdict in verdicts.items():
        if name == "CVA-01 class":
            continue
        assert verdict is False, f"{name!r} was wrongly classified never-built"

    # The trap entry specifically: status CONTAINS "cancelled" as a
    # substring but is not the bare word — must be refused.
    audacious_malta = next(e for e in roster if e["name"] == "Audacious class / Malta class")
    assert audacious_malta["status"] == "cancelled-built"
    assert pe._roster_entry_never_built(audacious_malta) is False


def test_never_built_verdict_table_via_roster_entries_accessor():
    """Same table, exercised through the real accessor
    (_machine_documentary_hold_roster_entries) the prefetch sweep actually
    calls — proves the `never_built` key is wired end to end, not just
    reachable by calling the classifier directly."""
    video = {
        "id": "ship-vid-1",
        "render_mode": "static_docu",
        "research_payload": {
            "documentary_style": "designed_vs_used",
            "unit_roster": _enriched_ship_roster(),
        },
    }
    entries = pe._machine_documentary_hold_roster_entries(video)
    assert len(entries) == 23
    never_built_names = [e["name"] for e in entries if e["never_built"]]
    # The accessor's "name" is the glued display string (designation + bare
    # name — see pipeline_executor._unit_display_name), not the bare
    # roster-item "name" field.
    assert never_built_names == ["CVA-01 Queen Elizabeth class (1960s design) CVA-01 class"]


# ---------------------------------------------------------------------------
# 2. Aircraft-shaped entries, including the most important negative case:
#    a cancelled-but-flown prototype (XB-70 Valkyrie style) must NOT be
#    classified as never-built.
# ---------------------------------------------------------------------------

AIRCRAFT_STATUS_ROSTER = [
    {
        "name": "XB-70 Valkyrie",
        "designation": "North American XB-70",
        "status": "cancelled-built",
        "built_count": "2 prototypes built and flown",
    },
    {
        "name": "Avro Arrow",
        "designation": "Avro CF-105",
        "status": "built-prototype",
        "built_count": "5-6 prototypes built and flown, program cancelled 1959",
    },
    {
        "name": "TSR-2",
        "designation": "BAC TSR-2",
        "status": "cancelled-built",
        "built_count": "1 prototype built and flown, several more airframes in build",
    },
    {
        "name": "Boeing B-52",
        "designation": "B-52",
        "status": "production",
        "built_count": "744 aircraft",
    },
    # A genuine paper-only cancellation for contrast: real decisive positive.
    {
        "name": "Paperhawk Interceptor",
        "designation": "XF-99 Paperhawk",
        "status": "cancelled",
    },
    # Contradiction trap: bare "cancelled" but built_count says otherwise —
    # must be refused (data inconsistency, not evidence).
    {
        "name": "Contradictory Bomber",
        "designation": "XB-00",
        "status": "cancelled",
        "built_count": "3 aircraft built before the program was cancelled",
    },
    # Missing status entirely — must be refused (never guess from absence).
    {
        "name": "No-Status Fighter",
        "designation": "YF-00",
    },
]


def test_cancelled_but_flown_prototype_is_never_classified_never_built():
    """THE MOST IMPORTANT NEGATIVE CASE: a cancelled programme whose
    prototypes were actually built and flown (XB-70 Valkyrie shape) has
    real photographs and must never be told otherwise."""
    for name in ("XB-70 Valkyrie", "Avro Arrow", "TSR-2"):
        item = next(e for e in AIRCRAFT_STATUS_ROSTER if e["name"] == name)
        assert pe._roster_entry_never_built(item) is False, (
            f"{name} was wrongly classified never-built — it has status "
            f"{item['status']!r} and built_count {item.get('built_count')!r}, "
            "a cancelled-but-BUILT programme with real photographs."
        )


def test_aircraft_roster_verdict_table():
    verdicts = {item["name"]: pe._roster_entry_never_built(item) for item in AIRCRAFT_STATUS_ROSTER}
    assert verdicts == {
        "XB-70 Valkyrie": False,
        "Avro Arrow": False,
        "TSR-2": False,
        "Boeing B-52": False,
        "Paperhawk Interceptor": True,
        "Contradictory Bomber": False,
        "No-Status Fighter": False,
    }, verdicts


# ---------------------------------------------------------------------------
# 3. Non-dict / string roster items (older roster shape, or a fixture with
#    no status field) must always refuse — there is nothing to classify.
# ---------------------------------------------------------------------------

def test_string_roster_item_never_classified():
    assert pe._roster_entry_never_built("Boeing XB-15") is False
    assert pe._roster_entry_never_built(None) is False
    assert pe._roster_entry_never_built({}) is False


# ---------------------------------------------------------------------------
# 4. _roster_status_built_count_contradicts: the soft repair-warning half.
# ---------------------------------------------------------------------------

def test_contradiction_helper_mirrors_the_classifiers_refusal():
    contradictory = {"status": "cancelled", "built_count": "3 aircraft built"}
    clean_cancelled = {"status": "cancelled"}
    cancelled_built = {"status": "cancelled-built", "built_count": "2 built"}

    assert pe._roster_status_built_count_contradicts(contradictory) is True
    assert pe._roster_entry_never_built(contradictory) is False

    assert pe._roster_status_built_count_contradicts(clean_cancelled) is False
    assert pe._roster_entry_never_built(clean_cancelled) is True

    # "cancelled-built" is not bare "cancelled" — not a contradiction case,
    # it's simply a different (correct) status value.
    assert pe._roster_status_built_count_contradicts(cancelled_built) is False


def test_roster_validation_flags_contradiction_as_soft_not_hard():
    """A status/built_count contradiction must surface as a SOFT warning
    (needs_review) — it must never block the video from advancing, since
    the classifier itself already refuses to act on the bad data; this is
    visibility for the next repair pass, not a new hard gate."""
    payload = {
        "unit_roster": [
            {"name": "Contradictory Bomber", "designation": "XB-00",
             "status": "cancelled", "built_count": "3 aircraft built before cancellation"},
            {"name": "Clean Cancelled", "designation": "XB-01", "status": "cancelled"},
        ],
        "machine_discovery_buckets": {"core_roster": [{"name": "x"}] * 20},
        "recommended_final_roster": ["Contradictory Bomber", "Clean Cancelled"],
        "gap_hunt_matrix": [{"candidate": "x"}],
        "edge_case_matrix": [{"edge_case_class": "x"}],
    }
    result = pe._roster_validation("Some Non-Complete-Title Video", payload)
    joined = " ".join(result["warnings"]).lower()
    assert "contradictory bomber" in joined
    assert "cancelled" in joined
    assert "clean cancelled" not in joined  # only the contradictory one is named
    soft_joined = " ".join(result["soft_warnings"]).lower()
    assert "contradictory bomber" in soft_joined
    hard_joined = " ".join(result["hard_warnings"]).lower()
    assert "contradictory bomber" not in hard_joined
    assert result["needs_review"] is True


def test_roster_validation_silent_when_no_contradiction():
    payload = {
        "unit_roster": [
            {"name": "Clean Cancelled", "designation": "XB-01", "status": "cancelled"},
            {"name": "Clean Built", "designation": "XB-02", "status": "production",
             "built_count": "10 aircraft"},
        ],
    }
    result = pe._roster_validation("A Small Video", payload)
    joined = " ".join(result["warnings"]).lower()
    assert "built_count asserts real hardware" not in joined


# ---------------------------------------------------------------------------
# 5. static_docu.prefetch_roster_references: a never-built machine must be
#    classified BEFORE any lookup — no candidate-gather, no hosting, no
#    vision call — and recorded with REASON_NEVER_BUILT.
# ---------------------------------------------------------------------------

def _video_row(video_id, roster):
    return {
        "id": video_id,
        "render_mode": "static_docu",
        "research_payload": {
            "documentary_style": "designed_vs_used",
            "unit_roster": roster,
        },
    }


@pytest.mark.asyncio
async def test_never_built_machine_skips_the_entire_lookup_chain(monkeypatch):
    video_id, tenant_id = str(uuid.uuid4()), str(uuid.uuid4())
    roster = [
        {"name": "Boeing XB-15", "designation": "XB-15", "status": "production", "built_count": "1"},
        {"name": "Northrop XB-35", "designation": "XB-35", "status": "production", "built_count": "2"},
        {"name": "CVA-01 class",
         "designation": "CVA-01 Queen Elizabeth class (1960s design)",
         "status": "cancelled"},
    ]
    video_row = _video_row(video_id, roster)

    gather_calls = []
    miss_writes = []

    async def fake_fetch_one(query, *args):
        if "FROM videos" in query:
            return dict(video_row)
        if "FROM static_reference_cache" in query:
            return None  # nothing cached for any machine
        return None

    async def fake_execute(query, *args):
        if "INSERT INTO static_reference_misses" in query:
            miss_writes.append(args)
        return None

    async def fake_gather(machine_arg, aliases, query):
        gather_calls.append(machine_arg)
        return []  # the other two miss too, for symmetry — irrelevant to the assertion

    monkeypatch.setattr(sd, "fetch_one", fake_fetch_one)
    monkeypatch.setattr(sd, "execute", fake_execute)
    monkeypatch.setattr(sd, "_gather_reference_candidates", fake_gather)

    result = await sd.prefetch_roster_references(video_id, tenant_id)

    assert result["status"] == "completed"
    assert result["roster_count"] == 3
    assert result["never_built"] == 1
    assert result["missed"] == 2  # the other two ran a real (if empty) search attempt
    assert result["verified"] == 0

    # THE MONEY ASSERTION: _gather_reference_candidates (and therefore the
    # whole hosting/vision chain downstream of it) must NEVER be called for
    # CVA-01 — this is the "saves money" half of the design.
    assert gather_calls == ["Boeing XB-15", "Northrop XB-35"], (
        "CVA-01 must never reach the candidate-gather step once classified "
        f"never-built; calls were: {gather_calls}"
    )

    never_built_writes = [w for w in miss_writes if w[4] == sd.REASON_NEVER_BUILT]
    assert len(never_built_writes) == 1
    tenant_arg, video_arg, mkey_arg, machine_arg, reason_arg, detail_arg = never_built_writes[0]
    assert tenant_arg == tenant_id
    assert video_arg == video_id
    assert machine_arg.startswith("CVA-01")
    assert "never" in detail_arg.lower() and "built" in detail_arg.lower()


@pytest.mark.asyncio
async def test_cached_photo_wins_over_never_built_classification(monkeypatch):
    """If a machine somehow already has a verified reference cached (e.g. an
    operator manually seeded a photo, or the classification is simply
    wrong for this tenant), the cache hit must win — never_built is only
    consulted for a machine with NO existing verified reference."""
    video_id, tenant_id = str(uuid.uuid4()), str(uuid.uuid4())
    roster = [
        {"name": "CVA-01 class",
         "designation": "CVA-01 Queen Elizabeth class (1960s design)",
         "status": "cancelled"},
        {"name": "Boeing XB-15", "designation": "XB-15", "status": "production", "built_count": "1"},
        {"name": "Northrop XB-35", "designation": "XB-35", "status": "production", "built_count": "2"},
    ]
    video_row = _video_row(video_id, roster)

    gather_calls = []
    miss_writes = []

    async def fake_fetch_one(query, *args):
        if "FROM videos" in query:
            return dict(video_row)
        if "FROM static_reference_cache" in query:
            if args and args[-1] == sd._machine_key(
                "CVA-01 Queen Elizabeth class (1960s design) CVA-01 class"
            ):
                return {"hosted_url": "https://storage.example/manually-seeded-cva01.jpg"}
            return None  # the other two are unrelated to this assertion
        return None

    async def fake_execute(query, *args):
        if "DELETE FROM static_reference_misses" in query:
            miss_writes.append(("delete", args))
        if "INSERT INTO static_reference_misses" in query:
            miss_writes.append(("insert", args))
        return None

    async def fake_gather(machine_arg, aliases, query):
        gather_calls.append(machine_arg)
        return []

    monkeypatch.setattr(sd, "fetch_one", fake_fetch_one)
    monkeypatch.setattr(sd, "execute", fake_execute)
    monkeypatch.setattr(sd, "_gather_reference_candidates", fake_gather)

    result = await sd.prefetch_roster_references(video_id, tenant_id)

    assert result["verified"] == 1  # CVA-01, from the cache — not the classifier
    assert result["never_built"] == 0, (
        "the cache hit must short-circuit BEFORE the never_built check, so a "
        "cached machine is never counted as a never_built skip"
    )
    cva01_name = "CVA-01 Queen Elizabeth class (1960s design) CVA-01 class"
    assert cva01_name not in gather_calls, "cached machine must never reach the candidate-gather step"
    cva01_key = sd._machine_key(cva01_name)
    assert ("delete", (tenant_id, video_id, cva01_key)) in miss_writes


# ---------------------------------------------------------------------------
# 6. roster_repair_dashboard end-to-end: a never_built miss row must
#    surface retryable=False (pre-existing C8 wiring — this proves it now
#    receives a REAL never_built row, not just a hand-fed test fixture).
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_dashboard_marks_never_built_machine_not_retryable(monkeypatch):
    tenant_id, video_id = str(uuid.uuid4()), str(uuid.uuid4())
    roster = [
        "Boeing XB-15",
        "Northrop XB-35",
        "CVA-01 Queen Elizabeth class (1960s design) CVA-01 class",
    ]
    video_row = {
        "id": video_id,
        "tenant_id": tenant_id,
        "render_mode": "static_docu",
        "research_payload": {"documentary_style": "designed_vs_used", "unit_roster": roster},
    }
    executor = pe.PipelineExecutor(tenant_id)

    async def fake_ensure_initialized():
        return None

    async def fake_get_video(vid):
        return dict(video_row)

    async def fake_load_cards(vid, payload, roster=None, target_machine=None):
        return payload

    monkeypatch.setattr(executor, "_ensure_initialized", fake_ensure_initialized)
    monkeypatch.setattr(executor, "_get_video", fake_get_video)
    monkeypatch.setattr(executor, "_load_machine_research_cards", fake_load_cards)

    cva01_key = sd._machine_key("CVA-01 Queen Elizabeth class (1960s design) CVA-01 class")

    async def fake_fetch_all(query, *args):
        if "FROM machine_research_cards" in query:
            return []
        if "FROM static_reference_cache" in query:
            return []
        if "FROM static_reference_misses" in query:
            return [{"machine_key": cva01_key, "reason_code": sd.REASON_NEVER_BUILT,
                     "reason_detail": "This machine was never actually built — no photo can ever exist."}]
        return []

    monkeypatch.setattr(pe, "fetch_all", fake_fetch_all)

    result = await executor.roster_repair_dashboard(video_id)
    units_by_machine = {u["machine"]: u for u in result["units"]}
    cva01_unit = units_by_machine["CVA-01 Queen Elizabeth class (1960s design) CVA-01 class"]
    assert cva01_unit["reference"]["status"] == "missing"
    assert cva01_unit["reference"]["reason_code"] == "never_built"
    assert cva01_unit["reference"]["retryable"] is False
