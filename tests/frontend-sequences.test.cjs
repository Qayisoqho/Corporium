const test=require('node:test'),assert=require('node:assert/strict'),fs=require('node:fs'),vm=require('node:vm');
const read=name=>fs.readFileSync('web/'+name+'.js','utf8').replace(/\r\n/g,'\n');
const deferred=()=>{let resolve;const promise=new Promise(r=>resolve=r);return {promise,resolve};};

function inlineHarness(){
 const source=read('inline-editor'),listeners={},drafts=new Map(),calls=[],nodes={notice:{textContent:''}},cards=[];
 const c={window:{},workspace:'dictionary',activeLanguage:'one',structuredClone,URLSearchParams,inlineDrafts:drafts,
  document:{addEventListener:(name,fn)=>listeners[name]=fn,querySelectorAll:()=>cards,createElement:()=>({})},$:id=>nodes[id],
  inlineStyledFields:d=>JSON.stringify(d.body),inlineSelection:()=>{},api:async()=>{calls.push('read');return {body:{translation:'server'},cells:[]};},
  originalApi:async()=>{calls.push('write');return {id:'saved'};},refreshUndo:async()=>calls.push('heavy-history'),
  loadTexts:async()=>calls.push('texts'),refreshExampleViews:async()=>calls.push('views')};
 c.window.corporiumRefreshUndoState=async()=>calls.push('history');
 vm.createContext(c);
 vm.runInContext(source.slice(source.indexOf('function repaintInline('),source.indexOf('async function refreshExampleViews(')),c);
 const start=source.indexOf("document.addEventListener('click',async e=>{");
 vm.runInContext(source.slice(start,source.indexOf("window.addEventListener('beforeunload'",start)),c);
 function card(key='independent:x'){const r={dataset:{exampleKey:key,exampleKind:'independent',exampleId:key.split(':')[1]},isConnected:true,innerHTML:'old',getClientRects:()=>[{}],append(){throw Error('outer error');}};cards.push(r);return r;}
 function click(r,action){const b={dataset:{},closest:()=>r,hasAttribute:name=>name==='data-inline-'+action};return listeners.click({preventDefault(){},target:{closest:()=>b}});}
 function draft(key='independent:x'){const d={kind:'independent',id:key.split(':')[1],owner_language:'one',body:{translation:'local',words:[]},words:[],layers:[],cells:[],dirty:true};drafts.set(key,d);return d;}
 return {c,calls,cards,card,click,draft,drafts,nodes};
}

