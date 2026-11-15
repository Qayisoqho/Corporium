const test=require('node:test'),assert=require('node:assert/strict'),fs=require('node:fs'),vm=require('node:vm');
const language=fs.readFileSync('web/languages.js','utf8'),home=fs.readFileSync('web/home.js','utf8');
const flush=async()=>{for(let i=0;i<12;i++)await Promise.resolve();};
const deferred=()=>{let resolve;return {promise:new Promise(r=>resolve=r),resolve:(...v)=>resolve(...v)};};

test('fast corpus startup waits for all scripts and uses the final typography/render/history wrappers',async()=>{
 const events={},calls=[],notice={textContent:''},c=vm.createContext({activeLanguage:'ordos',languageList:[],api:async()=>{calls.push('prefetch');return [{id:'other'}];},document:{readyState:'loading',addEventListener:(name,fn,options)=>{assert.equal(options.once,true);events[name]=fn;}},$:()=>notice,
  loadLanguages:async()=>{throw Error('early languages');},selectText:async()=>{throw Error('early renderer');},refreshUndo:async()=>{throw Error('early history');}});
 vm.runInContext(language.slice(language.indexOf('let initialLanguageCatalog='),language.indexOf('function refreshLanguageIPA')),c);
 await flush();assert.deepEqual(calls,['prefetch']);assert.equal(c.activeLanguage,'other');assert.equal(notice.textContent,'');
 c.loadLanguages=async()=>calls.push('languages+typography');c.selectText=async id=>calls.push('final renderer '+id);c.refreshUndo=async()=>calls.push('final history');
 events.DOMContentLoaded();await vm.runInContext('corpusReady',c);
 assert.deepEqual(calls,['prefetch','languages+typography','final renderer ','final history']);assert.equal(notice.textContent,'');
});

test('startup attached to an already parsed document runs once without waiting for a missed event',async()=>{
 let calls=0;const c=vm.createContext({activeLanguage:'ordos',languageList:[],api:async()=>{calls++;return [];},document:{readyState:'complete',addEventListener(){throw Error('already parsed');}},$:()=>({}),loadLanguages:async()=>calls++,selectText:async()=>calls++,refreshUndo:async()=>calls++});
 vm.runInContext(language.slice(language.indexOf('let initialLanguageCatalog='),language.indexOf('function refreshLanguageIPA')),c);
 await vm.runInContext('corpusReady',c);assert.equal(calls,4);
});

test('language selection is available early and the first UI read consumes its prefetched catalog once',async()=>{
 const events={},nodes={},calls=[];const c=vm.createContext({activeLanguage:'ordos',languageList:[],api:async()=>{calls.push('fetch');return [{id:'other'}];},document:{readyState:'loading',addEventListener:(name,fn)=>events[name]=fn},$:id=>nodes[id]??={value:'',innerHTML:''},localStorage:{setItem(){}},projectStorageKey:x=>x,languageOptions:()=>'',renderLanguage:()=>calls.push('render'),selectText:async()=>{},refreshUndo:async()=>{}});
 vm.runInContext(language.slice(language.indexOf('async function loadLanguages()'),language.indexOf('function renderLanguage()')),c);
 vm.runInContext(language.slice(language.indexOf('let initialLanguageCatalog='),language.indexOf('function refreshLanguageIPA')),c);
 await vm.runInContext('initialLanguageReady',c);assert.equal(c.activeLanguage,'other');assert.deepEqual(calls,['fetch']);
 events.DOMContentLoaded();await vm.runInContext('corpusReady',c);assert.deepEqual(calls,['fetch','render']);
 await c.loadLanguages();assert.deepEqual(calls,['fetch','render','fetch','render']);
});

for(const skip of [false,true])test(`home readiness includes language restoration, fonts and ${skip?'the skip choice':'the actual home content'}`,async()=>{
 const events={},corpus=deferred(),content=deferred(),fonts=deferred(),nodes={'home-skip':{checked:skip},'home-enter':{disabled:true}},calls=[];
 const doc={readyState:'loading',documentElement:{dataset:{appLoading:'true'}},fonts:{ready:Promise.resolve()},addEventListener:(name,fn)=>events[name]=fn};
 const c=vm.createContext({document:doc,window:{corporiumFontsReady:fonts.promise},$:id=>nodes[id]??={},restoreHomePlace:async()=>{await corpus.promise;calls.push('restore');},showHome:async()=>{calls.push('home');await content.promise;}});
 vm.runInContext(home.slice(home.indexOf('const homeRestored=')),c);
 await flush();assert.deepEqual(calls,[]);events.DOMContentLoaded();await flush();
 assert.deepEqual(calls,skip?[]:['home']);corpus.resolve();fonts.resolve();await flush();
 assert.equal(nodes['home-enter'].disabled,!skip);
 if(!skip){assert.equal(doc.documentElement.dataset.appLoading,'true');content.resolve();await flush();}
 assert.equal(doc.documentElement.dataset.appLoading,'false');assert.equal(nodes['home-enter'].disabled,false);
 if(skip)assert.equal(doc.documentElement.dataset.home,'false');
});
