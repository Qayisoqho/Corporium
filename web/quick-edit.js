// The quick view uses the actual draft and the normal transactional save pipeline.
(()=>{
 const editor=$('lexeme-editor'),form=$('lexeme-form'),save=$('save-lexeme');
 const dialog=document.createElement('dialog');dialog.id='lexeme-quick-editor';dialog.dataset.docked='true';
 dialog.innerHTML=(globalThis.CorporiumI18n?.f("6e1fa1615a9670",()=>[])??'<div class="dialog-top dialog-title-row"><h2>快捷编辑</h2><button type="button" id="quick-edit-return">返回完整编辑</button></div><div class="dialog-content" id="quick-edit-host"></div><div class="dialog-bottom" id="quick-edit-actions"></div>');
 document.body.append(dialog);
 let formHome=null,saveHome=null,typeHome=null,expanded=false,sequence=0,columns=[];
 const typeField=$('morph-entry-type').closest('label'),identity=form.querySelector(':scope>.metadata-grid');
 const rows=createQuickEditRows(()=>dialog.open,()=>columns);
 function componentColumns(row){
  if(row.registryRecord)return;
  const el=row.querySelector('.ws-writings'),values=wsReadWritings(el);
  for(const id of columns)if(!values.some(w=>w.type_id===id))values.push({type_id:id,text:''});
  wsWritings(el,values);if(columns.length)el.parentElement.open=true;
 }
 function restore(){
  if(!formHome)return;
  window.CorporiumParadigms?.setQuick(false);
  typeHome?.replaceWith(typeField);typeHome=null;identity.classList.remove('quick-identity-row');typeField.classList.remove('quick-entry-type');
  rows.clear();formHome.replaceWith(form);saveHome.replaceWith(save);formHome=saveHome=null;
  morphologyEditorBlock.open=expanded;
 }
 dialog.addEventListener('close',restore);
 $('quick-edit-return').onclick=()=>dialog.close();
 editor.addEventListener('close',()=>{sequence++;if(dialog.open)dialog.close();restore();});
 async function open(){
  const request=++sequence,lid=$('lexeme-language').value;
  try{
   const settings=await api('quick-edit-settings?'+new URLSearchParams({language:lid}));
   if(request!==sequence||!editor.open||$('lexeme-language').value!==lid)return;
   columns=settings.selected;
   for(const id of columns)if(![...$('lexeme-orthographies').children].some(r=>r.querySelector('.orthography-type').value===id))addOrthography({type_id:id});
   if(!$('lexeme-usages').children.length)addUsage({senses:[{}]});
   for(const usage of $('lexeme-usages').children)if(!usage.querySelector('.sense-editors').children.length)addSense(usage.querySelector('.sense-editors'));
   if(!$('ws-analyses').children.length)wsAnalysis({default:true,components:[{}]});
   for(const analysis of $('ws-analyses').children){const list=analysis.querySelector('.ws-components');if(!list.children.length)wsComponent(list);}
   for(const row of $('ws-analyses').querySelectorAll('.ws-component'))componentColumns(row);
   expanded=morphologyEditorBlock.open;morphologyEditorBlock.open=true;
   formHome=document.createComment('complete editor form');form.before(formHome);
   saveHome=document.createComment('complete editor save');save.before(saveHome);
   typeHome=document.createComment('complete editor entry type');typeField.before(typeHome);identity.append(typeField);identity.classList.add('quick-identity-row');typeField.classList.add('quick-entry-type');
   $('quick-edit-host').append(form);$('quick-edit-actions').append(save);
   dialog.showModal();window.CorporiumParadigms?.setQuick(true);rows.refresh();$('lexeme-headword').focus();
  }catch(e){$('lexeme-error').textContent=e.message;}
 }
 const button=document.createElement('button');button.type='button';button.id='lexeme-quick-open';button.textContent=(globalThis.CorporiumI18n?.f("54e43c5e0d6bd5",()=>[])??'快捷编辑');button.onclick=open;
 const originalOpen=openLexemeEditor;
 openLexemeEditor=async function(...args){await originalOpen(...args);if(!editor.open)return;dockDialog(editor);const header=editor.querySelector('.dialog-top');header.classList.add('lexeme-editor-actions');header.prepend(button);};
 const component=wsComponent;
 wsComponent=function(...args){component(...args);if(dialog.open){componentColumns(args[0].lastElementChild);rows.refresh();}};
 const usage=addUsage;
 addUsage=function(...args){usage(...args);if(dialog.open){const list=$('lexeme-usages').lastElementChild.querySelector('.sense-editors');if(!list.children.length)addSense(list);rows.refresh();}};
 const analysis=wsAnalysis;
 wsAnalysis=function(...args){analysis(...args);if(dialog.open){const list=$('ws-analyses').lastElementChild.querySelector('.ws-components');if(!list.children.length)wsComponent(list);rows.refresh();}};
 const sense=addSense;addSense=function(...args){sense(...args);rows.refresh();};
 // A column may be empty; it should disappear from saved data, not become an invalid writing.
 const prune=pruneNewLexemeRows;
 pruneNewLexemeRows=function(body,previous){if(dialog.open)body.orthographies=body.orthographies.filter(o=>o.text.trim());return prune(body,previous);};
 form.addEventListener('submit',event=>{
  if(!dialog.open)return;
  for(const row of $('ws-analyses').querySelectorAll('.ws-component')){
   if(row.registryPending||row.registryRecord)continue;
   if(!wsVal(row,'form').trim()&&(wsVal(row,'readings').trim()||wsReadWritings(row.querySelector('.ws-writings')).length)){
    event.preventDefault();event.stopImmediatePropagation();morphologyEditorBlock.open=true;
    $('lexeme-error').textContent=(globalThis.CorporiumI18n?.f("0df01a47729d05",()=>[])??'请填写新语素的形式；完全留空的组分会在保存时舍弃。');(row.querySelector('.quick-component-form')||row.querySelector('[data-ws="form"]')).focus();return;
   }
  }
 },true);

 const manage=document.createElement('button');manage.id='quick-edit-manager-open';manage.textContent=(globalThis.CorporiumI18n?.f("827f3c551899e6",()=>[])??'词条快捷编辑管理');$('management-entries').append(manage);
 makeDialog('quick-edit-manager',(globalThis.CorporiumI18n?.f("c08473fd6215d3",()=>[])??'<h2>词条快捷编辑管理</h2><label>语言<select id="quick-edit-language"></select></label><p>选择打开快捷编辑时始终显示的书写形式。</p><form id="quick-edit-settings-form"><div id="quick-edit-writing-types"></div><p id="quick-edit-settings-error" role="alert"></p><button class="primary" type="submit">保存设置</button></form>'));
 let settings=null,settingsSequence=0;
 async function load(){
  const request=++settingsSequence,lid=$('quick-edit-language').value;settings=null;$('quick-edit-settings-error').textContent='';$('quick-edit-writing-types').replaceChildren();
  try{const data=await api('quick-edit-settings?'+new URLSearchParams({language:lid}));if(request!==settingsSequence)return;settings=data;
   $('quick-edit-writing-types').innerHTML=data.writing_types.map(t=>`<label><input type="checkbox" value="${esc(t.id)}" ${data.selected.includes(t.id)?'checked':''}> ${esc(t.name)}</label>`).join('')||(globalThis.CorporiumI18n?.f("e5558898f26c4a",()=>[])??'<small>此语言尚无书写类型，可先在书写类型管理中添加。</small>');
  }catch(e){if(request===settingsSequence)$('quick-edit-settings-error').textContent=e.message;}
 }
 manage.onclick=async()=>{$('management-dialog').close();$('quick-edit-language').innerHTML=languageOptions();$('quick-edit-language').value=activeLanguage==='all'?'ordos':activeLanguage;$('quick-edit-manager').showModal();await load();};
 $('quick-edit-language').onchange=load;
 $('quick-edit-settings-form').onsubmit=async event=>{event.preventDefault();if(!settings)return;const submit=event.submitter||$('quick-edit-manager').querySelector('[type="submit"]');submit.disabled=true;$('quick-edit-language').disabled=true;
  try{await api('quick-edit-settings',{_language:$('quick-edit-language').value,revision:settings.revision,writing_types:[...$('quick-edit-writing-types').querySelectorAll('input:checked')].map(e=>e.value)});$('quick-edit-manager').close();}
  catch(e){$('quick-edit-settings-error').textContent=e.message;}finally{submit.disabled=false;$('quick-edit-language').disabled=false;}
 };
})();
