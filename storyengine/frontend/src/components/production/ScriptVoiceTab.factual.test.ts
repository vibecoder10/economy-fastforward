import { describe, expect, it } from "vitest";
import { readFileSync } from "node:fs";
import ts from "typescript";

const source = readFileSync(new URL("./ScriptVoiceTab.tsx", import.meta.url), "utf8");
const backendSource = readFileSync(new URL("../../../../backend/factual_machine_summary.py", import.meta.url), "utf8");

function numericConstant(body: string, name: string): number {
  const match = body.match(new RegExp(`(?:const\\s+)?${name}\\s*=\\s*(\\d+)\\s*;?`));
  if (!match) throw new Error(`missing numeric constant ${name}`);
  return Number(match[1]);
}

const FACTUAL_REVIEW_CONTEXT_VERSION = numericConstant(source, "FACTUAL_REVIEW_CONTEXT_VERSION");
const BACKEND_REVIEW_CONTEXT_VERSION = numericConstant(backendSource, "REVIEW_CONTEXT_VERSION");

function exportedFunction(name: string): string {
  const start = source.indexOf(`export function ${name}`);
  if (start < 0) throw new Error(`missing exported function ${name}`);
  const brace = source.indexOf("{", start);
  let depth = 0;
  for (let index = brace; index < source.length; index += 1) {
    if (source[index] === "{") depth += 1;
    if (source[index] === "}") depth -= 1;
    if (depth === 0) return source.slice(start, index + 1).replace("export function", "function");
  }
  throw new Error(`unterminated exported function ${name}`);
}

const helperSource = `
  const machineLabelMatches = (left: unknown, right: unknown) => String(left || "").trim().toLowerCase() === String(right || "").trim().toLowerCase();
  const machinePreviewPassesAntonGate = (preview: any) => Boolean(preview?.quality_audit?.passed && preview?.claim_bundle?.formula_sentences?.length === 5);
  const fullMachineResearchGatePassed = (validation: any, verifiedCount: number, rosterCount: number) => Boolean(validation?.passed && verifiedCount === rosterCount && validation?.units?.length >= rosterCount && (!validation?.target_machine || validation?.target_machine_passed === true));
  const FACTUAL_MACHINE_SCRIPT_CONTRACT = "factual_100_v1";
  const FACTUAL_REVIEW_CONTEXT_VERSION = ${FACTUAL_REVIEW_CONTEXT_VERSION};
  const DVSU_COMPILER_VERSION = ${numericConstant(source, "DVSU_COMPILER_VERSION")};
  const DVSU_EDITORIAL_VERSION = ${numericConstant(source, "DVSU_EDITORIAL_VERSION")};
  ${exportedFunction("machinePreviewPassesEditorialGate")}
  ${exportedFunction("factualMachineIdentityMatches")}
  ${exportedFunction("machinePreviewHasCurrentFactualIdentity")}
  ${exportedFunction("machinePreviewPassesContract")}
  ${exportedFunction("machineResearchGatePassesContract")}
  return { machinePreviewPassesContract, machineResearchGatePassesContract };
`;
const compiled = ts.transpileModule(helperSource, {
  compilerOptions: { target: ts.ScriptTarget.ES2020, module: ts.ModuleKind.None },
}).outputText;
const { machinePreviewPassesContract, machineResearchGatePassesContract } = new Function(compiled)();

const currentFactualBlock = {
  passed: true,
  paragraph: "SS-1 USS Holland " + Array(90).fill("fixture").join(" "),
  compiler_version: 2, factual_passed: true, editorial_review_version: 1,
  editorial_review: {version: 1, passed: true, issues: [], checks: Object.fromEntries(
    ["design_intent", "actual_use", "consequence", "gap_or_supported_substitute", "verdict", "spoken_style"].map(key => [key, true]))},
  machine: "SS-1 USS Holland",
  scene: 1,
  machine_script_contract: "factual_100_v1",
  review_context_version: 6,
  subject_context: "Every US Submarine Class Ever Built",
  source_fingerprint: "sha256-current",
};

