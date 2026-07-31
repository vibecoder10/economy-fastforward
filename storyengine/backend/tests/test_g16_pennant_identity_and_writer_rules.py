"""G16: pennant-tolerant identity match + writer prompt carries content rules.

Real evidence from a live 5-ship run (video d05efae3-46f8-4ee3-b690-849c3ca31fbc):
locked roster display names for ship-style DVsU rosters carry a leading
pennant/hull-number token ("53 HMS Prince of Wales", "41 HMS King George V",
"17 Duke of York", "79 Anson", "32 HMS Howe"). A model naturally writes the
name without that token ("HMS Prince of Wales"), which used to trip the
identity-vs-locked-machine check with "card unit does not match locked
machine 53 HMS Prince of Wales" even though the card was plainly about the
right ship.

Separately, two other blocking warnings from the same run
("visual_identity must include concrete visible machine features" and
"why_this_unit_deserves_a_paragraph must name a concrete engineering
decision, problem, tradeoff, or consequence") were rules the FIRST-pass
writer prompt never stated - the model only learned them after failing and
burning a paid repair round.

These tests are local/no-spend (fake Anthropic client, no real API calls).
"""

import asyncio
import copy
import json

import pipeline_executor as pe


# ---------------------------------------------------------------------------
# Shared fixtures (self-contained - deliberately not imported from
# test_machine_documentary_hold.py so this file's swap-proof stays isolated).
# ---------------------------------------------------------------------------

