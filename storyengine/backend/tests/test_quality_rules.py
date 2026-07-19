"""Pure-module unit tests for quality_rules.py (checklist C46b).

Covers the parts that need no DB and no live Claude call:
  - resolve_video_shape / rule_matches / active_rules_for_video: the
    deterministic scope-resolution matrix Ryan's 2026-07-19 ruling requires
    (applies_to resolved from VIDEO DATA, never LLM judgment about which
    gates apply).
  - compose_rules_text: severity-tagged text + the severity_by_rule map that
    reaches script_quality's blocking logic.
  - script_quality._apply_rule_severity: the deterministic hard-gate
    enforcement that consumes that map.
  - parse_markdown_table: round-trips a REAL excerpt copied verbatim from
    storyengine/notes/dvsu-quality-law.md.
  - suggest_applies_to: the ingestion-time keyword heuristic (distinct from,
    never a substitute for, active_rules_for_video's runtime resolution).
  - CRUD functions never get called by the parser (confirm-before-insert is
    proven at the wiring layer in
    tests/functional/test_c46b_quality_rules_wiring.py; this file proves the
    parser itself carries no DB import path that could accidentally fire).

Local/no-spend: llm_parse_rules_prose tests use a fake client, never a real
API call.
"""

import asyncio

import quality_rules as qr
import script_quality


# ---------------------------------------------------------------------------
# resolve_video_shape / rule_matches / active_rules_for_video — scope matrix
# ---------------------------------------------------------------------------

def _rule(rule_id, applies_to, severity="warn"):
    return {"rule_id": rule_id, "law": f"law {rule_id}", "evidence": None,
            "severity": severity, "applies_to": applies_to}


def test_research_video_shape_true_when_not_skipped_and_plan_includes_it():
    video = {"research_skipped": False, "pipeline_stages": None}
    shape = qr.resolve_video_shape(video)
    assert shape["research"] is True
    assert shape["all"] is True


def test_research_video_shape_false_when_skipped():
    video = {"research_skipped": True, "pipeline_stages": None}
    assert qr.resolve_video_shape(video)["research"] is False


def test_research_video_shape_false_when_plan_excludes_research():
    video = {"research_skipped": False, "pipeline_stages": ["script", "voice"]}
    assert qr.resolve_video_shape(video)["research"] is False


def test_story_shape_true_for_static_docu_render_mode():
    video = {"render_mode": "static_docu"}
    assert qr.resolve_video_shape(video)["story"] is True


def test_story_shape_false_for_non_static_docu():
    video = {"render_mode": None}
    assert qr.resolve_video_shape(video)["story"] is False


def test_animated_and_realistic_shape_from_render_style():
    assert qr.resolve_video_shape({"render_style": "animated"})["animated"] is True
    assert qr.resolve_video_shape({"render_style": "animated"})["realistic"] is False
    assert qr.resolve_video_shape({"render_style": "realistic"})["realistic"] is True


def test_research_only_rule_fires_on_research_video_not_story_video():
    research_video = {"research_skipped": False, "pipeline_stages": None, "render_mode": None}
    story_video = {"research_skipped": True, "render_mode": "static_docu"}
    rule = _rule("QL-18", {"research": True})

    assert qr.active_rules_for_video(research_video, [rule]) == [rule]
    assert qr.active_rules_for_video(story_video, [rule]) == []


def test_story_only_rule_fires_on_story_video_not_research_video():
    research_video = {"research_skipped": False, "pipeline_stages": None, "render_mode": None}
    story_video = {"research_skipped": True, "render_mode": "static_docu"}
    rule = _rule("QL-3", {"story": True})

    assert qr.active_rules_for_video(story_video, [rule]) == [rule]
    assert qr.active_rules_for_video(research_video, [rule]) == []


def test_all_scope_rule_always_matches():
    rule = _rule("QL-12", {"all": True})
    assert qr.active_rules_for_video({}, [rule]) == [rule]
    assert qr.active_rules_for_video({"render_mode": "static_docu", "research_skipped": False}, [rule]) == [rule]


def test_hybrid_research_and_story_video_matches_both_scoped_rules():
    hybrid = {"research_skipped": False, "pipeline_stages": None, "render_mode": "static_docu"}
    research_rule = _rule("QL-18", {"research": True})
    story_rule = _rule("QL-3", {"story": True})
    animated_rule = _rule("X-1", {"animated": True})

    matched = qr.active_rules_for_video(hybrid, [research_rule, story_rule, animated_rule])
    assert matched == [research_rule, story_rule]


