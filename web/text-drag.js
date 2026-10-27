/* Pointer dragging moves text containers only; content and references stay intact. */
(() => {
 let dragging=null,pending=null,dropBusy=false,suppressClick=false,frame=0,point=null;
 const host=$('texts');
 setupSidebarTitlePan(host,{row:'[data-text]',mask:'.text-title-mask',text:'.text-title'});
 function enable(){host.querySelectorAll('[data-text]').forEach(el=>{el.draggable=false;el.dataset.textDraggable='true';el.title=(globalThis.CorporiumI18n?.f("13b45c5bfd1eb1",()=>[])??'拖动到文件夹，或拖到其他文本的上方或下方排序');});}
 const previous=renderFolders;renderFolders=function(){previous();enable();};enable();
 const snapshot=()=>texts.filter(t=>t.language_id===activeLanguage).map(t=>({id:t.id,folder_id:t.folder_id||'',revision:t.info_revision}));
 function clear(){document.querySelectorAll('.text-drop-before,.text-drop-after,.text-drop-folder').forEach(e=>e.classList.remove('text-drop-before','text-drop-after','text-drop-folder'));}
 function target(x,y){
  const node=document.elementFromPoint(x,y);if(!node)return null;const row=node.closest('#texts [data-text]');
  if(row){const t=texts.find(t=>t.id===row.dataset.text);if(!t)return null;if(t.id===dragging.id)return {node:row,style:'text-drop-before',folder_id:t.folder_id||'',before_id:t.id};const box=row.getBoundingClientRect(),after=y>box.top+box.height/2;const peers=texts.filter(a=>(a.folder_id||'')===(t.folder_id||'')&&a.id!==dragging.id);const index=peers.findIndex(a=>a.id===t.id);return {node:row,style:after?'text-drop-after':'text-drop-before',folder_id:t.folder_id||'',before_id:after?peers[index+1]?.id||null:t.id};}
  const folder=node.closest('#texts [data-folder-group]');return folder?{node:folder.querySelector('summary'),style:'text-drop-folder',folder_id:folder.dataset.folderGroup,before_id:null}:null;
 }
 function highlight(){clear();if(!dragging||!point)return;const t=target(point.x,point.y);if(t)t.node.classList.add(t.style);}
 function autoscroll(){
  if(!dragging||!point)return;
  const el=pending?.scroller;if(el){const r=el.getBoundingClientRect();if(point.x>=r.left&&point.x<=r.right){const delta=point.y<r.top+28?-10:point.y>r.bottom-28?10:0;if(delta){el.scrollTop+=delta;highlight();}}}
  frame=requestAnimationFrame(autoscroll);
 }
 function finish(){cancelAnimationFrame(frame);dragging=null;pending=null;point=null;clear();document.body.classList.remove('text-dragging');setTimeout(()=>suppressClick=false,0);}
 host.addEventListener('pointerdown',e=>{const row=e.target.closest('[data-text]');if(!row||e.button!==0)return;let scroller=row.parentElement;while(scroller&&!(scroller.scrollHeight>scroller.clientHeight&&/auto|scroll/.test(getComputedStyle(scroller).overflowY)))scroller=scroller.parentElement;pending={row,x:e.clientX,y:e.clientY,pointer:e.pointerId,scroller};});
 host.addEventListener('dragstart',e=>{if(e.target.closest('[data-text]'))e.preventDefault();});
 document.addEventListener('pointermove',e=>{
  if(!pending||e.pointerId!==pending.pointer||!e.buttons)return;
  if(!dragging){
   if(Math.hypot(e.clientX-pending.x,e.clientY-pending.y)<6)return;
   let error='';if(dropBusy)error=(globalThis.CorporiumI18n?.f("a74503a59862e9",()=>[])??'正在保存文本顺序，请稍后再拖动');else if(activeLanguage==='all')error=(globalThis.CorporiumI18n?.f("19212fc6633c4b",()=>[])??'请先在左侧选择一种语言，再拖动该语言下的文本');else if(infoDirty)error=(globalThis.CorporiumI18n?.f("93eb9c089047b5",()=>[])??'文本元信息尚未保存，请先保存元信息修改，再拖动文本');
   if(error){finish();corporiumAlert(error);return;}
   dragging={id:pending.row.dataset.text,language:activeLanguage,snapshot:snapshot()};pending.row.setPointerCapture(e.pointerId);suppressClick=true;document.body.classList.add('text-dragging');frame=requestAnimationFrame(autoscroll);
  }
  e.preventDefault();point={x:e.clientX,y:e.clientY};highlight();
 });
 document.addEventListener('pointerup',async e=>{
  if(!pending||e.pointerId!==pending.pointer)return;if(!dragging){finish();return;}
  e.preventDefault();const t=target(e.clientX,e.clientY),s=dragging;finish();
  if(!t){await corporiumAlert((globalThis.CorporiumI18n?.f("e8c2f527764542",()=>[])??'文本只能拖到左侧文本文件夹或其他文本的前后位置，不能拖入独立例句库。'));return;}
  if(t.before_id===s.id)return;dropBusy=true;
  try{if(activeLanguage!==s.language||infoDirty)throw Error((globalThis.CorporiumI18n?.f("cccc4630bc4ff7",()=>[])??'界面或元信息编辑状态已变化，请保存修改并刷新侧栏后重新拖动'));await api('organize-text',{id:s.id,folder_id:t.folder_id,before_id:t.before_id,snapshot:s.snapshot,_language:s.language});await loadTexts();corporiumStatus((globalThis.CorporiumI18n?.f("c2f73d4ad92428",()=>[])??'文本归属与顺序已保存，可撤销。'));}catch(err){await corporiumAlert(err.message);}finally{dropBusy=false;}
 });
 document.addEventListener('pointercancel',finish);
 host.addEventListener('click',e=>{if(suppressClick){e.preventDefault();e.stopImmediatePropagation();}},true);
})();
