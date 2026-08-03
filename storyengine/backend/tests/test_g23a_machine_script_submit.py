"""G23a: manual machine-paragraph submission door (the hand-edit path).

Before this chunk there was NO door to save a hand-written machine
paragraph: machine-script-block always invokes the LLM writer; submit_script
replaces the whole script; edit_scene_text can't create scenes and bypasses
the machine hold state. This is Ryan's requested door after the 5-card
research residue (thin-evidence cards the writer LLM could not draft from
without inventing facts) - a real, repeatable hand-edit path, not a one-off.

The submitted paragraph faces the SAME referee (_validate_machine_story_
sentences) a generated paragraph must pass, with no shortcuts. Only the
sentence-to-evidence structural mapping is machine-derived
(_map_submitted_paragraph_to_claim_bundle - deterministic token overlap,
option (i) from the brief, chosen over a Haiku structure call so the whole
path is $0 and offline-testable); the paragraph text itself is never
rewritten - verbatim law.

These tests are local/no-spend: no Anthropic client is ever constructed or
called on this path (there is no writer step to mock).
"""

import asyncio
import json

import pipeline_executor as pe


MACHINE = "Boeing XB-15"


def _evidence_segments() -> list[dict]:
    rows = [
        ("E-PROBLEM", "original_problem",
         "Original problem claim grounded in the supplied source clear clear clear clear clear."),
        ("E-DECISION", "engineering_decision",
         "Engineering decision claim grounded in the supplied source with wing, engine, tail, nose, "
         "and fuselage features clear clear clear clear."),
        ("E-TRADEOFF", "tradeoff",
         "Tradeoff claim grounded in the supplied source clear clear clear clear clear clear clear clear."),
        ("E-REALITY", "reality",
         "Reality claim grounded in the supplied source through its Cold War service period "
         "clear clear clear clear clear clear."),
        ("E-MEMORABLE", "memorable_fact", "Memorable fact claim grounded in the supplied source."),
    ]
    return [
        {
            "evidence_id": evidence_id, "kind": kind, "claim": claim, "source_excerpt": claim,
            "source_url": f"https://airandspace.si.edu/test/{kind}", "source_title": "Test source",
            "locator": f"S{index}-E1", "numeric_tokens": [], "confidence": "high",
        }
        for index, (evidence_id, kind, claim) in enumerate(rows, start=1)
    ]


def _research_card() -> dict:
    return {
        "unit": MACHINE,
        "engineering_thesis": f"{MACHINE} mattered because its design promise had to survive real operating limits.",
        "why_this_unit_deserves_a_paragraph": (
            f"{MACHINE} deserves a paragraph because its problem exposed a tradeoff between design and reality."
        ),
        "surprising_fact": "Memorable fact claim grounded in the supplied source.",
        "source_notes": [f"{MACHINE}-source"],
        "evidence_segments": _evidence_segments(),
        "visual_identity": f"{MACHINE} identified by its wing, engine, tail, nose, and fuselage features.",
        "visual_identity_evidence_ids": ["E-DECISION"],
        "timeframe": f"{MACHINE} documented through its Cold War service period.",
        "timeframe_evidence_ids": ["E-REALITY"],
    }


# A genuinely well-grounded HAND-WRITTEN paragraph: every clause echoes the
# locked evidence's own wording (a human transcribing real facts, not an LLM
# paraphrasing), 5 sentences (4 evidence beats + closer), comfortably clears
# the 80-word hard floor without relying on the G18 grace band.
GOOD_PARAGRAPH = (
    "Original problem claim grounded in the supplied source clear clear clear clear clear. "
    "Engineering decision claim grounded in the supplied source with wing, engine, tail, nose, "
    "and fuselage features clear clear clear clear. "
    "Tradeoff claim grounded in the supplied source clear clear clear clear clear clear clear clear. "
    "Reality claim grounded in the supplied source through its Cold War service period "
    "clear clear clear clear clear clear. "
    "Boeing XB-15 proved that scale alone does not guarantee lasting success for every ambitious design."
)

# Same paragraph, except the reality sentence invents a specific unsupported
# number ("twelve thousand missions") - exactly the real residue failure
# shape (CVA-01 invents "ten", Activity invents "twelve thousand"/"fifty
# nine", Nairana invents "lieutenant").
INVENTED_FACT_PARAGRAPH = (
    "Original problem claim grounded in the supplied source clear clear clear clear clear. "
    "Engineering decision claim grounded in the supplied source with wing, engine, tail, nose, "
    "and fuselage features clear clear clear clear. "
    "Tradeoff claim grounded in the supplied source clear clear clear clear clear clear clear clear. "
    "Reality claim grounded in the supplied source through its Cold War service period, "
    "flying twelve thousand missions in secret. "
    "Boeing XB-15 proved that scale alone does not guarantee lasting success for every ambitious design."
)


