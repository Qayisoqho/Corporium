function withoutManualStatus(v){if(Array.isArray(v))return v.map(withoutManualStatus);if(!v||typeof v!=='object')return v;return Object.fromEntries(Object.entries(v).filter(([k])=>k!=='status').map(([k,x])=>[k,k==='notes'&&typeof x==='string'?x.replace(/(?:\n)?旧记录标记：有争议。/g,'').trim():withoutManualStatus(x)]));}
// Morphological records are hypotheses separate from the original interlinear text.
const morphEntryTypes={unspecified:'尚未分类',lexeme:'词条',root:'词根',affix:'词缀',clitic:'附着成分',infix:'中缀',circumfix:'环缀',connector:'连接成分',multipart:'其他多部分语素',stem:'词干',expression:'固定表达'};
const morphemeEntryTypes={unspecified:'尚未分类',root:'词根',stem:'词干',affix:'词缀',clitic:'附着成分',connector:'连接成分',multipart:'其他多部分语素'};
const morphemeFunctions={unspecified:'未指定',inflection:'屈折',derivation:'派生',both:'屈折与派生'};
const morphemePositions={unspecified:'未指定',prefix:'前缀',suffix:'后缀',infix:'中缀',circumfix:'环缀'};
const morphFormTypes={base:'基本形式',allomorph:'语素变体',inflected:'屈折形式',derived:'派生形式',stem:'词干形式',spelling:'书写变体',pronunciation:'读音变体',other:'其他形式'};
const morphVariations={unknown:'关系尚未确定',free:'自由变体',conditioned:'条件变体',na:'不适用'};
const morphConditions={phonological:'音系条件',morphological:'形态条件',syntactic:'句法条件',lexical:'特定词项条件'};
const morphRelations={stem:'词干形式',inflection:'屈折形式',derivation:'派生关系',allomorph:'语素变体'};
const morphSelect=(values,value)=>Object.entries(values).map(([id,label])=>`<option value="${esc(id)}" ${id===value?'selected':''}>${esc(label)}</option>`).join('');
let morphEditorData={tags:[],entries:[]},morphLinkTags=[],morphStandaloneTags=[],morphLinkRequest=0;
let exampleForm='all',exampleFormOwner=null;
function featurePicker(values=[],tags=morphEditorData.tags){
 const known=new Set(tags.map(t=>t.id));
 return '<div class="morph-features">'+tags.map(t=>`<label><input type="checkbox" value="${esc(t.id)}" ${values.includes(t.id)?'checked':''}> ${grammarLabel(t.symbol)} <small>${esc(t.description)}</small></label>`).join('')+values.filter(id=>!known.has(id)).map(id=>`<label><input type="checkbox" value="${esc(id)}" checked> 标签已不存在或不属于当前语言，请移除</label>`).join('')+(!tags.length?'<small>暂无标签，请先在“标签与检查”中登记。</small>':'')+'</div>';
}
const readFeatures=el=>[...el.querySelectorAll('.morph-features input:checked')].map(c=>c.value);
function featuresView(ids=[],tags=[]){return ids.map(id=>{const t=tags.find(t=>t.id===id);return grammarLabel(t?.symbol||'未找到标签');}).join(' · ');}
function morphFormLabel(v){return v.form+' · '+(morphFormTypes[v.kind]||v.kind||'其他形式')+' · '+(morphVariations[v.variation]||'关系尚未确定');}
function formOptions(forms=[],value=''){return '<option value="">已关联词条，未细分形式</option>'+forms.map(v=>`<option value="${esc(v.id)}" ${v.id===value?'selected':''}>${esc(morphFormLabel(v))}</option>`).join('');}

