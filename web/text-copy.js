/* Whole-text copies share the sentence evidence copier and one undo step. */
(()=>{
 const tr=text=>globalThis.CorporiumI18n?.phrase(text)??text;
 const button=document.createElement('button');button.id='copy-text';button.type='button';button.textContent=tr('复制文本');
 document.querySelector('.sidebar-create .workbench-menu-items').append(button);
 makeDialog('text-copy-dialog','<h2>'+tr('复制文本')+'</h2><form id="text-copy-form"><label>'+tr('来源文本')+'<select id="text-copy-source" required></select></label><label>'+tr('新文本标题')+'<input id="text-copy-title" required></label><p>'+tr('复制全部句子、标注、文本信息和发言人。词典关联保留；音频沿用原媒体，对齐另建副本。新旧文本可分别修改，整次复制可一步撤销。')+'</p><p><span>'+tr('句子数量')+'：</span><output id="text-copy-count">—</output></p><p id="text-copy-error" role="alert"></p><button id="text-copy-save" type="submit" class="primary">'+tr('确认复制')+'</button></form>');
 let snapshot=null,request=0,saving=false;
 async function preview(){
  const seq=++request; snapshot=null;$('text-copy-save').disabled=true;$('text-copy-count').textContent='—';$('text-copy-error').textContent='';
  const id=$('text-copy-source').value;if(!id){$('text-copy-title').value='';return;}
  try{const data=await api('text-copy-preview?id='+encodeURIComponent(id));if(seq!==request||!$('text-copy-dialog').open)return;snapshot=data;$('text-copy-title').value=data.title+tr('（副本）');$('text-copy-count').textContent=data.count;$('text-copy-save').disabled=false;}
  catch(error){if(seq===request)$('text-copy-error').textContent=error.message;}
 }
 button.onclick=safe(async()=>{
  button.closest('details').open=false;
  if(inlineDrafts.size)throw Error(tr('请先保存或取消正在编辑的例句。'));
  await loadTexts();
  $('text-copy-source').innerHTML='<option value="">'+tr('选择来源文本')+'</option>'+texts.map(t=>'<option value="'+esc(t.id)+'">'+esc(t.title)+'</option>').join('');
  $('text-copy-source').value=texts.some(t=>t.id===selected)?selected:'';
  $('text-copy-dialog').showModal();await preview();
 });
 $('text-copy-source').onchange=preview;
 $('text-copy-dialog').addEventListener('close',()=>{request++;snapshot=null;});
 $('text-copy-dialog').addEventListener('cancel',event=>{if(saving)event.preventDefault();});
 $('text-copy-form').onsubmit=async event=>{
  event.preventDefault();if(saving||!snapshot)return;saving=true;
  const dialog=$('text-copy-dialog'),close=dialog.querySelector('.close');
  for(const el of [$('text-copy-source'),$('text-copy-title'),$('text-copy-save'),close])el.disabled=true;
  let created=false;
  try{
   const result=await api('copy-text',{id:snapshot.id,token:snapshot.token,title:$('text-copy-title').value,_language:snapshot.language_id});
   created=true;dialog.close();clearFilters();if(workspace!=='corpus')await setWorkspace('corpus');await loadTexts();await selectText(result.id);
   corporiumStatus(tr('已复制文本，可一步撤销。'));
  }catch(error){if(created)corporiumStatus(tr('文本副本已保存，但页面刷新失败，请重新打开文本。')+' '+error.message);else $('text-copy-error').textContent=error.message;}
  finally{saving=false;for(const el of [$('text-copy-source'),$('text-copy-title'),$('text-copy-save'),close])el.disabled=false;}
 };
})();
