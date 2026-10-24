const test=require('node:test'),assert=require('node:assert/strict'),fs=require('node:fs'),vm=require('node:vm');
test('analysis search failures and cancellations clear running text and unlock controls',async()=>{
 const source=fs.readFileSync('web/analysis-workspace.js','utf8'),start=source.indexOf('async function execute('),end=source.indexOf('async function loadResult()',start);
 for(const where of ['request','results','cancel']){
  const status={textContent:''},locks=[],c={busy:false,request:0,activeLanguage:'one',queryValue:()=>({}),$:()=>status,lock:value=>{c.busy=value;locks.push(value);},fillQuery(){},loadRecords:async()=>{}};
  c.api=async()=>{if(where==='cancel'){const e=Error('cancelled');e.name='AbortError';throw e;}if(where==='request')throw Error('offline');return{id:'id',query:{}};};c.loadResult=async()=>{throw Error('results unavailable');};
  vm.createContext(c);vm.runInContext(source.slice(start,end),c);await assert.rejects(c.execute());assert.doesNotMatch(status.textContent,/正在/);assert.deepEqual(locks,[true,false]);assert.equal(c.busy,false);
 }
});
test('survey example lookup replaces pending text on failure and allows a successful retry',async()=>{
 const source=fs.readFileSync('web/grammar-survey.js','utf8'),start=source.indexOf('let pickerRequest=0;'),end=source.indexOf("\n$('survey-picker-search').onclick=",start),nodes={};
 const node=id=>nodes[id]??={value:'',textContent:'',innerHTML:'',replaceChildren(){},querySelectorAll:()=>[]};
 const c={URLSearchParams,$:node,pickerPage:1,topPagination(){},esc:s=>s};c.api=async()=>{throw Error('offline');};vm.createContext(c);vm.runInContext(source.slice(start,end),c);
 await assert.rejects(c.picker(),/offline/);assert.doesNotMatch(node('survey-picker-results').textContent,/正在/);assert.match(node('survey-picker-results').textContent,/重试/);
 c.api=async()=>({items:[],page:1,pages:1});await c.picker();assert.match(node('survey-picker-results').innerHTML,/没有符合条件/);
});