$('lexeme-headword').closest('.metadata-grid').insertAdjacentHTML('afterend','<section id="morph-entry-editor"><h3>形态身份与关系</h3><label>条目类型<select id="morph-entry-type">'+morphSelect(morphEntryTypes,'unspecified')+'</select></label><details><summary>条目固有语法特征</summary><p><small>仅填写整个条目固有的属性。特定词类用法、形式和用例的特征分别登记。</small></p><div id="morph-entry-features"></div></details><label>所属基本条目<input id="morph-base-query" type="search" data-lexeme-choice-query placeholder="输入词形筛选基本条目" aria-label="筛选基本条目" hidden><select id="morph-base" aria-label="所属基本条目"></select><small id="morph-base-count" class="lexeme-choice-count" hidden></small></label><label>与基本条目的关系<select id="morph-relation">'+morphSelect(morphRelations,'stem')+'</select></label><p><small>可将带语法信息的形式单独立为词条，同时关联到基本条目；没有此关系时留空。</small></p></section>');
$('lexeme-variants').parentElement.querySelector('summary').textContent='形式、变体与语法特征';$('add-variant').textContent='＋ 添加形式';
$('lexeme-variants').before(Object.assign(document.createElement('p'),{textContent:'条件目前用于记录和人工判断，不自动套用。地域、语体和代际信息使用下方的使用标签；原有变体保留为“关系尚未确定”。'}));
// Keep the searchable catalog in memory, mounting only a bounded set of options.
// A current selection is retained even when it lies outside the first page/query.
const lexemeChoiceIndexes=new WeakMap();
function lexemeChoiceRows(entries){
 if(!lexemeChoiceIndexes.has(entries))lexemeChoiceIndexes.set(entries,entries.map(x=>({id:x.id,label:lexemePlainLabel({...x,body:typeof x.body==='string'?JSON.parse(x.body):x.body})})).map(x=>({...x,search:x.label.toLowerCase()})));
 return lexemeChoiceIndexes.get(entries);
}
function boundedLexemeChoices(rows,value='',query='',limit=50,page=1){
 const q=query.trim().toLowerCase(),matches=rows.filter(r=>!q||(r.search||r.label.toLowerCase()).includes(q)),pages=Math.max(1,Math.ceil(matches.length/limit));page=Math.max(1,Math.min(pages,page));
 const items=matches.slice((page-1)*limit,page*limit),selected=rows.find(r=>r.id===value);
 if(selected&&!items.includes(selected))items.unshift(selected);
 return {items,total:matches.length,limit,page,pages};
}
function fillLexemeChoices(select,rows,value,query,placeholder,status,page=1){
 const result=boundedLexemeChoices(rows,value,query,50,page),previous=select.selectedOptions[0];
 select.innerHTML='<option value="">'+esc(placeholder)+'</option>'+result.items.map(r=>'<option value="'+esc(r.id)+'">'+esc(r.label)+'</option>').join('');
 if(value&&!result.items.some(r=>r.id===value))select.add(new Option(previous?.value===value?previous.textContent:'原引用不属于当前语言，请调整',value));
 select.value=value;
 if(status){status.hidden=rows.length<=result.limit;status.title='每批显示50项；可输入词形筛选，当前已选项始终保留。';status.innerHTML='<span>匹配 '+result.total+' 项'+(result.pages>1?' · '+result.page+' / '+result.pages:'')+(value?' · 已选保留':'')+'</span>'+(result.pages>1?'<button type="button" data-choice-page="'+(result.page-1)+'" aria-label="上一批关联候选" '+(result.page===1?'disabled':'')+'>‹</button><button type="button" data-choice-page="'+(result.page+1)+'" aria-label="下一批关联候选" '+(result.page===result.pages?'disabled':'')+'>›</button>':'');if(result.pages>1)for(const b of status.querySelectorAll('[data-choice-page]'))b.onclick=()=>fillLexemeChoices(select,rows,select.value,query,placeholder,status,Number(b.dataset.choicePage));}
}
function fillMorphEntry(b={}){
 const type=$('morph-entry-type');type.dataset.legacy=b.entry_type==='morpheme'?'morpheme':'';type.value=b.entry_type==='morpheme'?'unspecified':b.entry_type||'unspecified';type.onchange=()=>{type.dataset.legacy='';};$('morph-entry-features').innerHTML=featurePicker(b.features||[]);
 const base=b.relation?.base_id||'',entries=lexemeChoiceRows(morphEditorData.entries).filter(x=>x.id!==editingLexeme?.id),query=$('morph-base-query');
 query.value='';query.hidden=entries.length<=50;
 const render=()=>fillLexemeChoices($('morph-base'),entries,$('morph-base').value,query.value,'暂不指定',$('morph-base-count'));
 query.oninput=render;fillLexemeChoices($('morph-base'),entries,base,'','暂不指定',$('morph-base-count'));
 $('morph-base').value=base;$('morph-relation').value=b.relation?.type||'stem';$('morph-relation').disabled=!base;
}
$('morph-base').onchange=()=>{$('morph-relation').disabled=!$('morph-base').value;};
function readMorphEntry(){return {entry_type:$('morph-entry-type').dataset.legacy||$('morph-entry-type').value,features:readFeatures($('morph-entry-features')),relation:$('morph-base').value?{base_id:$('morph-base').value,type:$('morph-relation').value}:null};}
function variantIPAFont(orthographies=[],lid=activeLanguage){
 const ipa=orthographies.find(o=>/ipa|音标/i.test(o.label||''));
 const m=JSON.parse(languageList.find(l=>l.id===lid)?.metadata||'{}');
 return orthographyFont(ipa?.font||m.ipa_font||'IPAPANNEW');
}
function refreshVariantIPA(){
 const rows=[...$('lexeme-orthographies').children].map(row=>({label:row.querySelector('.orthography-label').value,font:row.querySelector('.orthography-font').value}));
 const font=variantIPAFont(rows,$('lexeme-language').value);
 for(const input of $('lexeme-variants').querySelectorAll('.morph-pronunciation'))input.style.fontFamily=['serif','sans-serif'].includes(font)?font:`"${font}", serif`;
}
for(const event of ['input','change','click'])$('lexeme-form').addEventListener(event,()=>queueMicrotask(refreshVariantIPA));
const morphOpenLexeme=openLexemeEditor;
openLexemeEditor=async function(x=null,form='',lid=activeLanguage){try{const owner=x?.language_id||(lid==='all'?'ordos':lid);morphEditorData=await api('morphology-options?language='+encodeURIComponent(owner));await morphOpenLexeme(x,form,lid);fillMorphEntry(x?.body||{});refreshVariantIPA();}catch(e){$('notice').textContent=e.message;}};
$('lexeme-language').addEventListener('change',async()=>{
 const lid=$('lexeme-language').value;try{const data=await api('morphology-options?language='+encodeURIComponent(lid));if($('lexeme-language').value!==lid)return;const b=readMorphEntry();morphEditorData=data;fillMorphEntry(b);for(const el of document.querySelectorAll('#lexeme-form .morph-feature-editor'))el.innerHTML=featurePicker(readFeatures(el));}catch(e){$('lexeme-error').textContent=e.message;}
});
const morphAddUsage=addUsage;
addUsage=function(u={}){morphAddUsage(u);$('lexeme-usages').lastElementChild.querySelector('.usage-tags').closest('details').insertAdjacentHTML('afterend','<details><summary>此词类用法固有语法特征</summary><div class="usage-features morph-feature-editor">'+featurePicker(u.features||[])+'</div></details>');};
const morphAddVariant=addVariant;
addVariant=function(v={}){
 if(!v.kind)v={...v,kind:v.id?'other':'allomorph'};
 morphAddVariant(v);const row=$('lexeme-variants').lastElementChild;
 row.querySelector('.variant-form').parentElement.firstChild.textContent='形式';
 row.insertAdjacentHTML('afterbegin',`<div class="metadata-grid"><label>形式类型<select class="morph-kind">${classOptions(lexemeClasses.filter(c=>c.kind==='form'),morphFormTypes[v.kind]||v.kind||'语素变体','请选择形式类型')}</select></label><label>变体关系<select class="morph-variation">${morphSelect(morphVariations,v.variation||'unknown')}</select></label></div>`);
 row.querySelector('.variant-notes').parentElement.insertAdjacentHTML('beforebegin',`<label>读音（IPA）<input class="morph-pronunciation" value="${esc(v.pronunciation||'')}"></label><details ${v.features?.length?'open':''}><summary>本形式表达的语法特征</summary><div class="form-features morph-feature-editor">${featurePicker(v.features||[])}</div></details><div class="morph-condition-types">${Object.entries(morphConditions).map(([id,label])=>`<label><input type="checkbox" value="${id}" ${(v.condition_types||[]).includes(id)?'checked':''}> ${label}</label>`).join('')}</div><label>分布条件（可选）<textarea class="morph-conditions" rows="2" placeholder="如：元音后；某类词干后；尚未发现限制">${esc(v.conditions||'')}</textarea></label><label>研究依据<input class="morph-source" value="${esc(v.source||'')}"></label>`);
 row.querySelector('.remove-variant').textContent='移除此形式';refreshVariantIPA();
};
function readMorphForm(row){return {kind:row.querySelector('.morph-kind').value,variation:row.querySelector('.morph-variation').value,pronunciation:row.querySelector('.morph-pronunciation').value,conditions:row.querySelector('.morph-conditions').value,source:row.querySelector('.morph-source').value,condition_types:[...row.querySelectorAll('.morph-condition-types input:checked')].map(e=>e.value),features:readFeatures(row.querySelector('.form-features'))};}
function morphologyView(x,data){
 const b={...x.body,variants:x.body.variants.map(v=>({...v,kind:v.kind||'other'}))},base=data.entries.find(e=>e.id===b.relation?.base_id),children=data.entries.filter(e=>JSON.parse(e.body).relation?.base_id===x.id);
 if(briefMode&&!b.features?.length&&!base&&!children.length&&!b.variants.length)return '';
 return `<section class="morphology-view">${b.features?.length?'<p>条目固有特征：'+featuresView(b.features,data.tags)+'</p>':''}${base?`<p>属于 <button data-morph-entry="${esc(base.id)}">${esc(lexemePlainLabel({...base,body:JSON.parse(base.body)}))}</button> 的${esc(morphRelations[b.relation.type])}</p>`:''}${children.length?'<p>关联条目：'+children.map(e=>`<button data-morph-entry="${esc(e.id)}">${esc(lexemePlainLabel({...e,body:JSON.parse(e.body)}))}</button>`).join(' ')+'</p>':''}<h3 class="${b.variants.length?'':'brief-empty'}">形式、变体与语法特征</h3>${b.variants.map(v=>`<article class="morph-form-view"><strong>${esc(v.form)}</strong> ${featuresView(v.features,data.tags)}<p>${[morphFormTypes[v.kind]||v.kind||'语素变体',(!briefMode||v.variation&&v.variation!=='unknown')?morphVariations[v.variation]||'关系尚未确定':''].filter(Boolean).map(esc).join(' · ')}</p>${v.pronunciation?'<p>读音：<span class="variant-ipa" style="font-family:'+orthographyStyle(variantIPAFont(x.body.orthographies,x.language_id))+'">'+esc(v.pronunciation)+'</span></p>':''}${v.conditions?'<p class="preserve-lines">出现条件（'+(v.condition_types||[]).map(t=>esc(morphConditions[t])).join('、')+'）：'+esc(v.conditions)+'</p>':''}${showTags(v.tags)}<p class="preserve-lines">${esc(v.notes)}</p>${v.source?'<p>依据：'+esc(v.source)+'</p>':''}<button data-morph-form="${esc(v.id)}">查看此形式例证</button></article>`).join('')||'<p class="brief-empty">尚未登记具体形式，可在编辑词条中添加。</p>'}</section>`;
}
function morphEvidence(e,b,tags){const evidence=componentEvidence(e.component_ref,b);const form=b.variants.find(v=>v.id===e.form_id);return `${evidence}<span class="morph-evidence" ${!form&&!e.segmentation_ref&&!e.features?.length?'hidden':''}>${e.segmentation_ref?'语素：'+esc(e.segmentation_ref.unit_form)+' → '+richGloss(e.segmentation_ref.unit_gloss)+(e.segmentation_review?'（待核对）':'')+' · ':''}${form?'具体形式：'+esc(form.form):''}${form?.features?.length?' · 形式特征：'+featuresView(form.features,tags):''}${e.features?.length?' · 本用例特征：'+featuresView(e.features,tags):''}</span>`;}
function wireMorphView(x){
 $('dictionary-detail').querySelectorAll('[data-morph-entry]').forEach(b=>b.onclick=dictSafe(()=>showLexeme(b.dataset.morphEntry)));
 $('dictionary-detail').querySelectorAll('[data-morph-form]').forEach(b=>b.onclick=dictSafe(async()=>{exampleForm=b.dataset.morphForm;await showLexeme(x.id);$('dictionary-example-controls').scrollIntoView({block:'start'});}));
 $('dictionary-example-controls').insertAdjacentHTML('beforeend','<label>形式范围（适用于两种来源） <select id="example-form"><option value="all">全部形式及未指定关联</option><option value="unassigned">尚未指定形式</option>'+x.body.variants.map(v=>`<option value="${esc(v.id)}">${esc(morphFormLabel(v))}</option>`).join('')+'</select></label>');
 $('example-form').value=exampleForm;$('example-form').onchange=dictSafe(async()=>{exampleForm=$('example-form').value;await showLexeme(x.id);});
}