def test_unknown_scope_key_is_skipped_logged_never_crashes(caplog):
    rule = _rule("Z-1", {"reserach": True})  # typo'd key
    with caplog.at_level("WARNING"):
        matched = qr.active_rules_for_video({"research_skipped": False}, [rule])
    assert matched == []
    assert any("unrecognized applies_to" in r.message for r in caplog.records)


def test_unknown_key_alongside_known_false_key_still_never_matches():
    rule = _rule("Z-2", {"reserach": True, "story": False})
    matched = qr.active_rules_for_video({"render_mode": "static_docu"}, [rule])
    assert matched == []


def test_channel_format_scope_matches_case_insensitively_when_supplied():
    rule = _rule("CF-1", {"channel_format": "Documentary"})
    matched = qr.active_rules_for_video({}, [rule], channel_format_value="documentary")
    assert matched == [rule]
    assert qr.active_rules_for_video({}, [rule], channel_format_value="dialogue") == []
    assert qr.active_rules_for_video({}, [rule]) == []  # no value supplied -> never matches


def test_rule_with_string_applies_to_json_is_coerced():
    # asyncpg hands jsonb columns back as raw JSON text by default.
    rule = {"rule_id": "QL-1", "law": "x", "evidence": None, "severity": "warn",
            "applies_to": '{"all": true}'}
    assert qr.active_rules_for_video({}, [rule]) == [rule]


def test_empty_or_garbage_applies_to_never_matches():
    assert qr.rule_matches({}, {"all": True}) is False
    assert qr.rule_matches(None, {"all": True}) is False
    assert qr.rule_matches("not json", {"all": True}) is False


# ---------------------------------------------------------------------------
# compose_rules_text — severity tagging
# ---------------------------------------------------------------------------

def test_compose_rules_text_empty_list_is_backward_compatible_empty():
    text, severities = qr.compose_rules_text([])
    assert text == ""
    assert severities == {}


def test_compose_rules_text_tags_each_rule_with_id_and_severity():
    rules = [
        _rule("QL-12", {"all": True}, severity="hard_gate"),
        _rule("QL-7", {"all": True}, severity="warn"),
        _rule("QL-2", {"all": True}, severity="guidance"),
    ]
    text, severities = qr.compose_rules_text(rules)
    assert "[QL-12] [HARD-GATE]" in text
    assert "[QL-7] [WARN]" in text
    assert "[QL-2] [GUIDANCE]" in text
    assert severities == {"QL-12": "hard_gate", "QL-7": "warn", "QL-2": "guidance"}


def test_compose_rules_text_orders_hard_gate_first():
    rules = [
        _rule("QL-2", {"all": True}, severity="guidance"),
        _rule("QL-12", {"all": True}, severity="hard_gate"),
    ]
    text, _ = qr.compose_rules_text(rules)
    assert text.index("QL-12") < text.index("QL-2")


# ---------------------------------------------------------------------------
# script_quality._apply_rule_severity — severity reaches blocking logic
# ---------------------------------------------------------------------------

def test_hard_gate_failure_upgrades_pass_verdict_to_revise():
    result = script_quality.CritiqueResult(
        verdict="pass", score=95, failing_gates=[],
        rule_verdicts=[{"rule": "QL-12", "passed": False, "note": "hype word used"}],
    )
    out = script_quality._apply_rule_severity(result, {"QL-12": "hard_gate"})
    assert out.verdict == "revise"


def test_warn_failure_alone_never_upgrades_pass_verdict():
    result = script_quality.CritiqueResult(
        verdict="pass", score=95, failing_gates=[],
        rule_verdicts=[{"rule": "QL-7", "passed": False, "note": "too many name-openers"}],
    )
    out = script_quality._apply_rule_severity(result, {"QL-7": "warn"})
    assert out.verdict == "pass"


def test_no_severity_map_is_a_noop():
    result = script_quality.CritiqueResult(verdict="pass")
    out = script_quality._apply_rule_severity(result, None)
    assert out.verdict == "pass"


