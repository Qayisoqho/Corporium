let focusStandaloneExample=()=>{},standaloneCommit=null,standaloneSourceSnapshot=null;
const standaloneSourceFields=['original','ipa','translation','source','notes','grammaticality','words'];
function standaloneSourceValues(){
  return standaloneSourceFields.map(key=>$('standalone-'+key)?.value||'');
}
let writingTypes=[],writingLanguage='ordos',editingType=null,standaloneEditing=null,standaloneLexeme=null,exampleLexemes=[],standaloneDirty=false,exampleSource='all';
const typeButton=document.createElement('button');typeButton.textContent=(globalThis.CorporiumI18n?.f("12ab064eb058af",()=>[])??'书写类型管理');typeButton.id='writing-manager-open';workspaceTabs.append(typeButton);
makeDialog('writing-manager',(globalThis.CorporiumI18n?.f("76d6716f0a3ac2",()=>[])??'<h2>书写形式管理</h2><p>按语言统一名称、字体和显示顺序。词条引用类型后，修改这里会同步影响所有引用。</p><label>语言<select id="writing-language"></select></label><div id="writing-list"></div><h3>待归类的旧书写形式</h3><div id="writing-legacy"></div><button id="writing-new">＋ 新建类型</button><form id="writing-form"><label>名称<input id="writing-name" required></label><label>统一字体<select id="writing-font"></select></label><label>显示顺序（较小的在前）<input id="writing-position" type="number" min="0" max="10000" value="0" required></label><label><input id="writing-adopt" type="checkbox"> 将本语言所有同名、未归类的书写形式转入此类型，统一采用所选字体</label><button type="submit" class="primary">保存类型</button></form><p id="writing-error" role="alert"></p>'));
function writingSafe(fn){return ()=>runSettingsEditorAction('writing-manager',async()=>{try{$('writing-error').textContent='';await fn();}catch(e){$('writing-error').textContent=e.message;}});}
async function fetchWritingTypes(lid){return (await api('writing-types?'+new URLSearchParams({lexical_language:lid,catalog_only:'1'}))).items;}
CorporiumLineSpacing.mount('writing',$('writing-form'));
function editWritingType(t=null){CorporiumLineSpacing.fill('writing',t);editingType=t;$('writing-name').value=t?.name||'';$('writing-font').innerHTML=fontChoices();selectFont($('writing-font'),t?.font||'Junicode');$('writing-position').value=t?.position||0;$('writing-adopt').checked=false;window.CorporiumManagement?.clean('writing-manager');}
async function loadWritingManager(){
  writingLanguage=$('writing-language').value;const data=await api('writing-types?'+new URLSearchParams({lexical_language:writingLanguage}));CorporiumLineSpacing.update('writing',data.items);
  $('writing-list').innerHTML=data.items.map((t,i)=>(globalThis.CorporiumI18n?.f("e2e99195ec75ab",()=>[esc(t.name),esc(availableFonts[t.font]||t.font),t.position,i,i,data.items.filter(x=>x.id!==t.id).map(x=>`<option value="${esc(x.id)}">${esc(x.name)}</option>`).join(''),i])??`<div class="writing-row"><strong>${esc(t.name)}</strong> · ${esc(availableFonts[t.font]||t.font)} · 顺序 ${t.position} <button data-type-edit="${i}">编辑</button><label>删除时转移到<select data-type-replace="${i}"><option value="">不转移（仅未被引用时可删除）</option>${data.items.filter(x=>x.id!==t.id).map(x=>`<option value="${esc(x.id)}">${esc(x.name)}</option>`).join('')}</select></label><button data-type-delete="${i}">删除类型</button></div>`)).join('')||(globalThis.CorporiumI18n?.f("7e13ee780e6fd3",()=>[])??'<p>尚无书写类型。</p>');
  $('writing-legacy').innerHTML=data.legacy.map((t,i)=>(globalThis.CorporiumI18n?.f("4eee8c1913697c",()=>[esc(t.name),t.count,t.fonts.map(f=>esc(availableFonts[f]||f)).join('、'),i])??`<p>${esc(t.name)} · ${t.count} 处 · 字体：${t.fonts.map(f=>esc(availableFonts[f]||f)).join('、')} <button data-adopt="${i}">选择统一字体并归类</button></p>`)).join('')||(globalThis.CorporiumI18n?.f("517d9b61e1a4a5",()=>[])??'<p>没有待归类内容。</p>');
  $('writing-list').querySelectorAll('[data-type-edit]').forEach(b=>b.onclick=()=>editWritingType(data.items[+b.dataset.typeEdit]));
  $('writing-list').querySelectorAll('[data-type-delete]').forEach(b=>b.onclick=writingSafe(async()=>{const t=data.items[+b.dataset.typeDelete];if(!await corporiumConfirm((globalThis.CorporiumI18n?.f("a0a33f3e5602ec",()=>[t.name])??'确认删除书写类型「'+t.name+'」？引用将转移到所选类型，可撤销。')))return;await api('writing-delete',{id:t.id,revision:t.revision,replacement_id:$('writing-list').querySelector(`[data-type-replace="${b.dataset.typeDelete}"]`).value,confirmed:true,_language:writingLanguage});await loadWritingManager();editWritingType();}));
  $('writing-legacy').querySelectorAll('[data-adopt]').forEach(b=>b.onclick=()=>{const t=data.legacy[+b.dataset.adopt],existing=data.items.find(x=>x.name===t.name);editWritingType(existing||{name:t.name,font:t.fonts[0]});$('writing-adopt').checked=true;});
}
async function openWritingManager(lid){
  $('writing-language').innerHTML=languageOptions();
  $('writing-language').value=lid;
  await loadWritingManager();
  editWritingType();
  showSettingsEditor('writing-manager');
}
$('writing-language').onchange=writingSafe(async()=>{await loadWritingManager();editWritingType();});$('writing-new').onclick=()=>editWritingType();
$('writing-form').onsubmit=async e=>{e.preventDefault();await writingSafe(async()=>{await api('writing-save',{...CorporiumLineSpacing.read('writing'),id:editingType?.id,revision:editingType?.revision,name:$('writing-name').value,font:$('writing-font').value,position:Number($('writing-position').value),adopt:$('writing-adopt').checked,_language:writingLanguage});await loadWritingManager();editWritingType();$('writing-error').textContent=(globalThis.CorporiumI18n?.f("47c51ddec34bd6",()=>[])??'已保存，引用此类型的词条统一更新。');})()};

