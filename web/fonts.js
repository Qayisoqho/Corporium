const availableFonts={IPAPANNEW:'IPAPANNEW',Junicode:'Junicode',SimSun:'宋体（系统）',KaiTi:'楷体（系统）','Microsoft YaHei':'微软雅黑（系统）',serif:'默认衬线字体','sans-serif':'默认无衬线字体'};
const validFont=value=>Object.hasOwn(availableFonts,value)||/^localfont-[0-9a-f]{24}$/.test(value||'');
const fontChoices=()=>Object.entries(availableFonts).map(([id,name])=>`<option value="${esc(id)}">${esc(name)}</option>`).join('');
function selectFont(select,value){
  if(validFont(value)&&![...select.options].some(o=>o.value===value))select.add(new Option('未检测到的字体（保留设置）',value));
  select.value=value;
}
async function scanFonts(refresh=false){
  const data=await api('fonts'+(refresh?'?refresh=true':''));
  for(const key of Object.keys(availableFonts))if(key.startsWith('localfont-'))delete availableFonts[key];
  let css='';
  for(const family of data.families){
    availableFonts[family.id]=family.name+'（font 文件夹）';
    for(const face of family.faces)css+=`@font-face{font-family:"${family.id}";src:url("${face.url}");font-style:${face.style};font-weight:${face.weight};font-display:swap}\n`;
  }
  let sheet=$('local-font-styles');if(!sheet){sheet=document.createElement('style');sheet.id='local-font-styles';document.head.append(sheet);}sheet.textContent=css;
  for(const select of document.querySelectorAll('#language-ipa-font,#language-annotation-font,.language-font,#writing-font,#layer-font,.orthography-font,.global-font')){
    const value=select.value;select.innerHTML=(select.classList.contains('global-font')?'<option value="">默认字体</option>':'')+fontChoices();selectFont(select,value);
  }
  $('font-scan-status').textContent=`检测到 ${data.families.length} 个字体家族、${data.file_count} 个字体文件。`;
  $('font-scan-errors').textContent=data.errors.map(e=>e.file+'：'+e.error).join('\n');
  $('font-scan-list').textContent=data.families.map(f=>f.name+' · '+f.faces.length+' 个字形').join('\n');
  renderLanguage();
}
let fontsReady;
window.corporiumFontsReady=new Promise(resolve=>{fontsReady=resolve;});
window.addEventListener('DOMContentLoaded',()=>{
  const panel=document.createElement('details');panel.className='font-panel';
  panel.innerHTML='<summary>自定义字体</summary><p>将字体文件或文件夹放入 font，再点击扫描。支持 TTF、OTF、WOFF，包含子文件夹；同一家族的字形合并显示。</p><button id="scan-fonts">扫描 font 文件夹</button><p id="font-scan-status" role="status"></p><p id="font-scan-list" class="preserve-lines"></p><p id="font-scan-errors" class="preserve-lines" role="alert"></p>';
  document.querySelector('.theme-panel').append(panel);
  $('scan-fonts').onclick=async()=>{const b=$('scan-fonts');b.disabled=true;try{await scanFonts(true);}catch(e){$('font-scan-status').textContent=e.message;}finally{b.disabled=false;}};
  scanFonts().catch(e=>$('font-scan-status').textContent=e.message).finally(fontsReady);
});
