// Old local row preferences are immutable defaults until saved into a language.
let legacyLanguageTypography={};try{legacyLanguageTypography=JSON.parse(localStorage.getItem('corporium-typography')||'{}')||{};}catch{}
function variantStyle(value){return {style:['italic','bolditalic'].includes(value)?'italic':'normal',weight:['bold','bolditalic'].includes(value)?700:400};}
function cssFont(value){return value==='@global'?'var(--global-font-stack,var(--default-ui-font))':['serif','sans-serif'].includes(value)?value:JSON.stringify(value);}
function rowFontCSS(value){return value==='@global'?cssFont(value):cssFont(value)+',var(--global-font-stack,var(--default-ui-font))';}
function clipboardFontStack(value){
 const ids=value==='@global'?savedFontStack(typography):[value,...savedFontStack(typography)];
 const names=ids.map(id=>systemFontName(id)||fontSources[id]?.name||typography.uiFontNames?.[id]||(!/^localfont-/.test(id)&&validFont(id)?id:null)).filter(Boolean);
 return [...new Set([...names,'sans-serif'])];
}
function languageTypographySettings(m={}){
 const result={};
 for(const [row,font,defaultFont,defaultVariant] of [['ipa','ipa','IPAPANNEW','regular'],['morpheme','annotation','Junicode','italic'],['gloss','gloss','Junicode','regular'],['translation','translation','sans-serif','regular']]){
  const legacyFont=row==='gloss'&&validFont(legacyLanguageTypography.gloss)?legacyLanguageTypography.gloss:defaultFont;
  const legacyVariant=row==='gloss'&&legacyLanguageTypography.glossBold?'bold':defaultVariant;
  const scales=[.6,.7,.8,.9,1,1.1,1.2,1.3,1.5,2],legacyScale=row==='ipa'&&scales.includes(Number(legacyLanguageTypography.ipaScale))?Number(legacyLanguageTypography.ipaScale):1;
  result[font+'_font']=m[font+'_font']==='@global'||validFont(m[font+'_font'])?m[font+'_font']:legacyFont;
  result[row+'_variant']=['regular','italic','bold','bolditalic'].includes(m[row+'_variant'])?m[row+'_variant']:legacyVariant;
  result[row+'_scale']=scales.includes(m[row+'_scale'])?m[row+'_scale']:legacyScale;
 }
 return result;
}
function languageTypographyCSS(m){
 const v=languageTypographySettings(m),props=[];
 for(const [row,font,css] of [['ipa','ipa','ipa'],['morpheme','annotation','form'],['gloss','gloss','gloss'],['translation','translation','translation']]){
  const variant=variantStyle(v[row+'_variant']);
  props.push(`--${font}-font:${rowFontCSS(v[font+'_font'])}`,`--${css}-style:${variant.style}`,`--${css}-weight:${variant.weight}`,`--${css==='form'?'form':row}-scale:${v[row+'_scale']}`);
 }
 return props.join(';');
}
function languageTypography(m){return esc(languageTypographyCSS(m));}
function applyLanguageTypography(element,m){
 const style=document.createElement('span').style;style.cssText=languageTypographyCSS(m);
 for(const property of style)element.style.setProperty(property,style.getPropertyValue(property));
}
const variantOptions=(globalThis.CorporiumI18n?.f("a83800db0c9c04",()=>[])??'<option value="regular">Regular · 正体</option><option value="italic">Italic · 斜体</option><option value="bold">Bold · 粗体</option><option value="bolditalic">Bold Italic · 粗斜体</option>');
const languageTypographyRows=[['ipa','ipa','IPA'],['morpheme','annotation',(globalThis.CorporiumI18n?.f("cd8e68c292f4ec",()=>[])??'语素')],['gloss','gloss',(globalThis.CorporiumI18n?.f("7cf3454e9cc5e2",()=>[])??'标注')],['translation','translation',(globalThis.CorporiumI18n?.f("fb0a1b8ddd3a34",()=>[])??'自由翻译')]];
const languageFontGrid=$('language-ipa-font').closest('.metadata-grid');languageFontGrid.classList.add('language-typography-grid');
for(const [row,font,label] of languageTypographyRows){
 let select=$('language-'+font+'-font');
 if(!select){const cell=document.createElement('label');cell.innerHTML=(globalThis.CorporiumI18n?.f("7adddf9c12cc6d",()=>[label,font,fontChoices()])??label+'默认字体<select id="language-'+font+'-font">'+fontChoices()+'</select>');languageFontGrid.append(cell);select=cell.querySelector('select');}
 select.classList.add('language-font');
 select.innerHTML=rowFontChoices();
 select.parentElement.insertAdjacentHTML('afterend',(globalThis.CorporiumI18n?.f("2463c8029a855a",()=>[label,row,variantOptions,label,row,[60,70,80,90,100,110,120,130,150,200].map(n=>`<option value="${n/100}">${n}%</option>`).join('')])??`<label>${label}字体变体<select id="language-${row}-variant">${variantOptions}</select></label><label>${label}行字号比例<select id="language-${row}-scale">${[60,70,80,90,100,110,120,130,150,200].map(n=>`<option value="${n/100}">${n}%</option>`).join('')}</select></label>`));
}
const rowFontPreview=document.createElement('div');rowFontPreview.className='language-font-preview';
rowFontPreview.innerHTML=`<p class="language-font-help">${fontUI('选择“跟随全局字体”，或为此行指定优先字体；缺字时继续使用全局回退。变体和字号比例分别生效。','Follow global fonts, or choose a preferred font for this row. Missing characters fall back to the global order. Variant and size remain independent.')}</p>`;
languageFontGrid.append(rowFontPreview);
function refreshLanguageFontPreview(){
 const metadata={};for(const [row,font] of languageTypographyRows){metadata[font+'_font']=$('language-'+font+'-font').value;metadata[row+'_variant']=$('language-'+row+'-variant').value;metadata[row+'_scale']=Number($('language-'+row+'-scale').value);}
 const samples=['pʰatʰeːl ɐ̃ ə̥ ʃ ŋ ʔ','ama-la=ni','mother-PST=TOP',fontUI('她和母亲说话。','She speaks with her mother.')];
 rowFontPreview.querySelectorAll('[data-font-row-preview]').forEach(el=>el.remove());
 for(const [i,[row,font,label]] of languageTypographyRows.entries()){
  const p=document.createElement('p');p.dataset.fontRowPreview=row;const caption=document.createElement('small');caption.textContent=label;const sample=document.createElement('span');sample.textContent=samples[i];
  const v=variantStyle(metadata[row+'_variant']);Object.assign(sample.style,{fontFamily:rowFontCSS(metadata[font+'_font']),fontStyle:v.style,fontWeight:v.weight,fontSize:metadata[row+'_scale']+'em'});p.append(caption,sample);rowFontPreview.append(p);
 }
}
languageFontGrid.addEventListener('change',refreshLanguageFontPreview);
window.addEventListener('corporium-fonts-changed',()=>{if($('language-dialog').open)refreshLanguageFontPreview();});
let typography={};try{typography=JSON.parse(localStorage.getItem('corporium-typography')||'{}')||{};}catch{}
function applyTypography(){
 const s=document.documentElement.style;
 document.documentElement.classList.toggle('custom-ui-font',Array.isArray(typography.uiFonts)||validFont(typography.ui));
 s.setProperty('--global-font-stack',fontStackCSS(savedFontStack(typography)));
 s.setProperty('--ui-font','var(--global-font-stack)');
 const v=variantStyle(typography.uiVariant);s.setProperty('--ui-style',v.style);s.setProperty('--ui-weight',v.weight);

}
applyTypography();
function mountGlobalSettingsSection(content,key,title){
 const section=document.createElement('details'),summary=document.createElement('summary');
 section.id='global-settings-'+key;section.className='global-settings-section';summary.textContent=title;
 const storageKey='corporium-global-settings-section-'+key;
 try{section.open=localStorage.getItem(storageKey)==='true';}catch{}
 content.classList.add('global-settings-body');content.before(section);section.append(summary,content);
 section.addEventListener('toggle',()=>{try{localStorage.setItem(storageKey,String(section.open));}catch{}});
 return section;
}
makeDialog('typography-dialog',(globalThis.CorporiumI18n?.f("9ef2f3f3f5ee28",()=>[variantOptions])??'<h2>全局设置</h2><form id="typography-form"><div id="global-font-settings"><p>界面字体适用于所有语言，保存在本机。例句各行的字体、变体和字号比例在“语言选项 → 编辑语言信息”中分别设置。</p><label>界面字体<select id="global-ui-font" class="global-font"></select></label><label>界面字体变体<select id="global-ui-variant">'+variantOptions+'</select></label></div><button class="primary" type="submit">保存设置</button></form>'));
mountGlobalSettingsSection($('global-font-settings'),'fonts',(globalThis.CorporiumI18n?.f("ac474ec1030210",()=>[])??'字体设置'));
const globalFontEditor=createFontStackEditor($('global-font-settings'));
$('typography-form').addEventListener('corporium-settings-discard',()=>globalFontEditor.load(typography));
$('typography-form').addEventListener('invalid',e=>{const section=e.target.closest('.global-settings-section');if(section)section.open=true;},true);
const typographyButton=document.createElement('button');typographyButton.id='global-settings';typographyButton.textContent=(globalThis.CorporiumI18n?.f("45d1c47c2347d9",()=>[])??'全局设置');document.querySelector('.theme-panel').append(typographyButton);
// The management center mounts this same form in place. Saving reports an
// explicit result so palette/language handlers do not depend on a modal closing.
const globalSettingsState={inline:false,loaded:false,loading:null,saving:false,baseline:'',touched:false,generation:0};
typographyButton.onclick=()=>{
 globalFontEditor.load(typography);if(!globalSettingsState.inline)$('typography-dialog').showModal();
};
$('typography-form').onsubmit=e=>{e.preventDefault();typography={...typography,...globalFontEditor.settings()};try{localStorage.setItem('corporium-typography',JSON.stringify(typography));}catch{}applyTypography();if($('typography-dialog').open)$('typography-dialog').close();return {saved:true};};

