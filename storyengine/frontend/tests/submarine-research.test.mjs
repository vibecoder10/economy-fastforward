import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import test from "node:test";
import ts from "typescript";
import React from "react";
import { renderToStaticMarkup } from "react-dom/server";

const source = readFileSync(new URL("../src/components/production/ResearchTab.tsx", import.meta.url), "utf8");
const helpers = source.slice(source.indexOf("function machineLabel("), source.indexOf("function CollapsibleSection("))
  .replaceAll("export function", "function");
const compiled = ts.transpileModule(`${helpers}\nreturn { machineLabel, machineLabelMatches, textMentionsMachine, sourcePackageForMachine };`, {
  compilerOptions: { target: ts.ScriptTarget.ES2022, module: ts.ModuleKind.None },
}).outputText;
const { machineLabel, machineLabelMatches, textMentionsMachine, sourcePackageForMachine } = new Function(compiled)();
const assessmentSource = source.slice(source.indexOf("function AssessmentQuotes("), source.indexOf("function BulletList("))
  .replaceAll("export function", "function");
const assessmentCompiled = ts.transpileModule(`${assessmentSource}\nreturn { SourceAssessmentPanel };`, {
  compilerOptions: { target: ts.ScriptTarget.ES2022, module: ts.ModuleKind.None, jsx: ts.JsxEmit.React },
}).outputText;
const { SourceAssessmentPanel } = new Function("React", assessmentCompiled)(React);

const representativeRoster = [
  "SS-1 USS Holland", "SS-2 USS Plunger", "SS-105 USS S-1", "SS-163 USS Barracuda",
  "SS-212 USS Gato", "SS-285 USS Balao", "SS-417 USS Tench", "SS-563 USS Tang",
  "AGSS-569 USS Albacore", "SS-580 USS Barbel", "SSN-571 USS Nautilus", "SSN-585 USS Skipjack",
  "SSN-593 USS Thresher", "SSN-637 USS Sturgeon", "SSN-688 USS Los Angeles", "SSN-21 USS Seawolf",
  "SSN-774 USS Virginia", "SSBN-598 USS George Washington", "SSBN-608 USS Ethan Allen", "SSBN-616 USS Lafayette",
];

test("preserves the accepted 20-submarine roster labels and order", () => {
  assert.equal(representativeRoster.length, 20);
  assert.deepEqual(representativeRoster.map(machineLabel), representativeRoster);
  const packages = Object.fromEntries(representativeRoster.map((machine, index) => [`package-${index}`, { machine }]));
  for (const machine of representativeRoster) {
    assert.equal(machineLabelMatches(machine, machine), true, machine);
    assert.equal(sourcePackageForMachine(packages, machine)?.machine, machine, machine);
  }
  assert.match(source, /research\.unit_roster\.map\(\(item: any, index: number\) =>/);
});

test("named submarines require the complete display identity, not a shared hull or class", () => {
  assert.equal(machineLabelMatches("SSN-571 USS Nautilus", "SSN 571 USS Nautilus"), true);
  assert.equal(machineLabelMatches("SSN-571 — USS Nautilus", "SSN-571 — USS Nautilus"), true);
  assert.equal(machineLabelMatches("SSN-571 USS Nautilus", "USS Nautilus (SSN-571)"), false);
  assert.equal(machineLabelMatches("AGSS-569 USS Albacore", "SS-569 USS Albacore"), false);
  assert.equal(machineLabelMatches("SSN-571 USS Nautilus", "SSN-571 USS Wrong Class"), false);
  assert.equal(machineLabelMatches("SSN-571 USS Nautilus", "SSN-571"), false);
  assert.equal(machineLabelMatches("SSN-571 USS Nautilus", "Nautilus class"), false);
  assert.equal(sourcePackageForMachine({ SSN571: { machine: "SSN-571 USS Wrong Class" } }, "SSN-571 USS Nautilus"), null);
  assert.equal(sourcePackageForMachine({ SS212: { machine: "SS-212 USS Gato class" } }, "SS-212 USS Gato"), null);
  assert.equal(machineLabelMatches("SS-212 USS Gato", "SS-212 USS Gato class"), false);
});

test("submarine excerpts need the exact USS name and correct naval hull", () => {
  assert.equal(textMentionsMachine("USS Nautilus (SSN-571) was commissioned in 1954.", "SSN-571 USS Nautilus"), true);
  assert.equal(textMentionsMachine("Nautilus (SSN 571) was commissioned in 1954.", "SSN-571 USS Nautilus"), true);
  assert.equal(textMentionsMachine("USS Albacore (SS-569) tested a teardrop hull.", "AGSS-569 USS Albacore"), true);
  assert.equal(textMentionsMachine("USS Nautilus (SSN-585) was discussed alongside Skipjack.", "SSN-571 USS Nautilus"), false);
  assert.equal(textMentionsMachine("USS Nautilus was famous.", "SSN-571 USS Nautilus"), false);
  assert.equal(textMentionsMachine("USS Skipjack (SSN-571) was a class reference.", "SSN-571 USS Nautilus"), false);
  assert.equal(textMentionsMachine("USS Tangent (SS-563) was a different vessel.", "SS-563 USS Tang"), false);
  assert.equal(textMentionsMachine("USS S-1 (SS-105) served early in the fleet.", "SS-105 USS S-1"), true);
});

test("SSR renders assessment evidence, counterevidence, warnings, and empty state", () => {
  const assessed = renderToStaticMarkup(React.createElement(SourceAssessmentPanel, {
    subjectWord: "submarine",
    assessment: {
      status: "assessed",
      claims: [{
        id: "C1", claim: "The boat was commissioned.", scope: "service", status: "disputed", reason: "Sources disagree.",
        evidence: [{ excerpt_id: "E1", quote: "Commissioned in 1954.", source_url: "https://navy.example/e1", source_title: "Navy source", locator: "p. 1" }],
        counterevidence: [{ excerpt_id: "E2", quote: "Commissioned in 1955.", source_url: "https://archive.example/e2", source_title: "Archive source", locator: "p. 2" }],
      }],
    },
  }));
  assert.match(assessed, /Disputed/);
  assert.match(assessed, /Supporting source quotes/);
  assert.match(assessed, /Counterevidence quotes/);
  assert.match(assessed, /Commissioned in 1954/);
  assert.match(assessed, /Commissioned in 1955/);
  assert.match(assessed, /not a measured probability/i);
  assert.doesNotMatch(assessed, /\d+(?:\.\d+)?%/);

  const failed = renderToStaticMarkup(React.createElement(SourceAssessmentPanel, {
    subjectWord: "submarine", assessment: { status: "needs_review", warnings: ["Receipt validation failed."] },
  }));
  assert.match(failed, /Needs review/);
  assert.match(failed, /Receipt validation failed/);

  const missing = renderToStaticMarkup(React.createElement(SourceAssessmentPanel, { subjectWord: "submarine", assessment: null }));
  assert.match(missing, /Not assessed/);
  assert.match(missing, /this submarine/);
});


test("factual cards use summary status without legacy Anton preview warnings", () => {
  assert.match(source, /factualResearch \? "Saved source-backed research summary"/);
  assert.match(source, /selectedSourcePackage && !factualResearch/);
  assert.doesNotMatch(assessmentSource, /row\.locator/);
});
