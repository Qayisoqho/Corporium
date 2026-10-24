// Explicit dictionary structure; original headwords and corpus segmentation stay independent.
const wsId=()=>crypto.randomUUID();
const wsInput=(key,label,value='',area=false)=>`<label>${esc(label)}${area?`<textarea data-ws="${key}" rows="2">${esc(value)}</textarea>`:`<input data-ws="${key}" value="${esc(value)}">`}</label>`;
const wsVal=(el,key)=>el.querySelector(`[data-ws="${key}"]`).value;
const wsOptions=(rows,value='',empty='尚未指定')=>`<option value="">${esc(empty)}</option>`+rows.map(r=>`<option value="${esc(r.id)}" ${r.id===value?'selected':''}>${esc(r.label||r.name)}</option>`).join('')+(value&&!rows.some(r=>r.id===value)?`<option selected value="${esc(value)}">原引用已不存在，请调整</option>`:'');
function wsMoveButtons(row){
 const tools=document.createElement('div');tools.className='ws-row-tools';tools.innerHTML='<button type="button" data-ws-up>上移</button><button type="button" data-ws-down>下移</button><button type="button" data-ws-remove>移除</button>';row.append(tools);
 tools.onclick=e=>{const b=e.target.closest('button');if(!b)return;const parent=row.parentElement;
 if(b.hasAttribute('data-ws-up')&&row.previousElementSibling)parent.insertBefore(row,row.previousElementSibling);
 if(b.hasAttribute('data-ws-down')&&row.nextElementSibling)parent.insertBefore(row.nextElementSibling,row);
 if(b.hasAttribute('data-ws-remove')){if(row.classList.contains('ws-component'))for(const r of parent.children)if(r.querySelector('.ws-parent').value===row.dataset.id)r.querySelector('.ws-parent').value=row.querySelector('.ws-parent').value;row.remove();}
 if(parent.classList.contains('ws-components'))wsParents(parent);lexemeDirty=true;
 };
}

// Class-level principal-parts template. Editing it never overwrites filled entries.
$('class-notes').parentElement.after(Object.assign(document.createElement('section'),{id:'ws-class-template',innerHTML:'<details open><summary>主要部分模板</summary><label>模块名称<input id="ws-template-title" placeholder="主要部分"></label><p>各项按显示顺序填写；词条通过“添加模板项”复制名称和说明，已有内容不会被覆盖。</p><div id="ws-template-slots"></div><button type="button" id="ws-slot-add">＋ 添加模板项</button></details>'}));
function wsSlot(s={}){const row=document.createElement('div');row.className='ws-template-slot';row.dataset.id=s.id||wsId();row.innerHTML=wsInput('label','项目名称',s.label)+wsInput('notes','说明',s.notes);$('ws-template-slots').append(row);wsMoveButtons(row);}
const wsFillClass=fillClass;fillClass=function(c=null){wsFillClass(c);$('ws-class-template').hidden=$('class-kind').value!=='morph';$('ws-template-title').value=c?.template?.title||'主要部分';$('ws-template-slots').replaceChildren();for(const s of c?.template?.slots||[])wsSlot(s);};
$('ws-slot-add').onclick=()=>wsSlot();
function readClassTemplate(){return {title:$('ws-template-title').value||'主要部分',slots:[...$('ws-template-slots').children].map(r=>({id:r.dataset.id,label:wsVal(r,'label'),notes:wsVal(r,'notes')}))};}

