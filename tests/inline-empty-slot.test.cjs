const test=require('node:test'),assert=require('node:assert/strict'),fs=require('node:fs'),vm=require('node:vm');
const source=fs.readFileSync('web/inline-editor.js','utf8');
function setup(forms,workspace='corpus'){
 const d={words:forms.map((_,i)=>({id:'new:'+i})),body:{words:forms.map(form=>({form,gloss:''}))},cells:[],selectedSlot:'new:'+(forms.length-1),selectedSlots:new Set()},listeners={},removed=[];
 const card={dataset:{exampleKey:workspace+':entry'},querySelector:()=>null},nodes=d.words.map(w=>({dataset:{inlineSlot:w.id},closest:()=>card,contains:el=>el===w.id,remove(){removed.push(w.id);}}));
 const document={addEventListener:(event,fn)=>listeners[event]=fn,querySelectorAll:()=>nodes,querySelector:()=>null,activeElement:'translation'};
 const c=vm.createContext({document,inlineDrafts:new Map([[card.dataset.exampleKey,d]]),setTimeout:fn=>fn(),inlineSelection:()=>{}});
 vm.runInContext(source.slice(source.indexOf('function inlineSlotEmpty('),source.indexOf('function inlineFocus(')),c);
 vm.runInContext(source.slice(source.indexOf('function inlineRemove('),source.indexOf('function inlineMerge(')),c);
 vm.runInContext(source.slice(source.indexOf("document.addEventListener('focusout'"),source.indexOf('function inlineSplitSpaces(')),c);
 return {d,document,removed,blur:()=>listeners.focusout({target:{closest:s=>s==='.editable-example'?card:nodes.at(-1)}})};
}
test('moving to another field retains the last empty slot in every shared example editor',()=>{
 for(const workspace of ['corpus','library','dictionary','survey','timeline','analysis','grammar'])for(const forms of [[''],['word','']]){
  const h=setup(forms,workspace);h.blur();h.blur();assert.equal(h.d.words.length,forms.length,workspace);assert.deepEqual(h.removed,[]);assert.equal(h.d.dirty,undefined);
 }
});
test('surplus trailing blanks collapse to one, preserving its identity and selection',()=>{
 for(const forms of [['','',''],['word','','','']]){
  const h=setup(forms);h.blur();const kept=forms[0]?2:1;assert.equal(h.d.words.length,kept);assert.equal(h.d.selectedSlot,h.d.words.at(-1).id);assert.equal(h.d.body.words.at(-1).form,'');h.blur();assert.equal(h.d.words.length,kept);
 }
});
test('focus, open dialogs, saving and drag mode protect empty fields',()=>{
 for(const protect of [h=>h.document.activeElement='new:1',h=>h.document.querySelector=()=>({}),h=>h.d.saving=true,h=>h.d.dragEnabled=true]){const h=setup(['','']);protect(h);h.blur();assert.equal(h.d.words.length,2);}
});
test('saved slots, annotations and analysis are not discarded as surplus blanks',()=>{
 for(const protect of [h=>h.d.words[1].id='saved',h=>h.d.words[1].protected=true,h=>h.d.body.words[1].gloss='N',h=>h.d.cells.push({unit_id:'new:1',value:'note'}),h=>h.d.body.words[1].redup_id='r',h=>h.d.body.words[1].morph_groups=[{}],h=>h.d.body.words[1].infix_confirmation={}]){const h=setup(['','']);protect(h);h.blur();assert.equal(h.d.words.length,2);}
 const h=setup(['','word','']);h.blur();assert.equal(h.d.words.length,3);
});
