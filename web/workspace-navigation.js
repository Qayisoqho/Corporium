// Restore each workspace only after every asynchronous workspace wrapper has rendered.
(()=>{
 const positions=new Map();
 const roots={survey:'survey-workspace',timeline:'timeline-workspace',corpus:'corpus-workspace',analysis:'analysis-workspace',dictionary:'dictionary-workspace',library:'example-library',grammar:'grammar-workspace'};
 const key=()=>activeLanguage+'\u0000'+workspace;
 window.corporiumDictionaryLocationKey=()=>JSON.stringify([window.dictionaryEntryKind?.()||'lexeme',window.dictionaryEntryKind?.()==='morpheme'?window.dictionaryMorphemeSelection?.():typeof dictionarySelection==='undefined'?null:dictionarySelection]);
 let exampleLocations=0,exampleHadTransition=false;
 // Track the operated word, including a sentence inside a scrolling timeline or
 // repeated survey evidence. A new user gesture always takes precedence.
 window.corporiumPreserveExampleLocation=async(source,work)=>{
  const owner=key(),selection=workspace==='dictionary'?window.corporiumDictionaryLocationKey():null,root=$(roots[workspace]);
  const current=()=>owner===key()&&(workspace!=='dictionary'||selection===window.corporiumDictionaryLocationKey());
  const cards=()=>root?[...root.querySelectorAll('.editable-example')].filter(el=>el.getClientRects().length):[];
  const matches=el=>el.dataset.exampleKind===source?.kind&&el.dataset.exampleId===source?.id;
  const card=source?.card?.isConnected&&matches(source.card)&&source.card.getClientRects().length?source.card:cards().find(matches);
  if(!card)return work();
  const identity=el=>({id:el.id,anchor:el.dataset.navigationAnchor});
  const lineage=[];for(let el=card.parentElement;el&&el!==root;el=el.parentElement)if(el.id||el.dataset.navigationAnchor)lineage.push(identity(el));
  const point=el=>Number.isInteger(source.word)?el.querySelectorAll('.words:not(.inline-words)>.word')[source.word]||el:el;
  const top=point(card).getBoundingClientRect().top,x=window.scrollX,y=window.scrollY;
  const containers=[];
  for(let el=card.parentElement;el&&el!==document.scrollingElement;el=el.parentElement){
   if(el.scrollHeight>el.clientHeight+1&&/(auto|scroll)/.test(getComputedStyle(el).overflowY)){
    const parent=el.id?null:el.parentElement?.closest('[id]'),trail=[];
    if(parent)for(let node=el;node!==parent;node=node.parentElement)trail.unshift([...node.parentElement.children].indexOf(node));
    containers.push({el,id:el.id,parentId:parent?.id,trail,selector:el.id?'':[...el.classList].map(c=>'.'+CSS.escape(c)).join(''),x:el.scrollLeft,y:el.scrollTop,offset:point(card).getBoundingClientRect().top-el.getBoundingClientRect().top});
   }
  }
  let interrupted=false;
  const interrupt=e=>{if(e.type!=='keydown'||['ArrowUp','ArrowDown','PageUp','PageDown','Home','End',' '].includes(e.key))interrupted=true;};
  const events=['wheel','touchmove','pointerdown','keydown'];for(const type of events)document.addEventListener(type,interrupt,{capture:true,passive:true});
  function target(){
   if(card.isConnected&&card.getClientRects().length)return point(card);
   let candidates=cards().filter(matches);
   for(const a of lineage){const scoped=candidates.filter(el=>{for(let p=el.parentElement;p&&p!==root;p=p.parentElement)if(a.anchor?p.dataset.navigationAnchor===a.anchor:p.id===a.id)return true;return false;});if(scoped.length){candidates=scoped;break;}}
   candidates.sort((a,b)=>Math.abs(point(a).getBoundingClientRect().top-top)-Math.abs(point(b).getBoundingClientRect().top-top));
   return candidates[0]?point(candidates[0]):null;
  }
  function put(){
   if(interrupted||!current())return;
   const anchor=target();
   for(const p of containers){let el=p.el.isConnected?p.el:p.id?$(p.id):null;
    if(!el&&p.parentId){const parent=$(p.parentId),matches=p.selector?parent?.querySelectorAll(p.selector):[];el=matches?.length===1?matches[0]:p.trail.reduce((node,index)=>node?.children[index],parent);}
    if(!el)continue;el.scrollLeft=p.x;el.scrollTop=p.y;if(anchor&&el.contains(anchor))el.scrollTop+=anchor.getBoundingClientRect().top-el.getBoundingClientRect().top-p.offset;
   }
   window.scrollTo({left:x,top:anchor?window.scrollY+anchor.getBoundingClientRect().top-top:y,behavior:'instant'});
  }
  if(!exampleLocations++)exampleHadTransition=document.documentElement.classList.contains('workspace-transition');document.documentElement.classList.add('workspace-transition');
  const observer=new MutationObserver(put);observer.observe(root,{childList:true,subtree:true});observer.observe(document.documentElement,{attributes:true,attributeFilter:['class']});
  const resize=typeof ResizeObserver==='undefined'?null:new ResizeObserver(put);resize?.observe(root);resize?.observe(card);for(const p of containers)resize?.observe(p.el);
  try{const result=await work();put();return result;}finally{
   await new Promise(resolve=>requestAnimationFrame(resolve));put();
   await new Promise(resolve=>requestAnimationFrame(resolve));put();
   observer.disconnect();resize?.disconnect();for(const type of events)document.removeEventListener(type,interrupt,true);
   if(!--exampleLocations&&!exampleHadTransition)document.documentElement.classList.remove('workspace-transition');
  }
 };
 // Undo waits for the outermost refresh, including derived views, before restoring.
 window.corporiumPreserveLocation=async work=>{
  const owner=key(),root=$(roots[workspace]),edge=$('workspace-toolbar')?.getBoundingClientRect().bottom||0;
  const candidates=()=>root?[...root.querySelectorAll('[data-navigation-anchor],article.entry[id],.editable-example[data-example-id]')].filter(el=>el.getClientRects().length):[];
  const anchors=candidates().filter(el=>el.getBoundingClientRect().bottom>edge).slice(0,3).map(el=>({id:el.id,anchor:el.dataset.navigationAnchor,example:el.dataset.exampleId,kind:el.dataset.exampleKind,top:el.getBoundingClientRect().top}));
  const x=window.scrollX,y=window.scrollY;
  const containers=[...document.querySelectorAll('[id]')].filter(el=>el!==document.scrollingElement&&el.getClientRects().length&&(el.scrollTop||el.scrollLeft)).map(el=>({id:el.id,x:el.scrollLeft,y:el.scrollTop}));
  const hadTransition=document.documentElement.classList.contains('workspace-transition');document.documentElement.classList.add('workspace-transition');
  function put(){
   if(owner!==key())return;
   for(const p of containers){const el=$(p.id);if(el){el.scrollTop=p.y;el.scrollLeft=p.x;}}
   const nodes=candidates();let target=null,previous=null;
   for(const a of anchors){target=nodes.find(el=>a.anchor?el.dataset.navigationAnchor===a.anchor:a.id?el.id===a.id:el.dataset.exampleId===a.example&&el.dataset.exampleKind===a.kind);if(target){previous=a;break;}}
   window.scrollTo({left:x,top:target?window.scrollY+target.getBoundingClientRect().top-previous.top:y,behavior:'instant'});
  }
  try{return await work();}finally{
   await new Promise(resolve=>requestAnimationFrame(resolve));put();
   await new Promise(resolve=>requestAnimationFrame(resolve));put();
   if(!hadTransition)document.documentElement.classList.remove('workspace-transition');
  }
 };
 function capture(){
  const root=$(roots[workspace]);
  if(!root||root.hidden||document.documentElement.dataset.home==='true')return;
  const edge=$('workspace-toolbar')?.getBoundingClientRect().bottom||0;
  const anchor=[...root.querySelectorAll('[data-navigation-anchor],article.entry[id]')].find(el=>el.getClientRects().length&&el.getBoundingClientRect().bottom>edge);
  positions.set(key(),{x:window.scrollX,y:window.scrollY,id:anchor?.id,anchor:anchor?.dataset.navigationAnchor,top:anchor?.getBoundingClientRect().top});
 }
 function restore(){
  const saved=positions.get(key());
  const root=$(roots[workspace]);
  const anchor=saved&&root&&[...root.querySelectorAll('[data-navigation-anchor],article.entry[id]')].find(el=>el.getClientRects().length&&(saved.anchor?el.dataset.navigationAnchor===saved.anchor:el.id===saved.id));
  window.scrollTo({left:saved?.x||0,top:anchor?window.scrollY+anchor.getBoundingClientRect().top-saved.top:saved?.y||0,behavior:'instant'});
 }
 const previous=setWorkspace;
 let pending=Promise.resolve();
 setWorkspace=function(name){
  // Serialize rapid tab clicks so a slower previous load cannot restore over a newer tab.
  const task=pending.then(async()=>{
   capture();document.documentElement.classList.add('workspace-transition');
   try{
    await previous(name);
    await new Promise(resolve=>requestAnimationFrame(resolve));
    restore();
    // Keep automatic anchoring disabled through the paint that follows the DOM replacement.
    await new Promise(resolve=>requestAnimationFrame(resolve));
    restore();
   }finally{document.documentElement.classList.remove('workspace-transition');}
  });
  pending=task.catch(()=>{});return task;
 };
})();
