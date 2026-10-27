const test=require('node:test'),assert=require('node:assert/strict'),fs=require('node:fs'),vm=require('node:vm');
test('morpheme candidates include available writings and all glosses, use writing fonts, and keep a bare form bare',()=>{
 const source=fs.readFileSync('web/word-structure.js','utf8'),c={writingTypes:[{id:'han',name:'汉字',font:'TestFont'}],esc:s=>String(s??'').replace(/[&<>"]/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;'}[c])),orthographyStyle:s=>s};vm.createContext(c);vm.runInContext(source.slice(source.indexOf('function wsRegistryGlosses'),source.indexOf('async function wsSearchRegistry')),c);
 const bare={id:'bare',form:'n',body:{readings:['n55']}},a={id:'m',form:'ma',display_number:2,body:{gloss:'母亲',senses:[{gloss:'母亲'},{gloss:'女性亲属'},{definition:'其他解释'}],writings:[{type_id:'han',text:'妈'},{type_id:'han',text:''}]}};
 const html=c.wsRegistryCandidate(a,'m');assert.match(html,/aria-pressed="true"/);assert.match(html,/font-family:TestFont/);assert.match(html,/妈/);assert.match(html,/母亲 \/ 女性亲属 \/ 其他解释/);assert.equal(c.wsRegistryLabel(bare),'n');assert.doesNotMatch(c.wsRegistryCandidate(bare,''),/n55|ws-candidate-gloss|ws-candidate-writing/);
 const unsafe=c.wsRegistryCandidate({id:'"x',form:'<bad>',body:{writings:[{text:'<img>'}],gloss:'<script>'}},'');assert.doesNotMatch(unsafe,/<bad>|<img>|<script>/);assert.match(unsafe,/&lt;img&gt;/);
});

function dragSetup(){
 const source=fs.readFileSync('web/quick-edit-rows.js','utf8'),lists={a:[],b:[]};let hit=null,done=0;for(const list of Object.values(lists))list.children=list;
 const c={drag:null,changed:()=>c.lexemeDirty=true,lexemeDirty:false,components:new Map(),document:{addEventListener(){},querySelectorAll:()=>Object.values(lists).flat().filter(r=>r.dataset.quickDrop),elementFromPoint:()=>hit},command:()=>({setAttribute(){},focus(){},setPointerCapture(){},hasPointerCapture(){return false;}})};vm.createContext(c);vm.runInContext(source.slice(source.indexOf(' function move('),source.indexOf(' function mountControl(')),c);
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
