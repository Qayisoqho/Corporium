const test=require('node:test'),assert=require('node:assert/strict'),fs=require('node:fs'),vm=require('node:vm');
const source=fs.readFileSync('web/paradigms.js','utf8');
test('template instances carry row provenance without sharing editable row identities',()=>{
 let n=0;const c={crypto:{randomUUID:()=>`new-${++n}`}};vm.createContext(c);vm.runInContext(source.slice(source.indexOf('function paradigmLayout('),source.indexOf('function paradigmPendingForm(')),c);
 const t={id:'template',title:'Test',dimensions:['Case'],rows:[{id:'nom',labels:['NOM']},{id:'acc',labels:['ACC']}]},a=c.paradigmFromTemplate(t),b=c.paradigmFromTemplate(t);
 assert.equal(a.template_id,'template');assert.equal(a.rows[0].template_row_id,'nom');assert.notEqual(a.rows[0].id,b.rows[0].id);assert.notEqual(a.rows[0].id,t.rows[0].id);
});
function setup({confirm=true,editing=false,stale=false}={}){
 const elements=new Map(),calls=[];function el(id){if(!elements.has(id))elements.set(id,{open:editing&&id==='lexeme-editor',value:id==='lexeme-language'?'ordos':'go',disabled:false,replaceChildren(){calls.push('replace');}});return elements.get(id);}
 const c={$:el,window:{corporiumInvalidateViews:()=>calls.push('invalidate')},workspace:'dictionary',templateBusy:false,templateLanguage:{id:'ordos',revision:4,name:'Ordos',metadata:'{}'},editingLexeme:{id:'go',revision:3,body:{notes:'unsaved original'}},quick:false,lexemeDirty:false,readMorphEntry:()=>({paradigms:[{id:'draft'}]}),corporiumConfirm:async m=>{calls.push({warning:m});return confirm;},originalApi:async(p,b)=>{calls.push({preview:p,request:b});return {token:'reviewed',deletions:[{headword:'go',table:'Past',labels:['PST']}]}},api:async(p,b)=>{calls.push({write:p,request:b});if(stale)throw Error('stale');return {editor_paradigms:[{id:'synced'}],editor_target_id:'go',editor_target_revision:4};},loadTemplateManager:async()=>calls.push('manager'),fillTemplate(){},templateChoices(){},addTable:t=>calls.push({table:t}),renderQuick(){},loadDictionary:async()=>calls.push('dictionary')};
 el('paradigm-template-form').querySelectorAll=()=>[];c.corporiumStatus=message=>calls.push({status:message});vm.createContext(c);vm.runInContext(source.slice(source.indexOf(' async function saveTemplates('),source.indexOf("\n $('paradigm-template-form').onsubmit")),c);return {c,calls,el};
}
test('cancelling populated removal leaves the template and current editor untouched',async()=>{
 const {c,calls,el}=setup({confirm:false});await c.saveTemplates([]);
 assert.equal(calls.some(x=>x.write),false);assert.equal(calls.includes('replace'),false);assert.equal(c.templateBusy,false);assert.equal(el('paradigm-template-choice').disabled,false);
});
test('confirmed removal submits precisely the preview token and refreshes reading view',async()=>{
 const {c,calls}=setup();await c.saveTemplates([]);const writes=calls.filter(x=>x.write);assert.equal(writes.length,1);assert.equal(writes[0].request.template_sync_token,'reviewed');assert.equal(writes[0].request.template_sync_confirmed,true);assert.ok(calls.includes('dictionary'));
});
test('an open draft is included in the warning and rebased without discarding unrelated edits',async()=>{
 const {c,calls}=setup({editing:true});await c.saveTemplates([]);assert.equal(calls.find(x=>x.preview).request.editor_target_revision,3);assert.equal(c.editingLexeme.revision,4);assert.equal(c.editingLexeme.body.notes,'unsaved original');assert.equal(calls.some(x=>x.table?.id==='synced'),true);assert.equal(calls.includes('dictionary'),false);assert.equal(c.lexemeDirty,true);
});
test('stale confirmation reports failure and unlocks controls without rebuilding the draft',async()=>{
 const {c,calls,el}=setup({editing:true,stale:true});await assert.rejects(c.saveTemplates([]),/stale/);assert.equal(calls.includes('replace'),false);assert.equal(c.editingLexeme.revision,3);assert.equal(el('paradigm-template-language').disabled,false);
});
