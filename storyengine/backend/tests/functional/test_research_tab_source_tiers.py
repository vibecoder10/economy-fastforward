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


def _frontend_api() -> Path:
    return (
        Path(__file__).resolve().parents[3]
        / "frontend"
        / "src"
        / "lib"
        / "api.ts"
    )


def test_one_machine_api_wrappers_use_isolated_endpoints():
    text = _frontend_api().read_text()
    readiness_wrapper = text[text.index("export const checkMachineScriptPreviewReadiness"):text.index("export const runMachineScriptPreview")]
    research_wrapper = text[text.index("export const runOneMachineResearch"):text.index("export const runNextStep")]
    preview_wrapper = text[text.index("export const runMachineScriptPreview"):text.index("export const runOneMachineResearch")]

    assert "`/api/pipeline/machine-script-preview-readiness/${videoId}`" in readiness_wrapper
    assert "`/api/pipeline/machine-research-one/${videoId}`" in research_wrapper
    assert "`/api/pipeline/machine-script-preview/${videoId}`" in preview_wrapper
    assert "body: JSON.stringify({ machine })" in readiness_wrapper
    assert "confirmedPaidRun: true" in research_wrapper
    assert "confirmed_paid_run: confirmedPaidRun" in research_wrapper
    assert "confirmedPaidRun: true" in preview_wrapper
    assert "confirmed_paid_run: confirmedPaidRun" in preview_wrapper
    assert "next_action?: string" in text
    assert "/api/pipeline/machine-research/" not in research_wrapper
    assert "/api/pipeline/script/" not in preview_wrapper


def test_research_tab_reads_verified_raw_source_packages():
    text = _research_tab().read_text()

    assert "machine_raw_source_packages" in text
    assert "candidate_excerpts" in text
    assert "sourceTierForEvidence(segment, selectedSourcePackage)" in text
    assert "source_url" in text
    assert "source_excerpt" in text
    assert "locator" in text


def test_research_tab_source_capture_gate_uses_locked_machine_excerpts():
    # sourcePackageStatus is kept as a PURE-DISPLAY helper (raw source-package
    # coverage panel); it no longer gates readiness. Slice ends at the next
    # helper now that sourcePackageReady has been deleted.
    text = _research_tab().read_text()
    helper = text[text.index("function sourcePackageStatus"):text.index("function sourceSlotCoverageRows")]

    assert "const targetExcerpts = machine ? excerpts.filter" in helper
    assert "const missingCaptureMethodCount = targetExcerpts.filter" in helper
    assert "targetExcerpts\n      .map((candidate: any) => String(candidate?.source_capture_method || \"\").trim())" in helper
    assert "excerpts.filter((candidate: any) => !String(candidate?.source_capture_method || \"\").trim())" not in helper
    assert helper.index("const targetExcerpts = machine ? excerpts.filter") < helper.index("const missingCaptureMethodCount = targetExcerpts.filter")


def test_research_tab_blocks_preview_on_served_readiness_not_client_recompute():
    # The Research tab no longer recomputes card readiness client-side. The single
    # source of truth is the backend verdict on card.readiness. The raw
    # source-package helpers stay for the DISPLAY panel only (coverage, audit).
    text = _research_tab().read_text()

    # No client-side readiness recompute.
    assert "function machineResearchCardStatus" not in text
    assert "function sourcePackageReady" not in text
    assert 'return { ready: true, message: "Research card ready · visual identity grounded" }' not in text
    assert "machineResearchCardStatus(" not in text

    # Backend-owned readiness read straight off the served card.
    assert "function machineResearchReadiness" in text
    assert "const readiness = card?.readiness" in text
    assert "readiness.passed === true" in text
    assert "const selectedResearchReadiness = machineResearchReadiness(selectedResearchCard)" in text
    assert "const selectedResearchReady = selectedResearchReadiness.ready" in text
    assert "selectedResearchStatusMessage" in text
    # readiness === null renders a Revalidate needed state; warnings shown verbatim.
    assert "selectedResearchReadiness.needsRevalidate" in text
    assert "selectedResearchReadiness.warnings" in text
    assert "Revalidate needed" in text
    assert "disabled={singleMachineRunning || singlePreviewRunning || readinessChecking || isResearching || taskRunning}" in text

    # Raw source-package DISPLAY helpers remain (informational only, not a gate).
    assert "function sourcePackageStatus" in text
    assert "function textMentionsMachine" in text
    assert "designationCodeMatches(code, targetCode)" in text
    assert "Raw source package machine mismatch · preview blocked" in text
    assert "packageKey && packageKey !== targetCode" in text
    assert "function sourceTierNumber" in text
    assert "function sourceTierForUrl" in text
    assert "wikipedia.org" in text
    assert "airandspace.si.edu" in text
    assert "sourcePackageStatus(selectedSourcePackage, selectedMachineLabel)" in text
    assert "const selectedRawSourceExcerpts = useMemo" in text
    assert "const selectedSourceAuditRows = useMemo" in text
    assert "search_result_audit" in text
    assert "Raw source package excerpts" in text
    assert "Search result audit" in text
    assert "Raw source package ready ·" in text
    assert "Research refresh required before preview." in text

    # React Query hydration still carries the served (now readiness-enriched) payload.
    assert "queryClient.setQueryData([\"video\", video.id]" in text
    assert "{ ...current, research_payload: result.research_payload }" in text
    assert text.count("{ ...current, research_payload: result.research_payload }") >= 2


