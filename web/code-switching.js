/* Shared, word-anchored code annotations. Audio correspondence is explicitly chosen. */
function codeDraftChanged(draft,span){
 const ids=[...draft.selected].sort(),before=span?[...span.word_ids].sort():[];
 return ids.length!==before.length||ids.some((id,i)=>id!==before[i])||(draft.code||'')!==(span?.code_id||'')||(draft.notes||'')!==(span?.notes||'');
}
function codeWordSelection(ids,selected,anchor,target,extend,toggle){
 if(extend&&ids.includes(anchor)){const a=ids.indexOf(anchor),b=ids.indexOf(target);return ids.slice(Math.min(a,b),Math.max(a,b)+1);}
 if(toggle){const out=new Set(ids.filter(id=>selected.has(id)));out.has(target)?out.delete(target):out.add(target);return [...out];}
 return [target];
}
window.CorporiumCodes=(()=>{
 let state=null,busy=false,refreshing=false,catalogRequest=0,openRequest=0;
 const escape=esc;
 const message=e=>{if(state){const out=state.panel.querySelector('.code-error');if(out)out.textContent=e.message;}else corporiumAlert(e.message);};
 const key=(kind,id)=>kind+':'+id;
 function tools(){return '<button type="button" data-code-open>语码标记</button>';}
 function overview(e){const p=e.code_profile;return p?.has_annotations?`<span class="code-overview ${p.mixed?'is-mixed':''}" title="${escape(p.languages.join('、'))}">${p.mixed?'混用':'语码'}：${escape(p.languages.join('、')||'未确定')}${p.review?' · 待核对':''}</span>`:'';}
 function word(w){const m=w.code_mark;return m?.end?`<span class="code-word-label ${m.review?'code-review':''}" title="${escape(m.name+(m.notes?' · '+m.notes:'')+(m.review?' · 待核对':''))}">${escape(m.short)}</span>`:'';}
 function gloss(w,html){const label=word(w);return label?`<span class="code-gloss-text">${html}</span>${label}`:html;}
 function stats(s){return s?.marked?` · 混用 ${s.mixed} 句${s.languages.length?' · 标记语言：'+s.languages.map(c=>c.name+' '+c.sentences+'句').join('、'):''}${s.review?' · '+s.review+'句待核对':''}`:'';}
 function read(){if(!state)return;const p=state.panel;state.code=p.querySelector('[data-code-language]').value;state.notes=p.querySelector('[data-code-notes]').value;}
 function dirty(){if(!state)return false;read();return codeDraftChanged(state,state.data.spans.find(s=>s.id===state.editing));}
 async function leave(){if(busy&&state)throw Error('正在保存语码标记，请稍候');if(dirty()&&!await corporiumConfirm('放弃尚未应用的语码标记修改？'))return false;close();return true;}
 function close(){openRequest++;state?.panel.remove();state=null;}
 function draw(){
  if(!state)return;const s=state,d=s.data,selected=s.selected;
  s.panel.innerHTML=`<div class="code-panel-heading"><strong>正文语码</strong><span>${escape(d.profile.base_name)} · 默认语言</span><button type="button" data-code-close aria-label="关闭语码标记">×</button></div><p class="code-hint">点选词格；Shift 连选，Ctrl 多选。未标记的词沿用句子语言。</p><div class="code-word-picker" role="group" aria-label="选择语码词格">${d.words.map((w,i)=>`<button type="button" data-code-pick="${escape(w.id)}" aria-pressed="${selected.has(w.id)}" ${!w.selectable?'disabled':''} title="第 ${i+1} 词">${escape(w.form||'（空）')}</button>`).join('')}</div><form class="code-editor"><label>语言<select data-code-language aria-label="词格语码"><option value="">未确定</option>${d.codes.map(c=>`<option value="${escape(c.id)}">${escape(c.name)}</option>`).join('')}</select></label><button type="button" data-code-catalog title="管理或新建语言标记">管理语言</button><label class="code-notes-label">备注<input data-code-notes aria-label="语码备注" maxlength="20000" value="${escape(s.notes)}" placeholder="可留空"></label><button type="submit" class="primary">${s.editing?'保存修改':'应用标记'}</button><button type="button" data-code-new ${!s.editing?'hidden':''}>新标记</button></form><p class="code-error" role="alert"></p><div class="code-span-list">${d.spans.map(span=>`<div class="code-span" data-code-row="${escape(span.id)}"><div class="code-span-heading"><strong>${escape(span.short)}</strong><span class="code-span-text" title="${escape(span.text)}">${escape(span.text)}</span>${span.review?'<span class="code-review" title="'+escape(span.review_reason)+'">待核对</span>':''}<button type="button" data-code-edit="${escape(span.id)}" aria-label="编辑${escape(span.name)}标记">编辑</button><button type="button" data-code-delete="${escape(span.id)}" aria-label="移除${escape(span.name)}标记">×</button></div>${span.notes?`<p class="code-span-notes">${escape(span.notes)}</p>`:''}<details class="code-audio"><summary>时间轴片段${d.intervals.some(i=>i.span_id===span.id)?' · 已关联':''}</summary><div class="code-audio-controls"><select data-code-interval="${escape(span.id)}" aria-label="选择${escape(span.name)}时间片段"><option value="">选择已有语言片段</option>${d.intervals.filter(i=>i.code_id===span.code_id&&(!i.span_id||i.span_id===span.id)).map(i=>`<option value="${escape(i.id)}">${escape(i.session_name)} · ${(i.start_ms/1000).toFixed(3)}—${(i.end_ms/1000).toFixed(3)}秒${i.span_id?' · 已关联':''}</option>`).join('')}</select><button type="button" data-code-link="${escape(span.id)}">关联</button></div>${d.intervals.filter(i=>i.span_id===span.id).map(i=>`<div class="code-audio-link"><span>${escape(i.session_name)} · ${(i.start_ms/1000).toFixed(3)}—${(i.end_ms/1000).toFixed(3)}秒</span><button type="button" data-code-unlink="${escape(span.id)}" data-code-interval-id="${escape(i.id)}">解除</button></div>`).join('')}<p class="code-hint">在时间轴中为本句建立同语言的“语言片段”，再在此关联。修改正文范围后需重新关联；时间片段会保留。</p></details></div>`).join('')||'<p class="code-hint">尚无正文语码标记。</p>'}</div>`;
  s.panel.querySelector('[data-code-language]').value=s.code||'';
  s.panel.querySelector('.code-editor').onsubmit=e=>{e.preventDefault();void apply('save').catch(message);};
 }
 async function open(card){
  const kind=card.dataset.exampleKind,id=card.dataset.exampleId;
  if(inlineDrafts.has(key(kind,id)))throw Error('请先保存或取消这条例句的标注编辑');
  if(!await leave())return;
  const seq=++openRequest,scope=activeLanguage,origin=workspace;
  const data=await api('code-detail?'+new URLSearchParams({kind,id}));
  if(seq!==openRequest||scope!==activeLanguage||origin!==workspace||!card.isConnected)return;
  const panel=document.createElement('section');panel.className='code-panel';panel.setAttribute('aria-label','正文语码标记');
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
   await originalApi('code-'+action,{kind:s.kind,record_id:s.id,token:s.data.token,id:s.editing,word_ids:[...s.selected],code_id:s.code,notes:s.notes,_language:s.data.owner_language,...extra});
   s.dirty=false;const data=await api('code-detail?'+new URLSearchParams({kind:s.kind,id:s.id}));
   close();await refresh();
   const card=[...document.querySelectorAll('.editable-example')].find(c=>c.dataset.exampleKind===s.kind&&c.dataset.exampleId===s.id&&c.getClientRects().length);
   if(card&&workspace!=='timeline'){const panel=document.createElement('section');panel.className='code-panel';panel.setAttribute('aria-label','正文语码标记');card.append(panel);state={...s,data,card,panel,editing:null,selected:new Set(),anchor:null,code:'',notes:'',dirty:false};draw();}
   corporiumStatus('语码标记已保存，可撤销。');
  }finally{busy=false;if(state)state.panel.inert=false;}
 }
 document.addEventListener('click',e=>{
  const opener=e.target.closest('[data-code-open]');if(opener){e.preventDefault();const menu=opener.closest('details');if(menu)menu.open=false;void open(opener.closest('.editable-example')).catch(message);return;}
  const p=e.target.closest('.code-panel');if(!p||p!==state?.panel||busy)return;const b=e.target.closest('button');if(!b||b.type==='submit')return;
  e.preventDefault();
  void (async()=>{
   read();const s=state;
   if(b.hasAttribute('data-code-close')){await leave();return;}
   if(b.hasAttribute('data-code-pick')){const ids=s.data.words.filter(w=>w.selectable).map(w=>w.id),id=b.dataset.codePick;s.selected=new Set(codeWordSelection(ids,s.selected,s.anchor,id,e.shiftKey,e.ctrlKey||e.metaKey));if(!e.shiftKey)s.anchor=id;s.dirty=true;draw();return;}
   if(b.hasAttribute('data-code-new')){if(dirty()&&!await corporiumConfirm('放弃尚未应用的修改，开始新标记？'))return;s.editing=null;s.selected=new Set();s.code='';s.notes='';s.dirty=false;draw();return;}
   if(b.hasAttribute('data-code-edit')){if(dirty()&&!await corporiumConfirm('放弃尚未应用的修改？'))return;const span=s.data.spans.find(x=>x.id===b.dataset.codeEdit);s.editing=span.id;s.selected=new Set(span.word_ids.filter(id=>s.data.words.some(w=>w.id===id)));s.code=span.code_id||'';s.notes=span.notes;s.dirty=false;draw();return;}
   if(b.hasAttribute('data-code-catalog')){await CorporiumPeople.open('code');const data=await api('code-detail?'+new URLSearchParams({kind:s.kind,id:s.id}));if(state===s){s.data=data;draw();}return;}
   if(b.hasAttribute('data-code-delete')){if(dirty()&&!await corporiumConfirm('放弃尚未应用的修改？'))return;if(await corporiumConfirm('移除这个正文语码标记及其时间关联？录音中的时间片段会保留，可撤销。'))await apply('delete',{id:b.dataset.codeDelete,confirmed:true});return;}
   if(b.hasAttribute('data-code-link')||b.hasAttribute('data-code-unlink')){if(dirty())throw Error('请先应用或取消正文标记的修改');const span=b.dataset.codeLink||b.dataset.codeUnlink,interval=b.dataset.codeIntervalId||s.panel.querySelector('[data-code-interval="'+CSS.escape(span)+'"]').value;const item=s.data.intervals.find(i=>i.id===interval);if(!item)throw Error('请选择本句的同语言时间片段');await apply(b.hasAttribute('data-code-unlink')?'unlink':'link',{id:span,interval_id:interval,interval_revision:item.revision});}
  })().catch(message);
 });
 document.addEventListener('input',e=>{if(state?.panel.contains(e.target)&&e.target.matches('[data-code-language],[data-code-notes]')){read();state.dirty=true;}});
 // Shared menu closes independently; refresh its code choices once editing finishes.
 $('participants-dialog').addEventListener('close',()=>{if(!state)return;const s=state;void api('code-detail?'+new URLSearchParams({kind:s.kind,id:s.id})).then(data=>{if(state===s){read();s.data=data;draw();}}).catch(message);void loadCatalog();});
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
 function filter(prefix){return `<label>语码<select id="${prefix}-code-mode" aria-label="${prefix==='corpus'?'文本':'独立例句'}语码筛选"><option value="">不限</option><option value="mixed">仅混用句</option><option value="marked">已标记</option><option value="review">待核对</option></select></label><label>标记语言<select id="${prefix}-code-id" aria-label="${prefix==='corpus'?'文本':'独立例句'}标记语言"><option value="">不限</option></select></label>`;}
 document.querySelector('#corpus-workspace .filters').insertAdjacentHTML('beforeend',filter('corpus'));
 document.querySelector('#example-library .filters').insertAdjacentHTML('beforeend',filter('library'));
 $('counts').insertAdjacentHTML('afterend','<span id="corpus-code-summary" class="code-search-summary"></span>');
 $('library-count').insertAdjacentHTML('afterend','<p id="library-code-summary" class="code-search-summary"></p>');
 const params=prefix=>({code_mode:$(prefix+'-code-mode').value,code_id:$(prefix+'-code-id').value});
 const lastFilters={corpus:params('corpus'),library:params('library')};
 for(const prefix of ['corpus','library'])for(const suffix of ['-code-mode','-code-id'])$(prefix+suffix).onchange=safe(async()=>{if(!await leave()){for(const [name,value] of Object.entries(lastFilters[prefix]))$(prefix+'-'+name.replace('code_','code-')).value=value;return;}lastFilters[prefix]=params(prefix);if(prefix==='corpus'){page=1;await search();}else{libraryPage=1;await loadLibrary();}});
 const previousClear=clearFilters;clearFilters=function(...args){for(const suffix of ['-code-mode','-code-id'])$('corpus'+suffix).value='';lastFilters.corpus=params('corpus');return previousClear(...args);};
 async function loadCatalog(){const seq=++catalogRequest;const codes=await api('code-catalog');if(seq!==catalogRequest)return;for(const prefix of ['corpus','library']){const select=$(prefix+'-code-id'),value=select.value;select.replaceChildren(new Option('不限',''),...codes.map(c=>new Option(c.name,c.id)));if(codes.some(c=>c.id===value))select.value=value;}}
 document.addEventListener('corporium-people-changed',()=>void loadCatalog().catch(message));
 void loadCatalog().catch(message);
 return {tools,overview,word,gloss,stats,params,leave};
})();
