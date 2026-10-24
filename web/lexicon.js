// Linking preserves the current gloss; later meaning edits sync by stable sense IDs.
let exampleKind='all',exampleRequest=0;
let workspace='corpus',dictionaryPage=1,dictionarySelection=null,dictionaryRequest=0;
let editingLexeme=null,lexemeDirty=false,linkUnit=null,linkLexeme=null,linkRequest=0;
const tagNames={register:'语域',region:'地域',period:'使用年代与状态',generation:'使用人群与代际',domain:'领域',other:'其他'};
const main=document.querySelector('main'),corpusWorkspace=document.createElement('div');
corpusWorkspace.id='corpus-workspace';
for(const child of [...main.children])if(child!==undoPanel)corpusWorkspace.append(child);
main.append(corpusWorkspace);
const workspaceTabs=document.createElement('nav');workspaceTabs.className='workspace-tabs';workspaceTabs.setAttribute('aria-label','工作区');
workspaceTabs.innerHTML='<button id="workspace-corpus" aria-pressed="true">文本语料</button><button id="workspace-dictionary" aria-pressed="false">词典</button>';
main.prepend(workspaceTabs);
const dictionaryPanel=document.createElement('section');dictionaryPanel.id='dictionary-workspace';dictionaryPanel.hidden=true;
dictionaryPanel.innerHTML='<div class="dictionary-heading"><div><div class="eyebrow">LEXICON · 词典与语料例证</div><h1 id="dictionary-title">词典</h1><p>词条 → 词类用法 → 义项。语料中的简短标注独立保留。</p></div><button id="new-lexeme" class="primary">＋ 新建词条</button></div><div class="search-row"><input id="dictionary-query" aria-label="检索词典" placeholder="检索词形、释义、变体、使用标签或备注"><button id="dictionary-search">检索词典</button></div><p id="dictionary-notice" role="status"></p><div class="dictionary-columns"><div class="dictionary-list-panel"><div class="dictionary-list-controls"><div id="dictionary-count"></div><label>每页 <select id="dictionary-page-size" aria-label="每页条目数"><option>10</option><option>20</option><option selected>30</option><option>50</option><option>100</option><option>200</option><option>500</option><option>1000</option><option value="all">全部</option></select></label></div><nav id="dictionary-top-pagination" aria-label="词典上方分页"></nav><div id="dictionary-list"></div><div class="pagination"><button id="dictionary-prev">上一页</button><span id="dictionary-page"></span><button id="dictionary-next">下一页</button></div></div><section id="dictionary-detail"><div class="empty">选择一个词条查看详细释义与语料例证。</div></section></div>';
main.append(dictionaryPanel);
setupSidebarTitlePan($('dictionary-list'),{row:'[data-lexeme]',mask:'.lexeme-title-mask',text:'.lexeme-title'});
try{const saved=localStorage.getItem('corporium-dictionary-page-size');if(['10','20','30','50','100','200','500','1000','all'].includes(saved))$('dictionary-page-size').value=saved;}catch{}
$('dictionary-page-size').onchange=dictSafe(async()=>{dictionaryPage=1;window.resetMorphemePage?.();try{localStorage.setItem('corporium-dictionary-page-size',$('dictionary-page-size').value);}catch{}await loadDictionary();});
function dictSafe(fn){return async(...args)=>{try{await fn(...args)}catch(e){if(e.name==='AbortError')return;$('dictionary-notice').textContent=e.message;$('notice').textContent=e.message;}};}
async function setWorkspace(name){
 workspace=name;
 // Draft guards in the outer wrappers finish before this activation. Commit
 // all panel visibility and navigation geometry before any asynchronous read.
 const roots={corpus:'corpus-workspace',dictionary:'dictionary-workspace',library:'example-library',grammar:'grammar-workspace',survey:'survey-workspace',timeline:'timeline-workspace',analysis:'analysis-workspace'};
 for(const [kind,id] of Object.entries(roots)){
  const panel=$(id);if(panel)panel.hidden=kind!==name;
  $('workspace-'+kind)?.setAttribute('aria-pressed',String(kind===name));
 }
 window.corporiumActivateWorkspace?.();
 window.corporiumSyncInlineDrafts?.();
 if(name==='dictionary'&&!window.corporiumReuseDictionary?.())await loadDictionary();
}
$('workspace-corpus').onclick=dictSafe(()=>setWorkspace('corpus'));
$('workspace-dictionary').onclick=dictSafe(()=>setWorkspace('dictionary'));
document.querySelector('aside').addEventListener('click',e=>{if(e.target.closest('[data-text],#all,#new,#import'))dictSafe(()=>setWorkspace('corpus'))();},true);
new MutationObserver(()=>{if(workspace==='dictionary')$('dictionary-notice').textContent=$('notice').textContent;}).observe($('notice'),{childList:true,subtree:true,characterData:true});
function showTags(tags=[]){return tags.map(t=>`<span class="lex-tag" title="${esc(t.note||'')}">${esc(tagNames[t.type]||t.type)}：${esc(t.value)}${t.note?' · '+esc(t.note):''}</span>`).join('');}
async function loadDictionary(withDetail=true){
  const seq=++dictionaryRequest,lid=activeLanguage;
  const list=$('dictionary-list'),listKey=JSON.stringify([lid,dictionaryPage,$('dictionary-query').value,$('dictionary-page-size').value,window.dictionaryOrganizationParams?.(),window.dictionarySearchParams?.()]),listScroll=list.dataset.pageKey===listKey?list.scrollTop:0;
  const result=await api('lexemes?'+new URLSearchParams({q:$('dictionary-query').value,page:dictionaryPage,page_size:$('dictionary-page-size').value,summary:'1',...(window.dictionaryOrganizationParams?.()||{}),...(window.dictionarySearchParams?.()||{})}));
  if(seq!==dictionaryRequest||lid!==activeLanguage)return;
  window.dictionaryOrganizationResult?.(result);
  dictionaryPage=result.page;
  topPagination($('dictionary-top-pagination'),result.page,result.pages,async target=>{dictionaryPage=target;await loadDictionary();});$('dictionary-top-pagination').hidden=result.pages<=1;$('dictionary-list').nextElementSibling.hidden=result.pages<=1;
  $('dictionary-title').textContent=(languageList.find(l=>l.id===activeLanguage)?.name||'全部语言')+' · 词典';
  $('dictionary-count').textContent=result.total+' 个词条';$('dictionary-page').textContent=result.page+' / '+result.pages;
  $('dictionary-prev').disabled=result.page===1;$('dictionary-next').disabled=result.page===result.pages;
  renderDictionaryList($('dictionary-list'),result.items,{attribute:'data-lexeme',select:id=>dictSafe(()=>showLexeme(id))(),empty:'<p class="empty">暂无词条。可以新建，也可以从语料中的词形开始。</p>',transform:window.dictionaryClassList,html:x=>{if(x.dictionaryClass)return window.dictionaryClassHeading(x.dictionaryClass);const markup=(x=>{const pos=x.body.usages.map(u=>usageLabel(u)).join(' / ');return `<button class="lexeme-list-item ${dictionarySelection===x.id?'active':''}" data-lexeme="${esc(x.id)}" aria-label="${esc(lexemePlainLabel(x)+(pos?'，'+pos:''))}" aria-pressed="${dictionarySelection===x.id}"><span class="lexeme-list-heading"><span class="lexeme-title-mask" title="${esc(lexemePlainLabel(x))}"><strong class="lexeme-title" style="${languageTypography(JSON.parse(languageList.find(l=>l.id===(x.language_id||activeLanguage))?.metadata||'{}'))}">${lexemeLabel(x)}</strong></span><span class="lexeme-list-pos" title="${esc(pos)}">${esc(pos)}</span></span>${x.body.homonym_note?'<small>'+esc(x.body.homonym_note)+'</small>':''}</button>`;})(x);return window.dictionarySelectableRow?.(x,markup)||markup;}});
  list.dataset.pageKey=listKey;list.scrollTop=listScroll;
  if(withDetail&&dictionarySelection){try{await showLexeme(dictionarySelection);}catch{$('dictionary-detail').innerHTML='<p>该词条已不存在，或已撤销。</p>';dictionarySelection=null;}}
}
const refreshDictionaryListOnly=loadDictionary;
async function refreshUnlinkedExamples(refresh){
 const scope=window.dictionarySearchScope?.(),filtered=scope?.query?.trim()||scope?.search?.conditions?.length;
 // Evidence text participates in dictionary searches. Keep filtered results
 // current without recreating the open detail and its unrelated sections.
 await Promise.all([refresh(),filtered?refreshDictionaryListOnly(false):Promise.resolve()]);
}
$('dictionary-search').onclick=dictSafe(async()=>{dictionaryPage=1;await loadDictionary();});
$('dictionary-query').onkeydown=e=>{if(e.key==='Enter')$('dictionary-search').click();};
$('dictionary-prev').onclick=dictSafe(async()=>{dictionaryPage--;await loadDictionary();});
$('dictionary-next').onclick=dictSafe(async()=>{dictionaryPage++;await loadDictionary();});
// Selection belongs to this visible page, never to hidden pages or filters.
function wireExampleSelection(section,items,unlink){
 const selected=new Set(),boxes=[...section.querySelectorAll('[data-example-select]')];let busy=false;
 const bars=[...section.querySelectorAll('[data-example-page-actions]')];
 for(const bar of bars)bar.insertAdjacentHTML('beforeend','<label class="example-select-all"><input type="checkbox" data-example-all>勾选本页全部</label><button type="button" data-example-unlink-selected disabled>解除选中关联</button>');
 function sync(){
  for(const box of boxes)box.checked=selected.has(+box.dataset.exampleSelect);
  for(const bar of bars){const all=bar.querySelector('[data-example-all]'),button=bar.querySelector('[data-example-unlink-selected]');all.checked=items.length>0&&selected.size===items.length;all.indeterminate=selected.size>0&&selected.size<items.length;all.disabled=busy||!items.length;button.disabled=busy||!selected.size;button.textContent=busy?'正在解除…':'解除选中关联'+(selected.size?'（'+selected.size+'）':'');}
 }
 const run=dictSafe(async rows=>{
  if(busy||!rows.length)return;
  busy=true;const controls=[...section.querySelectorAll('button,input,select')].map(el=>[el,el.disabled]);for(const [el] of controls)el.disabled=true;sync();
  try{await leaveSentenceDrafts();if(section.isConnected)await unlink(rows);}finally{busy=false;for(const [el,disabled] of controls)el.disabled=disabled;sync();}
 });
 for(const box of boxes)box.onchange=()=>{const i=+box.dataset.exampleSelect;if(box.checked)selected.add(i);else selected.delete(i);sync();};
 for(const bar of bars){bar.querySelector('[data-example-all]').onchange=e=>{selected.clear();if(e.target.checked)items.forEach((_,i)=>selected.add(i));sync();};bar.querySelector('[data-example-unlink-selected]').onclick=()=>run([...selected].map(i=>items[i]));}
 section.querySelectorAll('[data-example-unlink]').forEach(button=>button.onclick=()=>run([items[+button.dataset.exampleUnlink]]));sync();
}
function renderLexemeExamples(x,morphData,examples,request){
 const id=x.id,b=x.body,section=$('corpus-examples-section');if(!section||dictionarySelection!==id||request!==exampleRequest)return;
 section.classList.toggle('brief-empty',!(examples.reference_total??examples.total));
 section.innerHTML=`<h3>语料引用 · ${examples.occurrences??examples.total} 次出现</h3>${examples.total?`<p><small>${examples.total} 条关联记录（包括待核对的旧关联）</small></p>`:''}<label ${(examples.reference_total??examples.total)?'':'hidden'}>例证类型 <select id="example-kind"><option value="all">全部</option><option value="word">整词</option><option value="morpheme">语素</option></select></label>${examples.total?'<p><small>显示原句及其当前 gloss；待核对记录保留旧形式，不会自动转挂到新词上。</small></p>':''}<nav id="examples-top-pagination" ${examples.total?'':'hidden'} aria-label="语料例证上方分页"></nav><div id="lexeme-examples"></div><nav id="examples-bottom-pagination" ${examples.total?'':'hidden'} aria-label="语料例证下方分页"></nav>`;
 section.exampleRequest=(section.exampleRequest||0)+1;
 const refresh=async target=>{
  await leaveSentenceDrafts();const seq=++section.exampleRequest,current=()=>seq===section.exampleRequest&&section.isConnected&&request===exampleRequest;
  try{const next=await api('lexeme-examples?'+new URLSearchParams({id,page:target,kind:exampleKind,form_id:exampleForm}));if(current())renderLexemeExamples(x,morphData,next,request);}
  catch(error){if(current())renderLexemeExamples(x,morphData,examples,request);throw error;}
 };
 for(const nav of [section.querySelector('#examples-top-pagination'),section.querySelector('#examples-bottom-pagination')]){nav.dataset.examplePageActions='';if(examples.total)topPagination(nav,examples.page,examples.pages,refresh);}
 $('example-kind').value=exampleKind;$('example-kind').onchange=dictSafe(async()=>{exampleKind=$('example-kind').value;await refresh(1);});
  $('lexeme-examples').innerHTML=examples.items.map((e,i)=>{
    const usage=paradigmUsages(b).find(u=>u.id===e.usage_id),sense=usage?.senses.find(s=>s.id===e.sense_id);
    return `<article class="lex-example ${e.needs_review?'needs-review':''}"><div class="lex-example-source"><input type="checkbox" data-example-select="${i}" aria-label="选择关联 ${i+1}"><strong class="dictionary-wordform">${esc(e.form)}</strong> <span class="gloss">${richGloss(e.display_gloss??e.gloss,x.language_id)}</span><small> · ${e.kind==='word'?'整词':'语素'}${e.needs_review?' · '+((e.review_reason?'待核对：'+esc(e.review_reason):e.component_review?'待核对：关联的形态分析组分已改变或删除':'待核对：原单位已失效或语言已改变')):''}</small></div><div class="lex-example-classification"><span>${esc(usage?.pos||'词类未定')} / ${esc(sense?.short_gloss||'义项未定')}</span>${morphEvidence(e,b,morphData.tags)}</div>${e.entry?`<p>${esc(e.title)} · 第 ${e.position} 句</p><div class="lex-example-body">${renderDictionaryExample({...e.entry,text_language_id:e.text_language},'corpus',e.entry_id,[e])}</div>`:'<p>原句已删除；撤销删除可恢复。</p>'}<p class="preserve-lines">${esc(dictionaryLinkNote(e.notes))}</p><div class="lex-example-footer">${e.entry?`<button data-example-open="${i}">返回原句</button>`:''}<button data-example-unlink="${i}">解除关联</button></div></article>`;
  }).join('');
  $('lexeme-examples').querySelectorAll('[data-example-open]').forEach(button=>button.onclick=dictSafe(async()=>{
    const e=examples.items[Number(button.dataset.exampleOpen)];
    await setWorkspace('corpus');if(activeLanguage!==e.text_language)await switchLanguage(e.text_language);
    clearFilters();await loadTexts();window.CorporiumDialogue?.showOriginal(e.text_id);await selectText(e.text_id);page=Math.ceil(e.position/pageSize());await search();$('entry-'+e.entry_id)?.scrollIntoView({block:'center'});
    if(e.needs_review)$('notice').textContent='请点击当前词形重新建立关联，再解除词典中的旧关联。旧关联不会被自动转移。';
  }));

 wireExampleSelection(section,examples.items,async rows=>{await api('lexeme-unlink',{items:rows.map(e=>({id:e.id,revision:e.revision})),lexeme_id:id,_language:x.language_id});await refreshUnlinkedExamples(()=>refresh(examples.page));});
 $('dictionary-example-controls')?.classList.toggle('brief-empty',section.classList.contains('brief-empty')&&$('standalone-examples')?.classList.contains('brief-empty'));
}