def test_research_tab_canonicalizes_legacy_meaning_slots():
    text = _research_tab().read_text()

    assert "function canonicalAntonSourceSlot" in text
    assert "function canonicalAntonSourceSlotHints" in text
    assert '"historical_meaning", "legacy"' in text
    assert "const hints = canonicalAntonSourceSlotHints(rawHints)" in text
    assert "? canonicalAntonSourceSlotHints(candidate.anton_slot_hints)" in text
    assert "? canonicalAntonSourceSlotHints(sourcePackage.traceable_source_slot_coverage.missing_slots)" in text
    assert "function canonicalEvidenceBySlot" in text
    assert "const savedEvidenceBySlot = canonicalEvidenceBySlot(savedCoverage?.evidence_by_slot)" in text
    assert "return canonicalAntonSourceSlot(kind)" in text
    assert ".anton_slot_hints.map" not in text
    assert "sourcePackage.traceable_source_slot_coverage.missing_slots.map((slot: any) => String(slot || \"\").trim()).filter(Boolean)" not in text


def test_script_voice_tab_blocks_preview_on_served_readiness():
    # ScriptVoiceTab gates on the served backend readiness verdict, not a client
    # recompute. The raw source-package authoritative-tier checks stay for display.
    text = _script_voice_tab().read_text()

    assert "function machineResearchCardStatus" not in text
    assert "machineResearchCardStatus(" not in text
    assert "function machineResearchReadiness" in text
    assert "const activePreviewReadiness = machineResearchReadiness(activePreviewResearchCard)" in text
    assert "const activePreviewReady = activePreviewReadiness.ready" in text
    assert "machineResearchCardReady(card)" in text
    assert "machineResearchCardReady(card, label, sourcePackage)" not in text

    # Source-package DISPLAY helpers (authoritative-tier detection) remain.
    assert "function sourcePackageStatus" in text
    assert "Raw source package needs Tier 1-2 source · preview blocked" in text
    assert "authoritativeUrls.size < 1" in text
    assert "sourceTierNumber(candidate) <= 2" in text
    assert "function sourceCandidateTraceable" in text
    assert "function untraceableAntonSourceSlots" in text
    assert "const untraceableSlots = untraceableAntonSourceSlots(targetExcerpts)" in text
    assert "const traceableTargetExcerpts = targetExcerpts.filter(sourceCandidateTraceable)" in text
    assert "sourceExcerptTextById(traceableTargetExcerpts)" in text
    assert "Raw source package untraceable Anton slots ·" in text
    assert "function tierFourOnlyAntonSourceSlots" in text
    assert "const cautionOnlySlots = tierFourOnlyAntonSourceSlots(targetExcerpts)" in text
    assert "Raw source package Tier 4-only Anton slots ·" in text


def test_script_voice_tab_canonicalizes_legacy_meaning_slots():
    text = _script_voice_tab().read_text()

    assert "function canonicalAntonSourceSlot" in text
    assert "function canonicalAntonSourceSlotHints" in text
    assert '"historical_meaning", "legacy"' in text
    assert "const hints = canonicalAntonSourceSlotHints(rawHints)" in text
    assert "? canonicalAntonSourceSlotHints(candidate.anton_slot_hints)" in text
    assert "? canonicalAntonSourceSlotHints(sourcePackage.traceable_source_slot_coverage.missing_slots)" in text
    assert "function canonicalEvidenceBySlot" in text
    assert "const savedEvidenceBySlot = canonicalEvidenceBySlot(savedCoverage?.evidence_by_slot)" in text
    assert "return canonicalAntonSourceSlot(kind)" in text
    assert ".anton_slot_hints.map" not in text
    assert "sourcePackage.traceable_source_slot_coverage.missing_slots.map((slot: any) => String(slot || \"\").trim()).filter(Boolean)" not in text


