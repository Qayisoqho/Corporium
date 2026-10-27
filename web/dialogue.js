/* A time-ordered projection of a text. Never writes the text's sentence order. */
(()=>{
 const root=$('corpus-workspace'),bar=document.createElement('div'),view=document.createElement('section');
 bar.id='dialogue-controls';bar.innerHTML=(globalThis.CorporiumI18n?.f("564534663eecef",()=>[])??'<label><input id="dialogue-enabled" type="checkbox"> 对话视图</label><label id="dialogue-axis-label" hidden>依据时间轴 <select id="dialogue-axis" aria-label="对话视图时间轴"></select></label><label id="dialogue-color-label" hidden><input id="dialogue-colors" type="checkbox"> 区分发言人颜色</label><button id="dialogue-refresh" hidden>刷新对话</button>');
 view.id='dialogue-view';view.hidden=true;root.querySelector('header').after(bar);root.querySelector('.search').before(view);
 let textId=null,prefs={},seq=0,data=null,forceOriginal=null;
 const key=id=>'corporium-dialogue:'+ (typeof desktopProjectKey==='string'?desktopProjectKey:location.origin)+':'+id;
 const dirty=()=>[...inlineDrafts.values()].some(d=>d.dirty||d.saving);
 function check(){if(dirty())throw Error((globalThis.CorporiumI18n?.f("a26284e1ce2bbd",()=>[])??'请先保存或取消正在编辑的句子标注。'));}
 function save(){if(textId)try{localStorage.setItem(key(textId),JSON.stringify(prefs));}catch{}}
 function sync(){
  if(textId!==selected){textId=selected;try{prefs=JSON.parse(localStorage.getItem(key(textId))||'{}');}catch{prefs={};}data=null;}
  if(forceOriginal===selected){prefs.enabled=false;save();forceOriginal=null;}
  bar.hidden=!selected;$('dialogue-enabled').checked=!!prefs.enabled;$('dialogue-colors').checked=!!prefs.colors;
  const enabled=!!selected&&!!prefs.enabled;root.classList.toggle('dialogue-active',enabled);view.hidden=!enabled;
  for(const id of ['dialogue-axis-label','dialogue-color-label','dialogue-refresh'])$(id).hidden=!enabled;
  return enabled;
 }
 const time=ms=>{const sign=ms<0?'−':'';ms=Math.abs(ms);return sign+Math.floor(ms/60000)+':'+(ms%60000/1000).toFixed(3).padStart(6,'0');};
 async function load(){
  const ticket=++seq,tid=textId,lid=activeLanguage;
  let result;
  try{result=await api('dialogue?'+new URLSearchParams({text_id:tid,session_id:prefs.session||'',page:prefs.page||1,page_size:pageSize()}));}
  catch(e){if(!e.message.includes((globalThis.CorporiumI18n?.f("3cdfd76e87db88",()=>[])??'时间轴已不存在或属于另一语言')))throw e;if(ticket!==seq||tid!==selected)return;prefs.session='';save();result=await api('dialogue?'+new URLSearchParams({text_id:tid}));}
  if(ticket!==seq||tid!==selected||lid!==activeLanguage||!prefs.enabled)return;
  const choices=result.sessions;const select=$('dialogue-axis');select.replaceChildren(new Option((globalThis.CorporiumI18n?.f("3507c5f03da351",()=>[])??'请选择时间轴'),''),...choices.map(s=>new Option((globalThis.CorporiumI18n?.f("de83b3b592db90",()=>[s.name,s.aligned])??s.name+' · '+s.aligned+' 个区间'),s.id)));
  if(!prefs.session){const linked=choices.filter(s=>s.aligned);if(linked.length===1){prefs.session=linked[0].id;save();return load();}}
  select.value=prefs.session||'';data=result;prefs.page=result.page;
  render();
 }
 function render(){
  if(!data)return;
  if(!prefs.session){view.innerHTML=(globalThis.CorporiumI18n?.f("1490cfb0f3632c",()=>[])??'<p class="empty">选择用于排列此文本的时间轴。一个文本有多套录音时，各自的时间不能混排。</p>');return;}
  const single=data.single_speaker;
  view.innerHTML=(globalThis.CorporiumI18n?.f("38427bbdc73c73",()=>[data.sentences,data.aligned,data.unaligned,single?(globalThis.CorporiumI18n?.f("1021b0c9e8ac61",()=>[esc(data.speaker_names[single])])??' · 发言人：'+esc(data.speaker_names[single])):''])??`<p class="dialogue-summary">${data.sentences} 条句子 · ${data.aligned} 个发言区间 · ${data.unaligned} 句待对齐${single?' · 发言人：'+esc(data.speaker_names[single]):''}</p><small>按开始时间、轨道上下顺序排列；括号保留原文本句号。同句多次对齐分别显示，统计仍按句子记录去重。</small><nav id="dialogue-pages" aria-label="对话分页"></nav><div id="dialogue-rows"></div>`);
  topPagination($('dialogue-pages'),data.page,data.pages,async p=>{try{check();prefs.page=p;save();await load();view.scrollIntoView({block:'start'});}catch(e){void corporiumAlert(e.message);}});
  let pendingHeading=false;
  for(const r of data.items){
   if(!r.interval_id&&!pendingHeading){$('dialogue-rows').insertAdjacentHTML('beforeend',(globalThis.CorporiumI18n?.f("8fa8f7f094ce82",()=>[])??'<h3 class="dialogue-pending">待对齐</h3>'));pendingHeading=true;}
   const a=r.attribution,person=a.conflict?(globalThis.CorporiumI18n?.f("1b92a1738f3dc3",()=>[])??'⚠ 发言人待核对'):a.names.join('、')||(globalThis.CorporiumI18n?.f("e46d822b4ae0e0",()=>[])??'未指定发言人');
   const row=document.createElement('article');row.className='entry dialogue-entry';row.dataset.navigationAnchor='dialogue:'+(r.interval_id||r.entry_id);row.dataset.dialogueEntry=r.entry_id;
   if(prefs.colors&&a.ids.length===1&&!a.conflict){let hash=0;for(const c of a.ids[0])hash=(hash*31+c.charCodeAt(0))>>>0;row.dataset.speakerColor=String(hash%5);}
   row.innerHTML=`<div class="dialogue-row-head"><span class="dialogue-original">(${r.position})</span>${!single||a.ids.length!==1||a.conflict?(globalThis.CorporiumI18n?.f("e302bbef9dde9b",()=>[esc(person)])??`<button class="text-button" data-dialogue-person title="查看或指定句子发言人">${esc(person)}</button>`):''}${r.interval_id?(globalThis.CorporiumI18n?.f("119a2a65c51c24",()=>[time(r.start_ms),time(r.end_ms),esc(r.track_name),r.overlap?(globalThis.CorporiumI18n?.f("18bff90a2be9dc",()=>[r.overlap_group+1])??'<span class="dialogue-overlap">重叠发言 · '+(r.overlap_group+1)+'</span>'):'',r.occurrences>1?(globalThis.CorporiumI18n?.f("60a692a79dcedc",()=>[r.occurrences])??'<small>本句有 '+r.occurrences+' 个区间</small>'):''])??`<button class="text-button" data-dialogue-time title="跳到时间轴中的这个区间">${time(r.start_ms)}—${time(r.end_ms)}</button><small>${esc(r.track_name)}</small>${r.overlap?'<span class="dialogue-overlap">重叠发言 · '+(r.overlap_group+1)+'</span>':''}${r.occurrences>1?'<small>本句有 '+r.occurrences+' 个区间</small>':''}`):''}</div>`;
   const holder=document.createElement('div');holder.innerHTML=renderEditableExample({...r.record.body,text_language_id:r.record.owner_language},'corpus',r.entry_id);
   // Keep the selected dialogue interval's names in brief mode, without editing controls.
   holder.querySelectorAll('.collaborator-badge').forEach(el=>{el.dataset.personReady='1';el.classList.add('dialogue-brief-speaker');el.hidden=!a.names.length;el.innerHTML='<span class="sentence-brief-names">'+esc(a.names.join('、'))+'</span>';});
   if(r.interval_id)holder.querySelectorAll('.sentence-audio').forEach(el=>el.dataset.audioInterval=r.interval_id);
   row.append(...holder.childNodes);row.querySelector('[data-dialogue-person]')?.addEventListener('click',()=>void CollaboratorLinks.open('corpus',r.entry_id));
   row.querySelector('[data-dialogue-time]')?.addEventListener('click',safe(async()=>{check();await CorporiumTimeline.openInterval({session_id:prefs.session,interval_id:r.interval_id,start_ms:r.start_ms,end_ms:r.end_ms,language_id:r.record.owner_language,text_id:r.record.text_id});}));
   $('dialogue-rows').append(row);
  }
  $('dialogue-rows').onclick=safe(async e=>{const button=e.target.closest('[data-unit]');if(!button)return;check();const id=button.closest('[data-dialogue-entry]').dataset.dialogueEntry;const r=data.items.find(r=>r.entry_id===id);const word=r.record.body.words.find(w=>w.unit_id===button.dataset.unit);if(word)await openWordLink({...r.record.body,title:r.record.title,position:r.position},word);});
 }
 $('dialogue-enabled').onchange=safe(async()=>{try{check();prefs.enabled=$('dialogue-enabled').checked;prefs.page=1;save();await search();}catch(e){sync();throw e;}});
 $('dialogue-axis').onchange=safe(async()=>{try{check();prefs.session=$('dialogue-axis').value;prefs.page=1;save();await load();}catch(e){$('dialogue-axis').value=prefs.session||'';throw e;}});
 $('dialogue-colors').onchange=()=>{prefs.colors=$('dialogue-colors').checked;save();if(!dirty())render();};
 $('dialogue-refresh').onclick=safe(async()=>{check();await load();});
 const previousSearch=search;search=async function(...args){if(sync()){request++;await load();}else{seq++;await previousSearch(...args);}};
 for(const event of ['corporium-alignment-changed','corporium-people-changed'])document.addEventListener(event,()=>{if(workspace==='corpus'&&prefs.enabled&&!dirty())void load().catch(e=>corporiumAlert(e.message));});
 document.querySelector('#brief-mode')?.addEventListener('change',()=>{if(prefs.enabled&&!dirty())render();});
 window.CorporiumDialogue={showOriginal(id){forceOriginal=id;}};
 sync();
})();
