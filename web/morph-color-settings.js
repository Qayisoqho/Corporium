// Display preferences only: semantic roles and shared grammatical tag colors stay intact.
const morphPaletteRoles={base:(globalThis.CorporiumI18n?.f("21aa5a5ae2792d",()=>[])??'普通语素'),affix:(globalThis.CorporiumI18n?.f("bbbdee3851b6b1",()=>[])??'词缀（前缀／后缀等）'),clitic:(globalThis.CorporiumI18n?.f("4d04b2a24c3c7f",()=>[])??'附着成分'),infix:(globalThis.CorporiumI18n?.f("1f525b2be473dd",()=>[])??'中缀'),circumfix:(globalThis.CorporiumI18n?.f("c50027a6b5b134",()=>[])??'环缀'),connector:(globalThis.CorporiumI18n?.f("47982aa4bea1a2",()=>[])??'连接成分'),multipart:(globalThis.CorporiumI18n?.f("683a7a80a9ceab",()=>[])??'其他多部分语素'),reduplication:(globalThis.CorporiumI18n?.f("ce6b5d53c8824b",()=>[])??'重叠形态')};
const morphPaletteThemes={docoid:'Docoid',dawoid:'DAWoid',ivory:(globalThis.CorporiumI18n?.f("6b637a8b4f0465",()=>[])??'暖白 · 墨蓝'),night:(globalThis.CorporiumI18n?.f("82a4e05bc596c9",()=>[])??'夜间 · 星墨'),forest:(globalThis.CorporiumI18n?.f("239c56c03bef6c",()=>[])??'经典 · 苔绿')};
const morphPaletteDefaults={base:'--ipa',affix:'--gold',clitic:'--morph-clitic',infix:'--morph-infix',circumfix:'--morph-circumfix',connector:'--morph-connector',multipart:'--morph-multipart',reduplication:'--morph-reduplication'};
function normalizeMorphPalette(value){
 const source=value&&typeof value==='object'&&!Array.isArray(value)?value:{},colors={};
 for(const theme of Object.keys(morphPaletteThemes)){colors[theme]={};for(const role of Object.keys(morphPaletteRoles)){const color=source.colors?.[theme]?.[role];if(typeof color==='string'&&/^#[\da-f]{6}$/i.test(color))colors[theme][role]=color.toLowerCase();}}
 return {enabled:source.enabled!==false,roles:Object.fromEntries(Object.keys(morphPaletteRoles).map(role=>[role,source.roles?.[role]!==false])),colors};
}
function morphPaletteValues(value,theme){
 const p=normalizeMorphPalette(value);return Object.fromEntries(Object.keys(morphPaletteRoles).map(role=>[role,!p.enabled||!p.roles[role]?'var(--ipa,var(--ink))':p.colors[theme]?.[role]||'var('+morphPaletteDefaults[role]+',var(--ink))']));
}
(()=>{
 const key='corporium-morph-palette',root=document.documentElement,dialog=$('typography-dialog'),form=$('typography-form');
 const theme=()=>Object.hasOwn(morphPaletteThemes,root.dataset.theme)?root.dataset.theme:'docoid';
 const read=()=>{try{return normalizeMorphPalette(JSON.parse(localStorage.getItem(key)||'{}'));}catch{return normalizeMorphPalette({});}};
 let saved=read(),draft=null;
 function apply(value){root.dataset.morphColors=value.enabled?'on':'off';for(const [role,color] of Object.entries(morphPaletteValues(value,theme())))root.style.setProperty('--morph-display-'+role,color);}
 const area=document.createElement('fieldset');area.id='morph-color-settings';area.innerHTML=(globalThis.CorporiumI18n?.f("bdb4777ac83d06",()=>[Object.keys(morphPaletteRoles).map(role=>'<span class="morph-tone morph-tone-'+role+'">'+esc(morphPaletteRoles[role])+'</span>').join('')])??'<legend>当前皮肤 <small id="morph-color-theme"></small></legend><label class="morph-color-master"><input id="morph-colors-enabled" type="checkbox">启用成分配色</label><p class="morph-color-hint">关闭总开关或某一类型后，相关成分使用当前皮肤的 IPA 颜色。重叠形态只标记已关联的重叠部分，基底保持原配色。例句与右面板同步，语法标签列表保持原色。</p><div id="morph-color-rows"></div><div class="morph-color-preview" aria-label="成分颜色预览">'+Object.keys(morphPaletteRoles).map(role=>'<span class="morph-tone morph-tone-'+role+'">'+esc(morphPaletteRoles[role])+'</span>').join('')+'</div><div class="morph-color-bottom"><small>适用于所有语言；颜色按皮肤记忆，开关保存在本机。</small><button type="button" id="morph-colors-reset">恢复本皮肤默认色</button></div>');
 form.querySelector('button[type=submit]').before(area);
 const section=mountGlobalSettingsSection(area,'colors',(globalThis.CorporiumI18n?.f("c197e9d316c571",()=>[])??'成分配色'));$('global-settings-backup').before(section);
 function defaultColor(role){const value=getComputedStyle(root).getPropertyValue(morphPaletteDefaults[role]).trim();return /^#[\da-f]{6}$/i.test(value)?value:'#243d39';}
 function refreshControls(){
  if(!draft)return;$('morph-colors-enabled').checked=draft.enabled;
  for(const row of area.querySelectorAll('[data-color-role]')){const role=row.dataset.colorRole;row.querySelector('[data-role-enabled]').checked=draft.roles[role];for(const el of row.querySelectorAll('[data-color],[data-color-hex],[data-color-reset]'))el.disabled=!draft.enabled||!draft.roles[role];}
 }
 function render(){
  if(!draft)return;$('morph-color-theme').textContent=morphPaletteThemes[theme()];
  $('morph-color-rows').innerHTML=Object.entries(morphPaletteRoles).map(([role,label])=>{const color=draft.colors[theme()][role]||defaultColor(role);return (globalThis.CorporiumI18n?.f("3497c5f7fd8830",()=>[role,label,esc(label),color,label,color,label,label])??'<div class="morph-color-row" data-color-role="'+role+'"><label><input type="checkbox" data-role-enabled aria-label="为'+label+'启用配色">'+esc(label)+'</label><input type="color" data-color value="'+color+'" aria-label="'+label+'颜色"><input data-color-hex value="'+color+'" aria-label="'+label+'颜色代码" pattern="#[0-9a-fA-F]{6}" maxlength="7" required spellcheck="false"><button type="button" data-color-reset aria-label="恢复'+label+'默认色" title="恢复该项默认色">↶</button></div>');}).join('');refreshControls();
 }
 area.addEventListener('input',e=>{
  if(!draft)return;const row=e.target.closest('[data-color-role]');
  if(e.target.id==='morph-colors-enabled')draft.enabled=e.target.checked;
  else if(row){const role=row.dataset.colorRole;if(e.target.matches('[data-role-enabled]'))draft.roles[role]=e.target.checked;else if(e.target.matches('[data-color],[data-color-hex]')){const color=e.target.value;if(!/^#[\da-f]{6}$/i.test(color))return;draft.colors[theme()][role]=color.toLowerCase();row.querySelector('[data-color]').value=color;row.querySelector('[data-color-hex]').value=color.toLowerCase();}}
  refreshControls();apply(draft);
 });
 area.addEventListener('click',e=>{if(!draft)return;const reset=e.target.closest('[data-color-reset]');if(reset){delete draft.colors[theme()][reset.closest('[data-color-role]').dataset.colorRole];render();apply(draft);}});
 $('morph-colors-reset').onclick=()=>{if(draft){draft.colors[theme()]={};render();apply(draft);}};
 const open=typographyButton.onclick;typographyButton.onclick=async()=>{draft=normalizeMorphPalette(saved);render();return open();};
 const save=form.onsubmit;form.onsubmit=async e=>{const candidate=normalizeMorphPalette(draft||saved);await save(e);if(!dialog.open){saved=candidate;try{localStorage.setItem(key,JSON.stringify(saved));}catch{}draft=null;apply(saved);}};
 dialog.addEventListener('close',()=>{draft=null;apply(saved);});
 new MutationObserver(()=>{apply(draft||saved);if(draft)render();}).observe(root,{attributes:true,attributeFilter:['data-theme']});
 window.addEventListener('storage',e=>{if(e.key===key||e.key===null){saved=read();if(!draft)apply(saved);}});
 apply(saved);
})();