$('link-usage').parentElement.insertAdjacentHTML('beforebegin','<label>选择具体形式<select id="link-form"></select></label><p id="link-form-description" class="preserve-lines"></p><details><summary>本用例的语法特征</summary><div id="link-features"></div><button type="button" id="link-feature-suggest">从本句标注提取标签候选</button><p><small>点号只分隔标注成分，不据此切分语素。候选来自本语言标签库，采用后请核对。</small></p></details>');
const morphChooseLink=chooseLinkLexeme;
chooseLinkLexeme=async function(){const ticket=++morphLinkRequest;await morphChooseLink();if(ticket!==morphLinkRequest)return;const x=linkLexeme,u=linkUnit;if(!x){$('link-form').innerHTML=formOptions();$('link-features').innerHTML='';$('link-form-description').textContent='';return;}
 $('save-link').disabled=true;
 const data={tags:await api('grammar-tags?language='+encodeURIComponent(x.language_id))};if(ticket!==morphLinkRequest||linkLexeme!==x||linkUnit!==u)return;morphLinkTags=data.tags;
 const old=u.link.lexeme_id===x.id?u.link:{};$('link-form').innerHTML=formOptions(x.body.variants,old.form_id);if(x.target_kind==='morpheme')$('link-form').options[0].textContent='已关联语素，未细分形式';$('link-features').innerHTML=featurePicker(old.features||[],data.tags);showMorphLinkForm();
 $('save-link').disabled=!u.active||u.unit_type==='phonological_boundary';
};
// The original handler stored a function reference; update it to the extended chooser.
$('link-lexeme').onchange=linkSafe(chooseLinkLexeme);
function showMorphLinkForm(){const v=linkLexeme?.body.variants.find(v=>v.id===$('link-form').value);$('link-form-description').innerHTML=v?`${esc(morphFormLabel(v))}<br>${featuresView(v.features,morphLinkTags)}<br>${esc(v.conditions||'未填写出现条件')}<br>${esc(v.notes||'')}`:'';}
$('link-form').onchange=showMorphLinkForm;
$('link-feature-suggest').onclick=()=>{for(const input of $('link-features').querySelectorAll('input'))if(linkUnit?.suggested_features?.includes(input.value))input.checked=true;$('link-error').textContent='已勾选本句标注中可识别的标签候选，请核对后保存。';};

