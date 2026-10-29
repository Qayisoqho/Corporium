const {test}=require('node:test'),assert=require('node:assert/strict'),vm=require('node:vm'),fs=require('node:fs');
function setup(nested=false){
 const listeners=new Map(),observers=[],classes=new Set(),scrolls=[];
 const c={activeLanguage:'one',workspace:'corpus',dictionarySelection:'lexeme',requestAnimationFrame:fn=>setImmediate(fn),getComputedStyle:()=>({overflowY:'auto'})};
 c.window={scrollX:0,scrollY:1400,scrollTo:p=>{c.window.scrollX=p.left;c.window.scrollY=p.top;scrolls.push(p);}};
 const page={};
 const root={id:'corpus-workspace',dataset:{},parentElement:page,scrollHeight:0,clientHeight:0,isConnected:true,getClientRects:()=>[{}]};
 let scroller={id:'nested',dataset:{},classList:['tl-editor-body'],parentElement:root,scrollHeight:3000,clientHeight:500,scrollLeft:15,scrollTop:300,isConnected:true,contains:n=>cards.some(el=>el===n||el.word===n),getBoundingClientRect:()=>({top:1200-c.window.scrollY})};
 root.closest=()=>root;Object.defineProperty(root,'children',{get:()=>[scroller]});c.CSS={escape:s=>s};
 const makeCard=(id='sentence',scope='occurrence')=>{
  const parent={id:'',dataset:{navigationAnchor:scope},parentElement:nested?scroller:root,scrollHeight:0,clientHeight:0};
  const card={id:'',dataset:{exampleKind:'corpus',exampleId:id},parentElement:parent,isConnected:true,y:nested?700:1500,getClientRects:()=>card.isConnected?[{}]:[],querySelectorAll:()=>[card.word],getBoundingClientRect:()=>({top:(nested?1200+card.y-scroller.scrollTop:card.y)-c.window.scrollY})};
  card.word={getBoundingClientRect:()=>({top:card.getBoundingClientRect().top+60})};return card;
 };
 let cards=[makeCard()];root.querySelectorAll=selector=>selector==='.tl-editor-body'?[scroller]:cards;root.getBoundingClientRect=()=>({top:0});
 c.$=id=>id==='corpus-workspace'?root:id==='nested'?scroller:null;
 c.document={scrollingElement:page,documentElement:{classList:{contains:x=>classes.has(x),add:x=>classes.add(x),remove:x=>classes.delete(x)}},addEventListener:(n,fn)=>{if(!listeners.has(n))listeners.set(n,new Set());listeners.get(n).add(fn);},removeEventListener:(n,fn)=>listeners.get(n)?.delete(fn)};
 c.MutationObserver=class{constructor(fn){this.fn=fn;observers.push(this);}observe(){}disconnect(){this.done=true;}};
 vm.createContext(c);vm.runInContext(fs.readFileSync('web/workspace-navigation.js','utf8'),Object.assign(c,{setWorkspace:async()=>{}}));
 return {c,root,scroller,makeCard,card:cards[0],classes,listeners,scrolls,notify:()=>observers.filter(o=>!o.done).forEach(o=>o.fn()),replace:next=>{cards=next;},replaceScroller:next=>{scroller=next;},gesture:(name,event={})=>listeners.get(name)?.forEach(fn=>fn({type:name,...event}))};
}
test('the operated word keeps its viewport offset through intermediate reflow and final sentence replacement',async()=>{
 const s=setup(),before=s.card.word.getBoundingClientRect().top;
 await s.c.window.corporiumPreserveExampleLocation({kind:'corpus',id:'sentence',word:0,card:s.card},async()=>{
  s.card.y+=400;s.notify();assert.equal(s.card.word.getBoundingClientRect().top,before);
  const next=s.makeCard();next.y=2400;s.card.isConnected=false;s.replace([next]);s.notify();assert.equal(next.word.getBoundingClientRect().top,before);
 });
 assert.equal(s.c.window.scrollY,2300);assert.equal(s.classes.size,0);assert.ok([...s.listeners.values()].every(fns=>fns.size===0));
});
test('timeline-style nested scrolling follows the sentence without moving the outer document',async()=>{
 const s=setup(true),before=s.card.word.getBoundingClientRect().top,y=s.c.window.scrollY;
 await s.c.window.corporiumPreserveExampleLocation({kind:'corpus',id:'sentence',word:0},async()=>{s.card.y+=260;s.scroller.scrollTop=0;s.scroller.scrollLeft=0;});
 assert.equal(s.card.word.getBoundingClientRect().top,before);assert.equal(s.scroller.scrollTop,560);assert.equal(s.scroller.scrollLeft,15);assert.equal(s.c.window.scrollY,y);
});
test('saving a timeline sentence restores a rebuilt internal scroller that has no id',async()=>{
 const s=setup(true);s.scroller.id='';const before=s.card.word.getBoundingClientRect().top;
 let replacement;
 await s.c.window.corporiumPreserveExampleLocation({kind:'corpus',id:'sentence',word:0},async()=>{
  s.scroller.isConnected=false;replacement={...s.scroller,isConnected:true,scrollTop:0};s.replaceScroller(replacement);s.card.isConnected=false;s.replace([s.makeCard()]);s.notify();
 });
 assert.equal(replacement.scrollTop,300);assert.equal(s.c.window.scrollY,1400);assert.equal(s.root.querySelectorAll('.editable-example')[0].word.getBoundingClientRect().top,before);
});
test('a repeated sentence follows the clicked evidence instance after replacement',async()=>{
 const s=setup(),other=s.makeCard('sentence','another');other.y=900;s.replace([other,s.card]);
 await s.c.window.corporiumPreserveExampleLocation({kind:'corpus',id:'sentence',word:0,card:s.card},async()=>{const next=s.makeCard();next.y=1800;s.card.isConnected=false;s.replace([other,next]);});
 assert.equal(s.c.window.scrollY,1700);
});
test('user scrolling and navigation take precedence over a delayed save',async()=>{
 for(const action of ['wheel','pointerdown','keydown','workspace','language','selection']){
  const s=setup();if(action==='selection')s.c.workspace='dictionary';
  if(action==='selection')s.c.$=id=>id==='dictionary-workspace'?s.root:null;
  await s.c.window.corporiumPreserveExampleLocation({kind:'corpus',id:'sentence'},async()=>{s.card.y+=500;s.c.window.scrollY=900;if(action==='workspace')s.c.workspace='library';else if(action==='language')s.c.activeLanguage='two';else if(action==='selection')s.c.dictionarySelection='other';else s.gesture(action,{key:'PageDown'});});
  assert.equal(s.c.window.scrollY,900,action);
 }
});
test('missing sources do not move unrelated examples and errors restore then release tracking',async()=>{
 const s=setup();await s.c.window.corporiumPreserveExampleLocation({kind:'independent',id:'missing'},async()=>{s.c.window.scrollY=100;});assert.equal(s.c.window.scrollY,100);
 s.c.window.scrollY=1400;await assert.rejects(s.c.window.corporiumPreserveExampleLocation({kind:'corpus',id:'sentence'},async()=>{s.card.y+=250;throw Error('save failed');}),/save failed/);
 assert.equal(s.c.window.scrollY,1650);assert.equal(s.classes.size,0);
});
test('a different morpheme selection or dictionary kind cancels the old location',async()=>{
 for(const change of ['selection','kind']){const s=setup();s.c.workspace='dictionary';s.c.$=id=>id==='dictionary-workspace'?s.root:null;let selected='m1',kind='morpheme';s.c.window.dictionaryEntryKind=()=>kind;s.c.window.dictionaryMorphemeSelection=()=>selected;
  await s.c.window.corporiumPreserveExampleLocation({kind:'corpus',id:'sentence'},async()=>{s.card.y+=300;s.c.window.scrollY=900;if(change==='selection')selected='m2';else kind='lexeme';});assert.equal(s.c.window.scrollY,900);
 }
});
test('overlapping location guards keep automatic anchoring disabled until the last guard completes',async()=>{
 const s=setup();let release;const pending=new Promise(resolve=>release=resolve);
 const first=s.c.window.corporiumPreserveExampleLocation({kind:'corpus',id:'sentence'},()=>pending);
 await s.c.window.corporiumPreserveExampleLocation({kind:'corpus',id:'sentence'},async()=>{});assert.ok(s.classes.has('workspace-transition'));
 release();await first;assert.equal(s.classes.size,0);
});
