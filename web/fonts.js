const availableFonts={IPAPANNEW:'IPAPANNEW',Junicode:'Junicode','STIX Two Text':'STIX Two Text','Microsoft JhengHei':(globalThis.CorporiumI18n?.ui('微软正黑体（系统）','Microsoft JhengHei (system)')??'Microsoft JhengHei'),'Noto Sans':'Noto Sans','Source Han Sans SC':'Source Han Sans SC',SimSun:(globalThis.CorporiumI18n?.f("9e54fdb4964600",()=>[])??'宋体（系统）'),KaiTi:(globalThis.CorporiumI18n?.f("c7cfccb25d8707",()=>[])??'楷体（系统）'),'Microsoft YaHei':(globalThis.CorporiumI18n?.f("5737ed3ae0a260",()=>[])??'微软雅黑（系统）'),serif:(globalThis.CorporiumI18n?.f("6f02d7ddff1634",()=>[])??'默认衬线字体'),'sans-serif':(globalThis.CorporiumI18n?.f("71951def7b2688",()=>[])??'默认无衬线字体')};
const fontUI=(zh,en)=>globalThis.CorporiumI18n?.ui(zh,en)??zh;
function systemFontName(value){
  if(typeof value!=='string'||!/^systemfont-(?:[0-9a-f]{2}){1,1024}$/.test(value))return '';
  try{
    const name=decodeURIComponent(value.slice(11).replace(/../g,'%$&'));
    return name.length<=256&&name.trim()===name&&!/^@|[\u0000-\u001f\u007f-\u009f]/.test(name)?name:'';
  }catch{return '';}
}
const validFont=value=>typeof value==='string'&&(Object.hasOwn(availableFonts,value)||/^localfont-[0-9a-f]{24}$/.test(value)||!!systemFontName(value));
const defaultFontStack=['STIX Two Text','Microsoft JhengHei'];
function normalizeFontStack(values){
  const result=Array.isArray(values)?[...new Set(values.filter(validFont))].slice(0,32):[];
  return result.length?result:[...defaultFontStack];
}
function savedFontStack(settings={}){
  const stack=normalizeFontStack(Array.isArray(settings?.uiFonts)?settings.uiFonts:validFont(settings?.ui)?[settings.ui]:defaultFontStack);
  // The previous exact default follows this release's default. Custom chains
  // and explicitly selected annotation fonts keep their original choices.
  return stack.length===2&&stack[0]==='Noto Sans'&&stack[1]==='Source Han Sans SC'?[...defaultFontStack]:stack;
}
function fontStackCSS(values){
  const stack=normalizeFontStack(values);if(!stack.includes('sans-serif'))stack.push('sans-serif');
  return stack.map(value=>['serif','sans-serif'].includes(value)?value:JSON.stringify(value)).join(',');
}
const fontSources=Object.fromEntries(Object.keys(availableFonts).map(id=>[id,{id,name:id,source:['serif','sans-serif'].includes(id)?'generic':['SimSun','KaiTi','Microsoft YaHei','Microsoft JhengHei','Noto Sans','Source Han Sans SC'].includes(id)?'preset':'bundled',aliases:[]}]));
function fontSourceLabel(source){return {bundled:fontUI('随附','Bundled'),system:fontUI('系统','System'),folder:fontUI('font 文件夹','font folder'),generic:fontUI('通用','Generic'),preset:fontUI('系统预设','System preset')}[source]||fontUI('未检测到','Unavailable');}
function fontLabel(id){return fontSources[id]?.name||systemFontName(id)||availableFonts[id]||fontUI('未检测到的字体（保留设置）','Unavailable font (selection kept)');}
const fontChoices=()=>Object.entries(availableFonts).map(([id,name])=>`<option value="${esc(id)}">${esc(name)}</option>`).join('');
const rowFontChoices=()=>`<option value="@global">${esc(fontUI('跟随全局字体','Follow global fonts'))}</option>`+fontChoices();
const fontSelects='#language-ipa-font,#language-annotation-font,.language-font,#writing-font,#layer-font,.orthography-font,.global-font';
const parkedFontOptions=new WeakMap();
function restoreFontOptions(select){
  const cached=parkedFontOptions.get(select);if(!cached)return;
  parkedFontOptions.delete(select);
  // A renderer may already have supplied a new catalog. Never restore stale
  // nodes over those options, or overwrite a newer selection.
  if(select.options.length!==1||select.options[0]!==cached.kept)return;
  const value=select.value;select.replaceChildren(...cached.options);select.value=value;
}
function parkFontOptions(select){
  if(select.options.length<2||select.ownerDocument?.activeElement===select)return;
  const options=[...select.options],kept=options.find(option=>option.selected)||options[0],value=select.value;
  select.replaceChildren(kept);select.value=value;parkedFontOptions.set(select,{options,kept});
}
function selectFont(select,value){
  restoreFontOptions(select);
  if(validFont(value)&&![...select.options].some(o=>o.value===value))select.add(new Option(fontLabel(value)+' · '+fontUI('未检测到，保留设置','Unavailable, selection kept'),value));
  select.value=value;
  parkFontOptions(select);
}
function fontFaceCSS(data){
  const face=(family,f)=>`@font-face{font-family:"${family}";src:url("${f.url}");font-style:${f.style};font-weight:${f.weight};font-display:swap}\n`;
  const quote=value=>JSON.stringify(value).replace(/[\u0000-\u001f\u007f]/g,c=>'\\'+c.charCodeAt(0).toString(16)+' ');
  const stretches=[100,50,62.5,75,87.5,100,112.5,125,150,200];
  const system=(data.system?.families||[]).map(f=>f.faces.map(v=>`@font-face{font-family:${quote(f.id)};src:${v.local.map(n=>'local('+quote(n)+')').join(',')};font-style:${v.style};font-weight:${v.weight};font-stretch:${stretches[v.stretch]||100}%;font-display:swap}\n`).join('')).join('');
  return data.families.map(f=>f.faces.map(v=>face(f.id,v)).join('')).join('')+(data.builtins||[]).filter(f=>!f.bundled_ui).map(f=>face(f.family,f)).join('')+system;
}
let fontScanRequest=0,fontCatalogKey='',fontsStarted=false;
async function scanFonts(refresh=false){
  const request=++fontScanRequest;
  const data=await api('fonts'+(refresh?'?refresh=true':''));
  if(request!==fontScanRequest)return;
  const key=JSON.stringify(data);if(key===fontCatalogKey)return;
  for(const id of Object.keys(availableFonts))if(/^(localfont|systemfont)-/.test(id)){delete availableFonts[id];delete fontSources[id];}
  for(const family of data.families){
    availableFonts[family.id]=(globalThis.CorporiumI18n?.f("35d301e1dea4a6",()=>[family.name])??family.name+'（font 文件夹）');
    fontSources[family.id]={...family,source:'folder'};
  }
  for(const family of data.system?.families||[]){availableFonts[family.id]=family.name+' · '+fontSourceLabel('system');fontSources[family.id]={...family,source:'system'};}
  let sheet=$('local-font-styles');if(!sheet){sheet=document.createElement('style');sheet.id='local-font-styles';document.head.append(sheet);}sheet.textContent=fontFaceCSS(data);fontCatalogKey=key;
  for(const select of document.querySelectorAll(fontSelects)){
    const value=select.value;select.innerHTML=select.classList.contains('language-font')||select.id==='layer-font'?rowFontChoices():(select.classList.contains('global-font')?'<option value=""></option>':'')+fontChoices();selectFont(select,value);
  }
  $('font-scan-status').textContent=fontUI(`系统 ${data.system?.families.length||0} 个字体家族；font 文件夹 ${data.families.length} 个家族、${data.file_count} 个文件。`,`System: ${data.system?.families.length||0} families; font folder: ${data.families.length} families, ${data.file_count} files.`)+(data.system?.status==='unsupported'?' '+fontUI('系统字体读取目前支持 Windows。','System font discovery currently supports Windows.'):'');
  $('font-scan-errors').textContent=[...data.errors.map(e=>e.file+'：'+e.error),data.system?.error?fontUI('系统字体读取失败，可重试：','System font discovery failed; retry: ')+data.system.error:''].filter(Boolean).join('\n');
  $('font-scan-list').textContent=data.families.map(f=>(globalThis.CorporiumI18n?.f("f73db205a583f1",()=>[f.name,f.faces.length])??f.name+' · '+f.faces.length+' 个字形')).join('\n');
  renderLanguage();
  window.dispatchEvent?.(new Event('corporium-fonts-changed'));
}
let fontsReady;
window.corporiumFontsReady=new Promise(resolve=>{fontsReady=resolve;});
window.addEventListener('DOMContentLoaded',()=>{
  const panel=document.createElement('details');panel.className='font-panel';
  panel.innerHTML=`<summary>${fontUI('字体来源与扫描','Font sources and discovery')}</summary><p>${fontUI('可选择随附字体、本机系统字体及 font 文件夹字体。系统字体只在本机读取，不会复制进项目。将 TTF、OTF、WOFF 放入 font（支持子文件夹），重新扫描即可更新。','Choose bundled fonts, installed system fonts, or fonts in the font folder. System fonts stay on this computer and are not copied into the project. Add TTF, OTF, or WOFF files to font (including subfolders), then rescan.')}</p><button type="button" id="scan-fonts">${fontUI('重新扫描字体','Rescan fonts')}</button><p id="font-scan-status" role="status"></p><p id="font-scan-list" class="preserve-lines"></p><p id="font-scan-errors" class="preserve-lines" role="alert"></p>`;
  document.querySelector('.theme-panel').append(panel);
  $('scan-fonts').onclick=async()=>{const b=$('scan-fonts');b.disabled=true;try{await scanFonts(true);}catch(e){$('font-scan-status').textContent=e.message;}finally{b.disabled=false;}};
  fontsStarted=true;scanFonts().catch(e=>$('font-scan-status').textContent=e.message).finally(fontsReady);
});
window.addEventListener('focus',()=>{if(fontsStarted&&!document.hidden)scanFonts().catch(e=>$('font-scan-status').textContent=e.message);});
// Populate a native font menu before its pointer/keyboard default action. An
// unfocused select renders its selected option only; the complete node list is
// cached unchanged until needed. Programmatic selection also restores it above.
for(const type of ['pointerdown','focusin'])window.addEventListener(type,event=>{
  if(event.target.matches?.(fontSelects))restoreFontOptions(event.target);
},true);
window.addEventListener('focusout',event=>{
  if(event.target.matches?.(fontSelects))queueMicrotask(()=>parkFontOptions(event.target));
},true);
