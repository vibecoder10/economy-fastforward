"use client";

import { useState, useMemo, useEffect, useRef, useCallback } from "react";
import { motion, AnimatePresence } from "framer-motion";
import {
  ChevronDown, ChevronRight, Merge, Trash2, Plus, Volume2,
  Library, Wand2, Play, Square, Layers, Mic, Pencil, Loader2,
  CheckCircle, Clock, AlertCircle, Save, ShieldCheck,
  Cloud, CloudUpload, RefreshCw, ExternalLink,
} from "lucide-react";
import { useQuery, useQueryClient, useMutation } from "@tanstack/react-query";
import {
  getVideoScript, getVideoAssets, advanceVideo, rejectVideo,
  runPipelineStage, updateSceneText, updateVideo, clearStaleTask,
  runVoiceForScene, runSplit, getSceneSegments, updateSceneSegments,
  getDefaultScriptPrompt, rewriteSceneText,
  getDriveScriptStatus, pushScriptToDrive, syncScriptFromDrive,
  setApiKey, getApiKeyStatus, getDialogueMap, getAudioToken,
  getPipelineTaskStatus, checkMachineScriptPreviewReadiness, runMachineScriptPreview,
} from "@/lib/api";
import { API_URL } from "@/lib/env";
import type { ScriptScene as ApiScriptScene, Asset, Segment, MachineScriptPreview } from "@/lib/api";
import { useTaskPoller } from "@/hooks/use-task-poller";
import { useToast } from "@/components/ui/toast";
import { GlassCard } from "@/components/ui/GlassCard";
import { SegmentBadge } from "@/components/ui/SegmentBadge";
import { ActionButton } from "@/components/ui/ActionButton";
import { MiniWaveform } from "@/components/ui/MiniWaveform";
import { ProgressRing } from "@/components/ui/ProgressRing";
import { SystemPromptEditor } from "@/components/ui/SystemPromptEditor";

// ---------------------------------------------------------------------------
// Types
// ---------------------------------------------------------------------------

interface ScriptVoiceTabProps {
  video: any;
  onAdvanced?: () => void;
}

interface SentenceState {
  text: string;
  sfxMode: "none" | "library" | "elevenlabs" | "custom";
  sfxLibraryValue: string;
  sfxCustomPrompt: string;
  durationSeconds: number | null;
  cumulativeStart: number | null;
  imagePrompt: string | null;
  imageIndex: number | null;
}

interface SceneState {
  id: string;
  sceneNumber: number;
  actNumber: number;
  narrationText: string;
  displayText: string; // narrationText with style directives stripped
  visualStyle: string;
  composition: string;
  sources?: string[];
  imageGenerated?: boolean;
  voiceOverUrl: string | null;
  voiceStatus: string | null;
  scriptStatus: string | null;
  tone: string | null;
  sentences: SentenceState[];
}

// ---------------------------------------------------------------------------
// Constants
// ---------------------------------------------------------------------------

const SFX_LIBRARY = [
  { value: "", label: "-- No SFX --" },
  { value: "ambient-tension", label: "Ambient Tension" },
  { value: "war-drums", label: "War Drums (distant)" },
  { value: "paper-shuffle", label: "Paper Shuffle" },
  { value: "door-close", label: "Heavy Door Close" },
  { value: "crowd-murmur", label: "Crowd Murmur" },
  { value: "typing", label: "Keyboard Typing" },
  { value: "explosion-distant", label: "Distant Explosion" },
  { value: "clock-ticking", label: "Clock Ticking" },
  { value: "heartbeat", label: "Heartbeat" },
  { value: "wind", label: "Desert Wind" },
  { value: "helicopter", label: "Helicopter Flyover" },
  { value: "news-broadcast", label: "News Broadcast Chatter" },
];

/** Regex to match visual style directive lines (e.g. "dossier wide", "schema medium") */
const STYLE_DIRECTIVE_RE =
  /^(dossier|schema|echo|holographic hud|cinematic illustration|clay mannequin)\s*(wide|medium|closeup|environmental|portrait|overhead|low_angle)?\s*$/im;

// ---------------------------------------------------------------------------
// Helpers
// ---------------------------------------------------------------------------

function splitSentences(text: string): string[] {
  return text
    .split(/(?<=[.!?\u2014])\s+/)
    .map((s) => s.trim())
    .filter(Boolean);
}

/** Strip visual style directive lines from scene text for display. */
function stripStyleDirectives(text: string): string {
  return text
    .split("\n")
    .filter((line) => !STYLE_DIRECTIVE_RE.test(line.trim()))
    .join("\n")
    .trim();
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
  const blockingAuditChecksPassed = auditChecks.every((check: any) => check?.passed || check?.advisory);
  const completeFormulaSentences = formulaSentences.length === 5
    && formulaSentences.every((sentence: any) => String(sentence || "").trim().length > 0);
  return Boolean(
    preview?.passed === true
    && preview?.quality_audit?.passed === true
    && auditChecks.length > 0
    && blockingAuditChecksPassed
    && completeFormulaSentences
  );
}

function machinePreviewReviewMessages(preview: any): string[] {
  if (!preview) return [];
  const warningRows = Array.isArray(preview?.warnings)
    ? preview.warnings.map((warning: any) => String(warning || "").trim()).filter(Boolean)
    : [];
  const auditSummary = preview?.quality_audit?.passed === false && preview?.quality_audit?.summary
    ? [String(preview.quality_audit.summary)]
    : [];
  const failedAuditRows = Array.isArray(preview?.quality_audit?.checks)
    ? preview.quality_audit.checks
        .filter((check: any) => check && check.passed === false && !check.advisory)
        .map((check: any) => [check.label || check.name, check.detail].filter(Boolean).join(": "))
        .map((message: any) => String(message || "").trim())
        .filter(Boolean)
    : [];
  return Array.from(new Set([...warningRows, ...auditSummary, ...failedAuditRows])).slice(0, 6);
}

function previewErrorArtifact(
  machine: string,
  message: string,
  warnings?: string[],
  scene = 0,
  researchSource = "preview_error",
  checkName = "preview_error",
  checkLabel = "Preview error"
): MachineScriptPreview {
  const reviewMessages = (Array.isArray(warnings) && warnings.length ? warnings : [message])
    .map((warning) => String(warning || "").trim())
    .filter(Boolean);
  const summary = String(message || reviewMessages[0] || "Preview stopped before a paragraph was generated.").trim();
  return {
    machine,
    scene,
    paragraph: "",
    word_count: 0,
    passed: false,
    warnings: reviewMessages.length ? reviewMessages : [summary],
    research_source: researchSource,
    claim_bundle: { editorial_thesis: "", formula_sentences: [], claim_map: [] },
    quality_audit: {
      passed: false,
      summary,
      checks: [{
        name: checkName,
        label: checkLabel,
        passed: false,
        detail: summary,
      }],
    },
  };
}

function cardMatchesMachine(card: any, machine: string): boolean {
  return machineLabelMatches(cardLabel(card), machine);
}

function previewForMachine(previews: any, machine: string): MachineScriptPreview | null {
  if (!previews || typeof previews !== "object" || Array.isArray(previews)) return null;
  if (previews[machine]) return previews[machine] as MachineScriptPreview;
  const match = Object.entries(previews).find(([key, preview]: [string, any]) => (
    machineLabelMatches(key, machine) || previewMatchesMachine(preview, machine)
  ));
  return match ? match[1] as MachineScriptPreview : null;
}

function sourcePackageForMachine(packages: any, machine: string): any | null {
  if (!packages || typeof packages !== "object") return null;
  const key = normalizedUnitCode(machine);
  if (!Array.isArray(packages) && key && packages[key]) return packages[key];
  const rows = Array.isArray(packages) ? packages : Object.entries(packages).map(([rawKey, value]) => ({ rawKey, value }));
  for (const row of rows) {
    const rawKey = Array.isArray(packages) ? "" : String(row.rawKey || "");
    const candidate = Array.isArray(packages) ? row : row.value;
    if (!candidate || typeof candidate !== "object") continue;
    const machineName = String(candidate.machine || "");
    const machineKey = String(candidate.machine_key || "");
    if (
      normalizedUnitCode(rawKey) === key
      || normalizedUnitCode(machineName) === key
      || normalizedUnitCode(machineKey) === key
    ) {
      return candidate;
    }
  }
  return null;
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

function sourceVariantSelectionForEvidence(segment: any, sourcePackage: any): any | null {
  const match = sourceCandidateForEvidence(segment, sourcePackage);
  return match?.source_variant_selection || segment?.source_variant_selection || null;
}

function sourceVariantSelectionLabel(selection: any): string {
  if (!selection || typeof selection !== "object") return "";
  const variants = Array.isArray(selection?.evaluated_variants) ? selection.evaluated_variants : [];
  const selectedMethod = String(selection?.selected_capture_method || selection?.selected_variant?.source_capture_method || "").trim();
  const selectedVariant = selection?.selected_variant || variants.find((variant: any) => String(variant?.source_capture_method || "").trim() === selectedMethod);
  const compared = variants
    .map((variant: any) => String(variant?.source_capture_method || "").trim())
    .filter(Boolean);
  const score = selectedVariant && Number.isFinite(Number(selectedVariant?.covered_slot_count))
    ? `${Number(selectedVariant.covered_slot_count)} slots/${Number(selectedVariant?.distinct_slot_excerpt_count || 0)} distinct`
    : "";
  return [
    selectedMethod ? `selected ${selectedMethod}` : "",
    score,
    compared.length > 1 ? `compared ${compared.join("/")}` : "",
  ].filter(Boolean).join(" · ");
}

function canonicalAntonSourceSlot(slot: unknown): string {
  const normalized = String(slot || "").trim().toLowerCase();
  const slotMap: Record<string, string[]> = {
    original_problem: ["original_problem", "design_problem", "engineering_intent", "design_requirement", "doctrinal_problem", "identity_origin", "design_intent"],
    engineering_decision: ["engineering_decision", "engineering_response", "design_response", "scale_specs", "validated_concept"],
    tradeoff: ["tradeoff", "tradeoff_or_limit", "limitation", "failure_mode"],
    reality: ["reality", "actual_reality", "actual_outcome", "service_reality", "operational_reality", "combat_reality", "test_result", "build_reality", "production_reality", "prototype_reality", "historical_meaning", "legacy"],
  };
  return Object.entries(slotMap).find(([, aliases]) => aliases.includes(normalized))?.[0] || "";
}

function canonicalAntonSourceSlotHints(rawHints: unknown[]): string[] {
  const seen = new Set<string>();
  return rawHints.reduce((rows: string[], rawHint: unknown) => {
    const slot = canonicalAntonSourceSlot(rawHint);
    if (slot && !seen.has(slot)) {
      seen.add(slot);
      rows.push(slot);
    }
    return rows;
  }, []);
}

function sourceSlotHintsForEvidence(segment: any, sourcePackage: any): string[] {
  const match = sourceCandidateForEvidence(segment, sourcePackage);
  const rawHints = Array.isArray(match?.anton_slot_hints) ? match.anton_slot_hints : [];
  const hints = canonicalAntonSourceSlotHints(rawHints);
  if (hints.length > 0) return hints;
  return match ? Array.from(antonSourceSlotHints(match?.text)) : [];
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
      ? canonicalAntonSourceSlotHints(candidate.anton_slot_hints)
      : Array.from(antonSourceSlotHints(candidate?.text));
    hints.forEach((slot: string) => {
      if (!excerptId) return;
      rows[slot] = rows[slot] || [];
      if (!rows[slot].includes(excerptId)) rows[slot].push(excerptId);
    });
    return rows;
  }, {});
}

