/* Occurrence-local morpheme codes. Audio correspondence is explicitly chosen. */
function codeDraftChanged(draft,span){
 if(span?.legacy&&draft.selectionChanged)return true;
 const ids=[...draft.selected].sort(),before=span?[...(span.morpheme_ids??span.word_ids)].sort():[];
 return ids.length!==before.length||ids.some((id,i)=>id!==before[i])||(draft.code||'')!==(span?.code_id||'')||(draft.notes||'')!==(span?.notes||'');
}
function codeWordSelection(ids,selected,anchor,target,extend,toggle){
 if(extend&&ids.includes(anchor)){const a=ids.indexOf(anchor),b=ids.indexOf(target);return ids.slice(Math.min(a,b),Math.max(a,b)+1);}
 if(toggle){const out=new Set(ids.filter(id=>selected.has(id)));out.has(target)?out.delete(target):out.add(target);return [...out];}
 return [target];
}
function codeContextChanged(before,after){
 const spans=data=>data.spans.map(s=>[s.id,s.revision,s.code_id,s.word_ids,s.snapshot,s.notes]);
 return before.revision!==after.revision||JSON.stringify(before.words)!==JSON.stringify(after.words)||JSON.stringify(spans(before))!==JSON.stringify(spans(after))||JSON.stringify(before.intervals)!==JSON.stringify(after.intervals);
}
window.CorporiumCodes=(()=>{
 let state=null,busy=false,refreshing=false,catalogRequest=0,openRequest=0;
 const escape=esc;
 const message=e=>{if(state){const out=state.panel.querySelector('.code-error');if(out)out.textContent=e.message;}else corporiumAlert(e.message);};
 const key=(kind,id)=>kind+':'+id;
 function tools(){return (globalThis.CorporiumI18n?.f("c1c3ed48a4661c",()=>[])??'<button type="button" data-code-open>语码标记</button>');}
 function overview(e){const p=e.code_profile;return p?.has_annotations?`<span class="code-overview ${p.mixed?'is-mixed':''}" title="${escape(p.languages.join('、'))}">${p.mixed?(globalThis.CorporiumI18n?.f("5d72bd4f692c6d",()=>[])??'混用'):(globalThis.CorporiumI18n?.f("c10c66f52b6cf4",()=>[])??'语码')}：${escape(p.languages.join('、')||(globalThis.CorporiumI18n?.f("e83f4ea8e2a486",()=>[])??'未确定'))}</span>`:'';}
 function word(w){const m=w.code_mark,name=m?.code_id===null?(globalThis.CorporiumI18n?.ui('未确定','Uncertain')??'未确定'):m?.name;return m?.end?`<span class="code-word-label" tabindex="0" role="button" data-code-info="${escape(name+(m.notes?' · '+m.notes:''))}" title="${escape(name+(m.notes?' · '+m.notes:''))}">${escape(m.short)}</span>`:'';}
 function gloss(w,html){const label=word(w);return label?`<span class="code-gloss-text">${html}</span>${label}`:html;}
 function pair(w,lid,original){
  if(!w.code_cells?.length)return original;
  const chars={form:Array.from(w.form),gloss:Array.from(w.gloss)},out={form:'',gloss:''};let columns=0;
  // Validate the complete partition, including every separator and script command.
  for(const field of ['form','gloss']){let at=0;for(const cell of w.code_cells){const [a,z]=cell[field]||[];if(!Number.isInteger(a)||!Number.isInteger(z)||a!==at||z<a||z>chars[field].length)return original;at=z;}if(at!==chars[field].length)return original;}
  for(const cell of w.code_cells){
   const mark=cell.mark,label=mark?.end?word({code_mark:mark}):'',name=mark?.code_id===null?(globalThis.CorporiumI18n?.ui('未确定','Uncertain')??'未确定'):mark?.name;
   for(const field of ['form','gloss']){
    const [a,z]=cell[field],value=chars[field].slice(a,z).join('');
    const colors=(window.CorporiumMorphColors?.components(w)||[]).map(m=>({...m,[field]:(m[field]||[]).map(([b,e])=>[Math.max(0,b-a),Math.min(z-a,e-a)]).filter(([b,e])=>e>b)}));
    let html=field==='form'?rich(value):cell.key===null?escape(value):richGloss(value,lid,cell.grammatical);
    if(colors.length)html=window.CorporiumMorphColors.decorate(value,html,colors,field);
    out[field]+=`<span class="interlinear-part ${mark?'code-morpheme':''}"${mark?` title="${escape(name+(mark.notes?' · '+mark.notes:''))}"`:''}>${html}</span>`;
    if(label)out[field]+=field==='gloss'?label:'<span class="code-label-space" aria-hidden="true"></span>';
   }
   columns+=label?2:1;
  }
  return {...out,columns,code:true};
 }
 function stats(s){return s?.marked?(globalThis.CorporiumI18n?.f("d267674486336f",()=>[s.mixed,s.languages.length?(globalThis.CorporiumI18n?.f("0ae97afe4476b8",()=>[s.languages.map(c=>(globalThis.CorporiumI18n?.f("95808d2016bfa2",()=>[c.name,c.sentences])??c.name+' '+c.sentences+'句')).join('、')])??' · 标记语言：'+s.languages.map(c=>c.name+' '+c.sentences+'句').join('、')):''])??` · 混用 ${s.mixed} 句${s.languages.length?' · 标记语言：'+s.languages.map(c=>c.name+' '+c.sentences+'句').join('、'):''}`):'';}
 function read(){if(!state)return;const p=state.panel;state.code=p.querySelector('[data-code-language]').value;state.notes=p.querySelector('[data-code-notes]').value;}
 function dirty(){if(!state)return false;read();return codeDraftChanged(state,state.data.spans.find(s=>s.id===state.editing));}
 async function leave(){if(busy&&state)throw Error((globalThis.CorporiumI18n?.f("cfbc695dd603be",()=>[])??'正在保存语码标记，请稍候'));if(dirty()&&!await corporiumConfirm((globalThis.CorporiumI18n?.f("9367cc59b8364c",()=>[])??'放弃尚未应用的语码标记修改？')))return false;close();return true;}
 function close(){openRequest++;state?.panel.remove();state=null;}
 const t=(zh,en)=>globalThis.CorporiumI18n?.ui(zh,en)??zh;
 function picker(w,i,s){
  const label=t('第 '+(i+1)+' 词','Word '+(i+1));
  return `<div class="code-picker-word" role="group" aria-label="${escape(label)}"><button type="button" class="code-pick-whole" data-code-pick-word="${escape(w.id)}" aria-pressed="${w.morphemes.length&&w.morphemes.every(u=>s.selected.has(u.id))?true:w.morphemes.some(u=>s.selected.has(u.id))?'mixed':false}" ${!w.selectable?'disabled':''} title="${escape(t('选择整个词格','Select the whole word'))}"><span class="ui-help">${i+1}.</span> <span class="code-picker-form">${rich(w.form||t('（空）','(empty)'))}</span></button><div class="code-picker-parts">${w.morphemes.map(u=>`<button type="button" class="code-pick-morpheme" data-code-pick="${escape(u.id)}" aria-pressed="${s.selected.has(u.id)}" title="${escape(label+' · '+t('选择语素','Select morpheme'))}"><span class="code-picker-form">${rich(u.form)}</span><span class="code-picker-gloss">${richGloss(u.gloss,s.data.language_id)}</span></button>`).join('')||`<span class="ui-help">${w.live?t('请先整理本词的语素切分','Resolve this word’s segmentation first'):t('不单独标记','Not tagged separately')}</span>`}</div></div>`;
 }
 function spanRow(span,d){
  const name=span.code_id===null?t('未确定','Uncertain'):span.name;
  const intervals=d.intervals.filter(i=>i.code_id===span.code_id&&(!i.span_id||i.span_id===span.id));
  const time=i=>escape(i.session_name)+' · '+(i.start_ms/1000).toFixed(3)+'—'+(i.end_ms/1000).toFixed(3)+t('秒',' s');
  return `<div class="code-span" data-code-row="${escape(span.id)}"><div class="code-span-heading"><strong title="${escape(name)}">${escape(span.short)}</strong><span class="code-span-text" title="${escape(span.text)}">${escape(span.text)}</span><button type="button" data-code-edit="${escape(span.id)}" aria-label="${escape(t('编辑标记：','Edit tag: ')+name)}">${t('编辑','Edit')}</button><button type="button" data-code-delete="${escape(span.id)}" aria-label="${escape(t('移除标记：','Remove tag: ')+name)}">×</button></div>${span.notes?`<p class="code-span-notes">${escape(span.notes)}</p>`:''}${span.unavailable?.length?`<p class="code-hint">${t('原语素范围已变化；点“编辑”重新选择范围，或移除标记。','The original morphemes changed. Edit to select their current range, or remove the tag.')}</p>`:''}<details class="code-audio"><summary>${t('时间轴片段','Timeline segment')}${d.intervals.some(i=>i.span_id===span.id)?t(' · 已关联',' · Linked'):''}</summary><div class="code-audio-controls"><select data-code-interval="${escape(span.id)}" aria-label="${escape(t('选择时间片段：','Select time segment: ')+name)}"><option value="">${t('选择已有语言片段','Select an existing language segment')}</option>${intervals.map(i=>`<option value="${escape(i.id)}">${time(i)}${i.span_id?t(' · 已关联',' · Linked'):''}</option>`).join('')}</select><button type="button" data-code-link="${escape(span.id)}">${t('关联','Link')}</button></div>${d.intervals.filter(i=>i.span_id===span.id).map(i=>`<div class="code-audio-link"><span>${time(i)}</span><button type="button" data-code-unlink="${escape(span.id)}" data-code-interval-id="${escape(i.id)}">${t('解除','Unlink')}</button></div>`).join('')}<p class="code-hint">${t('在时间轴中为本句建立同语言的“语言片段”，再在此关联。修改正文范围后需重新关联；时间片段会保留。','Create a language segment for this sentence and language in the timeline, then link it here. Changes to the text range require relinking; the time segment is retained.')}</p></details></div>`;
 }
 function draw(){
  if(!state)return;const s=state,d=s.data,focus=document.activeElement?.closest('[data-code-pick],[data-code-pick-word]');
  const focused=focus&&s.panel.contains(focus)?['data-code-pick','data-code-pick-word'].find(a=>focus.hasAttribute(a)):null,focusedId=focused?focus.getAttribute(focused):null;
  s.panel.innerHTML=`<div class="code-panel-heading"><strong>${t('语素语码','Morpheme languages')}</strong><span>${escape(d.profile.base_name)} · ${t('默认语言','Default language')}</span><button type="button" data-code-close aria-label="${t('关闭语码标记','Close language tagging')}">×</button></div><p class="code-hint">${t('点选语素；Shift 连选，Ctrl／⌘ 多选。点击词形可选择整个词格。多部分语素整体选择；未标记语素沿用句子语言。','Select morphemes; Shift extends the selection, Ctrl/⌘ toggles it. Click a word form to select the whole word. Multipart morphemes are selected together; untagged morphemes use the sentence language.')}</p><div class="code-word-picker" role="group" aria-label="${t('选择语码语素','Select morphemes for language tagging')}">${d.words.map((w,i)=>picker(w,i,s)).join('')}</div>${d.spans.find(span=>span.id===s.editing)?.legacy?`<p class="code-hint">${t('旧词格标记：直接修改语言和备注会保留原范围；重新点选语素后，按新范围保存。','Legacy word tag: editing only the language or notes retains its original range. Reselect morphemes to save a new range.')}</p>`:''}<p class="code-hint" role="status">${t('已选 '+s.selected.size+' 个语素',s.selected.size+(s.selected.size===1?' morpheme selected':' morphemes selected'))}</p><form class="code-editor ui-controls ui-controls--compact"><label>${t('语言','Language')}<select data-code-language aria-label="${t('语素语码','Morpheme language')}"><option value="">${t('未确定','Uncertain')}</option>${d.codes.map(c=>`<option value="${escape(c.id)}">${escape(c.name)}</option>`).join('')}</select></label><button type="button" data-code-catalog>${t('管理语言','Manage languages')}</button><label class="code-notes-label">${t('备注','Notes')}<input data-code-notes aria-label="${t('语码备注','Language-tag notes')}" maxlength="20000" value="${escape(s.notes)}" placeholder="${t('可留空','Optional')}"></label><button type="submit" class="primary">${s.editing?t('保存修改','Save changes'):t('应用标记','Apply tag')}</button><button type="button" data-code-new ${!s.editing?'hidden':''}>${t('新标记','New tag')}</button></form>${s.stale?`<p class="code-hint">${t('例句或语码标记已在其他位置更新。请关闭后重新打开；当前选择尚未应用。','The sentence or its language tags changed elsewhere. Close and reopen this editor; your selection has not been applied.')}</p>`:''}<p class="code-error" role="alert"></p><div class="code-span-list">${d.spans.map(span=>spanRow(span,d)).join('')||`<p class="code-hint">${t('尚无正文语码标记。','No language tags in this text yet.')}</p>`}</div>`;
  s.panel.querySelector('[data-code-language]').value=s.code||'';
  if(s.stale)s.panel.querySelector('button[type=submit]').disabled=true;
  s.panel.querySelector('.code-editor').onsubmit=e=>{e.preventDefault();void apply('save').catch(message);};
  if(focused)s.panel.querySelector('['+focused+'="'+CSS.escape(focusedId)+'"]')?.focus({preventScroll:true});
 }
 async function open(card){
  const kind=card.dataset.exampleKind,id=card.dataset.exampleId;
  if(inlineDrafts.has(key(kind,id)))throw Error((globalThis.CorporiumI18n?.f("dc50a5c4cf2dd1",()=>[])??'请先保存或取消这条例句的标注编辑'));
  if(!await leave())return;
  const seq=++openRequest,scope=activeLanguage,origin=workspace;
  const data=await api('code-detail?'+new URLSearchParams({kind,id}));
  if(seq!==openRequest||scope!==activeLanguage||origin!==workspace||!card.isConnected)return;
  const panel=document.createElement('section');panel.className='code-panel';panel.setAttribute('aria-label',(globalThis.CorporiumI18n?.f("2de7022f540ab0",()=>[])??'正文语码标记'));
  card.append(panel);state={kind,id,data,panel,card,editing:null,selected:new Set(),anchor:null,code:'',notes:'',dirty:false};draw();panel.scrollIntoView({block:'nearest'});
 }
 async function refresh(){
  refreshing=true;
  try{await window.corporiumRefreshUndoState?.();await refreshExampleViews();document.dispatchEvent(new Event('corporium-alignment-changed'));}
  finally{refreshing=false;}
 }
 async function apply(action,extra={}){
  if(!state||busy)return;read();const s=state;busy=true;s.panel.inert=true;
  try{
   const previous=s.data.spans?.find(span=>span.id===s.editing),range=previous?.legacy&&!s.selectionChanged?{word_ids:previous.word_ids}:{morpheme_ids:[...s.selected]};
   await originalApi('code-'+action,{kind:s.kind,record_id:s.id,token:s.data.token,id:s.editing,...range,code_id:s.code,notes:s.notes,_language:s.data.owner_language,...extra});
   s.dirty=false;const data=await api('code-detail?'+new URLSearchParams({kind:s.kind,id:s.id}));
   close();await refresh();
   const card=[...document.querySelectorAll('.editable-example')].find(c=>c.dataset.exampleKind===s.kind&&c.dataset.exampleId===s.id&&c.getClientRects().length);
   if(card&&workspace!=='timeline'){const panel=document.createElement('section');panel.className='code-panel';panel.setAttribute('aria-label',(globalThis.CorporiumI18n?.f("713fc1954f8ff8",()=>[])??'正文语码标记'));card.append(panel);state={...s,data,card,panel,editing:null,selected:new Set(),anchor:null,code:'',notes:'',dirty:false};draw();}
   corporiumStatus((globalThis.CorporiumI18n?.f("b49daf947f02b1",()=>[])??'语码标记已保存，可撤销。'));
  }finally{busy=false;if(state)state.panel.inert=false;}
 }
 document.addEventListener('click',e=>{
  const info=e.target.closest('[data-code-info]');if(info){e.preventDefault();void corporiumAlert(info.dataset.codeInfo);return;}
  const opener=e.target.closest('[data-code-open]');if(opener){e.preventDefault();const menu=opener.closest('details');if(menu)menu.open=false;void open(opener.closest('.editable-example')).catch(message);return;}
  const p=e.target.closest('.code-panel');if(!p||p!==state?.panel||busy)return;const b=e.target.closest('button');if(!b||b.type==='submit')return;
  e.preventDefault();
  void (async()=>{
   read();const s=state;
   if(b.hasAttribute('data-code-close')){await leave();return;}
   if(b.hasAttribute('data-code-pick')){const ids=s.data.words.flatMap(w=>w.morphemes.map(u=>u.id)),id=b.dataset.codePick;s.selected=new Set(codeWordSelection(ids,s.selected,s.anchor,id,e.shiftKey,e.ctrlKey||e.metaKey));if(!e.shiftKey)s.anchor=id;s.selectionChanged=true;s.dirty=true;draw();return;}
   if(b.hasAttribute('data-code-pick-word')){const words=s.data.words,word=words.find(w=>w.id===b.dataset.codePickWord);if(!word?.selectable)return;const ids=words.flatMap(w=>w.morphemes.map(u=>u.id)),picked=word.morphemes.map(u=>u.id);if(e.shiftKey){s.selected=new Set(codeWordSelection(ids,s.selected,s.anchor,picked.at(-1),true,false));}else if(e.ctrlKey||e.metaKey){const remove=picked.every(id=>s.selected.has(id));for(const id of picked)remove?s.selected.delete(id):s.selected.add(id);}else s.selected=new Set(picked);s.anchor=picked[0];s.selectionChanged=true;s.dirty=true;draw();return;}
   if(b.hasAttribute('data-code-new')){if(dirty()&&!await corporiumConfirm((globalThis.CorporiumI18n?.f("099f00a61e87b0",()=>[])??'放弃尚未应用的修改，开始新标记？')))return;s.editing=null;s.selectionChanged=false;s.selected=new Set();s.code='';s.notes='';s.dirty=false;draw();return;}
   if(b.hasAttribute('data-code-edit')){if(dirty()&&!await corporiumConfirm((globalThis.CorporiumI18n?.f("6ad7c2d0d99794",()=>[])??'放弃尚未应用的修改？')))return;const span=s.data.spans.find(x=>x.id===b.dataset.codeEdit);s.editing=span.id;s.selectionChanged=false;s.selected=new Set(span.morpheme_ids);s.anchor=null;s.code=span.code_id||'';s.notes=span.notes;s.dirty=false;draw();return;}
   if(b.hasAttribute('data-code-catalog')){await CorporiumPeople.open('code');const data=await api('code-detail?'+new URLSearchParams({kind:s.kind,id:s.id}));if(state===s){s.stale=s.stale||codeContextChanged(s.data,data);if(!s.stale)s.data=data;draw();}return;}
   if(b.hasAttribute('data-code-delete')){if(dirty()&&!await corporiumConfirm((globalThis.CorporiumI18n?.f("539ccd23697da3",()=>[])??'放弃尚未应用的修改？')))return;if(await corporiumConfirm((globalThis.CorporiumI18n?.f("4fc8b5dad9d166",()=>[])??'移除这个正文语码标记及其时间关联？录音中的时间片段会保留，可撤销。')))await apply('delete',{id:b.dataset.codeDelete,confirmed:true});return;}
   if(b.hasAttribute('data-code-link')||b.hasAttribute('data-code-unlink')){if(dirty())throw Error((globalThis.CorporiumI18n?.f("a60f75e4004246",()=>[])??'请先应用或取消正文标记的修改'));const span=b.dataset.codeLink||b.dataset.codeUnlink,interval=b.dataset.codeIntervalId||s.panel.querySelector('[data-code-interval="'+CSS.escape(span)+'"]').value;const item=s.data.intervals.find(i=>i.id===interval);if(!item)throw Error((globalThis.CorporiumI18n?.f("141902e4b57e48",()=>[])??'请选择本句的同语言时间片段'));await apply(b.hasAttribute('data-code-unlink')?'unlink':'link',{id:span,interval_id:interval,interval_revision:item.revision});}
  })().catch(message);
 });
 document.addEventListener('keydown',e=>{const info=e.target.closest('[data-code-info]');if(info&&['Enter',' '].includes(e.key)){e.preventDefault();info.click();}});
 document.addEventListener('input',e=>{if(state?.panel.contains(e.target)&&e.target.matches('[data-code-language],[data-code-notes]')){read();state.dirty=true;}});
 // Shared menu closes independently; refresh its code choices once editing finishes.
 $('participants-dialog').addEventListener('close',()=>{if(!state)return;const s=state;void api('code-detail?'+new URLSearchParams({kind:s.kind,id:s.id})).then(data=>{if(state===s){read();s.stale=s.stale||codeContextChanged(s.data,data);if(!s.stale)s.data=data;draw();}}).catch(message);void loadCatalog();});
 const previousSearch=search;search=async function(...args){if(state&&$('participants-dialog').open)return;if(!refreshing&&state&&!await leave())return;return previousSearch(...args);};
 const previousLibrary=loadLibrary;loadLibrary=async function(...args){if(state&&$('participants-dialog').open)return;if(!refreshing&&state&&!await leave())return;return previousLibrary(...args);};
 const previousWorkspace=setWorkspace;setWorkspace=async function(name,...args){if(name!==workspace&&!await leave())return false;return previousWorkspace(name,...args);};
 const previousLanguage=switchLanguage;switchLanguage=async function(id,...args){if(id!==activeLanguage&&!await leave()){$('language-select').value=activeLanguage;return false;}return previousLanguage(id,...args);};
 const previousUndo=undoCommand;undoCommand=async function(...args){if(!await leave())return;return previousUndo(...args);};
 const previousHistory=refreshUndo;refreshUndo=async function(...args){if(state)return window.corporiumRefreshUndoState?.();return previousHistory(...args);};
 const previousEdit=edit;edit=async function(...args){if(!await leave())return;return previousEdit(...args);};
 const previousStandalone=openStandalone;openStandalone=async function(...args){if(!await leave())return;return previousStandalone(...args);};
 const previousLexeme=showLexeme;showLexeme=async function(...args){if(!refreshing&&state&&workspace==='dictionary'&&!await leave())return;return previousLexeme(...args);};
 const previousHome=showHome;showHome=async function(...args){if(!await leave())return;return previousHome(...args);};
 window.addEventListener('beforeunload',e=>{if(dirty()||busy){e.preventDefault();e.returnValue='';}});
 window.corporiumCodesDirty=()=>dirty()||busy;
 window.corporiumLeaveCodes=leave;
 function filter(prefix){return (globalThis.CorporiumI18n?.f("d4d23bb2bb756c",()=>[prefix,prefix==='corpus'?(globalThis.CorporiumI18n?.f("a76b40424f22e6",()=>[])??'文本'):(globalThis.CorporiumI18n?.f("e76e1a206b9e9f",()=>[])??'独立例句'),prefix,prefix==='corpus'?(globalThis.CorporiumI18n?.f("a92f17b5e9d305",()=>[])??'文本'):(globalThis.CorporiumI18n?.f("1f943151c293ee",()=>[])??'独立例句')])??`<label>语码<select id="${prefix}-code-mode" aria-label="${prefix==='corpus'?'文本':'独立例句'}语码筛选"><option value="">不限</option><option value="mixed">仅混用句</option><option value="marked">已标记</option></select></label><label>标记语言<select id="${prefix}-code-id" aria-label="${prefix==='corpus'?'文本':'独立例句'}标记语言"><option value="">不限</option></select></label>`);}
 document.querySelector('#corpus-workspace .filters').insertAdjacentHTML('beforeend',filter('corpus'));
 document.querySelector('#example-library .filters').insertAdjacentHTML('beforeend',filter('library'));
 $('counts').insertAdjacentHTML('afterend','<span id="corpus-code-summary" class="code-search-summary"></span>');
 $('library-count').insertAdjacentHTML('afterend','<p id="library-code-summary" class="code-search-summary"></p>');
 const params=prefix=>({code_mode:$(prefix+'-code-mode').value,code_id:$(prefix+'-code-id').value});
 const lastFilters={corpus:params('corpus'),library:params('library')};
 for(const prefix of ['corpus','library'])for(const suffix of ['-code-mode','-code-id'])$(prefix+suffix).onchange=safe(async()=>{if(!await leave()){for(const [name,value] of Object.entries(lastFilters[prefix]))$(prefix+'-'+name.replace('code_','code-')).value=value;return;}lastFilters[prefix]=params(prefix);if(prefix==='corpus'){page=1;await search();}else{libraryPage=1;await loadLibrary();}});
 const previousClear=clearFilters;clearFilters=function(...args){for(const suffix of ['-code-mode','-code-id'])$('corpus'+suffix).value='';lastFilters.corpus=params('corpus');return previousClear(...args);};
 async function loadCatalog(){const seq=++catalogRequest;const codes=await api('code-catalog');if(seq!==catalogRequest)return;for(const prefix of ['corpus','library']){const select=$(prefix+'-code-id'),value=select.value;select.replaceChildren(new Option((globalThis.CorporiumI18n?.f("3d3d5d37591a21",()=>[])??'不限'),''),...codes.map(c=>new Option(c.name,c.id)));if(codes.some(c=>c.id===value))select.value=value;}}
 document.addEventListener('corporium-people-changed',()=>void loadCatalog().catch(message));
 void loadCatalog().catch(message);
 return {tools,overview,word,gloss,pair,stats,params,leave};
})();
