/* Both destructive gates deliberately accept dblclick only. */
(()=>{
 const actions=document.createElement('div');actions.className='language-dialog-actions';
 $('save-language').before(actions);actions.append($('save-language'));
 const remove=document.createElement('button');remove.id='delete-language';remove.type='button';remove.className='danger language-delete-action';remove.textContent=(globalThis.CorporiumI18n?.f("eb3a056e808964",()=>[])??'删除语言（双击）');remove.title=(globalThis.CorporiumI18n?.f("1af01ae6937b5b",()=>[])??'双击打开删除确认窗口');actions.append(remove);
 makeDialog('language-delete-dialog',(globalThis.CorporiumI18n?.f("a03ca5e5c708b2",()=>[])??'<h2>确认删除语言</h2><p id="language-delete-name"></p><p id="language-delete-counts"></p><p>将删除该语言的全部资料、设置及撤销记录。删除前会保存完整数据库备份；此操作不能通过撤销恢复。</p><p id="language-delete-error" role="alert"></p><div class="language-dialog-actions"><button id="cancel-language-delete" type="button">取消</button><button id="confirm-language-delete" type="button" class="danger language-delete-action" disabled>确认删除（双击）</button></div>'));
 const dialog=$('language-delete-dialog'),confirm=$('confirm-language-delete'),cancel=$('cancel-language-delete');
 let pending=null,busy=false,opening=false,request=0;
 const open=openLanguage;openLanguage=function(lang=null){remove.hidden=!lang;remove.disabled=false;return open(lang);};
 function lock(value){busy=value;confirm.disabled=value||!pending||!!pending.blockers.length;cancel.disabled=value;dialog.querySelector('.close').disabled=value;}
 dialog.addEventListener('cancel',e=>{if(busy)e.preventDefault();});
 dialog.addEventListener('close',()=>{pending=null;request++;});
 cancel.onclick=()=>dialog.close();
 remove.ondblclick=async()=>{
  if(busy||opening||dialog.open||!editingLanguage)return;
  opening=true;remove.disabled=true;
  $('language-error').textContent='';
  try{
   if((typeof inlineDrafts!=='undefined'&&inlineDrafts.size)||infoDirty||(typeof lexemeDirty!=='undefined'&&lexemeDirty))throw Error((globalThis.CorporiumI18n?.f("e9e51341a62c0b",()=>[])??'请先保存或取消其他材料的编辑，再删除语言。'));
   await window.corporiumFlushSurvey?.();await window.corporiumFlushNotes?.();
   if(await window.corporiumLeaveMorpheme?.()===false||await window.corporiumLeaveCodes?.()===false)return;
   const owner={id:editingLanguage.id,revision:editingLanguage.revision,_language:editingLanguage.id},ticket=++request;
   pending=null;$('language-delete-name').textContent=(globalThis.CorporiumI18n?.f("27cfa3140fda53",()=>[editingLanguage.name])??'删除「'+editingLanguage.name+'」？');$('language-delete-counts').textContent=(globalThis.CorporiumI18n?.f("e501e745d57268",()=>[])??'正在核对资料…');$('language-delete-error').textContent='';confirm.disabled=true;dialog.showModal();cancel.focus();
   const result=await originalApi('language-delete-preview',owner);
   if(ticket!==request||!dialog.open)return;
   pending={...result,_language:owner.id};const c=result.counts;
   $('language-delete-counts').textContent=(globalThis.CorporiumI18n?.f("6f5a1fcd03c001",()=>[c.texts,c.entries,c.dictionary_examples,c.lexemes,c.morphemes,c.timeline_sessions,c.survey_nodes])??`${c.texts} 个文本 · ${c.entries} 个文本句子 · ${c.dictionary_examples} 个独立例句 · ${c.lexemes} 个词条 · ${c.morphemes} 个语素 · ${c.timeline_sessions} 个时间轴 · ${c.survey_nodes} 个调查条目`);
   $('language-delete-error').textContent=result.blockers.length?(globalThis.CorporiumI18n?.f("589a0f551a556e",()=>[result.blockers.join('、')])??'仍有其他材料引用本语言，请先调整引用：'+result.blockers.join('、')):'';
   confirm.disabled=!!result.blockers.length;
  }catch(e){if(dialog.open){$('language-delete-error').textContent=e.message;confirm.disabled=true;}else $('language-error').textContent=e.message;}
  finally{opening=false;remove.disabled=false;}
 };
 confirm.ondblclick=async()=>{
  if(busy||!pending||confirm.disabled)return;
  lock(true);$('language-delete-error').textContent='';
  try{
   const result=await originalApi('delete-language',{id:pending.id,revision:pending.revision,token:pending.token,_language:pending.id,confirmed:true});
   pending=null;
   try{localStorage.setItem(projectStorageKey('corpus-language'),result.next_language);sessionStorage.setItem('corporium-language-deleted',JSON.stringify({name:result.name,backup:result.backup}));}catch{}
   // Reload all workspaces together; no stale detail, draft or saved query may
   // continue submitting the language that has just been removed.
   window.location.reload();
  }catch(e){$('language-delete-error').textContent=e.message;pending=null;}
  finally{lock(false);}
 };
 try{const saved=sessionStorage.getItem('corporium-language-deleted');if(saved){sessionStorage.removeItem('corporium-language-deleted');const result=JSON.parse(saved);corpusReady.then(()=>corporiumStatus((globalThis.CorporiumI18n?.f("153d9a4056e1c7",()=>[result.name,result.backup])??'已删除「'+result.name+'」。操作前备份：data/backups/'+result.backup)));}}catch{}
})();