const wsEditor=document.createElement('section');wsEditor.id='word-structure-editor';wsEditor.innerHTML='<h3>形态类与主要部分</h3><div id="ws-memberships"></div><button type="button" id="ws-add-membership">＋ 关联形态类</button> <button type="button" id="ws-manage-classes">管理形态类</button><h3>词条语素分析</h3><p>按组分添加，或建立词干分组后选择上级分组。保存时会整理并关联语素条目；也可另外关联词典词条；实际形式无需拼合成词形。多部分形式在词条或语素的形式栏编辑；旧分析片段保留供核对。</p><div id="ws-analyses"></div><button type="button" id="ws-add-analysis">＋ 添加分析</button><datalist id="ws-role-options">'+['复合词干','词根','词干','派生词缀','屈折词缀','连接成分','中缀','环缀','多部分词根'].map(s=>`<option value="${s}">`).join('')+'</datalist>';
$('morph-entry-editor').after(wsEditor);
const wsUsageAdd=addUsage;addUsage=function(u={}){wsUsageAdd(u);const r=$('lexeme-usages').lastElementChild;if(!r.dataset.id)r.dataset.id=wsId();};
const wsVariantAdd=addVariant;addVariant=function(v={}){wsVariantAdd(v);const r=$('lexeme-variants').lastElementChild;if(!r.dataset.id)r.dataset.id=wsId();};
function wsUsages(){return [...$('lexeme-usages').children].map((r,i)=>({id:r.dataset.id,label:(i+1)+'. '+(r.querySelector('.usage-pos').value||'词类未指定')}));}
function wsVariants(){return [...$('lexeme-variants').children].map(r=>({id:r.dataset.id,label:r.querySelector('.variant-form').value||'未填写形式'}));}
// Rebuild labels by stable identity when local rows change; never select the
// new occupant of a deleted row's former ordinal position.
$('lexeme-usages').addEventListener('input',()=>{for(const select of wsEditor.querySelectorAll('.ws-usage'))select.innerHTML=wsOptions(wsUsages(),select.value,'整个词条');});
wsEditor.addEventListener('focusin',e=>{if(e.target.matches('.ws-variant'))e.target.innerHTML=wsOptions(wsVariants(),e.target.value,'不引用');});
function wsWritings(container,values=[]){
 container.innerHTML='<div class="ws-writing-rows"></div><button type="button" class="ws-add-writing">＋ 添加书写形式</button>';
 const add=(v={})=>{const r=document.createElement('div');r.className='ws-writing';r.innerHTML=`<label>书写类型<select>${wsOptions(writingTypes,v.type_id,'选择词典书写类型')}</select></label><label>书写内容<input value="${esc(v.text||'')}"></label><button type="button">移除</button>`;container.querySelector('.ws-writing-rows').append(r);
 const select=r.querySelector('select'),input=r.querySelector('input');const font=()=>input.style.fontFamily=cssFont(writingTypes.find(t=>t.id===select.value)?.font||'Junicode');font();select.onchange=font;r.querySelector('button').onclick=()=>{r.remove();lexemeDirty=true;};};
 for(const v of values)add(v);container.querySelector('.ws-add-writing').onclick=()=>{add();lexemeDirty=true;};
}
function wsReadWritings(el){return [...el.querySelector('.ws-writing-rows').children].map(r=>({type_id:r.querySelector('select').value,text:r.querySelector('input').value})).filter(w=>w.text.trim());}
function wsPart(container,p={}){
 const r=document.createElement('div');r.className='ws-part ws-box';r.dataset.id=p.id||wsId();r.innerHTML=wsInput('label','项目名称',p.label)+wsInput('form','形式（可直接填写）',p.form)+`<label>引用本词条形式<select class="ws-variant">${wsOptions(wsVariants(),p.variant_id,'不引用')}</select></label><details><summary>书写形式与语法标签</summary><div class="ws-writings"></div><div class="ws-features">${featurePicker(p.features||[])}</div></details>`+wsInput('notes','说明',p.notes,true);container.append(r);wsWritings(r.querySelector('.ws-writings'),p.writings);wsMoveButtons(r);
}
function wsMembership(m={}){
 const r=document.createElement('section');r.className='ws-membership ws-box';r.dataset.id=m.id||wsId();r.innerHTML=`<label>形态类<select class="ws-class">${wsOptions(lexemeClasses.filter(c=>c.kind==='morph'),m.class_id,'选择形态类')}</select></label><label>适用范围<select class="ws-usage">${wsOptions(wsUsages(),m.usage_id,'整个词条')}</select></label><p class="ws-class-notes"></p><details class="ws-parts-panel"><summary>主要部分</summary>${wsInput('title','本词条的模块名称（留空沿用类模板）',m.title)}<div class="ws-parts"></div><button type="button" class="ws-add-part">＋ 添加项目</button> <button type="button" class="ws-apply-template">添加模板项</button></details><details><summary>本词条例外与备注</summary>${wsInput('membership_notes','备注',m.notes,true)}</details>`;
 $('ws-memberships').append(r);for(const p of m.parts||[])wsPart(r.querySelector('.ws-parts'),p);
 const info=()=>{const c=lexemeClasses.find(c=>c.id===r.querySelector('.ws-class').value);r.querySelector('.ws-class-notes').textContent=c?.notes||'';r.querySelector('.ws-parts-panel>summary').textContent=wsVal(r,'title')||c?.template?.title||'主要部分';};info();r.querySelector('.ws-class').onchange=info;r.querySelector('[data-ws="title"]').oninput=info;
 r.querySelector('.ws-add-part').onclick=()=>{wsPart(r.querySelector('.ws-parts'));lexemeDirty=true;};
 r.querySelector('.ws-apply-template').onclick=()=>{const c=lexemeClasses.find(c=>c.id===r.querySelector('.ws-class').value),container=r.querySelector('.ws-parts'),existing=new Set([...container.children].map(p=>wsVal(p,'label')));for(const p of c?.template?.slots||[])if(!existing.has(p.label))wsPart(container,{label:p.label,notes:p.notes});lexemeDirty=true;};wsMoveButtons(r);
}
function wsParents(container){const rows=[...container.children];for(const r of rows){const s=r.querySelector('.ws-parent'),value=s.value;s.innerHTML=wsOptions(rows.filter(p=>p!==r).map((p,i)=>({id:p.dataset.id,label:wsVal(p,'form')||'组分 '+(i+1)})),value,'顶层组分');}}
function wsLinkOptions(row,c={}){
 const select=row.querySelector('.ws-target'),usage=row.querySelector('.ws-target-usage'),sense=row.querySelector('.ws-target-sense'),form=row.querySelector('.ws-target-form');
 const allEntries=lexemeChoiceRows(morphEditorData.entries).filter(e=>e.id!==editingLexeme?.id),query=row.querySelector('.ws-entry-query');query.dataset.lexemeChoiceQuery='';
 const count=document.createElement('small');count.className='lexeme-choice-count';query.after(count);
 query.oninput=()=>fillLexemeChoices(select,allEntries,select.value,query.value,'不关联额外词条',count);
 fillLexemeChoices(select,allEntries,c.lexeme_id||'','','不关联额外词条',count);
 const fillSense=(value='')=>{const b=JSON.parse(morphEditorData.entries.find(e=>e.id===select.value)?.body||'{}'),u=paradigmUsages(b,form.value).find(u=>u.id===usage.value);sense.innerHTML=wsOptions((u?.senses||[]).map((s,i)=>({id:s.id,label:(i+1)+'. '+(s.short_gloss||s.definition)})),value,'未细分义项');};
 const fill=(u='',s='',f='')=>{const b=JSON.parse(morphEditorData.entries.find(e=>e.id===select.value)?.body||'{}');usage.innerHTML=wsOptions((b.usages||[]).map((u,i)=>({id:u.id,label:(i+1)+'. '+(u.pos||'词类未指定')})),u,'未细分词类用法');form.innerHTML=wsOptions((b.variants||[]).map(v=>({id:v.id,label:v.form})),f,'未指定形式');fillSense(s);};
 fill(c.usage_id,c.sense_id,c.form_id);select.onchange=()=>fill();usage.onchange=()=>fillSense();form.onchange=()=>fillSense();
}
function wsComponent(container,c={}){
 const r=document.createElement('section');r.className='ws-component ws-box';r.dataset.id=c.id||wsId();r.dataset.legacySegments=JSON.stringify(c.segments||[]);r.innerHTML=wsInput('form','组分形式',c.form)+`<label>上级分组<select class="ws-parent">${wsOptions([...container.children].map(p=>({id:p.dataset.id,label:wsVal(p,'form')})),c.parent_id,'顶层组分')}</select></label><label>角色<input data-ws="role" list="ws-role-options" value="${esc(c.role||'')}"></label>`+wsInput('readings','读音（每行一个，不自动拆分声韵调）',(c.readings||[]).join('\n'),true)+wsInput('gloss','简短释义',c.gloss)+`<details><summary>组分的书写形式</summary><div class="ws-writings"></div></details><details class="ws-registry-picker" open><summary>关联已有语素</summary><div class="morpheme-actions"><input class="ws-registry-query" placeholder="搜索语素形式或释义" aria-label="搜索关联语素"><button type="button" class="ws-registry-search">搜索</button></div><select class="ws-registry-target" aria-label="关联已有语素"><option value="">保存时自动整理</option><option value="@new">建立独立新语素</option></select></details><details><summary>额外关联词条</summary><input class="ws-entry-query" placeholder="筛选词条" aria-label="筛选关联词条"><label>词条<select class="ws-target"></select></label><label>词类用法<select class="ws-target-usage"></select></label><label>义项<select class="ws-target-sense"></select></label><label>具体形式<select class="ws-target-form"></select></label></details><details><summary>语法特征、依据与备注</summary>${c.segments?.length?'<p class="ws-legacy-parts">已保留旧分析片段：'+esc(c.segments.join(' … '))+'</p>':''}<div class="ws-features">${featurePicker(c.features||[])}</div>${wsInput('component_source','组分研究依据',c.source)}${wsInput('notes','组分备注',c.notes,true)}</details>`;container.append(r);const picker=r.querySelector('.ws-registry-picker'),values=document.createElement('div');values.className='ws-registry-values';values.hidden=true;r.prepend(picker);picker.after(values);wsWritings(r.querySelector('.ws-writings'),c.writings);wsLinkOptions(r,c);wsRegistryPicker(r);wsMoveButtons(r);r.querySelector('[data-ws="form"]').addEventListener('change',()=>wsParents(container));
}
const wsLevels={unspecified:'分析层面未定',synchronic:'共时结构',diachronic:'历时分析'};
function wsAnalysis(a={}){
 const r=document.createElement('section');r.className='ws-analysis ws-box';r.dataset.id=a.id||wsId();r.innerHTML=wsInput('title','分析名称',a.title)+`<div class="metadata-grid"><label>分析层面<select data-ws="level">${morphSelect(wsLevels,a.level||'unspecified')}</select></label></div><label><input type="radio" name="ws-default" class="ws-default" ${a.default?'checked':''}> 默认展示这份分析</label><div class="ws-components"></div><button type="button" class="ws-add-component">＋ 添加组分</button><details><summary>分析依据与备注</summary>${wsInput('source','研究依据',a.source)}${wsInput('analysis_notes','分析备注',a.notes,true)}</details>`;$('ws-analyses').append(r);const list=r.querySelector('.ws-components');for(const c of a.components||[])wsComponent(list,c);wsParents(list);r.querySelector('.ws-add-component').onclick=()=>{wsComponent(list);wsParents(list);lexemeDirty=true;};wsMoveButtons(r);
}
function wsRead(){return pruneNewWordStructure({memberships:[...$('ws-memberships').children].map(r=>({id:r.dataset.id,class_id:r.querySelector('.ws-class').value,usage_id:r.querySelector('.ws-usage').value,title:wsVal(r,'title'),notes:wsVal(r,'membership_notes'),parts:[...r.querySelector('.ws-parts').children].map(p=>({id:p.dataset.id,label:wsVal(p,'label'),form:wsVal(p,'form'),variant_id:p.querySelector('.ws-variant').value,notes:wsVal(p,'notes'),writings:wsReadWritings(p.querySelector('.ws-writings')),features:readFeatures(p.querySelector('.ws-features'))}))})),analyses:[...$('ws-analyses').children].map(r=>({id:r.dataset.id,title:wsVal(r,'title'),level:wsVal(r,'level'),default:r.querySelector('.ws-default').checked,source:wsVal(r,'source'),notes:wsVal(r,'analysis_notes'),components:[...r.querySelector('.ws-components').children].map(c=>({id:c.dataset.id,parent_id:c.querySelector('.ws-parent').value,role:wsVal(c,'role'),form:wsVal(c,'form'),gloss:wsVal(c,'gloss'),readings:wsVal(c,'readings').split('\n').map(s=>s.trim()).filter(Boolean),segments:JSON.parse(c.dataset.legacySegments||'[]'),lexeme_id:c.querySelector('.ws-target').value,usage_id:c.querySelector('.ws-target-usage').value,sense_id:c.querySelector('.ws-target-sense').value,form_id:c.querySelector('.ws-target-form').value,writings:wsReadWritings(c.querySelector('.ws-writings')),features:readFeatures(c.querySelector('.ws-features')),notes:wsVal(c,'notes'),source:wsVal(c,'component_source')}))}))},editingLexeme?.body?.word_structure);}
function wsFill(b={},keepTargets=false){const targets=keepTargets?[...$("ws-analyses").querySelectorAll(".ws-registry-target")].map(el=>({id:el.closest(".ws-component").dataset.id,value:el.value,text:el.selectedOptions[0]?.textContent,changed:el.dataset.changed,record:el.closest(".ws-component").registryRecord,draft:el.closest(".ws-component").registryDraft})):[];$('ws-memberships').replaceChildren();$('ws-analyses').replaceChildren();for(const m of b.memberships||[])wsMembership(m);for(const a of b.analyses||[])wsAnalysis(a);for(const t of targets){const el=[...$("ws-analyses").querySelectorAll(".ws-component")].find(r=>r.dataset.id===t.id)?.querySelector(".ws-registry-target");if(el&&t.value){if(![...el.options].some(o=>o.value===t.value))el.append(new Option(t.text,t.value));el.value=t.value;if(t.changed)el.dataset.changed=t.changed;const row=el.closest('.ws-component');row.registryDraft=t.draft;if(t.record)wsSetRegistryRecord(row,t.record,{fill:false});}}}
const wsOpen=openLexemeEditor;openLexemeEditor=async function(...args){await wsOpen(...args);wsFill(args[0]?.body?.word_structure||{});};
const wsReadMorph=readMorphEntry;readMorphEntry=function(){return {...wsReadMorph(),word_structure:wsRead()};};
$('ws-add-membership').onclick=()=>{wsMembership();lexemeDirty=true;};$('ws-add-analysis').onclick=()=>{wsAnalysis({default:!$('ws-analyses').children.length});lexemeDirty=true;};$('ws-manage-classes').onclick=safe(()=>openClasses($('lexeme-language').value,'morph'));
const wsRefreshClasses=refreshClassConsumers;refreshClassConsumers=async function(){await wsRefreshClasses();if($('lexeme-editor').open&&$('lexeme-language').value===classLanguage){const data=wsRead();wsFill(data,true);}};
$('lexeme-language').addEventListener('change',async()=>{const lid=$('lexeme-language').value;try{const [data,types,classes]=await Promise.all([api('morphology-options?language='+encodeURIComponent(lid)),fetchWritingTypes(lid),api('classes?language='+encodeURIComponent(lid))]);if($('lexeme-language').value!==lid)return;const draft=wsRead();morphEditorData=data;writingTypes=types;lexemeClasses=classes;wsFill(draft);}catch(e){$('lexeme-error').textContent=e.message;}});
wsEditor.addEventListener('focusin',e=>{const s=e.target;if(s.matches('.ws-usage'))s.innerHTML=wsOptions(wsUsages(),s.value,'整个词条');if(s.matches('.ws-variant'))s.innerHTML=wsOptions(wsVariants(),s.value,'不引用');});

