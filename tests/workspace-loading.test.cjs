const test=require('node:test');
const assert=require('node:assert/strict');
const fs=require('node:fs');
const vm=require('node:vm');
const source=fs.readFileSync('web/workspace-loading.js','utf8');
function setup(){
 const calls=[],c={URL,URLSearchParams,structuredClone,activeLanguage:'one',window:{corporiumWorkspaceRevision:'a',dictionaryEntryKind:()=>c.kind},kind:'lexeme'};
 c.api=async(path,body)=>{calls.push([path,body]);if(c.fail)throw Error('read failed');return {items:[{id:'x',value:1}]};};
 c.originalApi=async()=>({workspace_revision:c.serverRevision||c.window.corporiumWorkspaceRevision});
 c.window.corporiumRefreshUndoState=async()=>{c.window.corporiumWorkspaceRevision=c.serverRevision;};
 c.showLexeme=async()=>{const a=await c.api('lexeme?id=x');a.items[0].value=9;return c.api('lexeme?id=x');};
 c.loadDictionary=async()=>{if(c.wait)await c.wait;return c.showLexeme();};
 vm.createContext(c);vm.runInContext(source,c);return {c,calls};
}
test('returning dictionary reuses a complete view only for the same revision, language and kind',async()=>{
 const {c}=setup();assert.equal(c.window.corporiumReuseDictionary(),false);
 await c.loadDictionary();assert.equal(c.window.corporiumReuseDictionary(),true);
 c.activeLanguage='two';assert.equal(c.window.corporiumReuseDictionary(),false);
 c.activeLanguage='one';c.kind='morpheme';assert.equal(c.window.corporiumReuseDictionary(),false);
 c.kind='lexeme';c.window.corporiumWorkspaceRevision='b';assert.equal(c.window.corporiumReuseDictionary(),false);
 await c.loadDictionary();assert.equal(c.window.corporiumReuseDictionary(),true);
});
test('repeated reads share a request within one render and receive independent values',async()=>{
 const {c,calls}=setup();const result=await c.showLexeme();assert.equal(result.items[0].value,1);assert.equal(calls.length,1);
 await c.showLexeme();assert.equal(calls.length,2); // No data cache survives the render.
 await c.api('lexeme?id=x');await c.api('lexeme?id=x');assert.equal(calls.length,4);
});
test('small catalogs reuse a revision, isolate returned values, and invalidate after writes or external revisions',async()=>{
 const {c,calls}=setup();const path='dictionary-search-options';
 const first=await c.api(path);first.items[0].value=99;
 assert.equal((await c.api(path)).items[0].value,1);assert.equal(calls.length,1);
 c.window.corporiumWorkspaceRevision='new';await c.api(path);assert.equal(calls.length,2);
 await c.api('lexeme-save',{});await c.api(path);assert.equal(calls.length,4);
 c.activeLanguage='two';await c.api(path);assert.equal(calls.length,5);
 c.window.corporiumWorkspaceRevision='failed';c.fail=true;await assert.rejects(c.api(path));c.fail=false;await c.api(path);assert.equal(calls.length,7);
});
test('returning to a cached dictionary checks external edits before deciding to reuse it',async()=>{
 const {c}=setup();await c.loadDictionary();await c.window.corporiumCheckDictionary();assert.equal(c.window.corporiumReuseDictionary(),true);
 c.serverRevision='external-edit';await c.window.corporiumCheckDictionary();assert.equal(c.window.corporiumReuseDictionary(),false);
 await c.loadDictionary();assert.equal(c.window.corporiumReuseDictionary(),true);
});
test('writes invalidate reuse and a failed or stale render cannot become reusable',async()=>{
 const {c}=setup();await c.loadDictionary();await c.api('lexeme-save',{id:'x'});assert.equal(c.window.corporiumReuseDictionary(),false);
 c.fail=true;await assert.rejects(c.loadDictionary());assert.equal(c.window.corporiumReuseDictionary(),false);c.fail=false;
 let finish;c.wait=new Promise(r=>finish=r);const pending=c.loadDictionary();c.window.corporiumWorkspaceRevision='new';finish();await pending;
 assert.equal(c.window.corporiumReuseDictionary(),false);
});

test('Word preparation keeps cached views; confirmed Word import invalidates them',async()=>{
 const {c}=setup();await c.loadDictionary();c.window.CorporiumViews.mark('corpus');
 for(const action of ['inspect','preview','export','template'])await c.api('docx-'+action,{});
 assert.equal(c.window.corporiumReuseDictionary(),true);assert.equal(c.window.CorporiumViews.current('corpus'),true);
 await c.api('docx-import',{});assert.equal(c.window.corporiumReuseDictionary(),false);assert.equal(c.window.CorporiumViews.current('corpus'),false);
});
test('only the latest concurrent list load may make a view reusable',async()=>{
 const {c}=setup();let first;c.wait=new Promise(r=>first=r);const a=c.loadDictionary();c.wait=null;
 await c.loadDictionary();c.activeLanguage='two';first();await a;assert.equal(c.window.corporiumReuseDictionary(),false);
});