async function showLexeme(id,examplePage=1){
  if(exampleFormOwner!==id){exampleForm='all';exampleFormOwner=id;}
  dictionarySelection=id;const request=++exampleRequest;
  // Reflect the click immediately, independently of detail/network latency.
  const buttons=$('dictionary-list').querySelectorAll('[data-lexeme].active');
  for(const button of buttons){button.classList.remove('active');button.setAttribute('aria-pressed','false');}
  const current=$('dictionary-list').querySelector('[data-lexeme="'+CSS.escape(id)+'"]');
  if(current){current.classList.add('active');current.setAttribute('aria-pressed','true');}
  const x=await api('lexeme?id='+encodeURIComponent(id));
  if(dictionarySelection!==id||request!==exampleRequest)return;
  $('dictionary-detail').style.cssText=languageTypographyCSS(JSON.parse(languageList.find(l=>l.id===x.language_id)?.metadata||'{}'));
  if(!['all','unassigned'].includes(exampleForm)&&!x.body.variants.some(v=>v.id===exampleForm))exampleForm='all';
  const [examples,morphData]=await Promise.all([api('lexeme-examples?'+new URLSearchParams({id,page:examplePage,kind:exampleKind,form_id:exampleForm})),api('morphology-options?'+new URLSearchParams({language:x.language_id,entry_id:id})),window.corporiumPrepareLexeme?.(x)]);
  if(dictionarySelection!==id||request!==exampleRequest)return;
  const b=x.body;
  $('dictionary-detail').innerHTML=`<div class="dictionary-heading lexeme-heading"><div class="lexeme-summary"><div class="lexeme-identity"><h2 class="dictionary-wordform">${lexemeLabel(x)}</h2><span class="lexeme-entry-type ${!b.entry_type||b.entry_type==='unspecified'?'brief-empty':''}">${esc(morphEntryTypes[b.entry_type]||'尚未分类')}</span></div><div class="lexeme-writing-classes"><div class="orthography-display">${(b.orthographies||[]).map(o=>`<div><small>${esc(o.label)}</small><span style="font-family:${orthographyStyle(o.font)}">${esc(o.text)}</span></div>`).join('')}</div>${wsMembershipsView(x,morphData)}</div>${b.homonym_note?`<small>${esc(b.homonym_note)}</small>`:''}</div><div class="lexeme-actions"><button id="edit-lexeme">编辑词条</button><button id="delete-lexeme" class="danger">删除</button></div></div><div class="lexeme-tags">${showTags(b.tags)}</div>${b.notes?`<p class="preserve-lines">${esc(b.notes)}</p>`:''}${b.usages.map((u,i)=>`<section class="lex-usage-view"><div class="usage-heading"><h3 class="${u.pos?'':'brief-empty'}">${i+1}. ${esc(u.pos||'词类待定')}</h3><span class="usage-grammar-features">${featuresView(u.features,morphData.tags)}</span><span class="usage-tags">${showTags(u.tags)}</span></div>${u.subclass?`<p class="usage-subclass-view">子类：${esc(u.subclass)}</p>`:''}${u.notes?`<p class="preserve-lines">${esc(u.notes)}</p>`:''}${u.senses.map((s,j)=>`<div class="lex-sense-view"><div class="sense-heading"><div class="sense-identity"><strong class="${s.short_gloss||s.definition||s.notes||s.tags?.length||s.features?.length?'':'brief-empty'}">义项 ${i+1}.${j+1}</strong><span class="sense-grammar-features">${featuresView(s.features,morphData.tags)}</span><span class="sense-tags">${showTags(s.tags)}</span></div><span class="sense-short-gloss ${s.short_gloss?'':'brief-empty'}">简短标注释义：<b>${richGloss(s.short_gloss||'未填写',x.language_id)}</b></span></div>${s.definition?`<p class="preserve-lines">${esc(s.definition)}</p>`:''}${s.notes?`<p class="preserve-lines">${esc(s.notes)}</p>`:''}</div>`).join('')}</section>`).join('')||'<p class="brief-empty">词类和义项尚待分析。</p>'}${paradigmView(x)}<details class="dictionary-morphology-block"><summary>形态分析、语素构成与条目关系</summary>${morphologyView(x,morphData)}</details><div id="dictionary-example-controls"></div><section id="corpus-examples-section"></section>`;
  $('edit-lexeme').onclick=()=>openLexemeEditor(x);
  $('delete-lexeme').onclick=dictSafe(async()=>{if(!await corporiumConfirm('确认删除词条「'+x.headword+'」？有关联例证时不能删除。'))return;await api('lexeme-delete',{id:x.id,revision:x.revision,confirmed:true,_language:x.language_id});dictionarySelection=null;$('dictionary-detail').textContent='词条已删除，可以撤销。';await loadDictionary();});
  renderLexemeExamples(x,morphData,examples,request);
  await renderStandalone(x,request);
  if(dictionarySelection===id&&request===exampleRequest)wireMorphView(x);
}

