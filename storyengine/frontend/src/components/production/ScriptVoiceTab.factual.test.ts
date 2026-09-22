import { describe, expect, it } from "vitest";
import { readFileSync } from "node:fs";
import ts from "typescript";

// The Script tab's machine-preview gate must agree with the ONE backend
// writer (backend/dvsu_script_v2.py): a preview counts only when it passed
// the writer's code-side audit AND carries the v2 contract, the same scene,
// the same subject and a research fingerprint. Legacy Anton / factual_100_v1
// blocks never pass, no matter what else they carry.
const source = readFileSync(new URL("./ScriptVoiceTab.tsx", import.meta.url), "utf8");
const backendSource = readFileSync(new URL("../../../../backend/dvsu_script_v2.py", import.meta.url), "utf8");

function stringConstant(body: string, name: string): string {
  const match = body.match(new RegExp(`${name}\\s*=\\s*"([^"]+)"`));
  if (!match) throw new Error(`missing string constant ${name}`);
  return match[1];
}

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
  const fullMachineResearchGatePassed = (validation: any, verifiedCount: number, rosterCount: number) => Boolean(validation?.passed && verifiedCount === rosterCount && validation?.units?.length >= rosterCount && (!validation?.target_machine || validation?.target_machine_passed === true));
  const FACTUAL_MACHINE_SCRIPT_CONTRACT = "${stringConstant(source, "FACTUAL_MACHINE_SCRIPT_CONTRACT")}";
  const DVSU_SCRIPT_CONTRACT = "${stringConstant(source, "DVSU_SCRIPT_CONTRACT")}";
  ${exportedFunction("factualMachineIdentityMatches")}
  ${exportedFunction("machinePreviewHasCurrentIdentity")}
  ${exportedFunction("machinePreviewPassesContract")}
  ${exportedFunction("machineResearchGatePassesContract")}
  return { machinePreviewPassesContract, machineResearchGatePassesContract };
`;
const compiled = ts.transpileModule(helperSource, {
  compilerOptions: { target: ts.ScriptTarget.ES2020, module: ts.ModuleKind.None },
}).outputText;
const { machinePreviewPassesContract, machineResearchGatePassesContract } = new Function(compiled)();

const SUBJECT = "Every US Submarine Class Ever Built";
const currentBlock = {
  passed: true,
  paragraph: "For fifty years every submarine had been a surface ship that could hide. " + Array(80).fill("word").join(" "),
  machine: "SS-1 USS Holland",
  scene: 1,
  machine_script_contract: "dvsu_script_v2",
  subject_context: SUBJECT,
  source_fingerprint: "sha256-current",
  claim_map: [],
  opened_with_name: false,
  bridged_to: null,
};

describe("machine script preview gate", () => {
  it("uses the same contract id as the backend writer", () => {
    expect(stringConstant(source, "DVSU_SCRIPT_CONTRACT")).toBe(stringConstant(backendSource, "SCRIPT_CONTRACT"));
  });

  it("accepts a current v2 block, matching on the roster's display label", () => {
    expect(machinePreviewPassesContract(currentBlock, "SS-1 — USS Holland", 1, SUBJECT)).toBe(true);
  });

  it("rejects a block that failed the audit, is stale, or belongs elsewhere", () => {
    expect(machinePreviewPassesContract({ ...currentBlock, passed: false }, "SS-1 — USS Holland", 1, SUBJECT)).toBe(false);
    expect(machinePreviewPassesContract({ ...currentBlock, paragraph: "  " }, "SS-1 — USS Holland", 1, SUBJECT)).toBe(false);
    expect(machinePreviewPassesContract({ ...currentBlock, source_fingerprint: "" }, "SS-1 — USS Holland", 1, SUBJECT)).toBe(false);
    expect(machinePreviewPassesContract(currentBlock, "SS-1 — USS Holland", 2, SUBJECT)).toBe(false);
    expect(machinePreviewPassesContract(currentBlock, "SS-1 — USS Holland", 1, "Every British Battleship Class Ever Built")).toBe(false);
    expect(machinePreviewPassesContract(currentBlock, "SSN-571 USS Nautilus", 1, SUBJECT)).toBe(false);
  });

  it("never passes a legacy Anton or factual_100_v1 block", () => {
    expect(machinePreviewPassesContract(
      { ...currentBlock, machine_script_contract: "factual_100_v1", review_context_version: 6, editorial_review: { passed: true } },
      "SS-1 — USS Holland", 1, SUBJECT,
    )).toBe(false);
    expect(machinePreviewPassesContract(
      { passed: true, paragraph: "Legacy paragraph", quality_audit: { passed: true, checks: [{ passed: true }] },
        claim_bundle: { formula_sentences: ["a", "b", "c", "d", "e"] } },
      "I49 HMS Argus", 1, SUBJECT,
    )).toBe(false);
  });

  it("matches a repeated roster hull code to the same persisted ship only", () => {
    const campania = { ...currentBlock, machine: "HMS Campania (D48)", scene: 12 };
    expect(machinePreviewPassesContract(campania, "D48 — HMS Campania (D48)", 12, SUBJECT)).toBe(true);
    expect(machinePreviewPassesContract(campania, "D49 — HMS Campania (D49)", 12, SUBJECT)).toBe(false);
  });

  it("keeps the research gate keyed on the research contract, not the script one", () => {
    const staleAggregate = { passed: false, units: Array(20).fill({ passed: true }) };
    expect(machineResearchGatePassesContract("factual_100_v1", staleAggregate, 21, 21)).toBe(true);
    expect(machineResearchGatePassesContract("legacy_anton", staleAggregate, 21, 21)).toBe(false);
    expect(machineResearchGatePassesContract("factual_100_v1", staleAggregate, 20, 21)).toBe(false);
  });
});
