const test=require('node:test'),assert=require('node:assert/strict'),fs=require('node:fs'),vm=require('node:vm');
function setup(){
 const elements=new Map(),writes=[],statuses=[];let pending,resolveWrite;
 function el(id){if(!elements.has(id))elements.set(id,{value:'',disabled:false,open:false,events:new Map(),append(){},addEventListener(n,f){this.events.set(n,f);},closest:()=>({open:true}),querySelector:()=>el('close'),showModal(){this.open=true;},close(){this.open=false;this.events.get('close')?.();}});return elements.get(id);}
 const c={window:{},workspace:'library',setWorkspace:async name=>{c.workspace=name;},document:{createElement:()=>el('button'),querySelector:()=>el('menu')},makeDialog(){},$:el,esc:x=>x,safe:f=>f,texts:[{id:'source',title:'Original'}],selected:'source',inlineDrafts:new Map(),loadTexts:async()=>{},clearFilters(){},selectText:async()=>{},corporiumStatus:x=>statuses.push(x),api:async(path,body)=>{if(!body)return {id:'source',title:'Original',language_id:'ordos',count:25,token:'token'};writes.push({path,body});return new Promise(resolve=>{resolveWrite=resolve;});}};
 vm.createContext(c);vm.runInContext(fs.readFileSync('web/text-copy.js','utf8'),c);
 return {c,el,writes,statuses,resolve:r=>resolveWrite(r)};
}
test('text copy coalesces repeated submission and preserves the reviewed source',async()=>{
 const {c,el,writes,resolve}=setup();await el('button').onclick();el('text-copy-title').value='My copy';
 const first=el('text-copy-form').onsubmit({preventDefault(){}});await el('text-copy-form').onsubmit({preventDefault(){}});
 assert.equal(writes.length,1);assert.equal(writes[0].path,'copy-text');assert.deepEqual(JSON.parse(JSON.stringify(writes[0].body)),{id:'source',token:'token',title:'My copy',_language:'ordos'});
 assert.equal(el('text-copy-source').disabled,true);resolve({id:'new'});await first;assert.equal(el('text-copy-dialog').open,false);assert.equal(el('text-copy-save').disabled,false);assert.equal(c.workspace,'corpus');
});
test('a failed post-save refresh reports a saved copy without issuing another creation',async()=>{
 const {c,el,writes,statuses,resolve}=setup();await el('button').onclick();c.selectText=async()=>{throw Error('offline');};
 const task=el('text-copy-form').onsubmit({preventDefault(){}});resolve({id:'new'});await task;
 assert.equal(writes.length,1);assert.equal(el('text-copy-dialog').open,false);assert.match(statuses[0],/副本已保存.*offline/);
 await el('text-copy-form').onsubmit({preventDefault(){}});assert.equal(writes.length,1);
});
test('late source previews cannot replace the most recently chosen text',async()=>{
 const {c,el}=setup();await el('button').onclick();const pending=new Map();c.api=path=>new Promise(resolve=>pending.set(path,resolve));
 el('text-copy-source').value='older';const old=el('text-copy-source').onchange();el('text-copy-source').value='newer';const latest=el('text-copy-source').onchange();
 pending.get('text-copy-preview?id=newer')({id:'newer',title:'Newer',count:3});await latest;
 pending.get('text-copy-preview?id=older')({id:'older',title:'Older',count:8});await old;
 assert.equal(el('text-copy-title').value,'Newer（副本）');assert.equal(el('text-copy-count').textContent,3);
});
