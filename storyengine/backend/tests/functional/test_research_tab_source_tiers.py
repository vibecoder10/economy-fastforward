"""Lock the DVsU research UI to show verified source-tier evidence.

The Anton one-machine pipeline saves raw fetched excerpts in
`machine_raw_source_packages`. The research card itself is model-authored, so
the UI must derive source strength from the raw package by matching
`source_url` + `locator` + copied `source_excerpt`, then show that tier before
a paid script preview run.
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


def _script_voice_tab() -> Path:
    return (
        Path(__file__).resolve().parents[3]
        / "frontend"
        / "src"
        / "components"
        / "production"
        / "ScriptVoiceTab.tsx"
    )


def test_research_tab_reads_verified_raw_source_packages():
    text = _research_tab().read_text()

    assert "machine_raw_source_packages" in text
    assert "candidate_excerpts" in text
    assert "sourceTierForEvidence(segment, selectedSourcePackage)" in text
    assert "source_url" in text
    assert "source_excerpt" in text
    assert "locator" in text


def test_research_tab_blocks_preview_without_ready_raw_package():
    text = _research_tab().read_text()

    assert "function sourcePackageReady" in text
    assert "function sourcePackageStatus" in text
    assert "function textMentionsMachine" in text
    assert "rawExcerpts.filter((candidate: any) => String(candidate?.text || \"\").trim())" in text
    assert "targetExcerpts.length < 6" in text
    assert "function sourceTierNumber" in text
    assert "function sourceTierForUrl" in text
    assert "host.endsWith(\".gov\")" in text
    assert "wikipedia.org" in text
    assert "airandspace.si.edu" in text
    assert "return host ? 3 : 0" in text
    assert "Raw source package machine mismatch · preview blocked" in text
    assert "const targetCode = normalizedUnitCode(machine)" in text
    assert "const packageCode = normalizedUnitCode(String(sourcePackage?.machine_key || sourcePackage?.machine || \"\"))" in text
    assert "selectedSourcePackageReady" in text
    assert "sourcePackageStatus(selectedSourcePackage, selectedMachineLabel)" in text
    assert "sourcePackageReady(selectedSourcePackage, selectedMachineLabel)" in text
    assert "disabled={singlePreviewRunning || isResearching || taskRunning || !selectedResearchCard || !selectedSourcePackageReady}" in text
    assert "Raw source package missing · preview blocked" in text
    assert "Raw source package target-thin ·" in text
    assert "Raw source package thin ·" in text
    assert "Raw source package caution-only · preview blocked" in text
    assert "Raw source package needs Tier 1-2 source · preview blocked" in text
    assert "Raw source package missing capture method ·" in text
    assert "Raw source package unsupported capture ·" in text
    assert 'new Set(["fetched_page", "tavily_raw_content"])' in text
    assert "missingCaptureMethodCount > 0" in text
    assert "unsupportedCaptureMethods.size > 0" in text
    assert "Raw source package ready ·" in text
    assert "sourceUrls.size < 2" in text
    assert "nonCautionUrls.size < 1" in text
    assert "authoritativeUrls.size < 1" in text
    assert "selectedSourcePackageStatus.message" in text


def test_script_voice_tab_blocks_preview_without_authoritative_source():
    text = _script_voice_tab().read_text()

    assert "function sourcePackageStatus" in text
    assert "Raw source package needs Tier 1-2 source · preview blocked" in text
    assert "authoritativeUrls.size < 1" in text
    assert "sourceTierNumber(candidate) <= 2" in text


def test_research_tab_counts_only_verified_machine_cards():
    text = _research_tab().read_text()

    assert "function sourcePackageForMachine" in text
    assert "const verifiedMachineResearchCount = useMemo" in text
    assert "sourcePackageReady(sourcePackageForMachine(research.machine_raw_source_packages, label), label)" in text
    assert "verified machines researched" in text
    assert "verifiedMachineResearchCount / research.unit_roster.length" in text
    assert "verified cards finished" in text
    assert "unit_research_cards?.length || 0" not in text


def test_research_tab_does_not_offer_bulk_machine_research_action():
    text = _research_tab().read_text()

    assert 'runPipelineStage(video.id, "machine-research")' not in text
    assert "handleMachineResearch" not in text
    assert "Start machine research" not in text
    assert "Continue machine research" not in text
    assert "Research selected" in text


def test_source_tier_helper_matches_excerpt_locator_not_card_claims():
    text = _research_tab().read_text()
    helper = text[text.index("function sourceCandidateForEvidence"):text.index("function CollapsibleSection")]

    assert "normalizedSourceText(segment?.source_excerpt" in helper
    assert "normalizedSourceText(candidate?.text" in helper
    assert "String(segment?.locator" in helper
    assert "String(candidate?.locator" in helper
    assert "String(candidate?.excerpt_id" in helper
    assert "locatorMatches" in helper
    assert "candidateUrl === sourceUrl" in helper
    assert "candidateText.includes(excerpt)" in helper
    assert "segment?.claim" not in helper


def test_research_tab_surfaces_source_capture_method():
    text = _research_tab().read_text()

    assert "function sourceCaptureMethodForEvidence" in text
    assert "match?.source_capture_method || segment?.source_capture_method" in text
    assert '"legacy_unmarked"' in text
    assert "source_capture_method?: string" in text
    assert "sourceCaptureMethodForEvidence(segment, selectedSourcePackage)" in text
    assert "evidence?.source_capture_method" in text
    assert "sourceCaptureMethod" in text
    assert "const cardSourcePackage = sourcePackageForMachine(research.machine_raw_source_packages, label)" in text
    assert "sourceCaptureMethodForEvidence(segment, cardSourcePackage)" in text


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
    assert "Editorial thesis" in text
    assert "selectedMachinePreview.claim_bundle?.editorial_thesis" in text
    assert "Anton quality audit" in text
    assert "selectedMachinePreview.quality_audit?.checks" in text
    assert 'check.advisory ? " · advisory" : ""' in text
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
    assert "Production script unchanged." in handler
    assert "setLocalMachinePreview({" in handler
    assert 'research_source: "preview_error"' in handler
    assert "warnings: [message]" in handler
    assert "Preview stopped before a paragraph was generated." in text