function canonicalEvidenceBySlot(evidenceBySlot: any): Record<string, string[]> {
  if (!evidenceBySlot || typeof evidenceBySlot !== "object" || Array.isArray(evidenceBySlot)) return {};
  return Object.entries(evidenceBySlot).reduce((rows: Record<string, string[]>, [rawSlot, rawIds]) => {
    const slot = canonicalAntonSourceSlot(rawSlot);
    if (!slot || !Array.isArray(rawIds)) return rows;
    rows[slot] = rows[slot] || [];
    rawIds
      .map((id: any) => String(id || "").trim())
      .filter(Boolean)
      .forEach((id: string) => {
        if (!rows[slot].includes(id)) rows[slot].push(id);
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
        ? canonicalAntonSourceSlotHints(candidate.anton_slot_hints)
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
        ? canonicalAntonSourceSlotHints(candidate.anton_slot_hints)
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
  return canonicalAntonSourceSlot(kind);
}

function sourcePackageStatus(sourcePackage: any, machine: string = ""): { ready: boolean; message: string } {
  const rawExcerpts = Array.isArray(sourcePackage?.candidate_excerpts) ? sourcePackage.candidate_excerpts : [];
  const excerpts = rawExcerpts.filter((candidate: any) => String(candidate?.text || "").trim());
  if (!sourcePackage || excerpts.length < 6) {
    return { ready: false, message: "Raw source package missing · preview blocked" };
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
  const allowedCaptureMethods = new Set(["fetched_page", "tavily_raw_content"]);
  const missingCaptureMethodCount = targetExcerpts.filter((candidate: any) => !String(candidate?.source_capture_method || "").trim()).length;
  const unsupportedCaptureMethods = new Set(
    targetExcerpts
      .map((candidate: any) => String(candidate?.source_capture_method || "").trim())
      .filter((method: string) => method && !allowedCaptureMethods.has(method))
  );
  if (missingCaptureMethodCount > 0) {
    return { ready: false, message: `Raw source package missing capture method · ${missingCaptureMethodCount} excerpt · preview blocked` };
  }
  if (unsupportedCaptureMethods.size > 0) {
    return { ready: false, message: `Raw source package unsupported capture · ${Array.from(unsupportedCaptureMethods).join(", ")} · preview blocked` };
  }
  if (machine) {
    const traceableTargetExcerpts = targetExcerpts.filter(sourceCandidateTraceable);
    const traceableEvidenceBySlot = sourceSlotEvidenceBySlot(traceableTargetExcerpts);
    const savedMissingSlots = Array.isArray(sourcePackage?.traceable_source_slot_coverage?.missing_slots)
      ? canonicalAntonSourceSlotHints(sourcePackage.traceable_source_slot_coverage.missing_slots)
      : [];
    const missingSlots = savedMissingSlots.length > 0
      ? savedMissingSlots
      : (() => {
          const coveredSlots = new Set(Object.keys(traceableEvidenceBySlot));
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
    const savedNeedsDistinct = sourcePackage?.traceable_source_slot_coverage?.needs_distinct_slot_excerpts === true;
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
  const savedCoverage = sourcePackage?.traceable_source_slot_coverage;
  const savedEvidenceBySlot = canonicalEvidenceBySlot(savedCoverage?.evidence_by_slot);
  const rawExcerpts = Array.isArray(sourcePackage?.candidate_excerpts) ? sourcePackage.candidate_excerpts : [];
  const targetExcerpts = machine ? rawExcerpts.filter((candidate: any) => textMentionsMachine(candidate?.text, machine)) : rawExcerpts;
  const computedEvidenceBySlot = sourceSlotEvidenceBySlot(targetExcerpts.filter(sourceCandidateTraceable));

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

function initFromApi(apiScenes: ApiScriptScene[], assets?: Asset[]): SceneState[] {
  const sorted = [...apiScenes].sort((a, b) => (a.scene || 0) - (b.scene || 0));
  const total = sorted.length;
  const actsCount = Math.min(total, 6);

  return sorted.map((s) => {
    const sceneAssets = (assets || [])
      .filter((a) => a.scene === s.scene)
      .sort((a, b) => (a.image_index || 0) - (b.image_index || 0));

    const sentences: SentenceState[] =
      sceneAssets.length > 0
        ? sceneAssets
            .filter((a) => !!a.sentence_text)
            .map((a) => ({
              text: a.sentence_text!,
              sfxMode: "none" as const,
              sfxLibraryValue: "",
              sfxCustomPrompt: "",
              durationSeconds: (a as any).duration_seconds ?? null,
              cumulativeStart: null,
              imagePrompt: (a as any).image_prompt ?? null,
              imageIndex: a.image_index ?? null,
            }))
        : splitSentences(s.scene_text || "").map((text) => ({
            text,
            sfxMode: "none" as const,
            sfxLibraryValue: "",
            sfxCustomPrompt: "",
            durationSeconds: null,
            cumulativeStart: null,
            imagePrompt: null,
            imageIndex: null,
          }));

    const rawText = s.scene_text || "";
    return {
      id: s.id,
      sceneNumber: s.scene || 0,
      actNumber: Math.ceil((s.scene || 1) / Math.ceil(total / actsCount)),
      narrationText: rawText,
      displayText: stripStyleDirectives(rawText),
      visualStyle: "dossier",
      composition: "wide",
      sources: s.sources
        ? (() => {
            try {
              return JSON.parse(s.sources!);
            } catch {
              return [];
            }
          })()
        : [],
      imageGenerated: sceneAssets.some((a) => !!a.image_url),
      voiceOverUrl: s.voice_over_url || null,
      voiceStatus: s.voice_status || null,
      scriptStatus: s.script_status || null,
      tone: s.tone || null,
      sentences,
    };
  });
}

// ---------------------------------------------------------------------------
// Status badges
// ---------------------------------------------------------------------------

function VoiceStatusBadge({ status }: { status: string | null | undefined }) {
  if (!status) return null;
  const lower = status.toLowerCase();
  if (lower === "finished" || lower === "done") {
    return (
      <span
        className="flex items-center gap-1 text-[9px] font-medium px-1.5 py-0.5 rounded-full"
        style={{ background: "rgba(0, 230, 138, 0.12)", color: "var(--green)" }}
      >
        <CheckCircle size={8} /> Voice Done
      </span>
    );
  }
  if (lower === "create" || lower === "pending") {
    return (
      <span
        className="flex items-center gap-1 text-[9px] font-medium px-1.5 py-0.5 rounded-full"
        style={{ background: "rgba(255, 186, 8, 0.12)", color: "var(--gold)" }}
      >
        <Clock size={8} /> Voice Pending
      </span>
    );
  }
  return (
    <span
      className="flex items-center gap-1 text-[9px] font-medium px-1.5 py-0.5 rounded-full"
      style={{ background: "rgba(255,255,255,0.06)", color: "var(--text-tertiary)" }}
    >
      {status}
    </span>
  );
}

function ScriptStatusBadge({ status }: { status: string | null | undefined }) {
  if (!status) return null;
  const lower = status.toLowerCase();
  if (lower === "finished" || lower === "done") {
    return (
      <span
        className="flex items-center gap-1 text-[9px] font-medium px-1.5 py-0.5 rounded-full"
        style={{ background: "rgba(0, 188, 212, 0.12)", color: "var(--turquoise)" }}
      >
        <CheckCircle size={8} /> Script Done
      </span>
    );
  }
  if (lower === "create" || lower === "pending") {
    return (
      <span
        className="flex items-center gap-1 text-[9px] font-medium px-1.5 py-0.5 rounded-full"
        style={{ background: "rgba(255, 120, 73, 0.12)", color: "var(--orange)" }}
      >
        <AlertCircle size={8} /> Script Pending
      </span>
    );
  }
  return null;
}

// ---------------------------------------------------------------------------
// SegmentEditor — save segment text edits to backend
// ---------------------------------------------------------------------------

function SegmentEditor({ videoId, sceneNumber }: { videoId: string; sceneNumber: number }) {
  const queryClient = useQueryClient();
  const { data, isLoading } = useQuery({
    queryKey: ["segments", videoId, sceneNumber],
    queryFn: () => getSceneSegments(videoId, sceneNumber),
  });
  const [edits, setEdits] = useState<Record<number, string>>({});
  const [saved, setSaved] = useState(false);

  const segments = data?.segments || [];
  const hasEdits = Object.keys(edits).length > 0;

  const saveMutation = useMutation({
    mutationFn: () => {
      const updated = segments.map((seg) => ({
        image_index: seg.image_index,
        sentence_text: edits[seg.image_index] ?? seg.sentence_text,
      }));
      return updateSceneSegments(videoId, sceneNumber, updated);
    },
    onSuccess: () => {
      setEdits({});
      setSaved(true);
      setTimeout(() => setSaved(false), 1500);
      queryClient.invalidateQueries({ queryKey: ["segments", videoId, sceneNumber] });
      queryClient.invalidateQueries({ queryKey: ["video-assets", videoId] });
    },
  });

  if (isLoading) {
    return (
      <div className="flex items-center gap-2 py-3 justify-center">
        <Loader2 size={14} className="animate-spin" style={{ color: "var(--turquoise)" }} />
        <span className="text-[11px]" style={{ color: "var(--text-tertiary)" }}>Loading segments...</span>
      </div>
    );
  }

  if (segments.length === 0) return null;

  return (
    <div className="mt-3 pt-3" style={{ borderTop: "1px solid rgba(255,255,255,0.06)" }}>
      <div className="flex items-center gap-2 mb-2">
        <Save size={11} style={{ color: "var(--turquoise)" }} />
        <span className="text-[10px] font-semibold uppercase tracking-wider" style={{ color: "var(--text-tertiary)" }}>
          Segments
        </span>
      </div>
      <div className="space-y-1.5">
        {segments.map((seg) => {
          const text = edits[seg.image_index] ?? seg.sentence_text;
          const isDirty = seg.image_index in edits;
          return (
            <div
              key={seg.image_index}
              className="rounded-lg p-2"
              style={{
                background: isDirty ? "rgba(0,212,170,0.04)" : "rgba(255,255,255,0.02)",
                border: `1px solid ${isDirty ? "rgba(0,212,170,0.2)" : "rgba(255,255,255,0.05)"}`,
              }}
            >
              <div className="flex items-center gap-2 mb-1">
                <span className="text-[9px] font-mono font-medium px-1.5 py-0.5 rounded"
                  style={{ background: "var(--turquoise-dim)", color: "var(--turquoise)" }}>
                  Seg {seg.image_index}
                </span>
                <span className="text-[9px] font-mono" style={{ color: "var(--text-tertiary)" }}>
                  {seg.word_count}w · {seg.duration_seconds.toFixed(1)}s
                </span>
                {isDirty && (
                  <span className="text-[9px] font-medium" style={{ color: "var(--turquoise)" }}>modified</span>
                )}
              </div>
              <textarea
                value={text}
                onChange={(e) => {
                  const val = e.target.value;
                  setEdits((prev) => {
                    if (val === seg.sentence_text) {
                      const next = { ...prev };
                      delete next[seg.image_index];
                      return next;
                    }
                    return { ...prev, [seg.image_index]: val };
                  });
                }}
                rows={Math.max(1, Math.ceil(text.length / 90))}
                className="w-full text-sm leading-relaxed resize-none outline-none rounded-lg px-2 py-1 transition-all"
                style={{ color: "var(--text-primary)", background: "transparent", border: "1px solid transparent" }}
                onFocus={(e) => { e.target.style.background = "var(--bg-elevated)"; e.target.style.borderColor = "var(--turquoise)"; }}
                onBlur={(e) => { e.target.style.background = "transparent"; e.target.style.borderColor = "transparent"; }}
              />
            </div>
          );
        })}
        <div className="flex items-center gap-2 pt-1">
          <button
            onClick={() => saveMutation.mutate()}
            disabled={!hasEdits || saveMutation.isPending}
            className="flex items-center gap-1.5 px-3 py-1.5 rounded-lg text-[11px] font-semibold transition-all disabled:opacity-30"
            style={{ background: "var(--turquoise)", color: "var(--bg-void)" }}
          >
            {saveMutation.isPending ? <Loader2 size={12} className="animate-spin" /> : <Save size={12} />}
            Save Segments
          </button>
          {saved && (
            <span className="text-[11px] font-medium" style={{ color: "var(--green)" }}>
              <CheckCircle size={12} className="inline mr-1" />Saved
            </span>
          )}
          {saveMutation.isError && (
            <span className="text-[11px]" style={{ color: "var(--red)" }}>
              Save failed: {(saveMutation.error as Error).message}
            </span>
          )}
        </div>
      </div>
    </div>
  );
}

// ---------------------------------------------------------------------------
// Custom voice (ElevenLabs) — paste a voice ID so narration uses your own voice
// instead of the default Kie roster. Saves to the same per-tenant key store as
// Settings → Keys, surfaced here where you actually generate voice.
// ---------------------------------------------------------------------------

function CustomVoiceCard() {
  const toast = useToast();
  const queryClient = useQueryClient();
  const [open, setOpen] = useState(false);
  const [voiceId, setVoiceId] = useState("");
  const [apiKey, setApiKeyValue] = useState("");

  const { data: voiceStatus } = useQuery({
    queryKey: ["key-status", "elevenlabs_voice_id"],
    queryFn: () => getApiKeyStatus("elevenlabs_voice_id"),
  });
  const { data: keyStatus } = useQuery({
    queryKey: ["key-status", "elevenlabs_api_key"],
    queryFn: () => getApiKeyStatus("elevenlabs_api_key"),
  });

  const save = useMutation({
    mutationFn: async () => {
      if (apiKey.trim()) await setApiKey("elevenlabs_api_key", apiKey.trim());
      if (voiceId.trim()) await setApiKey("elevenlabs_voice_id", voiceId.trim());
    },
    onSuccess: () => {
      toast.success("Saved — new voice generations will use your ElevenLabs voice.");
      setVoiceId("");
      setApiKeyValue("");
      queryClient.invalidateQueries({ queryKey: ["key-status", "elevenlabs_voice_id"] });
      queryClient.invalidateQueries({ queryKey: ["key-status", "elevenlabs_api_key"] });
    },
    onError: (err) => toast.error(`Couldn't save voice: ${(err as Error).message}`),
  });

  const voiceSet = !!voiceStatus?.configured;
  const keySet = !!keyStatus?.configured;
  const canSave = !!voiceId.trim() && (keySet || !!apiKey.trim()) && !save.isPending;

  return (
    <GlassCard className="p-5">
      <button
        onClick={() => setOpen((o) => !o)}
        className="flex items-center justify-between w-full text-left"
      >
        <span className="text-[10px] uppercase tracking-wider" style={{ color: "var(--text-tertiary)" }}>
          Custom Voice (ElevenLabs)
        </span>
        <span className="flex items-center gap-2">
          {voiceSet && (
            <span className="inline-flex items-center gap-1 text-[10px]" style={{ color: "var(--green)" }}>
              <CheckCircle size={11} /> set
            </span>
          )}
          {open ? <ChevronDown size={14} style={{ color: "var(--text-tertiary)" }} /> : <ChevronRight size={14} style={{ color: "var(--text-tertiary)" }} />}
        </span>
      </button>

      {open && (
        <div className="space-y-2.5 mt-3">
          <p className="text-[11px] leading-snug" style={{ color: "var(--text-tertiary)" }}>
            Paste a Voice ID from your ElevenLabs voice library to narrate in your own voice.
            {voiceSet ? " A voice is already saved — paste a new ID to change it." : ""}
          </p>
          <input
            value={voiceId}
            onChange={(e) => setVoiceId(e.target.value)}
            placeholder="ElevenLabs Voice ID (e.g. 21m00Tcm4TlvDq8ikWAM)"
            className="w-full px-3 py-2 rounded-lg text-sm font-mono"
            style={{ background: "var(--bg-elevated)", border: "1px solid var(--border-subtle)", color: "var(--text-primary)" }}
          />
          {!keySet && (
            <input
              value={apiKey}
              onChange={(e) => setApiKeyValue(e.target.value)}
              placeholder="ElevenLabs API key (needed once)"
              type="password"
              className="w-full px-3 py-2 rounded-lg text-sm font-mono"
              style={{ background: "var(--bg-elevated)", border: "1px solid var(--border-subtle)", color: "var(--text-primary)" }}
            />
          )}
          <ActionButton
            variant="outline"
            icon={save.isPending ? Loader2 : Save}
            className="w-full"
            onClick={() => canSave && save.mutate()}
            disabled={!canSave}
          >
            {save.isPending ? "Saving..." : "Save voice"}
          </ActionButton>
        </div>
      )}
    </GlassCard>
  );
}

// ---------------------------------------------------------------------------
// Main component
// ---------------------------------------------------------------------------

export function ScriptVoiceTab({ video, onAdvanced }: ScriptVoiceTabProps) {
  const queryClient = useQueryClient();
  const toast = useToast();

  // ---- Data fetching ----
  const { data: apiScenes, isLoading } = useQuery({
    queryKey: ["video-script", video.id],
    queryFn: () => getVideoScript(video.id),
    enabled: !!video.id,
  });

  const { data: apiAssets } = useQuery({
    queryKey: ["video-assets", video.id],
    queryFn: () => getVideoAssets(video.id),
    enabled: !!video.id,
  });

  const computed = useMemo(
    () => (apiScenes ? initFromApi(apiScenes, apiAssets || undefined) : []),
    [apiScenes, apiAssets],
  );

  // ---- Local state ----
  const [scenes, setScenes] = useState<SceneState[]>([]);
  const [collapsedActs, setCollapsedActs] = useState<Record<number, boolean>>({});
  const [expandedScenes, setExpandedScenes] = useState<Set<number>>(new Set());

  // Script actions
  const [approving, setApproving] = useState(false);
  const [rejecting, setRejecting] = useState(false);
  const [regeneratingScript, setRegeneratingScript] = useState(false);
  const [deletingScene, setDeletingScene] = useState<number | null>(null);
  const [rewritingScene, setRewritingScene] = useState<number | null>(null);
  const [savingScene, setSavingScene] = useState<number | null>(null);
  const [savedScene, setSavedScene] = useState<number | null>(null);
  const [showRevisionModal, setShowRevisionModal] = useState(false);
  const [revisionNotes, setRevisionNotes] = useState("");
  const [revisionScope, setRevisionScope] = useState("Minor tweaks");
  const [approved, setApproved] = useState(false);
  const [previewMachine, setPreviewMachine] = useState("");
  const [previewGenerating, setPreviewGenerating] = useState(false);
  const [machinePreview, setMachinePreview] = useState<MachineScriptPreview | null>(null);

  // Voice actions
  const [generatingVoiceAll, setGeneratingVoiceAll] = useState(false);
  const [generatingVoiceScene, setGeneratingVoiceScene] = useState<number | null>(null);

  // Task polling (script generation)
  const [scriptTaskRunning, setScriptTaskRunning] = useState(false);
  const { message: scriptTaskMessage } = useTaskPoller({
    videoId: video.id,
    enabled: scriptTaskRunning,
    interval: 3000,
    onComplete: async () => {
      setScriptTaskRunning(false);
      setRegeneratingScript(false);
      invalidateAll();
      // Auto-split sentences after script generation
      try {
        setSplitting(true);
        await runSplit(video.id);
        setSplitDone(true);
        invalidateAll();
      } catch {
        // Split failure is non-blocking — user can retry from sidebar
      } finally {
        setSplitting(false);
      }
    },
    onFailed: (error) => {
      setScriptTaskRunning(false);
      setRegeneratingScript(false);
      toast.error(`Script generation failed: ${error}`);
    },
  });

  // Task polling (voice generation)
  const [voiceTaskRunning, setVoiceTaskRunning] = useState(false);
  const { message: voiceTaskMessage } = useTaskPoller({
    videoId: video.id,
    enabled: voiceTaskRunning,
    interval: 3000,
    onComplete: () => {
      setVoiceTaskRunning(false);
      setGeneratingVoiceAll(false);
      setGeneratingVoiceScene(null);
      invalidateAll();
    },
    onFailed: (error) => {
      setVoiceTaskRunning(false);
      setGeneratingVoiceAll(false);
      setGeneratingVoiceScene(null);
      toast.error(`Voice generation failed: ${error}`);
    },
  });

  // Rehydrate after a page refresh: if the backend is still working on this
  // video, put the tab back into its generating state (spinner + disabled
  // buttons) instead of looking idle. This state used to live only in the
  // browser session that clicked the button, so a refresh went blind and
  // re-clicks bounced off the 409 guard with no explanation.
  useEffect(() => {
    let cancelled = false;
    getPipelineTaskStatus(video.id)
      .then((task) => {
        if (cancelled || !task || task.status !== "running") return;
        const msg = (task.message || "").toLowerCase();
        if (msg.includes("voic")) {
          setVoiceTaskRunning(true);
          setGeneratingVoiceAll(true);
        } else if (msg.includes("script")) {
          setScriptTaskRunning(true);
          setRegeneratingScript(true);
        }
      })
      .catch(() => {});
    return () => { cancelled = true; };
  }, [video.id]);

  // Scene segment state (declared here so fetchAndExpandScene is available to the prompt poller below)
  const [loadingSegments, setLoadingSegments] = useState<Set<number>>(new Set());

  const fetchAndExpandScene = useCallback(async (sceneNum: number) => {
    setLoadingSegments((prev) => new Set(prev).add(sceneNum));
    try {
      const resp = await getSceneSegments(video.id, sceneNum);
      if (resp.segments && resp.segments.length > 0) {
        setScenes((prev) =>
          prev.map((s) => {
            if (s.sceneNumber !== sceneNum) return s;
            const newSentences: SentenceState[] = resp.segments.map((seg: Segment) => ({
              text: seg.sentence_text || "",
              sfxMode: "none" as const,
              sfxLibraryValue: "",
              sfxCustomPrompt: "",
              durationSeconds: seg.duration_seconds ?? null,
              cumulativeStart: seg.cumulative_start ?? null,
              imagePrompt: seg.image_prompt ?? null,
              imageIndex: seg.image_index ?? null,
            }));
            return { ...s, sentences: newSentences };
          }),
        );
      }
    } catch {
      // Fall back to existing local sentences
    } finally {
      setLoadingSegments((prev) => {
        const next = new Set(prev);
        next.delete(sceneNum);
        return next;
      });
    }
    setExpandedScenes((prev) => new Set(prev).add(sceneNum));
  }, [video.id]);

  // Sentence splitting
  const [splitDone, setSplitDone] = useState(false);
  const [splitting, setSplitting] = useState(false);

  const invalidateAll = useCallback(() => {
    queryClient.invalidateQueries({ queryKey: ["video", video.id] });
    queryClient.invalidateQueries({ queryKey: ["video-script", video.id] });
    queryClient.invalidateQueries({ queryKey: ["video-assets", video.id] });
  }, [queryClient, video.id]);

  // ---- Google Drive script sync ----
  const { data: driveStatus, refetch: refetchDrive } = useQuery({
    queryKey: ["drive-script-status", video.id],
    queryFn: () => getDriveScriptStatus(video.id),
    enabled: !!video.id,
  });

  // Performance track: the dialogue-intelligence timeline (who speaks vs the
  // narrator). Before this card it existed only as 💬 badges on scene picture
  // cards — invisible until images existed, so creators couldn't tell the
  // hybrid voice was even wired (Ryan hit exactly that).
  const { data: dialogueMap } = useQuery({
    queryKey: ["dialogue-map", video.id],
    queryFn: () => getDialogueMap(video.id),
    enabled: !!video.id,
    staleTime: 30_000,
  });
  const performanceTrack = useMemo(() => {
    if (!dialogueMap) return null;
    const bySpeaker = new Map<
      string,
      { count: number; lines: Array<{ scene: number; index: number; text: string; voiced: boolean }> }
    >();
    let narration = 0;
    for (const sc of dialogueMap.scenes ?? []) {
      for (const seg of sc.segments ?? []) {
        if (seg.type === "dialogue" && seg.speaker) {
          const entry = bySpeaker.get(seg.speaker) ?? { count: 0, lines: [] };
          entry.count += 1;
          entry.lines.push({ scene: sc.scene, index: seg.index, text: seg.text || "", voiced: seg.voiced });
          bySpeaker.set(seg.speaker, entry);
        } else if (seg.type === "narration") {
          narration += 1;
        }
      }
    }
    return { mode: dialogueMap.dialogue_mode, bySpeaker: [...bySpeaker.entries()], narration };
  }, [dialogueMap]);

  // Per-line audition: tap a line on the Performance Track card to hear that
  // character's cast voice (the scene player only carries the narrator). The
  // segment MP3 streams via GET dialogue-audio/{scene}/{index} with the same
  // short-lived browser token the animatic uses.
  const lineAudioRef = useRef<HTMLAudioElement | null>(null);
  const [playingLine, setPlayingLine] = useState<string | null>(null);
  const playLine = useCallback(async (scene: number, index: number) => {
    const key = `${scene}:${index}`;
    const a = lineAudioRef.current;
    if (!a) return;
    if (playingLine === key) {
      a.pause();
      setPlayingLine(null);
      return;
    }
    try {
      const { token } = await getAudioToken(video.id);
      a.src = `${API_URL}/api/videos/${video.id}/dialogue-audio/${scene}/${index}?token=${token}`;
      await a.play();
      setPlayingLine(key);
    } catch {
      setPlayingLine(null);
      toast.error("Couldn't play that line — generate the voiceover first.");
    }
  }, [playingLine, video.id, toast]);

  // Scene narration audition: play a scene's voiceover right on its card so
  // the voice can be judged at the gate where it was generated (the full
  // player still lives on the Scenes tab).
  const sceneAudioRef = useRef<HTMLAudioElement | null>(null);
  const [playingSceneVoice, setPlayingSceneVoice] = useState<number | null>(null);
  const playSceneVoice = useCallback(async (scene: number) => {
    const a = sceneAudioRef.current;
    if (!a) return;
    if (playingSceneVoice === scene) {
      a.pause();
      setPlayingSceneVoice(null);
      return;
    }
    try {
      const { token } = await getAudioToken(video.id);
      a.src = `${API_URL}/api/videos/${video.id}/audio/${scene}?token=${token}`;
      await a.play();
      setPlayingSceneVoice(scene);
    } catch {
      setPlayingSceneVoice(null);
      toast.error("Couldn't play this scene's voice — try regenerating it.");
    }
  }, [playingSceneVoice, video.id, toast]);
  const [driveMsg, setDriveMsg] = useState<string | null>(null);
  const [driveConflict, setDriveConflict] = useState(false);

  const pushDriveMutation = useMutation({
    mutationFn: () => pushScriptToDrive(video.id),
    onSuccess: (res) => {
      setDriveMsg(null);
      setDriveConflict(false);
      refetchDrive();
      if (res.doc_url) window.open(res.doc_url, "_blank", "noopener,noreferrer");
    },
    onError: (e: Error) => setDriveMsg(e.message),
  });

  const pullDriveMutation = useMutation({
    mutationFn: (force: boolean) => syncScriptFromDrive(video.id, force),
    onSuccess: (res) => {
      if (res.conflict) {
        setDriveConflict(true);
        setDriveMsg(res.message || "Both sides changed since the last sync.");
        return;
      }
      setDriveConflict(false);
      setDriveMsg(res.message || (res.changed ? "Synced from Drive." : "No new edits."));
      if (res.changed) invalidateAll();
      refetchDrive();
    },
    onError: (e: Error) => { setDriveConflict(false); setDriveMsg(e.message); },
  });

  // Sync API data into local state (once)
  useEffect(() => {
    if (computed.length > 0 && scenes.length === 0) {
      setScenes(computed);
    }
  }, [computed, scenes.length]);

  // Re-sync voice data when API data refreshes (voice URLs may have appeared)
  useEffect(() => {
    if (computed.length > 0 && scenes.length > 0) {
      setScenes((prev) =>
        prev.map((s) => {
          const fresh = computed.find((c) => c.sceneNumber === s.sceneNumber);
          if (!fresh) return s;
          return {
            ...s,
            voiceOverUrl: fresh.voiceOverUrl,
            voiceStatus: fresh.voiceStatus,
          };
        }),
      );
    }
  }, [computed]); // eslint-disable-line react-hooks/exhaustive-deps

  // ---- Act grouping ----
  const actGroups = useMemo(
    () =>
      scenes.reduce(
        (acc, scene) => {
          if (!acc[scene.actNumber]) acc[scene.actNumber] = [];
          acc[scene.actNumber].push(scene);
          return acc;
        },
        {} as Record<number, SceneState[]>,
      ),
    [scenes],
  );

  // ---- Derived stats ----
  const totalScenes = scenes.length;
  const totalSentences = scenes.reduce((sum, s) => sum + s.sentences.length, 0);
  const wordCount = scenes.reduce(
    (sum, s) => sum + s.narrationText.split(/\s+/).filter(Boolean).length,
    0,
  );
  // A character-dialogue scene's voice lives in its per-segment performance
  // track, not a narrator MP3 — voice_over_url never exists for the pure
  // couple format, which left "Voice 0/1" stuck after every line was voiced.
  const dialogueVoicedScenes = useMemo(() => {
    const done = new Set<number>();
    if (dialogueMap?.dialogue_mode === "character_dialogue") {
      for (const sc of dialogueMap.scenes ?? []) {
        const segs = sc.segments ?? [];
        if (segs.length > 0 && segs.every((g) => g.voiced)) done.add(sc.scene);
      }
    }
    return done;
  }, [dialogueMap]);
  const sceneHasVoice = (s: { voiceOverUrl: string | null; sceneNumber: number }) =>
    !!s.voiceOverUrl || dialogueVoicedScenes.has(s.sceneNumber);
  const scenesWithVoice = scenes.filter(sceneHasVoice).length;
  const scenesWithScript = scenes.filter(
    (s) => !!s.narrationText.trim(),
  ).length;
  // Voice is OPTIONAL. When the creator turned AI voice-over off (skip_voice, or
  // no "voice" stage in the plan) it must not be required to finish this stage or
  // advance — otherwise a no-voice video is stuck behind a mandatory voice step.
  const voiceSkipped = !!video.skip_voice ||
    (Array.isArray(video.pipeline_stages) && !video.pipeline_stages.includes("voice"));
  const allReady = totalScenes > 0 && scenesWithScript === totalScenes &&
    (voiceSkipped || scenesWithVoice === totalScenes);

  // ---------------------------------------------------------------------------
  // Script handlers
  // ---------------------------------------------------------------------------

  const handleApprove = useCallback(async () => {
    if (!confirm("Approve script & voice and advance to next stage?")) return;
    setApproving(true);
    try {
      await advanceVideo(video.id);
      invalidateAll();
      setApproved(true);
    } catch (err) {
      toast.error(`Failed to approve: ${(err as Error).message}`);
      setApproving(false);
    }
  }, [video.id, invalidateAll]);

  const handleReject = useCallback(() => {
    setShowRevisionModal(true);
  }, []);

  const handleSubmitRevision = useCallback(async () => {
    setRejecting(true);
    try {
      const notes = `[${revisionScope}] ${revisionNotes}`;
      await updateVideo(video.id, { revision_notes: notes });
      await rejectVideo(video.id, notes);
      invalidateAll();
      setShowRevisionModal(false);
      setRevisionNotes("");
      setRevisionScope("Minor tweaks");
    } catch (err) {
      toast.error(`Failed to request revision: ${(err as Error).message}`);
    } finally {
      setRejecting(false);
    }
  }, [video.id, revisionScope, revisionNotes, invalidateAll, toast]);

  const scriptRegenerationBlockedReason = useCallback(() => {
    try {
      const payload = typeof video.research_payload === "string" ? JSON.parse(video.research_payload || "{}") : (video.research_payload || {});
      const roster = Array.isArray(payload?.unit_roster) ? payload.unit_roster : [];
      if (video.render_mode === "static_docu" && roster.length > 0) {
        const validation = payload?.unit_research_hold_validation;
        const cards = Array.isArray(payload?.unit_research_cards) ? payload.unit_research_cards : [];
        const packages = payload?.machine_raw_source_packages && typeof payload.machine_raw_source_packages === "object" && !Array.isArray(payload.machine_raw_source_packages)
          ? payload.machine_raw_source_packages
          : {};
        const verifiedCount = roster.filter((item: any) => {
          const label = machineLabel(item);
          const card = cards.find((candidate: any) => cardMatchesMachine(candidate, label));
          const sourcePackage = sourcePackageForMachine(packages, label);
          return machineResearchCardReady(card, label, sourcePackage) && sourcePackageReady(sourcePackage, label);
        }).length;
        if (!fullMachineResearchGatePassed(validation, verifiedCount, roster.length)) {
          return `Machine research is incomplete: ${verifiedCount}/${roster.length} verified cards finished.`;
        }
      }

      const scriptValidation = typeof video.script_validation === "string" ? JSON.parse(video.script_validation || "{}") : (video.script_validation || {});
      const scriptGate = scriptValidation?.unit_roster;
      if (scriptGate?.complete_title && scriptGate?.passed === false) {
        return `Script roster gate failed: ${(scriptGate.warnings || []).join("; ") || "script roster is incomplete"}`;
      }
    } catch {
      return null;
    }
    return null;
  }, [video.render_mode, video.research_payload, video.script_validation]);

  const handleRegenerateScript = useCallback(async () => {
    const blockedReason = scriptRegenerationBlockedReason();
    if (blockedReason) {
      toast.error(blockedReason);
      return;
    }
    setRegeneratingScript(true);
    try {
      await runPipelineStage(video.id, "script");
      setScriptTaskRunning(true);
    } catch (err: unknown) {
      const message = (err as Error).message || "";
      if (message.includes("409")) {
        try {
          await clearStaleTask(video.id);
          await runPipelineStage(video.id, "script");
          setScriptTaskRunning(true);
          return;
        } catch (retryErr) {
          toast.error(`Failed to regenerate: ${(retryErr as Error).message}`);
        }
      } else {
        toast.error(`Failed to regenerate: ${message}`);
      }
      setRegeneratingScript(false);
    }
  }, [video.id, scriptRegenerationBlockedReason, toast]);

  const handleSplitSentences = useCallback(async () => {
    setSplitting(true);
    setSplitDone(false);
    try {
      await runSplit(video.id);
      setSplitDone(true);
      invalidateAll();
      setTimeout(() => setSplitDone(false), 3000);
      // Auto-expand all scenes to show the split results
      const sceneNums = scenes.map((s) => s.sceneNumber);
      await Promise.allSettled(sceneNums.map((n) => fetchAndExpandScene(n)));
    } catch (err) {
      toast.error(`Split failed: ${(err as Error).message}`);
    } finally {
      setSplitting(false);
    }
  }, [video.id, invalidateAll, scenes, fetchAndExpandScene]);

  const handleDeleteScene = useCallback(
    async (sceneNum: number) => {
      setDeletingScene(sceneNum);
      try {
        await updateSceneText(video.id, sceneNum, "");
        invalidateAll();
        setScenes((prev) => prev.filter((s) => s.sceneNumber !== sceneNum));
      } catch (err) {
        toast.error(`Failed to delete scene: ${(err as Error).message}`);
      } finally {
        setDeletingScene(null);
      }
    },
    [video.id, invalidateAll],
  );

  // AI-rewrite one scene (static docu: one machine's unit paragraph) from the
  // research facts — dial in a single machine without re-rolling the script.
  const handleRewriteScene = useCallback(
    async (sceneNum: number) => {
      setRewritingScene(sceneNum);
      try {
        const res = await rewriteSceneText(video.id, sceneNum);
        setScenes((prev) =>
          prev.map((s) => {
            if (s.sceneNumber !== sceneNum) return s;
            const newSentences = splitSentences(res.text).map((t, i) => ({
              ...(s.sentences[i] || { sfxMode: "none" as const, sfxLibraryValue: "", sfxCustomPrompt: "", durationSeconds: null, cumulativeStart: null, imagePrompt: null, imageIndex: null }),
              text: t,
            }));
            return {
              ...s, narrationText: res.text, displayText: stripStyleDirectives(res.text),
              sentences: newSentences, voiceOverUrl: null, voiceStatus: null,
            };
          }),
        );
        invalidateAll();
        toast.success(`Scene ${sceneNum} rewritten (${res.word_count} words) — voice cleared for re-record`);
      } catch (err) {
        toast.error(`Rewrite failed: ${(err as Error).message}`);
      } finally {
        setRewritingScene(null);
      }
    },
    [video.id, invalidateAll],
  );

  const handleNarrationBlur = useCallback(
    async (sceneNum: number, text: string) => {
      setSavingScene(sceneNum);
      try {
        await updateSceneText(video.id, sceneNum, text);
        setSavedScene(sceneNum);
        setTimeout(() => setSavedScene(null), 1500);
      } catch (err) {
        console.error(`Failed to save scene ${sceneNum}:`, err);
      } finally {
        setSavingScene(null);
      }
    },
    [video.id],
  );

  // ---------------------------------------------------------------------------
  // Voice handlers
  // ---------------------------------------------------------------------------

  const handleGenerateAllVoice = useCallback(async () => {
    setGeneratingVoiceAll(true);
    try {
      await runPipelineStage(video.id, "voice");
      setVoiceTaskRunning(true);
    } catch (err: unknown) {
      const message = (err as Error).message || "";
      if (message.includes("409")) {
        try {
          await clearStaleTask(video.id);
          await runPipelineStage(video.id, "voice");
          setVoiceTaskRunning(true);
          return;
        } catch (retryErr) {
          toast.error(`Voice generation failed: ${(retryErr as Error).message}`);
        }
      } else {
        toast.error(`Voice generation failed: ${message}`);
      }
      setGeneratingVoiceAll(false);
    }
  }, [video.id]);

  const handleGenerateSceneVoice = useCallback(
    async (sceneNum: number) => {
      setGeneratingVoiceScene(sceneNum);
      try {
        await runVoiceForScene(video.id, sceneNum);
        setVoiceTaskRunning(true);
      } catch (err: unknown) {
        const message = (err as Error).message || "";
        if (message.includes("409")) {
          try {
            await clearStaleTask(video.id);
            await runVoiceForScene(video.id, sceneNum);
            setVoiceTaskRunning(true);
            return;
          } catch (retryErr) {
            toast.error(`Voice generation failed: ${(retryErr as Error).message}`);
          }
        } else {
          toast.error(`Voice generation failed: ${message}`);
        }
        setGeneratingVoiceScene(null);
      }
    },
    [video.id],
  );

  // ---------------------------------------------------------------------------
  // Scene editing helpers
  // ---------------------------------------------------------------------------

  const toggleAct = (actNum: number) => {
    setCollapsedActs((prev) => ({ ...prev, [actNum]: !prev[actNum] }));
  };

  const toggleExpand = async (sceneNum: number) => {
    if (expandedScenes.has(sceneNum)) {
      setExpandedScenes((prev) => {
        const next = new Set(prev);
        next.delete(sceneNum);
        return next;
      });
      return;
    }
    await fetchAndExpandScene(sceneNum);
  };

  const updateNarration = (sceneNum: number, text: string) => {
    setScenes((prev) =>
      prev.map((s) => {
        if (s.sceneNumber !== sceneNum) return s;
        const newSentences = splitSentences(text).map((t, i) => ({
          ...(s.sentences[i] || { sfxMode: "none" as const, sfxLibraryValue: "", sfxCustomPrompt: "", durationSeconds: null, cumulativeStart: null, imagePrompt: null, imageIndex: null }),
          text: t,
        }));
        return { ...s, narrationText: text, displayText: stripStyleDirectives(text), sentences: newSentences };
      }),
    );
  };

  const updateSentence = (sceneNum: number, sentIdx: number, text: string) => {
    setScenes((prev) =>
      prev.map((s) => {
        if (s.sceneNumber !== sceneNum) return s;
        const newSentences = s.sentences.map((sent, i) => (i === sentIdx ? { ...sent, text } : sent));
        const narrationText = newSentences.map((sent) => sent.text).join(" ");
        return { ...s, sentences: newSentences, narrationText, displayText: stripStyleDirectives(narrationText) };
      }),
    );
  };

  const mergeSentenceUp = (sceneNum: number, sentIdx: number) => {
    if (sentIdx === 0) return;
    setScenes((prev) =>
      prev.map((s) => {
        if (s.sceneNumber !== sceneNum) return s;
        const newSentences = [...s.sentences];
        newSentences[sentIdx - 1] = {
          ...newSentences[sentIdx - 1],
          text: newSentences[sentIdx - 1].text + " " + newSentences[sentIdx].text,
        };
        newSentences.splice(sentIdx, 1);
        const narrationText = newSentences.map((sent) => sent.text).join(" ");
        return { ...s, sentences: newSentences, narrationText, displayText: stripStyleDirectives(narrationText) };
      }),
    );
  };

  const deleteSentence = (sceneNum: number, sentIdx: number) => {
    setScenes((prev) =>
      prev.map((s) => {
        if (s.sceneNumber !== sceneNum) return s;
        const newSentences = s.sentences.filter((_, i) => i !== sentIdx);
        const narrationText = newSentences.map((sent) => sent.text).join(" ");
        return { ...s, sentences: newSentences, narrationText, displayText: stripStyleDirectives(narrationText) };
      }),
    );
  };

  const addSentenceAfter = (sceneNum: number, sentIdx: number) => {
    setScenes((prev) =>
      prev.map((s) => {
        if (s.sceneNumber !== sceneNum) return s;
        const newSentences = [...s.sentences];
        newSentences.splice(sentIdx + 1, 0, {
          text: "",
          sfxMode: "none",
          sfxLibraryValue: "",
          sfxCustomPrompt: "",
          durationSeconds: null,
          cumulativeStart: null,
          imagePrompt: null,
          imageIndex: null,
        });
        const narrationText = newSentences.map((sent) => sent.text).join(" ");
        return { ...s, sentences: newSentences, narrationText, displayText: stripStyleDirectives(narrationText) };
      }),
    );
  };

  const updateSfxMode = (sceneNum: number, sentIdx: number, mode: SentenceState["sfxMode"]) => {
    setScenes((prev) =>
      prev.map((s) => {
        if (s.sceneNumber !== sceneNum) return s;
        const newSentences = s.sentences.map((sent, i) => (i === sentIdx ? { ...sent, sfxMode: mode } : sent));
        return { ...s, sentences: newSentences };
      }),
    );
  };

  const updateSfxLibrary = (sceneNum: number, sentIdx: number, value: string) => {
    setScenes((prev) =>
      prev.map((s) => {
        if (s.sceneNumber !== sceneNum) return s;
        const newSentences = s.sentences.map((sent, i) =>
          i === sentIdx
            ? { ...sent, sfxLibraryValue: value, sfxMode: (value ? "library" : "none") as SentenceState["sfxMode"] }
            : sent,
        );
        return { ...s, sentences: newSentences };
      }),
    );
  };

  const updateSfxPrompt = (sceneNum: number, sentIdx: number, prompt: string) => {
    setScenes((prev) =>
      prev.map((s) => {
        if (s.sceneNumber !== sceneNum) return s;
        const newSentences = s.sentences.map((sent, i) =>
          i === sentIdx ? { ...sent, sfxCustomPrompt: prompt } : sent,
        );
        return { ...s, sentences: newSentences };
      }),
    );
  };

  const mergeSceneUp = (sceneNum: number) => {
    setScenes((prev) => {
      const idx = prev.findIndex((s) => s.sceneNumber === sceneNum);
      if (idx <= 0) return prev;
      const merged = [...prev];
      const narrationText = merged[idx - 1].narrationText + " " + merged[idx].narrationText;
      merged[idx - 1] = {
        ...merged[idx - 1],
        narrationText,
        displayText: stripStyleDirectives(narrationText),
        sentences: [...merged[idx - 1].sentences, ...merged[idx].sentences],
      };
      merged.splice(idx, 1);
      return merged;
    });
  };

  const addSceneAfter = (sceneNum: number) => {
    setScenes((prev) => {
      const idx = prev.findIndex((s) => s.sceneNumber === sceneNum);
      const actNum = prev[idx]?.actNumber || 1;
      const newScene: SceneState = {
        id: `new-${Date.now()}`,
        sceneNumber: Math.max(...prev.map((s) => s.sceneNumber)) + 1,
        actNumber: actNum,
        narrationText: "",
        displayText: "",
        visualStyle: "dossier",
        composition: "medium",
        sources: [],
        imageGenerated: false,
        voiceOverUrl: null,
        voiceStatus: null,
        scriptStatus: null,
        tone: null,
        sentences: [{ text: "", sfxMode: "none", sfxLibraryValue: "", sfxCustomPrompt: "", durationSeconds: null, cumulativeStart: null, imagePrompt: null, imageIndex: null }],
      };
      const result = [...prev];
      result.splice(idx + 1, 0, newScene);
      return result;
    });
  };

  // ---- Advance stage ----
  // HOOKS MUST STAY ABOVE THE EARLY RETURNS: these lived after the loading /
  // empty-state returns, so the hook count changed once the script loaded and
  // React threw #310 ("rendered more hooks than during the previous render"),
  // crashing the whole pipeline page to the error boundary.
  const [advancing, setAdvancing] = useState(false);
  const handleAdvanceStage = useCallback(async () => {
    setAdvancing(true);
    try {
      await advanceVideo(video.id);
      invalidateAll();
      onAdvanced?.();
    } catch (err) {
      toast.error(`Advance failed: ${(err as Error).message}`);
    } finally {
      setAdvancing(false);
    }
  }, [video.id, invalidateAll, onAdvanced]);

  const researchPayload = (() => {
    try {
      return typeof video.research_payload === "string" ? JSON.parse(video.research_payload) : (video.research_payload || {});
    } catch { return {}; }
  })();
  const parsedScriptValidation = (() => {
    try {
      return typeof video.script_validation === "string" ? JSON.parse(video.script_validation) : (video.script_validation || {});
    } catch { return {}; }
  })();
  const machineRoster = Array.isArray(researchPayload?.unit_roster) ? researchPayload.unit_roster : [];
  const isMachineDocumentary = video.render_mode === "static_docu" && machineRoster.length > 0;
  const scriptHold = parsedScriptValidation?.script_hold || null;
  const researchRosterGate = researchPayload?.unit_roster_validation || null;
  const verifiedMachineResearchCount = useMemo(() => {
    const cards = Array.isArray(researchPayload?.unit_research_cards) ? researchPayload.unit_research_cards : [];
    return machineRoster.filter((item: any) => {
      const label = machineLabel(item);
      const card = cards.find((candidate: any) => cardMatchesMachine(candidate, label));
      const sourcePackage = sourcePackageForMachine(researchPayload?.machine_raw_source_packages, label);
      return machineResearchCardReady(card, label, sourcePackage) && sourcePackageReady(sourcePackage, label);
    }).length;
  }, [machineRoster, researchPayload]);
  const machineResearchGate = (() => {
    const roster = machineRoster;
    if (roster.length === 0) return null;
    const validation = researchPayload?.unit_research_hold_validation;
    return fullMachineResearchGatePassed(validation, verifiedMachineResearchCount, roster.length)
      ? validation
      : {
          passed: false,
          complete_title: true,
          roster_count: roster.length,
          warnings: validation?.warnings || [`Machine research is incomplete: ${verifiedMachineResearchCount}/${roster.length} verified cards finished.`],
        };
  })();
  const scriptRosterGate = parsedScriptValidation?.unit_roster || null;
  const activeRosterGate = scriptRosterGate || (machineResearchGate?.passed === false ? machineResearchGate : researchRosterGate);
  const scriptGenerationBlockedByRoster = Boolean(activeRosterGate?.complete_title && activeRosterGate?.passed === false);
  const machineRosterLabels = machineRoster.map((item: any) => machineLabel(item)).filter(Boolean);
  const activePreviewMachine = previewMachine || machineRosterLabels[0] || "";
  const activePreviewResearchCard = (Array.isArray(researchPayload?.unit_research_cards) ? researchPayload.unit_research_cards : [])
    .find((candidate: any) => cardMatchesMachine(candidate, activePreviewMachine));
  const activePreviewSourcePackage = sourcePackageForMachine(researchPayload?.machine_raw_source_packages, activePreviewMachine);
  const activePreviewSourcePackageStatus = sourcePackageStatus(activePreviewSourcePackage, activePreviewMachine);
  const activePreviewSourcePackageReady = sourcePackageReady(activePreviewSourcePackage, activePreviewMachine);
  const activePreviewSourceCoverageRows = sourceSlotCoverageRows(activePreviewSourcePackage, activePreviewMachine);
  const activePreviewResearchCardStatus = machineResearchCardStatus(activePreviewResearchCard, activePreviewMachine, activePreviewSourcePackage);
  const activePreviewReady = activePreviewResearchCardStatus.ready && activePreviewSourcePackageReady;
  const activePreviewStatusMessage = activePreviewResearchCardStatus.ready
    ? activePreviewSourcePackageStatus.message
    : activePreviewResearchCardStatus.message;
  const activeMachinePreview = useMemo(() => {
    if (machinePreview && previewMatchesMachine(machinePreview, activePreviewMachine)) return machinePreview;
    return previewForMachine(researchPayload?.machine_script_previews, activePreviewMachine);
  }, [machinePreview, researchPayload?.machine_script_previews, activePreviewMachine]);
  const previewClaimMap = Array.isArray(activeMachinePreview?.claim_bundle?.claim_map)
    ? activeMachinePreview.claim_bundle.claim_map
    : [];
  const previewFormulaSentences = Array.isArray(activeMachinePreview?.claim_bundle?.formula_sentences)
    ? activeMachinePreview.claim_bundle.formula_sentences
    : [];
  const machinePreviewPassed = machinePreviewPassesAntonGate(activeMachinePreview);
  const activePreviewReviewMessages = machinePreviewReviewMessages(activeMachinePreview);
  const previewEvidenceById = (() => {
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
      source_variant_selection?: any;
      source_slot_hints?: string[];
    }> = {};
    const slots = Array.isArray((activeMachinePreview?.story_plan as any)?.slots)
      ? (activeMachinePreview?.story_plan as any).slots
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
          source_excerpt_id: String(segment?.source_excerpt_id || sourceCandidateForEvidence(segment, activePreviewSourcePackage)?.excerpt_id || ""),
          source_excerpt_hash: String(segment?.source_excerpt_hash || sourceCandidateForEvidence(segment, activePreviewSourcePackage)?.text_hash || ""),
          source_tier: sourceTierForEvidence(segment, activePreviewSourcePackage)?.label,
          source_capture_method: sourceCaptureMethodForEvidence(segment, activePreviewSourcePackage),
          source_variant_selection: sourceVariantSelectionForEvidence(segment, activePreviewSourcePackage),
          source_slot_hints: sourceSlotHintsForEvidence(segment, activePreviewSourcePackage),
        };
      }
    }
    return rows;
  })();
  const previewFormulaRows = previewFormulaSentences.map((sentence: string, index: number) => {
    const expectedSlots = ["original_problem", "engineering_decision", "tradeoff", "reality"];
    const expectedSlot = expectedSlots[index] || "conclusion";
    const claimRows = index < expectedSlots.length
      ? previewClaimMap.filter((row: any) => {
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
    const evidenceRows = evidenceIds.map((id) => ({ id, evidence: previewEvidenceById[id] }));
    return {
      sentence,
      slot: expectedSlot,
      label: index < expectedSlots.length ? ["problem", "decision", "tradeoff", "reality"][index] : "conclusion",
      evidenceRows,
    };
  });

  const handleMachinePreview = async () => {
    const machine = previewMachine || machineRosterLabels[0];
    if (!machine) return;
    setPreviewGenerating(true);
    try {
      const readiness = await checkMachineScriptPreviewReadiness(video.id, machine);
      if (readiness.research_payload) {
        queryClient.setQueryData(["video", video.id], (current: any) => (
          current ? { ...current, research_payload: readiness.research_payload } : current
        ));
      }
      if (!readiness.ready) {
        const message = readiness.summary || readiness.warnings?.[0] || "Single-machine preview readiness check failed.";
        setMachinePreview(previewErrorArtifact(
          readiness.machine || machine,
          message,
          readiness.warnings,
          readiness.scene || 0,
          "readiness_preflight",
          "readiness_preflight",
          "Readiness preflight"
        ));
        setPreviewMachine(readiness.machine || machine);
        invalidateAll();
        toast.error(`Preview blocked: ${message}. Production script unchanged.`);
        return;
      }
      const result = await runMachineScriptPreview(video.id, machine);
      setMachinePreview(result.preview);
      setPreviewMachine(machine);
      if (result.research_payload) {
        queryClient.setQueryData(["video", video.id], (current: any) => (
          current ? { ...current, research_payload: result.research_payload } : current
        ));
      }
      invalidateAll();
      if (machinePreviewPassesAntonGate(result.preview)) {
        toast.success(`${machine} preview generated. Production script unchanged.`);
      } else {
        toast.error(`${machine} preview needs review. Production script unchanged.`);
      }
    } catch (err) {
      const message = (err as Error).message || "Unknown error";
      setMachinePreview(previewErrorArtifact(machine, message));
      toast.error(`Preview failed: ${message}. Production script unchanged.`);
    } finally {
      setPreviewGenerating(false);
    }
  };

  // ---------------------------------------------------------------------------
  // Loading state
  // ---------------------------------------------------------------------------

  if (isLoading) {
    return (
      <div className="flex items-center justify-center py-20">
        <Loader2 size={24} className="animate-spin" style={{ color: "var(--orange)" }} />
        <span className="ml-3 text-sm" style={{ color: "var(--text-secondary)" }}>
          Loading script & voice...
        </span>
      </div>
    );
  }

  // ---------------------------------------------------------------------------
  // Empty state
  // ---------------------------------------------------------------------------

  if (!apiScenes || apiScenes.length === 0) {
    return (
      <GlassCard className="p-12 text-center">
        <Pencil size={32} className="mx-auto mb-3" style={{ color: "var(--text-tertiary)", opacity: 0.4 }} />
        <p className="text-lg font-display mb-2" style={{ color: "var(--text-secondary)" }}>
          Script Not Generated Yet
        </p>
        <p className="text-sm mb-6" style={{ color: "var(--text-tertiary)" }}>
          Research must be approved before script generation can begin. Current stage:{" "}
          <span style={{ color: "var(--turquoise)" }}>{(video.status || "").replace(/_/g, " ")}</span>
        </p>
        {activeRosterGate?.complete_title && activeRosterGate?.passed === false && (
          <div className="mb-5 rounded-xl p-4 text-left" style={{ background: "rgba(255,120,73,.08)", border: "1px solid rgba(255,120,73,.25)" }}>
            <div className="flex items-center gap-2 mb-2" style={{ color: "var(--orange)" }}>
              <AlertCircle size={16} />
              <span className="text-xs font-semibold uppercase tracking-wider">Roster gate blocked scripting</span>
            </div>
            <ul className="space-y-1">
              {(activeRosterGate.warnings || ["Research roster is incomplete."]).map((w: string, i: number) => (
                <li key={i} className="text-sm" style={{ color: "var(--text-secondary)" }}>• {w}</li>
              ))}
            </ul>
          </div>
        )}
        {isMachineDocumentary && verifiedMachineResearchCount > 0 && (
          <div className="mx-auto mb-6 max-w-2xl rounded-xl p-4 text-left" style={{ background: "rgba(255,255,255,.035)", border: "1px solid rgba(255,255,255,.1)" }}>
            <div className="flex items-center gap-2 mb-1">
              <Wand2 size={16} style={{ color: "var(--turquoise)" }} />
              <span className="text-sm font-semibold" style={{ color: "var(--text-primary)" }}>Single-machine test pass</span>
            </div>
            <p className="text-xs mb-3" style={{ color: "var(--text-tertiary)" }}>Generate one isolated paragraph for calibration. This does not create scenes, advance the video, or touch the full script.</p>
            <div className="flex flex-col sm:flex-row gap-2">
              <select
                value={activePreviewMachine}
                onChange={(e) => { setPreviewMachine(e.target.value); setMachinePreview(previewForMachine(researchPayload?.machine_script_previews, e.target.value)); }}
                className="flex-1 rounded-lg px-3 py-2 text-sm"
                style={{ background: "var(--bg-elevated)", color: "var(--text-primary)", border: "1px solid rgba(255,255,255,.12)" }}
              >
                {machineRosterLabels.map((machine: string, i: number) => <option key={machine} value={machine}>{i + 1}. {machine}</option>)}
              </select>
              <button
                onClick={handleMachinePreview}
                disabled={previewGenerating || !activePreviewReady}
                className="inline-flex items-center justify-center gap-2 rounded-lg px-4 py-2 text-sm font-semibold disabled:opacity-50"
                style={{ background: "var(--turquoise)", color: "var(--bg-void)" }}
              >
                {previewGenerating ? <Loader2 size={15} className="animate-spin" /> : <Wand2 size={15} />}
                {previewGenerating ? "Generating one..." : activeMachinePreview ? "Retry this machine" : "Generate one machine"}
              </button>
            </div>
            <div className="mt-2 inline-flex items-center gap-2 rounded-md px-2 py-1 text-[10px] font-semibold uppercase tracking-wider" style={{ background: activePreviewReady ? "rgba(0,230,138,.1)" : "rgba(255,120,73,.1)", color: activePreviewReady ? "var(--green)" : "var(--orange)", border: `1px solid ${activePreviewReady ? "rgba(0,230,138,.2)" : "rgba(255,120,73,.22)"}` }}>
              <ShieldCheck size={12} />
              {activePreviewStatusMessage}
            </div>
            {activePreviewSourcePackage && (
              <div className="mt-2 flex flex-wrap gap-1.5">
                {activePreviewSourceCoverageRows.map((row) => (
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
            {activeMachinePreview && (
              <div className="mt-4 rounded-lg p-4" style={{ background: "rgba(0,0,0,.2)", border: `1px solid ${machinePreviewPassed ? "rgba(74,222,128,.28)" : "rgba(255,120,73,.35)"}` }}>
                <div className="mb-2 flex items-center justify-between gap-2">
                  <span className="text-xs font-semibold" style={{ color: "var(--text-secondary)" }}>{activeMachinePreview.machine}</span>
                  <span className="text-xs font-mono" style={{ color: machinePreviewPassed ? "var(--green)" : "var(--orange)" }}>{activeMachinePreview.word_count} words · {machinePreviewPassed ? "Passed" : "Needs review"}</span>
                </div>
                {activeMachinePreview.claim_bundle?.editorial_thesis && (
                  <div className="mb-3 rounded-md px-3 py-2" style={{ background: "rgba(79,214,198,.07)", border: "1px solid rgba(79,214,198,.18)" }}>
                    <div className="text-[10px] font-semibold uppercase tracking-wider" style={{ color: "var(--turquoise)" }}>Editorial thesis</div>
                    <p className="mt-1 text-sm" style={{ color: "var(--text-primary)" }}>
                      {activeMachinePreview.claim_bundle.editorial_thesis}
                    </p>
                  </div>
                )}
                {!machinePreviewPassed && activePreviewReviewMessages.length > 0 && (
                  <div className="mb-3 rounded-md px-3 py-2" style={{ background: "rgba(255,120,73,.08)", color: "var(--orange)", border: "1px solid rgba(255,120,73,.18)" }}>
                    <div className="text-[10px] font-semibold uppercase tracking-wider">Review reason</div>
                    <ul className="mt-1 space-y-1 text-xs leading-5">
                      {activePreviewReviewMessages.map((message) => (
                        <li key={message}>{message}</li>
                      ))}
                    </ul>
                  </div>
                )}
                {activeMachinePreview.paragraph ? (
                  <p className="text-sm leading-6" style={{ color: "var(--text-primary)" }}>{activeMachinePreview.paragraph}</p>
                ) : (
                  <div className="rounded-md px-3 py-2 text-sm" style={{ background: "rgba(255,120,73,.08)", color: "var(--orange)", border: "1px solid rgba(255,120,73,.18)" }}>
                    Preview stopped before a paragraph was generated.
                  </div>
                )}
                {!activeMachinePreview.quality_audit?.checks?.length && (
                  <div className="mt-3 rounded-md px-3 py-2 text-xs" style={{ background: "rgba(255,120,73,.08)", color: "var(--orange)", border: "1px solid rgba(255,120,73,.18)" }}>
                    Legacy preview missing Anton audit. Regenerate this machine before accepting it.
                  </div>
                )}
                {previewFormulaSentences.length > 0 && (
                  <div className="mt-4 space-y-2">
                    <div className="flex items-center gap-2 text-xs font-semibold uppercase tracking-wider" style={{ color: "var(--text-tertiary)" }}>
                      <ShieldCheck size={13} />
                      Sentence assembly
                    </div>
                    {previewFormulaRows.map((row, index) => (
                      <div key={`formula-${index}`} className="rounded-md px-3 py-2" style={{ background: "rgba(255,255,255,.03)", border: "1px solid rgba(255,255,255,.08)" }}>
                        <span className="mb-1 inline-block rounded px-1.5 py-0.5 text-[10px] font-mono uppercase" style={{ color: index < 4 ? "var(--turquoise)" : "var(--orange)", background: index < 4 ? "rgba(79,214,198,.1)" : "rgba(255,120,73,.1)" }}>
                          {row.label}
                        </span>
                        <p className="text-xs leading-5" style={{ color: "var(--text-secondary)" }}>{row.sentence}</p>
                        {row.evidenceRows.length > 0 && (
                          <div className="mt-2 space-y-2">
                            {row.evidenceRows.map(({ id, evidence }: { id: string; evidence?: any }) => (
                              <div key={id} className="rounded px-2 py-2" style={{ background: "rgba(0,0,0,.14)", border: "1px solid rgba(255,255,255,.06)" }}>
                                <p className="truncate text-[10px]" style={{ color: "var(--text-tertiary)" }}>
                                  {[evidence?.source_title || id, evidence?.source_tier, evidence?.source_capture_method, sourceVariantSelectionLabel(evidence?.source_variant_selection), Array.isArray(evidence?.source_slot_hints) && evidence.source_slot_hints.length ? `hints ${evidence.source_slot_hints.join(", ")}` : "", evidence?.source_excerpt_id || evidence?.locator, evidence?.source_excerpt_hash ? `hash ${String(evidence.source_excerpt_hash).slice(0, 8)}` : ""].filter(Boolean).join(" · ")}
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
                {!!activeMachinePreview.quality_audit?.checks?.length && (
                  <div className="mt-4 space-y-2">
                    <div className="flex items-center gap-2 text-xs font-semibold uppercase tracking-wider" style={{ color: activeMachinePreview.quality_audit.passed ? "var(--green)" : "var(--orange)" }}>
                      <ShieldCheck size={13} />
                      Anton quality audit
                    </div>
                    <div className="grid gap-2 sm:grid-cols-2">
                      {activeMachinePreview.quality_audit.checks.map((check, index) => (
                        <div key={`${check.name || "audit"}-${index}`} className="rounded-md px-3 py-2" style={{ background: check.passed ? "rgba(0,230,138,.07)" : "rgba(255,120,73,.08)", border: `1px solid ${check.passed ? "rgba(0,230,138,.16)" : "rgba(255,120,73,.2)"}` }}>
                          <div className="text-[10px] font-semibold uppercase tracking-wider" style={{ color: check.passed ? "var(--green)" : "var(--orange)" }}>{check.label || check.name}{check.advisory ? " · advisory" : ""}</div>
                          {check.detail && <p className="mt-1 text-[11px] leading-4" style={{ color: "var(--text-secondary)" }}>{check.detail}</p>}
                        </div>
                      ))}
                    </div>
                  </div>
                )}
                {previewClaimMap.length > 0 && (
                  <div className="mt-4 space-y-2">
                    <div className="flex items-center gap-2 text-xs font-semibold uppercase tracking-wider" style={{ color: "var(--text-tertiary)" }}>
                      <ShieldCheck size={13} />
                      Evidence map
                    </div>
                    {previewClaimMap.slice(0, 8).map((row, index) => {
                      const evidenceIds = Array.isArray(row.used_evidence_ids)
                        ? row.used_evidence_ids
                        : Array.isArray(row.evidence_ids) ? row.evidence_ids : [];
                      const evidenceRows = evidenceIds
                        .map((id) => ({ id, evidence: previewEvidenceById[id] }))
                        .filter((item: { id: string; evidence?: any }) => item.id);
                      return (
                        <div key={`${row.slot || "slot"}-${index}`} className="rounded-md px-3 py-2" style={{ background: "rgba(255,255,255,.035)", border: "1px solid rgba(255,255,255,.08)" }}>
                          <div className="mb-1 flex flex-wrap items-center gap-2">
                            <span className="rounded px-1.5 py-0.5 text-[10px] font-mono uppercase" style={{ color: "var(--turquoise)", background: "rgba(79,214,198,.1)" }}>{row.slot || "slot"}</span>
                            <span className="text-[10px] font-mono" style={{ color: "var(--text-tertiary)" }}>{evidenceIds.join(", ")}</span>
                          </div>
                          <p className="text-xs leading-5" style={{ color: "var(--text-secondary)" }}>{row.span}</p>
                          {evidenceRows.length > 0 && (
                            <div className="mt-2 space-y-2">
                              {evidenceRows.map(({ id, evidence }: { id: string; evidence?: any }) => (
                                <div key={id} className="rounded px-2 py-2" style={{ background: "rgba(0,0,0,.14)", border: "1px solid rgba(255,255,255,.06)" }}>
                                  <p className="truncate text-[10px]" style={{ color: "var(--text-tertiary)" }}>
                                    {[evidence?.source_title || id, evidence?.source_tier, evidence?.source_capture_method, sourceVariantSelectionLabel(evidence?.source_variant_selection), Array.isArray(evidence?.source_slot_hints) && evidence.source_slot_hints.length ? `hints ${evidence.source_slot_hints.join(", ")}` : "", evidence?.source_excerpt_id || evidence?.locator, evidence?.source_excerpt_hash ? `hash ${String(evidence.source_excerpt_hash).slice(0, 8)}` : ""].filter(Boolean).join(" · ")}
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
              </div>
            )}
          </div>
        )}
        <button
          onClick={handleRegenerateScript}
          disabled={regeneratingScript || scriptTaskRunning || scriptGenerationBlockedByRoster}
          className="inline-flex items-center justify-center gap-2 px-6 py-3 rounded-xl text-base font-semibold font-body transition-all hover:brightness-110 active:scale-[0.98] disabled:opacity-50"
          style={{ background: "var(--turquoise)", color: "var(--bg-void)" }}
        >
          {regeneratingScript || scriptTaskRunning ? (
            <Loader2 size={18} className="animate-spin" />
          ) : (
            <Pencil size={18} />
          )}
          {scriptTaskRunning
            ? scriptTaskMessage || "Generating Script..."
            : regeneratingScript
              ? "Starting..."
              : "Generate Script"}
        </button>
      </GlassCard>
    );
  }

  // ---------------------------------------------------------------------------
  // Render
  // ---------------------------------------------------------------------------

  const isVoiceBusy = generatingVoiceAll || generatingVoiceScene !== null || voiceTaskRunning;

  // ---- Script pipeline stepper ----
  const scriptDone = scenesWithScript === totalScenes && totalScenes > 0;
  const voiceDone = voiceSkipped || (scenesWithVoice === totalScenes && totalScenes > 0);

  return (
    <div className="space-y-6 pb-24">
      {isMachineDocumentary && (
        <GlassCard className="p-5">
          <div className="flex items-center gap-3">
            <ShieldCheck size={18} style={{ color: scriptHold?.passed ? "var(--green)" : "var(--orange)" }} />
            <div>
              <h3 className="text-sm font-semibold" style={{ color: "var(--text-primary)" }}>Machine Script Hold</h3>
              <p className="text-xs" style={{ color: "var(--text-tertiary)" }}>One locked machine, one researched paragraph, one scene.</p>
            </div>
            <span className="ml-auto text-xs font-mono font-semibold" style={{ color: scriptHold?.passed ? "var(--green)" : "var(--orange)" }}>
              {scriptHold?.units?.filter((unit: any) => unit?.passed).length || 0}/{machineRoster.length} machines scripted
            </span>
          </div>
          <div className="mt-3 h-2 rounded-full overflow-hidden" style={{ background: "rgba(255,255,255,.08)" }}>
            <div className="h-full rounded-full transition-all" style={{ width: `${machineRoster.length ? Math.round(((scriptHold?.units?.filter((unit: any) => unit?.passed).length || 0) / machineRoster.length) * 100) : 0}%`, background: scriptHold?.passed ? "var(--green)" : "var(--orange)" }} />
          </div>
        </GlassCard>
      )}
      {/* Top action bar */}
      <div className="rounded-xl px-4 py-3 mb-4" style={{ background: "rgba(255,255,255,0.03)", border: "1px solid rgba(255,255,255,0.08)" }}>
        <div className="flex items-center justify-between gap-3 flex-wrap">
          <div className="flex items-center gap-4 text-[10px] font-mono" style={{ color: "var(--text-tertiary)" }}>
            <span>Script {scenesWithScript}/{totalScenes}</span>
            <span>Voice {voiceSkipped ? "off" : `${scenesWithVoice}/${totalScenes}`}</span>
          </div>
          <button onClick={handleAdvanceStage} disabled={advancing}
            className="px-3 py-1.5 rounded-lg text-[10px] font-semibold inline-flex items-center gap-1 disabled:opacity-50 transition-all hover:brightness-110"
            style={{ background: "var(--turquoise)", color: "var(--bg-void)" }}>
            {advancing ? <Loader2 size={12} className="animate-spin" /> : null}
            Advance Stage <ChevronRight size={12} />
          </button>
        </div>
      </div>

      {activeRosterGate && (
        <div className="rounded-xl p-4" style={{ background: activeRosterGate.passed ? "rgba(0,230,138,.06)" : "rgba(255,120,73,.08)", border: `1px solid ${activeRosterGate.passed ? "rgba(0,230,138,.22)" : "rgba(255,120,73,.25)"}` }}>
          <div className="flex items-start justify-between gap-3 mb-2">
            <div className="flex items-center gap-2" style={{ color: activeRosterGate.passed ? "var(--green)" : "var(--orange)" }}>
              {activeRosterGate.passed ? <ShieldCheck size={16} /> : <AlertCircle size={16} />}
              <span className="text-xs font-semibold uppercase tracking-wider">Script roster gate</span>
            </div>
            <span className="text-[10px] font-mono" style={{ color: "var(--text-tertiary)" }}>
              {activeRosterGate.roster_count || 0} locked item(s)
            </span>
          </div>
          {activeRosterGate.passed ? (
            <p className="text-sm" style={{ color: "var(--text-secondary)" }}>Script matches the locked research roster.</p>
          ) : (
            <ul className="space-y-1">
              {(activeRosterGate.warnings || ["Roster validation failed."]).map((w: string, i: number) => (
                <li key={i} className="text-sm" style={{ color: "var(--text-secondary)" }}>• {w}</li>
              ))}
            </ul>
          )}
        </div>
      )}

      {/* Script System Prompt */}
      <SystemPromptEditor
        label="Script System Prompt"
        currentValue={video.script_system_prompt}
        onSave={async (text) => {
          await updateVideo(video.id, { script_system_prompt: text || null });
          queryClient.invalidateQueries({ queryKey: ["video", video.id] });
        }}
        onReset={async () => {
          const res = await getDefaultScriptPrompt();
          await updateVideo(video.id, { script_system_prompt: null });
          queryClient.invalidateQueries({ queryKey: ["video", video.id] });
          return res.prompt;
        }}
      />

      {/* Script Pipeline Steps */}
      <div
        className="rounded-xl p-4"
        style={{ background: "rgba(255, 120, 73, 0.04)", border: "1px solid rgba(255, 120, 73, 0.12)" }}
      >
        <div className="flex items-center gap-2 mb-3">
          <span className="text-[10px] uppercase tracking-wider font-semibold" style={{ color: "var(--orange)" }}>
            Script Pipeline
          </span>
        </div>
        <div className="flex items-center gap-0">
          {[
            { label: "Generate Script", done: scriptDone, count: `${scenesWithScript}/${totalScenes}` },
            { label: voiceSkipped ? "Voice (off)" : "Generate Voice", done: voiceDone, count: voiceSkipped ? "Skipped" : `${scenesWithVoice}/${totalScenes}` },
            { label: "Approve", done: approved, count: approved ? "Done" : "Pending" },
          ].map((step, i, arr) => {
            const isNext = !step.done && (i === 0 || arr[i - 1].done);
            return (
              <div key={step.label} className="flex items-center gap-0 flex-1">
                <div className="flex flex-col items-center flex-1">
                  <div
                    className="w-7 h-7 rounded-full flex items-center justify-center text-[10px] font-bold mb-1"
                    style={{
                      background: step.done ? "var(--green)" : isNext ? "var(--orange)" : "rgba(255,255,255,0.06)",
                      color: step.done || isNext ? "var(--bg-void)" : "var(--text-tertiary)",
                      border: isNext ? "2px solid var(--orange)" : "none",
                    }}
                  >
                    {step.done ? "✓" : i + 1}
                  </div>
                  <span className="text-[9px] font-medium" style={{ color: step.done ? "var(--green)" : isNext ? "var(--orange)" : "var(--text-tertiary)" }}>
                    {step.label}
                  </span>
                  <span className="text-[8px] font-mono" style={{ color: "var(--text-tertiary)" }}>
                    {step.count}
                  </span>
                </div>
                {i < arr.length - 1 && (
                  <div className="w-8 h-px mx-1" style={{ background: step.done ? "var(--green)" : "rgba(255,255,255,0.1)" }} />
                )}
              </div>
            );
          })}
        </div>
        {/* Next action CTA */}
        {(() => {
          if (!scriptDone) return (
            <button
              onClick={handleRegenerateScript}
              disabled={regeneratingScript || scriptTaskRunning || scriptGenerationBlockedByRoster}
              className="mt-3 w-full inline-flex items-center justify-center gap-2 rounded-lg px-4 py-2.5 text-xs font-semibold transition-all disabled:opacity-50"
              style={{ background: "var(--orange)", color: "var(--bg-void)" }}
            >
              {(regeneratingScript || scriptTaskRunning) ? <Loader2 size={14} className="animate-spin" /> : <Pencil size={14} />}
              {scriptTaskRunning ? scriptTaskMessage || "Generating..." : "Step 1: Generate Script"}
            </button>
          );
          if (!voiceDone) return (
            <>
              <button
                onClick={handleGenerateAllVoice}
                disabled={isVoiceBusy}
                className="mt-3 w-full inline-flex items-center justify-center gap-2 rounded-lg px-4 py-2.5 text-xs font-semibold transition-all disabled:opacity-50"
                style={{ background: "var(--orange)", color: "var(--bg-void)" }}
              >
                {isVoiceBusy ? <Loader2 size={14} className="animate-spin" /> : <Mic size={14} />}
                {voiceTaskRunning ? voiceTaskMessage || "Generating..." : "Step 2: Generate Voice"}
              </button>
              {/* Re-roll the script before spending on voice (prompt/profile changes). */}
              <button
                onClick={handleRegenerateScript}
                disabled={regeneratingScript || scriptTaskRunning || isVoiceBusy || scriptGenerationBlockedByRoster}
                className="mt-2 w-full inline-flex items-center justify-center gap-2 rounded-lg px-4 py-2 text-xs font-medium transition-all disabled:opacity-50"
                style={{ background: "transparent", border: "1px solid var(--orange)", color: "var(--orange)" }}
              >
                {(regeneratingScript || scriptTaskRunning) ? <Loader2 size={14} className="animate-spin" /> : <Pencil size={14} />}
                {scriptTaskRunning ? scriptTaskMessage || "Regenerating…" : "Regenerate script"}
              </button>
            </>
          );
          if (!approved) return (
            <>
              <button
                onClick={handleApprove}
                disabled={approving || !allReady}
                className="mt-3 w-full inline-flex items-center justify-center gap-2 rounded-lg px-4 py-2.5 text-xs font-semibold transition-all disabled:opacity-50"
                style={{ background: "var(--green)", color: "var(--bg-void)" }}
              >
                {approving ? <Loader2 size={14} className="animate-spin" /> : <CheckCircle size={14} />}
                Step 3: Approve Script & Voice
              </button>
              {/* Go back and rewrite the script (e.g. after changing the style or scene rules). */}
              <button
                onClick={handleRegenerateScript}
                disabled={regeneratingScript || scriptTaskRunning || scriptGenerationBlockedByRoster}
                className="mt-2 w-full inline-flex items-center justify-center gap-2 rounded-lg px-4 py-2 text-xs font-medium transition-all disabled:opacity-50"
                style={{ background: "transparent", border: "1px solid var(--orange)", color: "var(--orange)" }}
              >
                {(regeneratingScript || scriptTaskRunning) ? <Loader2 size={14} className="animate-spin" /> : <Pencil size={14} />}
                {scriptTaskRunning ? scriptTaskMessage || "Regenerating…" : "Regenerate script"}
              </button>
            </>
          );
          return (
            <p className="mt-3 text-[10px] text-center" style={{ color: "var(--green)" }}>
              ✓ Script pipeline complete
            </p>
          );
        })()}
      </div>

      <div className="grid grid-cols-1 lg:grid-cols-[1fr_280px] gap-6">
        {/* ============================================================= */}
        {/* Main content area                                              */}
        {/* ============================================================= */}
        <div className="space-y-4">
          {Object.entries(actGroups).map(([actNum, actScenes]) => {
            const isCollapsed = collapsedActs[Number(actNum)];
            const actWordCount = actScenes.reduce(
              (sum, s) => sum + s.narrationText.split(/\s+/).filter(Boolean).length,
              0,
            );

            return (
              <div key={actNum}>
                {/* Act header */}
                <button
                  onClick={() => toggleAct(Number(actNum))}
                  className="flex items-center gap-3 w-full mb-3 group"
                >
                  <div className="flex-1 h-px" style={{ background: "var(--orange)", opacity: 0.3 }} />
                  <div
                    className="flex items-center gap-2 px-3 py-1 rounded-full transition-all"
                    style={{ background: isCollapsed ? "rgba(255, 120, 73, 0.1)" : "transparent" }}
                  >
                    {isCollapsed ? (
                      <ChevronRight size={14} style={{ color: "var(--orange)" }} />
                    ) : (
                      <ChevronDown size={14} style={{ color: "var(--orange)" }} />
                    )}
                    <span
                      className="text-xs font-semibold uppercase tracking-wider"
                      style={{ color: "var(--orange)" }}
                    >
                      Act {actNum}
                    </span>
                    <span className="text-[10px] font-mono" style={{ color: "var(--text-tertiary)" }}>
                      {actScenes.length} scenes &middot; {actWordCount} words
                    </span>
                  </div>
                  <div className="flex-1 h-px" style={{ background: "var(--orange)", opacity: 0.3 }} />
                </button>

                {!isCollapsed && (
                  <div className="space-y-3">
                    {actScenes.map((scene) => {
                      const isExpanded = expandedScenes.has(scene.sceneNumber);
                      const hasVoice = sceneHasVoice(scene);
                      const isPlayingThis = false;
                      const isGeneratingThisVoice = generatingVoiceScene === scene.sceneNumber;
                      // Per-scene word count. The wand rewrite enforces 95-120
                      // words per scene (routes/videos.py rewrite contract), but
                      // without a visible count over-cap scenes are invisible
                      // until the voice runs long.
                      const wordCount = scene.narrationText.split(/\s+/).filter(Boolean).length;
                      const overCap = wordCount > 120;
                      const rosterEntry = machineRoster[scene.sceneNumber - 1];
                      const holdUnit = scriptHold?.units?.find((unit: any) => Number(unit?.scene) === scene.sceneNumber);
                      const machineName = holdUnit?.machine
                        || (typeof rosterEntry === "string" ? rosterEntry : rosterEntry?.machine || rosterEntry?.unit || rosterEntry?.title)
                        || null;

                      return (
                        <GlassCard
                          key={scene.sceneNumber}
                          className="p-4"
                          style={{
                            borderLeftWidth: 3,
                            borderLeftColor: hasVoice
                              ? "var(--green)"
                              : scene.imageGenerated
                                ? "var(--turquoise)"
                                : "var(--orange)",
                          }}
                        >
                          {/* ---- Scene header ---- */}
                          <div className="flex items-center gap-2 mb-2">
                            <SegmentBadge
                              label={`S-${String(scene.sceneNumber).padStart(2, "0")}`}
                              color={scene.imageGenerated ? undefined : "var(--orange)"}
                            />
                            {isMachineDocumentary && machineName && (
                              <span className="text-sm font-semibold truncate max-w-[340px]" style={{ color: "var(--text-primary)" }} title={machineName}>
                                {machineName}
                              </span>
                            )}

                            {/* Status badges */}
                            <ScriptStatusBadge status={scene.scriptStatus} />
                            <VoiceStatusBadge status={scene.voiceStatus} />

                            {/* Word count — bold so out-of-cap scenes read at a glance */}
                            <span
                              className="text-[11px] font-mono font-bold px-1.5 py-0.5 rounded"
                              style={
                                overCap
                                  ? { background: "rgba(255, 120, 73, 0.15)", color: "var(--orange)" }
                                  : { color: "var(--text-secondary)" }
                              }
                              title={
                                overCap
                                  ? "Over the 120-word scene cap — wand-rewrite this scene to shorten it"
                                  : "Scene word count (target 95-120)"
                              }
                            >
                              {wordCount} words{overCap ? " · OVER CAP" : ""}
                            </span>

                            <div className="flex-1" />

                            {/* Tone badge */}
                            {scene.tone && (
                              <span
                                className="text-[9px] font-mono px-1.5 py-0.5 rounded"
                                style={{ background: "rgba(255,255,255,0.06)", color: "var(--text-tertiary)" }}
                              >
                                {scene.tone}
                              </span>
                            )}

                            {/* Expand/collapse toggle */}
                            <button
                              onClick={() => toggleExpand(scene.sceneNumber)}
                              disabled={loadingSegments.has(scene.sceneNumber)}
                              title={isExpanded ? "Collapse to unified text" : "Expand into timed sentence segments"}
                              className="flex items-center gap-1 px-2 py-1 rounded-lg text-[10px] font-medium transition-all"
                              style={{
                                background: isExpanded ? "var(--turquoise-dim)" : "transparent",
                                color: isExpanded ? "var(--turquoise)" : "var(--text-tertiary)",
                                border: `1px solid ${isExpanded ? "var(--turquoise-dim)" : "transparent"}`,
                              }}
                            >
                              {loadingSegments.has(scene.sceneNumber) ? (
                                <Loader2 size={11} className="animate-spin" />
                              ) : (
                                <Layers size={11} />
                              )}
                              {isExpanded ? "Collapse" : "Expand"}
                              <span className="font-mono">{scene.sentences.length}</span>
                            </button>

                            {!isMachineDocumentary && (
                              <>
                                <button
                                  onClick={() => mergeSceneUp(scene.sceneNumber)}
                                  title="Merge into scene above"
                                  className="p-1 rounded transition-colors hover:bg-[var(--bg-surface)]"
                                  style={{ color: "var(--text-tertiary)" }}
                                >
                                  <Merge size={12} />
                                </button>
                                <button
                                  onClick={() => addSceneAfter(scene.sceneNumber)}
                                  title="Add scene below"
                                  className="p-1 rounded transition-colors hover:bg-[var(--bg-surface)]"
                                  style={{ color: "var(--text-tertiary)" }}
                                >
                                  <Plus size={12} />
                                </button>
                              </>
                            )}
                            <button
                              onClick={() => handleRewriteScene(scene.sceneNumber)}
                              disabled={rewritingScene !== null}
                              title="AI-rewrite this scene from the research facts (clears its voice)"
                              className="p-1 rounded transition-colors hover:bg-[var(--bg-surface)]"
                              style={{ color: rewritingScene === scene.sceneNumber ? "var(--orange)" : "var(--text-tertiary)" }}
                            >
                              {rewritingScene === scene.sceneNumber ? (
                                <Loader2 size={12} className="animate-spin" />
                              ) : (
                                <Wand2 size={12} />
                              )}
                            </button>
                            {!isMachineDocumentary && (
                              <button
                                onClick={() => handleDeleteScene(scene.sceneNumber)}
                                disabled={deletingScene === scene.sceneNumber}
                                title="Delete scene"
                                className="p-1 rounded transition-colors hover:bg-[var(--bg-surface)]"
                                style={{ color: "var(--text-tertiary)" }}
                                onMouseEnter={(e) => {
                                  e.currentTarget.style.color = "var(--orange)";
                                }}
                                onMouseLeave={(e) => {
                                  e.currentTarget.style.color = "var(--text-tertiary)";
                                }}
                              >
                                {deletingScene === scene.sceneNumber ? (
                                  <Loader2 size={12} className="animate-spin" />
                                ) : (
                                  <Trash2 size={12} />
                                )}
                              </button>
                            )}
                          </div>

                          {/* ---- COLLAPSED: Unified text view ---- */}
                          {!isExpanded && (
                            <div className="relative">
                              <textarea
                                value={scene.displayText}
                                onChange={(e) => updateNarration(scene.sceneNumber, e.target.value)}
                                rows={Math.max(2, Math.ceil(scene.displayText.length / 100))}
                                className="w-full text-sm leading-relaxed resize-none outline-none rounded-lg px-3 py-2 transition-all"
                                style={{
                                  color: "var(--text-primary)",
                                  background: "transparent",
                                  border: "1px solid transparent",
                                }}
                                onFocus={(e) => {
                                  e.target.style.background = "var(--bg-elevated)";
                                  e.target.style.borderColor = "var(--orange)";
                                }}
                                onBlur={(e) => {
                                  e.target.style.background = "transparent";
                                  e.target.style.borderColor = "transparent";
                                  handleNarrationBlur(scene.sceneNumber, scene.narrationText);
                                }}
                              />
                              {savingScene === scene.sceneNumber && (
                                <Loader2
                                  size={12}
                                  className="animate-spin absolute top-2 right-2"
                                  style={{ color: "var(--turquoise)" }}
                                />
                              )}
                              {savedScene === scene.sceneNumber && (
                                <span
                                  className="absolute top-2 right-2 text-[10px] font-medium"
                                  style={{ color: "var(--green)" }}
                                >
                                  Saved
                                </span>
                              )}
                            </div>
                          )}

                          {/* ---- EXPANDED: Individual sentence cards ---- */}
                          <AnimatePresence>
                            {isExpanded && (
                              <motion.div
                                initial={{ opacity: 0, height: 0 }}
                                animate={{ opacity: 1, height: "auto" }}
                                exit={{ opacity: 0, height: 0 }}
                                transition={{ duration: 0.3 }}
                                className="space-y-2"
                              >
                                {scene.sentences.map((sent, sentIdx) => (
                                  <div
                                    key={sentIdx}
                                    className="rounded-xl p-3 transition-all"
                                    style={{
                                      background: "rgba(255,255,255,0.02)",
                                      border: "1px solid rgba(255,255,255,0.05)",
                                    }}
                                  >
                                    <div className="flex items-center gap-2 mb-1.5">
                                      <span
                                        className="text-[9px] font-mono font-medium px-1.5 py-0.5 rounded"
                                        style={{ background: "var(--orange-dim)", color: "var(--orange)" }}
                                      >
                                        {sentIdx + 1}/{scene.sentences.length}
                                      </span>
                                      {sent.durationSeconds != null && (
                                        <span
                                          className="text-[9px] font-mono px-1.5 py-0.5 rounded"
                                          style={{ background: "rgba(0, 188, 212, 0.1)", color: "var(--turquoise)" }}
                                          title={sent.cumulativeStart != null ? `Starts at ${sent.cumulativeStart.toFixed(1)}s` : undefined}
                                        >
                                          {sent.durationSeconds.toFixed(1)}s
                                        </span>
                                      )}
                                      {sent.cumulativeStart != null && (
                                        <span
                                          className="text-[8px] font-mono"
                                          style={{ color: "var(--text-tertiary)" }}
                                        >
                                          @{sent.cumulativeStart.toFixed(1)}s
                                        </span>
                                      )}
                                      <div className="flex-1" />
                                      <button
                                        onClick={() => mergeSentenceUp(scene.sceneNumber, sentIdx)}
                                        title="Merge up"
                                        className="p-0.5 rounded hover:bg-[var(--bg-surface)]"
                                        style={{ color: "var(--text-tertiary)" }}
                                      >
                                        <Merge size={10} />
                                      </button>
                                      <button
                                        onClick={() => addSentenceAfter(scene.sceneNumber, sentIdx)}
                                        title="Add below"
                                        className="p-0.5 rounded hover:bg-[var(--bg-surface)]"
                                        style={{ color: "var(--text-tertiary)" }}
                                      >
                                        <Plus size={10} />
                                      </button>
                                      <button
                                        onClick={() => deleteSentence(scene.sceneNumber, sentIdx)}
                                        title="Delete"
                                        className="p-0.5 rounded hover:bg-[var(--bg-surface)]"
                                        style={{ color: "var(--text-tertiary)" }}
                                      >
                                        <Trash2 size={10} />
                                      </button>
                                    </div>

                                    <textarea
                                      value={sent.text}
                                      onChange={(e) => updateSentence(scene.sceneNumber, sentIdx, e.target.value)}
                                      rows={Math.max(1, Math.ceil(sent.text.length / 90))}
                                      className="w-full text-sm leading-relaxed resize-none outline-none rounded-lg px-2 py-1 transition-all"
                                      style={{
                                        color: "var(--text-primary)",
                                        background: "transparent",
                                        border: "1px solid transparent",
                                      }}
                                      onFocus={(e) => {
                                        e.target.style.background = "var(--bg-elevated)";
                                        e.target.style.borderColor = "var(--turquoise)";
                                      }}
                                      onBlur={(e) => {
                                        e.target.style.background = "transparent";
                                        e.target.style.borderColor = "transparent";
                                      }}
                                    />

                                    {/* SFX per sentence */}
                                    <div className="flex items-center gap-2 mt-2 flex-wrap">
                                      <Volume2 size={10} style={{ color: "var(--gold)", opacity: 0.5 }} />
                                      {(["none", "library", "elevenlabs", "custom"] as const).map((mode) => {
                                        const labels = {
                                          none: "None",
                                          library: "Library",
                                          elevenlabs: "ElevenLabs",
                                          custom: "AI Prompt",
                                        };
                                        const icons = {
                                          none: null,
                                          library: <Library size={9} />,
                                          elevenlabs: <Mic size={9} />,
                                          custom: <Wand2 size={9} />,
                                        };
                                        const colors = {
                                          none: "var(--text-tertiary)",
                                          library: "var(--gold)",
                                          elevenlabs: "var(--green)",
                                          custom: "var(--purple)",
                                        };
                                        const isActive = sent.sfxMode === mode;
                                        return (
                                          <button
                                            key={mode}
                                            onClick={() => updateSfxMode(scene.sceneNumber, sentIdx, mode)}
                                            className="flex items-center gap-1 px-2 py-0.5 rounded-full text-[9px] font-medium transition-all"
                                            style={{
                                              background: isActive ? `${colors[mode]}15` : "transparent",
                                              color: isActive ? colors[mode] : "var(--text-tertiary)",
                                              border: `1px solid ${isActive ? `${colors[mode]}30` : "transparent"}`,
                                            }}
                                          >
                                            {icons[mode]}
                                            {labels[mode]}
                                          </button>
                                        );
                                      })}
                                    </div>

                                    {sent.sfxMode === "library" && (
                                      <div className="flex items-center gap-2 mt-1.5">
                                        <select
                                          value={sent.sfxLibraryValue}
                                          onChange={(e) =>
                                            updateSfxLibrary(scene.sceneNumber, sentIdx, e.target.value)
                                          }
                                          className="text-[10px] font-mono px-2 py-1 rounded-lg outline-none flex-1"
                                          style={{
                                            background: "var(--bg-elevated)",
                                            color: "var(--text-secondary)",
                                            border: "1px solid var(--border-subtle)",
                                          }}
                                        >
                                          <option value="">Select sound...</option>
                                          {SFX_LIBRARY.map((sfx) => (
                                            <option key={sfx.value} value={sfx.value}>
                                              {sfx.label}
                                            </option>
                                          ))}
                                        </select>
                                        {sent.sfxLibraryValue && (
                                          <button
                                            className="w-5 h-5 rounded-full flex items-center justify-center"
                                            style={{ background: "var(--green)", color: "var(--bg-void)" }}
                                          >
                                            <Play size={8} className="ml-px" />
                                          </button>
                                        )}
                                      </div>
                                    )}

                                    {sent.sfxMode === "elevenlabs" && (
                                      <div className="mt-1.5 flex items-start gap-2">
                                        <Mic size={11} style={{ color: "var(--green)", marginTop: 5 }} />
                                        <div className="flex-1">
                                          <textarea
                                            value={sent.sfxCustomPrompt}
                                            onChange={(e) =>
                                              updateSfxPrompt(scene.sceneNumber, sentIdx, e.target.value)
                                            }
                                            placeholder="Describe the sound for ElevenLabs to generate..."
                                            rows={2}
                                            className="w-full text-[10px] font-mono outline-none rounded-lg px-2 py-1.5 resize-none transition-all"
                                            style={{
                                              color: "var(--text-secondary)",
                                              background: "var(--bg-elevated)",
                                              border: "1px solid rgba(0, 230, 138, 0.15)",
                                            }}
                                            onFocus={(e) => {
                                              e.target.style.borderColor = "var(--green)";
                                            }}
                                            onBlur={(e) => {
                                              e.target.style.borderColor = "rgba(0, 230, 138, 0.15)";
                                            }}
                                          />
                                          <div className="flex items-center gap-2 mt-1">
                                            <button
                                              className="text-[9px] font-medium px-2 py-0.5 rounded-lg"
                                              style={{ background: "var(--green)", color: "var(--bg-void)" }}
                                            >
                                              Generate SFX
                                            </button>
                                            <span
                                              className="text-[9px] font-mono"
                                              style={{ color: "var(--text-tertiary)" }}
                                            >
                                              ~$0.03
                                            </span>
                                          </div>
                                        </div>
                                      </div>
                                    )}

                                    {sent.sfxMode === "custom" && (
                                      <div className="mt-1.5 flex items-start gap-2">
                                        <Wand2 size={11} style={{ color: "var(--purple)", marginTop: 5 }} />
                                        <textarea
                                          value={sent.sfxCustomPrompt}
                                          onChange={(e) =>
                                            updateSfxPrompt(scene.sceneNumber, sentIdx, e.target.value)
                                          }
                                          placeholder="Describe the SFX for AI generation..."
                                          rows={2}
                                          className="flex-1 text-[10px] font-mono outline-none rounded-lg px-2 py-1.5 resize-none transition-all"
                                          style={{
                                            color: "var(--text-secondary)",
                                            background: "var(--bg-elevated)",
                                            border: "1px solid var(--purple-dim)",
                                          }}
                                          onFocus={(e) => {
                                            e.target.style.borderColor = "var(--purple)";
                                          }}
                                          onBlur={(e) => {
                                            e.target.style.borderColor = "var(--purple-dim)";
                                          }}
                                        />
                                      </div>
                                    )}

                                  </div>
                                ))}
                              </motion.div>
                            )}
                          </AnimatePresence>

                          {/* ---- Voice status (generation controls only, playback moved to Storyboard tab) ---- */}
                          <div
                            className="mt-3 pt-3 flex items-center gap-3 flex-wrap"
                            style={{ borderTop: "1px solid rgba(255,255,255,0.06)" }}
                          >
                            <span
                              className="text-[10px] font-mono px-2 py-0.5 rounded-full"
                              style={{
                                color: hasVoice ? "var(--green)" : "var(--text-tertiary)",
                                background: hasVoice ? "rgba(0, 200, 83, 0.08)" : "rgba(255,255,255,0.04)",
                                border: `1px solid ${hasVoice ? "rgba(0, 200, 83, 0.2)" : "rgba(255,255,255,0.06)"}`,
                              }}
                            >
                              {hasVoice ? "Voice Ready" : "No Voice"}
                            </span>
                            {hasVoice && (
                              <button
                                onClick={() => playSceneVoice(scene.sceneNumber)}
                                title={playingSceneVoice === scene.sceneNumber ? "Stop playback" : "Listen to this scene's voiceover"}
                                className="flex items-center gap-1.5 text-[10px] font-medium px-2 py-1 rounded-lg transition-all hover:brightness-110"
                                style={{
                                  background: playingSceneVoice === scene.sceneNumber ? "var(--green)" : "rgba(0, 200, 83, 0.12)",
                                  color: playingSceneVoice === scene.sceneNumber ? "var(--bg-void)" : "var(--green)",
                                  border: "1px solid rgba(0, 200, 83, 0.3)",
                                }}
                              >
                                {playingSceneVoice === scene.sceneNumber ? <Square size={10} /> : <Play size={10} className="ml-px" />}
                                {playingSceneVoice === scene.sceneNumber ? "Stop" : "Play Voice"}
                              </button>
                            )}
                            <span
                              className="text-[10px] font-mono shrink-0"
                              style={{ color: "var(--text-tertiary)" }}
                            >
                              {Math.round((scene.narrationText.split(/\s+/).filter(Boolean).length || 0) / 2.5)}s
                            </span>
                            <button
                              onClick={() => handleGenerateSceneVoice(scene.sceneNumber)}
                              disabled={isVoiceBusy}
                              className="text-[10px] font-medium px-2 py-1 rounded-lg transition-all hover:brightness-110 disabled:opacity-40"
                              style={{
                                border: hasVoice ? "1px solid var(--turquoise)" : "none",
                                color: hasVoice ? "var(--turquoise)" : "var(--bg-void)",
                                background: hasVoice ? "transparent" : "var(--turquoise)",
                              }}
                            >
                              {isGeneratingThisVoice || (voiceTaskRunning && generatingVoiceScene === scene.sceneNumber)
                                ? (voiceTaskMessage || "Generating...")
                                : hasVoice ? "Regenerate Voice" : "Generate Voice"}
                            </button>
                          </div>

                          {/* Segment Editor — save segment text edits to backend */}
                          {isExpanded && <SegmentEditor videoId={video.id} sceneNumber={scene.sceneNumber} />}

                          {/* Sources + metadata */}
                          <div className="flex items-center gap-2 mt-2 flex-wrap">
                            {scene.sources?.map((src, srcIdx) => (
                              <span
                                key={srcIdx}
                                className="text-[10px] font-mono px-2 py-0.5 rounded"
                                style={{ background: "var(--yellow-dim)", color: "var(--yellow)" }}
                              >
                                [{src}]
                              </span>
                            ))}
                            {/* Visual style/composition hidden — internal pipeline metadata */}
                          </div>
                        </GlassCard>
                      );
                    })}
                  </div>
                )}
              </div>
            );
          })}
        </div>

        {/* ============================================================= */}
        {/* Sidebar                                                        */}
        {/* ============================================================= */}
        <div className="space-y-4">
          {/* Script details */}
          <GlassCard className="p-5">
            <h3
              className="text-xs font-semibold uppercase tracking-wider mb-3"
              style={{ color: "var(--text-secondary)" }}
            >
              Script &amp; Voice Details
            </h3>
            <div className="space-y-3">
              {[
                { label: "Framework", value: video.framework || video.framework_angle || "--" },
                { label: "Word Count", value: String(wordCount) },
                { label: "Scenes", value: String(totalScenes) },
                { label: "Sentences", value: String(totalSentences) },
                { label: "Target Length", value: `${video.videoLengthMin || video.video_length_minutes || 0} min` },
                { label: "Est. Cost", value: `$${(video.estimatedCost || video.total_cost || 0).toFixed(2)}` },
              ].map((row) => (
                <div key={row.label} className="flex items-center justify-between">
                  <span className="text-xs" style={{ color: "var(--text-secondary)" }}>
                    {row.label}
                  </span>
                  <span className="text-sm font-mono font-medium" style={{ color: "var(--text-primary)" }}>
                    {row.value}
                  </span>
                </div>
              ))}
            </div>
          </GlassCard>

          {/* Performance track: narrator vs character lines (dialogue intelligence) */}
          {performanceTrack?.mode && (
            <GlassCard className="p-5">
              <h3 className="text-xs font-semibold uppercase tracking-wider mb-3" style={{ color: "var(--text-secondary)" }}>
                Performance Track
              </h3>
              {performanceTrack.mode === "character_dialogue" ? (
                <div className="space-y-2">
                  <p className="text-[11px] leading-relaxed" style={{ color: "var(--text-tertiary)" }}>
                    Character dialogue detected. Each character performs their lines in their
                    own cast voice; the narrator carries everything else. Tap a line to hear it.
                  </p>
                  {performanceTrack.bySpeaker.map(([speaker, info]) => (
                    <div key={speaker}>
                      <div className="flex items-center justify-between">
                        <span className="text-xs" style={{ color: "var(--text-secondary)" }}>💬 {speaker}</span>
                        <span className="text-sm font-mono font-medium" style={{ color: "var(--text-primary)" }}>
                          {info.count} line{info.count === 1 ? "" : "s"}
                        </span>
                      </div>
                      <div className="mt-1 space-y-1">
                        {info.lines.map((l) => {
                          const key = `${l.scene}:${l.index}`;
                          return (
                            <div key={key} className="flex items-center gap-2">
                              <button
                                onClick={() => playLine(l.scene, l.index)}
                                disabled={!l.voiced}
                                title={l.voiced ? "Play this line" : "Not voiced yet — create the voiceover first"}
                                className="w-5 h-5 rounded-full flex items-center justify-center shrink-0"
                                style={{
                                  background: l.voiced ? "var(--turquoise)" : "rgba(255,255,255,0.08)",
                                  color: "var(--bg-void)",
                                  opacity: l.voiced ? 1 : 0.4,
                                  cursor: l.voiced ? "pointer" : "not-allowed",
                                }}
                              >
                                {playingLine === key ? <Square size={8} /> : <Play size={8} className="ml-px" />}
                              </button>
                              <span
                                className="text-[11px] truncate"
                                title={l.text}
                                style={{ color: l.voiced ? "var(--text-secondary)" : "var(--text-tertiary)" }}
                              >
                                S{l.scene} · {l.text}
                              </span>
                            </div>
                          );
                        })}
                      </div>
                    </div>
                  ))}
                  <div className="flex items-center justify-between">
                    <span className="text-xs" style={{ color: "var(--text-secondary)" }}>🎙 Narrator</span>
                    <span className="text-sm font-mono font-medium" style={{ color: "var(--text-primary)" }}>
                      {performanceTrack.narration} segment{performanceTrack.narration === 1 ? "" : "s"}
                    </span>
                  </div>
                  <audio ref={lineAudioRef} onEnded={() => setPlayingLine(null)} className="hidden" />
                </div>
              ) : (
                <p className="text-[11px] leading-relaxed" style={{ color: "var(--text-tertiary)" }}>
                  Narration only — one narrator voice reads the whole script.
                </p>
              )}
            </GlassCard>
          )}

          {/* Google Drive script sync */}
          <GlassCard className="p-5">
            <div className="flex items-center gap-2 mb-3">
              <Cloud size={14} style={{ color: "var(--turquoise)" }} />
              <h3 className="text-xs font-semibold uppercase tracking-wider" style={{ color: "var(--text-secondary)" }}>Google Drive</h3>
              {driveStatus?.drive_newer && (
                <span className="ml-auto text-[9px] font-medium px-1.5 py-0.5 rounded-full"
                  style={{ background: "rgba(255,186,8,0.14)", color: "var(--gold)" }}>
                  Drive edited
                </span>
              )}
            </div>

            {driveStatus && !driveStatus.connected ? (
              <p className="text-[11px] leading-relaxed" style={{ color: "var(--text-tertiary)" }}>
                Connect Google Drive in{" "}
                <a href="/settings" className="underline" style={{ color: "var(--turquoise)" }}>Settings</a>
                {" "}to edit this script as a Google Doc — in any AI tool — and sync edits back.
              </p>
            ) : (
              <div className="space-y-2">
                <p className="text-[11px] leading-relaxed" style={{ color: "var(--text-tertiary)" }}>
                  Edit your script as a Google Doc in your own Drive, then sync changes back here.
                </p>

                <button
                  onClick={() => pushDriveMutation.mutate()}
                  disabled={pushDriveMutation.isPending}
                  className="inline-flex items-center justify-center gap-2 w-full px-4 py-2 rounded-lg text-[12px] font-semibold transition-all hover:brightness-110 active:scale-[0.98] disabled:opacity-50"
                  style={{ background: "var(--turquoise)", color: "var(--bg-void)" }}
                >
                  {pushDriveMutation.isPending ? <Loader2 size={13} className="animate-spin" /> : <CloudUpload size={13} />}
                  {driveStatus?.doc_id ? "Update Doc in Drive" : "Edit in Google Drive"}
                </button>

                {driveStatus?.doc_id && (
                  <>
                    <a
                      href={driveStatus.doc_url || "#"}
                      target="_blank"
                      rel="noopener noreferrer"
                      className="inline-flex items-center justify-center gap-2 w-full px-4 py-2 rounded-lg text-[12px] font-medium transition-all hover:bg-[var(--bg-surface)]"
                      style={{ color: "var(--turquoise)", border: "1px solid var(--turquoise-dim)" }}
                    >
                      <ExternalLink size={12} /> Open Doc
                    </a>
                    <button
                      onClick={() => pullDriveMutation.mutate(false)}
                      disabled={pullDriveMutation.isPending}
                      className="inline-flex items-center justify-center gap-2 w-full px-4 py-2 rounded-lg text-[12px] font-semibold transition-all hover:brightness-110 active:scale-[0.98] disabled:opacity-50"
                      style={{
                        background: driveStatus?.drive_newer ? "var(--gold)" : "rgba(255,255,255,0.05)",
                        color: driveStatus?.drive_newer ? "var(--bg-void)" : "var(--text-secondary)",
                        border: "1px solid var(--border-subtle)",
                      }}
                    >
                      {pullDriveMutation.isPending ? <Loader2 size={13} className="animate-spin" /> : <RefreshCw size={13} />}
                      Sync from Drive
                    </button>
                  </>
                )}

                {driveStatus?.synced_at && (
                  <p className="text-[10px] font-mono" style={{ color: "var(--text-tertiary)" }}>
                    Last sync: {new Date(driveStatus.synced_at).toLocaleString()}
                  </p>
                )}

                {driveMsg && (
                  <div className="text-[11px] leading-relaxed rounded-lg px-2.5 py-2"
                    style={{
                      background: driveConflict ? "rgba(255,120,73,0.1)" : "rgba(255,255,255,0.04)",
                      color: driveConflict ? "var(--orange)" : "var(--text-secondary)",
                    }}>
                    {driveMsg}
                    {driveConflict && (
                      <button
                        onClick={() => pullDriveMutation.mutate(true)}
                        disabled={pullDriveMutation.isPending}
                        className="mt-2 inline-flex items-center gap-1.5 px-2.5 py-1 rounded-md text-[11px] font-semibold disabled:opacity-50"
                        style={{ background: "var(--orange)", color: "var(--bg-void)" }}
                      >
                        {pullDriveMutation.isPending ? <Loader2 size={11} className="animate-spin" /> : null}
                        Sync anyway (Drive wins)
                      </button>
                    )}
                  </div>
                )}
              </div>
            )}
          </GlassCard>

          {/* Script Validation */}
          {(() => {
            if (!video.script_validation) return null;
            let validation: { passed?: boolean; checks?: { name: string; passed: boolean; detail: string; advisory?: boolean }[] } | null = null;
            try {
              validation = typeof video.script_validation === "string" ? JSON.parse(video.script_validation) : video.script_validation;
            } catch { return null; }
            if (!validation?.checks) return null;
            const passCount = validation.checks.filter((c) => c.passed).length;
            const total = validation.checks.length;
            return (
              <GlassCard className="p-5">
                <div className="flex items-center gap-2 mb-3">
                  <ShieldCheck size={14} style={{ color: validation.passed ? "var(--green)" : "var(--red)" }} />
                  <h3 className="text-xs font-semibold uppercase tracking-wider" style={{ color: "var(--text-secondary)" }}>Script Validation</h3>
                  <span className="ml-auto text-[10px] font-mono" style={{ color: validation.passed ? "var(--green)" : "var(--red)" }}>
                    {passCount}/{total}
                  </span>
                </div>
                <div className="space-y-1.5">
                  {validation.checks.map((check) => {
                    const color = check.passed ? "var(--green)" : check.advisory ? "var(--gold)" : "var(--red)";
                    const label = check.passed ? "PASS" : check.advisory ? "WARN" : "FAIL";
                    return (
                      <div key={check.name} className="flex items-start gap-2">
                        <span className="text-[9px] font-mono font-semibold px-1.5 py-0.5 rounded shrink-0 mt-0.5"
                          style={{ background: `${color}20`, color }}>{label}</span>
                        <div className="min-w-0">
                          <span className="text-[11px] font-medium block" style={{ color: "var(--text-primary)" }}>
                            {check.name.replace(/_/g, " ")}
                          </span>
                          <span className="text-[10px] block truncate" style={{ color: "var(--text-tertiary)" }} title={check.detail}>
                            {check.detail}
                          </span>
                        </div>
                      </div>
                    );
                  })}
                </div>
              </GlassCard>
            );
          })()}

          {/* Voice progress */}
          <GlassCard className="p-5">
            <div className="space-y-4">
              <div>
                <p className="text-[10px] uppercase tracking-wider mb-2" style={{ color: "var(--text-tertiary)" }}>
                  Voice Progress
                </p>
                <div className="flex items-center gap-3">
                  <p className="text-2xl font-bold" style={{ color: "var(--text-primary)" }}>
                    {scenesWithVoice}/{totalScenes}
                  </p>
                  <ProgressRing
                    value={totalScenes > 0 ? (scenesWithVoice / totalScenes) * 100 : 0}
                    size={50}
                    color="var(--green)"
                    strokeWidth={4}
                  />
                </div>
                <p className="text-[10px] font-mono mt-1" style={{ color: "var(--text-tertiary)" }}>
                  {totalScenes > 0 ? Math.round((scenesWithVoice / totalScenes) * 100) : 0}% voiced
                </p>
              </div>
            </div>
          </GlassCard>

          {/* Custom voice (ElevenLabs) — paste your own voice ID */}
          <CustomVoiceCard />

          {/* Action buttons */}
          <div className="space-y-2">
            {/* Generate All Voice */}
            <ActionButton
              variant="outline"
              icon={isVoiceBusy ? Loader2 : Mic}
              className="w-full"
              onClick={handleGenerateAllVoice}
              disabled={isVoiceBusy || scenesWithVoice === totalScenes}
            >
              {voiceTaskRunning && generatingVoiceAll
                ? voiceTaskMessage || "Generating Voice..."
                : generatingVoiceAll
                  ? "Starting..."
                  : scenesWithVoice === totalScenes
                    ? "All Voiced"
                    : "Generate All Voice"}
            </ActionButton>

            {/* Regenerate Script */}
            <button
              onClick={handleRegenerateScript}
              disabled={regeneratingScript || scriptTaskRunning || scriptGenerationBlockedByRoster}
              className="inline-flex items-center justify-center gap-2 w-full px-5 py-2.5 rounded-xl text-sm font-semibold font-body transition-all hover:brightness-110 active:scale-[0.98] disabled:opacity-50 disabled:cursor-not-allowed"
              style={{
                background: "rgba(255, 120, 73, 0.15)",
                color: "var(--orange)",
                border: "1px solid var(--orange)",
              }}
            >
              {regeneratingScript || scriptTaskRunning ? (
                <>
                  <Loader2 size={14} className="animate-spin" />{" "}
                  {scriptTaskRunning ? scriptTaskMessage || "Generating..." : "Starting..."}
                </>
              ) : (
                "Regenerate Script"
              )}
            </button>

            {/* Divider */}
            <div className="pt-2" style={{ borderTop: "1px solid var(--border-subtle)" }} />

            {/* Approve / Reject / Approved */}
            {approved ? (
              <div
                className="flex items-center justify-center gap-2 w-full px-5 py-2.5 rounded-xl text-sm font-semibold"
                style={{ color: "var(--green)" }}
              >
                <CheckCircle size={14} /> Script &amp; Voice Approved
              </div>
            ) : (
              <>
                <ActionButton
                  variant="filled"
                  className="w-full"
                  onClick={handleApprove}
                  disabled={approving || !allReady}
                >
                  {approving ? (
                    <>
                      <Loader2 size={14} className="animate-spin" /> Advancing...
                    </>
                  ) : (
                    "Approve Script & Voice"
                  )}
                </ActionButton>
                {!allReady && (
                  <p className="text-[10px] text-center" style={{ color: "var(--text-tertiary)" }}>
                    All scenes need script text and voice audio before approval.
                  </p>
                )}
                <ActionButton variant="outline" className="w-full" onClick={handleReject} disabled={rejecting}>
                  {rejecting ? (
                    <>
                      <Loader2 size={14} className="animate-spin" /> Requesting...
                    </>
                  ) : (
                    "Request Revision"
                  )}
                </ActionButton>
              </>
            )}
          </div>
        </div>
      </div>

      {/* Full animatic playback lives on the Scenes tab; this hidden element
          backs the per-scene Play Voice audition button on the cards above.
          It sits at the component root so it exists in narration-only mode. */}
      <audio ref={sceneAudioRef} onEnded={() => setPlayingSceneVoice(null)} className="hidden" />

      {/* ============================================================= */}
      {/* Revision Modal                                                  */}
      {/* ============================================================= */}
      {showRevisionModal && (
        <div
          className="fixed inset-0 z-50 flex items-center justify-center bg-black/60 backdrop-blur-sm"
          onClick={() => setShowRevisionModal(false)}
        >
          <div
            className="w-full max-w-md rounded-xl p-6 space-y-4"
            style={{ background: "var(--bg-deep)", border: "1px solid var(--border)" }}
            onClick={(e) => e.stopPropagation()}
          >
            <h3 className="text-base font-semibold" style={{ color: "var(--text-primary)" }}>
              Request Revision
            </h3>
            <div>
              <label className="block text-xs font-medium mb-1.5" style={{ color: "var(--text-secondary)" }}>
                Revision Scope
              </label>
              <select
                value={revisionScope}
                onChange={(e) => setRevisionScope(e.target.value)}
                className="w-full px-3 py-2 rounded-lg text-sm outline-none"
                style={{
                  background: "var(--bg-elevated)",
                  color: "var(--text-primary)",
                  border: "1px solid var(--border)",
                }}
              >
                <option>Minor tweaks</option>
                <option>Major rewrite</option>
                <option>Different angle entirely</option>
              </select>
            </div>
            <div>
              <label className="block text-xs font-medium mb-1.5" style={{ color: "var(--text-secondary)" }}>
                What needs to change?
              </label>
              <textarea
                value={revisionNotes}
                onChange={(e) => setRevisionNotes(e.target.value)}
                placeholder="Describe the changes needed..."
                rows={4}
                className="w-full px-3 py-2 rounded-lg text-sm outline-none resize-none"
                style={{
                  background: "var(--bg-elevated)",
                  color: "var(--text-primary)",
                  border: "1px solid var(--border)",
                }}
                autoFocus
              />
            </div>
            <div className="flex gap-2 justify-end">
              <button
                onClick={() => setShowRevisionModal(false)}
                className="px-4 py-2 rounded-lg text-sm"
                style={{ color: "var(--text-secondary)" }}
              >
                Cancel
              </button>
              <button
                onClick={handleSubmitRevision}
                disabled={rejecting || !revisionNotes.trim()}
                className="px-4 py-2 rounded-lg text-sm font-semibold disabled:opacity-40"
                style={{ background: "var(--orange)", color: "var(--bg-void)" }}
              >
                {rejecting ? "Submitting..." : "Submit Revision"}
              </button>
            </div>
          </div>
        </div>
      )}
    </div>
  );
}
