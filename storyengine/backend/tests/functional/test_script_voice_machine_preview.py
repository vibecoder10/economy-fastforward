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
    text = _script_voice_tab().read_text()
    helper = text[text.index("function sourcePackageStatus"):text.index("function sourcePackageReady")]

    assert "const targetExcerpts = machine ? excerpts.filter" in helper
    assert "const missingCaptureMethodCount = targetExcerpts.filter" in helper
    assert "targetExcerpts\n      .map((candidate: any) => String(candidate?.source_capture_method || \"\").trim())" in helper
    assert "excerpts.filter((candidate: any) => !String(candidate?.source_capture_method || \"\").trim())" not in helper
    assert helper.index("const targetExcerpts = machine ? excerpts.filter") < helper.index("const missingCaptureMethodCount = targetExcerpts.filter")


def test_script_voice_preview_blocks_without_ready_raw_package():
    text = _script_voice_tab().read_text()

    assert "function sourcePackageForMachine" in text
    assert "function sourcePackageReady" in text
    assert "function sourcePackageStatus" in text
    assert "function textMentionsMachine" in text
    assert "function designationCodes" in text
    assert "function designationCodeMatches" in text
    assert "designationCodeMatches(code, targetCode)" in text
    assert "B-2 must not match B-21" in text
    assert "compactBody.includes(targetCode)" not in text
    assert "const bodyWords = new Set(bodyLower.match(/[a-z]{3,}/g) || [])" in text
    assert "bodyWords.has(word)" in text
    assert '"grumman", "general", "dynamics", "rockwell", "american", "republic", "mcdonnell"' in text
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
    assert "const packageKey = normalizedUnitCode(String(sourcePackage?.machine_key || \"\"))" in text
    assert "const packageMachine = normalizedUnitCode(String(sourcePackage?.machine || \"\"))" in text
    assert "packageKey && packageKey !== targetCode" in text
    assert "packageMachine && packageMachine !== targetCode" in text
    assert "activePreviewSourcePackageReady" in text
    assert "sourcePackageStatus(activePreviewSourcePackage, activePreviewMachine)" in text
    assert "sourcePackageReady(activePreviewSourcePackage, activePreviewMachine)" in text
    assert "activePreviewResearchCard" in text
    assert "activePreviewReady" in text
    assert "Research card missing · preview blocked" in text
    assert "Sourced memorable fact missing · preview blocked" in text
    assert "const hasSourcedMemorableFact" in text
    assert "String(segment?.source_excerpt || \"\").trim()" in text
    assert "Evidence source mismatch ·" in text
    assert "Research card missing Anton slots ·" in text
    assert "Research card needs distinct Anton excerpts · preview blocked" in text
    assert "Research card needs selected Tier 1-2 evidence · preview blocked" in text
    assert "Timeframe evidence Tier 4-only · preview blocked" in text
    assert "Visual identity evidence Tier 4-only · preview blocked" in text
    assert "sourceTierForEvidence(segment, sourcePackage)?.tier" in text
    assert "function sourceSlotHintsForEvidence" in text
    assert "anton_slot_hints" in text
    assert "source_slot_hints" in text
    assert "hints ${evidence.source_slot_hints.join(\", \")}" in text
    assert "function antonSlotRoleForEvidenceKind" in text
    assert "machineResearchCardStatus(activePreviewResearchCard, activePreviewMachine, activePreviewSourcePackage)" in text
    assert "disabled={previewGenerating || !activePreviewReady}" in text
    assert "Raw source package missing · preview blocked" in text
    assert "Raw source package target-thin ·" in text
    assert "Raw source package thin ·" in text
    assert "Raw source package caution-only · preview blocked" in text
    assert "Raw source package missing Anton slots ·" in text
    assert "sourcePackage?.traceable_source_slot_coverage?.missing_slots" in text
    assert "antonSourceSlotHints(candidate?.text)" in text
    assert "needs_distinct_slot_excerpts" in text
    assert "Raw source package needs distinct Anton excerpts" in text
    assert "Raw source package missing capture method ·" in text
    assert "Raw source package unsupported capture ·" in text
    assert "Raw source package missing provenance ·" in text
    assert 'new Set(["fetched_page", "tavily_raw_content"])' in text
    assert "missingCaptureMethodCount > 0" in text
    assert "missingSourceProvenanceCount > 0" in text
    assert "candidate?.source_variant_selection" in text
    assert "unsupportedCaptureMethods.size > 0" in text
    assert "Raw source package ready ·" in text
    assert "sourceUrls.size < 2" in text
    assert "nonCautionUrls.size < 1" in text
    assert "function sourceCandidateTraceable" in text
    assert "function untraceableAntonSourceSlots" in text
    assert "const untraceableSlots = untraceableAntonSourceSlots(targetExcerpts)" in text
    assert "const traceableTargetExcerpts = targetExcerpts.filter(sourceCandidateTraceable)" in text
    assert "const traceableEvidenceBySlot = sourceSlotEvidenceBySlot(traceableTargetExcerpts)" in text
    assert "sourceExcerptTextById(traceableTargetExcerpts)" in text
    assert "Raw source package untraceable Anton slots ·" in text
    assert "function tierFourOnlyAntonSourceSlots" in text
    assert "const cautionOnlySlots = tierFourOnlyAntonSourceSlots(targetExcerpts)" in text
    assert "Raw source package Tier 4-only Anton slots ·" in text
    assert "activePreviewSourcePackageStatus.message" in text
    assert "Research refresh required before preview." in text


