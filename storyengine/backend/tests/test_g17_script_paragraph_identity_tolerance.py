"""G17: script-stage identity tolerance + writer-prompt rules (carrier-ready).

The known cousin flagged by G16's worker: _validate_static_unit_paragraph (the
final SCRIPT paragraph gate, not the research-card gate G16 fixed) required
the machine's FULL glued 4-token code to appear as one contiguous substring of
the paragraph text - i.e. the pennant/hull-number/duplicate-name tokens
written with NOTHING between them. Real spoken narration never does that,
so this blocked every naturally-written paragraph in the real 23-carrier
roster (video d2e37cd6-521a-43aa-a14d-ce096a783c1e, "Every British Aircraft
Carrier Class Ever Built"). Fixture strings below are pulled verbatim from
that video's live machine_research_cards.machine_name / research_payload
unit_roster rows via `scripts/se.sh db` - not invented shapes.

These tests are local/no-spend (fake Anthropic client, no real API calls).
"""

import asyncio
import copy
import json

import pipeline_executor as pe


# ---------------------------------------------------------------------------
# Real roster fixture strings (video d2e37cd6, "Every British Aircraft
# Carrier Class Ever Built" - machine_research_cards.machine_name / the
# `roster = [_unit_display_name(x) for x in unit_roster]` list script-hold
# actually iterates).
# ---------------------------------------------------------------------------
ARGUS = "HMS Argus (I49) Argus"
FURIOUS = "HMS Furious (47) Furious"
AUDACIOUS = "CVA-01 predecessors Audacious class / Malta class"
COURAGEOUS = "Courageous, Glorious Courageous class"
CENTAUR = "Centaur, Albion, Bulwark, Hermes (R12) Centaur class"
# Two different Ark Royals appear in this roster's own history, so the NAME
# half (not just the designation half) carries its own trailing bracketed
# disambiguator - the sharpest real edge case for a bare last-split-token
# fallback.
ARK_ROYAL_1937 = "HMS Ark Royal (91) Ark Royal (1937)"


def _natural_paragraph(*sentences: str) -> str:
    return " ".join(sentences)


ARGUS_PARAGRAPH = _natural_paragraph(
    "The Admiralty needed proof that aircraft could operate from a moving hull before committing to a purpose-built carrier fleet.",
    "Engineers converted an unfinished Italian ocean liner into a flush flight deck, stripping away the superstructure that would have fouled a landing run.",
    "HMS Argus solved the arrestor problem other conversions never cracked, letting aircraft land without striking a bridge or funnel.",
    "That flush deck became the template every later British carrier copied, from armored fleet ships to light fleet hulls.",
    "The gamble on a converted liner hull paid off far beyond its own short service life.",
)

FURIOUS_PARAGRAPH = _natural_paragraph(
    "A fast battlecruiser hull gave the Admiralty a problem: how to launch aircraft from a ship built for speed, not flying.",
    "HMS Furious answered that question first, landing an aircraft on a moving warship years before any purpose-built carrier existed.",
    "That early trial exposed turbulence problems around the bridge that later conversions had to design around entirely.",
    "The lessons from those first landings shaped every flight deck the Royal Navy built afterward.",
    "One risky trial answered a question the whole fleet needed solved.",
)

AUDACIOUS_PARAGRAPH = _natural_paragraph(
    "Postwar budgets forced the Admiralty to cancel four large fleet carriers already laid down on the slips at two different yards.",
    "Design work on the Audacious class had promised an armored hangar and a heavier air group than any wartime British carrier before it.",
    "Only one hull, renamed and finished years late, ever reached the fleet, while its three sisters were broken up half built on the ways.",
    "The class proved that a sound design could still lose outright to a shrinking peacetime budget and a change in strategic priorities.",
    "Cancelled steel taught the Admiralty more about postwar limits than a single finished ship ever could have shown on its own.",
)