function wsWritingsView(rows,data){return (rows||[]).map(w=>{const t=data.writing_types.find(t=>t.id===w.type_id);return `<span class="ws-writing-view"><small>${esc(t?.name||'未找到书写类型')}</small><span style="font-family:${orthographyStyle(t?.font||'Junicode')}">${esc(w.text)}</span></span>`;}).join('');}
function wsStructureView(x,data){
 const b=x.body.word_structure||{},members=b.memberships||[],analyses=b.analyses||[],entry=id=>data.entries.find(e=>e.id===id);
 const link=id=>{const e=entry(id);return e?`<button class="dictionary-wordform" data-morph-entry="${esc(id)}">${esc(lexemePlainLabel({...e,body:JSON.parse(e.body)}))}</button>`:'<span>关联词条不存在</span>';};
 function node(c,all,level=0){
  const target=entry(c.lexeme_id),tb=target?JSON.parse(target.body):{},u=paradigmUsages(tb).find(u=>u.id===c.usage_id),s=u?.senses.find(s=>s.id===c.sense_id),f=tb.variants?.find(v=>v.id===c.form_id);
  return `<li><div class="ws-component-view" data-ws-component-id="${esc(c.id)}"><strong class="dictionary-wordform">${esc(c.form)}</strong>${c.role?` <small>${esc(c.role)}</small>`:''}${c.gloss?' → '+richGloss(c.gloss,x.language_id):''}${c.readings?.length?'<span class="ipa"> /'+esc(c.readings.join(' / '))+'/</span>':''}${featuresView(c.features||[],data.tags)}${c.segments?.length?`<p>同一语素的片段：${c.segments.map(s=>'<span class="dictionary-wordform">'+esc(s)+'</span>').join(' … ')}</p>`:''}<div>${wsWritingsView(c.writings,data)}</div>${c.lexeme_id?`<p>关联：${link(c.lexeme_id)} ${[u?.pos,s?.short_gloss||s?.definition,f?.form].filter(Boolean).map(esc).join(' · ')}</p>`:''}${c.notes||c.source?`<details><summary>组分依据与备注</summary>${c.source?`<p>依据：${esc(c.source)}</p>`:''}<p class="preserve-lines">${esc(c.notes)}</p></details>`:''}</div>${all.some(n=>n.parent_id===c.id)&&level<100?'<ol>'+all.filter(n=>n.parent_id===c.id).map(n=>node(n,all,level+1)).join('')+'</ol>':''}</li>`;
 }
 const reverse=data.entries.flatMap(e=>{const eb=JSON.parse(e.body);return (eb.word_structure?.analyses||[]).filter(a=>a.components.some(c=>c.lexeme_id===x.id)).map(a=>({e,a}));});
 const heading=a=>[a.title,a.level&&a.level!=='unspecified'?wsLevels[a.level]:''].filter(Boolean).map(esc).join(' · ');
 return `<section class="word-structure-view">${analyses.length?'<h3>语素构成</h3>':''}${[...analyses].sort((a,b)=>Number(b.default)-Number(a.default)).map(a=>{const title=heading(a),content=`<ol>${a.components.filter(c=>!c.parent_id).map(c=>node(c,a.components)).join('')}</ol>${a.source||a.notes?`<details><summary>依据与备注</summary>${a.source?`<p>依据：${esc(a.source)}</p>`:''}<p class="preserve-lines">${esc(a.notes)}</p></details>`:''}`;return title?`<details class="ws-analysis-view" ${a.default?'open':''}><summary>${title}</summary>${content}</details>`:`<div class="ws-analysis-view">${content}</div>`;}).join('')}${reverse.length?`<h3>包含本语素的词条</h3><p>词条构成中的关联，与文本出现和独立例句分别统计。</p><ul>${reverse.map(({e,a})=>`<li>${link(e.id)}${heading(a)?' · '+heading(a):''}</li>`).join('')}</ul>`:''}</section>`;
}
const wsMorphView=morphologyView;morphologyView=function(x,data){return wsMorphView(x,data)+wsStructureView(x,data);};

