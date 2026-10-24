const languagePanel=document.createElement('section');
languagePanel.className='language-panel';
languagePanel.innerHTML='<select id="language-select" aria-label="切换语言"></select><div class="language-tools"><button id="add-language" class="language-icon" title="新建语言" aria-label="新建语言">＋</button><button id="edit-language" class="language-icon" title="语言信息与设置" aria-label="语言信息与设置">⚙</button><button id="import-language-package" class="language-icon" title="导入语言数据包" aria-label="导入语言数据包">↥</button><button id="export-language" class="language-icon" title="导出当前语言" aria-label="导出当前语言">↧</button></div>';
languagePanel.querySelector('#import-language-package').innerHTML=uiIcon('import');
languagePanel.querySelector('#export-language').innerHTML=uiIcon('export');
document.querySelector('aside .eyebrow').before(languagePanel);
const brandLanguageRow=document.createElement('div');brandLanguageRow.className='brand-language-row';$('brand-language').before(brandLanguageRow);
const brandLanguagePicker=document.createElement('button');brandLanguagePicker.type='button';brandLanguagePicker.className='brand-language-picker';brandLanguagePicker.title='切换语言';brandLanguagePicker.setAttribute('aria-label','切换语言');brandLanguagePicker.setAttribute('aria-haspopup','menu');brandLanguagePicker.setAttribute('aria-expanded','false');brandLanguagePicker.setAttribute('aria-controls','brand-language-menu');brandLanguagePicker.textContent='▾';
$('language-select').hidden=true;brandLanguageRow.append($('brand-language'),brandLanguagePicker);
const brandLanguageMenu=document.createElement('div');brandLanguageMenu.id='brand-language-menu';brandLanguageMenu.setAttribute('role','menu');brandLanguageMenu.setAttribute('aria-label','切换语言');brandLanguageMenu.hidden=true;document.body.append(brandLanguageMenu);
function closeBrandLanguageMenu(focus=false){brandLanguageMenu.hidden=true;brandLanguagePicker.setAttribute('aria-expanded','false');if(focus)brandLanguagePicker.focus();}
function openBrandLanguageMenu(){
  brandLanguageMenu.innerHTML=[{id:'all',name:'全部语言'},...languageList].map(l=>`<button type="button" role="menuitemradio" tabindex="-1" aria-checked="${l.id===activeLanguage}" data-language="${esc(l.id)}"><span aria-hidden="true">${l.id===activeLanguage?'✓':''}</span><span>${esc(l.name)}</span></button>`).join('');
  const rect=brandLanguagePicker.getBoundingClientRect(),width=Math.min(260,window.innerWidth-16);
  brandLanguageMenu.style.width=width+'px';brandLanguageMenu.style.left=Math.max(8,Math.min(rect.right-width,window.innerWidth-width-8))+'px';brandLanguageMenu.style.top=(rect.bottom+5)+'px';brandLanguageMenu.style.maxHeight=Math.max(80,Math.min(320,window.innerHeight-rect.bottom-13))+'px';
  brandLanguageMenu.hidden=false;brandLanguagePicker.setAttribute('aria-expanded','true');(brandLanguageMenu.querySelector('[aria-checked="true"]')||brandLanguageMenu.firstElementChild)?.focus();
}
brandLanguagePicker.onclick=()=>brandLanguageMenu.hidden?openBrandLanguageMenu():closeBrandLanguageMenu();
brandLanguagePicker.onkeydown=e=>{if(['ArrowDown','ArrowUp'].includes(e.key)){e.preventDefault();openBrandLanguageMenu();}};
brandLanguageMenu.onclick=safe(async e=>{const item=e.target.closest('[data-language]');if(!item)return;closeBrandLanguageMenu(true);if(item.dataset.language!==activeLanguage)await switchLanguage(item.dataset.language);});
brandLanguageMenu.onkeydown=e=>{
  if(e.key==='Escape'){e.preventDefault();closeBrandLanguageMenu(true);return;}
  if(e.key==='Tab'){closeBrandLanguageMenu(true);return;}
  const items=[...brandLanguageMenu.querySelectorAll('button')],index=items.indexOf(document.activeElement);
  if(['ArrowDown','ArrowUp','Home','End'].includes(e.key)){e.preventDefault();items[e.key==='Home'?0:e.key==='End'?items.length-1:(index+(e.key==='ArrowDown'?1:-1)+items.length)%items.length]?.focus();}
};
document.addEventListener('pointerdown',e=>{if(!brandLanguageMenu.contains(e.target)&&!brandLanguagePicker.contains(e.target))closeBrandLanguageMenu();});
window.addEventListener('resize',()=>closeBrandLanguageMenu());
document.addEventListener('scroll',e=>{if(!brandLanguageMenu.contains(e.target))closeBrandLanguageMenu();},true);
const languageDetails=document.createElement('details');
languageDetails.className='metadata-panel language-details';
languageDetails.innerHTML='<summary id="language-summary">标注缩写</summary><div id="language-abbreviations"></div>';
document.querySelector('main header').after(languageDetails);
const languageFields=[['aliases','别名'],['native_name','本地名称（可填写 IPA）'],['code','语言代码（可选，如 ISO 639-3）'],['family','语系与语支'],['region','使用地区'],['description','语言说明'],['notes','研究备注']];
const checkFields=[['check_boundaries','核查语素数量和边界',true],['check_commands','提示未支持的 Typst 命令',true],['check_glossary','提示尚未登记的疑似语法标签',false],['require_ipa','提示 IPA 空缺',false],['require_translation','提示自由翻译空缺',false]];
const fontOptions='<option value="IPAPANNEW">IPAPANNEW</option><option value="Junicode">Junicode</option><option value="serif">系统衬线字体</option><option value="sans-serif">系统无衬线字体</option>';
makeDialog('language-dialog','<h2 id="language-heading">语言信息</h2><form id="language-form"><label>语言名称<input id="language-name" required></label>'+languageFields.map(([k,label])=>`<label>${label}<textarea id="language-${k}" rows="${['description','notes'].includes(k)?3:1}"></textarea></label>`).join('')+'<div class="metadata-grid"><label>IPA 默认字体<select id="language-ipa-font">'+fontOptions+'</select></label><label>语素默认字体<select id="language-annotation-font">'+fontOptions+'</select></label></div><label>标注缩写表<textarea id="language-glossary" rows="6" placeholder="每行：缩写 = 说明&#10;GEN = 属格&#10;PST = 过去时"></textarea></label><p><small>按正式标签及独立参考库检查；普通英文词义默认不提示。候选须经确认登记，忽略项按本语言保存。</small></p>'+checkFields.map(([k,label])=>`<label><input type="checkbox" id="language-${k}"> ${label}</label>`).join('')+'<p id="language-error" role="alert"></p><button class="primary" id="save-language" type="submit">保存语言信息</button></form>');
makeDialog('new-text-dialog','<h2>新建文本</h2><form id="new-text-form"><label>所属语言<select id="new-text-language"></select></label><label>文本标题<input id="new-text-title" required></label><p id="new-text-error" role="alert"></p><button class="primary" id="create-text" type="submit">创建文本</button></form>');
$('import-title').parentElement.insertAdjacentHTML('beforebegin','<label>导入到语言<select id="import-language"></select></label>');
$('file').accept='.typ';
$('file').parentElement.firstChild.textContent='选择 .typ 文件';
$('import-content').parentElement.firstChild.textContent='Typst 内容';
$('info-language').parentElement.firstChild.textContent='语言补充说明';
$('import-dialog').querySelector('h2').textContent='导入语料';
$('import-dialog').querySelector('p').textContent='导入文本到已有语言。导入语言数据（包括 JSON）请到左侧“语言选项”。';
$('import').textContent='导入文本';
$('ipa').parentElement.insertAdjacentHTML('beforebegin','<div class="metadata-grid"><label>句子语言<select id="entry-language"></select></label><label>语言备注<input id="entry-language-notes" placeholder="如：引语为另一种语言"></label></div>');
document.querySelector('.filters').insertAdjacentHTML('beforeend','<label>句子语言 <select id="sentence-language"><option value="">不限</option></select></label>');
$('language-glossary').parentElement.insertAdjacentHTML('beforebegin','<details><summary>音系单位边界</summary><p><small>仅含井号的语素格自动视为边界，不参与词典关联。每行用不同数量的井号指定名称；未命名的数量仍识别为音系边界。浏览时标注行默认留空，悬停井号可查看名称。留空可恢复默认名称。</small></p><label>井号与边界名称<textarea id="language-boundaries" rows="4" placeholder="# = 音系词边界&#10;## = 音系短语边界"></textarea></label></details>');
let editingLanguage=null,languageSwitchBusy=false;
function languageOptions(includeAll=false){return (includeAll?'<option value="all">全部语言</option>':'')+languageList.map(l=>`<option value="${esc(l.id)}">${esc(l.name)}</option>`).join('')}
function projectStorageKey(key){return typeof desktopProjectKey==='string'?key+':project:'+desktopProjectKey:key;}
async function loadLanguages(){
  languageList=await api('languages');
  if(activeLanguage!=='all'&&!languageList.some(l=>l.id===activeLanguage))activeLanguage=languageList.find(l=>l.id==='ordos')?.id||languageList[0]?.id||'all';
  try{localStorage.setItem(projectStorageKey('corpus-language'),activeLanguage);}catch{}
  $('language-select').innerHTML=languageOptions(true);$('language-select').value=activeLanguage;
  const sentence=$('sentence-language').value;
  $('sentence-language').innerHTML='<option value="">不限</option>'+languageOptions();$('sentence-language').value=sentence;
  renderLanguage();
}
function renderLanguage(){
  const lang=languageList.find(l=>l.id===activeLanguage),m=lang?JSON.parse(lang.metadata):{};
  $('brand-home').textContent='Corporium';
  $('brand-language').textContent=lang?.name||'全部语言';
  $('brand-native').textContent=m.native_name||'';
  $('brand-native').hidden=!m.native_name;
  const ipaFont=validFont(m.ipa_font)?m.ipa_font:'IPAPANNEW';
  $('brand-native').style.fontFamily=['serif','sans-serif'].includes(ipaFont)?ipaFont:`"${ipaFont}", serif`;
  document.title='Corporium · '+(lang?.name||'全部语言');
  $('edit-language').disabled=!lang;$('export-language').disabled=!lang;$('new-folder').disabled=!lang;
  $('all').textContent=lang?'本语言全部文本':'所有语言的文本';
  languageDetails.hidden=!lang;
  if(lang){
    $('language-summary').textContent='标注缩写';
    $('language-abbreviations').innerHTML='<dl class="glossary-list">'+Object.entries(m.glossary||{}).map(([k,v])=>`<div><dt>${grammarLabel(k,lang.id)}</dt><dd>${esc(v)}</dd></div>`).join('')+'</dl>';
  }
  if(!selected)$('title').textContent=lang?lang.name+' · 全部文本':'全部语言';
}
async function switchLanguage(lid){
  if(languageSwitchBusy)return;
  if(document.querySelector('dialog[open]'))throw Error('请先完成或关闭当前编辑窗口。');
  if(infoDirty&&!await corporiumConfirm('元信息尚未保存，是否放弃修改并切换语言？')){$('language-select').value=activeLanguage;return;}
  languageSwitchBusy=true;
  try{
    activeLanguage=lid;infoDirty=false;selected='';page=1;request++;chosen.clear();clearFilters();$('sentence-language').value='';
    try{localStorage.setItem(projectStorageKey('corpus-language'),lid)}catch{}
    await loadLanguages();await selectText('');await refreshUndo();
  }finally{languageSwitchBusy=false;}
}
$('language-select').onchange=safe(()=>switchLanguage($('language-select').value));
function openLanguage(lang=null){
  editingLanguage=lang;const m=lang?JSON.parse(lang.metadata):{};
  $('language-heading').textContent=lang?'编辑语言信息':'添加语言';$('language-name').value=lang?.name||'';
  for(const [k] of languageFields)$('language-'+k).value=m[k]||'';
  const fonts=languageTypographySettings(m);
  for(const [row,font] of languageTypographyRows){selectFont($('language-'+font+'-font'),fonts[font+'_font']);$('language-'+row+'-variant').value=fonts[row+'_variant'];$('language-'+row+'-scale').value=String(fonts[row+'_scale']);}
  $('language-boundaries').value=Object.entries(m.phonological_boundaries||{}).map(([k,v])=>k+' = '+v).join('\n');
  $('language-glossary').value=Object.entries(m.glossary||{}).map(([k,v])=>k+' = '+v).join('\n');
  for(const [k,,def] of checkFields)$('language-'+k).checked=m[k]??def;
  refreshLanguageIPA();$('language-error').textContent='';$('language-dialog').showModal();
}
$('add-language').onclick=()=>openLanguage();
$('edit-language').onclick=()=>openLanguage(languageList.find(l=>l.id===activeLanguage));
$('language-form').onsubmit=async event=>{
  event.preventDefault();$('save-language').disabled=true;
  try{
    const m=editingLanguage?JSON.parse(editingLanguage.metadata):{};
    for(const [k] of languageFields)m[k]=$('language-'+k).value;
    for(const [row,font] of languageTypographyRows){m[font+'_font']=$('language-'+font+'-font').value;m[row+'_variant']=$('language-'+row+'-variant').value;m[row+'_scale']=Number($('language-'+row+'-scale').value);}
    m.glossary={};
    for(const line of $('language-glossary').value.split('\n').filter(x=>x.trim())){
      const at=line.indexOf('=');if(at<1)throw Error('缩写表请按“GEN = 属格”的格式逐行填写');
      const key=line.slice(0,at).trim();if(!key||Object.keys(m.glossary).some(k=>k.toLowerCase()===key.toLowerCase()))throw Error('缩写不能为空或重复');
      m.glossary[key]=line.slice(at+1).trim();
    }
    m.phonological_boundaries={};
    for(const line of $('language-boundaries').value.split('\n').filter(x=>x.trim())){const match=line.match(/^\s*(#+)\s*=\s*(.+?)\s*$/);if(!match||m.phonological_boundaries[match[1]])throw Error('边界请按“# = 音系词边界”填写，井号数量不能重复、名称不能为空');m.phonological_boundaries[match[1]]=match[2];}
    for(const [k] of checkFields)m[k]=$('language-'+k).checked;
    const result=await api('save-language',{id:editingLanguage?.id,revision:editingLanguage?.revision,name:$('language-name').value,metadata:m,_language:editingLanguage?.id||activeLanguage});
    $('language-dialog').close();await switchLanguage(result.id);
  }catch(e){$('language-error').textContent=e.message}finally{$('save-language').disabled=false;}
};
$('export-language').onclick=safe(async()=>{const data=await api('export-language');download((languageList.find(l=>l.id===activeLanguage)?.name||'language').replace(/[\\/:*?"<>|]/g,'-')+'.json',JSON.stringify(data,null,2),'application/json');});
$('import').onclick=()=>{$('import-language').innerHTML=languageOptions();$('import-language').value=activeLanguage==='all'?(languageList[0]?.id||''):activeLanguage;$('import-dialog').showModal();};
$('import-submit').onclick=async()=>{
  $('import-submit').disabled=true;
  try{
    const title=$('import-title').value.trim();
    const lid=$('import-language').value;
    const content=$('import-content').value;
    let r;
    if(content.trim().startsWith('{'))throw Error('这里仅导入 Typst 文本。语言 JSON 请在左侧“语言选项 → 导入语言数据包”中导入。');
    else{if(!title)throw Error('请填写文本标题');r=await api('import',{title,source:$('source').value,content,_language:lid});}
    $('import-dialog').close();await switchLanguage(lid);await selectText(r.id||'');
    if(r.duplicate)corporiumStatus('这份源文件已在本语言中导入，已打开已有文本。');
  }catch(e){$('import-error').textContent=e.message}finally{$('import-submit').disabled=false;}
};
$('new').onclick=()=>{$('new-text-language').innerHTML=languageOptions();$('new-text-language').value=activeLanguage==='all'?(languageList[0]?.id||''):activeLanguage;$('new-text-title').value='';$('new-text-error').textContent='';$('new-text-dialog').showModal();};
$('new-text-form').onsubmit=async event=>{
  event.preventDefault();$('create-text').disabled=true;
  try{const lid=$('new-text-language').value;const r=await api('new-text',{title:$('new-text-title').value.trim(),empty:true,_language:lid});$('new-text-dialog').close();await switchLanguage(lid);await selectText(r.id);await beginSentenceDraft({kind:'corpus',text_id:r.id});}
  catch(e){$('new-text-error').textContent=e.message}finally{$('create-text').disabled=false;}
};
const languageReadEditor=readEditor;
readEditor=function(){return {...languageReadEditor(),language_id:$('entry-language').value,language_notes:$('entry-language-notes').value};};
const languageEdit=edit;
edit=async function(entry){
  $('entry-language').innerHTML='<option value="">沿用文本默认语言</option>'+languageOptions();
  $('entry-language').value=entry.language_id||'';$('entry-language-notes').value=entry.language_notes||'';
  await languageEdit(entry);
};
const languageRenderBody=renderBody;
renderBody=function(entry){
  const lid=entry.language_id||entry.text_language_id||current?.text_language_id||activeLanguage;
  const m=JSON.parse(languageList.find(l=>l.id===lid)?.metadata||'{}');

  const ipa=validFont(m.ipa_font)?m.ipa_font:'IPAPANNEW',annotation=validFont(m.annotation_font)?m.annotation_font:'Junicode';
  return `<div class="language-body" style="${languageTypography(m)}">${languageRenderBody(entry)}</div>`;
};
const typographyPreview=preview;preview=function(){applyLanguageTypography($('editor'),JSON.parse(languageList.find(l=>l.id===($('entry-language').value||current?.text_language_id||activeLanguage))?.metadata||'{}'));return typographyPreview();};
$('entry-language').onchange=preview;
const languageSearch=search;
search=async function(){await languageSearch();decorateLanguages();};
function decorateLanguages(){
  for(const entry of items){if(entry.kind==='independent')continue;
    const card=$('entry-'+entry.id);if(!card||card.querySelector('.language-badge'))continue;
    const badge=document.createElement('span');badge.className='language-badge';
    badge.textContent=entry.language_name+(entry.language_id?' · 句子单独指定':'');
    card.querySelector('.entry-head>span').append(' · ',badge);
    if(entry.language_notes){const p=document.createElement('small');p.className='language-note';p.textContent='语言备注：'+entry.language_notes;card.querySelector('.language-body').after(p);}
  }
}
// The API wrapper adds the sentence-language filter without changing other callers.
const languageApi=api;
api=async function(path,body){
  if(!body&&path.startsWith('entries?')&&$('sentence-language').value)path+='&sentence_language='+encodeURIComponent($('sentence-language').value);
  return languageApi(path,body);
};
$('sentence-language').onchange=$('search').onclick;
const languageClearFilters=clearFilters;
clearFilters=function(){languageClearFilters();$('sentence-language').value='';};
const languageLoadTexts=loadTexts;
loadTexts=async function(){await languageLoadTexts();renderLanguage();};
// All-language view groups texts by language, keeping investigation folders separate.
const languageRenderFolders=renderFolders;
renderFolders=function(){
  if(activeLanguage!=='all'){languageRenderFolders();return;}
  $('texts').innerHTML=languageList.map(l=>`<details class="folder-group" open><summary>${esc(l.name)}</summary>${texts.filter(t=>t.language_id===l.id).map(t=>`<button class="nav" data-text="${esc(t.id)}">${esc(t.title)}<small>${esc(folders.find(f=>f.id===t.folder_id)?.name||'未分类')} · ${t.count} 条语料</small></button>`).join('')||'<small>暂无文本</small>'}</details>`).join('');
  document.querySelectorAll('[data-text]').forEach(b=>b.onclick=safe(async()=>{const t=texts.find(t=>t.id===b.dataset.text);await switchLanguage(t.language_id);await selectText(t.id);}));
};
// Selecting context from cross-language results enters the text's own workspace.
const languageSelectText=selectText;
selectText=async function(id,...options){
  if(id&&activeLanguage==='all'){
    const text=texts.find(t=>t.id===id);if(text){await switchLanguage(text.language_id);}
  }
  await languageSelectText(id,...options);renderLanguage();
};
try{activeLanguage=localStorage.getItem(projectStorageKey('corpus-language'))||'ordos'}catch{}
const corpusReady=(async()=>{await loadLanguages();await selectText('');await refreshUndo();})().catch(e=>{$('notice').textContent=e.message;});

function refreshLanguageIPA(){const v=variantStyle($('language-ipa-variant').value);Object.assign($('language-native_name').style,{fontFamily:cssFont($('language-ipa-font').value)+',serif',fontStyle:v.style,fontWeight:v.weight});}
$('language-ipa-font').addEventListener('change',refreshLanguageIPA);
