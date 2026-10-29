const test=require('node:test'),assert=require('node:assert/strict'),fs=require('node:fs'),vm=require('node:vm');
const source=fs.readFileSync('web/lexicon.js','utf8');
function setup(){
 const nodes={},calls=[],features=[{value:'PL',checked:false},{value:'LOC',checked:true}],draft={lexeme:'target',form:'variant',usage:'u',sense:'s',component:'c',features:['PL'],query:'pending query',notes:'pending notes'};
 for(const [id,options] of Object.entries({'link-lexeme':['','target'],'link-form':['','variant'],'link-usage':['','u'],'link-sense':['','s'],'link-component':['','c']}))nodes[id]={value:'',options:options.map(value=>({value}))};
 for(const id of ['link-query','link-notes','save-link'])nodes[id]={value:''};nodes['link-features']={querySelectorAll:()=>features};
 const c=vm.createContext({$:id=>nodes[id],linkUnit:{active:true,effective_language_id:'one'},linkLexeme:null,document:{querySelectorAll:()=>[]},corporiumStatus:message=>calls.push(message),
  searchLinkLexemes:async(id,options)=>{assert.equal(id,'target');assert.equal(options.linkedOnly,true);c.linkLexeme={id,language_id:'one',revision:9};nodes['link-lexeme'].value=id;},chooseLinkLexeme:async()=>{c.linkLexeme=null;},showMorphLinkForm(){},chooseLinkUsage(){},showLinkSuggestion(){}});
 vm.runInContext(source.slice(source.indexOf('async function restoreWordLinkDraft'),source.indexOf('function linkedSentenceSource')),c);
 return {c,nodes,draft,features,calls};
}
test('source refresh keeps valid target selections, features and pending text using the fresh target revision',async()=>{
 const h=setup();assert.equal(await h.c.restoreWordLinkDraft(h.draft),true);assert.equal(h.c.linkLexeme.revision,9);
 for(const [id,value] of [['link-form','variant'],['link-usage','u'],['link-sense','s'],['link-component','c'],['link-query','pending query'],['link-notes','pending notes']])assert.equal(h.nodes[id].value,value);
 assert.deepEqual(h.features.map(f=>f.checked),[true,false]);assert.equal(h.nodes['save-link'].disabled,false);
});
test('removed meanings and features retain draft text but disable saving until reviewed',async()=>{
 for(const change of [h=>h.nodes['link-sense'].options=[{value:''}],h=>h.features.splice(0,1)]){
  const h=setup();change(h);assert.equal(await h.c.restoreWordLinkDraft(h.draft),false);assert.equal(h.nodes['save-link'].disabled,true);assert.equal(h.nodes['link-notes'].value,h.draft.notes);assert.equal(h.calls.length,1);
 }
});
test('a removed or cross-language target cannot silently become another association',async()=>{
 for(const fail of [false,true]){const h=setup();h.c.searchLinkLexemes=async()=>{if(fail)throw Error('deleted');h.c.linkLexeme={language_id:'other'};};await h.c.restoreWordLinkDraft(h.draft);assert.equal(h.c.linkLexeme,null);assert.equal(h.nodes['link-lexeme'].value,'');assert.equal(h.nodes['save-link'].disabled,true);assert.equal(h.nodes['link-query'].value,h.draft.query);}
});
test('late draft restoration cannot overwrite text for a newer inspector selection',async()=>{
 const h=setup();let resolve,current=true;h.c.searchLinkLexemes=()=>new Promise(r=>resolve=r);const pending=h.c.restoreWordLinkDraft(h.draft,()=>current);current=false;h.nodes['link-notes'].value='new selection';resolve();assert.equal(await pending,false);assert.equal(h.nodes['link-notes'].value,'new selection');assert.equal(h.calls.length,0);
});