const originalAddOrthography=addOrthography;
addOrthography=function(o={}){
  originalAddOrthography(o);const row=$('lexeme-orthographies').lastElementChild;
  const label=document.createElement('label');label.textContent=(globalThis.CorporiumI18n?.f("d7d771e7566769",()=>[])??'书写类型');const select=document.createElement('select');select.className='orthography-type';
  select.innerHTML=(globalThis.CorporiumI18n?.f("4b192614581caa",()=>[writingTypes.map(t=>`<option value="${esc(t.id)}">${esc(t.name)}</option>`).join('')])??'<option value="">未归类（保留单独设置）</option>'+writingTypes.map(t=>`<option value="${esc(t.id)}">${esc(t.name)}</option>`).join(''));label.append(select);row.prepend(label);
  if(o.type_id&&!writingTypes.some(t=>t.id===o.type_id))select.add(new Option((globalThis.CorporiumI18n?.f("a1dc86dd762f16",()=>[])??'类型已变化，请重新选择'),o.type_id));
  select.value=o.type_id||(!o.id&&writingTypes.length?writingTypes[0].id:'');
  function apply(){const t=writingTypes.find(t=>t.id===select.value),name=row.querySelector('.orthography-label'),font=row.querySelector('.orthography-font');name.disabled=font.disabled=!!select.value;if(t){name.value=t.name;selectFont(font,t.font);row.querySelector('.orthography-text').style.fontFamily=['serif','sans-serif'].includes(t.font)?t.font:`"${t.font}", serif`;}}
  select.onchange=()=>{apply();lexemeDirty=true;};apply();
};
$('lexeme-language').addEventListener('change',async()=>{try{writingTypes=await fetchWritingTypes($('lexeme-language').value);for(const row of $('lexeme-orthographies').children){const select=row.querySelector('.orthography-type');select.innerHTML=(globalThis.CorporiumI18n?.f("8cf5840bd9c242",()=>[writingTypes.map(t=>`<option value="${esc(t.id)}">${esc(t.name)}</option>`).join('')])??'<option value="">未归类（保留单独设置）</option>'+writingTypes.map(t=>`<option value="${esc(t.id)}">${esc(t.name)}</option>`).join(''));select.value='';row.querySelector('.orthography-label').disabled=row.querySelector('.orthography-font').disabled=false;}}catch(e){$('lexeme-error').textContent=e.message;}});

