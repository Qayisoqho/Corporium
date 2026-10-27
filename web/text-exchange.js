/* Format selection lives at the text level; language packages have their own UI. */
(() => {
 makeDialog('text-exchange-dialog',(globalThis.CorporiumI18n?.f("6c4c2f47675b42",()=>[])??`<h2 id="text-exchange-title">导入文本</h2><p id="text-exchange-language"></p><label>文件格式<select id="text-exchange-format"><option value="typst">Typst（.typ）</option><option value="excel">Excel（.xlsx）</option><option value="docx">Word（.docx）</option></select></label><label id="text-exchange-text-label" hidden>导出的文本<select id="text-exchange-text"></select></label><p id="text-exchange-hint"></p><p id="text-exchange-error" role="alert"></p><p id="text-exchange-status" role="status"></p><button id="text-exchange-next" class="primary">继续</button><button id="text-exchange-save" class="primary" hidden>选择保存位置</button>`));
 let mode='import',owner='',prepared=null,busy=false;
 function lock(value){for(const id of ['text-exchange-format','text-exchange-text','text-exchange-next','text-exchange-save'])$(id).disabled=value;}
 $('import').innerHTML=(globalThis.CorporiumI18n?.f("66bfd9be67b214",()=>[uiIcon('import')])??uiIcon('import')+'<span>导入</span>');$('export').innerHTML=(globalThis.CorporiumI18n?.f("446c4461c8b760",()=>[uiIcon('export')])??uiIcon('export')+'<span>导出</span>');$('import').title=(globalThis.CorporiumI18n?.f("16a62a1aee7697",()=>[])??'导入文本');$('export').title=(globalThis.CorporiumI18n?.f("e9956a2ffba78d",()=>[])??'导出文本');$('export').hidden=false;
 $('file').accept='.typ';$('file').parentElement.firstChild.textContent=(globalThis.CorporiumI18n?.f("6f9574bf356726",()=>[])??'选择 .typ 文件');$('import-dialog').querySelector('h2').textContent=(globalThis.CorporiumI18n?.f("60cd0d8009d193",()=>[])??'导入文本 · Typst');
 $('import-dialog').querySelector('p').textContent=(globalThis.CorporiumI18n?.f("96ca99247e2afa",()=>[])??'支持 #gloss 与 #pass。导入语言数据（包括 JSON）请到左侧“语言选项”，不在这里导入。');
 const oldSelect=selectText;selectText=async function(...args){await oldSelect(...args);$('export').hidden=false;};
 function update(){prepared=null;$('text-exchange-save').hidden=true;$('text-exchange-status').textContent=$('text-exchange-error').textContent='';$('text-exchange-text-label').hidden=mode!=='export'||$('text-exchange-format').value!=='typst';$('text-exchange-next').textContent=mode==='export'&&$('text-exchange-format').value==='typst'?(globalThis.CorporiumI18n?.f("c52603b2a6e087",()=>[])??'生成导出文件'):(globalThis.CorporiumI18n?.f("53b4d76f8fd8b8",()=>[])??'继续');}
 async function open(which){
  if(busy)return;if(activeLanguage==='all'){await corporiumAlert((globalThis.CorporiumI18n?.f("1eefdd1de34a05",()=>[])??'请先在左侧选择一种语言，再导入或导出文本。'));return;}
  mode=which;owner=activeLanguage;$('text-exchange-title').textContent=mode==='import'?(globalThis.CorporiumI18n?.f("201d950bdbc667",()=>[])??'导入文本'):(globalThis.CorporiumI18n?.f("5734fa7d19e60d",()=>[])??'导出文本');$('text-exchange-language').textContent=(globalThis.CorporiumI18n?.f("681e11adb6653a",()=>[languageList.find(l=>l.id===owner)?.name||owner])??'当前语言：'+(languageList.find(l=>l.id===owner)?.name||owner));$('text-exchange-hint').textContent=mode==='import'?(globalThis.CorporiumI18n?.f("547f65f9cd89a5",()=>[])??'这里只导入文本。导入语言数据（包括 JSON）请使用左侧“语言选项 → 导入语言数据包”。'):(globalThis.CorporiumI18n?.f("e18574f1ca3aa6",()=>[])??'只导出当前语言的文本；导出整个语言请使用左侧“语言选项”。');
  $('text-exchange-text').innerHTML=texts.filter(t=>t.language_id===owner).map(t=>`<option value="${esc(t.id)}">${esc(t.title)}</option>`).join('');if(selected)$('text-exchange-text').value=selected;update();$('text-exchange-dialog').showModal();
 }
 $('import').onclick=()=>open('import');$('export').onclick=()=>open('export');$('text-exchange-format').onchange=update;$('text-exchange-text').onchange=update;
 $('text-exchange-next').onclick=async()=>{
  if(busy)return;busy=true;lock(true);$('text-exchange-error').textContent='';$('text-exchange-next').disabled=true;
  try{
   if(owner!==activeLanguage)throw Error((globalThis.CorporiumI18n?.f("44962c1cef5fdd",()=>[])??'语言已切换，请重新打开窗口'));
   if($('text-exchange-format').value==='excel'){$('text-exchange-dialog').close();await CorporiumExcelExchange.open(mode);return;}
   if($('text-exchange-format').value==='docx'){$('text-exchange-dialog').close();await CorporiumDocxExchange.open(mode);return;}
   if(mode==='import'){$('text-exchange-dialog').close();$('import-language').innerHTML=languageOptions();$('import-language').value=owner;$('import-error').textContent='';$('import-dialog').showModal();return;}
   $('text-exchange-status').textContent=(globalThis.CorporiumI18n?.f("6f10e71a779565",()=>[])??'正在生成文件…');prepared=await api('text-export',{id:$('text-exchange-text').value,_language:owner});prepared.name=prepared.name.replace(/[\\/:*?"<>|]/g,'-');$('text-exchange-save').hidden=false;$('text-exchange-status').textContent=(globalThis.CorporiumI18n?.f("55e16821cdf8ac",()=>[])??'文件已生成，请选择保存位置。');
  }catch(e){$('text-exchange-error').textContent=e.message;$('text-exchange-status').textContent=(globalThis.CorporiumI18n?.f("b0e4550379cca6",()=>[])??'未完成，请修正后重试。');}finally{busy=false;lock(false);$('text-exchange-next').disabled=false;}
 };
 $('text-exchange-save').onclick=async()=>{
  if(busy||!prepared)return;busy=true;lock(true);
  try{
   if(owner!==activeLanguage)throw Error((globalThis.CorporiumI18n?.f("97145e21b8f905",()=>[])??'语言已切换，请重新导出'));
   if(window.pywebview?.api?.save_text_export){const r=await window.pywebview.api.save_text_export(prepared.token,prepared.name);if(r.error)throw Error(r.error);$('text-exchange-status').textContent=r.cancelled?(globalThis.CorporiumI18n?.f("8e98770577697c",()=>[])??'已取消保存。'):(globalThis.CorporiumI18n?.f("7047a3c635a545",()=>[r.path])??'已保存：'+r.path);}
   else if(window.showSaveFilePicker){const handle=await window.showSaveFilePicker({suggestedName:prepared.name,types:[{description:(globalThis.CorporiumI18n?.f("50ae471d4910a4",()=>[])??'Typst 文本'),accept:{'text/plain':['.typ']}}]});const dest=await handle.createWritable();try{await dest.write(Uint8Array.from(atob(prepared.data),c=>c.charCodeAt(0)));await dest.close();}catch(e){await dest.abort().catch(()=>{});throw e;}$('text-exchange-status').textContent=(globalThis.CorporiumI18n?.f("473a8cd54ab221",()=>[handle.name])??'已保存：'+handle.name);}
   else{download(prepared.name,Uint8Array.from(atob(prepared.data),c=>c.charCodeAt(0)),'text/plain;charset=utf-8');$('text-exchange-status').textContent=(globalThis.CorporiumI18n?.f("686420e47f903a",()=>[])??'已交给浏览器下载；保存位置由浏览器下载设置控制。');}
  }catch(e){if(e.name==='AbortError')$('text-exchange-status').textContent=(globalThis.CorporiumI18n?.f("dcfcd2702487f8",()=>[])??'已取消保存。');else $('text-exchange-error').textContent=e.message;}finally{busy=false;lock(false);}
 };
})();
