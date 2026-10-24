const test=require('node:test'),assert=require('node:assert/strict'),fs=require('node:fs'),vm=require('node:vm');
const source=fs.readFileSync('web/lexicon.js','utf8');
function setup(unlink){
 const boxes=Array.from({length:3},(_,i)=>({dataset:{exampleSelect:String(i)},checked:false,disabled:false}));
 const bars=Array.from({length:2},()=>{const all={checked:false,disabled:false},button={disabled:true};return {all,button,insertAdjacentHTML(){},querySelector:s=>s==='[data-example-all]'?all:button};});
 const single={dataset:{exampleUnlink:'1'},disabled:false},controls=[...boxes,...bars.flatMap(b=>[b.all,b.button]),single],section={isConnected:true,querySelectorAll:s=>s==='[data-example-select]'?boxes:s==='[data-example-page-actions]'?bars:s==='[data-example-unlink]'?[single]:controls};
 const errors=[],c=vm.createContext({dictSafe:fn=>async(...a)=>{try{return await fn(...a);}catch(e){errors.push(e);}},leaveSentenceDrafts:async()=>{}});
 vm.runInContext(source.slice(source.indexOf('function wireExampleSelection('),source.indexOf('function renderLexemeExamples(')),c);
 c.wireExampleSelection(section,[{id:'a'},{id:'b'},{id:'c'}],unlink);return {boxes,bars,single,errors};
}
test('page select-all and mixed states agree in both bars and pass only visible rows',async()=>{
 let chosen;const s=setup(async rows=>chosen=rows);
 s.bars[0].all.onchange({target:{checked:true}});assert.equal(s.boxes.filter(b=>b.checked).length,3);assert.equal(s.bars[1].all.checked,true);
 s.boxes[1].checked=false;s.boxes[1].onchange();assert.equal(s.bars[0].all.indeterminate,true);assert.equal(s.bars[1].all.checked,false);
 await s.bars[1].button.onclick();assert.deepEqual(Array.from(chosen,r=>r.id),['a','c']);
 s.bars[1].all.onchange({target:{checked:false}});assert.equal(s.bars[0].button.disabled,true);assert.equal(s.bars[0].all.indeterminate,false);
});
test('pending unlink coalesces clicks; failed requests preserve selection and enable retry',async()=>{
 let finish,calls=0;const s=setup(()=>{calls++;return new Promise((resolve,reject)=>finish=reject);});
 s.bars[0].all.onchange({target:{checked:true}});const first=s.bars[0].button.onclick();await Promise.resolve();
 await s.bars[1].button.onclick();assert.equal(calls,1);assert.equal(s.single.disabled,true);
 finish(Error('conflict'));await first;assert.equal(s.errors.length,1);assert.equal(s.boxes.filter(b=>b.checked).length,3);assert.equal(s.bars[0].button.disabled,false);
});
test('single-row unlink uses its own row and a new page starts with no selection',async()=>{
 let chosen;const s=setup(async rows=>chosen=rows);await s.single.onclick();assert.deepEqual(Array.from(chosen,r=>r.id),['b']);
 assert.equal(setup(async()=>{}).boxes.some(b=>b.checked),false);
});
