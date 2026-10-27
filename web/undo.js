const undoPanel=document.createElement('section');
undoPanel.className='undo-panel';
undoPanel.innerHTML=(globalThis.CorporiumI18n?.f("8ad84b94f6ceb8",()=>[])??'<div class="undo-actions"><button id="undo-action" disabled>撤销</button><button id="redo-action" disabled>重做</button><label>保留 <select id="undo-limit" aria-label="撤销步数"><option value="10">10 步</option><option value="20" selected>20 步</option><option value="30">30 步</option><option value="40">40 步</option></select></label></div><details><summary>最近操作</summary><ol id="undo-list"></ol><small>撤销后进行新修改会清空重做记录。缩短步数会清除超出上限的记录；完整备份另行保留。</small></details>');
document.querySelector('header').after(undoPanel);
let undoState=null,undoBusy=false;
const originalApi=api;
async function refreshUndo(){
  await loadLanguages();
  undoState=await originalApi('undo-state');
  window.corporiumWorkspaceRevision=undoState.workspace_revision;
  for(const kind of ['undo','redo']){
    const b=$(''+kind+'-action'),step=undoState[kind];
    b.disabled=undoBusy||!step;
    b.textContent=(kind==='undo'?(globalThis.CorporiumI18n?.f("25068bc08a6d18",()=>[])??'撤销'):(globalThis.CorporiumI18n?.f("77ef2b0c16106f",()=>[])??'重做'))+(step?'：'+step.label:'');
    b.title=activeLanguage==='all'?(globalThis.CorporiumI18n?.f("8bfd25c8cbc0c7",()=>[])??'请先选择一种语言'):((globalThis.CorporiumI18n?.f("10f8922d7d39e2",()=>[languageList.find(l=>l.id===activeLanguage)?.name])??'作用范围：'+languageList.find(l=>l.id===activeLanguage)?.name));
  }
  $('undo-limit').value=String(undoState.step_limit);
  $('undo-limit').disabled=activeLanguage==='all';
  undoPanel.querySelector('summary').textContent=activeLanguage==='all'?(globalThis.CorporiumI18n?.f("a4ef741f796d39",()=>[])??'最近操作 · 请先选择一种语言'):(globalThis.CorporiumI18n?.f("72a7422b33e58d",()=>[languageList.find(l=>l.id===activeLanguage)?.name])??'最近操作 · '+languageList.find(l=>l.id===activeLanguage)?.name);
  $('undo-list').replaceChildren(...undoState.steps.map(step=>{
    const li=document.createElement('li');
    li.textContent=step.label+' · '+new Date(step.created).toLocaleString()+(step.applied?'':(globalThis.CorporiumI18n?.f("c4002cb1a80fb0",()=>[])??'（已撤销）'));
    return li;
  }));
  if(!undoState.steps.length)$('undo-list').textContent=(globalThis.CorporiumI18n?.f("737f5e5484160d",()=>[])??'暂无操作记录');
}
// Some independent editors only need the history controls, without reloading their workspace.
window.corporiumRefreshUndoState=refreshUndo;
api=async function(path,body){
  const result=await originalApi(path,body);
  if(body&&!path.startsWith('analysis-')&&path!=='morpheme-save-preview'&&!['docx-inspect','docx-preview','docx-export','docx-template'].includes(path)){
    // Grammar editors own their one post-save audit, after the editor closes.
    const refresh=['grammaticality-save','grammaticality-type-save','grammaticality-type-delete','grammar-save','grammar-delete','grammar-register-batch','grammar-ignore','grammar-unignore','lexeme-unlink','dictionary-examples-unlink'].includes(path)?window.corporiumRefreshUndoState:refreshUndo;
    await refresh().catch(()=>{$('notice').textContent=(globalThis.CorporiumI18n?.f("3e3bd58ba777cf",()=>[])??'数据已保存，但操作记录刷新失败，请刷新页面。')});
  }
  return result;
};
async function undoCommand(kind){
  if(undoBusy)return;
  if(document.querySelector('dialog[open]')||infoDirty||(typeof inlineDrafts!=='undefined'&&inlineDrafts.size)){
    $('notice').textContent=(globalThis.CorporiumI18n?.f("bd960e2ba2abe7",()=>[])??'请先保存或取消正在编辑的内容，再撤销或重做。');return;
  }
  if(!undoState||!undoState[kind])return;
  undoBusy=true;
  $('undo-action').disabled=$('redo-action').disabled=true;
  try{
    await originalApi(''+kind,{generation:undoState.generation});
    chosen.clear();
    await loadLanguages();
    await loadTexts();
    await selectText(texts.some(t=>t.id===selected)?selected:'',{preservePage:true});
    corporiumStatus(kind==='undo'?(globalThis.CorporiumI18n?.f("f6f480b2313f62",()=>[])??'已撤销上一步操作。'):(globalThis.CorporiumI18n?.f("f7b0dd29f93274",()=>[])??'已重做操作。'));
  }finally{undoBusy=false;await refreshUndo();}
}
$('undo-action').onclick=safe(()=>undoCommand('undo'));
$('redo-action').onclick=safe(()=>undoCommand('redo'));
$('undo-limit').onchange=safe(async()=>{
  try{await originalApi('undo-limit',{generation:undoState.generation,limit:Number($('undo-limit').value)});}
  finally{await refreshUndo();}
});
document.addEventListener('keydown',event=>{
  if(event.target.closest('input,textarea,select,[contenteditable="true"]')||document.querySelector('dialog[open]'))return;
  if((event.ctrlKey||event.metaKey)&&!event.altKey&&event.key.toLowerCase()==='z'){
    event.preventDefault();safe(()=>undoCommand(event.shiftKey?'redo':'undo'))();
  }
});
// Regaining focus is a change check, not a request to rebuild the current page.
// A second window can still change this project while this window is in the background.
let focusCheck=null,focusDeferred=false;
async function refreshOnFocus(){
  if(document.documentElement?.dataset.appLoading==='true')return;
  if(focusCheck)return focusCheck;
  const lid=activeLanguage;
  focusCheck=(async()=>{
    const state=await originalApi('undo-state');
    if(lid!==activeLanguage)return;
    // Editors retain their drafts; the changed revision invalidates a reused view.
    const draft=document.querySelector('dialog[open]')||infoDirty||(typeof inlineDrafts!=='undefined'&&inlineDrafts.size)||window.corporiumNotesDirty?.()||window.corporiumSurveyDirty?.()||window.corporiumTimelineDirty?.()||window.corporiumCodesDirty?.();
    if(!focusDeferred&&state.workspace_revision&&state.workspace_revision===window.corporiumWorkspaceRevision){if(!draft)await window.corporiumCheckActiveCatalog?.();return;}
    if(draft){focusDeferred=true;await window.corporiumRefreshUndoState();}
    else {await refreshUndo();await window.corporiumRefreshVisibleWorkspace?.();focusDeferred=false;}
  })().finally(()=>{focusCheck=null;});
  return focusCheck;
}
window.addEventListener('focus',()=>safe(refreshOnFocus)());
// languages.js already initializes history after the initial corpus load.