makeDialog('lexeme-editor','<h2 id="lexeme-editor-title">词条</h2><form id="lexeme-form"><div class="metadata-grid"><label>词条所属语言<select id="lexeme-language"></select></label><label>词形<input id="lexeme-headword" required></label></div><h3>书写形式</h3><p><small>选择书写类型后统一使用该类型的名称和字体。可先在顶部“管理 → 书写类型管理”中建立类型；未归类的旧内容仍保留单独设置。</small></p><div id="lexeme-orthographies"></div><button type="button" id="add-orthography">＋ 添加书写形式</button><label>同形词下标（可选，正整数）<input id="lexeme-number" type="number" min="1" step="1" placeholder="同形时自动分配"></label><label>同形词区分说明<input id="lexeme-homonym" placeholder="可选，例如：同形词 Ⅰ；动词来源未定"></label><label>词条备注<textarea id="lexeme-notes" rows="2"></textarea></label><details><summary>整个词条的使用标签</summary><div id="lexeme-tags"></div></details><h3>词类用法与义项</h3><p><small>可有多个词类和义项；没有把握时可留空。关联例句默认跟随所选义项的简单释义；本句单独标注保留不变，可撤销。</small></p><div id="lexeme-usages"></div><button type="button" id="add-usage">＋ 添加词类用法</button><details><summary>形式变体</summary><div id="lexeme-variants"></div><button type="button" id="add-variant">＋ 添加变体</button></details><p id="lexeme-error" role="alert"></p><button class="primary" id="save-lexeme" type="submit">保存词条</button></form>');
function tagEditor(container,values=[],changed=()=>{lexemeDirty=true;},catalogue=undefined){
  container.innerHTML='<div class="tag-rows"></div><button type="button" class="add-tag">＋ 添加使用标签</button>';
  function add(t={}){const r=document.createElement('div');r.className='tag-row';r.innerHTML=`<select aria-label="标签类型">${usageTagOptions(t.type,catalogue)}</select><input aria-label="标签内容" placeholder="如：文语、西部、新用法" value="${esc(t.value||'')}"><input aria-label="标签说明" placeholder="补充说明（可选）" value="${esc(t.note||'')}"><button type="button" aria-label="移除此标签">×</button>`;r.querySelector('button').onclick=()=>{r.remove();changed();};container.querySelector('.tag-rows').append(r);}
  values.forEach(add);container.querySelector('.add-tag').onclick=()=>{add();changed();};
}
function readTags(container){return [...container.querySelector('.tag-rows').children].map(r=>({type:r.querySelector('select').value,value:r.querySelectorAll('input')[0].value,note:r.querySelectorAll('input')[1].value}));}
function addSense(container,s={}){
  const row=document.createElement('section');row.className='sense-editor';row.dataset.id=s.id||crypto.randomUUID();
  row.innerHTML=`<div class="lex-row-heading"><strong>义项</strong><button type="button" class="remove-sense">移除义项</button></div><label>简短标注释义<input class="sense-short" value="${esc(s.short_gloss||'')}" placeholder="如：家"></label><label>词典详细释义<textarea class="sense-definition" rows="3" placeholder="完整解释这个意义">${esc(s.definition||'')}</textarea></label><label>用法说明<textarea class="sense-notes" rows="2">${esc(s.notes||'')}</textarea></label><details><summary>仅此义项的使用标签</summary><div class="sense-tags"></div></details><details><summary>此义项的语法特征</summary><div class="sense-features morph-feature-editor">${featurePicker(s.features||[])}</div></details>`;
  tagEditor(row.querySelector('.sense-tags'),s.tags||[]);row.querySelector('.remove-sense').onclick=()=>{if(!row.dispatchEvent(new CustomEvent('corporium-before-sense-remove',{bubbles:true,cancelable:true,detail:{row}})))return;row.remove();lexemeDirty=true;$('lexeme-usages').dispatchEvent(new Event('input',{bubbles:true}));};container.append(row);
}
function addUsage(u={}){
  const row=document.createElement('section');row.className='usage-editor';row.dataset.id=u.id||'';
  row.innerHTML=`<div class="lex-row-heading"><strong>词类用法</strong><button type="button" class="remove-usage">移除此用法</button></div><label>词类<input class="usage-pos" value="${esc(u.pos||'')}" placeholder="如：名词；尚未确定时可留空"></label><label>子类<input class="usage-subclass" value="${esc(u.subclass||'')}" placeholder="如：分布数词、II 类"></label><label>用法备注<textarea class="usage-notes" rows="2">${esc(u.notes||'')}</textarea></label><details><summary>此词类用法的使用标签</summary><div class="usage-tags"></div></details><div class="sense-editors"></div><button type="button" class="add-sense">＋ 添加义项</button>`;
  tagEditor(row.querySelector('.usage-tags'),u.tags||[]);for(const s of u.senses||[])addSense(row.querySelector('.sense-editors'),s);
  row.querySelector('.add-sense').onclick=()=>{addSense(row.querySelector('.sense-editors'));lexemeDirty=true;$('lexeme-usages').dispatchEvent(new Event('input',{bubbles:true}));};row.querySelector('.remove-usage').onclick=()=>{if(!row.dispatchEvent(new CustomEvent('corporium-before-usage-remove',{bubbles:true,cancelable:true,detail:{row}})))return;row.remove();lexemeDirty=true;$('lexeme-usages').dispatchEvent(new Event('input',{bubbles:true}));};$('lexeme-usages').append(row);
}
function addVariant(v={}){
  const row=document.createElement('section');row.className='variant-editor';row.dataset.id=v.id||'';
  row.innerHTML=`<label>变体<input class="variant-form" value="${esc(v.form||'')}"></label><label>变体说明<input class="variant-notes" value="${esc(v.notes||'')}"></label><div class="variant-tags"></div><button type="button" class="remove-variant">移除变体</button>`;
  tagEditor(row.querySelector('.variant-tags'),v.tags||[]);row.querySelector('.remove-variant').onclick=()=>{row.remove();lexemeDirty=true;};$('lexeme-variants').append(row);
}
function openLexemeEditor(x=null,form='',lid=activeLanguage){
  editingLexeme=x;const b=x?.body||{};
  $('lexeme-editor-title').textContent=x?'编辑词条':'新建词条';$('lexeme-language').innerHTML=languageOptions();$('lexeme-language').value=x?.language_id||(lid==='all'?'ordos':lid);$('lexeme-language').disabled=!!x||$('word-link-dialog').open;
  $('lexeme-number').value=b.homonym_number||'';$('lexeme-headword').value=x?.headword||form;$('lexeme-homonym').value=b.homonym_note||'';$('lexeme-notes').value=b.notes||'';
  tagEditor($('lexeme-tags'),b.tags||[]);$('lexeme-usages').replaceChildren();$('lexeme-variants').replaceChildren();
  $('lexeme-orthographies').replaceChildren();for(const o of b.orthographies||[])addOrthography(o);
  for(const u of b.usages||[])addUsage(u);for(const v of b.variants||[])addVariant(v);
  if(!x)addUsage({senses:[{short_gloss:linkUnit?.display_gloss??linkUnit?.gloss??''}]});
  $('lexeme-error').textContent='';lexemeDirty=false;$('lexeme-editor').showModal();
}
$('add-orthography').onclick=()=>{addOrthography();lexemeDirty=true;};
$('new-lexeme').onclick=()=>{linkUnit=null;openLexemeEditor();};
$('add-usage').onclick=()=>{addUsage();lexemeDirty=true;$('lexeme-usages').dispatchEvent(new Event('input',{bubbles:true}));};$('add-variant').onclick=()=>{addVariant();lexemeDirty=true;};
$('lexeme-form').oninput=$('lexeme-form').onchange=e=>{if(!e.target.matches('[data-lexeme-choice-query]'))lexemeDirty=true;};
$('lexeme-editor').addEventListener('cancel',e=>guardDialogDiscard(e,lexemeDirty,'放弃尚未保存的词条修改？'));
function clearLexemeEditState(){lexemeDirty=false;editingLexeme=null;clearCorporiumStatus('lexeme-edit');}
$('lexeme-editor').addEventListener('close',()=>{if(!$('lexeme-editor').open)clearLexemeEditState();});
$('lexeme-editor').querySelector('.close').onclick=e=>{e.preventDefault();if($('lexeme-editor').dispatchEvent(new Event('cancel',{cancelable:true})))$('lexeme-editor').close();};
window.addEventListener('beforeunload',e=>{if($('lexeme-editor').open&&lexemeDirty){e.preventDefault();e.returnValue='';}});
function pruneNewLexemeRows(body,previous={}){
  // The morphology editor allocates UUIDs before saving. Compare with saved IDs
  // instead of assuming every row with an ID has already been saved.
  const known=field=>new Set((previous?.[field]||[]).map(r=>r.id));
  const blank=(row,fields)=>fields.every(k=>!String(row[k]||'').trim());
  const noTags=row=>(row.tags||[]).every(t=>!String(t.value||'').trim()&&!String(t.note||'').trim());
  const memberships=body.word_structure?.memberships||[],usedUsages=new Set(memberships.map(m=>m.usage_id)),usedVariants=new Set(memberships.flatMap(m=>(m.parts||[]).map(p=>p.variant_id)));
  const usages=known('usages'),senses=new Set((previous?.usages||[]).flatMap(u=>(u.senses||[]).map(s=>s.id)));
  body.usages=(body.usages||[]).map(u=>({...u,senses:(u.senses||[]).filter(s=>senses.has(s.id)||!blank(s,['short_gloss','definition','notes'])||!noTags(s)||s.features?.length)})).filter(u=>usages.has(u.id)||usedUsages.has(u.id)||!blank(u,['pos','subclass','notes'])||!noTags(u)||u.features?.length||u.senses.length);
  const variants=known('variants');body.variants=(body.variants||[]).filter(v=>variants.has(v.id)||usedVariants.has(v.id)||!blank(v,['form','notes','pronunciation','conditions','source'])||!noTags(v)||v.features?.length||v.condition_types?.length);
  const writings=known('orthographies');body.orthographies=(body.orthographies||[]).filter(o=>writings.has(o.id)||!blank(o,['text'])||!o.type_id&&!blank(o,['label']));
  return body;
}
$('lexeme-form').onsubmit=async event=>{
  event.preventDefault();$('save-lexeme').disabled=true;
  try{
    const b={...readMorphEntry(),homonym_number:$('lexeme-number').value?Number($('lexeme-number').value):null,homonym_note:$('lexeme-homonym').value,notes:$('lexeme-notes').value,tags:readTags($('lexeme-tags')),
      orthographies:[...$('lexeme-orthographies').children].map(o=>({id:o.dataset.id,type_id:o.querySelector('.orthography-type')?.value||'',label:o.querySelector('.orthography-label').value,text:o.querySelector('.orthography-text').value,font:o.querySelector('.orthography-font').value})),
      usages:[...$('lexeme-usages').children].map(u=>({id:u.dataset.id,pos:u.querySelector('.usage-pos').value,subclass:u.querySelector('.usage-subclass').value,features:readFeatures(u.querySelector('.usage-features')),notes:u.querySelector('.usage-notes').value,tags:readTags(u.querySelector('.usage-tags')),senses:[...u.querySelector('.sense-editors').children].map(s=>({id:s.dataset.id,features:readFeatures(s.querySelector('.sense-features')),short_gloss:s.querySelector('.sense-short').value,definition:s.querySelector('.sense-definition').value,notes:s.querySelector('.sense-notes').value,tags:readTags(s.querySelector('.sense-tags'))}))})),
      variants:[...$('lexeme-variants').children].map(v=>({...readMorphForm(v),id:v.dataset.id,form:v.querySelector('.variant-form').value,notes:v.querySelector('.variant-notes').value,tags:readTags(v.querySelector('.variant-tags'))}))};
    pruneNewLexemeRows(b,editingLexeme?.body);
    const hp=await api('homonym-preview?'+new URLSearchParams({lexical_language:$('lexeme-language').value,form:$('lexeme-headword').value,exclude:editingLexeme?.id||''}));
    if(hp.peers.length&&(!editingLexeme||editingLexeme.headword!==$('lexeme-headword').value.trim())&&!await corporiumConfirm('此词形与已有词条「'+hp.peers.map(p=>lexemePlainLabel({headword:p.headword,body:{homonym_number:p.number}})).join('、')+'」同形。确认建立独立同形词条？系统会分配互不重复的下标。'))return;
    const mp=await prepareMorphemeSave(b,editingLexeme?.id,$('lexeme-language').value);if(!mp)return;
    const x=await api('lexeme-save',{...mp,homonym_confirmation:hp.token,id:editingLexeme?.id,revision:editingLexeme?.revision,headword:$('lexeme-headword').value,body:b,_language:$('lexeme-language').value});
    lexemeDirty=false;$('lexeme-editor').close();
    if($('word-link-dialog').open){$('link-query').value='';await searchLinkLexemes(x.id);}
    else{dictionarySelection=x.id;await setWorkspace('dictionary');}
  }catch(e){$('lexeme-error').textContent=e.message;}finally{$('save-lexeme').disabled=false;}
};