def test_critique_script_end_to_end_applies_severity(monkeypatch):
    """Full critique_script() call: the judge returns 'pass' overall but
    flags a hard-gate rule as failed in rule_verdicts — the deterministic
    enforcement must still upgrade the verdict to 'revise'."""
    import json as _json

    class FakeClient:
        async def generate(self, **kwargs):
            return _json.dumps({
                "verdict": "pass", "score": 92, "failing_gates": [],
                "rewrite_guidance": "",
                "rule_verdicts": [{"rule": "QL-12", "passed": False, "note": "hype word"}],
            })

    result = asyncio.run(script_quality.critique_script(
        "tenant-1", "video-1", {"script": "Some script text."},
        rules_text="[QL-12] [HARD-GATE] Ban thumbnail-hype adjectives.",
        severity_by_rule={"QL-12": "hard_gate"},
        client=FakeClient(),
    ))
    assert result.verdict == "revise"
    assert "QL-12" in result.failed_rule_names


# ---------------------------------------------------------------------------
# parse_markdown_table — round-trips a REAL dvsu-quality-law.md excerpt
# ---------------------------------------------------------------------------

_REAL_DVSU_EXCERPT = """
| ID | Law (testable) | Evidence (counts) | Triangle - B / R / G | Sev |
|---|---|---|---|---|
| QL-1 | Reject under 80 spoken words; warn 80-95; reject over 170. Hit the register median, not a fixed number: tight-production 85-105, spec-block naval 100-120, long-form (crew/sunk/never-built) 110-130; the folded-outro final entry may reach 160. | 369 entries: median 107, p25 95, p90 131; under 80 = 4% (15), under 90 = 17% (64). | B target the band for the register. R flag under-80. G reject under 80, warn 80-95, reject over 170. | hard-gate |
| QL-3 | Every entry runs on a designed-vs-used gap (built for X, used as Y). Absent only when the machine was used exactly as designed. | Present 93/104 labeled entries (89%). | B state the designed intent then invert to actual use. R "no gap and no substitute". G reject entries with neither a twist nor a substitute. | hard-gate |
| QL-7 | Cap bare name-openers ("The [Maker] [Designation]...") at about 57% (17 of 30). | 105 spec-block entries: name 57%, bridge 24%. | B vary the opener. R "Nth name-opener in a row". G warn if name-openers exceed 60%. | warn |
| QL-2 | Word count tracks narrative weight and position, not a flat target. | First-entry median 107. | B weight the budget by importance and position. R important-machine-thin. G flag a below-median count. | guidance |
"""


def test_parse_markdown_table_round_trips_real_dvsu_excerpt():
    rows = qr.parse_markdown_table(_REAL_DVSU_EXCERPT)
    ids = [r["rule_id"] for r in rows]
    assert ids == ["QL-1", "QL-3", "QL-7", "QL-2"]

    by_id = {r["rule_id"]: r for r in rows}
    assert by_id["QL-1"]["severity"] == "hard_gate"
    assert by_id["QL-7"]["severity"] == "warn"
    assert by_id["QL-2"]["severity"] == "guidance"
    assert "Reject under 80 spoken words" in by_id["QL-1"]["law"]
    assert "369 entries" in by_id["QL-1"]["evidence"]
    # Triangle (B/R/G) column is intentionally dropped, not stored.
    for r in rows:
        assert "triangle" not in r
        assert set(r.keys()) == {"rule_id", "law", "evidence", "severity", "applies_to"}


def test_parse_markdown_table_skips_header_and_separator_rows():
    rows = qr.parse_markdown_table(_REAL_DVSU_EXCERPT)
    assert all(r["rule_id"] != "ID" for r in rows)
    assert len(rows) == 4  # not 6 (header + separator excluded)


def test_parse_markdown_table_returns_empty_for_non_table_text():
    assert qr.parse_markdown_table("Just some prose. No pipes here.") == []


def test_suggest_applies_to_research_keywords():
    law = "Cross-reference in at least two independent sources before stating as fact."
    assert qr.suggest_applies_to(law) == {"research": True}


def test_suggest_applies_to_story_keywords():
    law = "Every entry ends on a sharpened verdict with a designed-vs-used twist."
    assert qr.suggest_applies_to(law)["story"] is True


def test_suggest_applies_to_defaults_to_all():
    assert qr.suggest_applies_to("Never use passive voice in the opening line.") == {"all": True}


def test_suggest_applies_to_both_research_and_story():
    law = "Cite two sources for the twist reveal in the verdict."
    tagged = qr.suggest_applies_to(law)
    assert tagged == {"research": True, "story": True}


