"use client";

import { useMemo, useState, useCallback } from "react";
import { RefreshCw, FileText, Search, Loader2, Check, ChevronDown, ChevronRight, ShieldCheck } from "lucide-react";
import { useQueryClient } from "@tanstack/react-query";
import { GlassCard } from "@/components/ui/GlassCard";
import { ActionButton } from "@/components/ui/ActionButton";
import {
  runPipelineStage,
  advanceVideo,
  updateVideo,
  resetPipeline,
  clearStaleTask,
  runOneMachineResearch,
  runMachineScriptPreview,
} from "@/lib/api";
import type { MachineScriptPreview } from "@/lib/api";
import { useTaskPoller } from "@/hooks/use-task-poller";
import { useToast } from "@/components/ui/toast";

interface ResearchTabProps {
  video: any;
  onApproved?: () => void;
}

function machineLabel(item: any): string {
  if (typeof item === "string") return item;
  return [item?.designation, item?.name || item?.unit || item?.machine].filter(Boolean).join(" — ");
}

function cardLabel(card: any): string {
  return [card?.machine_name, card?.unit, card?.machine, card?.name, card?.designation].filter(Boolean)[0] || "";
}

function unitCode(text: string): string {
  const upper = String(text || "").toUpperCase().replace(/[–—]/g, "-");
  const designation = upper.match(/\b(?:X?Y?B|FB)-?\d{1,3}[A-Z]?\b/) || upper.match(/\b[A-Z]{1,4}-\d{1,4}[A-Z]?\b/);
  if (designation?.[0]) return designation[0].replace(/\s+/g, "");
  return (upper.match(/[A-Z0-9]+/g) || []).slice(0, 4).join(" ");
}

function normalizedUnitCode(text: string): string {
  return unitCode(text).replace(/[^A-Z0-9]/g, "");
}

function designationCodes(text: unknown): Set<string> {
  const body = String(text || "").toUpperCase().replace(/[–—]/g, "-");
  const matches = body.match(/\b(?:X?Y?B|FB)-?\d{1,3}[A-Z]?\b|\b[A-Z]{1,4}-\d{1,4}[A-Z]?\b/g) || [];
  return new Set(matches.map((item) => item.replace(/[^A-Z0-9]/g, "")));
}

function designationCodeMatches(candidateCode: string, targetCode: string): boolean {
  if (!candidateCode || !targetCode) return false;
  if (candidateCode === targetCode) return true;
  const suffix = candidateCode.startsWith(targetCode) ? candidateCode.slice(targetCode.length) : "";
  return Boolean(suffix && /^[A-Z]+$/.test(suffix));
}

function textMentionsMachine(text: unknown, machine: string): boolean {
  const body = String(text || "");
  const target = String(machine || "").trim();
  if (!body || !target) return false;
  const targetCode = normalizedUnitCode(target);
  const bodyCodes = designationCodes(body);
  // Exact designation tokens and letter suffixes only: B-2 must not match B-21.
  if (targetCode && Array.from(bodyCodes).some((code) => designationCodeMatches(code, targetCode))) return true;
  const bodyLower = body.toLowerCase();
  const targetLower = target.toLowerCase();
  if (targetLower.length >= 8 && bodyLower.includes(targetLower)) return true;
  const genericMakers = new Set([
    "boeing", "consolidated", "convair", "douglas", "northrop", "lockheed", "martin",
    "grumman", "general", "dynamics", "rockwell", "american", "republic", "mcdonnell",
  ]);
  const bodyWords = new Set(bodyLower.match(/[a-z]{3,}/g) || []);
  return (targetLower.match(/[a-z]{3,}/g) || [])
    .some((word) => !genericMakers.has(word) && bodyWords.has(word));
}

function machineLabelMatches(left: unknown, right: unknown): boolean {
  const leftText = String(left || "").trim();
  const rightText = String(right || "").trim();
  if (!leftText || !rightText) return false;
  const leftCode = normalizedUnitCode(leftText);
  const rightCode = normalizedUnitCode(rightText);
  if (leftCode && rightCode && leftCode === rightCode) return true;
  return leftText.toLowerCase() === rightText.toLowerCase();
}

function cardMatchesMachine(card: any, machine: string): boolean {
  return machineLabelMatches(cardLabel(card), machine);
}

function previewMatchesMachine(preview: any, machine: string): boolean {
  return machineLabelMatches(preview?.machine, machine);
}

function fullMachineResearchGatePassed(validation: any, verifiedCount: number, rosterCount: number): boolean {
  const units = Array.isArray(validation?.units) ? validation.units : [];
  return Boolean(
    validation?.passed
    && rosterCount > 0
    && verifiedCount === rosterCount
    && units.length >= rosterCount
    && !validation?.target_machine
  );
}

function machinePreviewPassesAntonGate(preview: any): boolean {
  const formulaSentences = Array.isArray(preview?.claim_bundle?.formula_sentences)
    ? preview.claim_bundle.formula_sentences
    : [];
  const auditChecks = Array.isArray(preview?.quality_audit?.checks)
    ? preview.quality_audit.checks
    : [];
  return Boolean(preview?.passed && preview?.quality_audit?.passed && auditChecks.length > 0 && formulaSentences.length === 5);
}

function previewForMachine(previews: any, machine: string): MachineScriptPreview | null {
  if (!previews || typeof previews !== "object" || Array.isArray(previews)) return null;
  if (previews[machine]) return previews[machine] as MachineScriptPreview;
  const match = Object.entries(previews).find(([key, preview]: [string, any]) => (
    machineLabelMatches(key, machine) || previewMatchesMachine(preview, machine)
  ));
  return match ? match[1] as MachineScriptPreview : null;
}

function normalizedSourceText(text: unknown): string {
  return String(text || "").toLowerCase().replace(/\s+/g, " ").trim();
}

function sourceCandidateForEvidence(segment: any, sourcePackage: any): any | null {
  const excerpts = Array.isArray(sourcePackage?.candidate_excerpts) ? sourcePackage.candidate_excerpts : [];
  const sourceUrl = String(segment?.source_url || "").trim();
  const locator = String(segment?.locator || "").trim();
  const sourceExcerptId = String(segment?.source_excerpt_id || segment?.excerpt_id || "").trim();
  const sourceExcerptHash = String(segment?.source_excerpt_hash || "").trim();
  const excerpt = normalizedSourceText(segment?.source_excerpt || "");
  if (!sourceUrl) return null;
  if (sourceExcerptId) {
    const exactIdMatch = excerpts.find((candidate: any) => {
      const candidateUrl = String(candidate?.source_url || "").trim();
      const candidateExcerptId = String(candidate?.excerpt_id || "").trim();
      const candidateHash = String(candidate?.text_hash || "").trim();
      return candidateUrl === sourceUrl
        && candidateExcerptId === sourceExcerptId
        && (!sourceExcerptHash || candidateHash === sourceExcerptHash);
    });
    if (exactIdMatch) return exactIdMatch;
  }
  if (sourceExcerptHash) {
    const exactHashMatch = excerpts.find((candidate: any) => {
      const candidateUrl = String(candidate?.source_url || "").trim();
      const candidateHash = String(candidate?.text_hash || "").trim();
      return candidateUrl === sourceUrl && candidateHash === sourceExcerptHash;
    });
    if (exactHashMatch) return exactHashMatch;
  }
  if (!excerpt) return null;
  return excerpts.find((candidate: any) => {
    const candidateUrl = String(candidate?.source_url || "").trim();
    const candidateLocator = String(candidate?.locator || "").trim();
    const candidateExcerptId = String(candidate?.excerpt_id || "").trim();
    const candidateText = normalizedSourceText(candidate?.text || "");
    const locatorMatches = !locator
      || locator === candidateLocator
      || locator === candidateExcerptId
      || Boolean(candidateLocator && candidateLocator.startsWith(`${locator};`));
    return candidateUrl === sourceUrl && locatorMatches && candidateText.includes(excerpt);
  }) || null;
}

function sourceTierForEvidence(segment: any, sourcePackage: any): { tier: number; label: string } | null {
  const match = sourceCandidateForEvidence(segment, sourcePackage);
  const rawTier = Number(match?.source_tier || segment?.source_tier || 0);
  const tier = rawTier || (match
    ? sourceTierNumber(match)
    : sourceTierForUrl(segment?.source_url, segment?.source_title));
  if (!tier) return null;
  return {
    tier,
    label: String(match?.source_tier_label || segment?.source_tier_label || `Tier ${tier}`),
  };
}

function sourceCaptureMethodForEvidence(segment: any, sourcePackage: any): string {
  const match = sourceCandidateForEvidence(segment, sourcePackage);
  return String(match?.source_capture_method || segment?.source_capture_method || "legacy_unmarked");
}

function sourceSlotHintsForEvidence(segment: any, sourcePackage: any): string[] {
  const match = sourceCandidateForEvidence(segment, sourcePackage);
  const rawHints = Array.isArray(match?.anton_slot_hints) ? match.anton_slot_hints : [];
  const hints = rawHints.map((slot: any) => String(slot || "").trim()).filter(Boolean);
  if (hints.length > 0) return hints;
  return match ? Array.from(antonSourceSlotHints(match?.text)) : [];
}

function sourceSlotHintsForCandidate(candidate: any): string[] {
  const rawHints = Array.isArray(candidate?.anton_slot_hints) ? candidate.anton_slot_hints : [];
  const hints = rawHints.map((slot: any) => String(slot || "").trim()).filter(Boolean);
  if (hints.length > 0) return hints;
  return Array.from(antonSourceSlotHints(candidate?.text));
}

function hostnameForSource(url: unknown): string {
  try {
    const host = new URL(String(url || "")).hostname.toLowerCase();
    return host.startsWith("www.") ? host.slice(4) : host;
  } catch {
    return "";
  }
}

function sourceTierForUrl(url: unknown, title: unknown = ""): number {
  const host = hostnameForSource(url);
  const titleText = String(title || "").toLowerCase();
  const cautionHosts = [
    "wikipedia.org", "youtube.com", "youtu.be", "facebook.com", "instagram.com",
    "tiktok.com", "x.com", "twitter.com", "reddit.com", "quora.com",
    "fandom.com", "pinterest.com",
  ];
  if (cautionHosts.some((item) => host === item || host.endsWith(`.${item}`))) return 4;
  if (host.includes("forum") || host.includes("wiki")) return 4;
  const primaryHosts = [
    "boeing.com", "lockheedmartin.com", "northropgrumman.com", "rtx.com",
    "prattwhitney.com", "geaerospace.com", "defense.gov", "af.mil",
    "army.mil", "navy.mil", "marines.mil", "usafa.edu", "nasa.gov",
    "archives.gov", "congress.gov",
  ];
  if (host.endsWith(".gov") || host.endsWith(".mil") || primaryHosts.some((item) => host === item || host.endsWith(`.${item}`))) return 1;
  const authoritativeHosts = [
    "si.edu", "airandspace.si.edu", "nationalww2museum.org", "iwm.org.uk",
    "imperialwarmuseums.org.uk", "rafmuseum.org.uk", "aerospace.org",
    "historynet.com", "aviation-history.com",
  ];
  if (authoritativeHosts.some((item) => host === item || host.endsWith(`.${item}`))) return 2;
  if (host.includes("museum") || titleText.includes("museum") || host.includes("archive")) return 2;
  return host ? 3 : 0;
}

function sourceTierNumber(candidate: any): number {
  const rawTier = Number(candidate?.source_tier || candidate?.tier || 0);
  if (rawTier) return rawTier;
  const label = String(candidate?.source_tier_label || candidate?.label || "");
  const match = label.match(/tier\s*(\d+)/i);
  if (match) return Number(match[1]);
  return sourceTierForUrl(candidate?.source_url || candidate?.url, candidate?.source_title || candidate?.title);
}