test('opening a cached reference reuses the existing draft instead of replacing it',async()=>{
 const h=inlineHarness(),r=h.card(),d=h.draft();await h.click(r,'start');
 assert.equal(h.drafts.get(r.dataset.exampleKey),d);assert.equal(h.calls.length,0);assert.match(r.innerHTML,/local/);
});
test('out-of-order opens of the same sentence cannot overwrite edits made after the first open',async()=>{
 const h=inlineHarness(),r=h.card(),gate=deferred();let n=0;
 h.c.api=async()=>{if(++n===1)await gate.promise;return {body:{translation:'server'},cells:[]};};
 const first=h.click(r,'start');await h.click(r,'start');const d=h.drafts.get(r.dataset.exampleKey);d.body.translation='typed';d.dirty=true;
 gate.resolve();await first;assert.equal(h.drafts.get(r.dataset.exampleKey),d);assert.equal(d.body.translation,'typed');
});
test('late annotation response after language switch cannot open a detached editor',async()=>{
 const h=inlineHarness(),r=h.card(),gate=deferred();h.c.api=async()=>{await gate.promise;return {body:{},cells:[]};};
 const pending=h.click(r,'start');await Promise.resolve();await Promise.resolve();h.c.activeLanguage='two';r.isConnected=false;gate.resolve();await pending;
 assert.equal(h.drafts.size,0);
});
test('inline save refreshes history once and delegates only the visible workspace',async()=>{
 const h=inlineHarness(),r=h.card();h.draft();await h.click(r,'save');assert.deepEqual(h.calls,['write','history','views']);assert.equal(h.drafts.size,0);
});
test('a successful write followed by a failed refresh reports success accurately without restoring a saveable draft',async()=>{
 const h=inlineHarness(),r=h.card();h.draft();h.c.refreshExampleViews=async()=>{throw Error('offline');};await h.click(r,'save');
 assert.equal(h.drafts.size,0);assert.match(h.nodes.notice.textContent,/已保存/);assert.match(h.nodes.notice.textContent,/offline/);assert.deepEqual(h.calls,['write','history']);
});
test('saving one sentence leaves another sentence draft and its stable slot identities intact',async()=>{
 const h=inlineHarness(),r=h.card();h.draft();const other=h.draft('corpus:y');other.words=[{id:'stable-slot'}];await h.click(r,'save');assert.equal(h.drafts.get('corpus:y'),other);assert.equal(other.words[0].id,'stable-slot');
});
for(const workspace of ['corpus','library','dictionary','grammar','survey','timeline'])test(`${workspace} sentence refresh does not query hidden corpus pages`,async()=>{
 const calls=[],source=read('inline-editor'),c={workspace,window:{corporiumInvalidateViews:()=>calls.push('invalidate')},dictionarySelection:'x'};
 for(const [name,label] of Object.entries({loadTexts:'texts',search:'search',loadLibrary:'library',loadDictionary:'dictionary',showLexeme:'detail',loadGrammar:'grammar'}))c[name]=async()=>calls.push(label);
 vm.createContext(c);vm.runInContext(source.slice(source.indexOf('async function refreshExampleViews('),source.indexOf("document.addEventListener('input',e=>{\n const card")),c);await c.refreshExampleViews();
 assert.deepEqual(calls,['invalidate',...({corpus:['texts','search'],library:['library'],dictionary:['dictionary'],grammar:['grammar']}[workspace]||[])]);
});
for(const kind of ['undo','redo'])for(const isNew of [false,true])test(`${kind} refuses ${isNew?'new':'existing'} sentence drafts before any database mutation`,async()=>{
 const source=read('undo'),calls=[],nodes={},c={undoBusy:false,infoDirty:false,inlineDrafts:new Map([['x',{isNew,dirty:true}]]),undoState:{undo:{},redo:{},generation:1},document:{querySelector:()=>null},$:id=>nodes[id]??={},originalApi:async()=>calls.push('write'),chosen:{clear(){}},loadLanguages:async()=>{},loadTexts:async()=>{},selectText:async()=>{},selected:'',texts:[],corporiumStatus(){},refreshUndo:async()=>{}};
 vm.createContext(c);vm.runInContext(source.slice(source.indexOf('async function undoCommand('),source.indexOf("$('undo-action').onclick")),c);await c.undoCommand(kind);
 assert.deepEqual(calls,[]);assert.match(nodes.notice.textContent,/保存或取消/);
});
test('dictionary preflight responses may not reverse the user’s most recent selection',async()=>{
 const source=read('morphemes'),line=source.split('\n').find(s=>s.includes('const oldShow=showLexeme;')),gate=deferred(),shown=[];
 const c={activeLanguage:'one',exampleRequest:0,leaveSentenceDrafts:async()=>{},api:async path=>{const id=decodeURIComponent(path.split('=')[1]);if(id==='first')await gate.promise;return {id};},showLexeme:async id=>{shown.push(id);c.dictionarySelection=id;},$:()=>({querySelector:()=>null})};
 vm.createContext(c);vm.runInContext(line,c);const first=c.showLexeme('first');await c.showLexeme('second');gate.resolve();await first;
 assert.deepEqual(shown,['second']);assert.equal(c.dictionarySelection,'second');
});

