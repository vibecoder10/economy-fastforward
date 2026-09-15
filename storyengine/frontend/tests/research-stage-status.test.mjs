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
test('saved roster requires saved cards before research is complete', () => {
  assert.equal(stages({fact_sheet: 'Verified research brief.'}).research.status, 'done');
  assert.equal(stages({unit_roster: ['Holland']}, {total: 1, ready: 0, units: []}).research.status, 'not_started');
  assert.equal(stages({unit_roster: ['Holland']}, {total: 1, ready: 1, units: []}).research.status, 'done');
});

test('accepted runtime roster is done without photos while saved-card research remains separate', () => {
  const payload = {
    roster_selection: {version: 1, status: 'completed', target_count: 20},
    unit_roster_validation: {passed: true},
    unit_roster: Array.from({length: 20}, (_, i) => `Machine ${i + 1}`),
    research_phase: 'roster_complete',
    fact_sheet: 'Selection evidence only.',
  };
  const view = stages(payload, {total: 20, ready: 0, units: []});
  assert.equal(view.roster.status, 'done');
  assert.equal(view.research.status, 'not_started');
  const active = stages({...payload, research_phase: 'unit_research'}, {total: 20, ready: 0, units: []});
  assert.equal(active.research.status, 'in_progress');
});

test('stale accepted flag and a hidden legacy draft never imply ready research', () => {
  const units = Array.from({length: 58}, (_, i) => `Candidate ${i}`);
  const draft = stages({unit_roster: units, unit_roster_validation:{passed:false}, fact_sheet:'Saved draft.'}, {total:0,ready:0,units:[]});
  assert.equal(draft.roster.status,'blocked');
  assert.equal(draft.research.status,'not_started');
  const stale = stages({unit_roster:units,roster_selection:{version:1,status:'completed',target_count:20},unit_roster_validation:{passed:false}});
  assert.notEqual(stale.roster.status,'done');
});