const morphOpenStandalone=openStandalone;
openStandalone=async function(x,e=null){morphStandaloneTags=await api('grammar-tags?language='+encodeURIComponent(x.language_id));await morphOpenStandalone(x,e);};
const morphAddTarget=addExampleTarget;
addExampleTarget=function(t={}){morphAddTarget(t);const row=$('standalone-targets').lastElementChild;
 row.insertAdjacentHTML('beforeend','<label>选择具体形式<select class="target-form"></select></label><details><summary>此例句关联的语法特征</summary><div class="target-features">'+featurePicker(t.features||[],morphStandaloneTags)+'</div></details>');
 const x=row.querySelector('.target-lexeme'),f=row.querySelector('.target-form');const fill=()=>{f.innerHTML=formOptions(exampleLexemes.find(e=>e.id===x.value)?.body.variants||[]);};fill();f.value=t.form_id||'';x.addEventListener('change',()=>{fill();row.querySelector('.target-features').innerHTML=featurePicker([],morphStandaloneTags);});
};

// Component references are scoped to their owning lexeme and analysis, never matched by spelling.
function componentSnapshot(body,ref){const a=body?.word_structure?.analyses?.find(a=>a.id===ref.analysis_id),c=a?.components.find(c=>c.id===ref.component_id);if(!c)return null;return {analysis:Object.fromEntries(Object.entries(a).filter(([k])=>k!=='components')),component:c};}
function componentStable(v){if(Array.isArray(v))return v.map(componentStable);if(v&&typeof v==='object')return Object.fromEntries(Object.keys(v).sort().map(k=>[k,componentStable(v[k])]));return v;}
function componentComparable(s){if(!s)return null;s=withoutManualStatus(s);const a=s.analysis||{},c=s.component||{};return {analysis:{title:'',notes:'',source:'',level:'unspecified',...a,default:true},component:{parent_id:'',role:'',form:'',gloss:'',lexeme_id:'',usage_id:'',sense_id:'',form_id:'',notes:'',source:'',writings:[],features:[],segments:[],...Object.fromEntries(Object.entries(c).filter(([k,v])=>!['number','homonym_number'].includes(k)&&!(k==='readings'&&!v?.length)))}};}
function componentNeedsReview(body,ref){return !!ref&&JSON.stringify(componentStable(componentComparable(componentSnapshot(body,ref))))!==JSON.stringify(componentStable(componentComparable(ref.snapshot)));}
function componentEvidence(ref,body){if(!ref)return '';const a=ref.snapshot?.analysis||{},c=ref.snapshot?.component||{};return `<span class="morph-evidence ${componentNeedsReview(body,ref)?'warning':''}">分析组分：${esc(a.title||'未命名分析')}  ·  <span class="segment-form">${esc(c.form||c.segments?.join('…')||'未填形式')}</span> — ${richGloss(c.gloss||'')} ${componentNeedsReview(body,ref)?'（组分已修改或删除，待核对）':''}${ref.notes?'<span class="preserve-lines">'+esc(ref.notes)+'</span>':''}</span>`;}
function componentPicker(id,x,old={}){const ref=old.component_ref,stale=componentNeedsReview(x?.body,ref),value=ref?JSON.stringify([ref.analysis_id,ref.component_id]):'';return `<label>对应条目形态分析中的组分<select id="${id}"><option value="">不指定具体组分（仅关联条目）</option>${stale?'<option value="@keep" selected>保留旧组分关联 · 待核对</option>':''}${(x?.body.word_structure?.analyses||[]).map((a,i)=>`<optgroup label="${esc((a.title||'分析 '+(i+1))+' · '+({synchronic:'共时',diachronic:'历时',unspecified:'层面未定'}[a.level]||a.level))}">${a.components.map(c=>{let path=[],p=c,seen=new Set();while(p&&!seen.has(p.id)){seen.add(p.id);path.unshift(p.form||p.segments?.join('…')||p.role||'未填形式');p=a.components.find(v=>v.id===p.parent_id);}const v=JSON.stringify([a.id,c.id]);return `<option value="${esc(v)}" ${!stale&&v===value?'selected':''}>${esc(path.join(' / '))} — ${esc(c.gloss||'未填标注')}${c.role?' · '+esc(c.role):''}</option>`;}).join('')}</optgroup>`).join('')}</select></label>${componentEvidence(ref,x?.body)}<small>按分析与组分身份关联；修改或删除组分后保留旧记录，重新选择并保存可确认当前分析。</small>`;}
function readComponentSelection(id){const value=$(id)?.value;if(value==='@keep')return undefined;if(!value)return null;const [analysis_id,component_id]=JSON.parse(value);return {analysis_id,component_id};}
const componentChooseLink=chooseLinkLexeme;
$('link-form').parentElement.insertAdjacentHTML('beforebegin','<div id="link-component-fields"></div>');
chooseLinkLexeme=async function(){await componentChooseLink();const x=linkLexeme,u=linkUnit;$('link-component-fields').innerHTML=u?.kind==='morpheme'&&(x?.target_kind!=='morpheme'||x.body.word_structure?.analyses?.length)?componentPicker('link-component',x,u?.link.lexeme_id===x?.id?u.link:{}):'';};
$('link-lexeme').onchange=linkSafe(chooseLinkLexeme);