COURAGEOUS_PARAGRAPH = _natural_paragraph(
    "Two First World War battlecruisers were built for speed at the expense of armor, leaving the Admiralty with fast hulls and no clear peacetime role.",
    "Converting them into the Courageous class gave those thin-skinned hulls a long flight deck and a second career the treaty fleet still needed.",
    "The conversion kept the underlying speed problem baked into the hull, a weakness the design never fully solved.",
    "Both ships proved that a fast hull could still carry aircraft well, even without the armor a purpose-built carrier would have.",
    "Speed bought them a second life that armor alone could never have earned.",
)

CENTAUR_PARAGRAPH = _natural_paragraph(
    "Wartime lessons about damage control pushed postwar designers toward a smaller, tougher fleet carrier than the armored giants before them.",
    "The Centaur class answered that call with a compact hull, angled improvements added later, and a hangar sized for jet aircraft rather than propeller machines.",
    "Only a handful of sister ships reached service before newer designs made the whole concept obsolete.",
    "The class bridged the gap between wartime armored carriers and the angled-deck ships that followed, without fully matching either.",
    "A stopgap by design, it kept British naval aviation flying while something better was worked out.",
)

ARK_ROYAL_PARAGRAPH = _natural_paragraph(
    "By the mid nineteen thirties the Admiralty wanted a carrier whose flight deck was structural, not simply bolted onto an existing hull.",
    "HMS Ark Royal answered that demand with an armored hangar built into the hull itself, a genuine first for a Royal Navy design.",
    "That armored-hangar approach protected aircraft below deck far better than any earlier battleship or battlecruiser conversion had ever managed.",
    "The design proved so sound that every armored fleet carrier built in the years afterward copied its basic hangar layout closely.",
    "One ship's hull design reshaped how the whole navy planned and built aircraft carriers from that point on.",
)


# ---------------------------------------------------------------------------
# Fix 1: script-paragraph identity/designation tolerance
# ---------------------------------------------------------------------------

def test_natural_paragraph_passes_for_its_own_real_roster_machine():
    """The bug, proven against every real roster shape from video d2e37cd6:
    a naturally-written paragraph must not fail the locked-designation gate
    just because it never glues the pennant/hull-number/duplicate name into
    one unbroken token the way the roster's own bookkeeping string does."""
    validate = pe.PipelineExecutor._validate_static_unit_paragraph

    for machine, paragraph in (
        (ARGUS, ARGUS_PARAGRAPH),
        (AUDACIOUS, AUDACIOUS_PARAGRAPH),
        (COURAGEOUS, COURAGEOUS_PARAGRAPH),
        (CENTAUR, CENTAUR_PARAGRAPH),
    ):
        warnings = validate(machine, paragraph)
        assert warnings == [], f"{machine!r}: {warnings}"


def test_ark_royal_1937_disambiguated_name_passes_despite_trailing_bracket():
    """The sharpest real edge case: the NAME half of the roster string carries
    its own trailing disambiguator ("(1937)" - this roster has two Ark
    Royals). A bare `.split()[-1]` fallback would demand the literal token
    "(1937)" appear in the paragraph, which no natural voiceover ever writes.
    Stripping ONE trailing bracket group recovers the real last name word."""
    validate = pe.PipelineExecutor._validate_static_unit_paragraph
    warnings = validate(ARK_ROYAL_1937, ARK_ROYAL_PARAGRAPH)
    assert warnings == [], warnings


def test_sibling_screening_still_rejects_a_different_machines_paragraph():
    """Do NOT loosen anything else: a paragraph plainly about HMS Furious
    must still fail the designation gate when validated against the LOCKED
    Argus slot - cross-machine sibling screening stays intact."""
    validate = pe.PipelineExecutor._validate_static_unit_paragraph
    warnings = validate(ARGUS, FURIOUS_PARAGRAPH)
    assert any(w.startswith("missing locked machine designation") for w in warnings), warnings


