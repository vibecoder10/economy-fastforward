import assert from 'node:assert/strict';
import {readFileSync} from 'node:fs';
import vm from 'node:vm';
import ts from 'typescript';
import test from 'node:test';

test('queued gather receipts show progress only while the shared task is active', () => {
 const panel = readFileSync(new URL('../src/components/production/RosterStagePanel.tsx', import.meta.url), 'utf8');
 const expression = panel.match(/const bridgeIsRosterSweep =([\s\S]*?);/)[1];
 const ctx = vm.createContext({taskWatcher:{running:true,taskType:'pipeline',message:'Gathering reference images'},payload:{roster_images:{status:'running'}}});
 assert.equal(vm.runInContext(expression,ctx),true);
 ctx.taskWatcher.running = false;
 assert.equal(vm.runInContext(expression,ctx),false);
 ctx.taskWatcher.running = true;
 ctx.payload.roster_images.status = 'completed';
 assert.equal(vm.runInContext(expression,ctx),false);
});

const source = readFileSync(new URL('../src/components/production/StaticDocuStageRail.tsx', import.meta.url), 'utf8');
const start = source.indexOf('export function computeStaticDocuStages(');
const end = source.indexOf('\n}', start) + 2;
const code = ts.transpileModule(source.slice(start, end).replace('export function', 'function'), {compilerOptions:{target:ts.ScriptTarget.ES2022}}).outputText;
const ctx = vm.createContext({RENDER_DONE_STATUSES:new Set(), getStaticDocuReadiness:()=>({blockedUnits:0,allReady:false,readyViews:0,readyUnits:0,generatingUnits:0})});
vm.runInContext(code,ctx);
const names = ['A','B'];
const payload = {roster_selection:{version:1,status:'completed',target_count:2},unit_roster_validation:{passed:true},unit_roster:names};
const stage = (dashboard, extra={}) => ctx.computeStaticDocuStages({status:'idea_logged',research_payload:{...payload,...extra}},undefined,dashboard);
const photo = (machine) => ({machine,state:'needs_research',warnings:[],reference:{status:'verified',kind:'photo',hosted_url:`https://host/${machine}`,source_url:`https://source/${machine}`}});

test('gather is done only for exact unique matching roster photos',()=>{
 assert.equal(stage({total:2,ready:0,units:[photo('A'),photo('B')]}).image_gather.status,'done');
 assert.notEqual(stage({total:2,ready:0,units:[photo('A'),photo('C')]}).image_gather.status,'done');
 assert.notEqual(stage({total:2,ready:0,units:[photo('A'),{...photo('B'),reference:{status:'verified',kind:'photo',hosted_url:'',source_url:'x'}}]}).image_gather.status,'done');
});
test('one-unit hold cannot complete research and designation is not duplicated',()=>{
 const one = stage({total:2,ready:1,units:[photo('A'),photo('B')]},{unit_research_hold_validation:{passed:true,units:[{machine:'A',passed:true}]}});
 assert.notEqual(one.research.status,'done');
 const compat = ctx.computeStaticDocuStages({status:'idea_logged',research_payload:{...payload,unit_roster:[{designation:'SS-1',name:'SS-1 Holland'}]}},undefined,{total:1,ready:0,units:[photo('SS-1 Holland')]});
 assert.equal(compat.image_gather.status,'done');
});
test('complete saved research remains done while missing images still gate the next step',()=>{
 const view = stage({total:2,ready:2,units:[photo('A'),photo('B')]},{unit_research_hold_validation:{passed:true,units:[{machine:'A',passed:true},{machine:'B',passed:true}]}});
 assert.equal(view.research.status,'done');
 const missing = stage({total:2,ready:2,units:[photo('A'),{...photo('B'),reference:{status:'missing'}}]},{unit_research_hold_validation:{passed:true,units:[{machine:'A',passed:true},{machine:'B',passed:true}]}});
 assert.equal(missing.research.status,'done');
 assert.notEqual(missing.image_gather.status,'done');
});
