const test=require('node:test'),assert=require('node:assert/strict'),fs=require('node:fs'),vm=require('node:vm');
function setup(){
 const nodes=Object.fromEntries(['grammar-source','grammar-lower','grammar-issue','grammar-query','grammar-run'].map(id=>[id,{}]));let runs=0;
 nodes['grammar-run'].click=()=>runs++;
 const c={grammarPage:2,grammarFocus:'',grammarSafe:f=>f,loadGrammar(){},$:id=>nodes[id]};vm.createContext(c);
 const s=fs.readFileSync('web/grammar.js','utf8');vm.runInContext(s.slice(s.indexOf("for(const id of ['grammar-source'"),s.indexOf('const grammarSwitch')),c);
 return {nodes,runs:()=>runs,press(extra={}){const e={key:'Enter',isComposing:false,repeat:false,preventDefault(){this.defaultPrevented=true;},...extra};nodes['grammar-query'].onkeydown(e);return e;}};
}
test('Enter submits once and consumes its native activation before the task dialog opens',()=>{
 const h=setup();assert.equal(h.press().defaultPrevented,true);assert.equal(h.runs(),1);
 assert.equal(h.press({repeat:true}).defaultPrevented,true);assert.equal(h.runs(),1);
});
test('IME confirmation and ordinary typing do not start grammar checks',()=>{
 const h=setup();assert.ok(!h.press({isComposing:true}).defaultPrevented);assert.ok(!h.press({key:'a'}).defaultPrevented);assert.equal(h.runs(),0);
});
test('explicit recheck is fresh while Enter and pagination-style reloads may reuse a verified result',async()=>{
 const source=fs.readFileSync('web/grammar.js','utf8'),nodes={},loads=[];
 const c={grammarPage:3,grammarFocus:'',grammarFilterOnly:false,grammarSafe:f=>f,$:id=>nodes[id]??={},loadGrammar:async args=>loads.push(args)};
 vm.createContext(c);vm.runInContext(source.slice(source.indexOf("$('grammar-run').onclick"),source.indexOf('const grammarSwitch')),c);
 nodes['grammar-run'].click=()=>nodes['grammar-run'].onclick();
 await nodes['grammar-run'].onclick();assert.equal(loads.at(-1).fresh,true);
 nodes['grammar-query'].onkeydown({key:'Enter',isComposing:false,repeat:false,preventDefault(){}});await Promise.resolve();
 assert.equal(loads.at(-1).fresh,false);assert.equal(c.grammarPage,1);
 await nodes['grammar-run'].onclick();assert.equal(loads.at(-1).fresh,true);
});
