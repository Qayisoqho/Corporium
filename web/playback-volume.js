/* Personal playback preferences. Never change recordings or corpus content. */
(()=>{
 'use strict';
 const ui=(zh,en)=>globalThis.CorporiumI18n?.ui(zh,en)??zh;
 const percent=value=>value===null||value===''||!Number.isFinite(Number(value))?100:Math.round(Math.max(0,Math.min(100,Number(value))));
 const sentence=(id,textId)=>({key:'sentence:'+id,parent:textId&&textId!=='@independent'?'text:'+textId:null,label:ui('句子音量','Sentence volume')});
 const recording=(kind,id,itemId)=>kind==='independent'?sentence('independent:'+id):({key:JSON.stringify(['recording',kind,id,itemId]),label:ui('录音音量','Recording volume')});
 function timelineContext(interval,range,sessionId){return interval?.entry_id&&range&&Math.abs(range[0]-interval.start_ms)<1&&Math.abs(range[1]-interval.end_ms)<1?sentence(interval.entry_id,interval.text_id):{key:'timeline:'+sessionId,label:ui('时间轴音量','Timeline volume')};}
 function createStore(storage,prefix){
  const memory=new Map(),listeners=new Set();
  function get(key){let raw=memory.get(key);if(!memory.has(key))try{const saved=storage?.getItem(prefix+key);if(saved!==null&&saved!==undefined)raw=JSON.parse(saved);}catch{}return {percent:percent(raw?.percent),muted:raw?.muted===true};}
  function notify(){for(const fn of listeners)fn();}
  function set(key,value){const next={...get(key),...value};next.percent=percent(next.percent);next.muted=next.muted===true;memory.set(key,next);try{storage?.setItem(prefix+key,JSON.stringify(next));}catch{}notify();}
  const factor=key=>{const v=get(key);return v.muted?0:v.percent/100;};
  return {get,set,notify,reload(){memory.clear();notify();},subscribe(fn){listeners.add(fn);return()=>listeners.delete(fn);},effective(context){return context?factor(context.key)*(context.parent?factor(context.parent):1):1;},reset(key){set(key,{percent:100,muted:false});},toggle(key){const v=get(key);set(key,v.percent===0?{percent:100,muted:false}:{muted:!v.muted});}};
 }
 if(typeof module!=='undefined'&&module.exports)module.exports={percent,sentence,recording,timelineContext,createStore};
 if(typeof document==='undefined')return;
 const prefix=(typeof projectStorageKey==='function'?projectStorageKey('corporium-playback-volume-v1'):'corporium-playback-volume-v1')+':';
 let storage;try{storage=localStorage;}catch{}
 const store=createStore(storage,prefix),bindings=new WeakMap(),players=new Map(),inline=new Set();
 const icon=muted=>'<svg viewBox="0 0 24 24" width="18" height="18" fill="none" stroke="currentColor" stroke-width="1.6" aria-hidden="true"><path d="M4 9h4l5-4v14l-5-4H4z"/>'+(muted?'<path d="m17 9 5 6m0-6-5 6"/>':'<path d="M16 8q4 4 0 8m3-11q7 7 0 14"/>')+'</svg>';
 function bind(media,context){players.set(media,context);media.muted=false;media.volume=store.effective(context);}
 function unbind(media){players.delete(media);}
 function button(label,text){const el=document.createElement('button');el.type='button';el.title=label;el.setAttribute('aria-label',label);el.textContent=text;return el;}
 function controls(root,getContext,vertical=false){
  root.classList.add('playback-volume');root.setAttribute('role','group');
  const mute=button(ui('静音','Mute'),''),slider=document.createElement('input'),output=document.createElement('output'),reset=button(ui('恢复默认音量（100%）','Reset volume (100%)'),'↺');
  slider.type='range';slider.min='0';slider.max='100';slider.step='1';if(vertical)slider.setAttribute('aria-orientation','vertical');
  output.className='playback-volume-value';root.append(mute,slider,output,reset);
  function refresh(){const context=getContext();if(!context)return;const value=store.get(context.key),silent=value.muted||value.percent===0;root.setAttribute('aria-label',context.label);slider.setAttribute('aria-label',context.label);slider.title=context.label;slider.value=value.percent;output.textContent=(value.muted?0:value.percent)+'%';mute.innerHTML=icon(silent);mute.setAttribute('aria-pressed',String(silent));const label=silent?ui('取消静音','Unmute'):ui('静音','Mute');mute.title=label;mute.setAttribute('aria-label',label);root.title=context.parent?ui('句子音量 × 文本音量；当前播放：','Sentence volume × text volume; effective volume: ')+Math.round(store.effective(context)*100)+'%':context.label;}
  slider.oninput=()=>{const context=getContext();if(context)store.set(context.key,{percent:slider.value,muted:false});};
  mute.onclick=()=>{const context=getContext();if(context)store.toggle(context.key);};
  reset.onclick=()=>{const context=getContext();if(context)store.reset(context.key);};
  refresh();return {root,slider,refresh};
 }
 let popup=null,anchor=null,popupControls=null,closeTimer=null,dragging=false,suppressFocus=false;
 function close(){clearTimeout(closeTimer);if(!popup)return;anchor?.setAttribute('aria-expanded','false');popup.remove();popup=null;anchor=null;popupControls=null;dragging=false;}
 function position(){if(!popup||!anchor?.isConnected){close();return;}const r=anchor.getBoundingClientRect();if(!r.width||!r.height){close();return;}const p=popup.getBoundingClientRect(),gap=5,width=document.documentElement.clientWidth,height=document.documentElement.clientHeight;popup.style.left=Math.max(6,Math.min(width-p.width-6,r.right+gap+p.width<=width?r.right+gap:r.left-p.width-gap))+'px';popup.style.top=Math.max(6,Math.min(height-p.height-6,r.top))+'px';}
 function postpone(){clearTimeout(closeTimer);closeTimer=setTimeout(()=>{if(!dragging&&!anchor?.matches(':hover')&&!popup?.matches(':hover')&&!popup?.contains(document.activeElement))close();},280);}
 function open(target){const context=bindings.get(target);if(!context)return;clearTimeout(closeTimer);if(anchor===target){popupControls.refresh();return;}close();anchor=target;popup=document.createElement('div');popup.className='playback-volume-popup';popup.id='playback-volume-popup';popup.setAttribute('popover','manual');popupControls=controls(popup,context,true);document.body.append(popup);if(popup.showPopover)popup.showPopover();else (target.closest('dialog[open]')||document.body).append(popup);target.setAttribute('aria-expanded','true');target.setAttribute('aria-controls',popup.id);popup.addEventListener('pointerenter',()=>clearTimeout(closeTimer));popup.addEventListener('pointerleave',postpone);popup.addEventListener('focusout',postpone);popup.addEventListener('pointerdown',()=>{dragging=true;});popup.addEventListener('click',e=>e.stopPropagation());position();}
 function mount(target,getContext){if(!target)return;bindings.set(target,getContext);target.dataset.playbackVolume='true';target.setAttribute('aria-expanded','false');target.addEventListener('pointerenter',()=>open(target));target.addEventListener('pointerleave',postpone);target.addEventListener('focus',()=>{if(!suppressFocus)open(target);});target.addEventListener('blur',postpone);target.addEventListener('keydown',e=>{if(['ArrowUp','ArrowDown'].includes(e.key)||e.key==='Tab'&&!e.shiftKey&&anchor===target){e.preventDefault();open(target);popupControls.slider.focus();}});}
 function mountInline(root,getContext){const c=controls(root,getContext);inline.add(c);return c.refresh;}
 store.subscribe(()=>{for(const [media,context] of players)media.volume=store.effective(context);popupControls?.refresh();for(const c of inline){if(c.root.isConnected)c.refresh();else inline.delete(c);}});
 window.addEventListener('storage',e=>{if(e.key===null||e.key.startsWith(prefix))store.reload();});
 document.addEventListener('pointerup',()=>{dragging=false;postpone();});document.addEventListener('pointercancel',()=>{dragging=false;postpone();});
 document.addEventListener('pointerdown',e=>{if(popup&&!popup.contains(e.target)&&e.target!==anchor)close();},true);
 document.addEventListener('keydown',e=>{if(e.key==='Escape'&&popup){e.preventDefault();e.stopPropagation();const target=anchor;close();suppressFocus=true;target?.focus({preventScroll:true});suppressFocus=false;}},true);
 document.addEventListener('scroll',position,true);window.addEventListener('resize',position);
 new MutationObserver(()=>{if(anchor&&(!anchor.isConnected||!anchor.getClientRects().length))close();}).observe(document.body,{childList:true,subtree:true});
 window.CorporiumVolume={...store,sentence,recording,timelineContext,bind,unbind,mount,mountInline,close};
})();
