const test=require('node:test'),assert=require('node:assert/strict'),vm=require('node:vm'),fs=require('node:fs');
test('grammar hover explanations preserve scripts, aliases, language scope and escaping',()=>{
 const context={activeLanguage:'a',languageList:[{id:'a',metadata:JSON.stringify({glossary:{'neg#sub[POT]':'可能否定','NEGATIVE':'可能否定',GEN:'属格'}})},{id:'b',metadata:JSON.stringify({glossary:{GEN:'另一语言的解释'}})}],esc:s=>String(s??'').replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]))};
 const source=fs.readFileSync('web/display-tools.js','utf8');vm.createContext(context);vm.runInContext(source.slice(0,source.indexOf('let briefMode')),context);
 assert.match(context.richGloss('打<neg#sub[POT]>来=NEGATIVE-GEN'),/title="可能否定">neg<sub>POT<\/sub>/);
 assert.match(context.richGloss('NEGATIVE'),/title="可能否定"/);assert.match(context.richGloss('GEN','b'),/title="另一语言的解释"/);
 assert.equal(context.richGloss('unregistered'),'unregistered');
 context.languageList[0].metadata=JSON.stringify({glossary:{GEN:'新解释 " <img>'}});
 assert.match(context.richGloss('GEN'),/title="新解释 &quot; &lt;img&gt;"/);
});
test('timeline navigation ignores foreign drafts and preserves its own unsaved edits',async()=>{
 const source=fs.readFileSync('web/timeline.js','utf8');let flushed=0;
 const context={inlineDrafts:new Map(),flushIntervalTime:async()=>flushed++,window:{discardEmptySentenceDrafts(){}},dirtyInterval:false,draftInterval:null};
 vm.createContext(context);vm.runInContext(source.slice(source.indexOf('function timelineHasSentenceDraft'),source.indexOf('window.CorporiumTimeline=')),context);
 for(const workspace of ['corpus','library','dictionary']){const draft={workspace,dirty:true};context.inlineDrafts.set(workspace,draft);await context.noDraft();assert.equal(context.inlineDrafts.get(workspace),draft);}
 context.inlineDrafts.set('timeline',{workspace:'timeline',dirty:true});await assert.rejects(context.noDraft(),/保存或取消/);
 context.inlineDrafts.delete('timeline');context.dirtyInterval=true;await assert.rejects(context.noDraft(),/时间尚未保存/);
 assert.ok(flushed>=5);
});
test('empty new rows with preallocated morphology IDs are discarded without losing saved or referenced identities',()=>{
 const source=fs.readFileSync('web/lexicon.js','utf8'),context={};vm.createContext(context);
 vm.runInContext(source.slice(source.indexOf('function pruneNewLexemeRows'),source.indexOf("$('lexeme-form').onsubmit")),context);
 const saved={usages:[{id:'saved',senses:[{id:'saved-sense'}]}],variants:[{id:'saved-v'}],orthographies:[{id:'saved-o'}]};
 const body={usages:[{id:'new-uuid',tags:[{type:'register',value:''}]},{id:'saved',senses:[{id:'blank-new-sense'},{id:'saved-sense'}]},{id:'feature-only',features:['feature']},{id:'referenced-u'}],variants:[{id:'empty-v',kind:'语素变体',variation:'unknown'},{id:'saved-v'},{id:'referenced-v'}],orthographies:[{id:'saved-o'},{id:'new-writing',label:'自动类型',type_id:'type'}],word_structure:{memberships:[{usage_id:'referenced-u',parts:[{variant_id:'referenced-v'}]}]}};
 context.pruneNewLexemeRows(body,saved);
 assert.deepEqual(body.usages.map(r=>r.id),['saved','feature-only','referenced-u']);assert.deepEqual(body.usages[0].senses.map(r=>r.id),['saved-sense']);assert.deepEqual(body.variants.map(r=>r.id),['saved-v','referenced-v']);assert.equal(body.orthographies.length,1);
});

