// Keep large pages in memory while mounting only the visible portion of the list.
function dictionaryVisibleRange(offsets,top,height,buffer=8){
 const find=y=>{let a=0,b=offsets.length-1;while(a<b){const m=(a+b+1)>>1;if(offsets[m]<=y)a=m;else b=m-1;}return Math.min(a,offsets.length-2);};
 return [Math.max(0,find(Math.max(0,top))-buffer),Math.min(offsets.length-1,find(Math.max(0,top)+height)+buffer+1)];
}
// Flatten only visible branches before virtualization, retaining collapsed headings.
function dictionaryClassRows(items,collapsed){
 const visible=[];let previous=[];
 for(const item of items){
  const nodes=item.sort_path||[],keys=nodes.map(n=>n.key);let first=0;
  while(first<previous.length&&first<nodes.length&&previous[first].key===nodes[first].key)first++;
  let hidden=false;
  for(let depth=0;depth<nodes.length;depth++){
   const path=JSON.stringify(keys.slice(0,depth+1)),closed=collapsed.has(path);
   if(depth>=first)visible.push({dictionaryClass:{path,label:nodes[depth].label,depth,closed}});
   if(closed){hidden=true;break;}
  }
  if(!hidden)visible.push(item);previous=nodes;
 }
 return visible;
}
function renderDictionaryList(host,source,options){
 const {html,attribute,select,empty,transform}=options,items=transform?transform(source):source;
 // Navigation moves this host into the module sidebar after its first load.
 // Bind to that stable scroll surface even while the host is still in main.
 const scroller=document.getElementById('workbench-module-nav')||host,virtual=items.length>200;
 const scrollBefore=scroller.scrollTop;host.dictionaryViewport?.destroy();
 let frame=0,range='',offsets=[],heights=[],width=0,scale=0,closed=false;
 const selected=()=>window.dictionaryListSelectionChanged?.();
 const prefix=()=>{offsets=[0];for(const h of heights)offsets.push(offsets.at(-1)+h);};
 function reset(){scale=parseFloat(getComputedStyle(document.documentElement).fontSize);heights=items.map(x=>scale*(x.dictionaryClass?2.4:2.465+(x.body.homonym_note?.length?1.01:0)));prefix();range='';}
 function origin(){return host.getBoundingClientRect().top-scroller.getBoundingClientRect().top+scroller.scrollTop;}
 function paint(){
  frame=0;if(closed||host.hidden||!host.isConnected)return;
  if(!virtual){host.innerHTML=items.map(html).join('')||empty;selected();return;}
  const top=scroller.scrollTop-origin(),[start,end]=dictionaryVisibleRange(offsets,top,Math.max(200,scroller.clientHeight)),key=start+':'+end;
  if(key===range)return;range=key;
  host.style.paddingTop=offsets[start]+'px';host.style.paddingBottom=(offsets.at(-1)-offsets[end])+'px';
  host.innerHTML=items.slice(start,end).map((x,i)=>'<div class="dictionary-virtual-row" role="listitem" aria-posinset="'+(start+i+1)+'" aria-setsize="'+items.length+'" data-virtual-index="'+(start+i)+'">'+html(x)+'</div>').join('');
  const measured=[...host.children].map(el=>el.getBoundingClientRect().height);let changed=false;
  for(let i=start;i<end;i++)if(measured[i-start]>0&&Math.abs(measured[i-start]-heights[i])>.5){heights[i]=measured[i-start];changed=true;}
  if(changed){prefix();host.style.paddingTop=offsets[start]+'px';host.style.paddingBottom=(offsets.at(-1)-offsets[end])+'px';}
  selected();
 }
 function schedule(){if(!frame&&!closed)frame=requestAnimationFrame(paint);}
 const click=e=>{const row=e.target.closest('['+attribute+']');if(row&&host.contains(row))select(row.getAttribute(attribute));};
 function focusRow(index,checkbox=false){index=Math.max(0,Math.min(index,items.length-1));scroller.scrollTop=origin()+offsets[index]-Math.max(0,(scroller.clientHeight-heights[index])/2);range='';paint();const row=host.querySelector('[data-virtual-index="'+index+'"]');(row?.querySelector(checkbox?'input[type=checkbox]':'['+attribute+']')||row?.querySelector('button'))?.focus({preventScroll:true});}
 const keydown=e=>{
  if(!virtual||e.altKey||e.ctrlKey||e.metaKey)return;const row=e.target.closest('[data-virtual-index]');if(!row)return;const index=Number(row.dataset.virtualIndex),checkbox=e.target.matches('input[type=checkbox]');
  const delta={ArrowUp:-1,ArrowDown:1,PageUp:-Math.max(1,Math.floor(scroller.clientHeight/heights[index])-1),PageDown:Math.max(1,Math.floor(scroller.clientHeight/heights[index])-1)};
  let target=e.key==='Home'?0:e.key==='End'?items.length-1:e.key in delta?index+delta[e.key]:null;
  if(e.key==='Tab'&&!e.shiftKey&&index===Number(host.lastElementChild.dataset.virtualIndex)&&!checkbox&&index<items.length-1)target=index+1;
  if(e.key==='Tab'&&e.shiftKey&&index===Number(host.firstElementChild.dataset.virtualIndex)&&(checkbox||!host.querySelector('input[type=checkbox]'))&&index>0)target=index-1;
  if(target!==null){e.preventDefault();focusRow(target,e.key==='Tab'&&!e.shiftKey?!!host.querySelector('input[type=checkbox]'):checkbox);}
 };
 host.addEventListener('click',click);host.addEventListener('keydown',keydown);
 const resize=new ResizeObserver(()=>{if(width!==scroller.clientWidth||scale!==parseFloat(getComputedStyle(document.documentElement).fontSize)){width=scroller.clientWidth;reset();}schedule();});
 host.style.paddingTop=host.style.paddingBottom='';if(virtual)host.setAttribute('role','list');else host.removeAttribute('role');
 if(virtual){reset();host.style.minHeight=offsets.at(-1)+'px';scroller.scrollTop=scrollBefore;width=scroller.clientWidth;scroller.addEventListener('scroll',schedule,{passive:true});resize.observe(scroller);document.fonts?.addEventListener('loadingdone',schedule);}
 host.dictionaryViewport={destroy(){closed=true;if(frame)cancelAnimationFrame(frame);resize.disconnect();scroller.removeEventListener('scroll',schedule);document.fonts?.removeEventListener('loadingdone',schedule);host.removeEventListener('click',click);host.removeEventListener('keydown',keydown);},refresh(){range='';schedule();},rebuild(){renderDictionaryList(host,source,options);}};
 paint();host.style.minHeight='';
}
