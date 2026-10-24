/* Format selection lives at the text level; language packages have their own UI. */
(() => {
 makeDialog('text-exchange-dialog',`<h2 id="text-exchange-title">导入文本</h2><p id="text-exchange-language"></p><label>文件格式<select id="text-exchange-format"><option value="typst">Typst（.typ）</option><option value="excel">Excel（.xlsx）</option><option value="docx">Word（.docx）</option></select></label><label id="text-exchange-text-label" hidden>导出的文本<select id="text-exchange-text"></select></label><p id="text-exchange-hint"></p><p id="text-exchange-error" role="alert"></p><p id="text-exchange-status" role="status"></p><button id="text-exchange-next" class="primary">继续</button><button id="text-exchange-save" class="primary" hidden>选择保存位置</button>`);
 let mode='import',owner='',prepared=null,busy=false;
 function lock(value){for(const id of ['text-exchange-format','text-exchange-text','text-exchange-next','text-exchange-save'])$(id).disabled=value;}
 $('import').innerHTML=uiIcon('import')+'<span>导入</span>';$('export').innerHTML=uiIcon('export')+'<span>导出</span>';$('import').title='导入文本';$('export').title='导出文本';$('export').hidden=false;
 $('file').accept='.typ';$('file').parentElement.firstChild.textContent='选择 .typ 文件';$('import-dialog').querySelector('h2').textContent='导入文本 · Typst';
 $('import-dialog').querySelector('p').textContent='支持 #gloss 与 #pass。导入语言数据（包括 JSON）请到左侧“语言选项”，不在这里导入。';
 const oldSelect=selectText;selectText=async function(...args){await oldSelect(...args);$('export').hidden=false;};
 function update(){prepared=null;$('text-exchange-save').hidden=true;$('text-exchange-status').textContent=$('text-exchange-error').textContent='';$('text-exchange-text-label').hidden=mode!=='export'||$('text-exchange-format').value!=='typst';$('text-exchange-next').textContent=mode==='export'&&$('text-exchange-format').value==='typst'?'生成导出文件':'继续';}
 async function open(which){
  if(busy)return;if(activeLanguage==='all'){await corporiumAlert('请先在左侧选择一种语言，再导入或导出文本。');return;}
  mode=which;owner=activeLanguage;$('text-exchange-title').textContent=mode==='import'?'导入文本':'导出文本';$('text-exchange-language').textContent='当前语言：'+(languageList.find(l=>l.id===owner)?.name||owner);$('text-exchange-hint').textContent=mode==='import'?'这里只导入文本。导入语言数据（包括 JSON）请使用左侧“语言选项 → 导入语言数据包”。':'只导出当前语言的文本；导出整个语言请使用左侧“语言选项”。';
  $('text-exchange-text').innerHTML=texts.filter(t=>t.language_id===owner).map(t=>`<option value="${esc(t.id)}">${esc(t.title)}</option>`).join('');if(selected)$('text-exchange-text').value=selected;update();$('text-exchange-dialog').showModal();
 }
 $('import').onclick=()=>open('import');$('export').onclick=()=>open('export');$('text-exchange-format').onchange=update;$('text-exchange-text').onchange=update;
 $('text-exchange-next').onclick=async()=>{
  if(busy)return;busy=true;lock(true);$('text-exchange-error').textContent='';$('text-exchange-next').disabled=true;
  try{
   if(owner!==activeLanguage)throw Error('语言已切换，请重新打开窗口');
   if($('text-exchange-format').value==='excel'){$('text-exchange-dialog').close();await CorporiumExcelExchange.open(mode);return;}
   if($('text-exchange-format').value==='docx'){$('text-exchange-dialog').close();await CorporiumDocxExchange.open(mode);return;}
   if(mode==='import'){$('text-exchange-dialog').close();$('import-language').innerHTML=languageOptions();$('import-language').value=owner;$('import-error').textContent='';$('import-dialog').showModal();return;}
   $('text-exchange-status').textContent='正在生成文件…';prepared=await api('text-export',{id:$('text-exchange-text').value,_language:owner});prepared.name=prepared.name.replace(/[\\/:*?"<>|]/g,'-');$('text-exchange-save').hidden=false;$('text-exchange-status').textContent='文件已生成，请选择保存位置。';
  }catch(e){$('text-exchange-error').textContent=e.message;$('text-exchange-status').textContent='未完成，请修正后重试。';}finally{busy=false;lock(false);$('text-exchange-next').disabled=false;}
 };
 $('text-exchange-save').onclick=async()=>{
  if(busy||!prepared)return;busy=true;lock(true);
  try{
   if(owner!==activeLanguage)throw Error('语言已切换，请重新导出');
   if(window.pywebview?.api?.save_text_export){const r=await window.pywebview.api.save_text_export(prepared.token,prepared.name);if(r.error)throw Error(r.error);$('text-exchange-status').textContent=r.cancelled?'已取消保存。':'已保存：'+r.path;}
   else if(window.showSaveFilePicker){const handle=await window.showSaveFilePicker({suggestedName:prepared.name,types:[{description:'Typst 文本',accept:{'text/plain':['.typ']}}]});const dest=await handle.createWritable();try{await dest.write(Uint8Array.from(atob(prepared.data),c=>c.charCodeAt(0)));await dest.close();}catch(e){await dest.abort().catch(()=>{});throw e;}$('text-exchange-status').textContent='已保存：'+handle.name;}
   else{download(prepared.name,Uint8Array.from(atob(prepared.data),c=>c.charCodeAt(0)),'text/plain;charset=utf-8');$('text-exchange-status').textContent='已交给浏览器下载；保存位置由浏览器下载设置控制。';}
  }catch(e){if(e.name==='AbortError')$('text-exchange-status').textContent='已取消保存。';else $('text-exchange-error').textContent=e.message;}finally{busy=false;lock(false);}
 };
})();