def test_research_tab_counts_only_verified_machine_cards():
    text = _research_tab().read_text()

    assert "function sourcePackageForMachine" in text
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
    assert "const rows = Array.isArray(packages) ? packages : Object.entries(packages).map" in text
    assert "const candidate = Array.isArray(packages) ? row : row.value" in text
    assert "normalizedUnitCode(rawKey) === key" in text
    assert "const verifiedMachineResearchCount = useMemo" in text
    # Verified count is driven purely by the served readiness verdict now.
    assert "machineResearchCardReady(card)" in text
    assert "machineResearchCardReady(card, label, sourcePackage)" not in text
    assert "sourcePackageReady(sourcePackage, label)" not in text
    assert "cards verified" in text
    assert "verifiedMachineResearchCount / research.unit_roster.length" in text or "verifiedMachineResearchCount}/{research.unit_roster.length" in text
    assert "const fullMachineResearchPassed = fullMachineResearchGatePassed" in text
    assert "!fullMachineResearchGatePassed(machineResearchGate, verifiedCount, lockedRoster.length)" in text
    assert "return machineResearchCardReady(card);" in text
    assert "verified cards finished" in text
    assert "unit_research_cards?.length || 0" not in text


def test_research_tab_shows_raw_source_beat_coverage():
    text = _research_tab().read_text()

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
    assert "const selectedSourceCoverageRows = sourceSlotCoverageRows(selectedSourcePackage, selectedMachineLabel)" in text
    assert "selectedSourceCoverageRows.map" in text
    assert 'original_problem: "Problem"' in text
    assert 'engineering_decision: "Decision"' in text
    assert 'tradeoff: "Tradeoff"' in text
    assert 'reality: "Reality"' in text
    assert "row.evidenceIds.slice(0, 3).join" in text
    assert "row.evidenceIds.join" in text


def test_research_tab_offers_bulk_machine_research_action():
    text = _research_tab().read_text()

    assert 'runPipelineStage(video.id, "machine-research")' in text
    assert "handleRunAllMachineResearch" in text
    assert "Run All Research Cards" in text
    assert "Research selected" in text
    assert "const machineResearchIsolatedMode = (research?.unit_roster?.length || 0) > 0" in text
    assert "{!machineResearchIsolatedMode && (" in text