def test_static_paragraph_identity_candidate_terms_strips_one_trailing_bracket_only():
    """The helper's own contract (G22: now a candidate SET, not one term -
    see the G22 section below for why): strip at
    most ONE trailing purely-bracketed group before splitting into words;
    every other roster shape (whose last word is already the real name,
    never a bracket) is untouched. "class" is excluded from AUDACIOUS/
    COURAGEOUS/CENTAUR's candidates (generic stopword), but each still
    carries its real distinguishing name word(s)."""
    assert pe._static_paragraph_identity_candidate_terms(ARGUS) == ["argus", "i49"]
    assert pe._static_paragraph_identity_candidate_terms(AUDACIOUS) == ["cva-01", "audacious", "malta"]
    assert pe._static_paragraph_identity_candidate_terms(COURAGEOUS) == ["courageous", "glorious"]
    assert pe._static_paragraph_identity_candidate_terms(CENTAUR) == ["centaur", "albion", "bulwark", "hermes", "r12"]
    assert pe._static_paragraph_identity_candidate_terms(FURIOUS) == ["furious", "47"]
    # The one case the bracket-strip actually changes: without it, this would
    # carry the literal, never-written-verbatim token "1937".
    assert pe._static_paragraph_identity_candidate_terms(ARK_ROYAL_1937) == ["ark", "royal", "91"]


def test_designation_gate_reuses_locked_machine_identity_codes_not_a_new_regex_family():
    """Single source of truth (task requirement): the fix reuses G16's own
    `_locked_machine_identity_codes` pennant-tolerant code set rather than a
    fresh parallel matcher. Exact-code paragraphs (the old behavior) still
    pass, proving this is a strict widening, not a replacement."""
    validate = pe.PipelineExecutor._validate_static_unit_paragraph
    exact_code_paragraph = _natural_paragraph(
        "HMSARGUSI49ARGUS is how the roster's own bookkeeping glues this ship's designation into one token, unlike any spoken sentence a person would say out loud.",
        "No narrator would ever write it this way, but the gate must still accept it if a draft somehow did.",
        "The point of this fixture is mechanical coverage of the exact-match branch, not realism.",
        "Word count padding follows here to clear the hard floor for this synthetic check only.",
        "Extra padding word extra padding word extra padding word extra padding word extra padding word extra padding.",
    )
    warnings = validate(ARGUS, exact_code_paragraph)
    assert not any(w.startswith("missing locked machine designation") for w in warnings), warnings


# ---------------------------------------------------------------------------
# Fix 1 companion: the closer's "new named entity" screen (a second, lower-
# probability site sharing the same disease) is widened to the same
# pennant-tolerant code SET rather than a single exact-code equality check.
# This is a strict superset of the old check (the set always contains the
# old single code), verified here by direct call rather than the full async
# story-sentence pipeline.
# ---------------------------------------------------------------------------

def test_locked_machine_identity_codes_widening_is_a_strict_superset():
    old_single_code = pe._normalized_unit_code(ARK_ROYAL_1937)
    widened_codes = pe._locked_machine_identity_codes(ARK_ROYAL_1937)
    assert old_single_code in widened_codes


# ---------------------------------------------------------------------------
# Fix 3: writer-prompt rule audit (G16's lesson). Two _validate_static_unit_
# paragraph rules - no production cues/labels, no chronological-biography
# structure - were already taught in the legacy single-shot prompt and the
# repair-round prompt, but were checker-only for the INVENTORY-mode
# first-pass write prompt (voice_rules): a fresh draft only learned them
# after failing once and burning a paid repair round. Folded into the
# prompt via the same shared-constant technique as G16's CONTENT-SHAPE RULES.
# ---------------------------------------------------------------------------

def _evidence_segments() -> list[dict]:
    rows = [
        ("E-PROBLEM", "original_problem", "Original problem claim grounded in the supplied source."),
        ("E-ROLE", "role_category", "Role category claim grounded in the supplied source."),
        ("E-DECISION", "engineering_decision", "Engineering decision claim grounded in the supplied source with broad flight deck, tall bridge, and forward hangar door features."),
        ("E-TRADEOFF", "tradeoff", "Tradeoff claim grounded in the supplied source."),
        ("E-REALITY", "reality", "Reality claim grounded in the supplied source through its wartime service period."),
        ("E-MEMORABLE", "memorable_fact", "Memorable fact claim grounded in the supplied source."),
    ]
    return [
        {
            "evidence_id": evidence_id,
            "kind": kind,
            "claim": claim,
            "source_excerpt": claim,
            "source_url": f"https://iwm.org.uk/test/{kind}",
            "source_title": "Test source",
            "locator": f"S{index}-E1",
            "numeric_tokens": [],
            "confidence": "high",
        }
        for index, (evidence_id, kind, claim) in enumerate(rows, start=1)
    ]


