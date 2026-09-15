import assert from 'node:assert/strict';
import {readFileSync} from 'node:fs';
import vm from 'node:vm';
import ts from 'typescript';
import test from 'node:test';

// Execute the actual stage computation without importing React or browser hooks.
const source = readFileSync(new URL('../src/components/production/StaticDocuStageRail.tsx', import.meta.url), 'utf8');
const start = source.indexOf('export function computeStaticDocuStages(');
const end = source.indexOf('\n}', start) + 2;
const code = ts.transpileModule(source.slice(start, end).replace('export function', 'function'), {
  compilerOptions: {target: ts.ScriptTarget.ES2022},
}).outputText;
const ctx = vm.createContext({
  RENDER_DONE_STATUSES: new Set(['rendered', 'done']),
  getStaticDocuReadiness: () => ({blockedUnits: 0, allReady: false}),
});
vm.runInContext(code, ctx);
const stages = (research_payload, dashboard) => ctx.computeStaticDocuStages({research_payload, status: 'idea_logged'}, undefined, dashboard);

test('contract metadata does not show completed research', () => {
  assert.equal(stages({machine_script_contract: 'factual_100_v1'}).research.status, 'not_started');
  assert.equal(stages(null).research.status, 'not_started');
});
test('saved brief and actual card readiness remain visible', () => {
  assert.equal(stages({fact_sheet: 'Verified research brief.'}).research.status, 'done');
  assert.equal(stages({unit_roster: ['Holland']}, {total: 1, ready: 0, units: []}).research.status, 'in_progress');
  assert.equal(stages({unit_roster: ['Holland']}, {total: 1, ready: 1, units: []}).research.status, 'done');
});
