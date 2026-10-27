const test=require('node:test'),assert=require('node:assert/strict'),vm=require('node:vm'),fs=require('node:fs');
const source=fs.readFileSync('web/code-switching.js','utf8'),scope={};
vm.runInNewContext(source.slice(0,source.indexOf('window.CorporiumCodes')),scope);
test('audio dropdown selection is not a text draft; selecting text, code or notes is',()=>{
 const d={selected:new Set(),code:'',notes:'',dirty:true,interval:'audio'};
 assert.equal(scope.codeDraftChanged(d),false);
 for(const change of [{selected:new Set(['word'])},{code:'zh'},{notes:'quotation'}])assert.equal(scope.codeDraftChanged({...d,...change}),true);
});
test('editing a saved span compares identities without treating selection order as a change',()=>{
 const s={word_ids:['a','b'],code_id:'zh',notes:'quote'},d={selected:new Set(['b','a']),code:'zh',notes:'quote'};
 assert.equal(scope.codeDraftChanged(d,s),false);
 assert.equal(scope.codeDraftChanged({...d,selected:new Set(['a'])},s),true);
 assert.equal(scope.codeDraftChanged({...d,notes:''},s),true);
 assert.equal(scope.codeDraftChanged({...d,code:'ru'},s),true);
});
test('word picking supports both Shift directions, Ctrl toggling and a missing anchor',()=>{
 const ids=['a','b','c','d'],pick=(selected,a,b,shift=false,ctrl=false)=>Array.from(scope.codeWordSelection(ids,new Set(selected),a,b,shift,ctrl));
 assert.deepEqual(pick([],'b','d',true),['b','c','d']);
 assert.deepEqual(pick([],'d','a',true),ids);
 assert.deepEqual(pick([],'gone','c',true),['c']);
 assert.deepEqual(pick(['a','b'],'a','b',false,true),['a']);
 assert.deepEqual(pick(['a'],'a','c',false,true),['a','c']);
 assert.deepEqual(pick(['a','b'],'a','d'),['d']);
});
test('code writes refresh their own view after committing, without the generic workspace reload during saving',async()=>{
 const calls=[],panel={inert:false},s={kind:'independent',id:'one',editing:null,selected:new Set(['word']),code:'zh',notes:'',data:{token:'snapshot',owner_language:'ordos'},panel};
 const c={state:s,busy:false,read(){},originalApi:async(path,b)=>{calls.push({path,b});},api:async path=>{assert.ok(path.startsWith('code-detail?'));return {};},close(){c.state=null;},refresh:async()=>calls.push('refresh'),document:{querySelectorAll:()=>[]},workspace:'library',URLSearchParams,corporiumStatus(){}};
 vm.createContext(c);vm.runInContext(source.slice(source.indexOf(' async function apply('),source.indexOf(" document.addEventListener('click'")),c);
 await vm.runInContext("apply('save')",c);assert.equal(c.busy,false);assert.equal(calls[0].path,'code-save');assert.equal(calls[0].b._language,'ordos');assert.equal(calls[1],'refresh');
});

test('only the last word labels a code range, inline with its original rich gloss',()=>{
 const c={escape:s=>String(s).replaceAll('&','&amp;').replaceAll('<','&lt;').replaceAll('"','&quot;')};
 vm.createContext(c);vm.runInContext(source.slice(source.indexOf(' function word(w)'),source.indexOf(' function stats(s)')),c);
 const mark={name:'汉语',short:'ZH',notes:'<quote>',start:true,end:false};
 const rich='<span class="grammar-label">PST</span>';
 assert.equal(c.gloss({code_mark:mark},rich),rich);
 const html=c.gloss({code_mark:{...mark,start:false,end:true}},rich);
 assert.ok(html.includes('<span class="code-gloss-text">'+rich+'</span><span class="code-word-label"'));
 assert.ok(html.includes('>ZH</span>'));assert.ok(html.includes('&lt;quote>'));assert.ok(!html.includes('>·</span>'));
});
