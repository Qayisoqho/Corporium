const test=require('node:test'),assert=require('node:assert/strict'),fs=require('node:fs'),vm=require('node:vm');
const source=fs.readFileSync('web/workbench.js','utf8'),shared=source.slice(source.indexOf('function sentenceMenuPlacement('),source.indexOf('/* Shared reading workbench:'));
function harness(){
 const listeners={},frames=[],observed=[],doc={documentElement:{clientWidth:800,clientHeight:600},body:{},activeElement:null,addEventListener:(name,fn)=>listeners[name]=fn};
 const win={getComputedStyle:()=>({fontSize:'16px',overflowX:'visible',overflowY:'visible'}),requestAnimationFrame:fn=>{frames.push(fn);return frames.length;},addEventListener:(name,fn)=>listeners['window:'+name]=fn};
 const c=vm.createContext({document:doc,window:win,queueMicrotask,MutationObserver:class{constructor(fn){observed.push(fn);}observe(){}}});vm.runInContext(shared,c);const controller=c.createSentenceMenus();
 function makeMenu(top=300,height=420){
  const menu={dataset:{},open:false,isConnected:true,parentElement:doc.body,listeners:{},getBoundingClientRect:()=>({top,bottom:top+32,left:680,right:760,width:80,height:32}),addEventListener(name,fn){this.listeners[name]=fn;},contains(node){return node===this||node===summary||node===items||rows.includes(node);}};
  const summary={attrs:{},parentElement:menu,setAttribute(k,v){this.attrs[k]=v;},listeners:{},addEventListener(name,fn){this.listeners[name]=fn;},getBoundingClientRect:()=>({left:680,right:760,top,bottom:top+32,width:80,height:32}),focus(){doc.activeElement=this;}};
  const rows=Array.from({length:4},(_,index)=>({index,disabled:index===1,hidden:false,onclick(){this.clicks=(this.clicks||0)+1;},getClientRects:()=>[{}],focus(){doc.activeElement=this;}}));
  const items={id:'',dataset:{},style:{},attrs:{},listeners:{},open:false,shows:0,hides:0,scrollHeight:height-2,get clientHeight(){return Math.min(height,parseFloat(this.style.maxHeight)||height)-2;},querySelectorAll:()=>rows,contains:node=>node===items||rows.includes(node),setAttribute(k,v){this.attrs[k]=v;},addEventListener(name,fn){this.listeners[name]=fn;},matches(){return this.open;},showPopover(){this.open=true;this.shows++;},hidePopover(){this.open=false;this.hides++;},getBoundingClientRect(){return {width:220,height:Math.min(height,parseFloat(this.style.maxHeight)||height)};}};
  menu.querySelector=selector=>selector.includes('summary')?summary:items;controller.mount(menu);
  const open=()=>{menu.open=true;menu.listeners.toggle({target:menu});};return {menu,summary,items,rows,open};
 }
 return {c,doc,listeners,frames,observed,controller,makeMenu};
}
test('a menu near the top opens below; a menu near the bottom opens above',()=>{
 const h=harness(),viewport={width:800,height:600};
 const down=h.c.sentenceMenuPlacement({top:30,bottom:62,right:760},{width:220,height:420},viewport,8);assert.equal(down.up,false);assert.equal(down.top,70);
 const up=h.c.sentenceMenuPlacement({top:550,bottom:582,right:760},{width:220,height:420},viewport,8);assert.equal(up.up,true);assert.equal(up.top,122);
});
test('a tall menu is bounded to the larger available space instead of losing its first commands',()=>{
 const h=harness(),p=h.c.sentenceMenuPlacement({top:380,bottom:412,right:790},{width:300,height:900},{width:800,height:600},8);
 assert.equal(p.up,true);assert.equal(p.top,8);assert.equal(p.maxHeight,364);assert.ok(p.left>=8&&p.left+300<=792);
});
test('narrow and offset visual viewports constrain both edges',()=>{
 const h=harness(),p=h.c.sentenceMenuPlacement({top:200,bottom:248,right:390},{width:450,height:500},{left:20,top:90,width:320,height:400},12);
 assert.ok(p.left>=32);assert.equal(p.maxWidth,296);assert.ok(p.top>=102);assert.ok(p.top+Math.min(500,p.maxHeight)<=478);
});
test('floating preserves original action nodes and does not consume the first destructive click',()=>{
 const h=harness(),m=h.makeMenu(),original=m.rows[3];m.open();assert.equal(m.items.open,true);assert.equal(m.items.style.position,'fixed');assert.equal(m.rows[3],original);
 original.onclick();assert.equal(m.menu.open,true);original.onclick();assert.equal(original.clicks,2);assert.equal(m.items.attrs.popover,'manual');
});
test('arrow navigation skips disabled commands and Escape restores the trigger',()=>{
 const h=harness(),m=h.makeMenu();m.summary.listeners.keydown({key:'ArrowDown',preventDefault(){}});assert.equal(h.doc.activeElement,m.rows[0]);
 m.items.listeners.keydown({key:'ArrowDown',preventDefault(){}});assert.equal(h.doc.activeElement,m.rows[2]);
 m.items.listeners.keydown({key:'End',preventDefault(){}});assert.equal(h.doc.activeElement,m.rows[3]);
 h.listeners.keydown({key:'Escape',preventDefault(){},stopPropagation(){}});assert.equal(m.menu.open,false);assert.equal(m.items.open,false);assert.equal(h.doc.activeElement,m.summary);
});
test('opening a second menu closes the previous popover; detached triggers release it',()=>{
 const h=harness(),a=h.makeMenu(),b=h.makeMenu();a.open();b.open();assert.equal(a.menu.open,false);assert.equal(a.items.hides,1);assert.equal(b.menu.open,true);
 b.menu.isConnected=false;h.observed[0]();assert.equal(b.items.open,false);assert.equal(b.summary.attrs['aria-expanded'],'false');
});
test('scrolling the menu does not reposition or reset its internal scroll',()=>{
 const h=harness(),m=h.makeMenu(300,900);m.open();h.listeners.scroll({target:m.items});assert.equal(h.frames.length,0);
 h.listeners.scroll({target:h.doc.body});assert.equal(h.frames.length,1);
});
test('a freshly reopened menu starts at its first command',()=>{
 const h=harness(),m=h.makeMenu(300,900);m.open();m.items.scrollTop=200;h.controller.close();m.open();assert.equal(m.items.scrollTop,0);
});
test('scrolling a trigger out of view closes the floating menu',()=>{
 const h=harness(),m=h.makeMenu();m.open();m.summary.getBoundingClientRect=()=>({top:-60,bottom:-28,left:680,right:760,width:80,height:32});h.listeners['window:resize']();h.frames.shift()();assert.equal(m.items.open,false);
});
test('Tab leaving the disclosure closes it without stealing the new focus',async()=>{
 const h=harness(),m=h.makeMenu();m.open();const next={};h.doc.activeElement=next;m.menu.listeners.focusout();await Promise.resolve();assert.equal(m.menu.open,false);assert.equal(h.doc.activeElement,next);
});
test('the fixed-position fallback keeps the original event ancestry when popovers are unavailable',()=>{
 const h=harness(),m=h.makeMenu();delete m.items.showPopover;delete m.items.hidePopover;m.open();assert.equal(m.items.style.position,'fixed');assert.equal(m.menu.open,true);h.controller.close();assert.equal(m.menu.open,false);
});
