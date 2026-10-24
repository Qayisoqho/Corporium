// Restore each workspace only after every asynchronous workspace wrapper has rendered.
(()=>{
 const positions=new Map();
 const roots={survey:'survey-workspace',timeline:'timeline-workspace',corpus:'corpus-workspace',analysis:'analysis-workspace',dictionary:'dictionary-workspace',library:'example-library',grammar:'grammar-workspace'};
 const key=()=>activeLanguage+'\u0000'+workspace;
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
