/* Fieldwork outlines: references share the existing sentence editor and audio controls. */
(()=>{
const panel=document.createElement('section');panel.id='survey-workspace';panel.hidden=true;main.append(panel);
libraryButton.hidden=true;
const tab=document.createElement('button');tab.id='workspace-survey';tab.textContent='语法调查';libraryButton.before(tab);
const statusNames={unasked:'未调查',followup:'待补证',evidence:'已有材料',done:'暂告完成'};
let state={nodes:[],writing_types:[],people:[]},selection=null,request=0,editing=null,editTimer=null,pickerPage=1,pickerNode=null;
const remembered=new Map(),expanded=new Set(),questionOpen=new Set(),multi=new Set();let draggedIds=null,selectionAnchor=null;
const call=(action,b)=>originalApi('survey-'+action,{...b,version:state.version,_language:activeLanguage});
const guard=fn=>safe(async(...args)=>{await flush();await fn(...args);});
const hasText=r=>(r||[]).some(x=>x.text.trim());
let nodeNumbers=new Map(),surveySearch=null,surveyReadingCleanup=()=>{};
const label=n=>esc((nodeNumbers.get(n.id)||'')+' '+n.title.replace(/^\d+(?:\.\d+)*[.、．]?\s+/,''));
function markup(runs=[]){return CorporiumRichText.markup(runs,state.writing_types);}
panel.innerHTML=`<div class="survey-heading"><div><h1>语法调查</h1><small>提纲 · 问题 · 例句证据 · 研究笔记</small></div><div><button id="survey-template">模板管理</button><button id="survey-root">＋ 主模块</button><button id="survey-library">独立例句库</button></div></div><p id="survey-message" role="status"></p><div class="survey-layout"><div id="survey-navigation"><nav id="survey-tree" aria-label="调查提纲"></nav></div><div id="survey-content"></div></div>`;
surveySearch=createSurveySearch({
 async prepare(){surveyReadingCleanup();noSentenceDraft();await flush();if(editing?.wasNew&&editing.node)selection=editing.node.id;parkEditor();},
 capture(){
  const nav=$('survey-navigation').closest('#workbench-module-nav')||$('survey-navigation');
  const cards=[...panel.querySelectorAll('[data-survey-node],[data-survey-evidence]')];
  const edge=$('workspace-toolbar').getBoundingClientRect().bottom,reading=[...panel.querySelectorAll('[data-survey-evidence]')].find(c=>c.getBoundingClientRect().bottom>edge)||cards[0];
  return {selection,expanded:[...expanded],questionOpen:[...questionOpen],multi:[...multi],anchor:selectionAnchor,scroll:window.scrollY,x:window.scrollX,reading:reading?.dataset.navigationAnchor,readingTop:reading?.getBoundingClientRect().top,sideScroll:nav.scrollTop,
   pages:[...panel.querySelectorAll('[data-evidence-list]')].map(h=>[h.dataset.evidenceList,Number(h.dataset.page)||1]),
   opens:cards.flatMap(c=>[...c.querySelectorAll(':scope>details,:scope>.editable-example>details.example-notes')].flatMap((d,index)=>d.open?[{node:c.dataset.surveyNode,evidence:c.dataset.surveyEvidence,index}]:[]))};
 },
 async restore(place,current){
  const fresh=await api('survey');if(!current())return;state=fresh;const ids=new Set(state.nodes.map(n=>n.id));selection=ids.has(place.selection)?place.selection:state.nodes[0]?.id||null;
  expanded.clear();place.expanded.filter(id=>ids.has(id)).forEach(id=>expanded.add(id));questionOpen.clear();place.questionOpen.filter(id=>ids.has(id)).forEach(id=>questionOpen.add(id));multi.clear();place.multi.filter(id=>ids.has(id)).forEach(id=>multi.add(id));selectionAnchor=place.anchor;remembered.set(activeLanguage,selection);
  tree();await content(current);if(!current())return;
  for(const [id,page] of place.pages)if(page>1){await showEvidence(id,page);if(!current())return;}
  for(const open of place.opens){const c=[...panel.querySelectorAll('[data-survey-node],[data-survey-evidence]')].find(c=>open.evidence?c.dataset.surveyEvidence===open.evidence:c.dataset.surveyNode===open.node);const d=c?.querySelectorAll(':scope>details,:scope>.editable-example>details.example-notes')[open.index];if(d)d.open=true;}
  await new Promise(resolve=>requestAnimationFrame(resolve));if(!current())return;restoreSurveyReading(place,current);($('survey-navigation').closest('#workbench-module-nav')||$('survey-navigation')).scrollTop=place.sideScroll;
 },
 async navigate(target,current){
  const fresh=await api('survey');if(!current())return [];state=fresh;const n=state.nodes.find(n=>n.id===target.node_id);if(!n)throw Error('该调查条目已删除，请重新检索。');selection=n.id;
  let parent=n.parent_id;const seen=new Set();while(parent&&!seen.has(parent)){seen.add(parent);expanded.add(parent);parent=state.nodes.find(n=>n.id===parent)?.parent_id;}
  if(n.kind==='question')questionOpen.add(n.id);tree();await content(current,target);if(!current())return [];
  const card=[...panel.querySelectorAll(target.evidence_id?'[data-survey-evidence]':'[data-survey-node]')].find(c=>target.evidence_id?c.dataset.surveyEvidence===target.evidence_id:c.dataset.surveyNode===target.node_id);if(!card)return [];
  const selectors=target.evidence_id?{judgment:':scope>.entry-head>small',context:':scope>details>.survey-rich',local_notes:':scope>.survey-local-note>.survey-rich',ipa:'.editable-example .ipa',form:'.editable-example .words:not(.inline-words)>.word>.form',gloss:'.editable-example .words:not(.inline-words)>.word>.gloss',translation:'.editable-example .translation',sentence_notes:'.editable-example>.example-notes>.preserve-lines'}:{title:':scope>.survey-card-head>:is(h2,h3)',content:':scope>.survey-rich',notes:':scope>.survey-notes>.survey-rich'};
  let roots=selectors[target.field]?[...card.querySelectorAll(selectors[target.field])]:[];
  if(!roots.length&&target.text){const extra=document.createElement('div');extra.dataset.surveySearchExtra='';extra.className='survey-search-extra';const title=document.createElement('small');title.textContent=({original:'原文',language_notes:'句子语言备注'}[target.field]||'命中内容')+'：';const value=document.createElement('div');value.textContent=target.text;extra.append(title,value);card.append(extra);roots=[value];}
  return roots.length?roots:[card.querySelector('.entry-head,.survey-card-head')||card];
 }
});

function restoreSurveyReading(place,current){
 surveyReadingCleanup();const reading=[...panel.querySelectorAll('[data-navigation-anchor]')].find(c=>c.dataset.navigationAnchor===place.reading);
 const events=['wheel','pointerdown','keydown','touchstart'];let timer,observer;
 const cleanup=()=>{clearTimeout(timer);observer?.disconnect();for(const type of events)document.removeEventListener(type,cleanup,true);};surveyReadingCleanup=cleanup;
 const align=()=>{if(!current()||workspace!=='survey'||panel.hidden){cleanup();return;}window.scrollTo({left:place.x,top:reading?.isConnected?window.scrollY+reading.getBoundingClientRect().top-place.readingTop:place.scroll,behavior:'instant'});};
 // Recording controls can resize the sentence after its initial render.
 observer=new ResizeObserver(align);observer.observe($('survey-content'));for(const type of events)document.addEventListener(type,cleanup,{capture:true,passive:true});timer=setTimeout(cleanup,1500);align();
}
function noSentenceDraft(){window.discardEmptySentenceDrafts?.();if(inlineDrafts.size)throw Error('请先保存或取消正在编辑的例句');}
async function load(){return window.CorporiumViews?window.CorporiumViews.run('survey',loadContent):loadContent();}
window.corporiumReloadSurvey=load;
async function loadContent(){await flush();parkEditor();surveySearch.refresh();const seq=++request,lid=activeLanguage;if(lid==='all'){state={nodes:[],writing_types:[],people:[]};$('survey-tree').replaceChildren();$('survey-content').innerHTML='<p class="empty">请在左侧选择一种语言，开始组织调查提纲。</p>';return;}if(!selection){try{const saved=JSON.parse(localStorage.getItem(projectStorageKey('survey-place-'+lid))||'{}');selection=saved.selection||null;for(const id of saved.expanded||[])expanded.add(id);}catch{}}const data=await api('survey');if(seq!==request||lid!==activeLanguage)return;state=data;if(!state.nodes.some(n=>n.id===selection))selection=state.nodes[0]?.id||null;remembered.set(lid,selection);let parent=state.nodes.find(n=>n.id===selection)?.parent_id;const visited=new Set();while(parent&&!visited.has(parent)){visited.add(parent);expanded.add(parent);parent=state.nodes.find(n=>n.id===parent)?.parent_id;}tree();await content();surveySearch.refresh();}
function tree(){
 nodeNumbers=CorporiumOrder.numbers(state.nodes);
 for(const id of multi)if(!state.nodes.some(n=>n.id===id))multi.delete(id);
 if(!surveySearch?.active())try{localStorage.setItem(projectStorageKey('survey-place-'+activeLanguage),JSON.stringify({selection,expanded:[...expanded]}));}catch{}
 const children=p=>state.nodes.filter(n=>n.parent_id===p);
 function branch(p,depth=0){return children(p).map(n=>{const nested=children(n.id).length;return `<div class="survey-tree-row" data-tree-node="${esc(n.id)}" draggable="${!dragLocked()}" style="--depth:${depth}"><button class="survey-fold" data-fold="${esc(n.id)}" aria-label="${expanded.has(n.id)?'折叠':'展开'} ${label(n)}" ${!nested?'disabled':''} aria-expanded="${expanded.has(n.id)}">${nested?(expanded.has(n.id)?'▾':'▸'):'·'}</button><button data-node="${esc(n.id)}" aria-current="${selection===n.id}" title="${label(n)}">${n.kind==='question'?'? ':''}${label(n)}${n.evidence_count?` <small>${n.evidence_count}</small>`:''}</button></div>${nested&&expanded.has(n.id)?branch(n.id,depth+1):''}`;}).join('');}
 $('survey-tree').innerHTML=`<div class="survey-tree-toolbar"><label><input id="survey-drag-lock" type="checkbox" ${dragLocked()?'checked':''}> 锁定拖动</label><small id="survey-multi-count"></small></div><div class="survey-root-drop" data-root-drop>提纲顶层（拖到此处）</div>`+(branch(null)||'<p class="empty">从空白模块开始，或导入汉语调查粗纲。</p>');
 $('survey-drag-lock').onchange=e=>{try{localStorage.setItem(projectStorageKey('survey-drag-lock-'+activeLanguage),String(e.target.checked));}catch{}tree();};
 $('survey-tree').querySelectorAll('[data-fold]').forEach(b=>b.onclick=()=>{expanded.has(b.dataset.fold)?expanded.delete(b.dataset.fold):expanded.add(b.dataset.fold);tree();});
 $('survey-tree').querySelectorAll('[data-node]').forEach(b=>b.onclick=guard(async e=>{noSentenceDraft();const id=b.dataset.node;
  if(e.shiftKey){const visible=[...$('survey-tree').querySelectorAll('[data-node]')].map(b=>b.dataset.node),anchor=selectionAnchor||selection||id;const range=selectionRange(visible,anchor,id);if(!e.ctrlKey&&!e.metaKey)multi.clear();for(const chosen of forbiddenMove(range))multi.add(chosen);paintMulti();return;}
  if(e.ctrlKey||e.metaKey){if(!multi.size&&selection)for(const chosen of forbiddenMove([selection]))multi.add(chosen);const remove=multi.has(id);for(const chosen of forbiddenMove([id]))remove?multi.delete(chosen):multi.add(chosen);selectionAnchor=id;paintMulti();return;}
  multi.clear();selectionAnchor=id;selection=id;remembered.set(activeLanguage,selection);tree();await content();}));paintMulti();bindTreeDrag();
}
function card(n,heading=false){return `<article class="survey-card" data-survey-node="${esc(n.id)}" data-navigation-anchor="survey:${esc(n.id)}"><div class="survey-card-head"><${heading?'h2':'h3'}>${label(n)}</${heading?'h2':'h3'}><span class="survey-status">${statusNames[n.body.status]}</span><button data-edit-node="${esc(n.id)}">编辑</button></div>${hasText(n.body.content)?`<div class="survey-rich">${markup(n.body.content)}</div>`:''}<details class="survey-notes"><summary>${hasText(n.body.notes)?'研究笔记 · 已填写':'添加研究笔记'}</summary><div class="survey-rich">${markup(n.body.notes)||'<small>暂无笔记</small>'}</div><button data-inline-note="${esc(n.id)}">编辑笔记</button></details><div class="survey-evidence-actions"><button data-pick="${esc(n.id)}">＋ 引用已有例句</button><button data-new-example="${esc(n.id)}">＋ 新建例句</button><small>修改例句同步到所有引用处；本处笔记单独保存</small></div><div data-evidence-list="${esc(n.id)}"></div></article>`;}
async function content(current=()=>true,focus=null){await flush();if(!current())return;surveySearch.clearHighlight();parkEditor();const n=state.nodes.find(n=>n.id===selection),root=$('survey-content');if(!n){root.innerHTML='<div class="survey-welcome"><h2>建立你的调查提纲</h2><p>模块和条目可多层嵌套。问题下面可以引用已有句子，也可以现场录入独立例句。</p><p>汉语语法调查模板仅提供分类标题，不包含问卷正文或预设回答。</p></div>';return;}
 const children=state.nodes.filter(x=>x.parent_id===n.id);
 root.innerHTML=`<div class="survey-node-tools">${n.kind==='section'?'<button id="survey-child">＋ 子条目</button><button id="survey-question">＋ 问题</button>':''}<button id="survey-up" title="同层上移">↑</button><button id="survey-down" title="同层下移">↓</button><button id="survey-copy">复制</button><button id="survey-save-template">存为模板</button><button id="survey-move">移动条目</button><button id="survey-delete" title="双击删除，原句保留">${n.parent_id?'删除条目':'删除整个提纲'}(双击)</button></div>${n.body.template?`<p class="survey-template-label">${esc(n.body.template)} · 可自由修改的副本</p>`:''}${card(n,true)}${children.map(c=>c.kind==='question'?`<details class="survey-question" data-question="${esc(c.id)}" ${questionOpen.has(c.id)?'open':''}><summary>${label(c)} <small>${statusNames[c.body.status]} · ${c.evidence_count} 条例证</small></summary>${card(c)}</details>`:`<button class="survey-child-link" data-child="${esc(c.id)}">▸ ${label(c)}</button>`).join('')}`;
 if($('survey-child'))$('survey-child').onclick=guard(()=>editNode(null,n.id,'section'));if($('survey-question'))$('survey-question').onclick=guard(()=>editNode(null,n.id,'question'));
 $('survey-up').onclick=guard(()=>mutate('order',{id:n.id,direction:'up'}));$('survey-down').onclick=guard(()=>mutate('order',{id:n.id,direction:'down'}));
 $('survey-save-template').onclick=guard(async()=>{const ids=moveIds(),name=await corporiumPrompt('模板名称（包含所选条目及全部下级；不包含研究笔记、回答和进度）',multi.size?'组合提纲':(state.nodes.find(x=>x.id===n.id)?.title||n.title));if(name===null)return;await call('template-file',{action:'save',node_ids:ids,name});await showTemplates();});
 $('survey-move').onclick=guard(openMove);
 $('survey-delete').ondblclick=guard(async()=>{noSentenceDraft();if(await corporiumConfirm('删除「'+(state.nodes.find(x=>x.id===n.id)?.title||n.title)+'」及其下级问题、笔记和例证引用？原句保留，可撤销。'))await mutate('delete',{id:n.id,confirmed:true});});
 $('survey-copy').onclick=()=>{$('survey-copy-dialog').showModal();};
 root.querySelectorAll('[data-inline-note]').forEach(b=>b.onclick=guard(()=>editNode(state.nodes.find(n=>n.id===b.dataset.inlineNote),null,null,true)));
 root.querySelectorAll('[data-edit-node]').forEach(b=>b.onclick=guard(()=>editNode(state.nodes.find(x=>x.id===b.dataset.editNode),null,null,!!b.hasAttribute('data-notes-focus'))));
 root.querySelectorAll('[data-child]').forEach(b=>b.onclick=guard(async()=>{noSentenceDraft();multi.clear();expanded.add(n.id);selection=b.dataset.child;tree();await content();}));
 root.querySelectorAll('[data-pick]').forEach(b=>b.onclick=guard(()=>openPicker(b.dataset.pick)));
 root.querySelectorAll('[data-new-example]').forEach(b=>b.onclick=guard(async()=>{noSentenceDraft();const nid=b.dataset.newExample;await beginSentenceDraft({kind:'independent',survey_node:nid,survey_version:state.version,host:b.closest('.survey-card').querySelector('[data-evidence-list]'),onSaved:async()=>{await updateState();await content();}});}));
 root.querySelectorAll('[data-question]').forEach(d=>d.addEventListener('toggle',()=>{if(d.open){questionOpen.add(d.dataset.question);void showEvidence(d.dataset.question);}else questionOpen.delete(d.dataset.question);}));
 paintMulti();await showEvidence(n.id,focus?.evidence_id?focus.page:1,focus?.evidence_id||'');for(const c of children)if(questionOpen.has(c.id))await showEvidence(c.id);
}
async function updateState(){state=await api('survey');tree();}
async function mutate(action,body){noSentenceDraft();const r=await call(action,body);selection=r.id??selection;await load();await refreshUndo();return r;}
function surveyExample(e,full=false){const brief=briefMode;try{if(full)briefMode=false;return renderEditableExample({...e.record.body,language_id:e.record.language_id,text_language_id:e.record.owner_language},e.kind,e.record_id);}finally{briefMode=brief;}}
async function showEvidence(nid,p=1,focus=''){const holder=[...panel.querySelectorAll('[data-evidence-list]')].find(h=>h.dataset.evidenceList===nid);if(!holder)return;const seq=holder._surveyRequest=(holder._surveyRequest||0)+1;const data=await api('survey-detail?'+new URLSearchParams({id:nid,page:p}));if(!holder.isConnected||seq!==holder._surveyRequest)return;holder.dataset.page=String(data.page);
 holder.innerHTML=data.items.map(e=>`<article class="entry survey-evidence ${e.id===focus?'survey-search-reveal':''}" data-survey-evidence="${esc(e.id)}" data-navigation-anchor="evidence:${esc(e.id)}"><div class="entry-head"><small>${e.kind==='corpus'?'文本引用':'独立例句'}${e.body.judgment?' · '+esc(e.body.judgment):''}${e.body.judges?.length?' · 判断者：'+e.body.judges.map(id=>esc(state.people.find(p=>p.id===id)?.name||'已删除')).join('、'):''}</small><div><button data-evidence-edit="${esc(e.id)}">本处笔记</button><button data-unlink="${esc(e.id)}">移除引用</button></div></div>${e.record?surveyExample(e,e.id===focus):'<p class="warning">原句已删除或已不属于本语言。引用及研究笔记保留，撤销原句删除可恢复。</p>'}${hasText(e.body.context)?`<details><summary>调查提示</summary><div class="survey-rich">${markup(e.body.context)}</div></details>`:''}${hasText(e.body.notes)?`<div class="survey-local-note"><small>本处研究笔记</small><div class="survey-rich">${markup(e.body.notes)}</div></div>`:''}</article>`).join('')||'<p class="survey-empty-evidence">尚未收集例证</p>';
 holder.querySelectorAll('[data-evidence-edit]').forEach(b=>b.onclick=guard(()=>editEvidence(data.items.find(e=>e.id===b.dataset.evidenceEdit))));
 holder.querySelectorAll('[data-unlink]').forEach(b=>b.onclick=guard(async()=>{noSentenceDraft();if(await corporiumConfirm('移除此处例证引用及本处笔记？原句保留，可撤销。'))await mutate('unlink',{node_id:nid,evidence_id:b.dataset.unlink});}));
 const pager=document.createElement('nav');holder.append(pager);if(data.pages>1)topPagination(pager,data.page,data.pages,next=>{noSentenceDraft();void showEvidence(nid,next);});
}
function dragLocked(){try{return localStorage.getItem(projectStorageKey('survey-drag-lock-'+activeLanguage))!=='false';}catch{return true;}}
function selectionRange(visible,anchor,target){const end=visible.indexOf(target),start=visible.indexOf(anchor);return end<0?[]:start<0?[target]:visible.slice(Math.min(start,end),Math.max(start,end)+1);}
function paintMulti(){for(const b of $('survey-tree').querySelectorAll('[data-node]')){b.classList.toggle('survey-multi-selected',multi.has(b.dataset.node));b.setAttribute('aria-pressed',String(multi.has(b.dataset.node)));}const c=$('survey-multi-count');if(c)c.textContent=multi.size?'已选 '+multi.size+' 项（含下级）':'';const save=$('survey-save-template');if(save)save.textContent=multi.size?'将所选存为模板':'存为模板';}
function moveIds(){return multi.size?[...multi]:selection?[selection]:[];}
function forbiddenMove(ids){const result=new Set(ids);let changed=true;while(changed){changed=false;for(const n of state.nodes)if(result.has(n.parent_id)&&!result.has(n.id)){result.add(n.id);changed=true;}}return result;}
function nodePath(n){const names=[n.title];let parent=n.parent_id;while(parent){const p=state.nodes.find(n=>n.id===parent);if(!p)break;names.unshift(p.title);parent=p.parent_id;}return names.join(' / ');}
makeDialog('survey-move-dialog','<h2>移动条目</h2><p id="survey-move-description"></p><label>移到哪个父层下面<select id="survey-move-parent"></select></label><p>移动所选条目及全部下级；原有子树结构保持，层级按新父层自动调整。父子同时选中时只移动父项一次。</p><button id="survey-move-confirm" class="primary">移动到所选层级末尾</button>');
let movingIds=[];
function openMove(){noSentenceDraft();movingIds=moveIds();if(!movingIds.length)return;const banned=forbiddenMove(movingIds);$('survey-move-description').textContent='移动 '+movingIds.length+' 个选中条目';$('survey-move-parent').innerHTML='<option value="">提纲顶层</option>'+state.nodes.filter(n=>n.kind==='section'&&!banned.has(n.id)).sort((a,b)=>nodePath(a).localeCompare(nodePath(b),'zh',{numeric:true})).map(n=>`<option value="${esc(n.id)}">${esc(nodePath(n))}</option>`).join('');$('survey-move-dialog').showModal();}
async function performMove(ids,target){noSentenceDraft();const result=await call('move',{ids,...target});multi.clear();result.moved_ids.forEach(id=>multi.add(id));selection=result.id;if(target.parent_id)expanded.add(target.parent_id);await load();await refreshUndo();}
$('survey-move-confirm').onclick=guard(async()=>{await performMove(movingIds,{parent_id:$('survey-move-parent').value});$('survey-move-dialog').close();});
function bindTreeDrag(){const nav=$('survey-tree');
 function clearDrop(){nav.querySelectorAll('[data-drop]').forEach(e=>delete e.dataset.drop);}
 function targetFor(e){const row=e.target.closest('[data-tree-node]');if(!row)return e.target.closest('[data-root-drop]')?{element:e.target.closest('[data-root-drop]'),parent_id:null,placement:'end',hint:'inside'}:null;const n=state.nodes.find(n=>n.id===row.dataset.treeNode),box=row.getBoundingClientRect(),ratio=(e.clientY-box.top)/box.height;const placement=ratio<.25?'before':ratio>.75?'after':n.kind==='section'?'end':'after';return {element:row,parent_id:placement==='end'?n.id:n.parent_id,anchor_id:placement==='end'?null:n.id,placement,hint:placement==='end'?'inside':placement};}
 nav.ondragstart=e=>{const row=e.target.closest('[data-tree-node]');if(dragLocked()||!row||inlineDrafts.size){e.preventDefault();return;}const id=row.dataset.treeNode;draggedIds=multi.has(id)?[...multi]:[id];e.dataTransfer.effectAllowed='move';e.dataTransfer.setData('text/plain',id);};
 nav.ondragover=e=>{if(dragLocked()||!draggedIds)return;clearDrop();const t=targetFor(e),banned=forbiddenMove(draggedIds);if(!t||banned.has(t.parent_id)||banned.has(t.anchor_id))return;e.preventDefault();e.dataTransfer.dropEffect='move';t.element.dataset.drop=t.hint;};
 nav.ondrop=e=>{if(dragLocked()||!draggedIds)return;e.preventDefault();const t=targetFor(e),ids=draggedIds;draggedIds=null;clearDrop();if(t)void guard(()=>performMove(ids,{parent_id:t.parent_id,anchor_id:t.anchor_id,placement:t.placement}))();};
 nav.ondragend=()=>{draggedIds=null;clearDrop();};
}
class SurveyDraft{
 constructor(read,write,status){this.read=read;this.write=write;this.status=status;this.dirty=false;this.generation=0;this.composing=false;this.saving=null;}
 changed(){this.dirty=true;this.generation++;this.status('待保存…');}
 flush(){
  if(this.saving)return this.saving;
  if(this.composing)return Promise.reject(Error('请先完成正在输入的文字，再切换调查条目。'));
  if(!this.dirty)return Promise.resolve();
  this.saving=Promise.resolve().then(async()=>{try{while(this.dirty){
   if(this.composing)throw Error('请先完成正在输入的文字，再切换调查条目。');
   const generation=this.generation,payload=this.read();this.status('保存中…');await this.write(payload);
   if(generation===this.generation)this.dirty=false;
  }this.status('已保存');}catch(error){this.status('未保存：'+error.message,true);throw error;}}).finally(()=>{this.saving=null;});return this.saving;
 }
}
const richBox=(id,title,runs=[])=>CorporiumRichText.box(id,title,runs,state.writing_types);
const readRich=el=>CorporiumRichText.read(el);
const bindRich=root=>CorporiumRichText.bind(root,state.writing_types);
const editor=document.createElement('section');editor.id='survey-edit-dialog';editor.className='survey-inline-editor';editor.hidden=true;editor.setAttribute('aria-label','调查条目页内编辑');
editor.innerHTML='<form id="survey-edit-form"><div class="survey-inline-heading"><strong id="survey-edit-title"></strong><button id="survey-edit-close" type="submit">完成编辑</button></div><div id="survey-edit-fields"></div><div class="survey-inline-actions"><small id="survey-save-status" role="status"></small><button id="survey-retry" type="button" hidden>重试保存</button><button id="survey-save-copy" type="button" hidden>另存为条目副本</button><button id="survey-discard" type="button">放弃未保存内容</button></div></form>';
document.body.append(editor);
function parkEditor(){clearTimeout(editTimer);editor.hidden=true;document.body.append(editor);$('survey-content').classList.remove('survey-creating');editing=null;}
function statusOptions(value){return Object.entries(statusNames).map(([k,v])=>`<option value="${k}" ${k===value?'selected':''}>${v}</option>`).join('');}
function orderedNodes(parent=null,depth=0){return state.nodes.filter(n=>n.parent_id===parent).flatMap(n=>[{...n,depth},...orderedNodes(n.id,depth+1)]);}
function showEditor(d,host){
 editing=d;d.language=activeLanguage;d.version=state.version;
 $('survey-content').classList.toggle('survey-creating',!!d.wasNew);
 d.draft=new SurveyDraft(()=>editPayload(d),async payload=>{
  const result=await originalApi('survey-'+(d.type==='node'?'save':'evidence'),{...payload,version:d.version,_language:d.language});
  applySaved(d,result);await window.corporiumRefreshUndoState?.().catch(()=>corporiumStatus('内容已保存，操作记录暂未刷新。'));
 },(text,error=false)=>{if(editing!==d)return;$('survey-save-status').textContent=text;$('survey-retry').hidden=!error;$('survey-save-copy').hidden=!(error&&d.type==='node');});
 $('survey-retry').hidden=$('survey-save-copy').hidden=true;
 editor.hidden=false;if(host){const head=host.querySelector(':scope > .survey-card-head,:scope > .entry-head');if(head)head.after(editor);else host.prepend(editor);}else $('survey-content').prepend(editor);
 editor.scrollIntoView({block:'nearest'});
}
function applySaved(d,result){
 d.version=result.version;
 if(d.type==='node')d.node=result.node;else d.e=result.evidence;
 if(activeLanguage!==d.language)return;
 state.version=result.version;const at=state.nodes.findIndex(n=>n.id===result.node.id);if(at<0)state.nodes.push(result.node);else state.nodes[at]=result.node;
 tree();paintSavedNode(result.node);if(result.evidence)paintSavedEvidence(result.evidence);
}
function paintSavedNode(n){
 const card=panel.querySelector('[data-survey-node="'+n.id+'"]');if(!card)return;const head=card.querySelector('.survey-card-head');
 head.querySelector('h2,h3').innerHTML=label(n);head.querySelector('.survey-status').textContent=statusNames[n.body.status];
 let view=card.querySelector(':scope > .survey-rich');if(hasText(n.body.content)){if(!view){view=document.createElement('div');view.className='survey-rich';head.after(view);}view.innerHTML=markup(n.body.content);}else view?.remove();
 const notes=card.querySelector(':scope > .survey-notes');notes.querySelector('summary').textContent=hasText(n.body.notes)?'研究笔记 · 已填写':'添加研究笔记';notes.querySelector('.survey-rich').innerHTML=markup(n.body.notes)||'<small>暂无笔记</small>';
 const question=card.closest('.survey-question');if(question)question.querySelector(':scope > summary').innerHTML=label(n)+' <small>'+statusNames[n.body.status]+' · '+n.evidence_count+' 条例证</small>';
}
function paintSavedEvidence(e){
 const card=[...panel.querySelectorAll('[data-evidence-edit]')].find(b=>b.dataset.evidenceEdit===e.id)?.closest('.survey-evidence');if(!card)return;
 card.querySelector('.entry-head>small').textContent=(e.kind==='corpus'?'文本引用':'独立例句')+(e.body.judgment?' · '+e.body.judgment:'')+(e.body.judges?.length?' · 判断者：'+e.body.judges.map(id=>state.people.find(p=>p.id===id)?.name||'已删除').join('、'):'');
 let context=card.querySelector(':scope > details');if(hasText(e.body.context)){if(!context){context=document.createElement('details');card.append(context);}context.innerHTML='<summary>调查提示</summary><div class="survey-rich">'+markup(e.body.context)+'</div>';}else context?.remove();
 let notes=card.querySelector(':scope > .survey-local-note');if(hasText(e.body.notes)){if(!notes){notes=document.createElement('div');notes.className='survey-local-note';card.append(notes);}notes.innerHTML='<small>本处研究笔记</small><div class="survey-rich">'+markup(e.body.notes)+'</div>';}else notes?.remove();
}
function editNode(n,parent=null,kind='section',notes=false){
 noSentenceDraft();const d={type:'node',node:n,parent,kind:n?.kind||kind,wasNew:!n},excluded=new Set();
 if(n){excluded.add(n.id);let changed=true;while(changed){changed=false;for(const x of state.nodes)if(excluded.has(x.parent_id)&&!excluded.has(x.id)){excluded.add(x.id);changed=true;}}}
 $('survey-edit-title').textContent=n?'编辑调查条目':'新建'+(kind==='question'?'问题':'模块或条目');
 $('survey-edit-fields').innerHTML=`<label>标题<input id="survey-edit-name" required maxlength="500" value="${esc(n?.title||'')}"></label><div class="survey-form-row"><label>所属上层<select id="survey-edit-parent"><option value="">顶层</option>${orderedNodes().filter(x=>x.kind==='section'&&!excluded.has(x.id)).map(x=>`<option value="${esc(x.id)}">${'　'.repeat(x.depth)}${label(x)}</option>`).join('')}</select></label><label>调查进度<select id="survey-edit-status">${statusOptions(n?.body.status||'unasked')}</select></label></div>${richBox('survey-edit-content','问题说明',n?.body.content)}${richBox('survey-edit-notes','研究笔记',n?.body.notes)}`;
 $('survey-edit-parent').value=n?.parent_id||parent||'';bindRich($('survey-edit-fields'));
 $('survey-save-status').textContent=n?'修改后自动保存。':'填写标题后自动保存。';
 showEditor(d,n?panel.querySelector('[data-survey-node="'+n.id+'"]'):null);$(notes?'survey-edit-notes':'survey-edit-name').focus();
}
function editEvidence(e){
 noSentenceDraft();$('survey-edit-title').textContent='本处笔记与调查判断';
 $('survey-edit-fields').innerHTML=`<div class="survey-form-row"><label>判断<input id="survey-edit-judgment" value="${esc(e.body.judgment||'')}" placeholder="如：自然、需要特定语境、不能确定"></label><label>判断者（可多选）<select id="survey-edit-judges" multiple>${state.people.map(p=>`<option value="${esc(p.id)}" ${(e.body.judges||[]).includes(p.id)?'selected':''}>${esc(p.name)}</option>`).join('')}</select></label></div>${richBox('survey-edit-context','调查提示',e.body.context)}${richBox('survey-edit-notes','本处研究笔记',e.body.notes)}`;
 bindRich($('survey-edit-fields'));$('survey-save-status').textContent='修改后自动保存。';
 const host=[...panel.querySelectorAll('[data-evidence-edit]')].find(b=>b.dataset.evidenceEdit===e.id)?.closest('.survey-evidence');showEditor({type:'evidence',e},host);
}
function editPayload(d=editing){
 if(d.type==='node'){const title=$('survey-edit-name').value.trim();if(!title)throw Error('请填写调查条目的标题，或放弃空白新条目。');return {id:d.node?.id,parent_id:$('survey-edit-parent').value,kind:d.kind,title,body:{...d.node?.body,status:$('survey-edit-status').value,content:readRich($('survey-edit-content')),notes:readRich($('survey-edit-notes'))}};}
 const e=d.e;return {node_id:e.node_id,evidence_id:e.id,kind:e.kind,record_id:e.record_id,body:{judgment:$('survey-edit-judgment').value,judges:[...$('survey-edit-judges').selectedOptions].map(o=>o.value),context:readRich($('survey-edit-context')),notes:readRich($('survey-edit-notes'))}};
}
async function flush(){clearTimeout(editTimer);if(editing)await editing.draft.flush();}
function changed(event={}){
 if(!editing)return;const d=editing;d.draft.changed();clearTimeout(editTimer);
 if(event.isComposing||d.draft.composing)return;
 if(d.type==='node'&&!d.node&&!$('survey-edit-name').value.trim()){ $('survey-save-status').textContent='填写标题后自动保存。';return;}
 editTimer=setTimeout(()=>void flush().catch(()=>{}),900);
}
$('survey-edit-fields').addEventListener('input',changed);
$('survey-edit-fields').addEventListener('change',changed);
$('survey-edit-fields').addEventListener('compositionstart',()=>{if(editing){editing.draft.composing=true;clearTimeout(editTimer);}});
$('survey-edit-fields').addEventListener('compositionend',()=>{if(editing){editing.draft.composing=false;changed();}});
$('survey-edit-fields').addEventListener('focusout',e=>{if(!editor.contains(e.relatedTarget))void flush().catch(()=>{});});
async function finishEditor(){const d=editing;await flush();if(d?.wasNew&&d.node)selection=d.node.id;parkEditor();await load();}
$('survey-edit-form').onsubmit=e=>{e.preventDefault();void finishEditor().catch(()=>{});};
$('survey-retry').onclick=()=>void flush().catch(()=>{});
$('survey-discard').onclick=safe(async()=>{const d=editing;if(d?.draft.saving)await d.draft.saving.catch(()=>{});if(d?.draft.dirty&&!await corporiumConfirm('放弃尚未保存的修改？此前已自动保存的内容保留，可用撤销恢复。'))return;if(d){d.draft.dirty=false;if(d.wasNew&&d.node)selection=d.node.id;}parkEditor();await load();});
$('survey-save-copy').onclick=safe(async()=>{
 const d=editing;if(!d||d.type!=='node')return;if(d.draft.saving)await d.draft.saving.catch(()=>{});
 editor.inert=true;
 try{const payload=editPayload(d),fresh=await originalApi('survey?language='+encodeURIComponent(d.language));delete payload.id;payload.title=payload.title.slice(0,494)+' · 副本';
  const result=await originalApi('survey-save',{...payload,version:fresh.version,_language:d.language});state=fresh;applySaved(d,result);d.draft.dirty=false;selection=result.node.id;parkEditor();tree();await content();editNode(result.node);$('survey-save-status').textContent='已保存为独立副本';await window.corporiumRefreshUndoState?.().catch(()=>corporiumStatus('副本已保存，操作记录暂未刷新。'));
 }catch(error){$('survey-save-status').textContent='副本未保存：'+error.message;}finally{editor.inert=false;}
});
window.corporiumFlushSurvey=flush;window.corporiumLeaveSurvey=parkEditor;
window.corporiumSurveyDirty=()=>!!(editing?.draft.dirty||editing?.draft.saving);
window.addEventListener('beforeunload',e=>{if(window.corporiumSurveyDirty()){e.preventDefault();e.returnValue='';}});
const previousSurveyUndo=undoCommand;undoCommand=async function(kind){await flush();parkEditor();return previousSurveyUndo(kind);};
makeDialog('survey-copy-dialog','<h2>复制调查条目</h2><p>复制当前条目及下级结构，原句不会复制。</p><label><input type="checkbox" id="survey-copy-evidence"> 包括研究笔记、调查进度和例证引用</label><button id="survey-copy-confirm" class="primary">创建副本</button>');
$('survey-copy-confirm').onclick=guard(async()=>{await mutate('copy',{id:selection,include_evidence:$('survey-copy-evidence').checked});$('survey-copy-dialog').close();});
makeDialog('survey-template-dialog','<h2>调查模板管理</h2><p id="survey-template-folder" class="survey-template-label"></p><p>模板包含结构、问题说明及书写类型；导入为独立副本。研究笔记、调查进度和例句回答不随模板保存。</p><div id="survey-template-list"></div><hr><h3>内置：汉语语法调查粗纲</h3><p>仅包含分类标题，可导入后修改，再存为自己的模板。</p><button id="survey-template-confirm">导入内置粗纲</button>');
async function showTemplates(){const d=await api('survey-templates');$('survey-template-folder').textContent='模板文件夹：'+d.folder;$('survey-template-list').innerHTML=d.items.map(t=>`<div class="survey-template-row" data-template-id="${esc(t.id)}"><strong>${esc(t.name)}</strong><small>${t.count} 项</small><button data-template-action="import">导入</button><button data-template-action="copy">复制</button><button data-template-action="rename">重命名</button><button data-template-action="delete" title="双击删除模板">删除(双击)</button></div>`).join('')||'<p>还没有自定义模板。在提纲中选择模块、项目或问题，点击「存为模板」。</p>';
 for(const row of $('survey-template-list').children){if(!row.dataset.templateId)continue;const t=d.items.find(t=>t.id===row.dataset.templateId);for(const b of row.querySelectorAll('[data-template-action]')){const run=guard(async()=>{const action=b.dataset.templateAction,payload={action,id:t.id};if(action==='delete'){if(!await corporiumConfirm('删除模板「'+t.name+'」？已导入的调查不受影响；文件移入模板文件夹的 deleted 子目录。'))return;payload.confirmed=true;}if(action==='rename'||action==='copy'){const name=await corporiumPrompt('模板名称',t.name+(action==='copy'?' · 副本':''));if(name===null)return;payload.name=name;}const r=await call('template-file',payload);if(action==='import'){multi.clear();selectionAnchor=r.id;selection=r.id;expanded.add(r.id);await load();await refreshUndo();$('survey-template-dialog').close();}else await showTemplates();});if(b.dataset.templateAction==='delete')b.ondblclick=run;else b.onclick=run;}}
 if(!$('survey-template-dialog').open)$('survey-template-dialog').showModal();}
$('survey-template').onclick=guard(async()=>{if(activeLanguage==='all'){await corporiumAlert('请先选择一种语言');return;}await showTemplates();});$('survey-template-confirm').onclick=guard(async()=>{multi.clear();selectionAnchor=null;const r=await mutate('template',{});expanded.add(r.id);tree();$('survey-template-dialog').close();});
$('survey-root').onclick=guard(()=>{if(activeLanguage==='all'){void corporiumAlert('请先选择一种语言');return;}editNode(null);});
$('survey-library').onclick=guard(async()=>{$('library-source').value='independent';libraryPage=1;await setWorkspace('library');});$('library-survey-back').onclick=guard(()=>setWorkspace('survey'));
makeDialog('survey-picker','<h2>引用已有例句</h2><div class="search-row"><input id="survey-picker-query" placeholder="原文、IPA、语素、标注、翻译、备注"><input id="survey-picker-text-query" aria-label="按文本名称筛选" placeholder="筛选文本名称"><select id="survey-picker-text" aria-label="选择引用文本"><option value="">全部文本</option></select><select id="survey-picker-source"><option value="all">全部来源</option><option value="corpus">文本句子</option><option value="independent">独立例句库</option></select><button id="survey-picker-search">检索</button></div><div id="survey-picker-results"></div><nav id="survey-picker-pages"></nav>');
async function openPicker(nid){noSentenceDraft();pickerNode=nid;pickerPage=1;$('survey-picker-results').textContent='正在读取例句…';$('survey-picker').showModal();const texts=await api('texts');pickerTexts=texts.filter(t=>activeLanguage==='all'||t.language_id===activeLanguage);fillPickerTexts();await picker();}
let pickerTexts=[];
function fillPickerTexts(){const select=$('survey-picker-text'),old=select.value,q=$('survey-picker-text-query').value.toLocaleLowerCase();select.innerHTML='<option value="">全部文本</option>'+pickerTexts.filter(t=>t.title.toLocaleLowerCase().includes(q)).map(t=>`<option value="${esc(t.id)}">${esc(t.title)}</option>`).join('');if([...select.options].some(o=>o.value===old))select.value=old;}
$('survey-picker-text-query').oninput=()=>{fillPickerTexts();};
$('survey-picker-text').onchange=()=>{if($('survey-picker-text').value)$('survey-picker-source').value='corpus';$('survey-picker-search').click();};
let pickerRequest=0;async function picker(){const seq=++pickerRequest;$('survey-picker-results').textContent='正在检索…';$('survey-picker-pages').replaceChildren();try{const data=await api('example-library?'+new URLSearchParams({q:$('survey-picker-query').value,source:$('survey-picker-source').value,text_id:$('survey-picker-source').value==='independent'?'':$('survey-picker-text').value,page:pickerPage}));if(seq!==pickerRequest)return;$('survey-picker-results').innerHTML=data.items.map((e,i)=>`<div class="survey-pick-row"><div><small>${esc(e.title)}${e.position?' · '+e.position:''}</small><p>${esc(e.body.ipa||e.body.original||'')}</p><small>${esc(e.body.translation)}</small></div><button data-pick-result="${i}">引用</button></div>`).join('')||'<p>没有符合条件的例句。</p>';
 $('survey-picker-results').querySelectorAll('[data-pick-result]').forEach(b=>b.onclick=guard(async()=>{const e=data.items[+b.dataset.pickResult];await mutate('evidence',{node_id:pickerNode,kind:e.kind,record_id:e.id,body:{}});$('survey-picker').close();}));topPagination($('survey-picker-pages'),data.page,data.pages,async p=>{pickerPage=p;await picker();});}catch(e){if(seq!==pickerRequest)return;$('survey-picker-results').textContent='检索未完成，请重试。';$('survey-picker-pages').replaceChildren();throw e;}}
$('survey-picker-search').onclick=safe(async()=>{pickerPage=1;await picker();});$('survey-picker-query').onkeydown=e=>{if(e.key==='Enter')$('survey-picker-search').click();};$('survey-picker-source').onchange=$('survey-picker-search').onclick;
const oldWorkspace=setWorkspace;setWorkspace=async function(name){await flush();if(name!==workspace)parkEditor();await oldWorkspace(name);panel.hidden=name!=='survey';tab.setAttribute('aria-pressed',String(name==='survey'));if(name==='survey'&&!window.CorporiumViews?.current('survey'))await load();};tab.onclick=guard(()=>setWorkspace('survey'));
const oldLanguage=switchLanguage;switchLanguage=async function(lid){await flush();parkEditor();await oldLanguage(lid);multi.clear();selectionAnchor=null;selection=remembered.get(activeLanguage)||null;if(workspace==='survey')await load();};
const oldRefresh=refreshExampleViews;refreshExampleViews=async function(){await oldRefresh();if(workspace==='survey')await load();};
const oldUndo=refreshUndo;refreshUndo=async function(){await oldUndo();if(workspace==='survey'&&!editing)await load();};
window.CorporiumSurvey={async openExample(id){const d=await api('independent-example?id='+encodeURIComponent(id));await setWorkspace('library');await openStandalone({language_id:d.language_id},d);}};
})();
