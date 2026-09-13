import { describe, expect, it } from "vitest";
import { readFileSync } from "node:fs";
import ts from "typescript";

const source = readFileSync(new URL("./ScriptVoiceTab.tsx", import.meta.url), "utf8");

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
  const fullMachineResearchGatePassed = (validation: any, verifiedCount: number, rosterCount: number) => Boolean(validation?.passed && verifiedCount === rosterCount && validation?.units?.length >= rosterCount && !validation?.target_machine);
  const FACTUAL_MACHINE_SCRIPT_CONTRACT = "factual_100_v1";
  const FACTUAL_REVIEW_CONTEXT_VERSION = 5;
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
  paragraph: "HMS Argus served as an aircraft carrier.",
  machine: "I49 HMS Argus",
  scene: 1,
  machine_script_contract: "factual_100_v1",
  review_context_version: 5,
  subject_context: "Every British Aircraft Carrier Class Ever Built",
  source_fingerprint: "sha256-current",
};

describe("factual machine script UI truth", () => {
  it("accepts the current factual block without requiring the legacy Anton audit", () => {
    expect(machinePreviewPassesContract(
      currentFactualBlock,
      true,
      "I49 HMS Argus",
      1,
      currentFactualBlock.subject_context,
    )).toBe(true);
  });

  it("does not pass stale, wrong-context, or failed factual blocks", () => {
    expect(machinePreviewPassesContract(
      { ...currentFactualBlock, review_context_version: 4 }, true,
      "I49 HMS Argus", 1, currentFactualBlock.subject_context,
    )).toBe(false);
    expect(machinePreviewPassesContract(
      currentFactualBlock, true,
      "I49 HMS Argus", 1, "Every British Battleship Class Ever Built",
    )).toBe(false);
    expect(machinePreviewPassesContract(
      { ...currentFactualBlock, passed: false }, true,
      "I49 HMS Argus", 1, currentFactualBlock.subject_context,
    )).toBe(false);
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