const focusSource=fs.readFileSync('web/undo.js','utf8').split('// Regaining focus')[1];
function focusSetup(){
 const calls={reads:0,heavy:0,light:0},handlers={};
 const c={activeLanguage:'one',infoDirty:false,open:false,state:{workspace_revision:'a'},window:{corporiumWorkspaceRevision:'a',addEventListener:(name,fn)=>handlers[name]=fn},document:{querySelector:()=>c.open?{}:null},safe:fn=>fn};
 c.originalApi=async()=>{calls.reads++;if(c.wait)await c.wait;if(c.fail)throw Error('offline');return c.state;};
 c.refreshUndo=async()=>{calls.heavy++;c.window.corporiumWorkspaceRevision=c.state.workspace_revision;};
 c.window.corporiumRefreshUndoState=async()=>{calls.light++;c.window.corporiumWorkspaceRevision=c.state.workspace_revision;};
 vm.createContext(c);vm.runInContext('// Regaining focus'+focusSource,c);return {c,calls,focus:()=>handlers.focus()};
}
test('unchanged focus checks do not reload language lists or workspace contents',async()=>{
 const {calls,focus}=focusSetup();await focus();await focus();assert.deepEqual(calls,{reads:2,heavy:0,light:0});
});
test('a changed project refreshes once; an open editor keeps its draft',async()=>{
 const {c,calls,focus}=focusSetup();c.state={workspace_revision:'b'};await focus();await focus();assert.equal(calls.heavy,1);
 c.open=true;c.state={workspace_revision:'c'};await focus();assert.equal(calls.light,1);assert.equal(calls.heavy,1);
 c.open=false;await focus();assert.equal(calls.heavy,2);
});
test('focus checks coalesce, ignore a late language response and can retry failures',async()=>{
 const {c,calls,focus}=focusSetup();let finish;c.wait=new Promise(r=>finish=r);const a=focus(),b=focus();c.activeLanguage='two';finish();await Promise.all([a,b]);
 assert.equal(calls.reads,1);assert.equal(calls.heavy,0);c.wait=null;c.fail=true;await assert.rejects(focus());
 c.fail=false;c.state={workspace_revision:'b'};await focus();assert.equal(calls.heavy,1);
});
test('inline sentence editing also defers an external refresh until the editor is closed',async()=>{
 const {c,calls,focus}=focusSetup();c.inlineDrafts=new Map([['sentence',{dirty:true}]]);c.state={workspace_revision:'b'};
 await focus();assert.equal(calls.heavy,0);assert.equal(calls.light,1);
 c.inlineDrafts.clear();await focus();assert.equal(calls.heavy,1);
});

test('unchanged project focus does not refresh an analysis catalog over an open draft',async()=>{
 const {c,focus}=focusSetup();let catalogs=0;c.window.corporiumCheckActiveCatalog=async()=>{catalogs++;};
 c.open=true;await focus();assert.equal(catalogs,0);c.open=false;await focus();assert.equal(catalogs,1);
});

test('undo and redo refresh the visible derived view after data changed, and a refused undo leaves it alone',async()=>{
 const {c}=setup();let refreshed=0;c.window.CorporiumViews.handlers.clear();
 c.window.CorporiumViews.register('homophones',()=>true,async()=>{refreshed++;c.window.CorporiumViews.mark('homophones');});
 c.undoCommand=async()=>{c.window.corporiumWorkspaceRevision='b';};
 const start=source.indexOf(" if(typeof undoCommand==='function')"),end=source.indexOf(" if(typeof corpusReady",start);
 c.views=c.window.CorporiumViews;vm.runInContext(source.slice(start,end),c);
 await c.undoCommand('undo');assert.equal(refreshed,1);await c.undoCommand('undo');assert.equal(refreshed,1);
});

test('context navigation keeps each language/module scroll and leaves an unchanged sidebar mounted',()=>{
 const script=fs.readFileSync('web/workbench.js','utf8'),start=script.indexOf(' let navOwner='),end=script.indexOf(' // Workspace titles',start);
 let mounts=0;const nodes=new Map();const c={activeLanguage:'one',workspace:'dictionary',moduleNav:{scrollTop:0,replaceChildren(){mounts++;this.scrollTop=0;}},corpusNav:{},sideActions:{},languageMore:{},languagePanel:{},dictionaryPanel:{querySelector:x=>x},restore(){},relocate(){},document:{documentElement:{dataset:{}}},$:id=>{if(!nodes.has(id))nodes.set(id,{});return nodes.get(id);}};
 vm.createContext(c);vm.runInContext(script.slice(start,end),c);
 c.contextNav();c.moduleNav.scrollTop=300;c.contextNav();assert.equal(mounts,1);assert.equal(c.moduleNav.scrollTop,300);
 c.workspace='survey';c.contextNav();assert.equal(c.moduleNav.scrollTop,0);c.moduleNav.scrollTop=120;
 c.workspace='dictionary';c.contextNav();assert.equal(c.moduleNav.scrollTop,300);
 c.activeLanguage='two';c.contextNav();assert.equal(c.moduleNav.scrollTop,0);
 c.activeLanguage='one';c.workspace='survey';c.contextNav();assert.equal(c.moduleNav.scrollTop,120);
});
