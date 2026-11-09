const test=require('node:test'),assert=require('node:assert/strict'),fs=require('node:fs'),vm=require('node:vm');
const source=fs.readFileSync('web/workbench.js','utf8');
function editorHarness(){
 const calls=[],nodes={},editor={open:true,querySelector(selector){return {click:()=>calls.push(selector)};}};
 const input={focus:()=>calls.push('focus original input')};
 nodes['lexeme-editor']=editor;nodes['lexeme-variants']={lastElementChild:{querySelector:()=>input}};
 for(const id of ['add-variant','ws-add-analysis'])nodes[id]={click:()=>calls.push(id)};
 const c={dictionarySelection:'owner',editingLexeme:{id:'owner'},$:id=>nodes[id]};
 nodes['edit-lexeme']={onclick:async()=>{calls.push('original edit');if(c.wait)await c.wait;}};
 vm.createContext(c);vm.runInContext(source.slice(source.indexOf('  async function editReadingMorphology('),source.indexOf('  function readingMorphology(){')),c);
 return {c,calls,editor,nodes};
}
test('add form uses the current entry editor and writing tab, leaving existing fields authoritative',async()=>{
 const h=editorHarness(),original=h.nodes['lexeme-variants'];await h.c.editReadingMorphology('forms');
 assert.deepEqual(h.calls,['original edit','[data-lx-index="writing"]','add-variant','focus original input']);
 assert.equal(h.nodes['lexeme-variants'],original);
});
test('add analysis activates the original morphology panel and its existing add action',async()=>{
 const h=editorHarness();await h.c.editReadingMorphology('analysis');
 assert.deepEqual(h.calls,['original edit','[data-lx-index="morphology"]','[data-lx-open=analysis],[data-lx-add=analysis]','ws-add-analysis']);
});
test('a refused editor opening never adds a form or changes sections',async()=>{
 const h=editorHarness();h.editor.open=false;await h.c.editReadingMorphology('forms');assert.deepEqual(h.calls,['original edit']);
});
test('an entry change during asynchronous editor preparation never adds to the new entry',async()=>{
 const h=editorHarness();let release;h.c.wait=new Promise(r=>release=r);const pending=h.c.editReadingMorphology('forms');
 h.c.dictionarySelection='another';h.c.editingLexeme={id:'another'};release();await pending;assert.deepEqual(h.calls,['original edit']);
});