function wsMembershipsView(x,data){const members=x.body.word_structure?.memberships||[];return members.length?`<div class="ws-memberships-inline">${members.map(m=>{const cls=data.classes.find(c=>c.id===m.class_id),u=x.body.usages.find(u=>u.id===m.usage_id),parts=m.parts.filter(p=>p.form?.trim()||x.body.variants.some(v=>v.id===p.variant_id&&v.form?.trim())||p.writings?.some(w=>w.text?.trim())||p.features?.length||(p.notes?.trim()&&!cls?.template?.slots?.some(s=>s.label===p.label&&s.notes?.trim()===p.notes.trim())));return `<article class="ws-membership-view"><strong>${esc(cls?.name||'未找到形态类')}</strong>${u?` <small>适用于：${esc(usageLabel(u))}</small>`:''}${cls?.notes?`<details><summary>类的共同说明</summary><p class="preserve-lines">${esc(cls.notes)}</p></details>`:''}${parts.length?`<details><summary>${esc(m.title||cls?.template?.title||'主要部分')}</summary><dl class="ws-parts-view">${parts.map(p=>{const v=x.body.variants.find(v=>v.id===p.variant_id);return `<div class="ws-principal-part"><dt>${esc(p.label||'未命名项目')}</dt><dd><span class="dictionary-wordform">${esc(p.form||v?.form||'')}</span>${p.form&&v?' · 引用：<span class="dictionary-wordform">'+esc(v.form)+'</span>':''}${featuresView(p.features||[],data.tags)}<div>${wsWritingsView(p.writings,data)}</div>${p.notes?`<p class="preserve-lines">${esc(p.notes)}</p>`:''}</dd></div>`;}).join('')}</dl></details>`:''}${m.notes?`<details><summary>本词条例外与备注</summary><p class="preserve-lines">${esc(m.notes)}</p></details>`:''}</article>`;}).join('')}</div>`:'';}

