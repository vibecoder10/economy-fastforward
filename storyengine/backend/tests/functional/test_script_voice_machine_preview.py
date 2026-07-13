"""Lock Script & Voice single-machine preview to the DVsU review contract."""

from pathlib import Path


def _script_voice_tab() -> Path:
    return (
        Path(__file__).resolve().parents[3]
        / "frontend"
        / "src"
        / "components"
        / "production"
        / "ScriptVoiceTab.tsx"
    )


def test_script_voice_preview_uses_normalized_machine_labels():
    text = _script_voice_tab().read_text()

    assert "function machineLabel" in text
    assert "function machineLabelMatches" in text
    assert "normalizedUnitCode(leftText)" in text
    assert "const machineRosterLabels" in text
    assert "machineRosterLabels.map" in text
    assert "previewForMachine(researchPayload?.machine_script_previews, e.target.value)" in text


def test_script_voice_preview_blocks_without_ready_raw_package():
    text = _script_voice_tab().read_text()

    assert "function sourcePackageForMachine" in text
    assert "function sourcePackageReady" in text
    assert "function sourcePackageStatus" in text
    assert "function sourceTierNumber" in text
    assert "function sourceTierForUrl" in text
    assert "host.endsWith(\".gov\")" in text
    assert "wikipedia.org" in text
    assert "airandspace.si.edu" in text
    assert "return host ? 3 : 0" in text
    assert "Raw source package machine mismatch · preview blocked" in text
    assert "const targetCode = normalizedUnitCode(machine)" in text
    assert "const packageCode = normalizedUnitCode(String(sourcePackage?.machine_key || sourcePackage?.machine || \"\"))" in text
    assert "activePreviewSourcePackageReady" in text
    assert "sourcePackageStatus(activePreviewSourcePackage, activePreviewMachine)" in text
    assert "sourcePackageReady(activePreviewSourcePackage, activePreviewMachine)" in text
    assert "disabled={previewGenerating || !activePreviewSourcePackageReady}" in text
    assert "Raw source package missing · preview blocked" in text
    assert "Raw source package thin ·" in text
    assert "Raw source package caution-only · preview blocked" in text
    assert "Raw source package unsupported capture ·" in text
    assert 'new Set(["fetched_page", "tavily_raw_content"])' in text
    assert "unsupportedCaptureMethods.size > 0" in text
    assert "Raw source package ready ·" in text
    assert "sourceUrls.size < 2" in text
    assert "nonCautionUrls.size < 1" in text
    assert "activePreviewSourcePackageStatus.message" in text


def test_script_voice_research_gate_counts_only_verified_cards():
    text = _script_voice_tab().read_text()

    assert "function cardMatchesMachine" in text
    assert "const verifiedMachineResearchCount = useMemo" in text
    assert "sourcePackageReady(sourcePackageForMachine(researchPayload?.machine_raw_source_packages, label), label)" in text
    assert "verified cards finished" in text
    assert "unit_research_cards?.length || 0" not in text


def test_script_voice_preview_visible_after_one_verified_machine():
    text = _script_voice_tab().read_text()

    assert "isMachineDocumentary && verifiedMachineResearchCount > 0" in text
    assert "isMachineDocumentary && machineResearchGate?.passed" not in text
    assert "Generate one machine" in text


def test_script_voice_preview_keeps_failed_reason_visible():
    text = _script_voice_tab().read_text()
    handler = text[text.index("const handleMachinePreview"):text.index("// ---------------------------------------------------------------------------", text.index("const handleMachinePreview"))]

    assert "setMachinePreview({" in handler
    assert 'research_source: "preview_error"' in handler
    assert "warnings: [message]" in handler
    assert "Preview stopped before a paragraph was generated." in text


def test_script_voice_preview_refreshes_saved_video_state():
    text = _script_voice_tab().read_text()
    handler = text[text.index("const handleMachinePreview"):text.index("// ---------------------------------------------------------------------------", text.index("const handleMachinePreview"))]

    assert "const invalidateAll = useCallback" in text
    assert "queryClient.invalidateQueries({ queryKey: [\"video\", video.id] })" in text
    assert "setMachinePreview(result.preview);" in handler
    assert "invalidateAll();" in handler


def test_script_voice_preview_evidence_map_shows_claims_and_excerpts():
    text = _script_voice_tab().read_text()

    assert "previewEvidenceById" in text
    assert "Editorial thesis" in text
    assert "machinePreview.claim_bundle?.editorial_thesis" in text
    assert "Anton quality audit" in text
    assert "machinePreview.quality_audit?.checks" in text
    assert 'check.advisory ? " · advisory" : ""' in text
    assert "source_excerpt: String(segment?.source_excerpt" in text
    assert "evidenceRows.map" in text
    assert "evidence?.claim" in text
    assert "evidence?.source_excerpt" in text


def test_script_voice_preview_surfaces_source_capture_method():
    text = _script_voice_tab().read_text()

    assert "function sourceCandidateForEvidence" in text
    assert "function sourceCaptureMethodForEvidence" in text
    assert "match?.source_capture_method || segment?.source_capture_method" in text
    assert '"legacy_unmarked"' in text
    assert "source_capture_method?: string" in text
    assert "sourceCaptureMethodForEvidence(segment, activePreviewSourcePackage)" in text
    assert "evidence?.source_capture_method" in text
