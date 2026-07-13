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
    assert "activePreviewSourcePackageReady" in text
    assert "disabled={previewGenerating || !activePreviewSourcePackageReady}" in text
    assert "Raw source package missing · preview blocked" in text
    assert "Raw source package ready ·" in text


def test_script_voice_preview_keeps_failed_reason_visible():
    text = _script_voice_tab().read_text()
    handler = text[text.index("const handleMachinePreview"):text.index("// ---------------------------------------------------------------------------", text.index("const handleMachinePreview"))]

    assert "setMachinePreview({" in handler
    assert 'research_source: "preview_error"' in handler
    assert "warnings: [message]" in handler
    assert "Preview stopped before a paragraph was generated." in text


def test_script_voice_preview_evidence_map_shows_claims_and_excerpts():
    text = _script_voice_tab().read_text()

    assert "previewEvidenceById" in text
    assert "Editorial thesis" in text
    assert "machinePreview.claim_bundle?.editorial_thesis" in text
    assert "Anton quality audit" in text
    assert "machinePreview.quality_audit?.checks" in text
    assert "source_excerpt: String(segment?.source_excerpt" in text
    assert "evidenceRows.map" in text
    assert "evidence?.claim" in text
    assert "evidence?.source_excerpt" in text