test('typing updates another visible copy, keeps the focused control and defers hidden copies until activation',async()=>{
 const h=inlineHarness(),r=h.card(),peer=h.card(),hidden=h.card(),d=h.draft();hidden.getClientRects=()=>[];
 const source=read('inline-editor'),start=source.indexOf("document.addEventListener('input',e=>{\n const card");
 let input;h.c.document.addEventListener=(_,fn)=>input=fn;
 vm.runInContext(source.slice(start,source.indexOf("document.addEventListener('click',async e=>{",start)),h.c);
 input({target:{closest:()=>r,matches:()=>false,classList:{contains:()=>false},dataset:{inlineField:'translation'},value:'typed'}});
 assert.equal(d.body.translation,'typed');assert.equal(r.innerHTML,'old');assert.match(peer.innerHTML,/typed/);assert.equal(hidden.innerHTML,'old');
 hidden.getClientRects=()=>[{}];h.c.window.corporiumSyncInlineDrafts();assert.match(hidden.innerHTML,/typed/);
});
test('cached workspace synchronizes drafts before its first asynchronous dictionary load',async()=>{
 const source=read('lexicon'),calls=[],panels={},gate=deferred(),c={workspace:'corpus',window:{corporiumActivateWorkspace:()=>calls.push('activate'),corporiumSyncInlineDrafts:()=>calls.push('draft'),corporiumReuseDictionary:()=>false},$:id=>panels[id]??={setAttribute(){}},loadDictionary:async()=>{calls.push('load');await gate.promise;}};
 vm.createContext(c);vm.runInContext(source.slice(source.indexOf('async function setWorkspace('),source.indexOf("$('workspace-corpus').onclick")),c);
 const pending=c.setWorkspace('dictionary');assert.deepEqual(calls,['activate','draft','load']);gate.resolve();await pending;
});
test('outer undo guard runs before autosave wrappers and location restoration',async()=>{
 const source=read('workspace-loading'),calls=[],nodes={},c={inlineDrafts:new Map([['draft',{}]]),$:id=>nodes[id]??={},window:{corporiumPreserveLocation:async fn=>{calls.push('location');return fn();}},undoCommand:async()=>calls.push('autosave'),views:{refreshVisible:async()=>calls.push('refresh')}};
 vm.createContext(c);const start=source.indexOf(" if(typeof undoCommand==='function')");vm.runInContext(source.slice(start,source.indexOf(" if(typeof corpusReady",start)),c);
 await c.undoCommand('undo');assert.deepEqual(calls,[]);assert.match(nodes.notice.textContent,/保存或取消/);
});
test('a failed save retains both drafts and stable word identities with no history refresh',async()=>{
 const h=inlineHarness(),r=h.card(),d=h.draft(),other=h.draft('corpus:y');d.words=[{id:'stable'}];h.c.originalApi=async()=>{throw Error('版本冲突');};await h.click(r,'save');
 assert.equal(h.drafts.size,2);assert.equal(h.drafts.get('corpus:y'),other);assert.equal(d.words[0].id,'stable');assert.equal(d.saving,false);assert.equal(d.error,'版本冲突');assert.deepEqual(h.calls,[]);
});
test('late dictionary preflight is discarded after a language change',async()=>{
 const source=read('morphemes'),line=source.split('\n').find(s=>s.includes('const oldShow=showLexeme;')),gate=deferred(),shown=[];
 const c={activeLanguage:'one',leaveSentenceDrafts:async()=>{},api:async()=>{await gate.promise;return {};},showLexeme:async id=>shown.push(id),$:()=>({querySelector:()=>null})};
 vm.createContext(c);vm.runInContext(line,c);const pending=c.showLexeme('old');await Promise.resolve();c.activeLanguage='two';gate.resolve();await pending;assert.deepEqual(shown,[]);
});
test('a handled conflict is not replayed when a draft is rendered in another workspace; retry may report it again',async()=>{
 const h=inlineHarness(),r=h.card(),d=h.draft(),source=read('inline-editor');
 Object.assign(h.c,{esc:x=>x??'',inlineSlotTools:()=>'',inlineSentenceLayers:()=>''});
 vm.runInContext(source.slice(source.indexOf('function inlineFields('),source.indexOf('function repaintInline(')),h.c);
 d.orphaned=[];d.error='版本冲突';h.c.repaintInline(r.dataset.exampleKey);assert.equal(d.errorShown,d.error);assert.doesNotMatch(h.c.inlineFields(d),/版本冲突/);
 // Starting another save clears the delivered error before a new failure.
 d.error='';h.c.repaintInline(r.dataset.exampleKey);d.error='版本冲突';assert.match(h.c.inlineFields(d),/版本冲突/);
});