makeDialog('word-link-dialog','<h2>词典关联</h2><p id="link-context"></p><div class="link-unit-field"><span id="link-unit-label">关联单位</span><select id="link-unit" hidden aria-hidden="true" tabindex="-1"></select><details id="link-unit-picker"><summary aria-labelledby="link-unit-label link-unit-current"><span id="link-unit-current"></span></summary><div id="link-unit-options" role="group" aria-label="选择关联单位"></div></details></div><p id="link-existing"></p><div class="search-row"><input id="link-query" aria-label="查找关联词条" placeholder="查找词形、变体或释义"><button id="link-search">查找</button><button id="link-create">＋ 建立新词条</button></div><p id="link-result-count"></p><label>选择条目<select id="link-lexeme" size="5"></select></label><label>词类用法<select id="link-usage"></select></label><label>义项<select id="link-sense"></select></label><p id="link-suggestion"></p><label>本用例分析备注<textarea id="link-notes" rows="2"></textarea></label><p><small>选定义项后默认跟随词典释义，可在“标注来源”中单独覆盖；解除关联保留当前标注。未指定具体意义时保留手写标注。</small></p><p id="link-error" role="alert"></p><button id="save-link" class="primary">保存关联</button><button id="unlink-unit">解除当前关联</button><button id="view-linked-lexeme">查看词条与例证</button>');
let independentLink=null,linkColorWord=null;
async function openWordLink(entry,word,options={}){
  independentLink=entry.independentLink||null;
  linkColorWord=word;
  const lid=word.language_id||entry.text_language_id||entry.language_id||activeLanguage;
  const opts=[{...word,id:independentLink?'@word':word.unit_id,type:'整词'},...(word.morphemes||[]).filter(m=>independentLink||m.unit_id).map(m=>({...m,id:independentLink?m.key:m.unit_id,type:'语素'}))].map(o=>({...o,label:o.type+' · '+o.form+' — '+o.gloss}));
  $('link-unit-options').innerHTML=opts.map(o=>{const p=CorporiumMorphColors.unit(word,o.type==='整词'?word:o,lid);return `<button type="button" data-link-unit="${esc(o.id)}" style="${languageTypography(JSON.parse(languageList.find(l=>l.id===lid)?.metadata||'{}'))}"><span class="link-unit-kind">${o.type} · </span><span class="link-unit-form">${p.form}</span> — <span class="gloss">${p.gloss}</span></button>`;}).join('');
  $('link-unit-picker').open=false;
  $('link-context').textContent=independentLink?'独立例句 · 第 '+(independentLink.word+1)+' 词':entry.title+' · 第 '+entry.position+' 句';$('link-unit').innerHTML=opts.map(o=>`<option value="${esc(o.id)}">${esc(o.label)}</option>`).join('');
  const selected=options.unitKey==='@word'?opts[0]:opts.find(o=>o.key===options.unitKey);if(selected)$('link-unit').value=selected.id;
  syncLinkUnitPicker();$('link-error').textContent='';$('word-link-dialog').showModal();await loadLinkUnit(options);
}
function syncLinkUnitPicker(){
 const selected=[...$('link-unit-options').querySelectorAll('[data-link-unit]')].find(b=>b.dataset.linkUnit===$('link-unit').value);
 if(selected){$('link-unit-current').innerHTML=selected.innerHTML;$('link-unit-current').setAttribute('style',selected.getAttribute('style'));}
 for(const b of $('link-unit-options').children)b.setAttribute('aria-pressed',String(b===selected));
}
$('link-unit-options').onclick=async event=>{const b=event.target.closest('[data-link-unit]');if(!b)return;$('link-unit').value=b.dataset.linkUnit;$('link-unit-picker').open=false;try{await $('link-unit').onchange();}finally{syncLinkUnitPicker();$('link-unit-picker').querySelector('summary').focus();}};
$('link-unit-picker').addEventListener('keydown',e=>{const buttons=[...$('link-unit-options').children];if(e.key==='Escape'){$('link-unit-picker').open=false;$('link-unit-picker').querySelector('summary').focus();}else if(['ArrowDown','ArrowUp','Home','End'].includes(e.key)){e.preventDefault();$('link-unit-picker').open=true;const i=buttons.indexOf(document.activeElement);buttons[e.key==='Home'?0:e.key==='End'?buttons.length-1:(i+(e.key==='ArrowDown'?1:-1)+buttons.length)%buttons.length]?.focus();}});
document.addEventListener('click',e=>{if(!$('link-unit-picker').contains(e.target))$('link-unit-picker').open=false;});
async function loadLinkUnit(options={}){
  const uid=$('link-unit').value,seq=++linkRequest;$('save-link').disabled=true;
  const u=independentLink?await independentLinkUnit(uid):await api('unit-dictionary?id='+encodeURIComponent(uid));if(seq!==linkRequest)return;
  const d=independentLink?independentLink.data:await api('segmentation?'+new URLSearchParams({kind:'corpus',id:u.entry_id}));if(seq!==linkRequest)return;
  linkColorWord=d.body.words.find(w=>independentLink?w===d.body.words[independentLink.word]:w.unit_id===uid||w.morphemes?.some(m=>m.unit_id===uid))||linkColorWord;
  for(const button of $('link-unit-options').children){const id=button.dataset.linkUnit,unit=independentLink?(id==='@word'?linkColorWord:linkColorWord?.morphemes?.find(m=>m.key===id)):(linkColorWord?.unit_id===id?linkColorWord:linkColorWord?.morphemes?.find(m=>m.unit_id===id));if(!unit)continue;const p=CorporiumMorphColors.unit(linkColorWord,unit,u.effective_language_id);button.querySelector('.link-unit-form').innerHTML=p.form;button.querySelector('.gloss').innerHTML=p.gloss;}syncLinkUnitPicker();
  linkUnit=u;linkLexeme=null;$('link-query').value='';$('link-notes').value=u.link.notes||'';
  const currentUnit=u.kind==='word'?linkColorWord:linkColorWord?.morphemes?.find(m=>independentLink?m.key===uid:m.unit_id===uid);
  const colored=linkColorWord&&currentUnit?CorporiumMorphColors.unit(linkColorWord,currentUnit,u.effective_language_id).gloss:richGloss(u.display_gloss??u.gloss,u.effective_language_id);
  $('link-existing').innerHTML='本句标注：<span class="gloss">'+colored+'</span>'+(u.link.id?' · 已有关联':' · 尚未关联');
  if(u.link.review_reason){const warning=document.createElement('p');warning.className='warning';warning.textContent='待核对：'+u.link.review_reason;$('link-existing').append(warning);}
  for(const relation of u.gloss_relations||[]){const p=document.createElement('span');p.className='morph-evidence';p.textContent='语义与论元关系：'+relation.sides.join(' → ');$('link-existing').append(p);}
  $('unlink-unit').disabled=!u.link.id;await searchLinkLexemes(u.link.lexeme_id,options);
}
async function searchLinkLexemes(preferred,options={}){
  if(!linkUnit)return;const seq=++linkRequest;
  const linkedOnly=!!(options.linkedOnly&&preferred);
  const data=linkedOnly?{items:[await api('lexeme?id='+encodeURIComponent(preferred))],total:1}:await api('lexemes?'+new URLSearchParams({targets:'all',counts:'0',search:JSON.stringify({scope:'entry'}),lexical_language:linkUnit.effective_language_id,q:$('link-query').value}));if(seq!==linkRequest)return;
  if(preferred&&!data.items.some(x=>x.id===preferred))data.items.unshift(await api('lexeme?id='+encodeURIComponent(preferred)));
  if(seq!==linkRequest)return;
  $('link-result-count').textContent=linkedOnly?'当前关联条目；可检索其他词条或语素':data.total+' 个匹配条目'+(data.total>30?'，显示前 30 个，请输入更具体的检索词':'');
  $('link-lexeme').innerHTML=data.items.map(x=>`<option value="${esc(x.id)}">${x.target_kind==='morpheme'?'语素 · ':''}${esc(lexemePlainLabel(x))} · ${esc(dictionaryTargetDescription(x))}${x.body.homonym_note?' · '+esc(x.body.homonym_note):''}</option>`).join('');
  if(preferred)$('link-lexeme').value=preferred;
  else if(data.items.length)$('link-lexeme').value=data.items[0].id;
  await chooseLinkLexeme();
}
async function chooseLinkLexeme(){
  const id=$('link-lexeme').value,seq=++linkRequest;$('save-link').disabled=true;
  const candidate=id?await api('lexeme?id='+encodeURIComponent(id)):null;if(seq!==linkRequest)return;linkLexeme=candidate;
  const morpheme=linkLexeme?.target_kind==='morpheme',usages=linkLexeme?.body.usages||[];
  $('link-usage').parentElement.firstChild.textContent=morpheme?'意义／功能分组':'词类用法';$('link-usage').parentElement.hidden=morpheme&&usages.length<=1;
  $('link-sense').parentElement.firstChild.textContent=morpheme?'意义／功能':'义项';$('view-linked-lexeme').textContent=morpheme?'查看语素与例证':'查看词条与例证';
  $('link-usage').innerHTML='<option value="">'+(morpheme?'全部意义／功能':'词类暂不确定')+'</option>'+usages.map((u,i)=>`<option value="${esc(u.id)}">${i+1}. ${esc(morpheme?'意义／功能组':usageLabel(u))}</option>`).join('');
  if(linkUnit.link.lexeme_id===id)$('link-usage').value=linkUnit.link.usage_id||'';
  if(morpheme&&usages.length===1)$('link-usage').value=usages[0].id;
  chooseLinkUsage();$('save-link').disabled=!linkLexeme||!linkUnit.active;$('view-linked-lexeme').disabled=!linkLexeme;
}
function chooseLinkUsage(){const usage=paradigmUsages(linkLexeme?.body,$('link-form')?.value||'').find(u=>u.id===$('link-usage').value);$('link-sense').innerHTML='<option value="">'+(linkLexeme?.target_kind==='morpheme'?'意义／功能暂不指定':'义项暂不确定')+'</option>'+(usage?.senses||[]).map((s,i)=>`<option value="${esc(s.id)}">${i+1}. ${esc((s.paradigm_label?s.paradigm_label+' — ':'')+(s.short_gloss||s.definition.slice(0,60)||'待补充'))}</option>`).join('');if(linkUnit.link.lexeme_id===linkLexeme?.id&&linkUnit.link.usage_id===usage?.id)$('link-sense').value=linkUnit.link.sense_id||'';showLinkSuggestion();}
function showLinkSuggestion(){const usage=paradigmUsages(linkLexeme?.body,$('link-form')?.value||'').find(u=>u.id===$('link-usage').value),sense=usage?.senses.find(s=>s.id===$('link-sense').value);$('link-suggestion').textContent=sense?(linkLexeme?.target_kind==='morpheme'?'语素简短标注建议：':'词典简短释义建议：')+(sense.short_gloss||'未填写')+'；详细释义：'+sense.definition:(linkLexeme?.target_kind==='morpheme'?'可以先关联语素，意义／功能可暂不指定。':'可以只关联词条，稍后再判断词类与义项。');}
function linkSafe(fn){return async(...args)=>{try{$('link-error').textContent='';await fn(...args);}catch(e){$('link-error').textContent=e.message;}};}
$('link-unit').onchange=linkSafe(loadLinkUnit);$('link-search').onclick=linkSafe(()=>searchLinkLexemes());$('link-query').onkeydown=e=>{if(e.key==='Enter')$('link-search').click();};$('link-lexeme').onchange=linkSafe(chooseLinkLexeme);$('link-usage').onchange=chooseLinkUsage;$('link-sense').onchange=showLinkSuggestion;
$('link-create').onclick=()=>{if(linkUnit)openLexemeEditor(null,linkUnit.form,linkUnit.effective_language_id);};
$('save-link').onclick=linkSafe(async()=>{
  if(!linkLexeme)return;$('save-link').disabled=true;
  try{if(independentLink){await saveIndependentLink();return;}await api('lexeme-link',{unit_id:linkUnit.id,unit_revision:linkUnit.revision,entry_revision:linkUnit.entry_revision,revision:linkUnit.link.revision||0,lexeme_id:linkLexeme.id,lexeme_revision:linkLexeme.revision,usage_id:$('link-usage').value,sense_id:$('link-sense').value,form_id:$('link-form').value,component_selection:readComponentSelection('link-component'),features:readFeatures($('link-features')),notes:$('link-notes').value,_language:linkUnit.language_id});await loadLinkUnit();await search();$('link-error').textContent='关联已保存，本句 gloss 未改变。';}finally{$('save-link').disabled=!linkLexeme;}
});
$('unlink-unit').onclick=linkSafe(async()=>{if(independentLink){await saveIndependentLink(true);return;}const l=linkUnit.link;await api('lexeme-unlink',{id:l.id,revision:l.revision,_language:l.language_id});await loadLinkUnit();await refreshExampleViews();});
$('view-linked-lexeme').onclick=linkSafe(async()=>{const id=linkLexeme.id;$('word-link-dialog').close();dictionarySelection=id;await setWorkspace('dictionary');await showLexeme(id);});
$('results').addEventListener('click',e=>{const button=e.target.closest('[data-unit]');if(!button)return;const entry=items.find(x=>x.words.some(w=>w.unit_id===button.dataset.unit));const word=entry?.words.find(w=>w.unit_id===button.dataset.unit);if(word)linkSafe(()=>openWordLink(entry,word))();});
const lexiconRefreshUndo=refreshUndo;
refreshUndo=async function(){await lexiconRefreshUndo();if(workspace==='dictionary'&&!$('lexeme-editor').open&&!$('morpheme-editor')?.open)await loadDictionary();};
const lexiconSwitchLanguage=switchLanguage;
switchLanguage=async function(lid){const old=activeLanguage;await lexiconSwitchLanguage(lid);if(old!==activeLanguage){dictionarySelection=null;dictionaryPage=1;$('dictionary-detail').innerHTML='<p>选择词条查看释义和例证。</p>';if(workspace==='dictionary')await loadDictionary();}};

