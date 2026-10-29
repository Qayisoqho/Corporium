const test=require('node:test'),assert=require('node:assert/strict'),fs=require('node:fs'),vm=require('node:vm');

test('quick and full entry editors request entry-only morphemes on every result page',async()=>{
 const source=fs.readFileSync(require.resolve('../web/word-structure.js'),'utf8'),requests=[];
 const result={hidden:true,querySelectorAll:()=>[]},select={value:'',options:[]},button={disabled:false};
 const row={isConnected:true,querySelector:selector=>({'.ws-registry-query':{value:'话'},'.ws-registry-search':button,'.ws-registry-target':select,'.ws-registry-results':result})[selector]};
 const s={URLSearchParams,$:()=>({value:'current-language'}),api:async url=>{requests.push(new URL('http://local/'+url));return {items:[],total:0,page:2,pages:2};}};
 vm.createContext(s);vm.runInContext(source.slice(source.indexOf('async function wsSearchRegistry('),source.indexOf('function wsRegistryRealization(')),s);
 for(const page of [1,2])await s.wsSearchRegistry(row,page);
 assert.equal(button.disabled,false);assert.equal(result.hidden,false);
 for(const [n,url] of requests.entries()){
  assert.equal(url.searchParams.get('q'),'话');assert.equal(url.searchParams.get('language'),'current-language');
  assert.equal(url.searchParams.get('page'),String(n+1));assert.deepEqual(JSON.parse(url.searchParams.get('search')),{scope:'entry'});
 }
});

test('morpheme merge and conversion target pickers use the same entry-only scope',async()=>{
 const source=fs.readFileSync(require.resolve('../web/morphemes.js'),'utf8'),requests=[],nodes={query:{value:'话'},'morpheme-target':{},'merge-target':{}};
 const s={URLSearchParams,$:id=>nodes[id],targets:[],api:async url=>{requests.push(new URL('http://local/'+url));return {items:[]};},targetFormOptions(){}};
 vm.createContext(s);vm.runInContext(source.match(/async function targetSearch[^\n]+/)[0],s);
 for(const target of ['morpheme-target','merge-target'])await s.targetSearch(target,'query','current-language');
 assert.equal(requests.length,2);
 for(const url of requests){assert.equal(url.searchParams.get('q'),'话');assert.equal(url.searchParams.get('language'),'current-language');assert.deepEqual(JSON.parse(url.searchParams.get('search')),{scope:'entry'});}
});
