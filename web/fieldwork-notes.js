/* Language-owned notes stay independent of dictionary selection and editor drafts. */
(()=>{
const sameRuns=(a,b)=>a.length===b.length&&a.every((r,i)=>r.text===b[i].text&&['bold','italic','highlight'].every(k=>!!r[k]===!!b[i][k])&&(r.type_id||'')===(b[i].type_id||''));
class NoteDraft{
 constructor(row,read,write,status){this.row=row;this.read=read;this.write=write;this.status=status;this.dirty=false;this.generation=0;this.saving=null;this.composing=false;}
 changed(){this.dirty=true;this.generation++;this.status((globalThis.CorporiumI18n?.f("d67cf729b4601d",()=>[])??'待保存…'));}
 flush(){
  if(this.saving)return this.saving;
  if(this.composing)return Promise.reject(Error((globalThis.CorporiumI18n?.f("6a4d0aef569750",()=>[])??'请先完成正在输入的文字，再离开笔记。')));
  if(!this.dirty)return Promise.resolve(0);
  this.saving=(async()=>{let count=0;try{
   while(this.dirty){
    if(this.composing)throw Error((globalThis.CorporiumI18n?.f("2653cb2cbb02c3",()=>[])??'请先完成正在输入的文字，再离开笔记。'));
    const generation=this.generation,payload={id:this.row.id,revision:this.row.revision,...this.read()};this.status((globalThis.CorporiumI18n?.f("cbf01a27232e0f",()=>[])??'保存中…'));
    const saved=await this.write(payload);this.row=saved;count++;
    if(generation===this.generation)this.dirty=false;
   }
   this.status((globalThis.CorporiumI18n?.f("bb2448472bf57b",()=>[])??'已保存'));return count;
  }catch(error){this.status((globalThis.CorporiumI18n?.f("1dd77d94c7366b",()=>[error.message])??'未保存：'+error.message),true);throw error;}finally{this.saving=null;}})();return this.saving;
 }
}

const panel=document.createElement('aside');panel.id='fieldwork-notes';panel.setAttribute('aria-label',(globalThis.CorporiumI18n?.f("693dfafacb5335",()=>[])??'调查笔记'));panel.hidden=true;
panel.innerHTML=(globalThis.CorporiumI18n?.f("e7bf5132431e89",()=>[])??'<div class="fieldwork-heading"><strong>调查笔记</strong><small id="fieldwork-language"></small><button id="fieldwork-new" type="button" title="新建调查笔记" aria-label="新建调查笔记">＋</button></div><p class="fieldwork-hint">调查时可以使用此区域记录内容，方便后续整理</p><details id="fieldwork-search"><summary>检索笔记 <small id="fieldwork-search-count"></small></summary><form id="fieldwork-search-form"><input id="fieldwork-search-query" aria-label="检索调查笔记" placeholder="搜索标题和内容…" maxlength="200"><button type="submit" aria-label="检索笔记" title="检索"><svg viewBox="0 0 20 20" aria-hidden="true"><circle cx="8" cy="8" r="5.5"/><path d="m12 12 5 5"/></svg></button><button id="fieldwork-search-clear" type="button" aria-label="清空笔记检索" title="清空并恢复列表">×</button></form></details><div id="fieldwork-message" role="status"></div><div id="fieldwork-list"></div>');
const toggle=document.createElement('button');toggle.id='fieldwork-toggle';toggle.type='button';toggle.setAttribute('aria-controls',panel.id);
toggle.innerHTML='<svg viewBox="0 0 10 24" aria-hidden="true"><path d="M3 6 7 12 3 18"/></svg>';
const resize=document.createElement('div');resize.id='fieldwork-resize';resize.tabIndex=0;resize.role='separator';resize.setAttribute('aria-label',(globalThis.CorporiumI18n?.f("eced1a3d412c37",()=>[])??'调整调查笔记宽度'));resize.setAttribute('aria-orientation','vertical');resize.setAttribute('aria-controls',panel.id);resize.title=(globalThis.CorporiumI18n?.f("81aeb3599eaec8",()=>[])??'拖动调整宽度；方向键微调；双击恢复默认');
document.body.append(panel,toggle,resize);
let opened=false,width=360,model={items:[],writing_types:[]},language='',activeId=null,draft=null,timer=null,request=0,actionPromise=null,gesture=null,dragFrame=0;
let searchState=null,searchOriginal=null;
const storage=k=>projectStorageKey('corporium-fieldwork-'+k);
try{opened=localStorage.getItem(storage('open'))==='true';width=Number(localStorage.getItem(storage('width')))||360;}catch{}
try{$('fieldwork-search').open=localStorage.getItem(storage('search-open'))==='true';}catch{}
$('fieldwork-search').addEventListener('toggle',()=>{try{localStorage.setItem(storage('search-open'),String($('fieldwork-search').open));}catch{}});
const call=(action,body,lid=language)=>originalApi('fieldwork-note-'+action,{...body,_language:lid});
const metadata=row=>({id:row.id,language_id:row.language_id,position:row.position,title:row.title,preview:row.preview,revision:row.revision});
const name=row=>row.title||row.preview?.split('\n')[0]||(globalThis.CorporiumI18n?.f("b7dbbd480c0ec7",()=>[])??'未命名笔记');
const list=$('fieldwork-list'),message=$('fieldwork-message'),add=$('fieldwork-new');
function rememberPlace(){try{localStorage.setItem(storage('place-'+language),activeId||'');}catch{}}
function layout(save=false){
 const max=Math.max(280,Math.min(640,innerWidth-32));width=Math.round(Math.max(280,Math.min(max,width)));
 document.documentElement.style.setProperty('--fieldwork-width',width+'px');
 const visible=workspace==='dictionary',left=$('workspace-sidebar')?.hidden?0:$('workspace-sidebar')?.getBoundingClientRect().width||0;
 panel.hidden=!(visible&&opened);toggle.hidden=!visible;resize.hidden=panel.hidden;
 document.documentElement.classList.toggle('fieldwork-open',visible&&opened);
 document.documentElement.classList.toggle('fieldwork-docked',visible&&opened&&innerWidth-left-width>=350);
 document.documentElement.classList.toggle('fieldwork-entry-room',visible&&opened&&innerWidth-left-width>=240);
 toggle.title=opened?(globalThis.CorporiumI18n?.f("d18395b14ee5ee",()=>[])??'收起调查笔记'):(globalThis.CorporiumI18n?.f("9ced57e3158e91",()=>[])??'展开调查笔记');toggle.setAttribute('aria-label',toggle.title);toggle.setAttribute('aria-expanded',String(opened));
 resize.setAttribute('aria-valuemin','280');resize.setAttribute('aria-valuemax',String(max));resize.setAttribute('aria-valuenow',String(width));
 if(save)try{localStorage.setItem(storage('width'),String(width));localStorage.setItem(storage('open'),String(opened));}catch{}
}
function status(text,error=false){
 const holder=draft?.holder;if(!holder)return;
 holder.querySelector('[data-note-status]').textContent=text;holder.querySelector('[data-note-status]').classList.toggle('fieldwork-error',error);
 holder.querySelector('[data-note-retry]').hidden=!error;holder.querySelector('[data-note-recover]').hidden=!error;
}
async function flush(){clearTimeout(timer);if(!draft)return;const count=await draft.flush();if(count)await window.corporiumRefreshUndoState().catch(()=>{message.textContent=(globalThis.CorporiumI18n?.f("a071fa0d96e049",()=>[])??'笔记已保存，操作记录暂未刷新。');});}
async function settle(){if(actionPromise)await actionPromise;await flush();}
function later(){clearTimeout(timer);if(!draft?.composing)timer=setTimeout(()=>void flush().catch(()=>{}),900);}
function updateHeader(row){
 const index=model.items.findIndex(r=>r.id===row.id);if(index>=0)model.items[index]=metadata(row);
 const card=[...list.children].find(el=>el.dataset.note===row.id);if(!card)return;
 card.querySelector('.fieldwork-title').textContent=name(row);card.querySelector('.fieldwork-preview').textContent=row.preview||(globalThis.CorporiumI18n?.f("1eaacf7fdfc430",()=>[])??'空白笔记');
 card.querySelector('[data-note-open]').title=name(row);
}
async function write(payload,lid){
 let saved;
 try{saved=await call('save',payload,lid);}catch(error){
  // A response may be lost after commit. Reconcile only an exact saved payload.
  try{const current=await originalApi('fieldwork-notes?'+new URLSearchParams({id:payload.id,language:lid}));if(current.title===payload.title.trim()&&sameRuns(current.body,payload.body))saved=current;}catch{}
  if(!saved)throw error;
 }
 updateHeader(saved);return saved;
}
function draw(){
 clearNoteHighlight();const hits=new Map(searchState?.items.map(r=>[r.id,r])||[]),rows=searchState?model.items.filter(r=>hits.has(r.id)||r.id===activeId):model.items;
 list.innerHTML=rows.map(row=>(globalThis.CorporiumI18n?.f("87bacab678ce07",()=>[row.id===activeId?'is-open':'',esc(row.id),esc(name(row)),row.id===activeId,esc(name(row)),searchState?surveySnippet(name(row),searchState.q):esc(name(row)),esc(row.preview||(globalThis.CorporiumI18n?.f("65159d4f3d510f",()=>[])??'空白笔记')),(hits.get(row.id)?.fields||[]).map(f=>'<small class="fieldwork-hit" data-note-hit-field="'+f.field+'"><b>'+esc(f.label)+'：</b>'+surveySnippet(f.snippet,searchState.q)+'</small>').join(''),uiIcon('copy'),uiIcon('delete'),row.id===activeId?'':'hidden'])??`<section class="fieldwork-card ${row.id===activeId?'is-open':''}" data-note="${esc(row.id)}"><div class="fieldwork-card-head"><button type="button" class="fieldwork-drag" data-note-drag aria-label="拖动调查笔记：${esc(name(row))}" title="拖动排序；上下方向键移动">⠿</button><button type="button" class="fieldwork-summary" data-note-open aria-expanded="${row.id===activeId}" title="${esc(name(row))}"><span class="fieldwork-title">${searchState?surveySnippet(name(row),searchState.q):esc(name(row))}</span><small class="fieldwork-preview">${esc(row.preview||'空白笔记')}</small>${(hits.get(row.id)?.fields||[]).map(f=>'<small class="fieldwork-hit" data-note-hit-field="'+f.field+'"><b>'+esc(f.label)+'：</b>'+surveySnippet(f.snippet,searchState.q)+'</small>').join('')}</button><button type="button" data-note-copy aria-label="复制调查笔记" title="复制笔记">${uiIcon('copy')}</button><button type="button" data-note-delete aria-label="删除调查笔记" title="删除笔记，可撤销">${uiIcon('delete')}</button></div><div class="fieldwork-card-body" ${row.id===activeId?'':'hidden'}></div></section>`)).join('')||(searchState?(globalThis.CorporiumI18n?.f("bc7c3c4dbf60bf",()=>[])??'<p class="fieldwork-empty">没有匹配的笔记。</p>'):(globalThis.CorporiumI18n?.f("12b596fa9f0b66",()=>[])??'<p class="fieldwork-empty">点击右上角 ＋，记录第一条调查笔记。</p>'));
 $('fieldwork-search-count').textContent=searchState?(globalThis.CorporiumI18n?.f("59bb216cd93532",()=>[searchState.total])??'· '+searchState.total+' 条'):'';if(searchState?.pages>1){const pages=document.createElement('nav');pages.className='fieldwork-search-pages';list.append(pages);topPagination(pages,searchState.page,searchState.pages,p=>runNoteSearch(p));}
 list.querySelectorAll('[data-note-drag]').forEach(el=>{el.disabled=!!searchState;el.hidden=!!searchState;});
}
async function edit(row,focus=false){
 const card=[...list.children].find(el=>el.dataset.note===row.id),holder=card.querySelector('.fieldwork-card-body');
 holder.innerHTML=(globalThis.CorporiumI18n?.f("1bcfca49a148d9",()=>[esc(row.title),CorporiumRichText.box('fieldwork-note-editor',(globalThis.CorporiumI18n?.f("2fa6a4f9003d35",()=>[])??'笔记内容'),row.body,model.writing_types)])??'<input class="fieldwork-note-title" aria-label="笔记标题" maxlength="500" placeholder="标题（可留空）" value="'+esc(row.title)+'">'+CorporiumRichText.box('fieldwork-note-editor','笔记内容',row.body,model.writing_types)+'<div class="fieldwork-save"><small data-note-status role="status">已保存</small><button type="button" data-note-retry hidden>重试保存</button><button type="button" data-note-recover hidden>保存为副本</button></div>');
 // Use the shared editor and controls, with shorter labels in this narrow panel.
 holder.querySelector('label').hidden=true;holder.querySelector('[data-format="highlight"]').textContent=(globalThis.CorporiumI18n?.f("d07a05aff599ee",()=>[])??'亮');holder.querySelector('[data-format="plain"]').textContent=(globalThis.CorporiumI18n?.f("2da52c79f6e539",()=>[])??'清');holder.querySelector('[data-list]').textContent='•';holder.querySelector('[data-apply-writing]').textContent=(globalThis.CorporiumI18n?.f("7d04b3c88caf5e",()=>[])??'应用');
 for(const button of holder.querySelectorAll('.survey-rich-tools button'))button.setAttribute('aria-label',button.title||button.textContent);
 CorporiumRichText.bind(holder,model.writing_types);
 const title=holder.querySelector('input'),editor=holder.querySelector('[contenteditable]'),lid=language;
 const d=new NoteDraft(row,()=>({title:title.value,body:CorporiumRichText.read(editor)}),payload=>write(payload,lid),status);d.holder=holder;draft=d;
 holder.addEventListener('compositionstart',()=>{d.composing=true;clearTimeout(timer);});
 holder.addEventListener('compositionend',()=>{d.composing=false;d.changed();later();});
 holder.addEventListener('input',e=>{clearNoteHighlight();d.changed();if(!e.isComposing)later();});
 holder.addEventListener('focusout',e=>{if(!holder.contains(e.relatedTarget))void flush().catch(()=>{});});
 holder.querySelector('[data-note-retry]').onclick=()=>void flush().catch(()=>{});
 holder.querySelector('[data-note-recover]').onclick=()=>void recover();
 if(searchState){highlightNote(card,searchState.q);card.scrollIntoView({block:'nearest'});}else if(focus)editor.focus();
}
async function reload(preferred,focus=false){
 const lid=activeLanguage,seq=++request;if(language!==lid){searchState=searchOriginal=null;$('fieldwork-search-query').value='';clearNoteHighlight();}draft=null;clearTimeout(timer);language=lid;model={items:[],writing_types:[]};activeId=null;
 $('fieldwork-language').textContent=languageList.find(l=>l.id===lid)?.name||(globalThis.CorporiumI18n?.f("f429c4022dfe43",()=>[])??'全部语言');add.disabled=lid==='all';message.textContent='';list.replaceChildren();
 if(lid==='all'){message.textContent=(globalThis.CorporiumI18n?.f("ede41205d8b978",()=>[])??'请选择一种语言记录调查笔记。');return;}
 const result=await originalApi('fieldwork-notes');if(seq!==request||lid!==activeLanguage)return;model=result;
 if(preferred===undefined)try{preferred=localStorage.getItem(storage('place-'+lid));}catch{}
 activeId=model.items.some(r=>r.id===preferred)?preferred:null;draw();rememberPlace();
 if(activeId){const row=await originalApi('fieldwork-notes?'+new URLSearchParams({id:activeId}));if(seq!==request||lid!==activeLanguage)return;await edit(row,focus);}
}
async function action(fn){
 if(actionPromise)return;
 message.textContent='';list.inert=true;add.disabled=true;
 actionPromise=(async()=>{await flush();await fn();await window.corporiumRefreshUndoState();})();
 try{await actionPromise;}catch(error){message.textContent=error.message;}finally{actionPromise=null;list.inert=false;add.disabled=activeLanguage==='all';}
}
async function recover(){
 if(actionPromise||!draft)return;list.inert=true;add.disabled=true;const d=draft,payload=d.read();clearTimeout(timer);if(d.saving)try{await d.saving;}catch{}
 actionPromise=(async()=>{const row=await call('create',{...payload,title:(globalThis.CorporiumI18n?.f("f9afa3d80ce61b",()=>[(payload.title||(globalThis.CorporiumI18n?.f("4d0a1b0658bd4b",()=>[])??'调查笔记')).slice(0,480)])??(payload.title||'调查笔记').slice(0,480)+' · 副本')},d.row.language_id);d.dirty=false;await reload(row.id);await window.corporiumRefreshUndoState();})();
 try{await actionPromise;}catch(error){message.textContent=(globalThis.CorporiumI18n?.f("25c02bbe8fecef",()=>[error.message])??'副本未保存：'+error.message);}finally{actionPromise=null;list.inert=false;add.disabled=activeLanguage==='all';}
}
add.onclick=()=>void action(async()=>{const row=await call('create',{});await reload(row.id,true);});
list.addEventListener('click',e=>{const card=e.target.closest('[data-note]');if(!card||!e.target.closest('[data-note-open],[data-note-copy],[data-note-delete]'))return;const id=card.dataset.note;
 void action(async()=>{const row=model.items.find(r=>r.id===id);if(!row)return;
  if(e.target.closest('[data-note-open]')){const next=activeId===id?null:id;draft=null;activeId=next;draw();rememberPlace();if(next){await edit(await originalApi('fieldwork-notes?id='+encodeURIComponent(next)),true);}return;}
  if(e.target.closest('[data-note-copy]')){const copy=await call('copy',{id,revision:row.revision});await reload(copy.id,true);return;}
  if(await corporiumConfirm((globalThis.CorporiumI18n?.f("3c46db10e0c372",()=>[])??'删除这条调查笔记？可通过上方“撤销”恢复。'))){await call('delete',{id,revision:row.revision,confirmed:true});await reload(activeId===id?null:activeId);}
 });
});
async function reorder(order,focusId){
 await action(async()=>{const result=await call('reorder',{order,snapshot:model.items.map(r=>({id:r.id,revision:r.revision}))});model=result;const selected=activeId;draft=null;draw();if(selected&&model.items.some(r=>r.id===selected))await edit(await originalApi('fieldwork-notes?id='+encodeURIComponent(selected)));[...list.querySelectorAll('[data-note]')].find(el=>el.dataset.note===focusId)?.querySelector('[data-note-drag]').focus({preventScroll:true});});
}
function clearNoteHighlight(){window.CSS?.highlights?.delete('fieldwork-search');list.querySelectorAll('.fieldwork-search-focus').forEach(e=>e.classList.remove('fieldwork-search-focus'));list.querySelectorAll('.fieldwork-search-fallback').forEach(e=>e.remove());}
function highlightNote(card,query){
 clearNoteHighlight();const editor=card.querySelector('[contenteditable]');if(!editor)return;card.classList.add('fieldwork-search-focus');
 const nodes=[];let text='';function walk(n){if(n.nodeType===3){nodes.push({node:n,start:text.length,end:text.length+n.length});text+=n.data;return;}if(n.nodeType!==1)return;if(n.tagName==='BR'){text+='\n';return;}if(['DIV','P','LI'].includes(n.tagName)&&text&&!text.endsWith('\n'))text+='\n';for(const child of n.childNodes)walk(child);}for(const child of editor.childNodes)walk(child);
 const ranges=[];for(const match of surveyTextRanges(text,query,200)){for(const part of nodes){const start=Math.max(match[0],part.start),end=Math.min(match[1],part.end);if(start>=end)continue;const range=document.createRange();range.setStart(part.node,start-part.start);range.setEnd(part.node,end-part.start);ranges.push(range);}}
 if(window.CSS?.highlights&&window.Highlight){CSS.highlights.set('fieldwork-search',new Highlight(...ranges));if(ranges[0])requestAnimationFrame(()=>{const rect=ranges[0].getBoundingClientRect(),box=editor.getBoundingClientRect();editor.scrollTop+=rect.top-box.top-20;});}
 else if(ranges.length){const preview=document.createElement('div');preview.className='fieldwork-search-fallback';preview.innerHTML=surveySnippet(text,query);editor.before(preview);}
}
async function runNoteSearch(page=1){const query=$('fieldwork-search-query').value.trim();if(!query){await clearNoteSearch();return;}await action(async()=>{
 if(!searchOriginal)searchOriginal={language,activeId,scroll:list.scrollTop,editorScroll:draft?.holder.querySelector('[contenteditable]')?.scrollTop||0};
 const lid=language,seq=++request,result=await originalApi('fieldwork-search?'+new URLSearchParams({q:query,page,language:lid}));if(seq!==request||lid!==activeLanguage)return;searchState=result;draft=null;activeId=null;draw();list.scrollTop=0;
});}
async function clearNoteSearch(){await action(async()=>{const original=searchOriginal;searchState=searchOriginal=null;$('fieldwork-search-query').value='';clearNoteHighlight();draft=null;activeId=original?.language===language&&model.items.some(r=>r.id===original.activeId)?original.activeId:null;draw();rememberPlace();if(activeId)await edit(await originalApi('fieldwork-notes?id='+encodeURIComponent(activeId)));requestAnimationFrame(()=>{list.scrollTop=original?.scroll||0;const editor=draft?.holder.querySelector('[contenteditable]');if(editor)editor.scrollTop=original?.editorScroll||0;});});}
$('fieldwork-search-form').onsubmit=e=>{e.preventDefault();void runNoteSearch();};$('fieldwork-search-clear').onclick=()=>void clearNoteSearch();
function clearDrop(){list.querySelectorAll('[data-drop]').forEach(el=>delete el.dataset.drop);}
function dragTick(){if(!gesture)return;const box=list.getBoundingClientRect();if(gesture.moved){list.scrollTop+=gesture.y<box.top+28?-7:gesture.y>box.bottom-28?7:0;const rows=[...list.children].filter(el=>el.dataset.note!==gesture.id);clearDrop();if(rows.length){const target=rows.find(el=>el.getBoundingClientRect().bottom>gesture.y)||rows.at(-1),r=target.getBoundingClientRect();gesture.target=target.dataset.note;gesture.after=gesture.y>(r.top+r.bottom)/2;target.dataset.drop=gesture.after?'after':'before';}}dragFrame=requestAnimationFrame(dragTick);}
list.addEventListener('pointerdown',e=>{const handle=e.target.closest('[data-note-drag]');if(!handle||searchState||e.button!==0||actionPromise)return;e.preventDefault();handle.setPointerCapture(e.pointerId);gesture={pointer:e.pointerId,id:handle.closest('[data-note]').dataset.note,start:e.clientY,y:e.clientY,moved:false};dragFrame=requestAnimationFrame(dragTick);});
list.addEventListener('pointermove',e=>{if(!gesture||gesture.pointer!==e.pointerId)return;gesture.y=e.clientY;gesture.moved||=Math.abs(gesture.y-gesture.start)>5;document.documentElement.classList.toggle('fieldwork-dragging',gesture.moved);});
function endDrag(e,cancel=false){if(!gesture||gesture.pointer!==e.pointerId)return;const g=gesture;gesture=null;cancelAnimationFrame(dragFrame);clearDrop();document.documentElement.classList.remove('fieldwork-dragging');if(cancel||!g.moved||!g.target)return;const order=model.items.map(r=>r.id).filter(id=>id!==g.id),index=order.indexOf(g.target)+(g.after?1:0);order.splice(index,0,g.id);void reorder(order,g.id);}
list.addEventListener('pointerup',e=>endDrag(e));list.addEventListener('pointercancel',e=>endDrag(e,true));
list.addEventListener('keydown',e=>{if(searchState||!e.target.closest('[data-note-drag]')||!['ArrowUp','ArrowDown'].includes(e.key))return;e.preventDefault();const id=e.target.closest('[data-note]').dataset.note,order=model.items.map(r=>r.id),i=order.indexOf(id),j=i+(e.key==='ArrowUp'?-1:1);if(j<0||j>=order.length)return;[order[i],order[j]]=[order[j],order[i]];void reorder(order,id);});
toggle.onclick=async()=>{try{await settle();opened=!opened;layout(true);if(opened)await reload(language===activeLanguage?activeId:undefined);}catch(error){message.textContent=error.message;}};
resize.onpointerdown=e=>{if(e.button!==0)return;e.preventDefault();resize.setPointerCapture(e.pointerId);};
resize.onpointermove=e=>{if(resize.hasPointerCapture(e.pointerId)){width=innerWidth-e.clientX;layout();}};
resize.onpointerup=resize.onpointercancel=resize.onlostpointercapture=()=>layout(true);
resize.ondblclick=()=>{width=360;layout(true);};
resize.onkeydown=e=>{if(!['ArrowLeft','ArrowRight','Home','End'].includes(e.key))return;e.preventDefault();width=e.key==='Home'?280:e.key==='End'?640:width+(e.key==='ArrowLeft'?10:-10);layout(true);};
window.corporiumLayoutNotes=layout;
window.addEventListener('resize',()=>layout());new ResizeObserver(()=>layout()).observe($('workspace-sidebar'));
const previousWorkspace=setWorkspace;setWorkspace=async function(name){if(name!==workspace)await settle();await previousWorkspace(name);layout();if(workspace==='dictionary'&&opened&&language!==activeLanguage)await reload(undefined);};
const previousLanguage=switchLanguage;let languageQueue=Promise.resolve();switchLanguage=function(id){const task=languageQueue.then(async()=>{await settle();await previousLanguage(id);if(language!==activeLanguage){draft=null;language='';request++;if(workspace==='dictionary'&&opened)await reload(undefined);}layout();});languageQueue=task.catch(()=>{});return task;};
const previousUndo=undoCommand;undoCommand=async function(kind){await settle();await previousUndo(kind);if(workspace==='dictionary'&&opened)await reload(activeId);else{draft=null;language='';request++;}};
const previousHome=showHome;showHome=async function(...args){try{await settle();return await previousHome(...args);}catch(error){message.textContent=error.message;}};
const previousApi=api;api=async function(path,body){if(['export-language','backup','language-package-export'].includes(path.split('?')[0]))await settle();return previousApi(path,body);};
window.corporiumFlushNotes=settle;window.corporiumNotesDirty=()=>!!(draft?.dirty||draft?.saving||actionPromise);
window.addEventListener('beforeunload',e=>{if(window.corporiumNotesDirty()){e.preventDefault();e.returnValue='';}});
layout();if(workspace==='dictionary'&&opened)void reload(undefined).catch(e=>{message.textContent=e.message;});
})();