makeDialog('standalone-editor',(globalThis.CorporiumI18n?.f("b8ff5c29bedf3e",()=>[])??'<h2>独立例句</h2><form id="standalone-form"><input type="hidden" id="standalone-original"><label>IPA<textarea id="standalone-ipa" rows="2"></textarea></label><label>语素与标注（每行：形式 + Tab + gloss）<textarea id="standalone-words" rows="4" placeholder="elǰige&#9;驴"></textarea></label><label>自由翻译<textarea id="standalone-translation" rows="2"></textarea></label><label>来源信息<textarea id="standalone-source" rows="2"></textarea></label><label>备注<textarea id="standalone-notes" rows="2"></textarea></label><h3>说明的词条与义项</h3><p>词条关联可留空。编辑将更新所有引用处；删除后调查中的引用会显示原句缺失，可撤销恢复。</p><div id="standalone-targets"></div><button type="button" id="standalone-add-target">＋ 关联另一词条</button><p id="standalone-error" role="alert"></p><button type="submit" id="standalone-save" class="primary">保存独立例句</button></form>'));
function addExampleTarget(t={}){
  const row=document.createElement('section');row.className='example-target';row.innerHTML=(globalThis.CorporiumI18n?.f("aba4334a54c9e6",()=>[exampleLexemes.map(x=>`<option value="${esc(x.id)}">${esc((x.target_kind==='morpheme'?(globalThis.CorporiumI18n?.f("cd8ca646c91759",()=>[])??'语素 · '):'')+lexemePlainLabel(x))}${x.body.homonym_note?' · '+esc(x.body.homonym_note):''}</option>`).join('')])??`<label>条目<select class="target-lexeme">${exampleLexemes.map(x=>`<option value="${esc(x.id)}">${esc((x.target_kind==='morpheme'?'语素 · ':'')+lexemePlainLabel(x))}${x.body.homonym_note?' · '+esc(x.body.homonym_note):''}</option>`).join('')}</select></label><label>词类用法<select class="target-usage"></select></label><label>义项<select class="target-sense"></select></label><button type="button">移除此关联</button>`);
  const x=row.querySelector('.target-lexeme'),u=row.querySelector('.target-usage'),s=row.querySelector('.target-sense');x.value=t.lexeme_id||standaloneLexeme.id||exampleLexemes[0]?.id||'';
  function senses(){const lex=exampleLexemes.find(l=>l.id===x.value),morpheme=lex?.target_kind==='morpheme',usage=paradigmUsages(lex?.body).find(v=>v.id===u.value);s.parentElement.firstChild.textContent=morpheme?(globalThis.CorporiumI18n?.f("93320044803917",()=>[])??'意义／功能'):(globalThis.CorporiumI18n?.f("70d159d03f5cad",()=>[])??'义项');s.innerHTML='<option value="">'+(morpheme?(globalThis.CorporiumI18n?.f("fb65919b4b28e4",()=>[])??'全部意义／功能'):(globalThis.CorporiumI18n?.f("1bfbbb2a238781",()=>[])??'整个词类用法'))+'</option>'+(usage?.senses||[]).map(v=>`<option value="${esc(v.id)}">${esc(v.short_gloss||v.definition||(morpheme?(globalThis.CorporiumI18n?.f("cf3652cdccf7c0",()=>[])??'意义／功能'):(globalThis.CorporiumI18n?.f("23e625de0f1e13",()=>[])??'义项')))}</option>`).join('');}
  function usages(){const lex=exampleLexemes.find(l=>l.id===x.value),morpheme=lex?.target_kind==='morpheme',usages=lex?.body.usages||[];u.parentElement.firstChild.textContent=morpheme?(globalThis.CorporiumI18n?.f("6f78fbfa425340",()=>[])??'意义／功能分组'):(globalThis.CorporiumI18n?.f("c5606f2bb8d616",()=>[])??'词类用法');u.parentElement.hidden=morpheme&&usages.length<=1;u.innerHTML='<option value="">'+(morpheme?(globalThis.CorporiumI18n?.f("1104648cc041d4",()=>[])??'整个语素'):(globalThis.CorporiumI18n?.f("bdfae526c4d2e2",()=>[])??'整个词条'))+'</option>'+usages.map((v,i)=>`<option value="${esc(v.id)}">${esc(morpheme?(globalThis.CorporiumI18n?.f("6da23b27f74316",()=>[i+1])??'意义／功能组 '+(i+1)):usageLabel(v))}</option>`).join('');if(morpheme&&usages.length===1)u.value=usages[0].id;senses();}
  x.onchange=usages;u.onchange=senses;usages();if(t.usage_id)u.value=t.usage_id;senses();s.value=t.sense_id||'';row.querySelector('button').onclick=()=>{row.remove();standaloneDirty=true;};row.dataset.componentRef=t.component_ref?JSON.stringify(t.component_ref):'';row.dataset.componentLexeme=t.lexeme_id||'';row.dataset.segmentationRef=t.segmentation_ref?JSON.stringify(t.segmentation_ref):'';if(t.segmentation_ref)row.insertAdjacentHTML('afterbegin',(globalThis.CorporiumI18n?.f("23de0f8b236229",()=>[esc(t.segmentation_ref.unit_form),esc(t.segmentation_ref.unit_gloss),t.segmentation_review?(globalThis.CorporiumI18n?.f("afd1e1acb8fafd",()=>[])??' · 待核对'):''])??'<p>语素关联：'+esc(t.segmentation_ref.unit_form)+' → '+esc(t.segmentation_ref.unit_gloss)+(t.segmentation_review?' · 待核对':'')+'</p>'));$('standalone-targets').append(row);
}
async function openStandalone(x,e=null){
  standaloneCommit=null;standaloneLexeme=x;standaloneEditing=e;exampleLexemes=[];
  applyLanguageTypography($('standalone-editor'),JSON.parse(languageList.find(l=>l.id===x.language_id)?.metadata||'{}'));
  let page=1;while(true){const result=await api('lexemes?'+new URLSearchParams({targets:'all',lexical_language:x.language_id,page}));exampleLexemes.push(...result.items);if(page>=result.pages)break;page++;}
  const b=e?.body||{};if($('standalone-grammaticality')&&window.CorporiumGrammaticality)$('standalone-grammaticality').innerHTML=window.CorporiumGrammaticality.choices(x.language_id,b.grammaticality||'');for(const k of ['original','ipa','translation','source','notes'])$('standalone-'+k).value=b[k]||'';
  $('standalone-words').value=(b.words||[]).map(w=>w.form+'\t'+w.gloss).join('\n');
  $('standalone-targets').replaceChildren();
  for(const [index,target] of (b.targets||(x.id?[{lexeme_id:x.id}]:[])).entries()){
    addExampleTarget(target);
    if(e)$('standalone-targets').lastElementChild.dataset.targetIndex=String(index);
  }
  standaloneSourceSnapshot=e?standaloneSourceValues():null;
  $('standalone-error').textContent='';standaloneDirty=false;$('standalone-editor').showModal();
}
$('standalone-add-target').onclick=()=>{addExampleTarget();standaloneDirty=true;};
$('standalone-words').onkeydown=e=>{if(e.key==='Tab'&&!e.shiftKey){e.preventDefault();const t=e.target;t.setRangeText('\t',t.selectionStart,t.selectionEnd,'end');standaloneDirty=true;}};
$('standalone-form').oninput=$('standalone-form').onchange=()=>standaloneDirty=true;
$('standalone-editor').addEventListener('cancel',e=>guardDialogDiscard(e,standaloneDirty,(globalThis.CorporiumI18n?.f("121573638a8a04",()=>[])??'放弃尚未保存的例句修改？')));
$('standalone-editor').querySelector('.close').onclick=e=>{e.preventDefault();if($('standalone-editor').dispatchEvent(new Event('cancel',{cancelable:true})))$('standalone-editor').close();};
window.addEventListener('beforeunload',e=>{if($('standalone-editor').open&&standaloneDirty){e.preventDefault();e.returnValue='';}});
$('standalone-form').onsubmit=async event=>{
  event.preventDefault();const source={kind:'independent',id:standaloneEditing?.id};const run=async()=>{$('standalone-save').disabled=true;
  try{
    const values=standaloneSourceValues(),rows=[...$('standalone-targets').children];
    const targets=rows.map(row=>({lexeme_id:row.querySelector('.target-lexeme').value,usage_id:row.querySelector('.target-usage').value,sense_id:row.querySelector('.target-sense').value,form_id:row.querySelector('.target-form').value,features:readFeatures(row.querySelector('.target-features'))}));
    const request={id:standaloneEditing?.id,revision:standaloneEditing?.revision,_language:standaloneLexeme.language_id};
    let saved;
    if(!standaloneCommit&&request.id&&standaloneSourceSnapshot&&values.every((value,i)=>value===standaloneSourceSnapshot[i])){
      saved=await api('example-links-save',{...request,targets:targets.map((target,i)=>({...target,index:rows[i].dataset.targetIndex===undefined?undefined:Number(rows[i].dataset.targetIndex)}))});
    }else{
      const body=Object.fromEntries(standaloneSourceFields.map((key,i)=>[key,values[i]]));
      body.words=CorporiumPairs.parse(body.words);
      body.targets=targets.map((target,i)=>({...target,component_ref:rows[i].dataset.componentRef&&rows[i].dataset.componentLexeme===target.lexeme_id?JSON.parse(rows[i].dataset.componentRef):undefined,segmentation_ref:rows[i].dataset.segmentationRef?JSON.parse(rows[i].dataset.segmentationRef):undefined}));
      saved=standaloneCommit?await standaloneCommit(body):await api('example-save',{...request,body});
    }
    standaloneDirty=false;standaloneCommit=null;$('standalone-editor').close();if(workspace==='dictionary'&&standaloneLexeme.id)await showLexeme(standaloneLexeme.id);else await refreshExampleViews();if(source.id)await window.corporiumSentenceInspector?.afterExampleSave?.(source);document.dispatchEvent(new CustomEvent('corporium-independent-saved',{detail:saved}));
  }catch(e){$('standalone-error').textContent=e.message;}finally{$('standalone-save').disabled=false;}};return window.corporiumPreserveExampleLocation?window.corporiumPreserveExampleLocation(source,run):run();
};
async function loadStandalonePage(x,page,focus){
 const query=new URLSearchParams({id:x.id,paged:'1',page,form_id:exampleForm});
 if(focus!==undefined)query.set('focus',focus);
 return api('dictionary-examples?'+query);
}
function standaloneEvidenceLabel(target,x){
 const usage=paradigmUsages(x.body).find(u=>u.id===target.usage_id),sense=usage?.senses.find(s=>s.id===target.sense_id);
 return rich(x.target_kind==='morpheme'?(globalThis.CorporiumI18n?.f("8fa03c6b508add",()=>[])??'语素'):
  usage?.pos||(globalThis.CorporiumI18n?.f("37e11b8bf6ceec",()=>[])??'整个词条'))+(sense?' / '+senseDisplay(sense,x.language_id):'');
}
async function renderStandalone(x,request,initialPage=1,initial=null,cachedTags=null){
  const data=initial||await loadStandalonePage(x,initialPage),entries=data.items,total=data.total,pages=data.pages;let page=data.page;
  if(!initial)await window.corporiumPrepareEvidence?.(null,data);
  const standaloneTags=cachedTags||await api('grammar-tags?language='+encodeURIComponent(x.language_id));if(request!==exampleRequest||dictionarySelection!==x.id)return;
  const controls=$('dictionary-example-controls');if(!controls.querySelector('#example-source'))controls.innerHTML=(globalThis.CorporiumI18n?.f("d683cabe01e081",()=>[])??'<h3>例句与例证</h3><label>来源 <select id="example-source"><option value="all">全部来源</option><option value="corpus">语料引用</option><option value="independent">独立例句</option></select></label> <button id="new-standalone">＋ 添加独立例句</button>');
  mountDictionaryUnlinkAll($('new-standalone'),x,()=>showLexeme(x.id));
  $('example-source').value=exampleSource;
  const section=document.createElement('section');section.id='standalone-examples';section.dataset.independentCount=String(total);section.classList.toggle('brief-empty',!total);$('standalone-examples')?.remove();controls.after(section);
  function draw(){const visible=entries;section.innerHTML=(globalThis.CorporiumI18n?.f("099667d983e2c6",()=>[total,total?'':'hidden',visible.map((e,i)=>{const b=e.body,targets=b.targets.filter(t=>t.lexeme_id===x.id);return (globalThis.CorporiumI18n?.f("f63b61a676c0ef",()=>[esc(e.id),i,i+1,b.targets.length,targets.map(t=>{const u=paradigmUsages(x.body).find(u=>u.id===t.usage_id),s=u?.senses.find(s=>s.id===t.sense_id);return '<div class="lex-example-classification"><span>'+rich(x.target_kind==='morpheme'?(globalThis.CorporiumI18n?.f("8fa03c6b508add",()=>[])??'语素'):u?.pos||(globalThis.CorporiumI18n?.f("37e11b8bf6ceec",()=>[])??'整个词条'))+(s?' / '+senseDisplay(s,x.language_id):'')+'</span>'+morphEvidence(t,x.body,standaloneTags)+'</div>';}).join(''),renderDictionaryExample({...b,language_id:x.language_id},'independent',e.id,targets),esc(b.source||(globalThis.CorporiumI18n?.f("6fa88e5af739c9",()=>[])??'未填写')),i,i,i,i])??`<article class="lex-example" id="independent-example-${esc(e.id)}"><div class="lex-example-source"><input type="checkbox" data-example-select="${i}" aria-label="选择独立例句 ${i+1}"><strong class="lex-tag">独立例句</strong></div><small>共关联 ${b.targets.length} 个词典关联</small><div class="lex-example-classifications">${targets.map(t=>{const u=paradigmUsages(x.body).find(u=>u.id===t.usage_id),s=u?.senses.find(s=>s.id===t.sense_id);return '<div class="lex-example-classification"><span>'+rich(x.target_kind==='morpheme'?'语素':u?.pos||'整个词条')+(s?' / '+senseDisplay(s,x.language_id):'')+'</span>'+morphEvidence(t,x.body,standaloneTags)+'</div>';}).join('')}</div>${renderDictionaryExample({...b,language_id:x.language_id},'independent',e.id,targets)}<p class="preserve-lines">出处：${esc(b.source||'未填写')}</p><div class="lex-example-footer"><button data-independent-layers="${i}">附加标注</button><button data-example-edit="${i}">编辑信息</button> <button data-example-unlink="${i}">解除关联</button><button data-independent-delete="${i}" class="danger">删除独立例句</button></div></article>`);}).join(''),total?'':'hidden'])??`<h3>独立例句 · ${total}</h3><nav id="standalone-top-pagination" ${total?'':'hidden'} aria-label="独立例句上方分页"></nav>`+visible.map((e,i)=>{const b=e.body,targets=b.targets.filter(t=>t.lexeme_id===x.id);return `<article class="lex-example" id="independent-example-${esc(e.id)}"><div class="lex-example-source"><input type="checkbox" data-example-select="${i}" aria-label="选择独立例句 ${i+1}"><strong class="lex-tag">独立例句</strong></div><small>共关联 ${b.targets.length} 个词典关联</small><div class="lex-example-classifications">${targets.map(t=>{const u=paradigmUsages(x.body).find(u=>u.id===t.usage_id),s=u?.senses.find(s=>s.id===t.sense_id);return '<div class="lex-example-classification"><span>'+rich(x.target_kind==='morpheme'?'语素':u?.pos||'整个词条')+(s?' / '+senseDisplay(s,x.language_id):'')+'</span>'+morphEvidence(t,x.body,standaloneTags)+'</div>';}).join('')}</div>${renderDictionaryExample({...b,language_id:x.language_id},'independent',e.id,targets)}<p class="preserve-lines">出处：${esc(b.source||'未填写')}</p><div class="lex-example-footer"><button data-independent-layers="${i}">附加标注</button><button data-example-edit="${i}">编辑信息</button> <button data-example-unlink="${i}">解除关联</button><button data-independent-delete="${i}" class="danger">删除独立例句</button></div></article>`;}).join('')+`<nav id="standalone-bottom-pagination" ${total?'':'hidden'} aria-label="独立例句下方分页"></nav>`);
    section.querySelectorAll('[data-independent-layers]').forEach(b=>b.onclick=dictSafe(()=>openAnnotation('independent',entries[+b.dataset.independentLayers].id)));
    section.querySelectorAll('[data-example-edit]').forEach(b=>b.onclick=dictSafe(()=>openStandalone(x,entries[+b.dataset.exampleEdit])));
    section.querySelectorAll('[data-independent-delete]').forEach(b=>b.onclick=dictSafe(async()=>{const e=entries[+b.dataset.independentDelete];if(!await corporiumConfirm((globalThis.CorporiumI18n?.f("40d57ea3974476",()=>[])??'确认删除这条独立例句？所有词条中的引用都会移除，可撤销。')))return;await api('example-delete',{id:e.id,revision:e.revision,confirmed:true,_language:e.language_id});await showLexeme(x.id);}));
    for(const nav of [section.querySelector('#standalone-top-pagination'),section.querySelector('#standalone-bottom-pagination')]){nav.dataset.examplePageActions='';nav.dataset.examplePages=String(pages);if(total)topPagination(nav,page,pages,dictSafe(async target=>{await leaveSentenceDrafts();await renderStandalone(x,request,target,null,standaloneTags);}));}
    wireExampleSelection(section,visible,async rows=>{await api('dictionary-examples-unlink',{lexeme_id:x.id,form_id:exampleForm,items:rows.map(e=>({id:e.id,revision:e.revision})),_language:x.language_id});await refreshUnlinkedExamples(()=>renderStandalone(x,request,page));});
    globalThis.CorporiumDictionaryEvidence?.refresh();
  }
  function filter(){exampleSource=$('example-source').value;$('corpus-examples-section').hidden=exampleSource==='independent';section.hidden=exampleSource==='corpus';globalThis.CorporiumDictionaryEvidence?.refresh();}
  focusStandaloneExample=dictSafe(async id=>{
   if(!entries.some(entry=>entry.id===id)){
    const data=await loadStandalonePage(x,page,id);
    if(request!==exampleRequest||dictionarySelection!==x.id)return;
    if(!data.focus_found){$('notice').textContent=globalThis.CorporiumI18n?.ui('这条例句已删除或已解除与该词条的关联。','This example has been deleted or unlinked from this entry.')??'这条例句已删除或已解除与该词条的关联。';return;}
    await renderStandalone(x,request,data.page,data,standaloneTags);
   }
   if(request!==exampleRequest||dictionarySelection!==x.id)return;
   $('example-source').value='independent';$('example-source').dispatchEvent(new Event('change'));
   $('independent-example-'+id)?.scrollIntoView({block:'center'});
  });
  draw();filter();$('example-source').onchange=filter;$('new-standalone').onclick=dictSafe(async()=>{await openStandalone(x);globalThis.CorporiumDictionaryEvidence?.refresh();});
  section.refreshMorphEvidence=structure=>{
   for(const e of entries){
    const classifications=$('independent-example-'+e.id)?.querySelectorAll('.lex-example-classifications .lex-example-classification');
    e.body.targets.filter(t=>t.lexeme_id===x.id).forEach((t,i)=>{
     if((structure.variants&&t.form_id)||(structure.morphology&&t.component_ref))updateMorphEvidence(classifications?.[i],t,x,standaloneTags);
    });
   }
  };
  section.savedEvidenceIds=()=>entries.map(entry=>entry.id);
  section.applySavedEvidence=rows=>{
   entries.forEach((entry,index)=>{
    const article=$('independent-example-'+entry.id),fresh=rows?.[index];
    const previousWords=entry.body.words;
    if(fresh)Object.assign(entry,fresh);
    const targets=entry.body.targets.filter(target=>target.lexeme_id===x.id);
    const labels=article.querySelectorAll('.lex-example-classifications .lex-example-classification>span:first-child');
    targets.forEach((target,i)=>{if(labels[i])labels[i].innerHTML=standaloneEvidenceLabel(target,x);});
    if(fresh)replaceDictionaryEvidenceWords(article,renderDictionaryExample(
     {...entry.body,language_id:x.language_id},'independent',entry.id,targets),previousWords,entry.body.words);
   });
  };
  section.refreshCurrentExamples=async source=>{
   const data=await loadStandalonePage(x,page),next=data.items;
   if(request!==exampleRequest||dictionarySelection!==x.id||!section.isConnected)return;
   if(data.total!==total||data.page!==page||next.length!==entries.length||next.some((e,i)=>e.id!==entries[i].id)){await renderStandalone(x,request,data.page,data,source?.kind==='lexeme'?standaloneTags:null);return;}
   if(source?.redraw||source?.kind==='lexeme'&&source.id===x.id){next.forEach((entry,index)=>Object.assign(entries[index],entry));draw();filter();return;}
   next.forEach((e,i)=>{Object.assign(entries[i],e);if(source?.kind!=='independent'||e.id!==source.id)return;const article=$('independent-example-'+e.id),card=article?.querySelector('.editable-example');if(!card)return;const template=document.createElement('template');template.innerHTML=renderDictionaryExample({...e.body,language_id:x.language_id},'independent',e.id,e.body.targets.filter(t=>t.lexeme_id===x.id));card.replaceWith(template.content.firstElementChild);const count=article.querySelector(':scope>small');if(count)count.textContent=globalThis.CorporiumI18n?.ui('共关联 '+e.body.targets.length+' 个词典关联',e.body.targets.length+' dictionary links')??'共关联 '+e.body.targets.length+' 个词典关联';});
  };
}