# ---------------------------------------------------------------------------
# llm_parse_rules_prose — fallback for non-table docs (fake client, no spend)
# ---------------------------------------------------------------------------

class _FakeProseClient:
    def __init__(self, response):
        self.response = response
        self.calls = 0

    async def generate(self, **kwargs):
        self.calls += 1
        return self.response


def test_llm_parse_rules_prose_extracts_rows():
    import json as _json
    client = _FakeProseClient(_json.dumps({
        "rules": [
            {"rule_id": "R-1", "law": "Never use passive voice.", "evidence": None, "severity": "hard_gate"},
            {"rule_id": "R-2", "law": "Prefer short sentences.", "evidence": "reads better aloud", "severity": "guidance"},
        ]
    }))
    rows = asyncio.run(qr.llm_parse_rules_prose("Some rules doc as prose.", client))
    assert [r["rule_id"] for r in rows] == ["R-1", "R-2"]
    assert rows[0]["severity"] == "hard_gate"
    assert rows[1]["evidence"] == "reads better aloud"


def test_llm_parse_rules_prose_fails_open_to_empty_list_on_error():
    class _BoomClient:
        async def generate(self, **kwargs):
            raise RuntimeError("network blip")

    rows = asyncio.run(qr.llm_parse_rules_prose("text", _BoomClient()))
    assert rows == []


def test_parse_rules_document_prefers_table_over_llm_fallback():
    """A table-shaped doc never reaches the LLM path at all — deterministic,
    zero cost."""
    client = _FakeProseClient("should never be called")

    class _ForbiddenClient:
        async def generate(self, **kwargs):
            raise AssertionError("table-shaped input must not fall through to the LLM parser")

    rows = asyncio.run(qr.parse_rules_document(_REAL_DVSU_EXCERPT, client=_ForbiddenClient()))
    assert len(rows) == 4


def test_parse_rules_document_falls_back_to_llm_for_prose():
    import json as _json
    client = _FakeProseClient(_json.dumps({
        "rules": [{"rule_id": "R-1", "law": "Always cold open.", "evidence": None, "severity": "warn"}]
    }))
    rows = asyncio.run(qr.parse_rules_document("Always cold open. No intros.", client=client))
    assert rows and rows[0]["rule_id"] == "R-1"
    assert client.calls == 1


# ---------------------------------------------------------------------------
# CRUD — tenant-scoped (fake DB via monkeypatched module-level fetch_*)
# ---------------------------------------------------------------------------

def test_list_all_rules_is_tenant_scoped(monkeypatch):
    captured = {}

    async def fake_fetch_all(query, *args):
        captured["query"] = query
        captured["args"] = args
        return [{"id": "1", "rule_id": "QL-1", "law": "x", "evidence": None,
                  "severity": "warn", "applies_to": '{"all": true}',
                  "source": "seed", "active": True,
                  "created_at": None, "updated_at": None}]

    monkeypatch.setattr(qr, "fetch_all", fake_fetch_all)
    rows = asyncio.run(qr.list_all_rules("tenant-xyz"))
    assert captured["args"] == ("tenant-xyz",)
    assert "WHERE tenant_id = $1" in captured["query"]
    assert rows[0]["applies_to"] == {"all": True}  # decoded from string


def test_create_rule_upserts_on_conflict(monkeypatch):
    captured = {}

    async def fake_fetch_one(query, *args):
        captured["query"] = query
        captured["args"] = args
        return {"id": "1", "rule_id": args[1], "law": args[2], "evidence": args[3],
                "severity": args[4], "applies_to": args[5], "source": args[6],
                "active": True, "created_at": None, "updated_at": None}

    monkeypatch.setattr(qr, "fetch_one", fake_fetch_one)
    row = asyncio.run(qr.create_rule(
        "tenant-xyz", rule_id="QL-1", law="Test law", severity="hard_gate", source="chat",
    ))
    assert "ON CONFLICT (tenant_id, rule_id) DO UPDATE" in captured["query"]
    assert captured["args"][0] == "tenant-xyz"
    assert row["rule_id"] == "QL-1"


def test_bulk_create_rules_never_called_by_parser_itself(monkeypatch):
    """Confirm-before-insert: parsing alone must never write. Prove it by
    making the write path explode if reached, then only parse."""
    async def forbidden_fetch_one(*_a, **_k):
        raise AssertionError("parsing must never touch the DB")

    monkeypatch.setattr(qr, "fetch_one", forbidden_fetch_one)
    rows = qr.parse_markdown_table(_REAL_DVSU_EXCERPT)
    assert len(rows) == 4  # parsed fine, zero DB calls