async function independentLinkUnit(key){
 const c=independentLink,d=await api('segmentation?'+new URLSearchParams({kind:'independent',id:c.id}));
 c.data=d;const w=d.body.words[c.word];if(!w)throw Error('原词已变化，请重新选择');
 const unit=key==='@word'?w:w.morphemes.find(m=>m.key===key);if(!unit)throw Error('语素已变化，请重新选择');
 const matches=d.body.targets.map((t,i)=>({...t,index:i})).filter(t=>!t.segmentation_ref?.detached&&t.segmentation_ref?.word===c.word&&t.segmentation_ref?.key===key);
 if(matches.length>1)throw Error('此单位有多个旧关联，请先在例句信息中核对');const target=matches[0];
 return {...unit,id:key,kind:key==='@word'?'word':'morpheme',active:true,language_id:d.language_id,effective_language_id:d.language_id,link:target?{...target,id:'target:'+target.index}: {}};
}
async function saveIndependentLink(remove=false){
 const c=independentLink,d=c.data;
 await api('segmentation-link',{kind:'independent',id:c.id,revision:d.revision,word:c.word,key:$('link-unit').value,...(remove?{remove_target:linkUnit.link.index}:{lexeme_id:linkLexeme.id,lexeme_revision:linkLexeme.revision,usage_id:$('link-usage').value,sense_id:$('link-sense').value,form_id:$('link-form').value,component_selection:readComponentSelection('link-component'),features:readFeatures($('link-features')),notes:$('link-notes').value}),_language:d.language_id});
 await loadLinkUnit();if(workspace==='corpus')await search();else await loadLibrary();$('link-error').textContent=remove?'关联已解除。':'关联已保存，本句标注未改变。';
}
document.addEventListener('click',linkSafe(async e=>{const b=e.target.closest('[data-library-word]');if(!b)return;const card=b.closest('.editable-example'),d=await api('segmentation?'+new URLSearchParams({kind:'independent',id:card.dataset.exampleId})),i=Number(b.dataset.libraryWord);await openWordLink({...d.body,title:'独立例句',position:i+1,independentLink:{id:card.dataset.exampleId,word:i}},d.body.words[i]);}));