def _valid_research_card(machine: str) -> dict:
    return {
        "unit": machine,
        "engineering_thesis": f"{machine} mattered because its deck design exposed hangar tradeoffs in service.",
        "why_this_unit_deserves_a_paragraph": (
            f"{machine} deserves a paragraph because its hangar decision exposed a tradeoff "
            "between protection, weight, and service reality."
        ),
        "surprising_fact": "Memorable fact claim grounded in the supplied source.",
        "source_notes": ["test-source"],
        "evidence_segments": _evidence_segments(),
        "visual_identity": f"{machine} identified by its broad flight deck, tall bridge, and forward hangar doors.",
        "visual_identity_evidence_ids": ["E-DECISION"],
        "timeframe": f"{machine} documented through its wartime service period.",
        "timeframe_evidence_ids": ["E-REALITY"],
    }


def _verified_package_for_segments(machine: str, segments: list[dict]) -> dict:
    return {
        "passed": True,
        "machine": machine,
        "machine_key": pe._normalized_unit_code(machine),
        "search_queries": [f'"{machine}" verified source'],
        "sources": [
            {
                "source_id": f"S{index}",
                "title": segment["source_title"],
                "url": segment["source_url"],
                "text_hash": "test",
                "text_chars": len(segment["source_excerpt"]),
            }
            for index, segment in enumerate(segments, start=1)
        ],
        "candidate_excerpts": [
            {
                "excerpt_id": f"S{index}-E1",
                "source_id": f"S{index}",
                "source_title": segment["source_title"],
                "source_url": segment["source_url"],
                "locator": segment.get("locator") or f"S{index}-E1",
                "text": f"{machine} {segment['source_excerpt']}",
                "text_hash": "test",
                "source_capture_method": "fetched_page",
                "source_variant_selection": {
                    "selected_capture_method": "fetched_page",
                    "selected_variant": {
                        "source_capture_method": "fetched_page",
                        "covered_slot_count": 4,
                        "distinct_slot_excerpt_count": 4,
                    },
                    "evaluated_variants": [
                        {"source_capture_method": "fetched_page", "covered_slot_count": 4},
                    ],
                    "selection_rule": "highest Anton-slot coverage; fetched_page wins exact ties",
                },
            }
            for index, segment in enumerate(segments, start=1)
        ],
    }


def _story_bundle(machine: str, words_per_sentence: int) -> str:
    target_words = max(5, words_per_sentence * 5)
    sentences = [
        f"{machine} original problem claim grounded in the supplied source.",
        "Engineering decision claim grounded in the supplied source.",
        "Tradeoff claim grounded in the supplied source.",
        "Reality claim grounded in the supplied source.",
        "The proof survived the machine.",
    ]
    fill_index = 0
    while pe._spoken_word_count(" ".join(sentences)) < target_words:
        index = fill_index % (len(sentences) - 1)
        sentences[index] = sentences[index].rstrip(".") + " clear."
        fill_index += 1
    ids = [["E-PROBLEM"], ["E-DECISION"], ["E-TRADEOFF"], ["E-REALITY", "E-MEMORABLE"]]
    return json.dumps({
        "editorial_thesis": f"{machine} mattered because its design promise had to survive real operating limits.",
        "twist": {"type": "role_change", "substitute": None, "summary": "Built for the promise, used as the proof."},
        "formula_sentences": sentences,
        "paragraph": " ".join(sentences),
        "claim_map": [
            {"slot": slot, "span": sentence, "used_evidence_ids": evidence_ids}
            for slot, sentence, evidence_ids in zip(
                ["original_problem", "engineering_decision", "tradeoff", "reality"], sentences, ids,
            )
        ],
        "onscreen_label": "",
    })


def _passing_quality_audit() -> dict:
    return {
        "passed": True,
        "checks": [{"name": "validator_warnings", "label": "Validator warnings", "passed": True, "detail": "clean"}],
        "summary": "Anton quality audit passed",
    }


