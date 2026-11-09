const test=require('node:test'),assert=require('node:assert/strict'),vm=require('node:vm'),fs=require('node:fs');
const source=fs.readFileSync('web/workbench.js','utf8');
function card(id,top){
 const values=new Map(),classes=new Set(['entry']),footerValues=new Map();
 const a={id,nodeType:1,isConnected:true,top,offset:30,reads:0,actionWidth:80,classList:{contains:x=>classes.has(x),toggle:(x,on)=>on?classes.add(x):classes.delete(x)},style:{getPropertyValue:k=>values.get(k)||'',setProperty:(k,v)=>values.set(k,v)}};
 const number={getBoundingClientRect:()=>({width:18})},line={getBoundingClientRect:()=>{a.reads++;return {top:a.top+a.offset};}},footer={style:{getPropertyValue:k=>footerValues.get(k)||'',setProperty:(k,v)=>footerValues.set(k,v)},querySelector:()=>({getBoundingClientRect:()=>{a.reads++;return {width:a.actionWidth};}})};
 a.getClientRects=()=>{a.reads++;return [{}];};a.getBoundingClientRect=()=>{a.reads++;return {top:a.top};};a.querySelector=s=>s.includes('input[data-pick]')?{}:s===':scope>.entry-head>span'?null:s===':scope>.sentence-number'?number:s.startsWith('.editable-example')?line:null;a.querySelectorAll=()=>[footer];a.closest=()=>a;a.matches=()=>true;return {a,values,footerValues};
}
function setup(){
 const one=card('one',100),two=card('two',400),resize=[],mutations=[],frames=[],listeners=new Map(),root={};let scans=0;
 const list={nodeType:1,cards:[one.a,two.a],querySelectorAll(){scans++;return this.cards;},closest:()=>null};
 const c=vm.createContext({ResizeObserver:class{constructor(fn){this.fn=fn;resize.push(this);}observe(target){this.target=target;}disconnect(){this.disconnected=true;}},MutationObserver:class{constructor(fn){this.fn=fn;mutations.push(this);}observe(target){this.target=target;}}});
 const win={requestAnimationFrame:fn=>(frames.push(fn),frames.length),getComputedStyle:()=>({lineHeight:'20px',fontSize:'16px',paddingTop:'0'}),addEventListener:(name,fn)=>listeners.set(name,fn)},doc={documentElement:root,fonts:{ready:{then(fn){listeners.set('fonts',fn);}}}};
 vm.runInContext(source.slice(source.indexOf('function createSentenceMeasurements('),source.indexOf('(()=>{const lists=',source.indexOf('function createSentenceMeasurements('))),c);c.createSentenceMeasurements([list],doc,win);
 const flush=()=>{for(let i=0;frames.length&&i<10;i++)frames.shift()();assert.equal(frames.length,0);};flush();return {one,two,list,resize,mutations,flush,listeners,scans:()=>scans,root};
}
test('a resized sentence measures its own number/footer without rescanning unaffected cards',()=>{
 const h=setup(),bReads=h.two.a.reads,scans=h.scans();assert.equal(h.one.values.get('--sentence-pick-offset'),'40px');
 h.one.a.offset=44;h.one.a.actionWidth=121.2;h.two.a.top+=100;h.resize.find(o=>o.target===h.one.a).fn([{target:h.one.a}]);h.flush();
 assert.equal(h.one.values.get('--sentence-pick-offset'),'54px');assert.equal(h.one.footerValues.get('--sentence-actions-width'),'122px');assert.equal(h.two.values.get('--sentence-pick-offset'),'40px');assert.equal(h.two.a.reads,bReads);assert.equal(h.scans(),scans);
});
test('new and removed group/card subtrees update observer membership and keep existing measurements',()=>{
 const h=setup(),third=card('third',700),mutation=h.mutations.find(o=>o.target===h.list),before=h.one.a.reads;
 h.list.cards.push(third.a);mutation.fn([{target:h.list,addedNodes:[third.a],removedNodes:[]}]);h.flush();assert.equal(third.values.get('--sentence-pick-offset'),'40px');assert.equal(h.one.a.reads,before);
 h.two.a.isConnected=false;h.list.cards=h.list.cards.filter(n=>n!==h.two.a);mutation.fn([{target:h.list,addedNodes:[],removedNodes:[h.two.a]}]);h.flush();assert.equal(h.resize.find(o=>o.target===h.two.a).disconnected,true);
});
test('font, density and window changes invalidate all cards; local content changes stay local',()=>{
 const h=setup(),aReads=h.one.a.reads,bReads=h.two.a.reads;
 h.mutations.find(o=>o.target===h.list).fn([{target:h.one.a,addedNodes:[{nodeType:3}],removedNodes:[]}]);h.flush();assert.ok(h.one.a.reads>aReads);assert.equal(h.two.a.reads,bReads);
 h.listeners.get('resize')();h.flush();assert.ok(h.two.a.reads>bReads);const after=h.two.a.reads;h.listeners.get('fonts')();h.flush();assert.ok(h.two.a.reads>after);
});