def _video(extra_validation: dict | None = None) -> dict:
    video = {
        "video_title": "Every US Strategic Bomber Ever Built",
        "render_mode": "static_docu",
        "research_payload": {
            "documentary_style": "designed_vs_used",
            "unit_roster": [MACHINE, "Consolidated B-24 Liberator", "Boeing B-17 Flying Fortress"],
            "unit_research_cards": [_research_card()],
        },
    }
    if extra_validation is not None:
        video["script_validation"] = extra_validation
    return video


def _scaffold(monkeypatch, video, *, fetch_rows_by_marker: dict[str, list] | None = None):
    """Shared executor + DB-fake scaffold used by every test below."""
    executor = pe.PipelineExecutor.__new__(pe.PipelineExecutor)
    executor.tenant_id = "tenant-test"

    writes: list[tuple[str, tuple]] = []
    activity: list[tuple] = []

    async def fake_init():
        return None

    async def fake_get_video(_video_id):
        return video

    async def fake_load_prompt_overrides(_video):
        return None

    async def fake_load_cards(_video_id, payload, _roster, target_machine=None):
        return dict(payload)

    async def fake_execute(query, *args):
        writes.append((query, args))
        return None

    fetch_rows_by_marker = fetch_rows_by_marker or {}

    async def fake_fetch_all(query, *args):
        for marker, rows in fetch_rows_by_marker.items():
            if marker in query:
                return rows
        return []

    async def fake_log(*_args, **_kwargs):
        activity.append(_args)
        return None

    async def fake_transition(*_args, **_kwargs):
        return None

    monkeypatch.setattr(executor, "_ensure_initialized", fake_init)
    monkeypatch.setattr(executor, "_get_video", fake_get_video)
    monkeypatch.setattr(executor, "_load_prompt_overrides", fake_load_prompt_overrides)
    monkeypatch.setattr(executor, "_load_machine_research_cards", fake_load_cards)
    monkeypatch.setattr(executor, "_log_activity", fake_log)
    monkeypatch.setattr(executor, "_log_transition", fake_transition)
    monkeypatch.setattr(executor, "_skip_disabled_next", lambda _video, status: status)
    monkeypatch.setattr(pe, "execute", fake_execute)
    monkeypatch.setattr(pe, "fetch_all", fake_fetch_all)

    return executor, writes, activity


# ---------------------------------------------------------------------------
# (1) A well-grounded hand paragraph saves and updates hold state exactly
#     like a generated one.
# ---------------------------------------------------------------------------

def test_well_grounded_hand_paragraph_saves_and_updates_hold_state(monkeypatch):
    video = _video()
    executor, writes, activity = _scaffold(monkeypatch, video, fetch_rows_by_marker={
        "FROM scripts": [],  # no prior scenes, no prior voice_id row
        "quality_rules": [],  # _load_dvsu_rule_overrides: no seeded tenant rows
    })

    result = asyncio.run(executor.run_machine_script_submit("video-test", MACHINE, GOOD_PARAGRAPH))

    assert result["status"] == "completed"
    script_block = result["script_block"]
    assert script_block["passed"] is True
    assert script_block["saved"] is True
    assert script_block["scene"] == 1
    assert script_block["machine"] == MACHINE
    assert not pe._blocking_warnings(script_block["warnings"])

    # Exactly the SAME persistence path a generated card uses: one combined
    # UPDATE-or-INSERT into scripts + UPDATE videos SET script_validation.
    atomic_writes = [(q, a) for q, a in writes if "UPDATE scripts" in q and "INSERT INTO scripts" in q]
    assert len(atomic_writes) == 1
    query, args = atomic_writes[0]
    assert args[2] == 1  # scene
    assert args[3] == " ".join(GOOD_PARAGRAPH.split())  # saved scene_text
    validation = json.loads(args[7])
    assert validation["machine_script_blocks"][MACHINE]["saved"] is True
    assert validation["script_hold"]["completed_count"] == 1
    assert validation["script_hold"]["total_count"] == 3
    unit = validation["script_hold"]["units"][0]
    assert unit["scene"] == 1
    assert unit["machine"] == MACHINE
    assert unit["passed"] is True
    # research_source names this a hand submission, not a generated draft -
    # visible in the audit trail exactly like machine-script-block's own
    # research_source field does for its generation path.
    assert unit["research_source"] == "hand_submitted"
    assert any("completed" in call for call in activity[-1])


