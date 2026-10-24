const {test}=require('node:test'),assert=require('node:assert/strict'),fs=require('node:fs'),vm=require('node:vm');
const source=fs.readFileSync('web/analysis-workspace.js','utf8');
test('analysis scope form declares unique control IDs',()=>{
 const panel={innerHTML:''};vm.runInNewContext(source.slice(source.indexOf('panel.innerHTML='),source.indexOf('function safeAnalysis')),{panel,dimensionNames:{},options:()=>''});
 const ids=Array.from(panel.innerHTML.matchAll(/\bid="([^"]+)"/g),m=>m[1]);
 assert.equal(new Set(ids).size,ids.length);
 assert.ok(ids.includes('analysis-code-mode'));assert.ok(ids.includes('analysis-code-id'));
});
test('code scope survives saved query round trips and missing catalog entries never broaden it',()=>{
 const els=new Map(),get=id=>{if(!els.has(id))els.set(id,{tagName:'SELECT',value:'',options:[{value:''}],add(option){this.options.push(option);},querySelectorAll:()=>[]});return els.get(id);};
 const context={$:get,renderPeople(){},updateScopeLabel(){},Option:class{constructor(label,value){this.label=label;this.value=value;}}};
 vm.createContext(context);vm.runInContext('let legacyScope={};'+source.slice(source.indexOf('function scopeValue()'),source.indexOf('function renderPeople(')),context);
 vm.runInContext(source.slice(source.indexOf('function setScope('),source.indexOf('function fillQuery(')),context);
 context.setScope({source:'all',code_mode:'mixed',code_id:'removed-code'});
 assert.equal(context.scopeValue().code_id,'removed-code');assert.equal(context.scopeValue().code_mode,'mixed');
 assert.ok(get('analysis-code-id').options.some(o=>o.value==='removed-code'&&o.label.includes('不会自动扩大')));
 context.setScope({source:'all'});assert.equal(context.scopeValue().code_id,'');assert.equal(context.scopeValue().code_mode,'');
});
