const test=require('node:test'),assert=require('node:assert/strict'),fs=require('node:fs'),vm=require('node:vm');
test('morpheme candidates include available writings and all glosses, use writing fonts, and keep a bare form bare',()=>{
 const source=fs.readFileSync('web/word-structure.js','utf8'),c={writingTypes:[{id:'han',name:'汉字',font:'TestFont'}],esc:s=>String(s??'').replace(/[&<>"]/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;'}[c])),orthographyStyle:s=>s};vm.createContext(c);require('./display-spacing-helpers.js')(c);vm.runInContext(source.slice(source.indexOf('function wsRegistryGlosses'),source.indexOf('async function wsSearchRegistry')),c);
 const bare={id:'bare',form:'n',body:{readings:['n55']}},a={id:'m',form:'ma',display_number:2,body:{gloss:'母亲',senses:[{gloss:'母亲'},{gloss:'女性亲属'},{definition:'其他解释'}],writings:[{type_id:'han',text:'妈'},{type_id:'han',text:''}]}};
 const html=c.wsRegistryCandidate(a,'m');assert.match(html,/aria-pressed="true"/);assert.match(html,/font-family:TestFont/);assert.match(html,/妈/);assert.match(html,/母亲 \/ 女性亲属 \/ 其他解释/);assert.equal(c.wsRegistryLabel(bare),'n');assert.doesNotMatch(c.wsRegistryCandidate(bare,''),/n55|ws-candidate-gloss|ws-candidate-writing/);
 const unsafe=c.wsRegistryCandidate({id:'"x',form:'<bad>',body:{writings:[{text:'<img>'}],gloss:'<script>'}},'');assert.doesNotMatch(unsafe,/<bad>|<img>|<script>/);assert.match(unsafe,/&lt;img&gt;/);
});

function dragSetup(){
 const source=fs.readFileSync('web/quick-edit-rows.js','utf8'),lists={a:[],b:[]};let hit=null,done=0;for(const list of Object.values(lists))list.children=list;
 const c={drag:null,changed:()=>c.lexemeDirty=true,lexemeDirty:false,components:new Map(),document:{addEventListener(){},querySelectorAll:()=>Object.values(lists).flat().filter(r=>r.dataset.quickDrop),elementFromPoint:()=>hit},command:()=>({setAttribute(){},focus(){},setPointerCapture(){},hasPointerCapture(){return false;}})};vm.createContext(c);require('./display-spacing-helpers.js')(c);vm.runInContext(source.slice(source.indexOf(' function move('),source.indexOf(' function mountControl(')),c);
 function row(group,id){const r={id,dataset:{},parentElement:lists[group],classList:{add(){},remove(){}},querySelector:()=>({focus(){}}),closest:()=>null,getBoundingClientRect:()=>({top:50,height:40}),before(other){const p=r.parentElement;p.splice(p.indexOf(other),1);p.splice(p.indexOf(r),0,other);},after(other){const p=r.parentElement;p.splice(p.indexOf(other),1);p.splice(p.indexOf(r)+1,0,other);}};Object.defineProperty(r,'previousElementSibling',{get:()=>r.parentElement[r.parentElement.indexOf(r)-1]});Object.defineProperty(r,'nextElementSibling',{get:()=>r.parentElement[r.parentElement.indexOf(r)+1]});lists[group].push(r);return r;}
 const event=(x=20,y=20)=>({button:0,pointerId:1,clientX:x,clientY:y,preventDefault(){}});
 return {c,lists,row,event,handle:r=>c.grip(r,r,()=>done++,'语素'),hit:r=>hit={closest:()=>r},done:()=>done};
}
test('row dragging and arrow keys reorder the original component nodes, while cross-analysis drops and cancellation do nothing',()=>{
 const {c,lists,row,event,handle,hit,done}=dragSetup(),a=row('a','a'),b=row('a','b'),foreign=row('b','foreign'),h=handle(a);
 hit(b);h.onpointerdown(event());c.pointerMove(event(40,95));c.pointerUp(event());assert.deepEqual([...lists.a],[b,a]);assert.equal(c.lexemeDirty,true);assert.equal(done(),1);
 h.onkeydown({key:'ArrowUp',preventDefault(){}});assert.deepEqual([...lists.a],[a,b]);assert.equal(done(),2);
 hit(foreign);h.onpointerdown(event());c.pointerMove(event(40,95));c.pointerUp(event());assert.deepEqual([...lists.a],[a,b]);assert.equal(done(),2);
 hit(b);h.onpointerdown(event());c.pointerMove(event(40,95));c.cancelDrag();c.pointerUp(event());assert.deepEqual([...lists.a],[a,b]);assert.equal(done(),2);
});

function inputNavigation(){
 const source=fs.readFileSync('web/quick-edit-rows.js','utf8'),components=new Map(),lists=[{children:[]},{children:[]}];let focused=null,selected=null,enabled=true;
 const c={components,active:()=>enabled,lexemeDirty:false};vm.createContext(c);
 vm.runInContext(source.slice(source.indexOf(' function componentColumn('),source.indexOf(' function componentView(')),c);
 function row(list,index){
  const element={parentElement:lists[list]},view={writingInputs:new Map()};lists[list].children.push(element);
  function input(column){return {value:list+':'+index+':'+column,disabled:false,readOnly:false,hidden:false,closest:()=>element,getClientRects(){return this.hidden?[]:[{}];},focus(){focused=this;},select(){selected=this;}};}
  for(const name of ['form','readings','gloss'])view[name]=input(name);
  for(const type of ['han','latin'])view.writingInputs.set(type,input(type));
  components.set(element,view);return {element,view,input};
 }
 const rows=[row(0,0),row(0,1),row(0,2),row(0,3)],foreign=row(1,0);
 function key(input,key,extra={}){let prevented=false;focused=selected=null;c.verticalInput({target:input,key,preventDefault(){prevented=true;},...extra});return {focused,selected,prevented};}
 return {rows,foreign,lists,c,key,active:value=>enabled=value};
}
test('component Up and Down keep the input column, select the destination text, and never edit the draft',()=>{
 const {rows,c,key}=inputNavigation();
 for(const name of ['form','readings','gloss']){
  const values=rows.map(r=>r.view[name].value),down=key(rows[0].view[name],'ArrowDown');
  assert.equal(down.focused,rows[1].view[name]);assert.equal(down.selected,down.focused);assert.equal(down.prevented,true);
  assert.equal(key(rows[1].view[name],'ArrowUp').focused,rows[0].view[name]);
  assert.deepEqual(rows.map(r=>r.view[name].value),values);
 }
 assert.equal(c.lexemeDirty,false);
});
test('component writing navigation follows the writing-type identity and skips unavailable cells',()=>{
 const {rows,key}=inputNavigation(),type='han',field=r=>r.view.writingInputs.get(type);
 rows[1].view.writingInputs=new Map([...rows[1].view.writingInputs].reverse());
 assert.equal(key(field(rows[0]),'ArrowDown').focused,field(rows[1]));
 field(rows[1]).readOnly=true;rows[2].view.writingInputs.delete(type);
 assert.equal(key(field(rows[0]),'ArrowDown').focused,field(rows[3]));
 assert.equal(key(field(rows[3]),'ArrowUp').focused,field(rows[0]));
});
test('component navigation respects current DOM order, skips hidden or disabled inputs, and stays in its analysis',()=>{
 const {rows,foreign,lists,key}=inputNavigation();
 rows[1].view.readings.disabled=true;rows[2].view.readings.hidden=true;
 assert.equal(key(rows[0].view.readings,'ArrowDown').focused,rows[3].view.readings);
 const edge=key(rows[3].view.readings,'ArrowDown');assert.equal(edge.focused,null);assert.equal(edge.prevented,true);assert.notEqual(edge.focused,foreign.view.readings);
 lists[0].children=[rows[3].element,rows[0].element,rows[1].element,rows[2].element];
 assert.equal(key(rows[0].view.form,'ArrowUp').focused,rows[3].view.form);
});
test('component inputs preserve IME, modifier shortcuts, native selectors, search boxes, and inactive editors',()=>{
 const {rows,key,active}=inputNavigation(),input=rows[0].view.readings;
 for(const extra of [{isComposing:true},{keyCode:229},{ctrlKey:true},{altKey:true},{metaKey:true},{shiftKey:true},{defaultPrevented:true}]){
  const result=key(input,'ArrowDown',extra);assert.equal(result.focused,null);assert.equal(result.prevented,false);
 }
 for(const name of ['ArrowLeft','ArrowRight','Enter','Tab'])assert.equal(key(input,name).prevented,false);
 assert.equal(key(rows[0].input('registry-search'),'ArrowDown').prevented,false);
 assert.equal(key(rows[0].input('native-select'),'ArrowDown').prevented,false);
 active(false);assert.equal(key(input,'ArrowDown').prevented,false);
});
test('readonly linked component fields retain native focus and navigation behavior',()=>{
 const {rows,key}=inputNavigation(),input=rows[0].view.readings;input.readOnly=true;
 assert.equal(key(input,'ArrowDown').prevented,false);input.readOnly=false;input.disabled=true;
 assert.equal(key(input,'ArrowDown').prevented,false);
});
