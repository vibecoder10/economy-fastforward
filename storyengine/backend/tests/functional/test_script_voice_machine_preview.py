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
    assert "const activeMachinePreview = useMemo" in text
    assert "previewForMachine(researchPayload?.machine_script_previews, activePreviewMachine)" in text
    assert "previewMatchesMachine(machinePreview, activePreviewMachine)" in text
    assert "queryClient.setQueryData([\"video\", video.id]" in text
    assert "{ ...current, research_payload: result.research_payload }" in text


def test_script_voice_source_capture_gate_uses_locked_machine_excerpts():
    # sourcePackageStatus is kept as a PURE-DISPLAY helper (raw source-package
    # coverage panel); it no longer gates readiness. Slice ends at the next
    # helper now that sourcePackageReady has been deleted.
    text = _script_voice_tab().read_text()
    helper = text[text.index("function sourcePackageStatus"):text.index("function sourceSlotCoverageRows")]

    assert "const targetExcerpts = machine ? excerpts.filter" in helper
    assert "const missingCaptureMethodCount = targetExcerpts.filter" in helper
    assert "targetExcerpts\n      .map((candidate: any) => String(candidate?.source_capture_method || \"\").trim())" in helper
    assert "excerpts.filter((candidate: any) => !String(candidate?.source_capture_method || \"\").trim())" not in helper
    assert helper.index("const targetExcerpts = machine ? excerpts.filter") < helper.index("const missingCaptureMethodCount = targetExcerpts.filter")


def test_script_voice_preview_blocks_on_served_readiness_not_client_recompute():
    # The client no longer recomputes research-card readiness. The single source
    # of truth is the backend verdict served on each card as card.readiness. The
    # raw source-package helpers are kept ONLY for the display panel (coverage,
    # excerpt counts) - they no longer gate the Run Script button.
    text = _script_voice_tab().read_text()

    # No client-side readiness recompute anywhere.
    assert "function machineResearchCardStatus" not in text
    assert "function sourcePackageReady" not in text
    assert 'return { ready: true, message: "Research card ready · visual identity grounded" }' not in text
    assert "machineResearchCardStatus(" not in text

    # Backend-owned readiness is read straight off the served card.
    assert "function machineResearchReadiness" in text
    assert "const readiness = card?.readiness" in text
    assert "readiness.passed === true" in text
    assert "readiness === null || readiness === undefined" in text
    assert "const activePreviewReadiness = machineResearchReadiness(activePreviewResearchCard)" in text
    assert "const activePreviewReady = activePreviewReadiness.ready" in text
    assert "disabled={previewGenerating || !activePreviewReady}" in text

    # Raw source-package DISPLAY helpers remain (informational only, not a gate).
    assert "function sourcePackageForMachine" in text
    assert "function sourcePackageStatus" in text
    assert "function textMentionsMachine" in text
    assert "function designationCodeMatches" in text
    assert "designationCodeMatches(code, targetCode)" in text
    assert "Raw source package machine mismatch · preview blocked" in text
    assert "const targetCode = normalizedUnitCode(machine)" in text
    assert "packageKey && packageKey !== targetCode" in text
    assert "function sourceTierNumber" in text
    assert "function sourceTierForUrl" in text
    assert "wikipedia.org" in text
    assert "airandspace.si.edu" in text
    assert "Raw source package ready ·" in text
    assert "activePreviewSourcePackageStatus.message" in text


def test_script_voice_preview_shows_raw_source_beat_coverage():
    text = _script_voice_tab().read_text()

    assert "function sourceSlotCoverageRows" in text
    assert "function distinctAntonSlotAssignment" in text
    assert "function excerptTextsOverlap" in text
    assert "function sourceExcerptTextById" in text
    assert "function sourceSlotEvidenceBySlot" in text
    assert "sourceExcerptTextById(traceableTargetExcerpts)" in text
    assert "sourcePackage?.traceable_source_slot_coverage" in text
    assert "savedEvidenceBySlot" in text
    assert "candidate?.anton_slot_hints" in text
    assert "sourceSlotEvidenceBySlot(targetExcerpts.filter(sourceCandidateTraceable))" in text
    assert "const activePreviewSourceCoverageRows = sourceSlotCoverageRows(activePreviewSourcePackage, activePreviewMachine)" in text
    assert "activePreviewSourceCoverageRows.map" in text
    assert 'original_problem: "Problem"' in text
    assert 'engineering_decision: "Decision"' in text
    assert 'tradeoff: "Tradeoff"' in text
    assert 'reality: "Reality"' in text
    assert "row.evidenceIds.slice(0, 3).join" in text
    assert "row.evidenceIds.join" in text


