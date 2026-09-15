import assert from 'node:assert/strict';
import {readFileSync} from 'node:fs';
import {createRequire} from 'node:module';
import vm from 'node:vm';
import test from 'node:test';
import ts from 'typescript';
import React from 'react';
import {renderToStaticMarkup} from 'react-dom/server';
const require=createRequire(import.meta.url);
const wrapper=tag=>({children,icon,...props})=>React.createElement(tag,props,children);
const stubs={
 '@/components/ui/GlassCard':{GlassCard:wrapper('section')},
 '@/components/ui/ActionButton':{ActionButton:wrapper('button')},
 '@/components/ui/toast':{useToast:()=>({success(){},error(){}})},
 '@tanstack/react-query':{useQueryClient:()=>({invalidateQueries(){}})},
 '@/hooks/use-task-poller':{useSharedTaskWatcher:()=>({running:false})},
 '@/lib/api':{}, '@/lib/utils':{toDisplayImageUrl:url=>url},
 '@/components/ui/confirm':{useConfirm:()=>async()=>true},
};
const src=readFileSync(new URL('../src/components/production/RosterStagePanel.tsx',import.meta.url),'utf8');
const compiled=ts.transpileModule(src,{compilerOptions:{target:ts.ScriptTarget.ES2022,module:ts.ModuleKind.CommonJS,jsx:ts.JsxEmit.ReactJSX}}).outputText;
const exports={};vm.runInNewContext(compiled,{exports,require:name=>stubs[name]||require(name),console});
const candidate={id:'a',image_url:'https://image/a',source_page:'https://archive/a',hosted_url:'https://asset/a',
 reason:'Clear whole hull and sail.',scores:{coverage:5,features:4,sharpness:4,unobstructed:3,perspective:5},
 identity:{status:'confirmed',evidence:[{url:'https://archive/a',quote:'The archive names this exact submarine.'}]},
 limitations:['Underwater control surface hidden.']};
const render=(ref)=>renderToStaticMarkup(React.createElement(exports.RosterStagePanel,{videoId:'v',
 video:{id:'v',research_payload:{unit_roster:['Submarine'],roster_selection:{status:'completed'}}},
 rosterDashboard:{total:1,ready:0,units:[{machine:'Submarine',state:'needs_research',warnings:[],reference:ref}]},
 isLoading:false,onRefresh(){},taskWatcher:{running:false},mode:'image_gather'}));
const selected=n=>({status:'verified',kind:'photo',source_url:candidate.image_url,hosted_url:candidate.hosted_url,
 source_page_url:candidate.source_page,selection_review:{version:1,status:'selected',compared_count:n,selected:candidate,
 candidates:[candidate,{id:'b',source_page:'https://archive/b',reason:'Bow covered by launch equipment.'}],
 supporting:[{id:'c',source_page:'https://archive/c',hosted_url:'https://asset/c',reason:'Stern detail.'}]}});
test('actual component renders multi-photo reasons, evidence, alternatives and supporting image',()=>{
 const html=render(selected(3));
 for(const text of ['Identity checked','Compared 3 photos','Why this photo','Clear whole hull','coverage 5/5','Underwater control surface','https://archive/a','https://archive/b','https://asset/c'])assert.ok(html.includes(text),text);
});
test('single source is explicit',()=>{const html=render(selected(1));assert.ok(html.includes('Single source'));assert.ok(!html.includes('Compared 1 photos'));});
test('legacy preview remains and gather invites review',()=>{
 const html=render({status:'missing',kind:'photo',hosted_url:'https://old/photo',source_url:'https://old/source',selection_pending:true});
 assert.ok(html.includes('https://old/photo'));assert.ok(html.includes('Photo saved'));assert.ok(html.includes('Review image choices'));assert.ok(!html.includes('Identity checked'));
});
test('provider failure preserves old preview with actual reason and direct-image hints',()=>{
 const html=render({status:'missing',hosted_url:'https://old/photo',reason_detail:'Vision provider unavailable.',
 selection_review:{version:1,status:'error',compared_count:0,reason:'Vision provider unavailable.',candidates:[]}});
 assert.ok(html.includes('https://old/photo'));assert.ok(html.includes('Vision provider unavailable.'));assert.ok(html.includes('Optional source page URL'));assert.ok(html.includes('direct image URL'));
});
