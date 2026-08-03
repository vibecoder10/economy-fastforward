"""G20: language-polish pass - grammar fixed, facts locked, referee re-checks.

The DVsU fact-grounding referee (_validate_machine_story_sentences /
_validate_static_unit_paragraph) is airtight on WHAT is claimed but has no
grammar/flow check. Real stored previews from video d2e37cd6 ("Every British
Aircraft Carrier Class Ever Built") shipped PASSING with grammar garbled by
the writer's own "prefer the evidence's own concrete nouns" pressure:

- "The revised requirement called for a large caliber ever designed for any
  Royal Navy ship" (locked evidence says "...so far ever designed..." - the
  writer dropped "so far" trying to stay close to evidence wording)
- "a ship that did not fired the guns she was born to carry" (broken verb)
- "Laid up in June about 1915 ... by the late about 1930s" (jammed date
  construction - "about" squeezed next to a written-out date)

This chunk adds ONE cheap-tier ("Models.CLAUDE_HAIKU") language-polish call
after the draft settles, then re-runs the SAME validators on the polished
text. Polish can only ever improve or no-op: any NEW blocking warning discards
the polish and keeps the draft untouched (_apply_dvsu_language_polish).

These tests are local/no-spend: every Anthropic call goes through a fake
client with scripted or algorithmic replies.
"""

import asyncio
import json

import pipeline_executor as pe


MACHINE = "HMS Furious (47) Furious"


# ---------------------------------------------------------------------------
# Shared fixture: a REAL-STYLE HMS Furious research card + the REAL glitched
# paragraph text pulled from video d2e37cd6's stored machine_script_previews
# (research_payload->machine_script_previews->HMSFURIOUS47FURIOUS). Verified
# empirically (see this chunk's dev notes) to reproduce prod's own "passed:
# true, advisory-only warnings" outcome under _validate_machine_story_sentences
# - i.e. this glitched paragraph really does clear the fact-grounding gate
# today, which is exactly the bug this chunk closes.
# ---------------------------------------------------------------------------

def _furious_evidence_segments() -> list[dict]:
    rows = [
        ("furious-ev1", "original_problem",
         "The revised requirement included two BL 18-inch Mk I guns, the "
         "largest caliber so far ever designed for any Royal Navy ship."),
        ("furious-ev2", "engineering_decision",
         "Squadron Commander Edwin Dunning first landed a Sopwith Pup aboard "
         "in summer 1917, the first attempt of its kind. On the third landing "
         "the engine choked and the aircraft crashed off the starboard bow, "
         "killing him."),
        ("furious-ev6", "engineering_decision",
         "Dunning's August 1917 landing was the first successful deck landing "
         "of an aircraft on a moving ship."),
        ("furious-ev3", "tradeoff",
         "HMS Furious had engine trouble which limited her speed to around 23 "
         "knots. The fatal crash exposed grave deck arrangement limitations "
         "that motivated a complete redesign."),
        ("furious-ev4", "reality",
         "Laid up in June 1915 and completed in June 1917, HMS Furious was "
         "taken in hand for conversion to an aircraft carrier that November, "
         "several months after service as a modified hybrid battlecruiser, "
         "then dispatched in April 1940 with eighteen Swordfish whose torpedo "
         "attack on German ships at Trondheim achieved nothing."),
    ]
    numeric_tokens = {
        "furious-ev1": [],
        "furious-ev2": ["1917"],
        "furious-ev6": ["1917"],
        "furious-ev3": ["23"],
        "furious-ev4": ["1915", "1917", "1940", "18"],
    }
    urls = {
        "furious-ev1": "https://naval-encyclopedia.com/test/original_problem",
        "furious-ev2": "https://naval-encyclopedia.com/test/engineering_decision",
        "furious-ev6": "https://www.rmg.co.uk/test/engineering_decision",
        "furious-ev3": "https://naval-encyclopedia.com/test/tradeoff",
        "furious-ev4": "https://naval-encyclopedia.com/test/reality",
    }
    return [
        {
            "evidence_id": evidence_id,
            "kind": kind,
            "claim": claim,
            "source_excerpt": claim,
            "source_url": urls[evidence_id],
            "source_title": "Test naval source",
            "locator": f"{evidence_id}-loc",
            "numeric_tokens": numeric_tokens[evidence_id],
            "confidence": "high",
        }
        for evidence_id, kind, claim in rows
    ]


