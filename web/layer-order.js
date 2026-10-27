/* Reorder definitions in their management window, never sentence input rows. */
(()=>{
 const host=$('layers-list');let rows=[],gesture=null,busy=false,frame=0;
 const text=(zh,en)=>document.documentElement.lang==='en'?en:zh;
 function clear(){cancelAnimationFrame(frame);gesture=null;host.querySelectorAll('[data-drop]').forEach(el=>delete el.dataset.drop);host.classList.remove('layer-dragging');}
 function target(x,y){const el=document.elementFromPoint(x,y)?.closest('#layers-list [data-layer-row]');if(!el)return null;const box=el.getBoundingClientRect();return {el,id:el.dataset.layerRow,after:y>box.top+box.height/2};}
 function highlight(){host.querySelectorAll('[data-drop]').forEach(el=>delete el.dataset.drop);if(!gesture?.moved)return;const hit=target(gesture.x,gesture.y);if(hit&&hit.id!==gesture.id)hit.el.dataset.drop=hit.after?'after':'before';}
 function scroll(){if(!gesture?.moved)return;const r=host.getBoundingClientRect();if(gesture.x>=r.left&&gesture.x<=r.right){host.scrollTop+=gesture.y<r.top+24?-8:gesture.y>r.bottom-24?8:0;highlight();}frame=requestAnimationFrame(scroll);}
 async function save(order,focus){
  if(busy||order.every((id,i)=>id===rows[i].id))return;
  busy=true;const language=layerLanguage,snapshot=rows.map(l=>({id:l.id,revision:l.revision}));host.setAttribute('aria-busy','true');
  try{
   const result=await api('layer-order',{order,snapshot,_language:language});
   window.corporiumInvalidateViews?.();
   if(layerLanguage!==language||!$('layers-dialog').open)return;
   await loadLayers();
   if(editingLayer){const fresh=result.layers.find(l=>l.id===editingLayer.id);if(fresh){editingLayer=fresh;$('layer-position').value=fresh.position;}}
   host.querySelector(`[data-layer-row="${CSS.escape(focus)}"] [data-layer-grip]`)?.focus({preventScroll:true});
   corporiumStatus(text('标注层顺序已保存，可撤销。','Layer order saved. You can undo it.'));
  }catch(error){await corporiumAlert(error.message);}
  finally{busy=false;host.removeAttribute('aria-busy');}
 }
 window.CorporiumLayerOrder={loaded(data){
  clear();rows=data;
  [...host.children].forEach((el,i)=>{if(!rows[i])return;el.dataset.layerRow=rows[i].id;el.classList.add('annotation-layer-row');const label=document.createElement('span');label.className='layer-row-label';for(const node of [...el.childNodes])if(node.nodeType===Node.TEXT_NODE)label.append(node);el.prepend(label);const grip=document.createElement('button');grip.type='button';grip.className='layer-drag-grip';grip.dataset.layerGrip='';grip.textContent='⠿';grip.title=text('上下拖动排序；也可用上下方向键','Drag to reorder, or use the Up and Down arrow keys');grip.setAttribute('aria-label',grip.title+' · '+rows[i].name);el.prepend(grip);});
 }};
 host.addEventListener('pointerdown',e=>{const grip=e.target.closest('[data-layer-grip]');if(!grip||e.button!==0||busy)return;e.preventDefault();grip.focus({preventScroll:true});grip.setPointerCapture(e.pointerId);gesture={pointer:e.pointerId,id:grip.parentElement.dataset.layerRow,x:e.clientX,y:e.clientY,start:e.clientY,moved:false};});
 host.addEventListener('pointermove',e=>{if(!gesture||gesture.pointer!==e.pointerId)return;gesture.x=e.clientX;gesture.y=e.clientY;if(!gesture.moved&&Math.abs(e.clientY-gesture.start)>5){gesture.moved=true;host.classList.add('layer-dragging');frame=requestAnimationFrame(scroll);}highlight();});
 host.addEventListener('pointerup',e=>{if(!gesture||gesture.pointer!==e.pointerId)return;const g=gesture,hit=target(e.clientX,e.clientY);clear();if(g.moved&&hit)void save(CorporiumOrder.move(rows.map(l=>l.id),[g.id],hit.id,hit.after),g.id);});
 host.addEventListener('pointercancel',clear);
 host.addEventListener('keydown',e=>{if(!e.target.closest('[data-layer-grip]'))return;if(e.key==='Escape'){clear();return;}if(!['ArrowUp','ArrowDown'].includes(e.key)||busy)return;e.preventDefault();const id=e.target.parentElement.dataset.layerRow,order=rows.map(l=>l.id),i=order.indexOf(id),j=i+(e.key==='ArrowUp'?-1:1);if(j<0||j>=order.length)return;[order[i],order[j]]=[order[j],order[i]];void save(order,id);});
 $('layers-dialog').addEventListener('close',clear);
})();