test('empty morphology placeholders are omitted while existing and meaningful partial rows retain their identities',()=>{
 const source=fs.readFileSync('web/word-structure.js','utf8'),c={};vm.createContext(c);vm.runInContext(source.slice(source.indexOf('function pruneNewWordStructure')),c);
 const value={memberships:[{id:'empty',parts:[]},{id:'saved'},{id:'partial',notes:'keep'}],analyses:[{id:'empty-analysis',default:true,level:'unspecified',components:[{id:'empty-component',form:' '}]},{id:'real',components:[{id:'empty',form:''},{id:'new',form:'ma'},{id:'saved-component',form:''},{id:'partial-component',readings:['ma']}]}]};
 c.pruneNewWordStructure(value,{memberships:[{id:'saved'}],analyses:[{id:'real',components:[{id:'saved-component'}]}]});
 assert.deepEqual(value.memberships.map(m=>m.id),['saved','partial']);assert.deepEqual(value.analyses.map(a=>a.id),['real']);assert.deepEqual(value.analyses[0].components.map(r=>r.id),['new','saved-component','partial-component']);
});
test('phonology dragging preserves fields, rejects cross-axis drops and cancels without reordering',()=>{
 const source=fs.readFileSync('web/homophone-phonology.js','utf8'),lists={initials:[],finals:[]};let hit=null;
 const markerRows=()=>Object.values(lists).flat().filter(r=>r.dataset.rowDrop);
 const context={$:()=>({querySelectorAll:markerRows}),document:{elementFromPoint:()=>hit}};vm.createContext(context);
 vm.runInContext(source.slice(source.indexOf(' let inventoryDrag=null;'),source.indexOf(' function row(')),context);
 function row(axis,name){const r={name,dataset:{},parentElement:lists[axis],classList:{add(){},remove(){}},setPointerCapture(){},hasPointerCapture(){return false;},querySelector(){return {focus(){}};},closest(){return null;},getBoundingClientRect(){return {top:50,height:50};},before(other){const list=r.parentElement;list.splice(list.indexOf(other),1);list.splice(list.indexOf(r),0,other);},after(other){const list=r.parentElement;list.splice(list.indexOf(other),1);list.splice(list.indexOf(r)+1,0,other);}};lists[axis].push(r);return r;}
 const a=row('initials','p'),b=row('initials','t'),foreign=row('finals','a'),editable={closest:()=>true},grip={closest:()=>null};
 const event=(target=grip,x=20,y=20)=>({button:0,pointerId:1,target,clientX:x,clientY:y,preventDefault(){}});
 hit={closest:()=>b};context.inventoryPointerDown(event(editable),a);context.inventoryPointerMove(event(grip,50,95));context.inventoryPointerUp(event());assert.deepEqual(lists.initials,[a,b]);
 context.inventoryPointerDown(event(),a);context.inventoryPointerMove(event(grip,50,95));context.inventoryPointerUp(event());assert.deepEqual(lists.initials,[b,a]);assert.equal(markerRows().length,0);
 hit={closest:()=>foreign};context.inventoryPointerDown(event(),b);context.inventoryPointerMove(event(grip,50,95));context.inventoryPointerUp(event());assert.deepEqual(lists.initials,[b,a]);assert.deepEqual(lists.finals,[foreign]);
 hit={closest:()=>a};context.inventoryPointerDown(event(),b);context.inventoryPointerMove(event(grip,50,95));context.clearInventoryDrag();context.inventoryPointerUp(event());assert.deepEqual(lists.initials,[b,a]);assert.equal(markerRows().length,0);
});
test('recognized punctuation and boundaries use one compact editing column without splitting symbols',()=>{
 const source=fs.readFileSync('web/inline-editor.js','utf8'),display=fs.readFileSync('web/display-tools.js','utf8'),c={phonologicalBoundary:s=>/^(#+)$/.test(s)};vm.createContext(c);
 vm.runInContext(display.slice(display.indexOf('function glossEditParts'),display.indexOf('function lexemeLabel')),c);
 vm.runInContext(source.slice(source.indexOf('const inlineWidth='),source.indexOf('function renderEditableExample')),c);
 for(const form of ['-','...','，','###']){c.word={form,gloss:'',...(form==='###'?{}:{punctuation:true,punctuation_form:form})};assert.equal(vm.runInContext('compactWord(word)',c),true);assert.deepEqual(Array.from(c.inlineWordParts(c.word,'form')),[form]);}
 c.word={form:'a-b',gloss:'时间-dat',punctuation:true,punctuation_form:'.'};assert.equal(vm.runInContext('compactWord(word)',c),false);assert.deepEqual(Array.from(c.inlineWordParts(c.word,'gloss')),['时间','-','dat']);
});