$('typography-form').querySelector('button[type=submit]').insertAdjacentHTML('beforebegin',(globalThis.CorporiumI18n?.f("690a3d1f4d0d8f",()=>[[5,10,20,30].map(n=>(globalThis.CorporiumI18n?.f("baef614a384f86",()=>[n,n])??`<option value="${n}">${n} 份</option>`)).join('')])??'<div id="global-backup-settings"><label>保留最近的自动备份<select id="auto-backup-limit">'+[5,10,20,30].map(n=>`<option value="${n}">${n} 份</option>`).join('')+'</select></label><p>适用于当前工作空间。保存后立即清理超出上限的旧自动备份；之后每次生成自动备份也会清理。包含旧版自动备份及升级、打开项目时的快照。“管理 → 导出完整备份”生成的手动备份不限数量，不参与清理。</p><p id="auto-backup-status" role="status"></p><p id="auto-backup-error" role="alert"></p></div>'));
const backupSettingsSection=mountGlobalSettingsSection($('global-backup-settings'),'backup',(globalThis.CorporiumI18n?.f("1a6a73e6515985",()=>[])??'自动备份'));
const backupSettingsOpen=typographyButton.onclick,backupSettingsSave=$('typography-form').onsubmit;
const backupSettingsSubmit=$('typography-form').querySelector('button[type="submit"]');
typographyButton.onclick=async()=>{backupSettingsOpen();backupSettingsSubmit.disabled=true;$('auto-backup-limit').disabled=true;$('auto-backup-error').textContent='';$('auto-backup-status').textContent=(globalThis.CorporiumI18n?.f("628f44b869cc9b",()=>[])??'正在读取自动备份设置…');try{const p=await api('backup-policy');$('auto-backup-limit').value=p.limit;$('auto-backup-status').textContent=(globalThis.CorporiumI18n?.f("0e867af144f810",()=>[p.count,(p.bytes/1048576).toFixed(1),p.count>p.limit?(globalThis.CorporiumI18n?.f("7aacc63a029539",()=>[])??'部分旧备份尚未清理，请检查文件是否被占用。'):''])??`当前 ${p.count} 份自动备份，合计 ${(p.bytes/1048576).toFixed(1)} MB。${p.count>p.limit?'部分旧备份尚未清理，请检查文件是否被占用。':''}`);$('auto-backup-limit').disabled=false;backupSettingsSubmit.disabled=false;}catch(e){backupSettingsSection.open=true;$('auto-backup-error').textContent=e.message;}};
$('typography-form').onsubmit=async e=>{e.preventDefault();backupSettingsSubmit.disabled=true;try{const p=await api('backup-policy',{limit:Number($('auto-backup-limit').value)});if(p.count>p.limit){backupSettingsSection.open=true;$('auto-backup-error').textContent=(globalThis.CorporiumI18n?.f("5831c6aa0af7a7",()=>[])??'设置已保存，但部分旧备份被占用，暂时无法清理；下次将继续尝试。');return {saved:false};}return backupSettingsSave(e);}catch(error){backupSettingsSection.open=true;$('auto-backup-error').textContent=error.message;return {saved:false};}finally{backupSettingsSubmit.disabled=false;}};

