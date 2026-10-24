const test=require('node:test'),assert=require('node:assert/strict'),fs=require('node:fs'),vm=require('node:vm');
test('dictionary activates one panel and its sidebar before its first asynchronous read',async()=>{
 const source=fs.readFileSync('web/lexicon.js','utf8');
 const ids=['corpus','dictionary','library','grammar','survey','timeline','analysis'];
 const nodes=Object.fromEntries(ids.flatMap(name=>[[name==='library'?'example-library':name+'-workspace',{hidden:name!=='grammar'}],['workspace-'+name,{setAttribute(k,v){this[k]=v;}}]]));
 let release;const wait=new Promise(r=>release=r),log=[];
 const c={workspace:'grammar',$:id=>nodes[id],window:{corporiumActivateWorkspace:()=>log.push('layout')},loadDictionary:async()=>{log.push('read');await wait;}};
 vm.createContext(c);vm.runInContext(source.slice(source.indexOf('async function setWorkspace('),source.indexOf("$('workspace-corpus').onclick")),c);
 const pending=c.setWorkspace('dictionary');assert.equal(c.workspace,'dictionary');
 assert.deepEqual(log,['layout','read']);assert.deepEqual(Object.entries(nodes).filter(([id,n])=>!id.startsWith('workspace-')&&!n.hidden).map(([id])=>id),['dictionary-workspace']);
 assert.equal(nodes['workspace-dictionary']['aria-pressed'],'true');assert.equal(nodes['workspace-grammar']['aria-pressed'],'false');release();await pending;
 c.window.corporiumReuseDictionary=()=>true;await c.setWorkspace('dictionary');assert.deepEqual(log,['layout','read','layout']);
});
test('a refused dictionary draft leave keeps the current panel and does not request a new view',async()=>{
 const source=fs.readFileSync('web/workbench.js','utf8'),start=source.indexOf(' const previousWorkspace=setWorkspace;'),end=source.indexOf(' const previousLanguage=',start);
 let activated=0;const c={workspace:'dictionary',leaveLexeme:async()=>false,sentenceInspector:{leave:async()=>{throw Error('should not leave');}},window:{},setWorkspace:async()=>activated++};
 vm.createContext(c);vm.runInContext(source.slice(start,end),c);await assert.rejects(c.setWorkspace('grammar'),/保留/);assert.equal(activated,0);assert.equal(c.workspace,'dictionary');
});
function grammarSetup(){
 const nodes=new Map(),calls=[];const c={$:id=>{if(!nodes.has(id))nodes.set(id,{value:'',disabled:false,textContent:'',close(){calls.push('close');}});return nodes.get(id);},window:{},grammarEditing:null,grammarDirty:true};
 c.originalApi=async path=>{calls.push(path);if(c.wait)await c.wait;if(c.saveError)throw Error('保存失败');return {id:'tag'};};
 c.loadGrammar=async()=>{calls.push('audit');if(c.auditError)throw Error('检查失败');};
 c.refreshUndo=async()=>{calls.push('heavy');await c.loadGrammar();};c.window.corporiumRefreshUndoState=async()=>calls.push('history');
 const undo=fs.readFileSync('web/undo.js','utf8'),grammar=fs.readFileSync('web/grammar.js','utf8');
 vm.createContext(c);vm.runInContext(undo.slice(undo.indexOf('api=async function('),undo.indexOf('async function undoCommand(')),c);
 vm.runInContext(grammar.slice(grammar.indexOf("$('grammar-form').onsubmit="),grammar.indexOf("$('grammar-run').onclick=")),c);
 return {c,calls,submit:()=>c.$('grammar-form').onsubmit({preventDefault(){}})};
}
test('tag save updates history and performs exactly one audit after closing the editor',async()=>{
 const {c,calls,submit}=grammarSetup();await submit();assert.deepEqual(calls,['grammar-save','history','close','audit']);assert.equal(c.grammarDirty,false);assert.equal(c.$('grammar-save').disabled,false);
 calls.length=0;await c.api('grammar-delete',{});await c.loadGrammar();assert.deepEqual(calls,['grammar-delete','history','audit']);
});
test('tag double submission is coalesced and an audit failure is reported as an already saved label',async()=>{
 const {c,calls,submit}=grammarSetup();let release;c.wait=new Promise(r=>release=r);const first=submit();await submit();release();c.auditError=true;await first;
 assert.equal(calls.filter(x=>x==='grammar-save').length,1);assert.equal(calls.filter(x=>x==='audit').length,1);assert.match(c.$('grammar-notice').textContent,/标签已保存/);assert.equal(c.$('grammar-save').disabled,false);
});
test('save failure keeps the tag editor dirty and does not run a check',async()=>{
 const {c,calls,submit}=grammarSetup();c.saveError=true;await submit();assert.deepEqual(calls,['grammar-save']);assert.equal(c.grammarDirty,true);assert.match(c.$('grammar-error').textContent,/保存失败/);
});
test('dictionary starts its independent catalogs together and consumers reuse each pending request',async()=>{
 const paths=[],gates=new Map();const c={URL,URLSearchParams,structuredClone,activeLanguage:'one',window:{corporiumWorkspaceRevision:'a'},showLexeme:async()=>{},api:path=>{paths.push(path);return new Promise(r=>gates.set(path,r));},loadDictionary:async()=>{for(const p of ['dictionary-search-options','dictionary-organization','dictionary-counts'])await c.api(p);}};
 vm.createContext(c);vm.runInContext(fs.readFileSync('web/workspace-loading.js','utf8'),c);
 const pending=c.loadDictionary();assert.deepEqual(paths,['dictionary-search-options','dictionary-organization','dictionary-counts']);for(const release of gates.values())release({});await pending;assert.equal(paths.length,3);
});