function antonSourceSlotHints(text: unknown): Set<string> {
  const lower = normalizedSourceText(text);
  const slotPatterns: Record<string, RegExp[]> = {
    original_problem: [
      /\bproblem\b/,
      /\b(?:requirement|required|called for|needed?|wanted|demanded|requested|specified)\b/,
      /\b(?:project|program|contract|mission|specification)\b/,
      /\b(?:designed|developed|intended)\s+to\b/,
      /\basked\s+whether\b/,
    ],
    engineering_decision: [
      /\b(?:design|decision|built|developed|configured|equipped|mounted|carried|powered)\b/,
      /\b(?:wing|wingspan|fuselage|engine|engines|payload|range|speed|horsepower|propulsion)\b/,
      /\b(?:model|prototype|airframe|structure|configuration|feature|features)\b/,
    ],
    tradeoff: [
      /\btrade[- ]?off\b/,
      /\b(?:limitation|limited|underpowered|slow|sluggish|obsolete|problem|failed|failure)\b/,
      /\b(?:could not|couldn['’]?t|unable|too\s+(?:slow|heavy|large|expensive|costly))\b/,
      /\b(?:sacrificed|compromise|drawback|despite|but|however|stranded|cancelled|canceled)\b/,
    ],
    reality: [
      /\breality\b/,
      /\b(?:served|service|assigned|used|flew|operated|converted|transport|missions?)\b/,
      /\b(?:production|produced|built|prototype|prototypes|delivered|scrapped|retired)\b/,
      /\b(?:combat|war|world war|record|lost|losses|cancelled|canceled|operational)\b/,
    ],
  };
  const hints = new Set<string>();
  Object.entries(slotPatterns).forEach(([slot, patterns]) => {
    if (patterns.some((pattern) => pattern.test(lower))) hints.add(slot);
  });
  return hints;
}

const REQUIRED_ANTON_SOURCE_SLOTS = ["original_problem", "engineering_decision", "tradeoff", "reality"];

function sourceExcerptId(candidate: any): string {
  return String(candidate?.excerpt_id || candidate?.locator || "").trim();
}

function sourceExcerptTextById(excerpts: any[]): Record<string, string> {
  return excerpts.reduce((rows: Record<string, string>, candidate: any) => {
    const excerptId = sourceExcerptId(candidate);
    const text = String(candidate?.text || "").trim();
    if (excerptId && text) rows[excerptId] = text;
    return rows;
  }, {});
}

function sourceSlotEvidenceBySlot(excerpts: any[]): Record<string, string[]> {
  return excerpts.reduce((rows: Record<string, string[]>, candidate: any) => {
    const excerptId = sourceExcerptId(candidate);
    const hints = Array.isArray(candidate?.anton_slot_hints)
      ? candidate.anton_slot_hints.map((slot: any) => String(slot || "").trim()).filter(Boolean)
      : Array.from(antonSourceSlotHints(candidate?.text));
    hints.forEach((slot: string) => {
      if (!excerptId) return;
      rows[slot] = rows[slot] || [];
      if (!rows[slot].includes(excerptId)) rows[slot].push(excerptId);
    });
    return rows;
  }, {});
}

function sourceCandidateTraceable(candidate: any): boolean {
  const allowedCaptureMethods = new Set(["fetched_page", "tavily_raw_content"]);
  const sourceUrl = String(candidate?.source_url || "").trim();
  const locator = String(candidate?.locator || candidate?.excerpt_id || "").trim();
  const captureMethod = String(candidate?.source_capture_method || "").trim();
  return Boolean(sourceUrl && locator && allowedCaptureMethods.has(captureMethod));
}

function untraceableAntonSourceSlots(excerpts: any[]): string[] {
  return REQUIRED_ANTON_SOURCE_SLOTS.filter((slot) => {
    const slotCandidates = excerpts.filter((candidate: any) => {
      const hints = Array.isArray(candidate?.anton_slot_hints)
        ? candidate.anton_slot_hints.map((hint: any) => String(hint || "").trim()).filter(Boolean)
        : Array.from(antonSourceSlotHints(candidate?.text));
      return hints.includes(slot);
    });
    return slotCandidates.length > 0 && !slotCandidates.some(sourceCandidateTraceable);
  });
}

function tierFourOnlyAntonSourceSlots(excerpts: any[]): string[] {
  return REQUIRED_ANTON_SOURCE_SLOTS.filter((slot) => {
    const slotCandidates = excerpts.filter((candidate: any) => {
      const hints = Array.isArray(candidate?.anton_slot_hints)
        ? candidate.anton_slot_hints.map((hint: any) => String(hint || "").trim()).filter(Boolean)
        : Array.from(antonSourceSlotHints(candidate?.text));
      return hints.includes(slot);
    });
    const traceableCandidates = slotCandidates.filter(sourceCandidateTraceable);
    return traceableCandidates.length > 0 && traceableCandidates.every((candidate: any) => sourceTierNumber(candidate) >= 4);
  });
}

function excerptTextsOverlap(left: unknown, right: unknown): boolean {
  const leftText = normalizedSourceText(left);
  const rightText = normalizedSourceText(right);
  if (!leftText || !rightText) return false;
  if (leftText === rightText || leftText.includes(rightText) || rightText.includes(leftText)) return true;
  const stopwords = new Set(["a", "an", "and", "as", "by", "for", "from", "in", "into", "of", "on", "or", "source", "sourced", "supplied", "grounded", "claim", "claims", "exact", "text", "the", "this", "that", "to", "was", "with"]);
  const leftTokens = new Set((leftText.match(/[a-z0-9]+/g) || []).filter((token) => !stopwords.has(token)));
  const rightTokens = new Set((rightText.match(/[a-z0-9]+/g) || []).filter((token) => !stopwords.has(token)));
  if (Math.min(leftTokens.size, rightTokens.size) < 12) return false;
  const intersection = Array.from(leftTokens).filter((token) => rightTokens.has(token)).length;
  return intersection / Math.max(1, Math.min(leftTokens.size, rightTokens.size)) >= 0.95;
}

function distinctAntonSlotAssignment(
  evidenceBySlot: Record<string, string[]>,
  requiredSlots = REQUIRED_ANTON_SOURCE_SLOTS,
  excerptTextById: Record<string, string> = {}
): Record<string, string> {
  const orderedSlots = [...requiredSlots].sort((a, b) => (evidenceBySlot[a]?.length || 0) - (evidenceBySlot[b]?.length || 0));
  const assignment: Record<string, string> = {};
  const used = new Set<string>();
  const conflictsWithUsed = (excerptId: string): boolean => {
    const text = excerptTextById[excerptId];
    if (!text) return false;
    return Array.from(used).some((usedId) => excerptTextsOverlap(text, excerptTextById[usedId]));
  };

  const assign = (index: number): boolean => {
    if (index >= orderedSlots.length) return true;
    const slot = orderedSlots[index];
    for (const excerptId of evidenceBySlot[slot] || []) {
      if (!excerptId || used.has(excerptId) || conflictsWithUsed(excerptId)) continue;
      assignment[slot] = excerptId;
      used.add(excerptId);
      if (assign(index + 1)) return true;
      used.delete(excerptId);
      delete assignment[slot];
    }
    return false;
  };

  if (!assign(0)) return {};
  return requiredSlots.reduce((rows: Record<string, string>, slot) => {
    if (assignment[slot]) rows[slot] = assignment[slot];
    return rows;
  }, {});
}

function antonSlotRoleForEvidenceKind(kind: unknown): string {
  const normalized = String(kind || "").trim().toLowerCase();
  const kindMap: Record<string, string[]> = {
    original_problem: ["original_problem", "design_problem", "engineering_intent", "design_requirement", "doctrinal_problem", "identity_origin", "design_intent"],
    engineering_decision: ["engineering_decision", "engineering_response", "design_response", "scale_specs", "validated_concept"],
    tradeoff: ["tradeoff", "tradeoff_or_limit", "limitation", "failure_mode"],
    reality: ["reality", "actual_reality", "actual_outcome", "service_reality", "operational_reality", "combat_reality", "test_result", "build_reality", "production_reality", "prototype_reality", "historical_meaning", "legacy"],
  };
  return Object.entries(kindMap).find(([, kinds]) => kinds.includes(normalized))?.[0] || "";
}

function sourcePackageStatus(sourcePackage: any, machine: string = ""): { ready: boolean; message: string } {
  const rawExcerpts = Array.isArray(sourcePackage?.candidate_excerpts) ? sourcePackage.candidate_excerpts : [];
  const excerpts = rawExcerpts.filter((candidate: any) => String(candidate?.text || "").trim());
  if (!sourcePackage || excerpts.length < 6) {
    return { ready: false, message: "Raw source package missing · preview blocked" };
  }
  const allowedCaptureMethods = new Set(["fetched_page", "tavily_raw_content"]);
  const missingCaptureMethodCount = excerpts.filter((candidate: any) => !String(candidate?.source_capture_method || "").trim()).length;
  const unsupportedCaptureMethods = new Set(
    excerpts
      .map((candidate: any) => String(candidate?.source_capture_method || "").trim())
      .filter((method: string) => method && !allowedCaptureMethods.has(method))
  );
  if (missingCaptureMethodCount > 0) {
    return { ready: false, message: `Raw source package missing capture method · ${missingCaptureMethodCount} excerpt · preview blocked` };
  }
  if (unsupportedCaptureMethods.size > 0) {
    return { ready: false, message: `Raw source package unsupported capture · ${Array.from(unsupportedCaptureMethods).join(", ")} · preview blocked` };
  }
  const targetCode = normalizedUnitCode(machine);
  const packageKey = normalizedUnitCode(String(sourcePackage?.machine_key || ""));
  const packageMachine = normalizedUnitCode(String(sourcePackage?.machine || ""));
  if (targetCode && ((!packageKey && !packageMachine) || (packageKey && packageKey !== targetCode) || (packageMachine && packageMachine !== targetCode))) {
    return { ready: false, message: "Raw source package machine mismatch · preview blocked" };
  }
  const targetExcerpts = machine ? excerpts.filter((candidate: any) => textMentionsMachine(candidate?.text, machine)) : excerpts;
  if (machine && targetExcerpts.length < 6) {
    return { ready: false, message: `Raw source package target-thin · ${targetExcerpts.length}/${excerpts.length} matching excerpts · preview blocked` };
  }
  if (machine) {
    const savedMissingSlots = Array.isArray(sourcePackage?.source_slot_coverage?.missing_slots)
      ? sourcePackage.source_slot_coverage.missing_slots.map((slot: any) => String(slot || "").trim()).filter(Boolean)
      : [];
    const computedEvidenceBySlot = sourceSlotEvidenceBySlot(targetExcerpts);
    const missingSlots = savedMissingSlots.length > 0
      ? savedMissingSlots
      : (() => {
          const coveredSlots = new Set(Object.keys(computedEvidenceBySlot));
          return REQUIRED_ANTON_SOURCE_SLOTS
            .filter((slot) => !coveredSlots.has(slot));
        })();
    if (missingSlots.length > 0) {
      return { ready: false, message: `Raw source package missing Anton slots · ${missingSlots.join(", ")} · preview blocked` };
    }
    const untraceableSlots = untraceableAntonSourceSlots(targetExcerpts);
    if (untraceableSlots.length > 0) {
      return { ready: false, message: `Raw source package untraceable Anton slots · ${untraceableSlots.join(", ")} · preview blocked` };
    }
    const traceableTargetExcerpts = targetExcerpts.filter(sourceCandidateTraceable);
    const traceableEvidenceBySlot = sourceSlotEvidenceBySlot(traceableTargetExcerpts);
    const savedNeedsDistinct = sourcePackage?.source_slot_coverage?.needs_distinct_slot_excerpts === true;
    const distinctAssignment = distinctAntonSlotAssignment(
      traceableEvidenceBySlot,
      REQUIRED_ANTON_SOURCE_SLOTS,
      sourceExcerptTextById(traceableTargetExcerpts)
    );
    if (savedNeedsDistinct || Object.keys(distinctAssignment).length < REQUIRED_ANTON_SOURCE_SLOTS.length) {
      return { ready: false, message: "Raw source package needs distinct Anton excerpts · preview blocked" };
    }
    const cautionOnlySlots = tierFourOnlyAntonSourceSlots(targetExcerpts);
    if (cautionOnlySlots.length > 0) {
      return { ready: false, message: `Raw source package Tier 4-only Anton slots · ${cautionOnlySlots.join(", ")} · preview blocked` };
    }
  }
  const sourceUrls = new Set(
    targetExcerpts.map((candidate: any) => String(candidate?.source_url || "").trim()).filter(Boolean)
  );
  const nonCautionUrls = new Set(
    targetExcerpts
      .filter((candidate: any) => String(candidate?.source_url || "").trim() && sourceTierNumber(candidate) > 0 && sourceTierNumber(candidate) <= 3)
      .map((candidate: any) => String(candidate?.source_url || "").trim())
  );
  const authoritativeUrls = new Set(
    targetExcerpts
      .filter((candidate: any) => String(candidate?.source_url || "").trim() && sourceTierNumber(candidate) > 0 && sourceTierNumber(candidate) <= 2)
      .map((candidate: any) => String(candidate?.source_url || "").trim())
  );
  if (sourceUrls.size < 2) {
    return { ready: false, message: `Raw source package thin · ${targetExcerpts.length} excerpts / ${sourceUrls.size} source URL · preview blocked` };
  }
  if (nonCautionUrls.size < 1) {
    return { ready: false, message: "Raw source package caution-only · preview blocked" };
  }
  if (authoritativeUrls.size < 1) {
    return { ready: false, message: "Raw source package needs Tier 1-2 source · preview blocked" };
  }
  if (sourcePackage.passed === false) {
    const errors = Array.isArray(sourcePackage?.errors)
      ? sourcePackage.errors.map((error: any) => String(error || "").trim()).filter(Boolean)
      : [];
    return { ready: false, message: `Raw source package failed · ${errors[0] || "preview blocked"}` };
  }
  return { ready: true, message: `Raw source package ready · ${targetExcerpts.length} excerpts · ${sourceUrls.size} sources` };
}

function sourcePackageReady(sourcePackage: any, machine: string = ""): boolean {
  return sourcePackageStatus(sourcePackage, machine).ready;
}

function sourceSlotCoverageRows(sourcePackage: any, machine: string = "") {
  const requiredSlots = REQUIRED_ANTON_SOURCE_SLOTS;
  const savedCoverage = sourcePackage?.source_slot_coverage;
  const savedEvidenceBySlot = savedCoverage && typeof savedCoverage === "object" && !Array.isArray(savedCoverage?.evidence_by_slot)
    ? savedCoverage.evidence_by_slot
    : {};
  const rawExcerpts = Array.isArray(sourcePackage?.candidate_excerpts) ? sourcePackage.candidate_excerpts : [];
  const targetExcerpts = machine ? rawExcerpts.filter((candidate: any) => textMentionsMachine(candidate?.text, machine)) : rawExcerpts;
  const computedEvidenceBySlot = sourceSlotEvidenceBySlot(targetExcerpts);

  const labelBySlot: Record<string, string> = {
    original_problem: "Problem",
    engineering_decision: "Decision",
    tradeoff: "Tradeoff",
    reality: "Reality",
  };

  return requiredSlots.map((slot) => {
    const savedIds = Array.isArray(savedEvidenceBySlot?.[slot])
      ? savedEvidenceBySlot[slot].map((id: any) => String(id || "").trim()).filter(Boolean)
      : [];
    const evidenceIds = savedIds.length > 0 ? savedIds : (computedEvidenceBySlot[slot] || []);
    return {
      slot,
      label: labelBySlot[slot] || slot,
      covered: evidenceIds.length > 0,
      evidenceIds,
    };
  });
}

function machineResearchCardStatus(card: any, machine: string = "", sourcePackage: any = null): { ready: boolean; message: string } {
  if (!card) return { ready: false, message: "Research card missing · preview blocked" };
  const timeframe = String(card?.timeframe || "").trim();
  const timeframeEvidenceIds = Array.isArray(card?.timeframe_evidence_ids)
    ? card.timeframe_evidence_ids.map((item: any) => String(item || "").trim()).filter(Boolean)
    : [];
  if (timeframe.split(/\s+/).filter(Boolean).length < 5 || timeframeEvidenceIds.length < 1) {
    return { ready: false, message: "Timeframe missing · preview blocked" };
  }
  const visualIdentity = String(card?.visual_identity || "").trim();
  const visualIdentityEvidenceIds = Array.isArray(card?.visual_identity_evidence_ids)
    ? card.visual_identity_evidence_ids.map((item: any) => String(item || "").trim()).filter(Boolean)
    : [];
  if (visualIdentity.split(/\s+/).filter(Boolean).length < 8 || visualIdentityEvidenceIds.length < 1) {
    return { ready: false, message: "Visual identity missing · preview blocked" };
  }
  const evidenceSegments = Array.isArray(card?.evidence_segments) ? card.evidence_segments : [];
  const hasSourcedMemorableFact = evidenceSegments.some((segment: any) => (
    ["memorable_fact", "surprising_fact", "retention_fact"].includes(String(segment?.kind || "").trim().toLowerCase())
    && String(segment?.source_excerpt || "").trim()
    && (String(segment?.source_url || "").trim() || String(segment?.locator || "").trim())
  ));
  if (!hasSourcedMemorableFact) {
    return { ready: false, message: "Sourced memorable fact missing · preview blocked" };
  }
  const evidenceIds = new Set(
    evidenceSegments
      .map((segment: any) => String(segment?.evidence_id || "").trim())
      .filter(Boolean)
  );
  const evidenceById = new Map(
    evidenceSegments
      .filter((segment: any) => String(segment?.evidence_id || "").trim())
      .map((segment: any) => [String(segment?.evidence_id || "").trim(), segment])
  );
  const unknownTimeframeEvidenceIds = timeframeEvidenceIds.filter((id: string) => !evidenceIds.has(id));
  if (unknownTimeframeEvidenceIds.length > 0) {
    return { ready: false, message: `Timeframe evidence missing · ${unknownTimeframeEvidenceIds.join(", ")} · preview blocked` };
  }
  const unknownEvidenceIds = visualIdentityEvidenceIds.filter((id: string) => !evidenceIds.has(id));
  if (unknownEvidenceIds.length > 0) {
    return { ready: false, message: `Visual identity evidence missing · ${unknownEvidenceIds.join(", ")} · preview blocked` };
  }
  if (machine && !machineLabelMatches(cardLabel(card), machine)) {
    return { ready: false, message: "Research card machine mismatch · preview blocked" };
  }
  if (sourcePackage && Array.isArray(sourcePackage?.candidate_excerpts)) {
    const sourcedSegments = evidenceSegments.filter((segment: any) => String(segment?.source_excerpt || "").trim());
    const staleSegment = sourcedSegments.find((segment: any) => (
      !String(segment?.source_url || "").trim()
      || !String(segment?.locator || "").trim()
      || !sourceCandidateForEvidence(segment, sourcePackage)
    ));
    if (staleSegment) {
      const evidenceId = String(staleSegment?.evidence_id || "unknown evidence").trim();
      return { ready: false, message: `Evidence source mismatch · ${evidenceId} · preview blocked` };
    }
    const requiredSourceTextById: Record<string, string> = {};
    const requiredSourceIdsBySlot = sourcedSegments.reduce((rows: Record<string, string[]>, segment: any) => {
      const role = antonSlotRoleForEvidenceKind(segment?.kind);
      if (!REQUIRED_ANTON_SOURCE_SLOTS.includes(role)) return rows;
      const match = sourceCandidateForEvidence(segment, sourcePackage);
      const excerptId = String(match?.excerpt_id || segment?.source_excerpt_id || match?.locator || segment?.locator || "").trim();
      if (!excerptId) return rows;
      const excerptText = String(match?.text || segment?.source_excerpt || "").trim();
      if (excerptText) requiredSourceTextById[excerptId] = excerptText;
      rows[role] = rows[role] || [];
      if (!rows[role].includes(excerptId)) rows[role].push(excerptId);
      return rows;
    }, {});
    const missingRequiredSlots = REQUIRED_ANTON_SOURCE_SLOTS.filter((slot) => !(requiredSourceIdsBySlot[slot]?.length));
    if (missingRequiredSlots.length > 0) {
      return { ready: false, message: `Research card missing Anton slots · ${missingRequiredSlots.join(", ")} · preview blocked` };
    }
    const requiredAssignment = distinctAntonSlotAssignment(
      requiredSourceIdsBySlot,
      REQUIRED_ANTON_SOURCE_SLOTS,
      requiredSourceTextById
    );
    if (Object.keys(requiredAssignment).length < REQUIRED_ANTON_SOURCE_SLOTS.length) {
      return { ready: false, message: "Research card needs distinct Anton excerpts · preview blocked" };
    }
    const selectedTiers = sourcedSegments
      .map((segment: any) => sourceTierForEvidence(segment, sourcePackage)?.tier || 0)
      .filter((tier: number) => tier > 0);
    if (selectedTiers.length > 0 && selectedTiers.every((tier: number) => tier > 2)) {
      return { ready: false, message: "Research card needs selected Tier 1-2 evidence · preview blocked" };
    }
    const timeframeTiers = timeframeEvidenceIds
      .map((id: string) => sourceTierForEvidence(evidenceById.get(id), sourcePackage)?.tier || 0)
      .filter((tier: number) => tier > 0);
    if (timeframeTiers.length > 0 && timeframeTiers.every((tier: number) => tier >= 4)) {
      return { ready: false, message: "Timeframe evidence Tier 4-only · preview blocked" };
    }
    const visualTiers = visualIdentityEvidenceIds
      .map((id: string) => sourceTierForEvidence(evidenceById.get(id), sourcePackage)?.tier || 0)
      .filter((tier: number) => tier > 0);
    if (visualTiers.length > 0 && visualTiers.every((tier: number) => tier >= 4)) {
      return { ready: false, message: "Visual identity evidence Tier 4-only · preview blocked" };
    }
  }
  return { ready: true, message: "Research card ready · visual identity grounded" };
}

function machineResearchCardReady(card: any, machine: string = "", sourcePackage: any = null): boolean {
  return machineResearchCardStatus(card, machine, sourcePackage).ready;
}

function sourcePackageForMachine(packages: any, machine: string): any | null {
  if (!packages || typeof packages !== "object" || !machine) return null;
  const key = normalizedUnitCode(machine);
  if (!Array.isArray(packages) && key && packages[key]) return packages[key];
  const rows = Array.isArray(packages) ? packages : Object.entries(packages).map(([rawKey, value]) => ({ rawKey, value }));
  for (const row of rows) {
    const rawKey = Array.isArray(packages) ? "" : String(row.rawKey || "");
    const candidate = Array.isArray(packages) ? row : row.value;
    if (!candidate || typeof candidate !== "object") continue;
    const packageMachine = String(candidate.machine || "");
    const packageKey = String(candidate.machine_key || "");
    if (
      normalizedUnitCode(rawKey) === key
      || normalizedUnitCode(packageMachine) === key
      || normalizedUnitCode(packageKey) === key
    ) {
      return candidate;
    }
  }
  return null;
}

function CollapsibleSection({ label, borderColor, children, defaultOpen = false }: {
  label: string; borderColor?: string; children: React.ReactNode; defaultOpen?: boolean;
}) {
  const [open, setOpen] = useState(defaultOpen);
  return (
    <GlassCard className="p-5" style={borderColor ? { borderLeftWidth: 3, borderLeftColor: borderColor } : undefined}>
      <button
        className="flex items-center gap-2 w-full text-left"
        onClick={() => setOpen(!open)}
      >
        {open ? <ChevronDown size={14} style={{ color: "var(--text-tertiary)" }} /> : <ChevronRight size={14} style={{ color: "var(--text-tertiary)" }} />}
        <h3 className="text-[10px] font-semibold uppercase tracking-wider" style={{ color: "var(--text-tertiary)" }}>
          {label}
        </h3>
      </button>
      {open && <div className="mt-3">{children}</div>}
    </GlassCard>
  );
}

function TagChips({ text }: { text: string }) {
  // Split on bullet points, numbered lists, newlines, or semicolons
  const items = text
    .split(/[\n•;]|(?:\d+\.\s)/)
    .map(s => s.replace(/^[-–—]\s*/, "").trim())
    .filter(s => s.length > 0 && s.length < 120);

  if (items.length <= 1) {
    return <p className="text-sm leading-relaxed whitespace-pre-line" style={{ color: "var(--text-primary)" }}>{text}</p>;
  }

  return (
    <div className="flex flex-wrap gap-2">
      {items.map((item, i) => (
        <span
          key={i}
          className="inline-block px-3 py-1.5 rounded-lg text-xs font-medium"
          style={{ background: "var(--bg-elevated)", color: "var(--text-secondary)", border: "1px solid var(--border)" }}
        >
          {item}
        </span>
      ))}
    </div>
  );
}

function BulletList({ text }: { text: string }) {
  // Parse facts/parallels into separate items by splitting on numbered patterns or bullet-like separators
  const items = text
    .split(/\n(?=[-•\d])|(?<=\.)\s*(?=\d+\.)/)
    .map(s => s.replace(/^[-•\d]+[.)]\s*/, "").trim())
    .filter(Boolean);

  if (items.length <= 1) {
    return <p className="text-sm leading-relaxed whitespace-pre-line" style={{ color: "var(--text-primary)" }}>{text}</p>;
  }

  return (
    <ul className="space-y-2">
      {items.map((item, i) => (
        <li key={i} className="flex gap-2 text-sm leading-relaxed" style={{ color: "var(--text-primary)" }}>
          <span className="shrink-0 mt-1.5 w-1.5 h-1.5 rounded-full" style={{ background: "var(--turquoise)" }} />
          <span>{item}</span>
        </li>
      ))}
    </ul>
  );
}

function SourceList({ text }: { text: string }) {
  const lines = text.split("\n").map(s => s.trim()).filter(Boolean);
  return (
    <div className="space-y-1">
      {lines.map((line, i) => {
        // Try to extract URL from the line
        const urlMatch = line.match(/(https?:\/\/[^\s)]+)/);
        return (
          <div key={i} className="text-xs font-mono leading-relaxed" style={{ color: "var(--text-secondary)" }}>
            {urlMatch ? (
              <>
                {line.replace(urlMatch[0], "").replace(/[-–—]\s*$/, "").trim()}{" "}
                <a href={urlMatch[0]} target="_blank" rel="noopener noreferrer" className="underline" style={{ color: "var(--turquoise)" }}>
                  {urlMatch[0].length > 60 ? urlMatch[0].slice(0, 60) + "..." : urlMatch[0]}
                </a>
              </>
            ) : (
              line
            )}
          </div>
        );
      })}
    </div>
  );
}