// Keep the core entry form first; detailed analysis remains available below senses.
const morphologyEditorBlock=document.createElement('details');morphologyEditorBlock.className='dictionary-morphology-block';morphologyEditorBlock.innerHTML='<summary>形态分析、语素构成与条目关系</summary>';$('add-usage').after(morphologyEditorBlock);morphologyEditorBlock.append($('morph-entry-editor'),wsEditor,$('lexeme-variants').parentElement);

function wsRegistryPicker(row){
 const select=row.querySelector('.ws-registry-target');
 const forms=document.createElement('select');forms.className='ws-registry-form';forms.setAttribute('aria-label','关联语素的基本形式或变体');forms.hidden=true;select.after(forms);
 forms.onchange=()=>{select.dataset.changed='true';lexemeDirty=true;wsSetRegistryRecord(row,row.registryRecord,{formId:forms.value});};
 select.onchange=safe(async()=>{const value=select.value;row.registryError=null;row.registryPending=null;if(value){select.dataset.changed='true';lexemeDirty=true;}else delete select.dataset.changed;if(!value||value==='@new'){wsReleaseRegistry(row);return;}const lid=$('lexeme-language').value;row.registryPending=(async()=>{try{const m=await api('morpheme?id='+encodeURIComponent(value));if(!row.isConnected||select.value!==value||$('lexeme-language').value!==lid)return;if(m.language_id!==lid)throw Error('请选择当前语言的语素');wsSetRegistryRecord(row,m,{formId:row.registryRecord?.id===value?select.dataset.formId||'':''});}catch(e){if(select.value!==value)return;row.registryError=e;throw e;}})();await row.registryPending;});
 row.querySelector('.ws-registry-search').onclick=safe(()=>wsSearchRegistry(row));
 row.querySelector('.ws-registry-query').onkeydown=e=>{if(e.key==='Enter'){e.preventDefault();row.querySelector('.ws-registry-search').click();}};
}

