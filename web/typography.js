// Old local row preferences are immutable defaults until saved into a language.
let legacyLanguageTypography={};try{legacyLanguageTypography=JSON.parse(localStorage.getItem('corporium-typography')||'{}')||{};}catch{}
function variantStyle(value){return {style:['italic','bolditalic'].includes(value)?'italic':'normal',weight:['bold','bolditalic'].includes(value)?700:400};}
function cssFont(value){return ['serif','sans-serif'].includes(value)?value:JSON.stringify(value);}
function languageTypographySettings(m={}){
 const result={};
 for(const [row,font,defaultFont,defaultVariant] of [['ipa','ipa','IPAPANNEW','regular'],['morpheme','annotation','Junicode','italic'],['gloss','gloss','Junicode','regular'],['translation','translation','sans-serif','regular']]){
  const legacyFont=row==='gloss'&&validFont(legacyLanguageTypography.gloss)?legacyLanguageTypography.gloss:defaultFont;
  const legacyVariant=row==='gloss'&&legacyLanguageTypography.glossBold?'bold':defaultVariant;
  const scales=[.6,.7,.8,.9,1,1.1,1.2,1.3,1.5,2],legacyScale=row==='ipa'&&scales.includes(Number(legacyLanguageTypography.ipaScale))?Number(legacyLanguageTypography.ipaScale):1;
  result[font+'_font']=validFont(m[font+'_font'])?m[font+'_font']:legacyFont;
  result[row+'_variant']=['regular','italic','bold','bolditalic'].includes(m[row+'_variant'])?m[row+'_variant']:legacyVariant;
  result[row+'_scale']=scales.includes(m[row+'_scale'])?m[row+'_scale']:legacyScale;
 }
 return result;
}
function languageTypographyCSS(m){
 const v=languageTypographySettings(m),props=[];
 for(const [row,font,css] of [['ipa','ipa','ipa'],['morpheme','annotation','form'],['gloss','gloss','gloss'],['translation','translation','translation']]){
  const variant=variantStyle(v[row+'_variant']);
  props.push(`--${font}-font:${cssFont(v[font+'_font'])}`,`--${css}-style:${variant.style}`,`--${css}-weight:${variant.weight}`,`--${css==='form'?'form':row}-scale:${v[row+'_scale']}`);
 }
 return props.join(';');
}
function languageTypography(m){return esc(languageTypographyCSS(m));}
function applyLanguageTypography(element,m){
 const style=document.createElement('span').style;style.cssText=languageTypographyCSS(m);
 for(const property of style)element.style.setProperty(property,style.getPropertyValue(property));
}
const variantOptions='<option value="regular">Regular · 正体</option><option value="italic">Italic · 斜体</option><option value="bold">Bold · 粗体</option><option value="bolditalic">Bold Italic · 粗斜体</option>';
const languageTypographyRows=[['ipa','ipa','IPA'],['morpheme','annotation','语素'],['gloss','gloss','标注'],['translation','translation','自由翻译']];
const languageFontGrid=$('language-ipa-font').closest('.metadata-grid');languageFontGrid.classList.add('language-typography-grid');
for(const [row,font,label] of languageTypographyRows){
 let select=$('language-'+font+'-font');
 if(!select){const cell=document.createElement('label');cell.innerHTML=label+'默认字体<select id="language-'+font+'-font">'+fontChoices()+'</select>';languageFontGrid.append(cell);select=cell.querySelector('select');}
 select.classList.add('language-font');
 select.parentElement.insertAdjacentHTML('afterend',`<label>${label}字体变体<select id="language-${row}-variant">${variantOptions}</select></label><label>${label}行字号比例<select id="language-${row}-scale">${[60,70,80,90,100,110,120,130,150,200].map(n=>`<option value="${n/100}">${n}%</option>`).join('')}</select></label>`);
}
let typography={};try{typography=JSON.parse(localStorage.getItem('corporium-typography')||'{}')||{};}catch{}
function applyTypography(){
 const s=document.documentElement.style;
 document.documentElement.classList.toggle('custom-ui-font',validFont(typography.ui));
 for(const [key,fallback] of [['ui','Segoe UI']]){
  const font=validFont(typography[key])?typography[key]:fallback;s.setProperty('--'+key+'-font',cssFont(font));
 }
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
makeDialog('typography-dialog','<h2>全局设置</h2><form id="typography-form"><div id="global-font-settings"><p>界面字体适用于所有语言，保存在本机。例句各行的字体、变体和字号比例在“语言选项 → 编辑语言信息”中分别设置。</p><label>界面字体<select id="global-ui-font" class="global-font"></select></label><label>界面字体变体<select id="global-ui-variant">'+variantOptions+'</select></label></div><button class="primary" type="submit">保存设置</button></form>');
mountGlobalSettingsSection($('global-font-settings'),'fonts','字体设置');
$('typography-form').addEventListener('invalid',e=>{const section=e.target.closest('.global-settings-section');if(section)section.open=true;},true);
const typographyButton=document.createElement('button');typographyButton.id='global-settings';typographyButton.textContent='全局设置';document.querySelector('.theme-panel').append(typographyButton);
typographyButton.onclick=()=>{
 const select=$('global-ui-font');select.innerHTML='<option value="">默认字体</option>'+fontChoices();selectFont(select,typography.ui||'');
 $('global-ui-variant').value=typography.uiVariant||'regular';$('typography-dialog').showModal();
};
$('typography-form').onsubmit=e=>{e.preventDefault();typography={...typography,ui:$('global-ui-font').value,uiVariant:$('global-ui-variant').value};try{localStorage.setItem('corporium-typography',JSON.stringify(typography));}catch{}applyTypography();$('typography-dialog').close();};

$('typography-form').querySelector('button[type=submit]').insertAdjacentHTML('beforebegin','<div id="global-backup-settings"><label>保留最近的自动备份<select id="auto-backup-limit">'+[5,10,20,30].map(n=>`<option value="${n}">${n} 份</option>`).join('')+'</select></label><p>适用于当前工作空间。保存后立即清理超出上限的旧自动备份；之后每次生成自动备份也会清理。包含旧版自动备份及升级、打开项目时的快照。“管理 → 导出完整备份”生成的手动备份不限数量，不参与清理。</p><p id="auto-backup-status" role="status"></p><p id="auto-backup-error" role="alert"></p></div>');
const backupSettingsSection=mountGlobalSettingsSection($('global-backup-settings'),'backup','自动备份');
const backupSettingsOpen=typographyButton.onclick,backupSettingsSave=$('typography-form').onsubmit;
const backupSettingsSubmit=$('typography-form').querySelector('button[type="submit"]');
typographyButton.onclick=async()=>{backupSettingsOpen();backupSettingsSubmit.disabled=true;$('auto-backup-limit').disabled=true;$('auto-backup-error').textContent='';$('auto-backup-status').textContent='正在读取自动备份设置…';try{const p=await api('backup-policy');$('auto-backup-limit').value=p.limit;$('auto-backup-status').textContent=`当前 ${p.count} 份自动备份，合计 ${(p.bytes/1048576).toFixed(1)} MB。${p.count>p.limit?'部分旧备份尚未清理，请检查文件是否被占用。':''}`;$('auto-backup-limit').disabled=false;backupSettingsSubmit.disabled=false;}catch(e){backupSettingsSection.open=true;$('auto-backup-error').textContent=e.message;}};
$('typography-form').onsubmit=async e=>{e.preventDefault();backupSettingsSubmit.disabled=true;try{const p=await api('backup-policy',{limit:Number($('auto-backup-limit').value)});if(p.count>p.limit){backupSettingsSection.open=true;$('auto-backup-error').textContent='设置已保存，但部分旧备份被占用，暂时无法清理；下次将继续尝试。';return;}backupSettingsSave(e);}catch(error){backupSettingsSection.open=true;$('auto-backup-error').textContent=error.message;}finally{backupSettingsSubmit.disabled=false;}};

$('language-ipa-variant').addEventListener('change',refreshLanguageIPA);
