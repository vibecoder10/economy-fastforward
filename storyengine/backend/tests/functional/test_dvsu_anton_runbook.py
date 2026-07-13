"""Lock the DVsU Anton runbook to the one-machine proof contract."""

from pathlib import Path


def _runbook() -> Path:
    return (
        Path(__file__).resolve().parents[3]
        / "notes"
        / "dvsu-anton-single-machine-pipeline.md"
    )


def test_dvsu_anton_runbook_keeps_one_machine_evidence_contract():
    text = _runbook().read_text()

    assert "Raw source package" in text or "raw source package" in text
    assert "`source_variant_selection`" in text
    assert "the evaluated capture methods, selected method, coverage counts, exact-text hashes, and the tie-break rule" in text
    assert "and to carry `source_variant_selection`" in text
    assert "compact `SOURCE_SELECTION`, `EXCERPT_TEXT_HASH`, `ANTON_SLOT_HINTS`" in text
    assert "provenance is supplied for grounding and then backfilled by validation" in text
    assert "`Raw source package missing provenance`" in text
    assert "missing `source_variant_selection` returns `readiness_preflight` instead of paying for preview" in text
    assert "`source_capture_method`, and `source_variant_selection`" in text
    assert "The story plan and preview artifact preserve that provenance" in text
    assert "compact `source_variant_selection` label beside the raw excerpt" in text
    assert "original_problem -> engineering_decision -> tradeoff -> reality" in text
    assert "Do not research or pre-write a standalone \"meaning\" beat" in text
    assert "normalizes those labels into `reality` before building `machine_story_plans`" in text
    assert "may not use them to fill `why_this_unit_deserves_a_paragraph`" in text
    assert "For the current proof, only the selected first machine is researched or previewed" in text
    assert "Current live proof row `fc73860c-a9af-444f-95a5-7f86d60503e0` needs a fresh one-machine research pass for `Boeing XB-15` before preview" in text
    assert "without `source_capture_method` or `source_variant_selection`" in text
    assert "no-spend readiness preflight for `Boeing XB-15`" in text
    assert "Run only the single-machine script preview for `Boeing XB-15` after readiness passes" in text
    assert "`benchmark_cadence` is hard-gated from the claim map" in text
    assert "claim-mapped `engineering_decision` sentence" in text


def test_dvsu_anton_runbook_keeps_failed_preview_as_review_artifact():
    text = _runbook().read_text()

    assert "Selected-machine preview gates that fail before a paragraph LLM call" in text
    assert "save a failed `machine_script_previews[<machine_key>]` artifact" in text
    assert "reviewable UI audit artifacts" in text
    assert "They still do not call Claude, mutate `scripts`, update `script_validation`, or advance the video" in text
    assert "/machine-script-preview-readiness/{video_id}" in text
    assert "readiness preflight is read-only" in text
    assert "`readiness_preflight`" in text
    assert "paid preview did not run" in text
    assert "Do not run broad research or full script generation" in text


def test_dvsu_anton_runbook_keeps_script_briefs_evidence_derived():
    text = _runbook().read_text()

    assert "Saved `machine_script_briefs` are review aids only and are derived from validated evidence rows" in text
    assert "source_contract: evidence_rows_only" in text
    assert "evidence IDs, copied source excerpts, URLs, locators, and source metadata" in text
    assert "must not contain unsourced top-level card summaries" in text