def test_bulk_create_rules_writes_only_when_explicitly_invoked(monkeypatch):
    inserted = []

    async def fake_fetch_one(query, *args):
        inserted.append(args)
        return {"id": str(len(inserted)), "rule_id": args[1], "law": args[2],
                "evidence": args[3], "severity": args[4], "applies_to": args[5],
                "source": args[6], "active": True, "created_at": None, "updated_at": None}

    monkeypatch.setattr(qr, "fetch_one", fake_fetch_one)
    rows = qr.parse_markdown_table(_REAL_DVSU_EXCERPT)
    assert inserted == []  # nothing written by parsing alone

    saved = asyncio.run(qr.bulk_create_rules("tenant-xyz", rows, source="doc_upload"))
    assert len(saved) == 4
    assert len(inserted) == 4


def test_update_rule_only_sets_provided_fields(monkeypatch):
    captured = {}

    async def fake_fetch_one(query, *args):
        captured["query"] = query
        captured["args"] = args
        return {"id": "1", "rule_id": "QL-1", "law": "x", "evidence": None,
                "severity": "warn", "applies_to": '{"all": true}', "source": "chat",
                "active": False, "created_at": None, "updated_at": None}

    monkeypatch.setattr(qr, "fetch_one", fake_fetch_one)
    row = asyncio.run(qr.update_rule("tenant-xyz", "rule-id-1", {"active": False}))
    assert "active = $1" in captured["query"]
    assert "law = " not in captured["query"]
    assert captured["args"][-2:] == ("tenant-xyz", "rule-id-1")
    assert row["active"] is False


def test_deactivate_rule_returns_false_when_not_found(monkeypatch):
    async def fake_fetch_one(*_a, **_k):
        return None

    monkeypatch.setattr(qr, "fetch_one", fake_fetch_one)
    ok = asyncio.run(qr.deactivate_rule("tenant-xyz", "missing-id"))
    assert ok is False


# ---------------------------------------------------------------------------
# resolve_dvsu_overrides (checklist C46c) — the reference-tenant deltas.
# Rows here are REAL law text copied verbatim from
# storyengine/notes/dvsu-quality-law.md so the extractor patterns are proven
# against the actual doc, not a paraphrase.
# ---------------------------------------------------------------------------

_QL1_LAW = (
    "Reject under 80 spoken words; warn 80-95; reject over 170. Hit the "
    "register median, not a fixed number: tight-production 85-105, "
    "spec-block naval 100-120, long-form (crew/sunk/never-built) 110-130; "
    "the folded-outro final entry may reach 160."
)
_QL4_LAW = (
    'Name the twist from an expanded menu; do not default to "other." The '
    "five canonical types cover about half the corpus; add the recurring "
    "subtypes: lost-fly-off, treaty/politics-cancelled, cost-killed, "
    "mission-obsoleted-by-countermeasure, redundant-backup, "
    "incremental-stopgap, peaked-obsolete-concept, "
    "killed-by-secondary-threat, self-destruction, "
    "role-discontinued-by-budget, built-for-a-threat-that-never-existed."
)
_QL12_LAW = (
    "Ban thumbnail-hype adjectives (incredible, amazing, stunning, insane, "
    "epic, jaw-dropping, mind-blowing, game-changing, breathtaking, "
    "unbelievable, spectacular). Superlatives allowed ONLY when anchored to "
    "a verifiable fact. Avoid free-floating emotive nouns (nightmare, "
    "death-trap, killer)."
)


def test_resolve_dvsu_overrides_empty_when_no_matching_rule_ids():
    assert qr.resolve_dvsu_overrides([]) == {}
    assert qr.resolve_dvsu_overrides([_rule("QL-99", {"all": True})]) == {}


def test_resolve_dvsu_overrides_ql1_word_floor_parses_real_law_text():
    overrides = qr.resolve_dvsu_overrides([
        {"rule_id": "QL-1", "law": _QL1_LAW, "evidence": None,
         "severity": "hard_gate", "applies_to": {"story": True}},
    ])
    assert overrides["word_floor"] == {
        "hard_min": 80, "warn_top": 95, "hard_max": 170, "severity": "hard_gate",
    }