def _valid_research_card() -> dict:
    return {
        "unit": MACHINE,
        "engineering_thesis": (
            "HMS Furious mattered because her abandoned gun platform became "
            "the Royal Navy's first full-deck carrier."
        ),
        "why_this_unit_deserves_a_paragraph": (
            "HMS Furious deserves a paragraph because her gun-platform origin "
            "and fatal test landings exposed the real cost of carrier aviation."
        ),
        "surprising_fact": "The third deck landing killed the pilot who proved the concept.",
        "source_notes": ["furious-source"],
        "evidence_segments": _furious_evidence_segments(),
        "visual_identity": f"{MACHINE} identified by her flush flight deck and island-free silhouette.",
        "visual_identity_evidence_ids": ["furious-ev2"],
        "timeframe": f"{MACHINE} documented through her First World War and Second World War service.",
        "timeframe_evidence_ids": ["furious-ev4"],
    }


def _verified_package_for_segments(segments: list[dict]) -> dict:
    return {
        "passed": True,
        "machine": MACHINE,
        "machine_key": pe._normalized_unit_code(MACHINE),
        "search_queries": [f'"{MACHINE}" verified source'],
        "sources": [
            {
                "source_id": segment["evidence_id"],
                "title": segment["source_title"],
                "url": segment["source_url"],
                "text_hash": "test",
                "text_chars": len(segment["source_excerpt"]),
            }
            for segment in segments
        ],
        "candidate_excerpts": [
            {
                "excerpt_id": segment["locator"],
                "source_id": segment["evidence_id"],
                "source_title": segment["source_title"],
                "source_url": segment["source_url"],
                "locator": segment["locator"],
                "text": segment["source_excerpt"],
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
            for segment in segments
        ],
    }


# The REAL glitched draft (video d2e37cd6, HMSFURIOUS47FURIOUS preview,
# "passed": true - only advisory warnings). Slot order matches formula:
# original_problem, engineering_decision, tradeoff, reality, closer.
DRAFT_SENTENCES = [
    "The revised requirement called for a large caliber ever designed for any "
    "Royal Navy ship, but the ambition lasted months before the hull's "
    "purpose changed entirely.",
    "A plan illustrating her conversion to a full flight deck followed "
    "Squadron Commander Edwin Dunning's landing of a Sopwith Pup in summer "
    "1917, the first attempt of its kind, though the third landing killed "
    "him when his engine choked and the aircraft crashed off the starboard "
    "bow.",
    "Engine trouble limited her speed to around twenty-three knots, and the "
    "fatal crash exposed grave deck arrangement limitations that motivated a "
    "complete redesign.",
    "Laid up in June about 1915 and completed in June 1917, HMS Furious was "
    "taken in hand for conversion to an aircraft carrier that November, "
    "several months after service as a modified hybrid battlecruiser, then "
    "dispatched in April 1940 with eighteen Swordfish whose torpedo attack on "
    "German ships at Trondheim achieved nothing.",
    "The Royal Navy learned carrier aviation by killing its pioneers on a "
    "ship that did not fired the guns she was born to carry.",
]

# The correct grammar-only fix: "so far" restored, jammed "about" removed,
# broken verb fixed. Every fact, number, date, and name is untouched.
CORRECTED_SENTENCES = [
    "The revised requirement called for a large caliber so far ever designed "
    "for any Royal Navy ship, but the ambition lasted months before the "
    "hull's purpose changed entirely.",
    DRAFT_SENTENCES[1],
    DRAFT_SENTENCES[2],
    "Laid up in June 1915 and completed in June 1917, HMS Furious was taken "
    "in hand for conversion to an aircraft carrier that November, several "
    "months after service as a modified hybrid battlecruiser, then "
    "dispatched in April 1940 with eighteen Swordfish whose torpedo attack on "
    "German ships at Trondheim achieved nothing.",
    "The Royal Navy learned carrier aviation by killing its pioneers on a "
    "ship that did not fire the guns she was born to carry.",
]

_SLOTS = ["original_problem", "engineering_decision", "tradeoff", "reality"]
_EVIDENCE_IDS = [["furious-ev1"], ["furious-ev2", "furious-ev6"], ["furious-ev3"], ["furious-ev4"]]


def _bundle_for(sentences: list[str]) -> dict:
    return {
        "editorial_thesis": (
            "HMS Furious evolved from an abandoned gun platform into the "
            "Royal Navy's first full-deck carrier, teaching the service how "
            "to operate naval aviation through fatal trial and error."
        ),
        "twist": {
            "type": "ironic_outcome",
            "substitute": None,
            "summary": "Built for guns she never fired, converted to a carrier that killed its pioneering test pilot.",
        },
        "formula_sentences": list(sentences),
        "paragraph": " ".join(sentences),
        "claim_map": [
            {"slot": slot, "span": sentence, "used_evidence_ids": eids}
            for slot, sentence, eids in zip(_SLOTS, sentences, _EVIDENCE_IDS)
        ],
        "onscreen_label": "",
    }


def _furious_plan() -> dict:
    payload = {"unit_research_cards": [{"unit": MACHINE, "evidence_segments": _furious_evidence_segments()}]}
    return pe._machine_story_plan(payload, MACHINE)


def _draft_paragraph_and_warnings():
    plan = _furious_plan()
    bundle = _bundle_for(DRAFT_SENTENCES)
    paragraph, warnings = pe._validate_machine_story_sentences(MACHINE, plan, bundle, {})
    return plan, bundle, paragraph, warnings


def test_furious_glitch_fixture_passes_validation_today():
    """Proves the bug this chunk closes: the REAL garbled paragraph clears
    the fact-grounding referee with zero blocking warnings - "did not fired"
    and the dropped "so far" ship untouched today because nothing checks
    grammar."""
    _plan, _bundle, paragraph, warnings = _draft_paragraph_and_warnings()
    assert not pe._blocking_warnings(warnings)
    assert "did not fired the guns" in paragraph
    assert "a large caliber ever designed" in paragraph
    assert "in June about 1915" in paragraph


# ---------------------------------------------------------------------------
# (a) glitch fixture polished by a fake client -> re-validated -> the fixed
# text stored, polished=True, pre_polish_paragraph carries the original draft.
# ---------------------------------------------------------------------------

class _FakePolishClient:
    def __init__(self, reply_sentences):
        self._reply_sentences = reply_sentences
        self.calls = 0
        self.prompts = []

    async def generate(self, **kwargs):
        self.calls += 1
        self.prompts.append(kwargs["prompt"])
        return json.dumps(self._reply_sentences)


def test_polish_fixes_the_real_glitches_and_stores_audit_trail():
    plan, draft_bundle, draft_paragraph, draft_warnings = _draft_paragraph_and_warnings()
    fake = _FakePolishClient(CORRECTED_SENTENCES)

    result = asyncio.run(pe._apply_dvsu_language_polish(
        anthropic_client=fake,
        machine=MACHINE,
        paragraph=draft_paragraph,
        warnings=draft_warnings,
        bundle=draft_bundle,
        story_plan=plan,
        dvsu_rule_overrides={},
        opening_brief="Do NOT open with the machine name. Open with a paradox or contradiction.",
    ))

    assert fake.calls == 1
    assert result["polished"] is True
    assert result["pre_polish_paragraph"] == draft_paragraph
    # The three real glitches are gone...
    assert "did not fired the guns" not in result["paragraph"]
    assert "a large caliber ever designed" not in result["paragraph"]
    assert "in June about 1915" not in result["paragraph"]
    # ...and the grammar-correct facts are in place, with no fact changed.
    assert "did not fire the guns" in result["paragraph"]
    assert "large caliber so far ever designed" in result["paragraph"]
    assert "in June 1915" in result["paragraph"]
    assert "twenty-three knots" in result["paragraph"]
    assert "eighteen Swordfish" in result["paragraph"]
    assert "April 1940" in result["paragraph"]
    # Facts stay locked: the referee re-approves the polished text.
    assert not pe._blocking_warnings(result["warnings"])
    # claim_map spans were re-keyed to the polished sentences so the SAME
    # validator can still find each span inside its formula sentence.
    assert result["bundle"]["claim_map"][0]["span"] == CORRECTED_SENTENCES[0]
    assert result["bundle"]["claim_map"][3]["span"] == CORRECTED_SENTENCES[3]
    # Polish prompt carries the no-new-facts law.
    assert "never add, remove, or alter any fact, number, date, name, or claim" in fake.prompts[0]


# ---------------------------------------------------------------------------
# (b) a fake polish that BREAKS grounding (changes a sourced number) is
# discarded; the draft is kept untouched and polished=False.
# ---------------------------------------------------------------------------

def test_polish_that_changes_a_number_is_discarded_and_draft_kept():
    plan, draft_bundle, draft_paragraph, draft_warnings = _draft_paragraph_and_warnings()
    broken_sentences = list(DRAFT_SENTENCES)
    broken_sentences[2] = broken_sentences[2].replace("twenty-three knots", "thirty knots")
    fake = _FakePolishClient(broken_sentences)

    # Sanity: prove the broken text really would introduce a NEW blocking
    # warning if nothing guarded against it - otherwise this test would pass
    # for the wrong reason.
    _bp, broken_warnings = pe._validate_machine_story_sentences(MACHINE, plan, _bundle_for(broken_sentences), {})
    assert pe._blocking_warnings(broken_warnings)

    result = asyncio.run(pe._apply_dvsu_language_polish(
        anthropic_client=fake,
        machine=MACHINE,
        paragraph=draft_paragraph,
        warnings=draft_warnings,
        bundle=draft_bundle,
        story_plan=plan,
        dvsu_rule_overrides={},
        opening_brief="Do NOT open with the machine name. Open with a paradox or contradiction.",
    ))

    assert result["polished"] is False
    assert result["pre_polish_paragraph"] is None
    assert result["paragraph"] == draft_paragraph
    assert result["bundle"] is draft_bundle
    assert result["warnings"] == draft_warnings


# ---------------------------------------------------------------------------
# (c) a polish provider that errors (or replies with garbage) never crashes
# script-hold - the draft is kept, polished=False.
# ---------------------------------------------------------------------------

class _ErroringClient:
    async def generate(self, **_kwargs):
        raise RuntimeError("polish provider unavailable")


class _MalformedReplyClient:
    async def generate(self, **_kwargs):
        return "this is not JSON at all {"


class _WrongShapeReplyClient:
    async def generate(self, **_kwargs):
        return json.dumps(["too", "few", "sentences"])


def test_polish_provider_error_keeps_draft_no_crash():
    plan, draft_bundle, draft_paragraph, draft_warnings = _draft_paragraph_and_warnings()

    for client in (_ErroringClient(), _MalformedReplyClient(), _WrongShapeReplyClient()):
        result = asyncio.run(pe._apply_dvsu_language_polish(
            anthropic_client=client,
            machine=MACHINE,
            paragraph=draft_paragraph,
            warnings=draft_warnings,
            bundle=draft_bundle,
            story_plan=plan,
            dvsu_rule_overrides={},
            opening_brief="Do NOT open with the machine name. Open with a paradox or contradiction.",
        ))
        assert result["polished"] is False
        assert result["paragraph"] == draft_paragraph
        assert result["warnings"] == draft_warnings


# ---------------------------------------------------------------------------
# (e) a currently-passing CLEAN paragraph still gets a polish attempt, but a
# no-op reply (identical sentences) stores identical text and polished=False.
# ---------------------------------------------------------------------------

def test_polish_noop_on_already_clean_paragraph_stores_identical_text():
    plan, _bundle, _paragraph, _warnings = _draft_paragraph_and_warnings()
    clean_sentences = CORRECTED_SENTENCES
    clean_bundle = _bundle_for(clean_sentences)
    clean_paragraph, clean_warnings = pe._validate_machine_story_sentences(MACHINE, plan, clean_bundle, {})
    assert not pe._blocking_warnings(clean_warnings)

    fake = _FakePolishClient(clean_sentences)
    result = asyncio.run(pe._apply_dvsu_language_polish(
        anthropic_client=fake,
        machine=MACHINE,
        paragraph=clean_paragraph,
        warnings=clean_warnings,
        bundle=clean_bundle,
        story_plan=plan,
        dvsu_rule_overrides={},
        opening_brief="Do NOT open with the machine name. Open with a paradox or contradiction.",
    ))

    assert fake.calls == 1, "polish must still run on an already-clean paragraph"
    assert result["polished"] is False
    assert result["paragraph"] == clean_paragraph
    assert result["pre_polish_paragraph"] is None


# ---------------------------------------------------------------------------
# (d) the writer prompt's vocabulary guidance carries the grammar-outranks-
# vocabulary law - single shared constant, not re-typed text.
# ---------------------------------------------------------------------------

def test_grammar_outranks_vocabulary_rule_constant_shape():
    assert pe._GRAMMAR_OUTRANKS_VOCABULARY_RULE.startswith("Grammatical correctness always outranks")
    assert "function" in pe._GRAMMAR_OUTRANKS_VOCABULARY_RULE
    assert "concrete nouns and numbers" in pe._GRAMMAR_OUTRANKS_VOCABULARY_RULE


# ---------------------------------------------------------------------------
# Generic single-machine fixture (mirrors test_machine_documentary_hold.py's
# proven _evidence_segments/_valid_research_card/_verified_package_for_segments
# shape byte-for-byte) for the two end-to-end _run_static_script_hold tests
# below - these need to clear the FULL research-card contract gate
# (visual_identity grounding, memorable_fact segment, designed-vs-used gap,
# verified source package), which the Furious fixture above deliberately
# keeps minimal for the direct-validator unit tests.
# ---------------------------------------------------------------------------

_GENERIC_MACHINE = "Boeing XB-15"


def _generic_evidence_segments() -> list[dict]:
    rows = [
        ("E-PROBLEM", "original_problem", "Original problem claim grounded in the supplied source."),
        ("E-ROLE", "role_category", "Role category claim grounded in the supplied source."),
        ("E-DECISION", "engineering_decision",
         "Engineering decision claim grounded in the supplied source with wing, engine, tail, nose, and fuselage features."),
        ("E-TRADEOFF", "tradeoff", "Tradeoff claim grounded in the supplied source."),
        ("E-REALITY", "reality", "Reality claim grounded in the supplied source through its Cold War service period."),
        ("E-MEMORABLE", "memorable_fact", "Memorable fact claim grounded in the supplied source."),
        ("E-MEANING", "historical_meaning", "Historical meaning claim grounded in the supplied source."),
        ("E-LABEL", "onscreen_label", "Onscreen label claim grounded in the supplied source."),
    ]
    return [
        {
            "evidence_id": evidence_id, "kind": kind, "claim": claim, "source_excerpt": claim,
            "source_url": f"https://airandspace.si.edu/test/{kind}", "source_title": "Test source",
            "locator": f"S{index}-E1", "numeric_tokens": [], "confidence": "high",
        }
        for index, (evidence_id, kind, claim) in enumerate(rows, start=1)
    ]


def _generic_valid_research_card() -> dict:
    return {
        "unit": _GENERIC_MACHINE,
        "engineering_thesis": f"{_GENERIC_MACHINE} mattered because its design promise had to survive real operating limits.",
        "why_this_unit_deserves_a_paragraph": (
            f"{_GENERIC_MACHINE} deserves a paragraph because its problem exposed a "
            "tradeoff between design and reality."
        ),
        "surprising_fact": "Memorable fact claim grounded in the supplied source.",
        "source_notes": [f"{_GENERIC_MACHINE}-source"],
        "evidence_segments": _generic_evidence_segments(),
        "visual_identity": f"{_GENERIC_MACHINE} identified by its wing, engine, tail, nose, and fuselage features.",
        "visual_identity_evidence_ids": ["E-DECISION"],
        "timeframe": f"{_GENERIC_MACHINE} documented through its Cold War service period.",
        "timeframe_evidence_ids": ["E-REALITY"],
    }


def _generic_verified_package(segments: list[dict]) -> dict:
    return {
        "passed": True, "machine": _GENERIC_MACHINE, "machine_key": pe._normalized_unit_code(_GENERIC_MACHINE),
        "search_queries": [f'"{_GENERIC_MACHINE}" verified source'],
        "sources": [
            {"source_id": f"S{index}", "title": segment["source_title"], "url": segment["source_url"],
             "text_hash": "test", "text_chars": len(segment["source_excerpt"])}
            for index, segment in enumerate(segments, start=1)
        ],
        "candidate_excerpts": [
            {
                "excerpt_id": f"S{index}-E1", "source_id": f"S{index}", "source_title": segment["source_title"],
                "source_url": segment["source_url"], "locator": segment.get("locator") or f"S{index}-E1",
                "text": f"{_GENERIC_MACHINE} {segment['source_excerpt']}", "text_hash": "test",
                "source_capture_method": "fetched_page",
                "source_variant_selection": {
                    "selected_capture_method": "fetched_page",
                    "selected_variant": {"source_capture_method": "fetched_page", "covered_slot_count": 4, "distinct_slot_excerpt_count": 4},
                    "evaluated_variants": [{"source_capture_method": "fetched_page", "covered_slot_count": 4}],
                    "selection_rule": "highest Anton-slot coverage; fetched_page wins exact ties",
                },
            }
            for index, segment in enumerate(segments, start=1)
        ],
    }


_GENERIC_SLOTS = ["original_problem", "engineering_decision", "tradeoff", "reality"]
_GENERIC_IDS = [["E-PROBLEM"], ["E-DECISION"], ["E-TRADEOFF"], ["E-REALITY"]]

# A real-pattern glitched draft using only words the generic evidence already
# grounds: a dropped "grounded" (word-squeeze), a jammed "about", and a
# broken "did not fired" verb in the (non-claim-mapped) closer. Padded past
# the 80-word hard floor so no EDIT round fires before the polish call.
_GENERIC_DRAFT_SENTENCES = [
    f"{_GENERIC_MACHINE} original problem claim in the supplied source.",
    "Engineering decision claim grounded in the supplied source with wing, engine, "
    "tail, nose, and fuselage features clear clear clear clear.",
    "Tradeoff claim grounded in the supplied source clear clear clear clear clear "
    "clear clear clear clear clear clear clear clear clear clear.",
    "Reality claim grounded in about the supplied source through its Cold War service period.",
    "The machine that did not fired the guns survived on the proof it gave instead.",
]
_GENERIC_CORRECTED_SENTENCES = [
    f"{_GENERIC_MACHINE} original problem claim grounded in the supplied source.",
    _GENERIC_DRAFT_SENTENCES[1],
    _GENERIC_DRAFT_SENTENCES[2],
    "Reality claim grounded in the supplied source through its Cold War service period.",
    "The machine that did not fire the guns survived on the proof it gave instead.",
]


def _generic_bundle_json(sentences: list[str]) -> str:
    return json.dumps({
        "editorial_thesis": f"{_GENERIC_MACHINE} mattered because its design promise had to survive real operating limits.",
        "twist": {"type": "role_change", "substitute": None, "summary": "Built for the promise, used as the proof."},
        "formula_sentences": sentences,
        "paragraph": " ".join(sentences),
        "claim_map": [
            {"slot": slot, "span": sentence, "used_evidence_ids": ids}
            for slot, sentence, ids in zip(_GENERIC_SLOTS, sentences, _GENERIC_IDS)
        ],
        "onscreen_label": "",
    })


def _generic_video() -> dict:
    roster = [_GENERIC_MACHINE]
    return {
        "video_title": "Every US Strategic Bomber Ever Built",
        "render_mode": "static_docu",
        "research_payload": {
            "documentary_style": "designed_vs_used",
            "unit_roster": roster,
            "unit_research_cards": [_generic_valid_research_card()],
            "machine_raw_source_packages": {
                pe._verified_source_cache_key(_GENERIC_MACHINE): _generic_verified_package(_generic_evidence_segments()),
            },
        },
    }


def _generic_executor_scaffold(fake_anthropic, monkeypatch):
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

    def passed_quality_audit(*_args, **_kwargs):
        return {
            "passed": True,
            "checks": [{"name": "validator_warnings", "label": "Validator warnings", "passed": True, "detail": "clean"}],
            "summary": "Anton quality audit passed",
        }

    monkeypatch.setattr(pe, "execute", fake_execute)
    monkeypatch.setattr(pe, "fetch_all", fake_fetch_all)
    monkeypatch.setattr(pe, "_anton_preview_quality_audit", passed_quality_audit)
    monkeypatch.setattr(executor, "_log_activity", fake_log)
    return executor


def test_inventory_mode_first_pass_prompt_states_grammar_outranks_vocabulary(monkeypatch):
    """End-to-end: render the ACTUAL first-pass inventory-mode write prompt
    (voice_rules block inside _run_static_script_hold) and prove it states
    the outranking rule verbatim via the shared constant - the same technique
    G16/G17 used for their own writer-prompt rule audits."""
    video = _generic_video()
    roster = [_GENERIC_MACHINE]

    class FakeAnthropic:
        def __init__(self):
            self.prompts = []

        async def generate(self, **kwargs):
            self.prompts.append(kwargs["prompt"])
            marker = "SENTENCES (JSON array, one entry per sentence, in order):\n"
            if marker in kwargs["prompt"]:
                start = kwargs["prompt"].index(marker) + len(marker)
                end = kwargs["prompt"].index("\n\n", start)
                return kwargs["prompt"][start:end]
            return _generic_bundle_json(_GENERIC_DRAFT_SENTENCES)

    fake_anthropic = FakeAnthropic()
    executor = _generic_executor_scaffold(fake_anthropic, monkeypatch)

    asyncio.run(executor._run_static_script_hold("video-test", video, roster, target_machine=_GENERIC_MACHINE))

    assert fake_anthropic.prompts, "no first-pass write prompt was ever rendered"
    first_pass_prompt = fake_anthropic.prompts[0]
    assert "VOICE RULES" in first_pass_prompt
    assert pe._GRAMMAR_OUTRANKS_VOCABULARY_RULE in first_pass_prompt
    # It sits right alongside the GROUNDING rule it tempers - not a standalone
    # law disconnected from the pressure it's outranking.
    assert "GROUNDING: zero freedom in WHAT is claimed" in first_pass_prompt


# ---------------------------------------------------------------------------
# End-to-end wiring: the polish pass actually fires inside
# _run_static_script_hold's single-machine preview flow and the STORED
# preview carries polished=True + pre_polish_paragraph - not just the
# standalone helper function in isolation.
# ---------------------------------------------------------------------------

def test_single_machine_preview_stores_polished_paragraph_and_audit_trail(monkeypatch):
    video = _generic_video()
    roster = [_GENERIC_MACHINE]

    class FakeAnthropic:
        def __init__(self):
            self.prompts = []

        async def generate(self, **kwargs):
            self.prompts.append(kwargs["prompt"])
            marker = "SENTENCES (JSON array, one entry per sentence, in order):\n"
            if marker in kwargs["prompt"]:
                start = kwargs["prompt"].index(marker) + len(marker)
                end = kwargs["prompt"].index("\n\n", start)
                sentences = json.loads(kwargs["prompt"][start:end])
                assert sentences == _GENERIC_DRAFT_SENTENCES
                return json.dumps(_GENERIC_CORRECTED_SENTENCES)
            return _generic_bundle_json(_GENERIC_DRAFT_SENTENCES)

    fake_anthropic = FakeAnthropic()
    executor = _generic_executor_scaffold(fake_anthropic, monkeypatch)

    result = asyncio.run(
        executor._run_static_script_hold("video-test", video, roster, target_machine=_GENERIC_MACHINE)
    )

    assert result["status"] == "completed"
    preview = result["preview"]
    assert preview["passed"] is True
    assert preview["polished"] is True
    assert preview["pre_polish_paragraph"] == " ".join(_GENERIC_DRAFT_SENTENCES)
    assert "claim in the supplied source" not in preview["paragraph"]
    assert "claim grounded in the supplied source" in preview["paragraph"]
    assert "grounded in about the supplied source" not in preview["paragraph"]
    assert "did not fired the guns" not in preview["paragraph"]
    assert "did not fire the guns" in preview["paragraph"]
    # Two writer calls (first-pass write, no EDIT round needed) + one polish call.
    assert len(fake_anthropic.prompts) == 2