def _evidence_segments() -> list[dict]:
    rows = [
        ("E-PROBLEM", "original_problem", "Original problem claim grounded in the supplied source."),
        ("E-ROLE", "role_category", "Role category claim grounded in the supplied source."),
        ("E-DECISION", "engineering_decision", "Engineering decision claim grounded in the supplied source with hull, deck, and turret features."),
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


def _visual_identity_fields(machine: str) -> dict:
    return {
        "visual_identity": f"{machine} identified by its broad flight deck, tall bridge, and forward gun turret.",
        "visual_identity_evidence_ids": ["E-DECISION"],
    }


def _timeframe_fields(machine: str) -> dict:
    return {
        "timeframe": f"{machine} documented through its wartime service period.",
        "timeframe_evidence_ids": ["E-REALITY"],
    }


def _valid_research_card(machine: str, **overrides) -> dict:
    card = {
        "unit": machine,
        "engineering_thesis": f"{machine} mattered because its speed decision exposed armor tradeoffs in service.",
        "why_this_unit_deserves_a_paragraph": (
            f"{machine} deserves a paragraph because its speed requirement exposed a tradeoff "
            "between armor, power, and service reality."
        ),
        "surprising_fact": "Memorable fact claim grounded in the supplied source.",
        "source_notes": ["test-source"],
        "evidence_segments": _evidence_segments(),
    }
    card.update(_visual_identity_fields(machine))
    card.update(_timeframe_fields(machine))
    card.update(overrides)
    return card


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


# ---------------------------------------------------------------------------
# Fix 1: pennant/hull-number tolerance
# ---------------------------------------------------------------------------

def test_locked_machine_identity_codes_strips_only_a_leading_digit_token():
    """The helper's own contract: the locked code as written, plus - only
    when the name opens with a standalone digit token - the code with that
    token stripped. A name with no leading digit is untouched (single code)."""
    with_pennant = pe._locked_machine_identity_codes("53 HMS Prince of Wales")
    assert pe._normalized_unit_code("53 HMS Prince of Wales") in with_pennant
    assert pe._normalized_unit_code("HMS Prince of Wales") in with_pennant

    without_pennant = pe._locked_machine_identity_codes("HMS Prince of Wales")
    assert without_pennant == {pe._normalized_unit_code("HMS Prince of Wales")}

    # A sibling's own different pennant/name never lands in this set.
    sibling = pe._locked_machine_identity_codes("53 HMS King George V")
    assert pe._normalized_unit_code("HMS Prince of Wales") not in sibling


def test_card_unit_matches_locked_machine_despite_missing_pennant_prefix():
    """The real bug: card roster_index 2 (machine "53 HMS Prince of Wales")
    blocked with "card unit does not match locked machine 53 HMS Prince of
    Wales" because the model wrote the unit as "HMS Prince of Wales" (no
    pennant). Same shape proven for every real name from the live roster."""
    real_locked_names = [
        "53 HMS Prince of Wales",
        "41 HMS King George V",
        "17 Duke of York",
        "79 Anson",
        "32 HMS Howe",
    ]
    for locked_name in real_locked_names:
        without_pennant = locked_name.split(" ", 1)[1]
        card = {"unit": without_pennant}
        warnings = pe._research_card_contract_warnings(locked_name, card)
        assert not any(
            w.startswith("card unit does not match locked machine") for w in warnings
        ), f"{locked_name!r}: {warnings}"


def test_card_unit_pennant_tolerance_still_rejects_a_sibling_machine():
    """Do NOT loosen anything else: "HMS Prince of Wales" must still NOT
    match locked "53 HMS King George V" - cross-machine sibling screening
    stays intact."""
    card = {"unit": "HMS Prince of Wales"}
    warnings = pe._research_card_contract_warnings("53 HMS King George V", card)
    assert any(
        w == "card unit does not match locked machine 53 HMS King George V"
        for w in warnings
    ), warnings


def test_card_unit_exact_match_with_pennant_still_passes():
    """Regression: a card that DOES include the pennant verbatim (exact
    match, no stripping needed) is unaffected by the new tolerance."""
    card = {"unit": "53 HMS Prince of Wales"}
    warnings = pe._research_card_contract_warnings("53 HMS Prince of Wales", card)
    assert not any(
        w.startswith("card unit does not match locked machine") for w in warnings
    ), warnings


def test_field_specificity_checks_tolerate_missing_pennant_prefix():
    """The same style of check ("first-4-tokens" fallback code) lives inside
    visual_identity/timeframe/why_this_unit_deserves_a_paragraph's own
    "must be specific to the locked machine" gate. Prove all three tolerate
    the missing pennant the same way as the card-unit emitter."""
    machine = "53 HMS Prince of Wales"
    unprefixed = "HMS Prince of Wales"

    visual_warnings = pe._visual_identity_warnings(
        machine,
        f"{unprefixed} identified by its broad flight deck, tall bridge, and forward gun turret.",
        [], [],
    )
    assert "visual_identity must be specific to the locked machine" not in visual_warnings

    timeframe_warnings = pe._timeframe_warnings(
        machine,
        f"{unprefixed} documented through its wartime service period.",
        [], [],
    )
    assert "timeframe must be specific to the locked machine" not in timeframe_warnings

    paragraph_warnings = pe._paragraph_worth_warnings(
        machine,
        f"{unprefixed} deserves a paragraph because its speed requirement exposed a tradeoff "
        "between armor, power, and service reality.",
    )
    assert "why_this_unit_deserves_a_paragraph must be specific to the locked machine" not in paragraph_warnings


# ---------------------------------------------------------------------------
# Fix 1 companion: the content-shape rule itself is UNCHANGED - only the
# writer prompt now teaches it upfront. A card that genuinely fails must
# still fail.
# ---------------------------------------------------------------------------

def test_visual_identity_content_rule_still_blocks_generic_text():
    warnings = pe._visual_identity_warnings(
        "53 HMS Prince of Wales",
        "This is a truly remarkable and unforgettable piece of naval engineering history.",
        [], [],
    )
    assert pe._VISUAL_IDENTITY_CONTENT_RULE in warnings


def test_why_paragraph_content_rule_still_blocks_generic_text():
    warnings = pe._paragraph_worth_warnings(
        "53 HMS Prince of Wales",
        "HMS Prince of Wales was famous and legendary and deserves a paragraph in this video.",
    )
    assert pe._WHY_PARAGRAPH_CONTENT_RULE in warnings


# ---------------------------------------------------------------------------
# Fix 2: writer prompt states the content rules upfront, shared verbatim
# with the validator (single source of truth, never drifts).
# ---------------------------------------------------------------------------

def test_content_rule_constants_match_the_validators_own_warning_text():
    """The constants ARE what the validators emit - not a re-typed copy."""
    assert pe._VISUAL_IDENTITY_CONTENT_RULE == "visual_identity must include concrete visible machine features"
    assert pe._WHY_PARAGRAPH_CONTENT_RULE == (
        "why_this_unit_deserves_a_paragraph must name a concrete engineering decision, "
        "problem, tradeoff, or consequence"
    )

    # And the validators actually append these exact constants, not literals
    # that happen to read the same - prove by identity-safe equality on the
    # emitted warning for a text that fails only that one rule.
    visual_warnings = pe._visual_identity_warnings(
        "Boeing XB-15",
        "This is a truly remarkable and unforgettable piece of aviation engineering history.",
        [], [],
    )
    assert pe._VISUAL_IDENTITY_CONTENT_RULE in visual_warnings

    paragraph_warnings = pe._paragraph_worth_warnings(
        "Boeing XB-15",
        "Boeing XB-15 was famous and legendary and deserves a paragraph in this video.",
    )
    assert pe._WHY_PARAGRAPH_CONTENT_RULE in paragraph_warnings


def test_writer_rule_lines_carry_the_shared_constants_verbatim():
    assert pe._VISUAL_IDENTITY_CONTENT_RULE in pe._visual_identity_writer_rule_line()
    assert pe._WHY_PARAGRAPH_CONTENT_RULE in pe._why_paragraph_writer_rule_line()


def test_writer_prompt_rendering_teaches_both_content_rules_upfront(monkeypatch):
    """End-to-end: render the ACTUAL first-pass card-writing prompt built by
    _run_unit_research_hold (not a static source-grep) and prove it states
    both content-shape rules verbatim, using the same shared constants the
    validators emit. First drafts should be born knowing the rules instead
    of learning them from a paid repair round."""
    machine = "53 HMS Prince of Wales"
    roster_names = [machine]
    payload = {"unit_roster": roster_names, "fact_sheet": "Source-grounded background."}
    passing_card = _valid_research_card(machine)

    class FakeAnthropic:
        def __init__(self):
            self.prompts = []

        async def generate(self, **kwargs):
            self.prompts.append(kwargs["prompt"])
            return json.dumps(passing_card)

    fake_anthropic = FakeAnthropic()
    executor = pe.PipelineExecutor.__new__(pe.PipelineExecutor)
    executor.tenant_id = "tenant-test"
    executor.__dict__["_pipeline"] = type("FakePipeline", (), {"anthropic": fake_anthropic})()

    async def fake_execute(query, *args, **_kwargs):
        return None

    async def fake_fetch_all(*args, **_kwargs):
        return []

    async def fake_log(*_args, **_kwargs):
        return None

    async def fake_gather(_title, target_machine, _payload):
        return _verified_package_for_segments(target_machine, _evidence_segments())

    monkeypatch.setattr(pe, "execute", fake_execute)
    monkeypatch.setattr(pe, "fetch_all", fake_fetch_all)
    monkeypatch.setattr(executor, "_log_activity", fake_log)
    monkeypatch.setattr(executor, "_gather_verified_machine_source_package", fake_gather)

    asyncio.run(
        executor._run_unit_research_hold(
            "video-test", "Designed vs Used", payload, roster_names, target_machine=machine,
        )
    )

    assert fake_anthropic.prompts, "no card-writing prompt was ever rendered"
    first_pass_prompt = fake_anthropic.prompts[0]
    assert pe._WHY_PARAGRAPH_CONTENT_RULE in first_pass_prompt
    assert pe._VISUAL_IDENTITY_CONTENT_RULE in first_pass_prompt
    # Actionable, not just the bare rule sentence: the example vocabulary is
    # pulled from the SAME word list the validator's regex matches against.
    assert "because" in first_pass_prompt and "tradeoff" in first_pass_prompt
    assert "deck" in first_pass_prompt or "hull" in first_pass_prompt
