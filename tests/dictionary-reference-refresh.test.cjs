const test=require('node:test'),assert=require('node:assert/strict'),fs=require('node:fs'),vm=require('node:vm');
const source=fs.readFileSync('web/lexicon.js','utf8');
function setup(kind='lexeme'){
 const button={disabled:true,isConnected:true},root={dataset:{referenceId:'entry',referenceRevision:'3'}},calls=[];
 const c=vm.createContext({workspace:'dictionary',dictionarySelection:'entry',activeLanguage:'one',URLSearchParams,
  $:id=>id.endsWith('detail')?root:button,window:{dictionaryEntryKind:()=>kind,dictionaryMorphemeSelection:()=>c.dictionarySelection},
  originalApi:async path=>{calls.push(path);return {revision:3,can_delete:true,components:0};}});
 vm.runInContext(source.slice(source.indexOf('let dictionaryReferenceRequest='),source.indexOf('async function refreshUnlinkedExamples')),c);
 return {c,button,root,calls,refresh:()=>c.window.corporiumRefreshDictionaryReferenceState()};
}
for(const kind of ['lexeme','morpheme'])test(`${kind} deletion state follows remaining evidence and components without reopening the entry`,async()=>{
 const h=setup(kind);await h.refresh();assert.equal(h.button.disabled,false);
 for(const components of [0,2]){h.c.originalApi=async()=>({revision:3,can_delete:false,components});await h.refresh();assert.equal(h.button.disabled,true);assert.match(h.button.title,components?/组分/:/例句/);}
 h.c.originalApi=async()=>({revision:3,can_delete:true});await h.refresh();assert.equal(h.button.disabled,false);assert.equal(h.button.title,'');
});
test('reference refresh does not enable deletion against an unseen entry revision',async()=>{
 const h=setup();h.c.originalApi=async()=>({revision:4,can_delete:true});await h.refresh();assert.equal(h.button.disabled,true);assert.match(h.button.title,/重新打开/);assert.equal(h.root.dataset.referenceRevision,'3');
});
test('an older reference response cannot undo a newer count for the same entry',async()=>{
 const h=setup(),pending=[];h.c.originalApi=()=>new Promise(r=>pending.push(r));const old=h.refresh(),fresh=h.refresh();pending[1]({revision:3,can_delete:false});await fresh;pending[0]({revision:3,can_delete:true});await old;assert.equal(h.button.disabled,true);
});
test('late reference responses cannot change another entry, language, or workspace',async()=>{
 for(const move of [h=>h.c.dictionarySelection='other',h=>h.c.activeLanguage='other',h=>h.c.workspace='corpus',h=>h.button.isConnected=false]){
  const h=setup();let resolve;h.c.originalApi=()=>new Promise(r=>resolve=r);const pending=h.refresh();move(h);resolve({revision:3,can_delete:true});await pending;assert.equal(h.button.disabled,true);
 }
});
test('unlink refresh recomputes references and updates a filtered list without rebuilding the detail',async()=>{
 const calls=[],c=vm.createContext({window:{dictionarySearchScope:()=>({query:'test'}),corporiumRefreshDictionaryReferenceState:async()=>calls.push('references')},refreshDictionaryListOnly:async detail=>calls.push(['list',detail])});
 vm.runInContext(source.slice(source.indexOf('async function refreshUnlinkedExamples'),source.indexOf("$('dictionary-search').onclick")),c);
 await c.refreshUnlinkedExamples(async()=>calls.push('evidence'));assert.deepEqual(calls,['evidence',['list',false],'references']);
});
