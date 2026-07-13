"""Lock the DVsU research UI to show verified source-tier evidence.

The Anton one-machine pipeline saves raw fetched excerpts in
`machine_raw_source_packages`. The research card itself is model-authored, so
the UI must derive source strength from the raw package by matching
`source_url` + copied `source_excerpt`, then show that tier before a paid
script preview run.
"""

from pathlib import Path


def _research_tab() -> Path:
    return (
        Path(__file__).resolve().parents[3]
        / "frontend"
        / "src"
        / "components"
        / "production"
        / "ResearchTab.tsx"
    )


def test_research_tab_reads_verified_raw_source_packages():
    text = _research_tab().read_text()

    assert "machine_raw_source_packages" in text
    assert "candidate_excerpts" in text
    assert "sourceTierForEvidence(segment, selectedSourcePackage)" in text
    assert "source_url" in text
    assert "source_excerpt" in text


def test_source_tier_helper_matches_excerpt_text_not_card_claims():
    text = _research_tab().read_text()
    helper = text[text.index("function sourceTierForEvidence"):text.index("function CollapsibleSection")]

    assert "normalizedSourceText(segment?.source_excerpt" in helper
    assert "normalizedSourceText(candidate?.text" in helper
    assert "candidateUrl === sourceUrl" in helper
    assert "candidateText.includes(excerpt)" in helper
    assert "segment?.claim" not in helper


def test_research_tab_surfaces_tier_badges_and_labels():
    text = _research_tab().read_text()

    assert "Tier {sourceTier.tier}" in text
    assert "sourceTier?.label" in text
    assert "source_tier_label" in text
    assert "source_tier" in text


def test_research_tab_preview_evidence_map_shows_claims_and_excerpts():
    text = _research_tab().read_text()

    assert "selectedPreviewClaimMap" in text
    assert "selectedPreviewEvidenceById" in text
    assert "source_excerpt: String(segment?.source_excerpt" in text
    assert "evidence?.claim" in text
    assert "evidence?.source_excerpt" in text
    assert "evidenceRows.map" in text


def test_research_tab_matches_cards_and_previews_by_normalized_machine_code():
    text = _research_tab().read_text()

    assert "function machineLabelMatches" in text
    assert "normalizedUnitCode(leftText)" in text
    assert "normalizedUnitCode(rightText)" in text
    assert "function cardMatchesMachine" in text
    assert "cardMatchesMachine(candidate, selectedMachineLabel)" in text
    assert "function previewForMachine" in text
    assert "previewMatchesMachine(localMachinePreview, selectedMachineLabel)" in text
    assert "previewForMachine(research?.machine_script_previews, selectedMachineLabel)" in text


def test_research_tab_keeps_failed_preview_reason_visible():
    text = _research_tab().read_text()

    handler = text[text.index("const handleOneMachinePreview"):text.index("const handleApproveResearch")]
    assert "setLocalMachinePreview({" in handler
    assert 'research_source: "preview_error"' in handler
    assert "warnings: [message]" in handler
    assert "Preview stopped before a paragraph was generated." in text