def test_script_voice_research_gate_counts_only_verified_cards():
    text = _script_voice_tab().read_text()

    assert "function cardMatchesMachine" in text
    assert "function fullMachineResearchGatePassed" in text
    assert "function machinePreviewPassesAntonGate" in text
    assert "const auditChecks = Array.isArray(preview?.quality_audit?.checks)" in text
    assert "auditChecks.length > 0" in text
    assert "const blockingAuditChecksPassed = auditChecks.every((check: any) => check?.passed || check?.advisory)" in text
    assert "const completeFormulaSentences = formulaSentences.length === 5" in text
    assert "formulaSentences.every((sentence: any) => String(sentence || \"\").trim().length > 0)" in text
    assert "preview?.passed === true" in text
    assert "preview?.quality_audit?.passed === true" in text
    assert "&& blockingAuditChecksPassed" in text
    assert "&& completeFormulaSentences" in text
    assert "verifiedCount === rosterCount" in text
    assert "units.length >= rosterCount" in text
    assert "!validation?.target_machine" in text
    assert "const verifiedMachineResearchCount = useMemo" in text
    assert "const sourcePackage = sourcePackageForMachine(researchPayload?.machine_raw_source_packages, label)" in text
    assert "machineResearchCardReady(card, label, sourcePackage)" in text
    assert "sourcePackageReady(sourcePackage, label)" in text
    assert "verified cards finished" in text
    assert "unit_research_cards?.length || 0" not in text


def test_script_voice_preview_shows_raw_source_beat_coverage():
    text = _script_voice_tab().read_text()

    assert "function sourceSlotCoverageRows" in text
    assert "function distinctAntonSlotAssignment" in text
    assert "function excerptTextsOverlap" in text
    assert "function sourceExcerptTextById" in text
    assert "function sourceSlotEvidenceBySlot" in text
    assert "antonSlotRoleForEvidenceKind(segment?.kind)" in text
    assert "sourceExcerptTextById(traceableTargetExcerpts)" in text
    assert "requiredSourceTextById" in text
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
    assert "fullMachineResearchGatePassed(validation, verifiedCount, roster.length)" in text
    assert "fullMachineResearchGatePassed(validation, verifiedMachineResearchCount, roster.length)" in text
    assert "const sourcePackage = sourcePackageForMachine(packages, label)" in text
    assert "return machineResearchCardReady(card, label, sourcePackage) && sourcePackageReady(sourcePackage, label)" in text
    assert "const scriptGenerationBlockedByRoster" in text
    assert text.count("scriptGenerationBlockedByRoster") >= 5
    assert "scriptRegenerationBlockedReason()" in handler
    assert "toast.error(blockedReason)" in handler
    assert handler.index("scriptRegenerationBlockedReason()") < handler.index('runPipelineStage(video.id, "script")')


def test_script_voice_preview_keeps_failed_reason_visible():
    text = _script_voice_tab().read_text()
    handler = text[text.index("const handleMachinePreview"):text.index("// ---------------------------------------------------------------------------", text.index("const handleMachinePreview"))]
    helper = text[text.index("function previewErrorArtifact"):text.index("function cardMatchesMachine")]

    assert "setMachinePreview(previewErrorArtifact(" in handler
    assert '"readiness_preflight"' in handler
    assert '"Readiness preflight"' in handler
    assert 'researchSource = "preview_error"' in helper
    assert 'checkName = "preview_error"' in helper
    assert 'checkLabel = "Preview error"' in helper
    assert "research_source: researchSource" in helper
    assert "name: checkName" in helper
    assert "label: checkLabel" in helper
    assert "quality_audit: {" in helper
    assert "previewErrorArtifact(machine, message)" in handler
    assert "Production script unchanged." in handler
    assert "Preview stopped before a paragraph was generated." in text


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

    assert "const machine = previewMachine || machineRosterLabels[0]" in handler
    assert "checkMachineScriptPreviewReadiness(video.id, machine)" in handler
    assert "setMachinePreview(previewErrorArtifact(" in handler
    assert "readinessWarningsWithNextAction(readiness, message)" in handler
    assert "Next action:" in text
    assert '"readiness_preflight"' in handler
    assert '"Readiness preflight"' in handler
    assert "Readiness blocked:" in handler
    assert "Production script unchanged." in handler
    assert "runMachineScriptPreview(video.id, machine)" not in handler
    assert 'runPipelineStage(video.id, "script")' not in handler
    assert "advanceVideo(" not in handler
    assert "resetPipeline(" not in handler
    assert "generateVoice(" not in handler
    assert "Check readiness" in text