def test_content_rule_constants_match_the_validators_own_intent():
    """The constants ARE the rule text used in the prompt - not a re-typed
    copy that can silently drift from what the checker actually enforces."""
    assert pe._STATIC_PARAGRAPH_NO_PRODUCTION_CUES_RULE.startswith("No heading, markdown, bullets, labels")
    assert "b-roll" in pe._STATIC_PARAGRAPH_NO_PRODUCTION_CUES_RULE
    assert pe._STATIC_PARAGRAPH_NO_CHRONOLOGY_RULE.startswith("Do not write a chronological biography")


def test_inventory_mode_first_pass_prompt_teaches_both_previously_checker_only_rules(monkeypatch):
    """End-to-end: render the ACTUAL first-pass inventory-mode write prompt
    built by _run_static_script_hold for the REAL video title (video
    d2e37cd6, "Every British Aircraft Carrier Class Ever Built") and prove it
    states both rules verbatim using the shared constants, instead of the
    model only learning them from a paid repair round."""
    machine = ARGUS
    roster = [machine]
    video = {
        "video_title": "Every British Aircraft Carrier Class Ever Built",
        "render_mode": "static_docu",
        "research_payload": {
            "documentary_style": "designed_vs_used",
            "unit_roster": roster,
            "unit_research_cards": [_valid_research_card(machine)],
            "machine_raw_source_packages": {
                pe._verified_source_cache_key(machine): _verified_package_for_segments(machine, _evidence_segments()),
            },
        },
    }

    class FakeAnthropic:
        def __init__(self):
            self.prompts = []
            self.outputs = [_story_bundle(machine, 20)]

        async def generate(self, **kwargs):
            self.prompts.append(kwargs["prompt"])
            return self.outputs.pop(0) if self.outputs else _story_bundle(machine, 20)

    fake_anthropic = FakeAnthropic()
    executor = pe.PipelineExecutor.__new__(pe.PipelineExecutor)
    executor.tenant_id = "tenant-test"
    executor.__dict__["_pipeline"] = type(
        "FakePipeline", (), {"anthropic": fake_anthropic, "script_system_prompt": "TEST SCRIPT CONTRACT"},
    )()

    async def fake_execute(query, *args):
        return None

    async def fake_fetch_all(query, *args):
        return []

    async def fake_log(*_args, **_kwargs):
        return None

    async def fake_update_status(*_args, **_kwargs):
        return None

    async def fake_validate(_video_id):
        return {"passed": True}

    monkeypatch.setattr(pe, "execute", fake_execute)
    monkeypatch.setattr(pe, "fetch_all", fake_fetch_all)
    monkeypatch.setattr(pe, "_anton_preview_quality_audit", lambda *_a, **_k: _passing_quality_audit())
    monkeypatch.setattr(executor, "_log_activity", fake_log)
    monkeypatch.setattr(executor, "_validate_static_script_roster", fake_validate)
    monkeypatch.setattr(executor, "_update_video_status", fake_update_status)
    monkeypatch.setattr(executor, "_skip_disabled_next", lambda _video, status: status)

    asyncio.run(executor._run_static_script_hold("video-test", video, roster))

    assert fake_anthropic.prompts, "no first-pass write prompt was ever rendered"
    first_pass_prompt = fake_anthropic.prompts[0]
    assert "VOICE RULES" in first_pass_prompt
    assert pe._STATIC_PARAGRAPH_NO_PRODUCTION_CUES_RULE in first_pass_prompt
    assert pe._STATIC_PARAGRAPH_NO_CHRONOLOGY_RULE in first_pass_prompt
    # Regression: the designation rule that was ALREADY taught stays present.
    assert "say the locked machine designation at least once" in first_pass_prompt