window.CorporiumGlobalSettings={
 mount(host){
  const form=$('typography-form');globalSettingsState.inline=true;host.append(form);typographyButton.hidden=true;
  for(const outlet of form.querySelectorAll('[role=alert],[id$="-error"]'))outlet.dataset.inlineMessage='true';
  const actions=document.createElement('div');actions.className='settings-form-actions';
  const submit=form.querySelector('button[type=submit]'),cancel=document.createElement('button'),status=document.createElement('span');
  cancel.type='button';cancel.textContent=globalThis.CorporiumI18n?.ui('取消修改','Discard changes')??'取消修改';
  status.id='global-settings-status';status.setAttribute('role','status');status.setAttribute('aria-live','polite');
  submit.before(actions);actions.append(submit,cancel,status);
  const snapshot=()=>JSON.stringify([...form.querySelectorAll('input,select,textarea')].filter(el=>!el.closest('#morph-color-settings')&&!el.hasAttribute('data-settings-transient')).map(el=>[el.id,el.type==='checkbox'||el.type==='radio'?el.checked:el.value]));
  const update=()=>{if(!globalSettingsState.loading&&!globalSettingsState.saving){globalSettingsState.touched=snapshot()!==globalSettingsState.baseline;status.textContent=this.dirty()?(globalThis.CorporiumI18n?.ui('有未保存的设置','Unsaved settings')??'有未保存的设置'):'';}};
  form.addEventListener('input',update);form.addEventListener('change',update);
  form.addEventListener('click',()=>requestAnimationFrame(update));
  this.snapshot=snapshot;
  const save=form.onsubmit;
  form.onsubmit=async event=>{
   event.preventDefault();if(globalSettingsState.saving||globalSettingsState.loading)return {saved:false};
   const wasInert=form.inert;globalSettingsState.saving=true;cancel.disabled=true;form.inert=true;form.setAttribute('aria-busy','true');
   try{
    const result=await save.call(form,event);
    if(result?.saved){
     globalSettingsState.loaded=false;await this.load(true);
     status.textContent=globalThis.CorporiumI18n?.ui('设置已保存','Settings saved')??'设置已保存';
    }
    return result;
   }finally{globalSettingsState.saving=false;cancel.disabled=false;form.inert=wasInert;form.removeAttribute('aria-busy');}
  };
  cancel.onclick=async()=>{if(globalSettingsState.saving)return;this.discard();await this.load();status.textContent=globalThis.CorporiumI18n?.ui('已恢复保存的设置','Saved settings restored')??'已恢复保存的设置';};
 },
 async load(force=false){
  if(globalSettingsState.loading)return globalSettingsState.loading;
  if(globalSettingsState.loaded&&!force)return;
  const generation=globalSettingsState.generation,form=$('typography-form'),wasInert=form.inert;form.inert=true;
  globalSettingsState.loading=Promise.resolve().then(()=>typographyButton.onclick()).then(()=>{
   if(generation!==globalSettingsState.generation)return;
   globalSettingsState.loaded=!backupSettingsSubmit.disabled;
   if(globalSettingsState.loaded){globalSettingsState.baseline=this.snapshot?.()||'';globalSettingsState.touched=false;}
  }).finally(()=>{globalSettingsState.loading=null;form.inert=wasInert;});
  return globalSettingsState.loading;
 },
 dirty(){return globalSettingsState.loaded&&(globalSettingsState.touched||window.corporiumMorphPaletteDirty?.()===true||[...$('morph-color-settings').querySelectorAll('[data-color-hex]:enabled')].some(input=>!input.validity.valid));},
 busy(){return globalSettingsState.saving||!!globalSettingsState.loading;},
 discard(){
  if(globalSettingsState.saving)return;
  globalSettingsState.generation++;globalSettingsState.loaded=false;globalSettingsState.baseline='';globalSettingsState.touched=false;
  $('typography-form').dispatchEvent(new Event('corporium-settings-discard'));
 },
 open(){typographyButton.click();}
};
window.corporiumGlobalSettingsDirty=()=>window.CorporiumGlobalSettings.dirty()||globalSettingsState.saving;

$('language-ipa-variant').addEventListener('change',refreshLanguageIPA);
