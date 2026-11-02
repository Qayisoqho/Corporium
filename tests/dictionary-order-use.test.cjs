const test=require('node:test'),assert=require('node:assert/strict'),fs=require('node:fs'),vm=require('node:vm');
const source=fs.readFileSync('web/dictionary-organization.js','utf8');
function setup({fail=false,editingOrder=null}={}){
 const nodes={'order-name':{value:'Custom'},'order-alphabet':{value:'p p̄ b ḇ m t ṯ d ḏ n k ḵ g ḡ ṇ s z j r l w ’ h'},'order-case':{checked:false},'order-form':{}},saved=new Map(),calls=[];
 const c=vm.createContext({$:id=>nodes[id],activeLanguage:'ordos',owner:'ordos',managerLanguage:'ordos',order:'',dictionaryPage:5,editingOrder,localStorage:{setItem:(k,v)=>saved.set(k,v)},projectStorageKey:k=>'project:'+k,managerSafe:(_,fn)=>fn,
 api:async(path,body)=>{calls.push({path,body});if(fail)throw Error('save failed');return {id:editingOrder?.id||'scheme'};},changed:async()=>calls.push({refreshOrder:c.order,page:c.dictionaryPage}),editOrder:id=>calls.push({edit:id}),corporiumStatus:s=>calls.push({status:s})});
 vm.runInContext(source.match(/ function rememberOrder[^\n]+/)[0]+'\n'+source.match(/ \$\('order-form'\).onsubmit[^\n]+/)[0],c);
 return {c,saved,calls,save:()=>nodes['order-form'].onsubmit()};
}
for(const editingOrder of [null,{id:'existing',revision:2}])test(`${editingOrder?'editing':'creating'} a scheme applies it before reloading the first page`,async()=>{
 const h=setup({editingOrder});await h.save();const id=editingOrder?.id||'scheme';assert.equal(h.c.order,id);assert.equal(h.saved.get('project:dictionary-order:ordos'),id);assert.deepEqual(h.calls[1],{refreshOrder:id,page:1});assert.equal(h.calls[0].body.alphabet,'p p̄ b ḇ m t ṯ d ḏ n k ḵ g ḡ ṇ s z j r l w ’ h');
});
test('saving does not overwrite another language selection after a language switch',async()=>{
 const h=setup();h.c.activeLanguage=h.c.owner='other';h.c.order='other-order';await h.save();assert.equal(h.c.order,'other-order');assert.equal(h.c.dictionaryPage,5);assert.equal(h.saved.get('project:dictionary-order:ordos'),'scheme');assert.equal(h.saved.has('project:dictionary-order:other'),false);
});
test('failed save preserves the current order, page and stored choice',async()=>{
 const h=setup({fail:true});await assert.rejects(h.save(),/save failed/);assert.equal(h.c.order,'');assert.equal(h.c.dictionaryPage,5);assert.equal(h.saved.size,0);assert.equal(h.calls.length,1);
});
