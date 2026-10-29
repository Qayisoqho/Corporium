// Serialized app dialogs: async answers never fall through as truthy Promises.
let corporiumDialogQueue=Promise.resolve();
function corporiumDialog(message,kind='alert',initial=''){
 const run=()=>new Promise(resolve=>{
  const previous=document.activeElement,dialog=document.createElement('dialog');
  dialog.className='corporium-message';dialog.setAttribute('aria-labelledby','corporium-message-title');dialog.setAttribute('aria-describedby','corporium-message-body');
  const title=document.createElement('h2');title.id='corporium-message-title';title.textContent=kind==='confirm'?(globalThis.CorporiumI18n?.f("421d8c651d3cee",()=>[])??'请确认'):kind==='prompt'?(globalThis.CorporiumI18n?.f("72b8562b1637ad",()=>[])??'请输入'):(globalThis.CorporiumI18n?.f("3ca9a2ba418411",()=>[])??'提示');
  const body=document.createElement('div');body.id='corporium-message-body';body.textContent=String(message);
  const actions=document.createElement('div');actions.className='corporium-message-actions';
  const input=kind==='prompt'?document.createElement('input'):null;
  dialog.append(title,body);if(input){input.value=initial;input.setAttribute('aria-label',String(message));dialog.append(input);}
  const finish=value=>{dialog.close();dialog.remove();if(previous?.isConnected)previous.focus({preventScroll:true});resolve(value);};
  if(kind!=='alert'){const cancel=document.createElement('button');cancel.textContent=(globalThis.CorporiumI18n?.f("6a4a6ec9ee6233",()=>[])??'取消');cancel.onclick=()=>finish(kind==='prompt'?null:false);actions.append(cancel);}
  const ok=document.createElement('button');ok.className='primary';ok.textContent=kind==='alert'?(globalThis.CorporiumI18n?.f("776c43d3f82f70",()=>[])??'知道了'):(globalThis.CorporiumI18n?.f("3e665d9169de9e",()=>[])??'确定');ok.onclick=()=>finish(input?input.value:true);actions.append(ok);dialog.append(actions);
  dialog.addEventListener('cancel',e=>{e.preventDefault();finish(kind==='prompt'?null:false);});
  input?.addEventListener('keydown',e=>{if(e.key==='Enter'&&!e.isComposing){e.preventDefault();ok.click();}});
  document.body.append(dialog);dialog.showModal();(input||actions.firstChild).focus();input?.select();
 });
 const result=corporiumDialogQueue.then(run);corporiumDialogQueue=result.catch(()=>{});return result;
}
const corporiumConfirm=message=>corporiumDialog(message,'confirm');
const corporiumAlert=message=>corporiumDialog(message);
const corporiumPrompt=(message,initial='')=>corporiumDialog(message,'prompt',initial);
let corporiumStatusText='',corporiumStatusOwner=null;
function corporiumStatus(message,owner=null){corporiumStatusText=String(message);corporiumStatusOwner=owner;document.getElementById('notice').textContent=corporiumStatusText;}
function clearCorporiumStatus(owner){
 if(corporiumStatusOwner!==owner)return;
 for(const id of ['notice','dictionary-notice']){const el=document.getElementById(id);if(el?.textContent===corporiumStatusText)el.textContent='';}
 corporiumStatusText='';corporiumStatusOwner=null;
}
function guardDialogDiscard(event,dirty,message){
 if(!dirty)return;event.preventDefault();const dialog=event.target.closest('dialog');
 if(!dialog||dialog.dataset.discardPending)return;dialog.dataset.discardPending='true';
 corporiumConfirm(message).then(yes=>{if(yes&&dialog.open)dialog.close();}).finally(()=>delete dialog.dataset.discardPending);
}
// Existing action-error outlets share one presentation, including dynamically built editors.
const messageOutlet='[role="alert"],[id$="-error"],.inline-error,#notice,#dictionary-notice,#grammar-notice';
new MutationObserver(records=>{
 const outlets=new Set();for(const record of records){const node=record.target.nodeType===1?record.target:record.target.parentElement;const parent=node?.closest(messageOutlet);if(parent)outlets.add(parent);for(const child of record.addedNodes||[]){if(child.nodeType===1){if(child.matches(messageOutlet))outlets.add(child);child.querySelectorAll(messageOutlet).forEach(el=>outlets.add(el));}}}
 const messages=new Set();for(const el of outlets){if(el.closest('[data-inline-message]'))continue;const text=el.textContent.trim();if(text&&(el.id==='notice'||el.id==='dictionary-notice')&&text===corporiumStatusText)continue;if(text&&!el.closest('.corporium-message')){messages.add(text);el.textContent='';}}
 for(const message of messages)void corporiumAlert(message);
}).observe(document.body,{subtree:true,childList:true,characterData:true});
const $=id=>document.getElementById(id);
let activeLanguage='ordos',languageList=[];
let texts=[], selected='', page=1, total=0, items=[], current=null, request=0;
const pageSize=()=>Number($('page-size').value);
const esc=s=>String(s??'').replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
function rich(s){return esc(s).replace(/#sub\[([^\[\]]*)\]/g,'<sub>$1</sub>').replace(/\\([~?\[\]#])/g,'$1')}
async function api(path,body){const scopedPath=path+(path.includes('?')?'&':'?')+'language='+encodeURIComponent(activeLanguage);if(body)body={_language:activeLanguage,...body};const r=await fetch('/api/'+(body?path:scopedPath),body?{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(body)}:{});const d=await r.json();if(!r.ok)throw Error(d.error||(globalThis.CorporiumI18n?.f("d258ea4a87d0d6",()=>[])??'操作失败'));return d}
function safe(fn){return async(...args)=>{try{await fn(...args)}catch(e){if(e.name==='AbortError')return;$('notice').textContent=e.message}}}
function renderWord(w,lid,hit=false){
 const boundary=phonologicalBoundary(w.form);
 if(w.punctuation&&w.punctuation_form===w.form)return `<div class="word punctuation-unit"><span class="form">${rich(w.form)}</span></div>`;
 const pair=window.CorporiumMorphColors?.pair(w,lid)||{form:rich(w.form),gloss:richGloss(w.gloss,lid)};
 const linked=Boolean(w.dictionary_linked||w.linked_lexeme||w.morph_colors?.length&&w.morph_colors.every(m=>m.linked));
 const formClass='form '+(linked?'is-linked':'');
 const evidence=Number.isInteger(w.dictionary_evidence)&&w.dictionary_evidence>0?w.dictionary_evidence:null;
 return `<div class="word ${boundary?'phonological-boundary':''} ${pair.columns?'interlinear-word':''} ${hit?'hit':''} ${w.code_mark?'code-marked':''} ${evidence?'dictionary-evidence':''}" ${pair.columns?`style="--morph-columns:${pair.columns};--word-columns:${pair.columns+(w.code_mark?.end?1:0)}"`:""} ${evidence?(globalThis.CorporiumI18n?.f("136e51df2dc036",()=>[evidence,evidence])??`data-dictionary-evidence="${evidence}" title="本条目关联：第 ${evidence} 个词格"`):''} data-code-unit="${esc(w.code_unit||w.unit_id||w.annotation_id||'')}">${w.unit_id&&!boundary?(globalThis.CorporiumI18n?.f("d5a1a1a43e2df2",()=>[formClass,esc(w.unit_id),pair.form])??`<button type="button" class="${formClass} word-dictionary" data-unit="${esc(w.unit_id)}" title="查看或关联词典">${pair.form}</button>`):`<span class="${formClass}" ${boundary?`title="${esc(boundaryName(w.form,lid))}"`:''}>${pair.form}</span>`}<span class="gloss">${window.CorporiumCodes?.gloss(w,boundary?boundaryGloss(w,lid):pair.gloss)??(boundary?boundaryGloss(w,lid):pair.gloss)}</span>${renderExtraLayers(w)}</div>`;
}
// Dictionary cards share the ordinary word layout; evidence only marks bound slots.
function renderDictionaryExample(body,kind,id,links){
 const slots=new Set();
 for(const link of links){
  const ref=link.segmentation_ref;
  const index=kind==='corpus'?(link.active&&!link.needs_review?link.word_position:null):(!link.segmentation_review&&ref&&!ref.detached?ref.word:null);
  if(Number.isInteger(index)&&index>=0&&index<body.words.length)slots.add(index);
 }
 const marked={...body,words:body.words.map((word,index)=>({...word,...(slots.has(index)?{dictionary_evidence:index+1}:{})}))};
 const sentenceOnly=kind==='independent'&&!slots.size&&links.some(link=>!link.segmentation_ref);
 return renderEditableExample(marked,kind,id)+(sentenceOnly?(globalThis.CorporiumI18n?.f("14bed5feb12b55",()=>[])??'<small class="dictionary-evidence-hint">句级引用，未指定关联词格。</small>'):'');
}
function renderBody(e){const lid=e.language_id||e.text_language_id||current?.text_language_id||activeLanguage;return `<div class="ipa">${rich(e.ipa)}${window.CorporiumCodes?.overview(e)||''}</div>${renderSentenceLayers(e,"ipa")}<div class="words">${e.words.map((w,i)=>renderWord(w,lid,(e.hits||[]).includes(i))).join('')}</div><div class="translation">${rich(e.translation)}</div>${renderSentenceLayers(e,"translation")}${e.annotation_review_count?(globalThis.CorporiumI18n?.f("35370ae31f275d",()=>[e.annotation_review_count])??`<p class="warning">${e.annotation_review_count} 项附加标注待核对，请打开“附加标注”处理。</p>`):''}`}

function textNavigationRow(t){return (globalThis.CorporiumI18n?.f("c0ddaf4334ec2f",()=>[selected===t.id?'active':'',esc(t.id),esc(t.title),t.count,esc(t.title),esc(t.title),t.count])??`<button class="nav ${selected===t.id?'active':''}" data-text="${esc(t.id)}" aria-label="${esc(t.title)}，${t.count}句"><span class="text-title-mask" title="${esc(t.title)}"><span class="text-title">${esc(t.title)}</span></span><span class="text-sentence-count" aria-hidden="true">${t.count}</span></button>`);}
async function loadTexts(){texts=await api('texts');$('texts').innerHTML=texts.map(textNavigationRow).join('');$('all').classList.toggle('active',!selected);document.querySelectorAll('[data-text]').forEach(b=>b.onclick=safe(()=>selectText(b.dataset.text)));}
async function selectText(id,{preservePage=false}={}){const same=id===selected;selected=id;if(!preservePage||!same)page=1;const t=texts.find(t=>t.id===id);$('title').textContent=t?.title||(globalThis.CorporiumI18n?.f("51ac0ac57ac136",()=>[])??'全部文本');$('subtitle').textContent=t?.source||(globalThis.CorporiumI18n?.f("01304441e84a6c",()=>[])??'语料文本和行间语法标注');for(const id of ['export','original','add'])$(id).hidden=!selected;$('notice').textContent=t&&JSON.parse(t.errors).length?(globalThis.CorporiumI18n?.f("badd25066d28da",()=>[JSON.parse(t.errors).length,JSON.parse(t.errors).map(e=>(globalThis.CorporiumI18n?.f("ac48064a2c5b90",()=>[e.line,e.message])??`第 ${e.line} 行：${e.message}`)).join('\n')])??`导入时有 ${JSON.parse(t.errors).length} 处无法解析，请下载原始文件核查：\n`+JSON.parse(t.errors).map(e=>`第 ${e.line} 行：${e.message}`).join('\n')):'';await loadTexts();await search()}
function corpusEntryCard(e){return e.kind==='independent'?(globalThis.CorporiumI18n?.f("60187f0c5cfa42",()=>[e.id,renderEditableExample(e,'independent',e.id)])??`<article class="entry" id="entry-${e.id}"><div class="entry-head"><span>独立例句库</span><div></div></div>${renderEditableExample(e,'independent',e.id)}</article>`):(globalThis.CorporiumI18n?.f("02f8fa07a27636",()=>[e.id,e.position,esc(e.title),String(e.position).padStart(3,'0'),e.id,e.id,e.id,renderEditableExample(e,e.kind||'corpus',e.id),e.warnings.length?(globalThis.CorporiumI18n?.f("2aa10a916a5972",()=>[e.warnings.length,e.warnings.map(w=>'<div>'+esc(w)+'</div>').join('')])??`<details class="warning"><summary>${e.warnings.length} 项待核查</summary>${e.warnings.map(w=>'<div>'+esc(w)+'</div>').join('')}</details>`):''])??`<article class="entry" id="entry-${e.id}"><div class="sentence-number" aria-label="文本内句序">(${e.position})</div><div class="entry-head"><span>${esc(e.title)} / ${String(e.position).padStart(3,'0')}</span><div><button data-copy-sentence="${e.id}" title="复制完整句子并插入指定位置">复制句子</button><button data-context="${e.id}">前后文</button><button data-edit="${e.id}">编辑信息</button></div></div>${renderEditableExample(e,e.kind||'corpus',e.id)}${e.warnings.length?`<details class="warning"><summary>${e.warnings.length} 项待核查</summary>${e.warnings.map(w=>'<div>'+esc(w)+'</div>').join('')}</details>`:''}</article>`);}
async function search(){const seq=++request;const q=new URLSearchParams({text:selected,page,q:$('query').value,field:$('field').value,mode:$('mode').value,page_size:pageSize(),case:$('case').checked,warnings:$('warnings').checked,include_independent:!selected,...(window.CorporiumCodes?.params('corpus')||{})});const data=await api('entries?'+q);if(seq!==request)return;items=data.items;total=data.total;page=data.page;$('counts').textContent=(globalThis.CorporiumI18n?.f("803038dda99e1f",()=>[total,$('query').value?(globalThis.CorporiumI18n?.f("dfc685d4a77fc4",()=>[])??'命中语料'):(globalThis.CorporiumI18n?.f("dbb310ab4b9461",()=>[])??'语料'),$('query').value?(globalThis.CorporiumI18n?.f("829f69e4386da3",()=>[data.tokens])??' · '+data.tokens+' 个命中词次'):''])??`${total} 条${$('query').value?'命中语料':'语料'}${$('query').value?' · '+data.tokens+' 个命中词次':''}`);if($('corpus-code-summary'))$('corpus-code-summary').textContent=window.CorporiumCodes?.stats(data.code_summary)||'';$('results').innerHTML=items.map(corpusEntryCard).join('')||(globalThis.CorporiumI18n?.f("26ae125368a3c8",()=>[])??'<div class="empty">没有匹配的语料。试试其他层次或取消完全匹配。</div>');$('page').textContent=`${page} / ${Math.max(1,Math.ceil(total/pageSize()))}`;$('prev').disabled=page===1;$('next').disabled=page*pageSize()>=total;document.querySelectorAll('[data-edit]').forEach(b=>b.onclick=safe(()=>edit(items.find(e=>e.id===b.dataset.edit))));document.querySelectorAll('[data-context]').forEach(b=>b.onclick=safe(async()=>{const e=items.find(e=>e.id===b.dataset.context);clearFilters();await selectText(e.text_id);page=Math.ceil(e.position/pageSize());await search();$('entry-'+e.id)?.scrollIntoView({block:'center',behavior:'smooth'})}))}
function clearFilters(){$('field').value='all';$('query').value='';$('mode').value='contains';for(const id of ['case','warnings'])$(id).checked=false}
function readEditor(){const words=$('pairs').value.split('\n').filter(l=>l.trim()).map((line,i)=>{const parts=line.split('\t');if(parts.length!==2)throw Error((globalThis.CorporiumI18n?.f("c133593e6d8e2d",()=>[i+1])??`第 ${i+1} 行需要一个 Tab 分隔词形和 gloss`));const old=current.words[i];return {form:parts[0],gloss:parts[1],form_kind:old?.form_kind||'content',gloss_kind:old?.gloss_kind||'content'}});return {ipa:$('ipa').value,translation:$('translation').value,notes:$('notes').value,words}}
function preview(){try{$('preview').innerHTML=renderBody(readEditor());$('edit-error').textContent=''}catch(e){$('edit-error').textContent=e.message}}
async function edit(entry){current=entry;$('edit-title').textContent=entry.title+' · '+entry.position;$('ipa').value=entry.ipa;$('translation').value=entry.translation;$('pairs').value=entry.words.map(w=>w.form+'\t'+w.gloss).join('\n');$('notes').value=entry.notes||'';$('raw').textContent=entry.raw;$('history').textContent=(globalThis.CorporiumI18n?.f("1bd08d6e363dda",()=>[])??'加载历史…');preview();$('editor').showModal();const history=await api('history?id='+entry.id);$('history').innerHTML=history.map((h,i)=>(globalThis.CorporiumI18n?.f("3612c478ab7980",()=>[h.revision,esc(new Date(h.created).toLocaleString()),i])??`<div class="history-item">版本 ${h.revision} · ${esc(new Date(h.created).toLocaleString())} <button data-restore="${i}">载入此版本</button></div>`)).join('')||(globalThis.CorporiumI18n?.f("2723a32c4836e7",()=>[])??'<p>尚无修改历史。</p>');document.querySelectorAll('[data-restore]').forEach(b=>b.onclick=()=>{const h=history[Number(b.dataset.restore)].body;$('ipa').value=h.ipa;$('translation').value=h.translation;$('pairs').value=h.words.map(w=>w.form+'\t'+w.gloss).join('\n');$('notes').value=h.notes||'';current={...current,words:h.words};$('entry-language').value=h.language_id||'';$('entry-language-notes').value=h.language_notes||'';preview()})}
function download(name,data,type){const a=document.createElement('a');const url=URL.createObjectURL(new Blob([data],{type}));a.href=url;a.download=name;a.click();setTimeout(()=>URL.revokeObjectURL(url),1000)}
$('all').onclick=safe(()=>selectText(''));$('search').onclick=safe(async()=>{page=1;await search()});$('query').onkeydown=e=>{if(e.key==='Enter')$('search').click()};$('clear').onclick=safe(async()=>{clearFilters();page=1;await search()});for(const id of ['field','mode','case','warnings','page-size'])$(id).onchange=$('search').onclick;
$('prev').onclick=safe(async()=>{page--;await search();window.scrollTo(0,0)});$('next').onclick=safe(async()=>{page++;await search();window.scrollTo(0,0)});
for(const id of ['ipa','translation','pairs'])$(id).oninput=preview;
$('pairs').onkeydown=e=>{if(e.key==='Tab'&&!e.shiftKey){e.preventDefault();const t=e.target;t.setRangeText('\t',t.selectionStart,t.selectionEnd,'end');preview()}};
$('save').onclick=async()=>{const source={kind:'corpus',id:current.id};const run=async()=>{try{$('save').disabled=true;const saved=await api('save',{id:current.id,revision:current.revision,gloss_revision:current.gloss_revision,...readEditor()});$('editor').close();await search();await window.corporiumSentenceInspector?.afterExampleSave?.(source);corporiumStatus((globalThis.CorporiumI18n?.f("89474f686e6541",()=>[])??'已保存；修改前的版本已存入历史。'));if(saved.dictionary_review_count)$('notice').textContent+=(globalThis.CorporiumI18n?.f("5a5cda46d758ec",()=>[saved.dictionary_review_count])??' '+saved.dictionary_review_count+' 条词典关联需要核对：原词或语素已改变，请在词典例证中处理。');}catch(e){$('edit-error').textContent=e.message}finally{$('save').disabled=false}};return window.corporiumPreserveExampleLocation?window.corporiumPreserveExampleLocation(source,run):run();};
function entryEditorDirty(){try{const d=readEditor();return ['ipa','translation','notes','language_id','language_notes'].some(k=>(d[k]||'')!==(current[k]||''))||JSON.stringify(d.words)!==JSON.stringify(current.words.map(({form,gloss,form_kind,gloss_kind})=>({form,gloss,form_kind:form_kind||'content',gloss_kind:gloss_kind||'content'})));}catch{return true;}}
$('editor').addEventListener('cancel',e=>guardDialogDiscard(e,entryEditorDirty(),(globalThis.CorporiumI18n?.f("cf2f76fce49d47",()=>[])??'放弃尚未保存的修改？')));
$('editor').querySelector('.close').onclick=e=>{e.preventDefault();$('editor').dispatchEvent(new Event('cancel',{cancelable:true}))&&$('editor').close()};
$('import').onclick=()=>{$('import-dialog').showModal()};$('file').onchange=async()=>{const f=$('file').files[0];if(!f)return;$('import-content').value=await f.text();$('import-title').value=f.name.replace(/\.typ$/i,'');$('source').value=f.name};
$('import-submit').onclick=async()=>{try{$('import-submit').disabled=true;const title=$('import-title').value.trim();if(!title)throw Error((globalThis.CorporiumI18n?.f("2f030c84085298",()=>[])??'请填写文本标题'));const r=await api('import',{title,source:$('source').value,content:$('import-content').value});$('import-dialog').close();await loadTexts();clearFilters();await selectText(r.id);if(r.duplicate)$('notice').textContent=(globalThis.CorporiumI18n?.f("2e9cd2dfbd02df",()=>[])??'这份源文件已经导入，已打开已有文本。')}catch(e){$('import-error').textContent=e.message}finally{$('import-submit').disabled=false}};
$('new').onclick=safe(async()=>{const title=await corporiumPrompt((globalThis.CorporiumI18n?.f("cbb106bbbb4915",()=>[])??'新文本标题'));if(!title?.trim())return;const r=await api('new-text',{title:title.trim()});await loadTexts();clearFilters();await selectText(r.id);await edit(items[0])});
$('add').onclick=safe(async()=>{const r=await api('add',{text_id:selected});clearFilters();page=Math.ceil(r.position/pageSize());await loadTexts();await search();await edit(items.find(e=>e.position===r.position))});
for(const id of ['export','original'])$(id).onclick=safe(async()=>{const r=await fetch('/api/export?id='+selected+(id==='original'?'&original=true':''));if(!r.ok)throw Error((globalThis.CorporiumI18n?.f("86f43ddfc20ac9",()=>[])??'导出失败'));download(texts.find(t=>t.id===selected).title+(id==='original'?'.original':'')+'.typ',await r.text(),'text/plain;charset=utf-8')});
$('backup').onclick=safe(async()=>download('ordos-backup-'+new Date().toISOString().slice(0,10)+'.json',JSON.stringify(await api('backup'),null,2),'application/json'));


function topPagination(container,currentPage,pages,onPage){
  container.className='pagination top-pagination';
  container.innerHTML=(globalThis.CorporiumI18n?.f("8461984fd9b2e6",()=>[currentPage<=1?'disabled':'',currentPage,pages,currentPage>=pages?'disabled':'',pages,currentPage])??`<button type="button" class="top-prev" ${currentPage<=1?'disabled':''}>上一页</button><span>${currentPage} / ${pages}</span><button type="button" class="top-next" ${currentPage>=pages?'disabled':''}>下一页</button><label>跳至 <input type="number" min="1" max="${pages}" step="1" value="${currentPage}" aria-label="跳转页码"> 页</label><button type="button" class="top-jump">跳转</button>`);
  const run=async target=>{container.querySelectorAll('button').forEach(b=>b.disabled=true);try{await onPage(target);}catch(e){$('notice').textContent=e.message;topPagination(container,currentPage,pages,onPage);}};
  container.querySelector('.top-prev').onclick=()=>run(currentPage-1);
  container.querySelector('.top-next').onclick=()=>run(currentPage+1);
  const jump=()=>{const input=container.querySelector('input');if(!input.value||!input.reportValidity())return;run(Number(input.value));};
  container.querySelector('.top-jump').onclick=jump;
  container.querySelector('input').onkeydown=e=>{if(e.key==='Enter'){e.preventDefault();jump();}};
}
const corpusTop=document.createElement('nav');corpusTop.id='corpus-top-pagination';corpusTop.setAttribute('aria-label',(globalThis.CorporiumI18n?.f("a7d3ab94f89c02",()=>[])??'语料上方分页'));$('results').before(corpusTop);
const paginationSearch=search;
search=async function(){await paginationSearch();corpusTop.hidden=pageSize()<20;topPagination(corpusTop,page,Math.max(1,Math.ceil(total/pageSize())),async target=>{page=target;await search();});};

function renderExtraLayers(w){return (w.extra_layers||[]).filter(l=>l.visible).map(l=>`<span class="extra-layer" style="${layerStyle(l)}"><small>${esc(l.name)}</small>${esc(l.value)||'&nbsp;'}</span>`).join('');}

function layerStyle(l){return `font-family:${esc(JSON.stringify(validFont(l.font)?l.font:'Junicode'))};--layer-scale:${(l.size||100)/100};font-size:calc(.9375rem * var(--layer-scale));font-style:${['italic','bolditalic'].includes(l.style)?'italic':'normal'};font-weight:${['bold','bolditalic'].includes(l.style)?700:400};font-variant-caps:${l.style==='small-caps'?'small-caps':'normal'}`;}
function renderSentenceLayers(e,anchor){return (e.sentence_layers||[]).filter(l=>l.anchor===anchor&&l.visible&&l.value).map(l=>`<div class="sentence-layer" style="${layerStyle(l)}"><small>${esc(l.name)}</small><div>${esc(l.value)}</div></div>`).join('');}