def test_research_tab_one_machine_buttons_call_only_isolated_routes():
    text = _research_tab().read_text()
    research_handler = text[text.index("const handleOneMachineResearch"):text.index("const handleOneMachineReadiness")]
    readiness_handler = text[text.index("const handleOneMachineReadiness"):text.index("const handleOneMachinePreview")]
    preview_handler = text[text.index("const handleOneMachinePreview"):text.index("const handleApproveResearch")]

    assert "const machine = machineOverride || selectedMachine || machineLabel(roster[0])" in research_handler
    assert "confirmPaidOneMachineAction(" in research_handler
    assert "paid one-machine research refresh" in research_handler
    assert "runOneMachineResearch(video.id, machine, true)" in research_handler
    assert research_handler.index("confirmPaidOneMachineAction(") < research_handler.index("runOneMachineResearch(video.id, machine, true)")
    assert "One-machine research refresh canceled before any provider call." in research_handler
    assert "setLocalMachinePreview(null)" in research_handler
    assert 'runPipelineStage(video.id, "machine-research")' not in research_handler
    assert "advanceVideo(" not in research_handler
    assert "resetPipeline(" not in research_handler

    assert "machine = machineOverride || selectedMachine || machineLabel(roster[0])" in readiness_handler
    assert "checkMachineScriptPreviewReadiness(video.id, machine)" in readiness_handler
    assert "setLocalMachinePreview(previewErrorArtifact(" in readiness_handler
    assert "readinessWarningsWithNextAction(readiness, message)" in readiness_handler
    assert "Next action:" in text
    assert "preview?.research_source === \"readiness_preflight\" ? messages : messages.slice(0, 6)" in text
    assert '? [`Next action: ${nextAction}`, ...warnings]' in text
    assert '"readiness_preflight"' in readiness_handler
    assert '"Readiness preflight"' in readiness_handler
    assert "Readiness blocked:" in readiness_handler
    assert "Production script unchanged." in readiness_handler
    assert "runMachineScriptPreview(video.id, machine, true)" not in readiness_handler
    assert 'runPipelineStage(video.id, "script")' not in readiness_handler
    assert "advanceVideo(" not in readiness_handler
    assert "resetPipeline(" not in readiness_handler
    assert "Check readiness" not in text

    assert "machine = machineOverride || selectedMachine || machineLabel(roster[0])" in preview_handler
    assert "checkMachineScriptPreviewReadiness(video.id, machine)" in preview_handler
    assert "confirmPaidOneMachineAction(" in preview_handler
    assert "paid single-machine script preview" in preview_handler
    assert "runMachineScriptPreview(video.id, machine, true)" in preview_handler
    assert preview_handler.index("checkMachineScriptPreviewReadiness(video.id, machine)") < preview_handler.index("runMachineScriptPreview(video.id, machine, true)")
    assert preview_handler.index("confirmPaidOneMachineAction(") < preview_handler.index("runMachineScriptPreview(video.id, machine, true)")
    assert "Single-machine script preview canceled before any provider call." in preview_handler
    assert "if (!readiness.ready)" in preview_handler
    assert '"readiness_preflight"' in preview_handler
    assert '"Readiness preflight"' in preview_handler
    assert "setLocalMachinePreview(result.preview)" in preview_handler
    assert "Production script unchanged." in preview_handler
    assert 'runPipelineStage(video.id, "script")' not in preview_handler
    assert "advanceVideo(" not in preview_handler
    assert "resetPipeline(" not in preview_handler


def test_source_tier_helper_matches_excerpt_locator_not_card_claims():
    text = _research_tab().read_text()
    helper = text[text.index("function sourceCandidateForEvidence"):text.index("function CollapsibleSection")]

    assert "normalizedSourceText(segment?.source_excerpt" in helper
    assert "normalizedSourceText(candidate?.text" in helper
    assert "String(segment?.source_excerpt_id || segment?.excerpt_id" in helper
    assert "String(segment?.source_excerpt_hash" in helper
    assert "exactIdMatch" in helper
    assert "exactHashMatch" in helper
    assert "candidateExcerptId === sourceExcerptId" in helper
    assert "candidateHash === sourceExcerptHash" in helper
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
    assert "function sourceVariantSelectionForEvidence" in text
    assert "function sourceVariantSelectionLabel" in text
    assert "match?.source_capture_method || segment?.source_capture_method" in text
    assert "match?.source_variant_selection || segment?.source_variant_selection" in text
    assert '"legacy_unmarked"' in text
    assert "source_capture_method?: string" in text
    assert "source_variant_selection?: any" in text
    assert "source_excerpt_id?: string" in text
    assert "source_excerpt_hash?: string" in text
    assert "segment?.source_excerpt_id || sourceCandidateForEvidence(segment, selectedSourcePackage)?.excerpt_id" in text
    assert "segment?.source_excerpt_hash || sourceCandidateForEvidence(segment, selectedSourcePackage)?.text_hash" in text
    assert "sourceCaptureMethodForEvidence(segment, selectedSourcePackage)" in text
    assert "sourceVariantSelectionForEvidence(segment, selectedSourcePackage)" in text
    assert "sourceVariantSelectionLabel(candidate?.source_variant_selection)" in text
    assert "sourceVariantSelectionLabel(evidence?.source_variant_selection)" in text
    assert "selected ${selectedMethod}" in text
    assert "compared ${compared.join(\"/\")}" in text
    assert "evidence?.source_capture_method" in text
    assert "evidence?.source_excerpt_id || evidence?.locator" in text
    assert "evidence?.source_excerpt_hash ? `hash ${String(evidence.source_excerpt_hash).slice(0, 8)}` : \"\"" in text
    assert "sourceCaptureMethod" in text
    assert "const cardSourcePackage = sourcePackageForMachine(research.machine_raw_source_packages, label)" in text
    assert "sourceCaptureMethodForEvidence(segment, selectedSourcePackage)" in text