function wsRegistryGlosses(m){return [...new Set([m.body?.gloss,...(m.body?.senses||[]).map(s=>s.gloss||s.definition)].filter(s=>typeof s==='string'&&s.trim()))];}
function wsRegistryLabel(m){return [m.form+(m.display_number?' ['+m.display_number+']':''),...(m.body?.writings||[]).map(w=>w.text).filter(s=>s?.trim()),...wsRegistryGlosses(m),...(m.body?.variants?.length?['变体：'+m.body.variants.map(v=>v.form).join('、')]:[])].join(' · ');}
function wsRegistryCandidate(m,value){
 const writings=(m.body?.writings||[]).filter(w=>w.text?.trim()).map(w=>{const t=writingTypes.find(t=>t.id===w.type_id);return `<span class="ws-candidate-writing" title="${esc(t?.name||'书写形式')}" style="font-family:${orthographyStyle(t?.font||'Junicode')}">${esc(w.text)}</span>`;}).join('');
 const glosses=wsRegistryGlosses(m);
 return `<button type="button" data-ws-registry-id="${esc(m.id)}" aria-pressed="${m.id===value}"><strong class="dictionary-wordform">${esc(m.form)}${m.display_number?'<sub>'+esc(m.display_number)+'</sub>':''}</strong>${writings}${glosses.length?'<span class="ws-candidate-gloss">'+esc(glosses.join(' / '))+'</span>':''}${m.body?.variants?.length?'<span class="ws-candidate-variants">变体：'+esc(m.body.variants.map(v=>v.form).join('、'))+'</span>':''}</button>`;
}