# ---------------------------------------------------------------------------
# G22: the single-last-word fallback above still had a live gap. A roster
# entry whose display name happens to END with a generic roster-bookkeeping
# classifier ("... Campania class", "... Empire Mac-Ship conversions")
# degraded the fallback to a term no SINGLE-SHIP paragraph naturally writes
# ("class"), even though the paragraph names its own machine by name twice.
# Multi-ship class entries (Colossus class, Attacker class - both PASS)
# only survived by accident: their paragraphs genuinely narrate several
# sister ships, so the word "class" happens to appear. Live repro: 7 of 23
# machines on video d2e37cd6 - every one a single-ship conversion or an
# awkward slash/compound name - hit exactly "missing locked machine
# designation" with zero other blocking warnings. Fix: the fallback is now
# a candidate SET (_static_paragraph_identity_candidate_terms) - every
# meaningful word from the display name, generic classifiers stripped -
# and the check passes if the paragraph contains ANY of them.
# ---------------------------------------------------------------------------

# The 7 real holdout roster display strings (video d2e37cd6, confirmed live
# via `se db` - not invented shapes).
ACTIVITY = "HMS Activity (D94) Activity class"
CAMPANIA = "HMS Campania (D48) Campania class"
PRETORIA_CASTLE = "HMS Pretoria Castle (F61) Pretoria Castle class"
NAIRANA = "Nairana, Vindex Nairana class"
ARCHER_MAC_SHIP = "CAM ships and MAC ships Archer class / Empire Mac-Ship conversions"
CVA01_PREDECESSORS = "CVA-01 predecessors Audacious class / Malta class"
CVA01_CLASS = "CVA-01 Queen Elizabeth class (1960s design) CVA-01 class"

# Campania's REAL generated draft (captured live from a machine-script-block
# response, /tmp/campania.json) - names "HMS Campania (D48)" twice, never
# the word "class", and blocked with EXACTLY "missing locked machine
# designation HMSCAMPANIAD48CAMPANIA" before this fix.
CAMPANIA_REAL_PARAGRAPH = _natural_paragraph(
    "Converted from a passenger cargo vessel ordered by Shaw Savill Line in 1940, the ship "
    "that became HMS Campania (D48) entered service as an escort carrier before a strange "
    "final chapter began.",
    "HMS Campania (D48)'s final mission came in October 1952, when she was towed to the "
    "Monte Bello Islands to measure the shockwave of Britain's first atomic bomb test.",
    "The escort carrier spent her last days not hunting submarines, but measuring shockwaves, "
    "a fittingly strange coda for a ship built to ferry cargo.",
)


def test_g22_all_seven_real_holdout_names_produce_sensible_candidate_terms():
    """Every one of the 7 live-blocked machines must derive a candidate set
    that actually contains its real distinguishing name word(s), not just
    the generic classifier that was silently degrading the old fallback."""
    assert pe._static_paragraph_identity_candidate_terms(ACTIVITY) == ["activity", "d94"]
    assert pe._static_paragraph_identity_candidate_terms(CAMPANIA) == ["campania", "d48"]
    assert pe._static_paragraph_identity_candidate_terms(PRETORIA_CASTLE) == ["pretoria", "castle", "f61"]
    assert pe._static_paragraph_identity_candidate_terms(NAIRANA) == ["nairana", "vindex"]
    archer_terms = pe._static_paragraph_identity_candidate_terms(ARCHER_MAC_SHIP)
    assert "archer" in archer_terms and "mac-ship" in archer_terms
    cva01_predecessors_terms = pe._static_paragraph_identity_candidate_terms(CVA01_PREDECESSORS)
    assert "malta" in cva01_predecessors_terms and "audacious" in cva01_predecessors_terms
    cva01_class_terms = pe._static_paragraph_identity_candidate_terms(CVA01_CLASS)
    assert "cva-01" in cva01_class_terms
    assert "queen" in cva01_class_terms and "elizabeth" in cva01_class_terms
    # None of the 7 should EVER resolve to a bare generic classifier as their
    # only candidate - that was the whole bug.
    for machine in (ACTIVITY, CAMPANIA, PRETORIA_CASTLE, NAIRANA, ARCHER_MAC_SHIP, CVA01_PREDECESSORS, CVA01_CLASS):
        terms = pe._static_paragraph_identity_candidate_terms(machine)
        assert terms, f"{machine!r} produced no candidates at all"
        assert not all(term in pe._GENERIC_IDENTITY_STOPWORDS for term in terms), (
            f"{machine!r} candidates are ALL generic: {terms}"
        )


