const {test}=require('node:test'),assert=require('node:assert/strict'),fs=require('node:fs'),vm=require('node:vm');
const source=fs.readFileSync(require('node:path').join(__dirname,'../web/language-deletion.js'),'utf8');
function setup(options={}){
 const nodes={},calls=[],storage=new Map();let reloads=0;
 function node(id=''){
  const n={id,hidden:false,disabled:false,open:false,textContent:'',handlers:{},before(){},append(...children){for(const c of children)if(c.id)nodes[c.id]=c;},querySelector(){return node();},addEventListener(type,fn){this.handlers[type]=fn;},showModal(){this.open=true;},close(){this.open=false;this.handlers.close?.();},focus(){},click(){return this.onclick?.();},dblclick(){return this.ondblclick?.();}};
  return n;
 }
 const get=id=>nodes[id]||(nodes[id]=node(id));
 const pending={id:'target',name:'测试语言',revision:7,token:'proof',blockers:options.blockers||[],counts:{texts:1,entries:2,dictionary_examples:3,lexemes:4,morphemes:5,timeline_sessions:0,survey_nodes:0}};
 const ctx={document:{createElement:()=>node()},$:get,makeDialog:id=>get(id),openLanguage(lang){ctx.editingLanguage=lang;},editingLanguage:{id:'target',name:'测试语言',revision:7},infoDirty:false,inlineDrafts:new Map(),lexemeDirty:false,
  window:{location:{reload(){reloads++;}}},localStorage:{setItem:(k,v)=>storage.set(k,v)},sessionStorage:{setItem:(k,v)=>storage.set(k,v),getItem:()=>null,removeItem(){}},projectStorageKey:k=>'project:'+k,
  originalApi:async(path,body)=>{calls.push({path,body});if(path==='language-delete-preview')return options.preview?options.preview():pending;if(options.save)return options.save();return {name:'测试语言',backup:'before.sqlite3',next_language:'remaining'};}
 };
 vm.createContext(ctx);vm.runInContext(source,ctx);
 return {ctx,nodes,calls,storage,get,reloads:()=>reloads};
}
test('both buttons require a double click; a single click makes no request',async()=>{
 const s=setup();await s.get('delete-language').click();assert.equal(s.calls.length,0);
 await s.get('delete-language').dblclick();assert.equal(s.calls.length,1);assert.equal(s.get('language-delete-dialog').open,true);
 await s.get('confirm-language-delete').click();assert.equal(s.calls.length,1);
 await s.get('confirm-language-delete').dblclick();assert.equal(s.calls.length,2);assert.equal(s.calls[1].body.confirmed,true);assert.equal(s.calls[1].body.token,'proof');assert.equal(s.reloads(),1);assert.equal(s.storage.get('project:corpus-language'),'remaining');
});
test('cancel and a new-language editor never delete anything',async()=>{
 const s=setup();s.ctx.openLanguage();assert.equal(s.get('delete-language').hidden,true);
 s.ctx.openLanguage({id:'target',name:'测试语言',revision:7});assert.equal(s.get('delete-language').hidden,false);
 await s.get('delete-language').dblclick();s.get('cancel-language-delete').click();await s.get('confirm-language-delete').dblclick();assert.equal(s.calls.length,1);
});
test('blocked preview cannot be confirmed and unsaved drafts prevent preview',async()=>{
 const s=setup({blockers:['另一种语言']});await s.get('delete-language').dblclick();assert.equal(s.get('confirm-language-delete').disabled,true);await s.get('confirm-language-delete').dblclick();assert.equal(s.calls.length,1);
 const d=setup();d.ctx.inlineDrafts.set('sentence',{});await d.get('delete-language').dblclick();assert.equal(d.calls.length,0);assert.match(d.get('language-error').textContent,/保存或取消/);
});
test('slow preview and deletion cannot be submitted twice',async()=>{
 let finish;const saved=new Promise(r=>finish=r),s=setup({save:()=>saved});
 await s.get('delete-language').dblclick();const work=s.get('confirm-language-delete').dblclick();await s.get('confirm-language-delete').dblclick();assert.equal(s.calls.length,2);assert.equal(s.get('cancel-language-delete').disabled,true);
 finish({name:'测试语言',backup:'before.sqlite3',next_language:'all'});await work;assert.equal(s.reloads(),1);assert.equal(s.get('confirm-language-delete').disabled,true);
});
test('failed deletion retains the dialogs and requires a new preview',async()=>{
 const s=setup({save:()=>{throw Error('语言资料已变化');}});await s.get('delete-language').dblclick();await s.get('confirm-language-delete').dblclick();assert.equal(s.reloads(),0);assert.equal(s.get('language-delete-dialog').open,true);assert.equal(s.get('confirm-language-delete').disabled,true);assert.match(s.get('language-delete-error').textContent,/已变化/);
});
