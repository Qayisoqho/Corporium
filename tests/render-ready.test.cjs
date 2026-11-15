const test=require('node:test'),assert=require('node:assert/strict'),fs=require('node:fs'),vm=require('node:vm');
const {CorporiumViewBatch}=require('../web/render-ready.js');
const deferred=()=>{let resolve,reject;const promise=new Promise((a,b)=>{resolve=a;reject=b;});return {promise,resolve,reject};};
const tick=()=>new Promise(resolve=>setImmediate(resolve));
test('sentence preparation shares overlapping reads, batches only missing identities and bounds retained rows',async()=>{
 const calls=[],wait=deferred();const cache=new CorporiumViewBatch(async ids=>{calls.push(ids);await wait.promise;return Object.fromEntries(ids.map(id=>[id,{id}]));},{identity:()=>1,size:2,limit:3});
 const first=cache.get(['a','b','a']),second=cache.get(['b','c']);await tick();assert.deepEqual(calls,[['a','b'],['c']]);wait.resolve();
 assert.deepEqual(await first,{a:{id:'a'},b:{id:'b'}});await second;await cache.get(['d','e']);assert.equal(cache.values.size,3);
});
test('failed reads retry, and old pending reads cannot replace a newer project/revision',async()=>{
 let owner=1,calls=0;const first=deferred(),cache=new CorporiumViewBatch(async ids=>{calls++;if(owner===1)return first.promise;return {a:owner};},{identity:()=>owner});
 const old=cache.get(['a']);await tick();owner=2;assert.equal((await cache.get(['a'])).a,2);first.resolve({a:1});await old;assert.equal((await cache.get(['a'])).a,2);assert.equal(calls,2);
 let fail=true;const retries=new CorporiumViewBatch(async()=>{if(fail)throw Error('temporary');return {a:3};},{identity:()=>1});await assert.rejects(retries.get(['a']),/temporary/);fail=false;assert.equal((await retries.get(['a'])).a,3);
});
test('new unsaved sentence identities do not cause attachment requests',async()=>{
 const cache=new CorporiumViewBatch(()=>{throw Error('unexpected request');},{identity:()=>1});assert.deepEqual(await cache.get(['new:draft','',null]),{});
});
function lexemeSetup(){
 const source=fs.readFileSync('web/lexicon.js','utf8'),start=source.indexOf('async function showLexeme('),end=source.indexOf("  $('dictionary-detail').innerHTML=lexemeDetailHTML",start);
 const pending=new Map(),started=[],detail={innerHTML:'old entry',dataset:{},style:{}},selection={querySelectorAll:()=>[],querySelector:()=>null};
 const read=name=>{started.push(name);const d=deferred();pending.set(name,d);return d.promise;};
 const c={URLSearchParams,CSS:{escape:s=>s},$:id=>id==='dictionary-detail'?detail:selection,languageList:[],dictionarySelection:'old',exampleFormOwner:null,exampleForm:'all',exampleKind:'all',exampleRequest:0,dictionaryMissingNotice:'',displayedLexeme:null,displayedLexemeContext:null,clearDictionaryMissingNotice(){},languageTypographyCSS:()=>'',window:{corporiumPrepareLexeme:()=>read('sections'),corporiumPrepareFonts:()=>read('fonts'),corporiumPrepareEvidence:()=>read('accessories')},loadStandalonePage:()=>read('independent'),originalApi:()=>read('reference'),api:path=>path.startsWith('lexeme?id=')?Promise.resolve({id:'new',language_id:'test',revision:1,body:{variants:[]}}):read(path.split('?')[0])};
 vm.createContext(c);vm.runInContext(source.slice(start,end)+"  $('dictionary-detail').innerHTML=x.id;\n}",c);
 return {c,detail,pending,started,finish(){for(const [name,d] of pending)if(name!=='accessories')d.resolve({items:[]});}};
}
test('entry sections and fonts start together; the previous detail stays intact until all visible content is ready',async()=>{
 const h=lexemeSetup(),opening=h.c.showLexeme('new');await tick();assert.deepEqual(h.started,['morphology-options','lexeme-examples','independent','reference','sections','fonts']);assert.equal(h.detail.innerHTML,'old entry');h.finish();await tick();assert.equal(h.detail.innerHTML,'old entry');h.pending.get('accessories').resolve();await opening;assert.equal(h.detail.innerHTML,'new');
});
test('a superseded selection or failed request cannot commit a partial entry',async()=>{
 const h=lexemeSetup(),opening=h.c.showLexeme('new');await tick();h.finish();await tick();h.c.dictionarySelection='other';h.c.exampleRequest++;h.pending.get('accessories').resolve();await opening;assert.equal(h.detail.innerHTML,'old entry');
 const failed=lexemeSetup(),read=failed.c.showLexeme('new');await tick();failed.pending.get('independent').reject(Error('unavailable'));failed.finish();await assert.rejects(read,/unavailable/);assert.equal(failed.detail.innerHTML,'old entry');
});