describe("factual machine script UI truth", () => {
  it("keeps the UI factual review version aligned with the backend", () => {
    expect(FACTUAL_REVIEW_CONTEXT_VERSION).toBe(BACKEND_REVIEW_CONTEXT_VERSION);
    const compiler = readFileSync(new URL("../../../../backend/script_research_packet.py", import.meta.url), "utf8");
    expect(numericConstant(source, "DVSU_COMPILER_VERSION")).toBe(numericConstant(compiler, "COMPILER_VERSION"));
    expect(numericConstant(source, "DVSU_EDITORIAL_VERSION")).toBe(numericConstant(backendSource, "EDITORIAL_REVIEW_VERSION"));
  });

  it("accepts the current Holland factual block with an em dash display label", () => {
    expect(machinePreviewPassesContract(
      currentFactualBlock,
      true,
      "SS-1 — USS Holland",
      1,
      currentFactualBlock.subject_context,
    )).toBe(true);
  });

  it("does not pass stale, wrong-context, or failed factual blocks", () => {
    expect(machinePreviewPassesContract(
      { ...currentFactualBlock, review_context_version: 5 }, true,
      "SS-1 — USS Holland", 1, currentFactualBlock.subject_context,
    )).toBe(false);
    expect(machinePreviewPassesContract(
      currentFactualBlock, true,
      "SS-1 — USS Holland", 1, "Every British Battleship Class Ever Built",
    )).toBe(false);
    expect(machinePreviewPassesContract(
      { ...currentFactualBlock, passed: false, review_context_version: 6 }, true,
      "SS-1 — USS Holland", 1, currentFactualBlock.subject_context,
    )).toBe(false);
  });

  it("rejects thin drafts and old factual-only approvals", () => {
    for (const changes of [{paragraph: "SS-1 USS Holland was a submarine."}, {compiler_version: 1},
      {editorial_review: undefined}, {editorial_review: {...currentFactualBlock.editorial_review, passed: false}}]) {
      expect(machinePreviewPassesContract({...currentFactualBlock, ...changes}, true,
        "SS-1 — USS Holland", 1, currentFactualBlock.subject_context)).toBe(false);
    }
  });

  it("keeps legacy previews behind the Anton audit", () => {
    expect(machinePreviewPassesContract(
      { passed: true, paragraph: "Legacy paragraph" }, false,
      "I49 HMS Argus", 1, currentFactualBlock.subject_context,
    )).toBe(false);
  });

  it("matches a repeated roster hull code to the same persisted factual ship only", () => {
    const campania = {
      ...currentFactualBlock,
      machine: "HMS Campania (D48)",
      scene: 12,
    };
    expect(machinePreviewPassesContract(
      campania, true, "D48 — HMS Campania (D48)", 12, campania.subject_context,
    )).toBe(true);
    expect(machinePreviewPassesContract(
      campania, true, "D49 — HMS Campania (D49)", 12, campania.subject_context,
    )).toBe(false);
  });

  it("uses all current served cards for the factual research gate only", () => {
    const staleAggregate = { passed: false, units: Array(20).fill({ passed: true }) };
    expect(machineResearchGatePassesContract(
      "factual_100_v1", staleAggregate, 21, 21,
    )).toBe(true);
    expect(machineResearchGatePassesContract(
      "legacy_anton", staleAggregate, 21, 21,
    )).toBe(false);
    expect(machineResearchGatePassesContract(
      "factual_100_v1", staleAggregate, 20, 21,
    )).toBe(false);
  });
});


describe("evidence-led editorial compatibility", () => {
  it("accepts v2 without legacy narrative categories and retains v1", () => {
    const block = {...currentFactualBlock, editorial_review_version: 2,
      editorial_review: {version: 2, passed: true, issues: [], checks: {evidence_led: true, coherent: true, spoken_style: true}}};
    expect(machinePreviewPassesContract(block, true, block.machine, 1, block.subject_context)).toBe(true);
    expect(machinePreviewPassesContract(currentFactualBlock, true, block.machine, 1, block.subject_context)).toBe(true);
    expect(machinePreviewPassesContract({...block, editorial_review: null}, true, block.machine, 1, block.subject_context)).toBe(false);
    expect(machinePreviewPassesContract({...block, factual_passed: false}, true, block.machine, 1, block.subject_context)).toBe(false);
  });
});