def test_script_voice_preview_visible_after_one_verified_machine():
    text = _script_voice_tab().read_text()

    assert "isMachineDocumentary && verifiedMachineResearchCount > 0" in text
    assert "isMachineDocumentary && machineResearchGate?.passed" not in text
    assert "Generate one machine" in text
    assert "{activeMachinePreview && (" in text
    assert 'activeMachinePreview ? "Retry this machine" : "Generate one machine"' in text


def test_script_voice_full_script_generation_waits_for_full_machine_research_gate():
    text = _script_voice_tab().read_text()
    handler = text[text.index("const handleRegenerateScript"):text.index("const handleSplitSentences")]

    assert "const scriptRegenerationBlockedReason" in text
    assert "Machine research is incomplete:" in text
    # Nonfactual channels retain the aggregate gate; factual batches defer
    # missing-card preparation to the server-side selected-machine preflight.
    assert "return fullMachineResearchGatePassed(validation, verifiedCount, rosterCount);" in text
    assert "payload?.machine_script_contract !== FACTUAL_MACHINE_SCRIPT_CONTRACT" in text
    assert "machineResearchGatePassesContract(" in text
    # The full-script gate now counts verified cards via the served readiness verdict only.
    assert "return machineResearchCardReady(card);" in text
    assert "sourcePackageReady(sourcePackage, label)" not in text
    assert "const scriptGenerationBlockedByRoster" in text
    assert text.count("scriptGenerationBlockedByRoster") >= 5
    assert "scriptRegenerationBlockedReason()" in handler
    assert "toast.error(blockedReason)" in handler
    assert handler.index("scriptRegenerationBlockedReason()") < handler.index('runPipelineStage(video.id, "script")')


def test_script_voice_preview_refreshes_saved_video_state():
    text = _script_voice_tab().read_text()
    handler = text[text.index("const handleMachinePreview"):text.index("// ---------------------------------------------------------------------------", text.index("const handleMachinePreview"))]

    assert "const invalidateAll = useCallback" in text
    assert "queryClient.invalidateQueries({ queryKey: [\"video\", video.id] })" in text
    assert "setMachinePreview(result.preview);" in handler
    assert "invalidateAll();" in handler


def test_script_voice_readiness_button_is_no_spend():
    text = _script_voice_tab().read_text()
    handler = text[text.index("const handleMachineReadiness"):text.index("const handleMachinePreview")]

    assert "const machine = machineOverride || previewMachine || machineRosterLabels[0]" in handler
    assert "checkMachineScriptPreviewReadiness(video.id, machine)" in handler
    assert "setMachinePreview(previewErrorArtifact(" in handler
    assert "readinessWarningsWithNextAction(readiness, message)" in handler
    assert "Next action:" in text
    assert "preview?.research_source === \"readiness_preflight\" ? messages : messages.slice(0, 6)" in text
    assert '? [`Next action: ${nextAction}`, ...warnings]' in text
    assert '"readiness_preflight"' in handler
    assert '"Readiness preflight"' in handler
    assert "Readiness blocked:" in handler
    assert "Production script unchanged." in handler
    assert "runMachineScriptPreview(video.id, machine, true)" not in handler
    assert 'runPipelineStage(video.id, "script")' not in handler
    assert "advanceVideo(" not in handler
    assert "resetPipeline(" not in handler
    assert "generateVoice(" not in handler
    assert "Check readiness" in text


def test_script_voice_preview_button_calls_only_isolated_preview_route():
    text = _script_voice_tab().read_text()
    handler = text[text.index("const handleMachinePreview"):text.index("// ---------------------------------------------------------------------------", text.index("const handleMachinePreview"))]

    assert "const machine = machineOverride || previewMachine || machineRosterLabels[0]" in handler
    assert "checkMachineScriptPreviewReadiness(video.id, machine)" in handler
    assert "confirmPaidOneMachineAction(" in handler
    assert "paid single-machine script preview" in handler
    assert "runMachineScriptPreview(video.id, machine, true)" in handler
    assert handler.index("checkMachineScriptPreviewReadiness(video.id, machine)") < handler.index("runMachineScriptPreview(video.id, machine, true)")
    assert handler.index("confirmPaidOneMachineAction(") < handler.index("runMachineScriptPreview(video.id, machine, true)")
    assert "Single-machine script preview canceled before any provider call." in handler
    assert "if (!readiness.ready && !readiness.preparable)" in handler
    assert '"readiness_preflight"' in handler
    assert '"Readiness preflight"' in handler
    assert "setMachinePreview(result.preview)" in handler
    assert "setPreviewMachine(machine)" in handler
    assert "Production script unchanged." in handler
    assert 'runPipelineStage(video.id, "script")' not in handler
    assert "advanceVideo(" not in handler
    assert "resetPipeline(" not in handler
    assert "generateVoice(" not in handler