def test_research_tab_surfaces_tier_badges_and_labels():
    text = _research_tab().read_text()

    assert "Tier ${tier}" in text
    assert "match?.source_tier_label || segment?.source_tier_label || `Tier ${tier}`" in text
    assert "source_tier_label" in text
    assert "source_tier" in text
    assert "sourceTierNumber(match)" in text
    assert "sourceTierForUrl(segment?.source_url, segment?.source_title)" in text


def test_script_voice_preview_surfaces_raw_excerpt_identity():
    text = _script_voice_tab().read_text()

    assert "source_excerpt_id?: string" in text
    assert "source_excerpt_hash?: string" in text
    assert "segment?.source_excerpt_id || sourceCandidateForEvidence(segment, activePreviewSourcePackage)?.excerpt_id" in text
    assert "segment?.source_excerpt_hash || sourceCandidateForEvidence(segment, activePreviewSourcePackage)?.text_hash" in text
    assert "const sourceExcerptId = String(segment?.source_excerpt_id || segment?.excerpt_id || \"\").trim()" in text
    assert "const sourceExcerptHash = String(segment?.source_excerpt_hash || \"\").trim()" in text
    assert "exactIdMatch" in text
    assert "exactHashMatch" in text
    assert "evidence?.source_excerpt_id || evidence?.locator" in text
    assert "evidence?.source_excerpt_hash ? `hash ${String(evidence.source_excerpt_hash).slice(0, 8)}` : \"\"" in text


def test_research_tab_preview_evidence_map_shows_claims_and_excerpts():
    text = _research_tab().read_text()

    assert "selectedPreviewClaimMap" in text
    assert "selectedPreviewFormulaSentences" in text
    assert "selectedPreviewFormulaRows" in text
    assert "machinePreviewPassesAntonGate(result.preview)" in text
    assert "const selectedMachinePreviewPassed = machinePreviewPassesAntonGate(selectedMachinePreview)" in text
    assert "function machinePreviewReviewMessages" in text
    assert "const selectedMachinePreviewReviewMessages = machinePreviewReviewMessages(selectedMachinePreview)" in text
    assert "preview?.quality_audit?.passed === false && preview?.quality_audit?.summary" in text
    assert "check && check.passed === false && !check.advisory" in text
    assert "Review reason" in text
    assert "selectedMachinePreviewReviewMessages.map" in text
    assert "Legacy preview missing Anton audit" in text
    assert "const spanMatchesSentence = span && (span === sentence || sentence.includes(span));" in text
    assert "return Boolean(spanMatchesSentence && (!slot || slot === expectedSlot));" in text
    assert "span.includes(sentence)" not in text
    assert "Sentence assembly" in text
    assert '["problem", "decision", "tradeoff", "reality"][index] : "conclusion"' in text
    assert "selectedPreviewEvidenceById" in text
    assert "Editorial thesis" in text
    assert "selectedMachinePreview.claim_bundle?.editorial_thesis" in text
    assert "Anton quality audit" in text
    assert "selectedMachinePreview.quality_audit?.checks" in text
    assert "const checkPassedOrAdvisory = check.passed || check.advisory" in text
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


def test_research_tab_verified_badges_render_served_readiness():
    """Per-card badges/counts render the served verdict; failed cards list warnings."""
    text = _research_tab().read_text()

    # No client recompute; shared readiness helper is the single source.
    assert "function machineResearchCardStatus" not in text
    assert "function machineResearchReadiness" in text

    # Per-card badge derives from card.readiness.
    assert "const cardReadiness = machineResearchReadiness(card)" in text
    assert "const cardVerified = cardReadiness.ready" in text

    # readiness === null renders a Revalidate needed state (not ready).
    assert "cardReadiness.needsRevalidate" in text
    assert "Revalidate needed" in text

    # Failed-card warnings are listed verbatim.
    assert "cardReadiness.warnings.length > 0" in text
    assert "cardReadiness.warnings.map" in text


def test_research_tab_keeps_failed_preview_reason_visible():
    text = _research_tab().read_text()

    handler = text[text.index("const handleOneMachinePreview"):text.index("const handleApproveResearch")]
    helper = text[text.index("function previewErrorArtifact"):text.index("function previewForMachine")]
    assert "Production script unchanged." in handler
    assert "setLocalMachinePreview(previewErrorArtifact(" in handler
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
    assert "Preview stopped before a paragraph was generated." in text