const nativeComponentPicker=componentPicker;
componentPicker=function(id,x,old={}){
 const holder=document.createElement('div');holder.innerHTML=nativeComponentPicker(id,x,old);const select=holder.querySelector('select');select.hidden=true;
 const options=[...select.options].map(o=>{let text=esc(o.textContent);if(o.value&&o.value!=='@keep'){const [aid,cid]=JSON.parse(o.value),a=x.body.word_structure.analyses.find(a=>a.id===aid),c=a.components.find(c=>c.id===cid);const path=[],seen=new Set();let parent=c;while(parent&&!seen.has(parent.id)){seen.add(parent.id);path.unshift(parent.form||parent.segments?.join('…')||parent.role||'未填形式');parent=a.components.find(v=>v.id===parent.parent_id);}text='<small>'+esc(a.title||'形态分析')+'</small> · <span class="component-form">'+esc(path.join(' / '))+'</span> — <span class="gloss">'+richGloss(c.gloss||'未填标注',x.language_id)+'</span>'; }return {value:o.value,html:text};});
 const picker=document.createElement('details');picker.className='component-picker';picker.setAttribute('style',languageTypographyCSS(JSON.parse(languageList.find(l=>l.id===x?.language_id)?.metadata||'{}')));picker.innerHTML='<summary>'+options.find(o=>o.value===select.value).html+'</summary><div>'+options.map(o=>'<button type="button" data-component-select="'+esc(id)+'" data-component-value="'+esc(o.value)+'">'+o.html+'</button>').join('')+'</div>';select.after(picker);return holder.innerHTML;
};
document.addEventListener('click',e=>{const button=e.target.closest('[data-component-select]');if(!button)return;const select=$(button.dataset.componentSelect);select.value=button.dataset.componentValue;select.dispatchEvent(new Event('change',{bubbles:true}));const picker=button.closest('.component-picker');picker.querySelector('summary').innerHTML=button.innerHTML;picker.open=false;picker.querySelector('summary').focus();});
document.addEventListener('keydown',e=>{if(e.key==='Escape'){const picker=e.target.closest('.component-picker');if(picker){picker.open=false;picker.querySelector('summary').focus();e.stopPropagation();}}});