# ---------------------------------------------------------------------------
# (2) An invented-fact paragraph is rejected with warnings, no shortcuts.
# ---------------------------------------------------------------------------

def test_invented_fact_paragraph_is_rejected_with_warnings(monkeypatch):
    video = _video()
    executor, writes, activity = _scaffold(monkeypatch, video, fetch_rows_by_marker={
        "FROM scripts": [],
        "quality_rules": [],
    })

    result = asyncio.run(executor.run_machine_script_submit("video-test", MACHINE, INVENTED_FACT_PARAGRAPH))

    assert result["status"] == "completed"
    script_block = result["script_block"]
    assert script_block["passed"] is False
    assert script_block["saved"] is False
    blocking = pe._blocking_warnings(script_block["warnings"])
    assert any("twelve thousand" in w for w in blocking), blocking
    assert any(w.startswith("claim_map row 4 introduced unsupported numerical detail") for w in blocking)
    # No shortcuts: nothing was written to the scripts table for a rejected
    # hand submission, exactly like a rejected generated draft.
    assert not any("INSERT INTO scripts" in q for q, _a in writes)
    assert any("needs review" in str(call) for call in activity[-1])


def test_missing_research_card_still_hard_blocks_submission(monkeypatch):
    """Scope guard: the submit door still requires a real saved research
    card - it is a save path for a vetted card's own facts, not a way to
    bypass the research stage entirely."""
    video = _video()
    video["research_payload"]["unit_research_cards"] = []
    executor, writes, _activity = _scaffold(monkeypatch, video)

    result = asyncio.run(executor.run_machine_script_submit("video-test", MACHINE, GOOD_PARAGRAPH))

    assert result["status"] == "failed"
    assert "saved research card" in result["error"]
    assert writes == []


def test_wrong_sentence_count_is_rejected_not_hard_failed(monkeypatch):
    """A hand-written paragraph that isn't exactly 5 sentences (4 evidence
    beats + closer, the same Anton formula a generated draft must follow)
    is rejected with a clear structural warning in the SAME response shape
    as a referee rejection - not a raw 400, so the human sees exactly why."""
    video = _video()
    executor, writes, _activity = _scaffold(monkeypatch, video, fetch_rows_by_marker={
        "FROM scripts": [], "quality_rules": [],
    })
    three_sentence_paragraph = (
        "Original problem claim grounded in the supplied source. "
        "Engineering decision claim grounded in the supplied source. "
        "Boeing XB-15 proved something in the end."
    )

    result = asyncio.run(executor.run_machine_script_submit("video-test", MACHINE, three_sentence_paragraph))

    assert result["status"] == "completed"
    script_block = result["script_block"]
    assert script_block["passed"] is False
    assert any("exactly 5 sentences" in w for w in script_block["warnings"])
    assert writes == []


# ---------------------------------------------------------------------------
# (3) Submitted text is byte-identical after save (verbatim law).
# ---------------------------------------------------------------------------

def test_submitted_text_is_byte_identical_after_save(monkeypatch):
    # Deliberately messy whitespace (tabs, doubled spaces, a stray newline) -
    # the ONLY normalization allowed is collapsing that whitespace to single
    # spaces; no word may be added, removed, or reordered.
    messy_paragraph = GOOD_PARAGRAPH.replace(
        "Original problem claim grounded",
        "Original  problem\tclaim   grounded",
    )
    expected_normalized = " ".join(messy_paragraph.split())
    assert expected_normalized == " ".join(GOOD_PARAGRAPH.split()), "fixture sanity: whitespace-only edit"

    video = _video()
    executor, writes, _activity = _scaffold(monkeypatch, video, fetch_rows_by_marker={
        "FROM scripts": [], "quality_rules": [],
    })

    result = asyncio.run(executor.run_machine_script_submit("video-test", MACHINE, messy_paragraph))

    assert result["status"] == "completed"
    script_block = result["script_block"]
    assert script_block["passed"] is True
    # The SAVED paragraph (both in the response and in the DB write) is
    # byte-identical to the whitespace-normalized submission - no rewording.
    assert script_block["paragraph"] == expected_normalized
    atomic_writes = [(q, a) for q, a in writes if "UPDATE scripts" in q and "INSERT INTO scripts" in q]
    assert atomic_writes[0][1][3] == expected_normalized
    # And the underlying sentence text is preserved word-for-word too - the
    # mapping only assigned evidence ids, never touched a word.
    for sentence in script_block["claim_bundle"]["formula_sentences"]:
        assert sentence in expected_normalized
