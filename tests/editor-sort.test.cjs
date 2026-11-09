const test=require('node:test'),assert=require('node:assert/strict'),fs=require('node:fs'),vm=require('node:vm');
const source=fs.readFileSync('web/workbench.js','utf8');
function setup(){
 const frames=new Map(),bodyClasses=new Set(),form={arranged:true,parentElement:null,querySelector:()=>({getBoundingClientRect:()=>({bottom:80})})};
 const state={inputs:0,hit:null,nextFrame:0,frames,bodyClasses,form};
 const scroller={scrollTop:0};
 const c={Event,Math,window:{innerHeight:700},$:()=>({offsetHeight:30}),getComputedStyle:()=>({overflowY:'visible'}),requestAnimationFrame:fn=>{const id=++state.nextFrame;frames.set(id,fn);return id;},cancelAnimationFrame:id=>frames.delete(id),document:{scrollingElement:scroller,elementFromPoint:()=>state.hit,body:{classList:{add:x=>bodyClasses.add(x),remove:x=>bodyClasses.delete(x)}}}};
 vm.createContext(c);vm.runInContext(source.slice(source.indexOf(' let editorSort=null;'),source.indexOf(' function decorateEditorSort(')),c);
 function list(){return {children:[],parentElement:form};}
 function row(parent,id,kind='sense',values={gloss:id}){
  const classes=new Set(),r={id,values,parentElement:parent,isConnected:true,kind,classList:{add:x=>classes.add(x),remove:x=>classes.delete(x),contains:x=>classes.has(x)},dataset:{},dispatchEvent:e=>{assert.equal(e.type,'input');assert.equal(e.bubbles,true);state.inputs++;},removeAttribute:name=>{if(name==='data-lx-drop')delete r.dataset.lxDrop;},matches:selector=>selector==='.'+kind+'-editor',closest:selector=>selector==='form'?form:selector==='.lx-arranged'?(form.arranged?form:null):selector==='.'+kind+'-editor'?r:kind==='sense'&&selector==='.usage-editor'?r.usage:null,getBoundingClientRect:()=>({top:100,height:100})};
  r.before=other=>{other.parentElement.children.splice(other.parentElement.children.indexOf(other),1);parent.children.splice(parent.children.indexOf(r),0,other);other.parentElement=parent;};
  r.after=other=>{other.parentElement.children.splice(other.parentElement.children.indexOf(other),1);parent.children.splice(parent.children.indexOf(r)+1,0,other);other.parentElement=parent;};
  Object.defineProperties(r,{nextElementSibling:{get:()=>parent.children[parent.children.indexOf(r)+1]||null},previousElementSibling:{get:()=>parent.children[parent.children.indexOf(r)-1]||null}});parent.children.push(r);return r;
 }
 function handle(){const captured=new Set();return {focuses:0,focus(){this.focuses++;},setPointerCapture:id=>captured.add(id),hasPointerCapture:id=>captured.has(id),releasePointerCapture:id=>captured.delete(id),closest:()=>form.arranged?form:null};}
 const event=(x=10,y=10,pointerId=1)=>({button:0,clientX:x,clientY:y,pointerId,preventDefault(){}});
 return {c,state,scroller,list,row,handle,event};
}
test('sense reordering keeps the exact rows, values and identities and dirties only a changed order',()=>{
 const s=setup(),list=s.list(),a=s.row(list,'s1'),b=s.row(list,'s2'),original=a.values;
 assert.equal(s.c.moveEditorRow(a,b,'before'),false);assert.equal(s.state.inputs,0);
 assert.equal(s.c.moveEditorRow(a,b,'after'),true);assert.deepEqual(list.children,[b,a]);assert.equal(a.values,original);assert.equal(a.id,'s1');assert.equal(s.state.inputs,1);
 assert.equal(s.c.moveEditorRow(a,b,'after'),false);assert.equal(s.state.inputs,1);
});
test('a sense cannot be moved into a different part of speech',()=>{
 const s=setup(),one=s.list(),two=s.list(),a=s.row(one,'s1'),b=s.row(two,'s2');
 for(const where of ['before','after'])assert.equal(s.c.moveEditorRow(a,b,where),false);
 assert.deepEqual(one.children,[a]);assert.deepEqual(two.children,[b]);assert.equal(s.state.inputs,0);
});
test('dragging a POS group moves its original nested senses as one unit',()=>{
 const s=setup(),list=s.list(),a=s.row(list,'u1','usage'),b=s.row(list,'u2','usage');a.senses=[{id:'s1',gloss:'one'},{id:'s2',gloss:'two'}];const senses=a.senses,grip=s.handle();
 s.state.hit=b;s.c.editorSortDown(s.event(),a,grip);s.c.editorSortMove(s.event(50,180));assert.equal(b.dataset.lxDrop,'after');s.c.editorSortUp(s.event(50,180));
 assert.deepEqual(list.children,[b,a]);assert.equal(a.senses,senses);assert.deepEqual(a.senses.map(x=>x.id),['s1','s2']);assert.equal(s.state.inputs,1);assert.equal(s.state.frames.size,0);assert.equal(s.state.bodyClasses.size,0);assert.equal(grip.hasPointerCapture(1),false);
});
test('pointer movement across a foreign usage clears a previous valid sense drop',()=>{
 const s=setup(),one=s.list(),two=s.list(),a=s.row(one,'s1'),b=s.row(one,'s2'),foreign=s.row(two,'s3'),grip=s.handle();
 s.state.hit=b;s.c.editorSortDown(s.event(),a,grip);s.c.editorSortMove(s.event(50,180));assert.equal(b.dataset.lxDrop,'after');
 s.state.hit=foreign;s.c.editorSortMove(s.event(50,180));assert.equal(b.dataset.lxDrop,undefined);s.c.editorSortUp(s.event(50,180));
 assert.deepEqual(one.children,[a,b]);assert.deepEqual(two.children,[foreign]);assert.equal(s.state.inputs,0);
});
test('clicks, another pointer and a cancelled drag leave the draft order unchanged',()=>{
 const s=setup(),list=s.list(),a=s.row(list,'a'),b=s.row(list,'b'),grip=s.handle();s.state.hit=b;
 s.c.editorSortDown(s.event(),a,grip);s.c.editorSortUp(s.event());assert.equal(s.state.inputs,0);
 s.c.editorSortDown(s.event(),a,grip);s.c.editorSortMove(s.event(50,180,2));s.c.editorSortUp(s.event(50,180,2));assert.equal(s.state.frames.size,0);
 s.c.editorSortMove(s.event(50,180));assert.equal(b.dataset.lxDrop,'after');s.c.clearEditorSort();s.c.editorSortUp(s.event());
 assert.deepEqual(list.children,[a,b]);assert.equal(s.state.inputs,0);assert.equal(grip.hasPointerCapture(1),false);assert.equal(b.dataset.lxDrop,undefined);
});
test('the editor autoscrolls while dragging near the visible edge and stops after cancellation',()=>{
 const s=setup(),list=s.list(),a=s.row(list,'a'),b=s.row(list,'b'),grip=s.handle();s.state.hit=b;
 s.c.editorSortDown(s.event(),a,grip);s.c.editorSortMove(s.event(40,660));const [id,frame]=[...s.state.frames][0];s.state.frames.delete(id);frame();
 assert.equal(s.scroller.scrollTop,14);assert.equal(s.state.frames.size,1);s.c.clearEditorSort();assert.equal(s.state.frames.size,0);assert.equal(s.state.inputs,0);
});
test('a row removed or moved by another editor action is never committed to a stale drag destination',()=>{
 const s=setup(),list=s.list(),a=s.row(list,'a'),b=s.row(list,'b'),grip=s.handle();s.state.hit=b;
 s.c.editorSortDown(s.event(),a,grip);s.c.editorSortMove(s.event(40,180));a.isConnected=false;s.c.editorSortUp(s.event(40,180));assert.equal(s.state.inputs,0);
 a.isConnected=true;s.c.editorSortDown(s.event(),a,grip);s.c.editorSortMove(s.event(40,180));a.parentElement=s.list();s.c.editorSortUp(s.event(40,180));assert.equal(s.state.inputs,0);
});
