const test=require('node:test'),assert=require('node:assert/strict'),fs=require('node:fs'),vm=require('node:vm');
const source=fs.readFileSync('web/grammar.js','utf8');
function setup(){
 const nodes={'grammar-source':{value:'all'},'grammar-lower':{checked:false},'grammar-tag-query':{value:''}},calls=[],published=[],draws=[];
 const data={tags:[{id:'pl',uses:2}],unknown:[],ignored:[],tag_page:1,tag_pages:1,tag_total:1};
 const c=vm.createContext({URLSearchParams,activeLanguage:'ordos',grammarRequest:0,grammarTagPage:1,grammarTagNav:{},
  grammarPanel:{dataset:{grammarView:'tags'}},$:id=>nodes[id],publishGrammarAudit:x=>published.push(x),
  drawGrammarTags:()=>draws.push('tags'),registryPagination:()=>{},drawGrammarCandidates:x=>draws.push(x),
  window:{corporiumRunTask:async(...args)=>{calls.push(['task',...args]);return data;}},
  originalApi:async path=>{calls.push(['probe',path]);return {needs_task:true,definitions:data};},
  api:async()=>{throw Error('duplicate readiness probe');}});
 vm.runInContext(source.slice(source.indexOf('async function loadGrammar'),source.indexOf('\nmakeDialog')),c);
 return {c,calls,published,draws,data};
}
test('registry preparation displays definitions then starts one task without a second probe',async()=>{
 const x=setup();await x.c.loadGrammar();assert.deepEqual(x.calls.map(row=>row[0]),['probe','task']);
 assert.equal(x.calls[1][1],'grammar-audit');assert.equal(x.calls[1][2].language,'ordos');
 assert.equal(x.published.at(-1).pending,false);assert.equal(x.draws.at(-1),x.data);
});
test('ready registry uses one ordinary request and opens no task',async()=>{
 const x=setup();x.c.originalApi=async()=>x.data;await x.c.loadGrammar();assert.equal(x.calls.length,0);assert.equal(x.draws.at(-1),x.data);
});
test('late registry responses cannot populate a different language or an obsolete request',async()=>{
 for(const mutate of [c=>c.activeLanguage='other',c=>c.grammarRequest++]){
  const x=setup();let finish;x.c.originalApi=()=>new Promise(resolve=>finish=resolve);const work=x.c.loadGrammar();mutate(x.c);
  finish({needs_task:true,definitions:x.data});await work;assert.equal(x.calls.length,0);assert.equal(x.draws.length,0);
 }
});
test('failed preparation publishes an error without completed usage counts',async()=>{
 const x=setup();x.c.window.corporiumRunTask=async()=>{throw Error('cancelled');};await assert.rejects(x.c.loadGrammar(),/cancelled/);
 assert.equal(x.published.at(-1).error,true);assert.equal(x.draws.length,1);
});