async function wsSearchRegistry(row,page=1){
 const sequence=row.registrySearchSequence=(row.registrySearchSequence||0)+1,lid=$('lexeme-language').value,q=row.querySelector('.ws-registry-query').value,button=row.querySelector('.ws-registry-search'),select=row.querySelector('.ws-registry-target');
 button.disabled=true;
 try{
  const result=await api('morphemes?'+new URLSearchParams({q,language:lid,page,page_size:20}));
  if(!row.isConnected||sequence!==row.registrySearchSequence||$('lexeme-language').value!==lid)return;
  const value=select.value,old=[...select.options].find(o=>o.value===value);
  select.innerHTML='<option value="">保存时自动整理</option><option value="@new">建立独立新语素</option>'+result.items.map(m=>`<option value="${esc(m.id)}">${esc(wsRegistryLabel(m))}</option>`).join('');
  if(value&&!result.items.some(m=>m.id===value)&&value!=='@new'&&old)select.append(old);select.value=value;
  let matches=row.querySelector('.ws-registry-results');if(!matches){matches=document.createElement('div');matches.className='ws-registry-results';row.querySelector('.ws-registry-picker').append(matches);}
  matches.hidden=false;matches.innerHTML=`<small role="status">${result.total} 个结果${result.total?' · 点击选择语素':''}</small><div class="ws-registry-candidates">${result.items.map(m=>wsRegistryCandidate(m,value)).join('')||'<small>没有找到语素，可调整关键词或选择建立独立新语素。</small>'}</div>${result.pages>1?`<nav><button type="button" data-ws-registry-page="${result.page-1}" ${result.page===1?'disabled':''}>上一页</button><small>${result.page} / ${result.pages}</small><button type="button" data-ws-registry-page="${result.page+1}" ${result.page===result.pages?'disabled':''}>下一页</button></nav>`:''}`;
  matches.querySelectorAll('[data-ws-registry-id]').forEach(b=>b.onclick=()=>{select.value=b.dataset.wsRegistryId;matches.hidden=true;select.dispatchEvent(new Event('change',{bubbles:true}));});
  matches.querySelectorAll('[data-ws-registry-page]').forEach(b=>b.onclick=safe(()=>wsSearchRegistry(row,Number(b.dataset.wsRegistryPage))));
 }finally{if(sequence===row.registrySearchSequence)button.disabled=false;}
}