def test_script_voice_preview_button_calls_only_isolated_preview_route():
    text = _script_voice_tab().read_text()
    handler = text[text.index("const handleMachinePreview"):text.index("// ---------------------------------------------------------------------------", text.index("const handleMachinePreview"))]

    assert "const machine = previewMachine || machineRosterLabels[0]" in handler
    assert "checkMachineScriptPreviewReadiness(video.id, machine)" in handler
    assert "runMachineScriptPreview(video.id, machine)" in handler
    assert handler.index("checkMachineScriptPreviewReadiness(video.id, machine)") < handler.index("runMachineScriptPreview(video.id, machine)")
    assert "if (!readiness.ready)" in handler
    assert '"readiness_preflight"' in handler
    assert '"Readiness preflight"' in handler
    assert "setMachinePreview(result.preview)" in handler
    assert "setPreviewMachine(machine)" in handler
    assert "Production script unchanged." in handler
    assert 'runPipelineStage(video.id, "script")' not in handler
    assert "advanceVideo(" not in handler
    assert "resetPipeline(" not in handler
    assert "generateVoice(" not in handler


def test_script_voice_preview_evidence_map_shows_claims_and_excerpts():
    text = _script_voice_tab().read_text()

    assert "previewEvidenceById" in text
    assert "previewFormulaSentences" in text
    assert "previewFormulaRows" in text
    assert "machinePreviewPassesAntonGate(result.preview)" in text
    assert "const machinePreviewPassed = machinePreviewPassesAntonGate(activeMachinePreview)" in text
    assert "function machinePreviewReviewMessages" in text
    assert "const activePreviewReviewMessages = machinePreviewReviewMessages(activeMachinePreview)" in text
    assert "preview?.quality_audit?.passed === false && preview?.quality_audit?.summary" in text
    assert "check && check.passed === false && !check.advisory" in text
    assert "Review reason" in text
    assert "activePreviewReviewMessages.map" in text
    assert "Legacy preview missing Anton audit" in text
    assert "const spanMatchesSentence = span && (span === sentence || sentence.includes(span));" in text
    assert "return Boolean(spanMatchesSentence && (!slot || slot === expectedSlot));" in text
    assert "span.includes(sentence)" not in text
    assert "Sentence assembly" in text
    assert '["problem", "decision", "tradeoff", "reality"][index] : "conclusion"' in text
    assert "Editorial thesis" in text
    assert "activeMachinePreview.claim_bundle?.editorial_thesis" in text
    assert "Anton quality audit" in text
    assert "activeMachinePreview.quality_audit?.checks" in text
    assert 'check.advisory ? " · advisory" : ""' in text
    assert "source_excerpt: String(segment?.source_excerpt" in text
    assert "evidenceRows.map" in text
    assert "evidence?.claim" in text
    assert "evidence?.source_excerpt" in text


def test_script_voice_preview_surfaces_source_capture_method():
    text = _script_voice_tab().read_text()

    assert "function sourceCandidateForEvidence" in text
    assert "function sourceTierForEvidence" in text
    assert "sourceTierNumber(match)" in text
    assert "sourceTierForUrl(segment?.source_url, segment?.source_title)" in text
    assert "function sourceCaptureMethodForEvidence" in text
    assert "function sourceVariantSelectionForEvidence" in text
    assert "function sourceVariantSelectionLabel" in text
    assert "match?.source_capture_method || segment?.source_capture_method" in text
    assert "match?.source_variant_selection || segment?.source_variant_selection" in text
    assert '"legacy_unmarked"' in text
    assert "source_capture_method?: string" in text
    assert "source_variant_selection?: any" in text
    assert "sourceCaptureMethodForEvidence(segment, activePreviewSourcePackage)" in text
    assert "sourceVariantSelectionForEvidence(segment, activePreviewSourcePackage)" in text
    assert "sourceVariantSelectionLabel(evidence?.source_variant_selection)" in text
    assert "selected ${selectedMethod}" in text
    assert "compared ${compared.join(\"/\")}" in text
    assert "evidence?.source_capture_method" in text