function EditableText({ text, mono }: { text: string; mono?: boolean }) {
  return (
    <textarea
      defaultValue={text}
      rows={Math.max(3, Math.ceil(text.length / 100))}
      className={`w-full text-sm leading-relaxed whitespace-pre-line resize-none outline-none rounded-lg px-2 py-1 transition-all ${mono ? "font-mono text-xs" : ""}`}
      style={{ color: "var(--text-primary)", background: "transparent", border: "1px solid transparent" }}
      onFocus={(e) => { e.target.style.background = "var(--bg-elevated)"; e.target.style.borderColor = "var(--turquoise)"; }}
      onBlur={(e) => { e.target.style.background = "transparent"; e.target.style.borderColor = "transparent"; }}
    />
  );
}

export function ResearchTab({ video, onApproved }: ResearchTabProps) {
  const queryClient = useQueryClient();
  const toast = useToast();
  const [isResearching, setIsResearching] = useState(false);
  const [isApproving, setIsApproving] = useState(false);
  const [approved, setApproved] = useState(false);
  const [showFeedback, setShowFeedback] = useState(false);
  const [feedbackText, setFeedbackText] = useState("");
  const [feedbackSaved, setFeedbackSaved] = useState(false);
  const [feedbackSaving, setFeedbackSaving] = useState(false);
  const [approveError, setApproveError] = useState<string | null>(null);
  const [taskRunning, setTaskRunning] = useState(false);
  const [selectedMachine, setSelectedMachine] = useState("");
  const [singleMachineRunning, setSingleMachineRunning] = useState(false);
  const [singlePreviewRunning, setSinglePreviewRunning] = useState(false);
  const [localMachinePreview, setLocalMachinePreview] = useState<MachineScriptPreview | null>(null);

  const { message: taskMessage } = useTaskPoller({
    videoId: video.id,
    enabled: taskRunning,
    interval: 3000,
    onComplete: () => {
      setTaskRunning(false);
      setIsResearching(false);
      queryClient.invalidateQueries({ queryKey: ["video", video.id] });
      queryClient.invalidateQueries({ queryKey: ["video-script", video.id] });
      queryClient.invalidateQueries({ queryKey: ["video-assets", video.id] });
    },
    onFailed: (error) => {
      setTaskRunning(false);
      setIsResearching(false);
      toast.error(`Research failed: ${error}`);
    },
  });

  const handleReResearch = useCallback(async () => {
    setIsResearching(true);
    try {
      await runPipelineStage(video.id, "research");
      setTaskRunning(true);
    } catch (err: unknown) {
      const message = (err as Error).message || "";
      if (message.includes("409")) {
        try {
          await clearStaleTask(video.id);
          await runPipelineStage(video.id, "research");
          setTaskRunning(true);
          return;
        } catch (retryErr) {
          toast.error(`Research failed: ${(retryErr as Error).message}`);
        }
      } else {
        toast.error(`Research failed: ${message}`);
      }
      setIsResearching(false);
    }
  }, [video.id]);

  const handleOneMachineResearch = useCallback(async () => {
    setSingleMachineRunning(true);
    try {
      const payload = typeof video.research_payload === "string" ? JSON.parse(video.research_payload || "{}") : video.research_payload;
      const roster = Array.isArray(payload?.unit_roster) ? payload.unit_roster : [];
      const machine = selectedMachine || machineLabel(roster[0]);
      if (!machine) {
        throw new Error("No locked machine selected.");
      }
      const result = await runOneMachineResearch(video.id, machine);
      setLocalMachinePreview(null);
      if (result.research_payload) {
        queryClient.setQueryData(["video", video.id], (current: any) => (
          current ? { ...current, research_payload: result.research_payload } : current
        ));
      }
      queryClient.invalidateQueries({ queryKey: ["video", video.id] });
      if (result.status === "needs_review") {
        toast.error("Raw source package saved. Machine card needs review.");
      } else {
        toast.success("Machine research saved.");
      }
    } catch (err: unknown) {
      toast.error(`Machine research failed: ${(err as Error).message || "Unknown error"}`);
    } finally {
      setSingleMachineRunning(false);
    }
  }, [video.id, video.research_payload, selectedMachine, queryClient, toast]);

  const handleOneMachinePreview = useCallback(async () => {
    setSinglePreviewRunning(true);
    let machine = selectedMachine || "";
    try {
      const payload = typeof video.research_payload === "string" ? JSON.parse(video.research_payload || "{}") : video.research_payload;
      const roster = Array.isArray(payload?.unit_roster) ? payload.unit_roster : [];
      machine = selectedMachine || machineLabel(roster[0]);
      if (!machine) {
        throw new Error("No locked machine selected.");
      }
      const result = await runMachineScriptPreview(video.id, machine);
      setLocalMachinePreview(result.preview);
      if (result.research_payload) {
        queryClient.setQueryData(["video", video.id], (current: any) => (
          current ? { ...current, research_payload: result.research_payload } : current
        ));
      }
      queryClient.invalidateQueries({ queryKey: ["video", video.id] });
      if (machinePreviewPassesAntonGate(result.preview)) {
        toast.success("Single-machine preview passed. Production script unchanged.");
      } else {
        toast.error("Single-machine preview needs review. Production script unchanged.");
      }
    } catch (err: unknown) {
      const message = (err as Error).message || "Unknown error";
      if (machine) {
        setLocalMachinePreview({
          machine,
          scene: 0,
          paragraph: "",
          word_count: 0,
          passed: false,
          warnings: [message],
          research_source: "preview_error",
          claim_bundle: { claim_map: [] },
        });
      }
      toast.error(`Script preview failed: ${message}. Production script unchanged.`);
    } finally {
      setSinglePreviewRunning(false);
    }
  }, [video.id, video.research_payload, selectedMachine, queryClient, toast]);

  const handleApproveResearch = useCallback(async () => {
    let rosterGate: any = null;
    try {
      const payload = typeof video.research_payload === "string" ? JSON.parse(video.research_payload) : video.research_payload;
      rosterGate = payload?.unit_roster_validation;
      const lockedRoster = Array.isArray(payload?.unit_roster) ? payload.unit_roster : [];
      const machineResearchGate = payload?.unit_research_hold_validation;
      const cards = Array.isArray(payload?.unit_research_cards) ? payload.unit_research_cards : [];
      const packages = payload?.machine_raw_source_packages && typeof payload.machine_raw_source_packages === "object" && !Array.isArray(payload.machine_raw_source_packages)
        ? payload.machine_raw_source_packages
        : {};
      const verifiedCount = lockedRoster.filter((item: any) => {
        const label = machineLabel(item);
        const card = cards.find((candidate: any) => cardMatchesMachine(candidate, label));
        const sourcePackage = sourcePackageForMachine(packages, label);
        return machineResearchCardReady(card, label, sourcePackage) && sourcePackageReady(sourcePackage, label);
      }).length;
      if (lockedRoster.length > 0 && !fullMachineResearchGatePassed(machineResearchGate, verifiedCount, lockedRoster.length)) {
        setApproveError(`Machine research is incomplete: ${verifiedCount}/${lockedRoster.length} verified cards finished.`);
        return;
      }
    } catch { /* ignore malformed payload */ }
    if (rosterGate?.complete_title && rosterGate?.passed === false) {
      setApproveError(`Roster gate failed: ${(rosterGate.warnings || []).join("; ") || "research roster is incomplete"}`);
      return;
    }
    if (!confirm("Approve research and move to scripting?")) return;
    setIsApproving(true);
    setApproveError(null);
    try {
      await advanceVideo(video.id);
      setApproved(true);
      queryClient.invalidateQueries({ queryKey: ["video", video.id] });
      window.scrollTo({ top: 0, behavior: "smooth" });
      onApproved?.();
    } catch (err) {
      setApproveError((err as Error).message);
      setIsApproving(false);
    }
  }, [video.id, video.research_payload, queryClient, onApproved]);

  const research = useMemo(() => {
    if (!video) return null;
    let payload: Record<string, any> = {};
    if (video.research_payload) {
      try {
        payload = typeof video.research_payload === "string"
          ? JSON.parse(video.research_payload)
          : video.research_payload;
      } catch {
        payload = {};
      }
    }
    return {
      headline: video.headline || payload.headline || null,
      thesis: video.thesis || payload.thesis || null,
      executive_hook: video.executive_hook || payload.executive_hook || null,
      fact_sheet: payload.fact_sheet || null,
      historical_parallels: payload.historical_parallels || null,
      framework_analysis: payload.framework_analysis || null,
      character_dossier: payload.character_dossier || null,
      narrative_arc: payload.narrative_arc || payload.narrative_arc_suggestion || null,
      counter_arguments: payload.counter_arguments || null,
      visual_seeds: payload.visual_seeds || null,
      themes: payload.themes || null,
      psychological_angles: payload.psychological_angles || null,
      source_bibliography: payload.source_bibliography || null,
      unit_roster: Array.isArray(payload.unit_roster) ? payload.unit_roster : [],
      machine_discovery_buckets: payload.machine_discovery_buckets || null,
      recommended_final_roster: Array.isArray(payload.recommended_final_roster) ? payload.recommended_final_roster : [],
      gap_hunt_matrix: Array.isArray(payload.gap_hunt_matrix) ? payload.gap_hunt_matrix : [],
      operator_decision_points: Array.isArray(payload.operator_decision_points) ? payload.operator_decision_points : [],
      roster_contract: payload.roster_contract || null,
      roster_audit: payload.roster_audit || null,
      unit_roster_validation: payload.unit_roster_validation || (Array.isArray(payload.unit_roster) && payload.unit_roster.length > 0
        ? {
            passed: true,
            complete_title: true,
            roster_count: payload.unit_roster.length,
            warnings: [],
            legacy_roster: true,
          }
        : null),
      unit_research_cards: Array.isArray(payload.unit_research_cards) ? payload.unit_research_cards : [],
      unit_research_hold_validation: payload.unit_research_hold_validation || null,
      machine_raw_source_packages: payload.machine_raw_source_packages && typeof payload.machine_raw_source_packages === "object" && !Array.isArray(payload.machine_raw_source_packages)
        ? payload.machine_raw_source_packages
        : {},
      machine_script_previews: payload.machine_script_previews && typeof payload.machine_script_previews === "object" && !Array.isArray(payload.machine_script_previews)
        ? payload.machine_script_previews
        : {},
    };
  }, [video]);

  const selectedMachineLabel = useMemo(() => {
    return selectedMachine || machineLabel(research?.unit_roster?.[0]) || "";
  }, [research?.unit_roster, selectedMachine]);

  const selectedResearchCard = useMemo(() => {
    if (!research || !selectedMachineLabel) return null;
    return research.unit_research_cards.find((candidate: any) => cardMatchesMachine(candidate, selectedMachineLabel)) || null;
  }, [research, selectedMachineLabel]);

  const selectedMachinePreview = useMemo(() => {
    if (localMachinePreview && previewMatchesMachine(localMachinePreview, selectedMachineLabel)) return localMachinePreview;
    return previewForMachine(research?.machine_script_previews, selectedMachineLabel);
  }, [localMachinePreview, research?.machine_script_previews, selectedMachineLabel]);

  const selectedSourcePackage = useMemo(() => {
    if (!research || !selectedMachineLabel) return null;
    return sourcePackageForMachine(research.machine_raw_source_packages, selectedMachineLabel);
  }, [research, selectedMachineLabel]);
  const selectedSourcePackageStatus = sourcePackageStatus(selectedSourcePackage, selectedMachineLabel);
  const selectedSourcePackageReady = sourcePackageReady(selectedSourcePackage, selectedMachineLabel);
  const selectedSourceCoverageRows = sourceSlotCoverageRows(selectedSourcePackage, selectedMachineLabel);
  const selectedRawSourceExcerpts = useMemo(() => {
    const excerpts = Array.isArray(selectedSourcePackage?.candidate_excerpts)
      ? selectedSourcePackage.candidate_excerpts.filter((candidate: any) => String(candidate?.text || "").trim())
      : [];
    return (selectedMachineLabel
      ? excerpts.filter((candidate: any) => textMentionsMachine(candidate?.text, selectedMachineLabel))
      : excerpts
    ).slice(0, 8);
  }, [selectedSourcePackage, selectedMachineLabel]);
  const selectedResearchCardStatus = machineResearchCardStatus(selectedResearchCard, selectedMachineLabel, selectedSourcePackage);
  const selectedResearchReady = selectedResearchCardStatus.ready && selectedSourcePackageReady;
  const selectedResearchStatusMessage = selectedResearchCardStatus.ready
    ? selectedSourcePackageStatus.message
    : selectedResearchCardStatus.message;
  const verifiedMachineResearchCount = useMemo(() => {
    if (!research) return 0;
    return research.unit_roster.filter((item: any) => {
      const label = machineLabel(item);
      const card = research.unit_research_cards.find((candidate: any) => cardMatchesMachine(candidate, label));
      const sourcePackage = sourcePackageForMachine(research.machine_raw_source_packages, label);
      return machineResearchCardReady(card, label, sourcePackage) && sourcePackageReady(sourcePackage, label);
    }).length;
  }, [research]);
  const fullMachineResearchPassed = fullMachineResearchGatePassed(
    research?.unit_research_hold_validation,
    verifiedMachineResearchCount,
    research?.unit_roster?.length || 0
  );

  const selectedPreviewClaimMap = Array.isArray(selectedMachinePreview?.claim_bundle?.claim_map)
    ? selectedMachinePreview.claim_bundle.claim_map
    : [];
  const selectedPreviewFormulaSentences = Array.isArray(selectedMachinePreview?.claim_bundle?.formula_sentences)
    ? selectedMachinePreview.claim_bundle.formula_sentences
    : [];
  const selectedMachinePreviewPassed = machinePreviewPassesAntonGate(selectedMachinePreview);

  const selectedPreviewEvidenceById = useMemo(() => {
    const rows: Record<string, {
      slot?: string;
      claim?: string;
      source_excerpt?: string;
      source_title?: string;
      source_url?: string;
      locator?: string;
      source_excerpt_id?: string;
      source_excerpt_hash?: string;
      source_tier?: string;
      source_capture_method?: string;
      source_slot_hints?: string[];
    }> = {};
    const slots = Array.isArray((selectedMachinePreview?.story_plan as any)?.slots)
      ? (selectedMachinePreview?.story_plan as any).slots
      : [];
    for (const slot of slots) {
      const slotName = String(slot?.slot || "");
      const segments = Array.isArray(slot?.evidence_segments) ? slot.evidence_segments : [];
      for (const segment of segments) {
        const id = String(segment?.evidence_id || "");
        if (!id) continue;
        rows[id] = {
          slot: slotName,
          claim: String(segment?.claim || ""),
          source_excerpt: String(segment?.source_excerpt || ""),
          source_title: String(segment?.source_title || ""),
          source_url: String(segment?.source_url || ""),
          locator: String(segment?.locator || ""),
          source_excerpt_id: String(segment?.source_excerpt_id || sourceCandidateForEvidence(segment, selectedSourcePackage)?.excerpt_id || ""),
          source_excerpt_hash: String(segment?.source_excerpt_hash || sourceCandidateForEvidence(segment, selectedSourcePackage)?.text_hash || ""),
          source_tier: sourceTierForEvidence(segment, selectedSourcePackage)?.label,
          source_capture_method: sourceCaptureMethodForEvidence(segment, selectedSourcePackage),
          source_slot_hints: sourceSlotHintsForEvidence(segment, selectedSourcePackage),
        };
      }
    }
    return rows;
  }, [selectedMachinePreview?.story_plan, selectedSourcePackage]);
  const selectedPreviewFormulaRows = selectedPreviewFormulaSentences.map((sentence: string, index: number) => {
    const expectedSlots = ["original_problem", "engineering_decision", "tradeoff", "reality"];
    const expectedSlot = expectedSlots[index] || "conclusion";
    const claimRows = index < expectedSlots.length
      ? selectedPreviewClaimMap.filter((row: any) => {
          const span = String(row?.span || "").trim();
          const slot = String(row?.slot || "").trim();
          const spanMatchesSentence = span && (span === sentence || sentence.includes(span));
          return Boolean(spanMatchesSentence && (!slot || slot === expectedSlot));
        })
      : [];
    const evidenceIds = Array.from(new Set(
      claimRows.flatMap((row: any) => {
        if (Array.isArray(row?.used_evidence_ids)) return row.used_evidence_ids;
        if (Array.isArray(row?.evidence_ids)) return row.evidence_ids;
        return [];
      }).map((id: any) => String(id || "").trim()).filter(Boolean)
    ));
    const evidenceRows = evidenceIds.map((id) => ({ id, evidence: selectedPreviewEvidenceById[id] }));
    return {
      sentence,
      slot: expectedSlot,
      label: index < expectedSlots.length ? ["problem", "decision", "tradeoff", "reality"][index] : "conclusion",
      evidenceRows,
    };
  });

  const selectedPreviewSlots = Array.isArray((selectedMachinePreview?.story_plan as any)?.slots)
    ? (selectedMachinePreview?.story_plan as any).slots
    : [];

  if (!research || !research.headline) {
    return (
      <GlassCard className="p-12 text-center">
        <Search size={32} className="mx-auto mb-3" style={{ color: "var(--text-tertiary)", opacity: 0.4 }} />
        <p className="text-lg font-display mb-2" style={{ color: "var(--text-secondary)" }}>
          Research Not Started
        </p>
        <p className="text-sm mb-6" style={{ color: "var(--text-tertiary)" }}>
          This video is at the &ldquo;{video.status?.replace(/_/g, " ") || "idea logged"}&rdquo; stage.
        </p>
        <ActionButton
          variant="filled"
          icon={isResearching || taskRunning ? Loader2 : RefreshCw}
          onClick={handleReResearch}
          disabled={isResearching || taskRunning}
        >
          {taskRunning ? (taskMessage || "Researching...") : isResearching ? "Starting..." : "Run Research"}
        </ActionButton>
      </GlassCard>
    );
  }

  return (
    <div className="space-y-4">
      {/* Headline */}
      <GlassCard className="p-5" style={{ borderLeftWidth: 3, borderLeftColor: "var(--gold)" }}>
        <h3 className="text-[10px] font-semibold uppercase tracking-wider mb-2" style={{ color: "var(--text-tertiary)" }}>
          Headline
        </h3>
        <textarea
          defaultValue={research.headline}
          rows={2}
          className="w-full text-lg font-semibold resize-none outline-none rounded-lg px-2 py-1 transition-all"
          style={{ color: "var(--text-primary)", background: "transparent", border: "1px solid transparent" }}
          onFocus={(e) => { e.target.style.background = "var(--bg-elevated)"; e.target.style.borderColor = "var(--gold)"; }}
          onBlur={(e) => { e.target.style.background = "transparent"; e.target.style.borderColor = "transparent"; }}
        />
      </GlassCard>

      {research.unit_roster_validation && (
        <GlassCard className="p-5" style={{ borderLeftWidth: 3, borderLeftColor: research.unit_roster_validation.passed ? "var(--green)" : "var(--orange)" }}>
          <div className="flex items-start justify-between gap-3 mb-3">
            <div>
              <h3 className="text-[10px] font-semibold uppercase tracking-wider mb-1" style={{ color: "var(--text-tertiary)" }}>
                Unit Roster Contract
              </h3>
              <p className="text-sm" style={{ color: research.unit_roster_validation.passed ? "var(--green)" : "var(--orange)" }}>
                {research.unit_roster_validation.passed
                  ? `Passed — ${research.unit_roster_validation.roster_count || research.unit_roster.length} locked item(s)`
                  : "Needs fix before scripting"}
              </p>
            </div>
            <span className="px-2 py-1 rounded-md text-[10px] font-semibold" style={{ background: research.unit_roster_validation.passed ? "rgba(0,230,138,.12)" : "rgba(255,120,73,.12)", color: research.unit_roster_validation.passed ? "var(--green)" : "var(--orange)" }}>
              {research.unit_roster_validation.passed ? "LOCKED" : "BLOCKED"}
            </span>
          </div>
          {research.unit_roster_validation.warnings?.length > 0 && (
            <ul className="mb-3 space-y-1">
              {research.unit_roster_validation.warnings.map((w: string, i: number) => (
                <li key={i} className="text-sm" style={{ color: "var(--orange)" }}>• {w}</li>
              ))}
            </ul>
          )}
          {research.unit_roster_validation.gaps?.length > 0 && (
            <div className="mb-3">
              <div className="text-[10px] font-semibold uppercase tracking-wider mb-2" style={{ color: "var(--text-tertiary)" }}>Likely gaps named by research</div>
              <div className="flex flex-wrap gap-2">
                {research.unit_roster_validation.gaps.map((g: string) => (
                  <span key={g} className="px-2 py-1 rounded-md text-xs" style={{ background: "rgba(255,120,73,.12)", color: "var(--orange)", border: "1px solid rgba(255,120,73,.25)" }}>{g}</span>
                ))}
              </div>
            </div>
          )}
          {research.roster_audit && (
            <div className="mb-3 grid grid-cols-1 lg:grid-cols-2 gap-3">
              {research.roster_audit.inclusion_boundary && (
                <div className="rounded-lg p-3" style={{ background: "rgba(255,255,255,.04)" }}>
                  <div className="text-[10px] font-semibold uppercase tracking-wider mb-1" style={{ color: "var(--text-tertiary)" }}>Inclusion boundary</div>
                  <p className="text-xs" style={{ color: "var(--text-secondary)" }}>{research.roster_audit.inclusion_boundary}</p>
                </div>
              )}
              <div className="rounded-lg p-3" style={{ background: "rgba(255,255,255,.04)" }}>
                <div className="text-[10px] font-semibold uppercase tracking-wider mb-2" style={{ color: "var(--text-tertiary)" }}>Research audit</div>
                <div className="text-xs space-y-1" style={{ color: "var(--text-secondary)" }}>
                  <div>Searches: {research.roster_audit.search_queries_used?.length || 0}</div>
                  <div>Source families: {research.roster_audit.source_families_crosschecked?.length || 0}</div>
                  <div>Unresolved candidates: {research.roster_audit.unresolved_candidates?.length || 0}</div>
                  {research.roster_audit.confidence && <div>Confidence: {research.roster_audit.confidence}</div>}
                  {research.unit_roster_validation?.candidate_universe_count !== undefined && <div>Candidate universe: {research.unit_roster_validation.candidate_universe_count}</div>}
                  {research.unit_roster_validation?.has_gap_hunt_matrix !== undefined && <div>Gap hunt: {research.unit_roster_validation.has_gap_hunt_matrix ? "done" : "missing"}</div>}
                </div>
              </div>
              {research.machine_discovery_buckets && (
                <div className="lg:col-span-2 rounded-lg p-3" style={{ background: "rgba(255,255,255,.04)" }}>
                  <div className="text-[10px] font-semibold uppercase tracking-wider mb-2" style={{ color: "var(--text-tertiary)" }}>Machine discovery buckets</div>
                  <div className="grid grid-cols-2 md:grid-cols-5 gap-2">
                    {Object.entries(research.machine_discovery_buckets).map(([bucket, items]: [string, any]) => (
                      <div key={bucket} className="rounded-md px-2 py-2" style={{ background: "rgba(255,255,255,.04)" }}>
                        <div className="text-[10px] uppercase tracking-wide" style={{ color: "var(--text-tertiary)" }}>{bucket.replace(/_/g, " ")}</div>
                        <div className="text-lg font-semibold" style={{ color: "var(--text-primary)" }}>{Array.isArray(items) ? items.length : 0}</div>
                      </div>
                    ))}
                  </div>
                </div>
              )}
              {research.operator_decision_points?.length > 0 && (
                <div className="lg:col-span-2 rounded-lg p-3" style={{ background: "rgba(255,120,73,.08)", border: "1px solid rgba(255,120,73,.18)" }}>
                  <div className="text-[10px] font-semibold uppercase tracking-wider mb-2" style={{ color: "var(--orange)" }}>Operator decision points</div>
                  <div className="space-y-2">
                    {research.operator_decision_points.map((point: any, i: number) => (
                      <div key={i} className="text-xs" style={{ color: "var(--text-secondary)" }}>
                        <span style={{ color: "var(--text-primary)" }}>{point.question || point.name || `Decision ${i + 1}`}</span>
                        {point.default_recommendation && <span> — default: {point.default_recommendation}</span>}
                        {point.reason && <div style={{ color: "var(--text-tertiary)" }}>{point.reason}</div>}
                      </div>
                    ))}
                  </div>
                </div>
              )}
              {research.gap_hunt_matrix?.length > 0 && (
                <div className="lg:col-span-2 rounded-lg p-3" style={{ background: "rgba(255,255,255,.04)" }}>
                  <div className="text-[10px] font-semibold uppercase tracking-wider mb-2" style={{ color: "var(--text-tertiary)" }}>Adversarial gap hunt</div>
                  <div className="space-y-2 max-h-48 overflow-auto pr-1">
                    {research.gap_hunt_matrix.map((item: any, i: number) => (
                      <div key={i} className="text-xs" style={{ color: "var(--text-secondary)" }}>
                        <span style={{ color: "var(--text-primary)" }}>{item.candidate || item.name || `Candidate ${i + 1}`}</span>
                        {item.final_placement && <span> — {item.final_placement}</span>}
                        {item.discovery_path && <div style={{ color: "var(--text-tertiary)" }}>Found by: {item.discovery_path}</div>}
                        {item.reason && <div style={{ color: "var(--text-tertiary)" }}>{item.reason}</div>}
                      </div>
                    ))}
                  </div>
                </div>
              )}
              {research.roster_audit.search_queries_used?.length > 0 && (
                <div className="lg:col-span-2 rounded-lg p-3" style={{ background: "rgba(255,255,255,.04)" }}>
                  <div className="text-[10px] font-semibold uppercase tracking-wider mb-2" style={{ color: "var(--text-tertiary)" }}>Roster-discovery searches</div>
                  <div className="flex flex-wrap gap-1.5">
                    {research.roster_audit.search_queries_used.map((q: string, i: number) => (
                      <span key={`${q}-${i}`} className="px-2 py-1 rounded-md text-[11px]" style={{ background: "rgba(255,255,255,.06)", color: "var(--text-secondary)" }}>{q}</span>
                    ))}
                  </div>
                </div>
              )}
            </div>
          )}
          {research.unit_roster.length > 0 && (
            <div>
              <div className="text-[10px] font-semibold uppercase tracking-wider mb-2" style={{ color: "var(--text-tertiary)" }}>Locked roster</div>
              <div className="grid grid-cols-1 md:grid-cols-2 gap-1.5 max-h-56 overflow-auto pr-1">
                {research.unit_roster.map((item: any, i: number) => {
                  const label = machineLabel(item);
                  return <div key={i} className="text-xs px-2 py-1.5 rounded-md" style={{ background: "rgba(255,255,255,.04)", color: "var(--text-secondary)" }}>{i + 1}. {label}</div>;
                })}
              </div>
            </div>
          )}
        </GlassCard>
      )}

      {research.unit_roster.length > 0 && research.unit_roster_validation?.passed && (
        <GlassCard className="p-5" style={{ borderLeftWidth: 3, borderLeftColor: fullMachineResearchPassed ? "var(--green)" : "var(--turquoise)" }}>
          <div className="flex flex-col gap-4 sm:flex-row sm:items-start sm:justify-between">
            <div className="min-w-0 flex-1">
              <div className="flex items-center gap-2 mb-1">
                <FileText size={15} style={{ color: "var(--turquoise)" }} />
                <h3 className="text-[10px] font-semibold uppercase tracking-wider" style={{ color: "var(--text-tertiary)" }}>Step 2 · Machine research cards</h3>
              </div>
              <p className="text-sm" style={{ color: "var(--text-secondary)" }}>
                {verifiedMachineResearchCount}/{research.unit_roster.length} verified machines researched. Each selected-machine card is saved with a raw source package before the next machine begins.
              </p>
              <div className="mt-3 h-2 overflow-hidden rounded-full" style={{ background: "rgba(255,255,255,.08)" }}>
                <div className="h-full rounded-full transition-all" style={{ width: `${Math.min(100, (verifiedMachineResearchCount / research.unit_roster.length) * 100)}%`, background: fullMachineResearchPassed ? "var(--green)" : "var(--turquoise)" }} />
              </div>
              <div className="mt-4 flex flex-col gap-2 sm:flex-row">
                <select
                  value={selectedMachine || machineLabel(research.unit_roster[0]) || ""}
                  onChange={(e) => {
                    setSelectedMachine(e.target.value);
                    setLocalMachinePreview(null);
                  }}
                  className="flex-1 rounded-lg px-3 py-2 text-sm"
                  style={{ background: "var(--bg-elevated)", color: "var(--text-primary)", border: "1px solid rgba(255,255,255,.12)" }}
                >
                  {research.unit_roster.map((item: any, i: number) => {
                    const label = machineLabel(item);
                    return <option key={`${label}-${i}`} value={label}>{i + 1}. {label}</option>;
                  })}
                </select>
                <ActionButton
                  variant="outline"
                  icon={singleMachineRunning ? Loader2 : RefreshCw}
                  onClick={handleOneMachineResearch}
                  disabled={singleMachineRunning || isResearching || taskRunning}
                >
                  {singleMachineRunning ? "Researching..." : "Research selected"}
                </ActionButton>
                <ActionButton
                  variant="filled"
                  icon={singlePreviewRunning ? Loader2 : ShieldCheck}
                  onClick={handleOneMachinePreview}
                  disabled={singlePreviewRunning || isResearching || taskRunning || !selectedResearchReady}
                >
                  {singlePreviewRunning ? "Previewing..." : selectedMachinePreview ? "Preview selected" : "Script preview"}
                </ActionButton>
              </div>
              <div className="mt-2 inline-flex items-center gap-2 rounded-md px-2 py-1 text-[10px] font-semibold uppercase tracking-wider" style={{ background: selectedResearchReady ? "rgba(0,230,138,.1)" : "rgba(255,120,73,.1)", color: selectedResearchReady ? "var(--green)" : "var(--orange)", border: `1px solid ${selectedResearchReady ? "rgba(0,230,138,.2)" : "rgba(255,120,73,.22)"}` }}>
                <ShieldCheck size={12} />
                {selectedResearchStatusMessage}
              </div>
              {selectedSourcePackage && (
                <div className="mt-2 flex flex-wrap gap-1.5">
                  {selectedSourceCoverageRows.map((row) => (
                    <span
                      key={row.slot}
                      className="inline-flex max-w-full items-center gap-1.5 rounded-md px-2 py-1 text-[10px] font-semibold uppercase tracking-wider"
                      style={{
                        background: row.covered ? "rgba(0,230,138,.08)" : "rgba(255,120,73,.08)",
                        color: row.covered ? "var(--green)" : "var(--orange)",
                        border: `1px solid ${row.covered ? "rgba(0,230,138,.18)" : "rgba(255,120,73,.2)"}`,
                      }}
                      title={row.evidenceIds.join(", ") || "Missing"}
                    >
                      <span>{row.label}</span>
                      <span className="font-mono normal-case tracking-normal" style={{ color: "var(--text-tertiary)" }}>
                        {row.evidenceIds.slice(0, 3).join(", ") || "missing"}
                      </span>
                    </span>
                  ))}
                </div>
              )}
              {selectedSourcePackage && (
                <details className="mt-3 rounded-md" style={{ background: "rgba(0,0,0,.14)", border: "1px solid rgba(255,255,255,.08)" }}>
                  <summary className="cursor-pointer px-3 py-2 text-[10px] font-semibold uppercase tracking-wider" style={{ color: "var(--text-tertiary)" }}>
                    Raw source package excerpts
                  </summary>
                  <div className="space-y-2 px-3 pb-3">
                    {selectedRawSourceExcerpts.map((candidate: any, excerptIndex: number) => {
                      const hints = sourceSlotHintsForCandidate(candidate);
                      const tier = sourceTierNumber(candidate);
                      return (
                        <div key={`${candidate?.excerpt_id || candidate?.locator || "excerpt"}-${excerptIndex}`} className="rounded px-2 py-2" style={{ background: "rgba(255,255,255,.035)", border: "1px solid rgba(255,255,255,.06)" }}>
                          <p className="truncate text-[10px]" style={{ color: "var(--text-tertiary)" }}>
                            {[candidate?.excerpt_id || candidate?.locator, tier ? `Tier ${tier}` : "", candidate?.source_capture_method, hints.length ? `hints ${hints.join(", ")}` : "", candidate?.source_title].filter(Boolean).join(" · ")}
                          </p>
                          <p className="mt-1 text-[11px] leading-4" style={{ color: "var(--text-secondary)" }}>{candidate?.text}</p>
                        </div>
                      );
                    })}
                    {selectedRawSourceExcerpts.length === 0 && (
                      <p className="text-xs" style={{ color: "var(--text-tertiary)" }}>No matching raw excerpts saved for the selected machine.</p>
                    )}
                  </div>
                </details>
              )}
            </div>
          </div>

          {research.unit_research_hold_validation?.warnings?.length > 0 && (
            <ul className="mt-3 space-y-1">
              {research.unit_research_hold_validation.warnings.map((warning: string, i: number) => (
                <li key={i} className="text-xs" style={{ color: "var(--orange)" }}>• {warning}</li>
              ))}
            </ul>
          )}

          {selectedResearchCard && (
            <div
              className="mt-4 rounded-lg p-4"
              style={{
                background: "rgba(0,0,0,.18)",
                border: `1px solid ${selectedMachinePreviewPassed ? "rgba(74,222,128,.28)" : "rgba(255,255,255,.09)"}`,
              }}
            >
              <div className="mb-3 flex flex-col gap-2 sm:flex-row sm:items-start sm:justify-between">
                <div>
                  <div className="flex items-center gap-2">
                    <ShieldCheck size={14} style={{ color: selectedMachinePreviewPassed ? "var(--green)" : "var(--turquoise)" }} />
                    <h4 className="text-[10px] font-semibold uppercase tracking-wider" style={{ color: "var(--text-tertiary)" }}>
                      Single-machine script preview
                    </h4>
                  </div>
                  <p className="mt-1 text-sm" style={{ color: "var(--text-primary)" }}>{selectedMachineLabel}</p>
                </div>
                <div className="flex flex-wrap gap-2">
                  <span className="rounded-md px-2 py-1 text-[10px] font-semibold uppercase tracking-wider" style={{ background: selectedMachinePreviewPassed ? "rgba(0,230,138,.12)" : "rgba(255,255,255,.06)", color: selectedMachinePreviewPassed ? "var(--green)" : "var(--text-tertiary)" }}>
                    {selectedMachinePreview ? (selectedMachinePreviewPassed ? "Passed" : "Needs review") : "Not previewed"}
                  </span>
                  {selectedMachinePreview?.word_count !== undefined && (
                    <span className="rounded-md px-2 py-1 text-[10px] font-mono" style={{ background: "rgba(255,255,255,.06)", color: "var(--text-tertiary)" }}>
                      {selectedMachinePreview.word_count} words
                    </span>
                  )}
                  {selectedMachinePreview?.research_source && (
                    <span className="rounded-md px-2 py-1 text-[10px] font-mono" style={{ background: "rgba(255,255,255,.06)", color: "var(--text-tertiary)" }}>
                      {selectedMachinePreview.research_source}
                    </span>
                  )}
                </div>
              </div>

              {selectedMachinePreview ? (
                <div className="space-y-4">
                  {selectedMachinePreview.claim_bundle?.editorial_thesis && (
                    <div className="rounded-md px-3 py-2" style={{ background: "rgba(79,214,198,.07)", border: "1px solid rgba(79,214,198,.18)" }}>
                      <div className="text-[10px] font-semibold uppercase tracking-wider" style={{ color: "var(--turquoise)" }}>Editorial thesis</div>
                      <p className="mt-1 text-sm" style={{ color: "var(--text-primary)" }}>
                        {selectedMachinePreview.claim_bundle.editorial_thesis}
                      </p>
                    </div>
                  )}
                  {(selectedMachinePreview.onscreen_label || selectedMachinePreview.claim_bundle?.onscreen_label) && (
                    <div className="rounded-md px-3 py-2" style={{ background: "rgba(255,255,255,.035)", border: "1px solid rgba(255,255,255,.08)" }}>
                      <div className="text-[10px] font-semibold uppercase tracking-wider" style={{ color: "var(--text-tertiary)" }}>On-screen label</div>
                      <p className="mt-1 text-sm" style={{ color: "var(--text-primary)" }}>
                        {selectedMachinePreview.onscreen_label || selectedMachinePreview.claim_bundle?.onscreen_label}
                      </p>
                    </div>
                  )}
                  {selectedMachinePreview.paragraph ? (
                    <p className="text-sm leading-6" style={{ color: "var(--text-primary)" }}>{selectedMachinePreview.paragraph}</p>
                  ) : (
                    <div className="rounded-md px-3 py-2 text-sm" style={{ background: "rgba(255,120,73,.08)", color: "var(--orange)", border: "1px solid rgba(255,120,73,.18)" }}>
                      Preview stopped before a paragraph was generated.
                    </div>
                  )}
                  {!selectedMachinePreview.quality_audit?.checks?.length && (
                    <div className="rounded-md px-3 py-2 text-xs" style={{ background: "rgba(255,120,73,.08)", color: "var(--orange)", border: "1px solid rgba(255,120,73,.18)" }}>
                      Legacy preview missing Anton audit. Regenerate this machine before accepting it.
                    </div>
                  )}

                  {selectedPreviewFormulaRows.length > 0 && (
                    <div className="space-y-2">
                      <div className="flex items-center gap-2 text-[10px] font-semibold uppercase tracking-wider" style={{ color: "var(--text-tertiary)" }}>
                        <ShieldCheck size={12} />
                        Sentence assembly
                      </div>
                      {selectedPreviewFormulaRows.map((row, index) => (
                        <div key={`selected-formula-${index}`} className="rounded-md px-3 py-2" style={{ background: "rgba(255,255,255,.03)", border: "1px solid rgba(255,255,255,.08)" }}>
                          <span className="mb-1 inline-block rounded px-1.5 py-0.5 text-[10px] font-mono uppercase" style={{ color: index < 4 ? "var(--turquoise)" : "var(--orange)", background: index < 4 ? "rgba(79,214,198,.1)" : "rgba(255,120,73,.1)" }}>
                            {row.label}
                          </span>
                          <p className="text-xs leading-5" style={{ color: "var(--text-secondary)" }}>{row.sentence}</p>
                          {row.evidenceRows.length > 0 && (
                            <div className="mt-2 space-y-2">
                              {row.evidenceRows.map(({ id, evidence }: { id: string; evidence?: any }) => (
                                <div key={id} className="rounded px-2 py-2" style={{ background: "rgba(0,0,0,.14)", border: "1px solid rgba(255,255,255,.06)" }}>
                                  <p className="truncate text-[10px]" style={{ color: "var(--text-tertiary)" }}>
                                    {[evidence?.source_title || id, evidence?.source_tier, evidence?.source_capture_method, Array.isArray(evidence?.source_slot_hints) && evidence.source_slot_hints.length ? `hints ${evidence.source_slot_hints.join(", ")}` : "", evidence?.source_excerpt_id || evidence?.locator, evidence?.source_excerpt_hash ? `hash ${String(evidence.source_excerpt_hash).slice(0, 8)}` : ""].filter(Boolean).join(" · ")}
                                  </p>
                                  {evidence?.source_excerpt && <p className="mt-1 text-[11px] leading-4" style={{ color: "var(--text-primary)" }}>{evidence.source_excerpt}</p>}
                                </div>
                              ))}
                            </div>
                          )}
                        </div>
                      ))}
                    </div>
                  )}

                  {!!selectedMachinePreview.quality_audit?.checks?.length && (
                    <div className="space-y-2">
                      <div className="flex items-center gap-2 text-[10px] font-semibold uppercase tracking-wider" style={{ color: selectedMachinePreview.quality_audit.passed ? "var(--green)" : "var(--orange)" }}>
                        <ShieldCheck size={12} />
                        Anton quality audit
                      </div>
                      <div className="grid gap-2 sm:grid-cols-2">
                        {selectedMachinePreview.quality_audit.checks.map((check, index) => (
                          <div key={`${check.name || "audit"}-${index}`} className="rounded-md px-3 py-2" style={{ background: check.passed ? "rgba(0,230,138,.07)" : "rgba(255,120,73,.08)", border: `1px solid ${check.passed ? "rgba(0,230,138,.16)" : "rgba(255,120,73,.2)"}` }}>
                            <div className="text-[10px] font-semibold uppercase tracking-wider" style={{ color: check.passed ? "var(--green)" : "var(--orange)" }}>{check.label || check.name}{check.advisory ? " · advisory" : ""}</div>
                            {check.detail && <p className="mt-1 text-[11px] leading-4" style={{ color: "var(--text-secondary)" }}>{check.detail}</p>}
                          </div>
                        ))}
                      </div>
                    </div>
                  )}

                  {selectedPreviewSlots.length > 0 && (
                    <div className="flex flex-wrap gap-2">
                      {selectedPreviewSlots.map((slot: any) => {
                        const evidenceCount = Array.isArray(slot?.evidence_ids) ? slot.evidence_ids.length : 0;
                        return (
                          <span key={slot.slot} className="rounded-md px-2 py-1 text-[10px] font-mono" style={{ background: slot.required ? "rgba(79,214,198,.1)" : "rgba(255,255,255,.055)", color: slot.required ? "var(--turquoise)" : "var(--text-tertiary)", border: "1px solid rgba(255,255,255,.08)" }}>
                            {slot.slot}: {evidenceCount}
                          </span>
                        );
                      })}
                    </div>
                  )}

                  {selectedPreviewClaimMap.length > 0 && (
                    <div className="space-y-2">
                      <div className="flex items-center gap-2 text-[10px] font-semibold uppercase tracking-wider" style={{ color: "var(--text-tertiary)" }}>
                        <ShieldCheck size={12} />
                        Evidence map
                      </div>
                      {selectedPreviewClaimMap.slice(0, 10).map((row: any, index: number) => {
                        const evidenceIds = Array.isArray(row.used_evidence_ids)
                          ? row.used_evidence_ids
                          : Array.isArray(row.evidence_ids) ? row.evidence_ids : [];
                        const evidenceRows = evidenceIds
                          .map((id: string) => ({ id, evidence: selectedPreviewEvidenceById[id] }))
                          .filter((item: { id: string; evidence?: any }) => item.id);
                        return (
                          <div key={`${row.slot || "slot"}-${index}`} className="rounded-md px-3 py-2" style={{ background: "rgba(255,255,255,.035)", border: "1px solid rgba(255,255,255,.08)" }}>
                            <div className="mb-1 flex flex-wrap items-center gap-2">
                              <span className="rounded px-1.5 py-0.5 text-[10px] font-mono uppercase" style={{ color: "var(--turquoise)", background: "rgba(79,214,198,.1)" }}>{row.slot || "slot"}</span>
                              <span className="text-[10px] font-mono" style={{ color: "var(--text-tertiary)" }}>{evidenceIds.join(", ")}</span>
                            </div>
                            {row.span && <p className="text-xs leading-5" style={{ color: "var(--text-secondary)" }}>{row.span}</p>}
                            {evidenceRows.length > 0 && (
                              <div className="mt-2 space-y-2">
                                {evidenceRows.map(({ id, evidence }: { id: string; evidence?: any }) => (
                                  <div key={id} className="rounded px-2 py-2" style={{ background: "rgba(0,0,0,.14)", border: "1px solid rgba(255,255,255,.06)" }}>
                                    <p className="truncate text-[10px]" style={{ color: "var(--text-tertiary)" }}>
                                      {[evidence?.source_title || id, evidence?.source_tier, evidence?.source_capture_method, Array.isArray(evidence?.source_slot_hints) && evidence.source_slot_hints.length ? `hints ${evidence.source_slot_hints.join(", ")}` : "", evidence?.source_excerpt_id || evidence?.locator, evidence?.source_excerpt_hash ? `hash ${String(evidence.source_excerpt_hash).slice(0, 8)}` : ""].filter(Boolean).join(" · ")}
                                    </p>
                                    {evidence?.claim && <p className="mt-1 text-[11px] leading-4" style={{ color: "var(--text-primary)" }}>{evidence.claim}</p>}
                                    {evidence?.source_excerpt && <p className="mt-1 text-[11px] leading-4" style={{ color: "var(--text-secondary)" }}>{evidence.source_excerpt}</p>}
                                  </div>
                                ))}
                              </div>
                            )}
                          </div>
                        );
                      })}
                    </div>
                  )}

                  {!!selectedMachinePreview.warnings?.length && (
                    <p className="text-xs" style={{ color: "var(--orange)" }}>{selectedMachinePreview.warnings.join(" · ")}</p>
                  )}
                </div>
              ) : (
                <div className="rounded-md px-3 py-2 text-sm" style={{ background: "rgba(255,255,255,.035)", color: "var(--text-secondary)", border: "1px solid rgba(255,255,255,.08)" }}>
                  Research card saved. Script preview pending.
                </div>
              )}
            </div>
          )}

          <div className="mt-4 space-y-2">
            {research.unit_roster.map((item: any, index: number) => {
              const label = machineLabel(item);
              const card = research.unit_research_cards.find((candidate: any) => cardMatchesMachine(candidate, label));
              const cardSourcePackage = sourcePackageForMachine(research.machine_raw_source_packages, label);
              const cardStatus = machineResearchCardStatus(card, label, cardSourcePackage);
              const cardReady = cardStatus.ready;
              const cardSourceReady = sourcePackageReady(cardSourcePackage, label);
              const cardVerified = cardReady && cardSourceReady;
              const cardStatusLabel = cardVerified ? "Verified" : card ? (cardReady ? "Needs source" : "Needs card data") : "Waiting";
              return (
                <details key={`${label}-${index}`} className="rounded-lg" style={{ background: "rgba(255,255,255,.04)", border: "1px solid rgba(255,255,255,.06)" }}>
                  <summary className="flex cursor-pointer list-none items-center justify-between gap-3 px-3 py-2.5 text-sm">
                    <span style={{ color: card ? "var(--text-primary)" : "var(--text-tertiary)" }}>{index + 1}. {label}</span>
                    <span className="shrink-0 text-[10px] font-semibold uppercase tracking-wider" style={{ color: cardVerified ? "var(--green)" : card ? "var(--orange)" : "var(--text-tertiary)" }}>{cardStatusLabel}</span>
                  </summary>
                  {card && (
                    <div className="space-y-3 border-t px-3 py-3" style={{ borderColor: "rgba(255,255,255,.06)" }}>
                      {card.engineering_thesis && <p className="text-sm leading-relaxed" style={{ color: "var(--text-primary)" }}>{card.engineering_thesis}</p>}
                      <div className="grid gap-3 md:grid-cols-2">
                        {card.why_this_unit_deserves_a_paragraph && <div><div className="text-[10px] uppercase tracking-wider" style={{ color: "var(--text-tertiary)" }}>Why it matters</div><p className="text-xs mt-1" style={{ color: "var(--text-secondary)" }}>{card.why_this_unit_deserves_a_paragraph}</p></div>}
                        {card.actual_outcome && <div><div className="text-[10px] uppercase tracking-wider" style={{ color: "var(--text-tertiary)" }}>What happened</div><p className="text-xs mt-1" style={{ color: "var(--text-secondary)" }}>{card.actual_outcome}</p></div>}
                        {card.design_problem && <div><div className="text-[10px] uppercase tracking-wider" style={{ color: "var(--text-tertiary)" }}>Engineering problem</div><p className="text-xs mt-1" style={{ color: "var(--text-secondary)" }}>{card.design_problem}</p></div>}
                        {card.tradeoff && <div><div className="text-[10px] uppercase tracking-wider" style={{ color: "var(--text-tertiary)" }}>Design tradeoff</div><p className="text-xs mt-1" style={{ color: "var(--text-secondary)" }}>{card.tradeoff}</p></div>}
                      </div>
                      {Array.isArray(card.source_notes) && card.source_notes.length > 0 && <div className="text-[11px] font-mono" style={{ color: "var(--text-tertiary)" }}>Sources: {card.source_notes.join(" · ")}</div>}
                      {Array.isArray(card.evidence_segments) && card.evidence_segments.length > 0 && (
                        <div className="space-y-2">
                          <div className="flex items-center gap-2 text-[10px] font-semibold uppercase tracking-wider" style={{ color: "var(--text-tertiary)" }}>
                            <ShieldCheck size={12} />
                            Exact evidence segments
                          </div>
                          <div className="space-y-2">
                            {card.evidence_segments.slice(0, 12).map((segment: any, segmentIndex: number) => {
                              const sourceTier = sourceTierForEvidence(segment, cardSourcePackage);
                              const sourceCaptureMethod = sourceCaptureMethodForEvidence(segment, cardSourcePackage);
                              const sourceSlotHints = sourceSlotHintsForEvidence(segment, cardSourcePackage);
                              return (
                                <div key={`${segment.evidence_id || segment.kind || "evidence"}-${segmentIndex}`} className="rounded-md px-3 py-2" style={{ background: "rgba(255,255,255,.035)", border: "1px solid rgba(255,255,255,.08)" }}>
                                  <div className="mb-1 flex flex-wrap items-center gap-2">
                                    <span className="rounded px-1.5 py-0.5 text-[10px] font-mono uppercase" style={{ color: "var(--turquoise)", background: "rgba(79,214,198,.1)" }}>{segment.kind || "slot"}</span>
                                    {segment.evidence_id && <span className="text-[10px] font-mono" style={{ color: "var(--text-tertiary)" }}>{segment.evidence_id}</span>}
                                    {sourceTier && (
                                      <span className="rounded px-1.5 py-0.5 text-[10px] font-mono" style={{ color: sourceTier.tier >= 4 ? "var(--orange)" : "var(--green)", background: sourceTier.tier >= 4 ? "rgba(255,166,77,.12)" : "rgba(0,230,138,.1)" }}>
                                        Tier {sourceTier.tier}
                                      </span>
                                    )}
                                    {segment.confidence && <span className="text-[10px]" style={{ color: "var(--text-tertiary)" }}>{segment.confidence}</span>}
                                    {sourceCaptureMethod && <span className="text-[10px] font-mono" style={{ color: "var(--text-tertiary)" }}>{sourceCaptureMethod}</span>}
                                    {sourceSlotHints.length > 0 && <span className="text-[10px] font-mono" style={{ color: "var(--text-tertiary)" }}>hints {sourceSlotHints.join(", ")}</span>}
                                  </div>
                                  {segment.claim && <p className="text-xs leading-5" style={{ color: "var(--text-primary)" }}>{segment.claim}</p>}
                                  {segment.source_excerpt && <p className="mt-1 text-xs leading-5" style={{ color: "var(--text-secondary)" }}>{segment.source_excerpt}</p>}
                                  {(segment.source_title || sourceTier || segment.source_url || segment.locator) && (
                                    <p className="mt-1 truncate text-[10px]" style={{ color: "var(--text-tertiary)" }}>
                                      {[segment.source_title, sourceTier?.label, segment.source_url, segment.locator].filter(Boolean).join(" · ")}
                                    </p>
                                  )}
                                </div>
                              );
                            })}
                          </div>
                        </div>
                      )}
                    </div>
                  )}
                </details>
              );
            })}
          </div>
        </GlassCard>
      )}

      {/* Thesis — full width with accent border */}
      {research.thesis && (
        <GlassCard className="p-5" style={{ borderLeftWidth: 3, borderLeftColor: "var(--turquoise)" }}>
          <h3 className="text-[10px] font-semibold uppercase tracking-wider mb-3" style={{ color: "var(--text-tertiary)" }}>Thesis</h3>
          <EditableText text={research.thesis} />
        </GlassCard>
      )}

      {/* Executive Hook — full width with accent border */}
      {research.executive_hook && (
        <GlassCard className="p-5" style={{ borderLeftWidth: 3, borderLeftColor: "var(--orange)" }}>
          <h3 className="text-[10px] font-semibold uppercase tracking-wider mb-3" style={{ color: "var(--text-tertiary)" }}>Executive Hook</h3>
          <EditableText text={research.executive_hook} />
        </GlassCard>
      )}

      {/* Two-column grid for main content */}
      <div className="grid grid-cols-1 lg:grid-cols-2 gap-4">
        {/* Fact Sheet — bullet list */}
        {research.fact_sheet && (
          <GlassCard className="p-5" style={{ borderLeftWidth: 3, borderLeftColor: "var(--turquoise)" }}>
            <h3 className="text-[10px] font-semibold uppercase tracking-wider mb-3" style={{ color: "var(--text-tertiary)" }}>Fact Sheet</h3>
            <BulletList text={research.fact_sheet} />
          </GlassCard>
        )}

        {/* Historical Parallels — bullet list */}
        {research.historical_parallels && (
          <GlassCard className="p-5" style={{ borderLeftWidth: 3, borderLeftColor: "var(--turquoise)" }}>
            <h3 className="text-[10px] font-semibold uppercase tracking-wider mb-3" style={{ color: "var(--text-tertiary)" }}>Historical Parallels</h3>
            <BulletList text={research.historical_parallels} />
          </GlassCard>
        )}

        {/* Character Dossier */}
        {research.character_dossier && (
          <GlassCard className="p-5" style={{ borderLeftWidth: 3, borderLeftColor: "var(--turquoise)" }}>
            <h3 className="text-[10px] font-semibold uppercase tracking-wider mb-3" style={{ color: "var(--text-tertiary)" }}>Character Dossier</h3>
            <BulletList text={research.character_dossier} />
          </GlassCard>
        )}

        {/* Visual Seeds */}
        {research.visual_seeds && (
          <GlassCard className="p-5" style={{ borderLeftWidth: 3, borderLeftColor: "var(--turquoise)" }}>
            <h3 className="text-[10px] font-semibold uppercase tracking-wider mb-3" style={{ color: "var(--text-tertiary)" }}>Visual Seeds</h3>
            <BulletList text={research.visual_seeds} />
          </GlassCard>
        )}
      </div>

      {/* Narrative Arc — full width */}
      {research.narrative_arc && (
        <GlassCard className="p-5 lg:col-span-2" style={{ borderLeftWidth: 3, borderLeftColor: "var(--turquoise)" }}>
          <h3 className="text-[10px] font-semibold uppercase tracking-wider mb-3" style={{ color: "var(--text-tertiary)" }}>Narrative Arc</h3>
          <EditableText text={research.narrative_arc} />
        </GlassCard>
      )}

      {/* Themes + Psychological Angles — tag chips */}
      <div className="grid grid-cols-1 lg:grid-cols-2 gap-4">
        {research.themes && (
          <GlassCard className="p-5" style={{ borderLeftWidth: 3, borderLeftColor: "var(--turquoise)" }}>
            <h3 className="text-[10px] font-semibold uppercase tracking-wider mb-3" style={{ color: "var(--text-tertiary)" }}>Themes</h3>
            <TagChips text={research.themes} />
          </GlassCard>
        )}
        {research.psychological_angles && (
          <GlassCard className="p-5" style={{ borderLeftWidth: 3, borderLeftColor: "var(--turquoise)" }}>
            <h3 className="text-[10px] font-semibold uppercase tracking-wider mb-3" style={{ color: "var(--text-tertiary)" }}>Psychological Angles</h3>
            <TagChips text={research.psychological_angles} />
          </GlassCard>
        )}
      </div>

      {/* Collapsible sections */}
      {research.framework_analysis && (
        <CollapsibleSection label="Framework Analysis" borderColor="var(--turquoise)">
          <EditableText text={research.framework_analysis} />
        </CollapsibleSection>
      )}

      {research.counter_arguments && (
        <CollapsibleSection label="Counter Arguments" borderColor="var(--turquoise)">
          <EditableText text={research.counter_arguments} />
        </CollapsibleSection>
      )}

      {research.source_bibliography && (
        <CollapsibleSection label="Sources" borderColor="var(--turquoise)">
          <SourceList text={research.source_bibliography} />
        </CollapsibleSection>
      )}

      {/* Actions */}
      {approveError && (
        <div className="text-sm text-center py-2 px-4 rounded-lg" style={{ color: "var(--orange)", background: "rgba(255, 120, 73, 0.1)" }}>
          Failed to approve: {approveError}
        </div>
      )}
      <div className="flex gap-3 justify-end flex-wrap">
        {!approved && (
          <>
            <button
              className="inline-flex items-center justify-center gap-2 px-5 py-2.5 rounded-xl text-sm font-semibold font-body transition-all hover:brightness-110 active:scale-[0.98] disabled:opacity-50"
              style={{ background: "rgba(255, 120, 73, 0.15)", color: "var(--orange)", border: "1px solid var(--orange)" }}
              onClick={handleReResearch}
              disabled={isResearching || taskRunning}
            >
              {(isResearching || taskRunning) ? <Loader2 size={16} className="animate-spin" /> : <RefreshCw size={16} />}
              {taskRunning ? (taskMessage || "Researching...") : isResearching ? "Starting..." : "Regenerate Research"}
            </button>
            <button
              className="inline-flex items-center justify-center gap-2 px-5 py-2.5 rounded-xl text-sm font-semibold font-body transition-all hover:brightness-110 active:scale-[0.98]"
              style={{ background: "transparent", color: "var(--text-secondary)", border: "1px solid var(--border)" }}
              onClick={() => setShowFeedback(true)}
            >
              <FileText size={16} /> Request Changes
            </button>
            <button
              className="inline-flex items-center justify-center gap-2 px-5 py-2.5 rounded-xl text-sm font-semibold font-body transition-all hover:brightness-110 active:scale-[0.98] disabled:opacity-50"
              style={{ background: "var(--green)", color: "var(--bg-void)" }}
              onClick={handleApproveResearch}
              disabled={isApproving}
            >
              {isApproving ? <Loader2 size={16} className="animate-spin" /> : <Check size={16} />}
              {isApproving ? "Advancing..." : "Approve Research"}
            </button>
          </>
        )}
        {approved && (
          <div className="inline-flex items-center gap-2 px-5 py-2.5 rounded-xl text-sm font-semibold" style={{ color: "var(--green)" }}>
            <Check size={16} /> Research Approved
          </div>
        )}
      </div>

      {/* Feedback Modal */}
      {showFeedback && (
        <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/60 backdrop-blur-sm" onClick={() => setShowFeedback(false)}>
          <div className="w-full max-w-md rounded-xl p-6 space-y-4" style={{ background: "var(--bg-deep)", border: "1px solid var(--border)" }} onClick={(e) => e.stopPropagation()}>
            <h3 className="text-base font-semibold" style={{ color: "var(--text-primary)" }}>Request Changes</h3>
            <textarea
              value={feedbackText}
              onChange={(e) => setFeedbackText(e.target.value)}
              placeholder="What should be changed?"
              rows={4}
              className="w-full px-3 py-2 rounded-lg text-sm outline-none resize-none"
              style={{ background: "var(--bg-elevated)", color: "var(--text-primary)", border: "1px solid var(--border)" }}
              autoFocus
            />
            <div className="flex gap-2 justify-end">
              <button onClick={() => setShowFeedback(false)} className="px-4 py-2 rounded-lg text-sm" style={{ color: "var(--text-secondary)" }} disabled={feedbackSaving}>Cancel</button>
              <button
                onClick={async () => {
                  setFeedbackSaving(true);
                  try {
                    await updateVideo(video.id, { revision_notes: feedbackText });
                    setShowFeedback(false);
                    setFeedbackSaved(true);
                    setTimeout(() => setFeedbackSaved(false), 3000);
                  } catch (err) {
                    toast.error(`Failed to save: ${(err as Error).message}`);
                  } finally {
                    setFeedbackSaving(false);
                  }
                }}
                className="px-4 py-2 rounded-lg text-sm font-semibold disabled:opacity-50"
                style={{ background: "var(--turquoise)", color: "var(--bg-void)" }}
                disabled={feedbackSaving || !feedbackText.trim()}
              >
                {feedbackSaving ? "Saving..." : "Save Feedback"}
              </button>
            </div>
          </div>
        </div>
      )}

      {feedbackSaved && (
        <div className="text-sm text-center py-2" style={{ color: "var(--green)" }}>Feedback saved</div>
      )}
    </div>
  );
}