function wsRegistryRealization(record,formId=''){
 const variant=(record.body.variants||[]).find(v=>v.id===formId);
 if(formId&&!variant)throw Error('关联的语素变体已不存在，请重新选择');
 return {form:variant?.form||record.form,readings:variant?.pronunciation?[variant.pronunciation]:record.body.readings||[],gloss:record.body.gloss||''};
}
function wsRegistryFormOptions(record){return '<option value="">基本形式 · '+esc(record.form)+'</option>'+(record.body.variants||[]).map((v,i)=>'<option value="'+esc(v.id)+'">变体 '+(i+1)+' · '+esc(v.form)+(v.conditions?' · '+esc(v.conditions):'')+'</option>').join('');}
function wsSetRegistryRecord(row,record,{fill=true,formId=''}={}){
 const keys=['form','readings','gloss'],select=row.querySelector('.ws-registry-target');
 if(!row.registryDraft)row.registryDraft={...Object.fromEntries(keys.map(k=>[k,wsVal(row,k)])),writings:wsReadWritings(row.querySelector('.ws-writings'))};
 if(fill)wsWritings(row.querySelector('.ws-writings'),record.body.writings||[]);
 row.registryRecord=record;row.registryError=null;
 const values=wsRegistryRealization(record,formId),forms=row.querySelector('.ws-registry-form');forms.innerHTML=wsRegistryFormOptions(record);forms.value=formId;forms.hidden=!(record.body.variants||[]).length;forms.title=forms.selectedOptions[0]?.textContent||'';select.dataset.formId=formId;
 if(![...select.options].some(o=>o.value===record.id))select.append(new Option(wsRegistryLabel(record),record.id));select.value=record.id;
 for(const key of keys){const input=row.querySelector('[data-ws="'+key+'"]');if(fill)input.value=key==='readings'?values.readings.join('\n'):values[key];input.closest('label').hidden=true;}
 const view=row.querySelector('.ws-registry-values');view.hidden=false;view.innerHTML='<strong class="dictionary-wordform">'+esc(values.form)+'</strong>'+(values.readings.length?'<span class="ipa">/'+esc(values.readings.join(' / '))+'/</span>':'')+'<span class="gloss">'+richGloss(values.gloss,record.language_id)+'</span>'+wsWritingsView(fill?(record.body.writings||[]):wsReadWritings(row.querySelector('.ws-writings')).length?wsReadWritings(row.querySelector('.ws-writings')):(record.body.writings||[]),{writing_types:writingTypes});
 wsParents(row.parentElement);
}
function wsReleaseRegistry(row){
 const draft=row.registryDraft;for(const key of ['form','readings','gloss']){const input=row.querySelector('[data-ws="'+key+'"]');if(draft)input.value=draft[key];input.closest('label').hidden=false;}
 if(draft)wsWritings(row.querySelector('.ws-writings'),draft.writings||[]);
 row.registryRecord=null;row.registryDraft=null;row.querySelector('.ws-registry-values').hidden=true;wsParents(row.parentElement);
 row.querySelector('.ws-registry-form').hidden=true;delete row.querySelector('.ws-registry-target').dataset.formId;
}

// Only unsaved, entirely empty placeholders are omitted; referenced rows stay explicit.
function pruneNewWordStructure(value,previous={}){
 previous=previous||{};const known=key=>new Set((previous[key]||[]).map(r=>r.id));
 const payload=v=>v&&typeof v==='object'?Object.entries(v).some(([k,x])=>!['id','default'].includes(k)&&!(k==='level'&&x==='unspecified')&&(typeof x==='string'?!!x.trim():Array.isArray(x)?x.some(payload):payload(x))):typeof v==='string'?!!v.trim():!!v;
 const memberships=known('memberships'),analyses=known('analyses'),components=new Set((previous.analyses||[]).flatMap(a=>(a.components||[]).map(c=>c.id)));
 value.memberships=(value.memberships||[]).filter(m=>memberships.has(m.id)||payload(m));
 value.analyses=(value.analyses||[]).map(a=>{const parents=new Set(a.components.map(c=>c.parent_id).filter(Boolean));return {...a,components:a.components.filter(c=>components.has(c.id)||parents.has(c.id)||payload(c))};}).filter(a=>analyses.has(a.id)||payload(a));
 return value;
}