def test_resolve_dvsu_overrides_ql1_skipped_when_law_text_unparseable():
    """A row present but reworded away from the extractor's pattern is
    skipped for that key alone -- never raises, never half-applies."""
    overrides = qr.resolve_dvsu_overrides([
        {"rule_id": "QL-1", "law": "Keep paragraphs reasonably sized.",
         "evidence": None, "severity": "hard_gate", "applies_to": {"story": True}},
    ])
    assert "word_floor" not in overrides


def test_resolve_dvsu_overrides_ql3_twist_gate_severity():
    overrides = qr.resolve_dvsu_overrides([
        {"rule_id": "QL-3", "law": "twist law", "evidence": None,
         "severity": "warn", "applies_to": {"story": True}},
    ])
    assert overrides["twist_gate"] == {"severity": "warn"}


def test_resolve_dvsu_overrides_ql4_twist_menu_unions_canonical_and_parsed_subtypes():
    overrides = qr.resolve_dvsu_overrides([
        {"rule_id": "QL-4", "law": _QL4_LAW, "evidence": None,
         "severity": "guidance", "applies_to": {"story": True}},
    ])
    menu = overrides["twist_menu"]
    assert menu["severity"] == "guidance"
    # The 5 canonical types (not named in the law column, only Evidence) ...
    for canonical in ("role_change", "obsolete_but_enduring", "myth_vs_reality",
                       "cheap_beats_good", "ambition_outran_tech"):
        assert canonical in menu["types"]
    # ... unioned with all 11 subtypes parsed straight out of the law text.
    for subtype in (
        "lost_fly_off", "treaty_politics_cancelled", "cost_killed",
        "mission_obsoleted_by_countermeasure", "redundant_backup",
        "incremental_stopgap", "peaked_obsolete_concept",
        "killed_by_secondary_threat", "self_destruction",
        "role_discontinued_by_budget", "built_for_a_threat_that_never_existed",
    ):
        assert subtype in menu["types"]
    assert len(menu["types"]) == 16


def test_resolve_dvsu_overrides_ql12_banned_words_parsed_from_real_law_text():
    overrides = qr.resolve_dvsu_overrides([
        {"rule_id": "QL-12", "law": _QL12_LAW, "evidence": None,
         "severity": "hard_gate", "applies_to": {"all": True}},
    ])
    assert overrides["banned_hype_words"] == {
        "words": (
            "incredible", "amazing", "stunning", "insane", "epic",
            "jaw-dropping", "mind-blowing", "game-changing", "breathtaking",
            "unbelievable", "spectacular",
        ),
        "severity": "hard_gate",
    }


def test_resolve_dvsu_overrides_only_includes_present_rule_ids():
    """A tenant seeded with only QL-12 (not QL-1/QL-3/QL-4) gets ONLY the
    QL-12 override key -- proves the mechanism is per-rule, not all-or-nothing."""
    overrides = qr.resolve_dvsu_overrides([
        {"rule_id": "QL-12", "law": _QL12_LAW, "evidence": None,
         "severity": "hard_gate", "applies_to": {"all": True}},
    ])
    assert set(overrides.keys()) == {"banned_hype_words"}


def test_resolve_dvsu_overrides_generalizes_to_a_second_non_dvsu_tenant():
    """checklist C46c requirement: at least one law that is NOT DvsU-specific
    demonstrated working for a HYPOTHETICAL second tenant purely via table
    rows + scope matching -- no code specialization. QL-1's word-floor shape
    (hard floor / warn band / hard ceiling) is a generic craft law; a second
    tenant ("Acme Explainers") writing a completely different word-count
    contract (a 40-word hard floor, warn under 60, 300-word ceiling) gets
    ITS OWN numbers back from the exact same resolver -- nothing here reads
    "DvsU" or knows about aircraft."""
    acme_rules = [
        {"rule_id": "QL-1",
         "law": "Reject under 40 spoken words; warn 40-60; reject over 300.",
         "evidence": None, "severity": "hard_gate", "applies_to": {"all": True}},
    ]
    overrides = qr.resolve_dvsu_overrides(acme_rules)
    assert overrides["word_floor"] == {
        "hard_min": 40, "warn_top": 60, "hard_max": 300, "severity": "hard_gate",
    }
    assert overrides["word_floor"] != qr.resolve_dvsu_overrides([
        {"rule_id": "QL-1", "law": _QL1_LAW, "evidence": None,
         "severity": "hard_gate", "applies_to": {"all": True}},
    ])["word_floor"]