def test_g22_campania_real_captured_draft_now_passes():
    """Campania's ACTUAL generated draft (captured live, currently blocking
    in prod) must pass under the fix - a pure check fix, zero re-drafting,
    zero paid calls needed to repair this scene."""
    validate = pe.PipelineExecutor._validate_static_unit_paragraph
    warnings = validate(CAMPANIA, CAMPANIA_REAL_PARAGRAPH)
    assert not any(w.startswith("missing locked machine designation") for w in warnings), warnings


def test_g22_furious_still_passes_without_its_pennant():
    """Regression: Furious's real shape (names itself, never writes the
    pennant "(47)") must keep passing - the fix only ADDS candidates, it
    must never narrow what already worked."""
    validate = pe.PipelineExecutor._validate_static_unit_paragraph
    warnings = validate(FURIOUS, FURIOUS_PARAGRAPH)
    assert not any(w.startswith("missing locked machine designation") for w in warnings), warnings


def test_g22_paragraph_that_never_names_its_machine_still_blocks():
    """Identity enforcement stays intact: broadening the candidate SET must
    never let a paragraph that genuinely never mentions its own machine
    (by any of its distinguishing name words - "campania" or "d48") slip
    through. Deliberately never writes either word, and padded past the
    80-word hard floor so ONLY the designation check is under test here."""
    validate = pe.PipelineExecutor._validate_static_unit_paragraph
    unrelated_paragraph = _natural_paragraph(
        "A separate design entirely, this vessel answered a different requirement altogether, "
        "built to a specification nobody on this roster ever proposed.",
        "Engineers solved a completely unrelated problem with an unrelated hull shape, "
        "trading one set of tradeoffs for another the Admiralty never asked for.",
        "None of this text refers to the locked machine by either of its own name words, "
        "on purpose, proving the gate still catches a genuine miss.",
        "The story stays deliberately generic, describing a service history that could "
        "belong to any hull in the fleet rather than this one specifically.",
        "Nothing in these sentences should ever satisfy a candidate term for the ship this "
        "paragraph was actually supposed to be about.",
    )
    warnings = validate(CAMPANIA, unrelated_paragraph)
    assert any(w.startswith("missing locked machine designation") for w in warnings), warnings


def test_g22_all_stoplist_name_falls_back_to_last_word_behavior():
    """If stripping the generic stoplist would leave NOTHING (a constructed
    entry whose every word is generic), the fix must fall back to the OLD
    single-last-word behavior rather than accepting everything - a stoplist
    word must never be the only candidate that legalizes an entry."""
    all_stoplist_name = "Ship Class Conversions"
    terms = pe._static_paragraph_identity_candidate_terms(all_stoplist_name)
    # Every word in the name IS a stopword, so stripping leaves nothing -
    # falls back to the bare last word, exactly like the pre-G22 helper did.
    assert terms == ["conversions"]

    validate = pe.PipelineExecutor._validate_static_unit_paragraph
    paragraph_with_word = _natural_paragraph(
        "This entry only ever gets called out through its own generic bookkeeping word.",
        "The paragraph names the fallback conversions term explicitly right here.",
        "No specific ship name exists for this constructed edge case on purpose.",
        "The fallback must still legalize the paragraph through that one word.",
        "Padding sentence to clear the hard word floor for this synthetic fixture only.",
    )
    warnings = validate(all_stoplist_name, paragraph_with_word)
    assert not any(w.startswith("missing locked machine designation") for w in warnings), warnings

    paragraph_without_word = _natural_paragraph(
        "This entry is discussed here without ever using its own fallback bookkeeping term.",
        "Every sentence carefully avoids the one word that would legalize it under the fallback.",
        "No specific ship name exists for this constructed edge case on purpose.",
        "The gate must still correctly block since neither a code nor the fallback word appears.",
        "Padding sentence to clear the hard word floor for this synthetic fixture only.",
    )
    warnings = validate(all_stoplist_name, paragraph_without_word)
    assert any(w.startswith("missing locked machine designation") for w in warnings), warnings
