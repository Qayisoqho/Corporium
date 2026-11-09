function clearButton(after,id,action){
 const button=document.createElement('button');button.id=id;button.type='button';button.textContent=(globalThis.CorporiumI18n?.f("0a08f43b16f29e",()=>[])??'清空条件');after.after(button);button.onclick=safe(action);return button;
}
clearButton($('dictionary-search'),'dictionary-clear',async()=>{$('dictionary-query').value='';dictionaryPage=1;await loadDictionary();});
clearButton($('library-search'),'library-clear',async()=>{$('library-query').value='';$('library-source').value='all';$('library-field').value='all';$('library-mode').value='contains';$('library-case').checked=false;libraryPage=1;await loadLibrary();});
clearButton($('grammar-tag-query'),'grammar-tags-clear',()=>{$('grammar-tag-query').value='';drawGrammarTags();});
clearButton($('link-search'),'link-clear',async()=>{$('link-query').value='';await searchLinkLexemes();});
clearButton($('library-lexeme-search'),'library-lexeme-clear',async()=>{$('library-lexeme-query').value='';await findLibraryLexemes();});
clearButton($('auto-link-preview'),'auto-link-clear',()=>{$('auto-link-scope').value='';for(const c of $('auto-mark-options').querySelectorAll('input'))c.checked=true;$('auto-mark-position').value='edges';resetAutoPlan();});
const clearShowLexeme=showLexeme;showLexeme=async function(id,p=1){await clearShowLexeme(id,p);if($('example-source')&&!$('examples-clear'))clearButton($('example-source').parentElement,'examples-clear',async()=>{exampleSource='all';exampleKind='all';exampleForm='all';await showLexeme(dictionarySelection,1);});globalThis.CorporiumDictionaryEvidence?.refresh();};
const briefLabel=document.createElement('label');briefLabel.className='brief-control';briefLabel.innerHTML=(globalThis.CorporiumI18n?.f("8ee02065c7d2bd",()=>[])??'<input id="brief-mode" type="checkbox"> 简要模式');workspaceTabs.after(briefLabel);$('brief-mode').checked=briefMode;
const displayWorkspace=setWorkspace;setWorkspace=async function(name){await displayWorkspace(name);if(name==='corpus'&&!window.CorporiumViews?.current('corpus')){await loadTexts();await search();}};
$('brief-mode').onchange=safe(async()=>{
 if(inlineDrafts.size){$('brief-mode').checked=briefMode;await corporiumAlert((globalThis.CorporiumI18n?.f("7d2f4958105fd4",()=>[])??'请先保存或取消正在进行的标注编辑，再切换简要模式。'));return;}
 briefMode=$('brief-mode').checked;document.documentElement.classList.toggle('brief-mode',briefMode);
 try{localStorage.setItem('corporium-brief',String(briefMode));}catch{}
 await refreshExampleViews();
});
// Preserve ordinary clicks, but do not navigate after dragging to select button/link text.
let selectionPointer=null,selectionDragged=false;
document.addEventListener('pointerdown',e=>{selectionPointer={x:e.clientX,y:e.clientY};selectionDragged=false;},true);
document.addEventListener('pointermove',e=>{if(selectionPointer&&e.buttons===1&&Math.hypot(e.clientX-selectionPointer.x,e.clientY-selectionPointer.y)>4)selectionDragged=true;},true);
document.addEventListener('pointerup',()=>{selectionPointer=null;},true);
document.addEventListener('pointercancel',()=>{selectionPointer=null;selectionDragged=false;},true);
document.addEventListener('click',e=>{const dragged=selectionDragged;selectionDragged=false;if(e.detail&&dragged&&!window.getSelection()?.isCollapsed&&e.target.closest('button,a,summary,label')){e.preventDefault();e.stopImmediatePropagation();}},true);

// Keep the actual controls (and their listeners), with only the content scrolling.
function dockDialog(dialog){
 if(dialog.dataset.docked||!dialog.open)return;
 const close=dialog.querySelector('form[method="dialog"]');if(!close)return;
 dialog.dataset.docked='true';
 const header=document.createElement('div'),content=document.createElement('div'),footer=document.createElement('div');
 header.className='dialog-top';content.className='dialog-content';footer.className='dialog-bottom';
 header.append(close);while(dialog.firstChild)content.append(dialog.firstChild);
 for(const button of content.querySelectorAll('button.primary,button[type="submit"]')){
  if(dialog.id==='recorder-dialog'&&button.closest('.recorder-actions'))continue;
  const form=button.form;if(form){if(!form.id)form.id=dialog.id+'-docked-form';button.setAttribute('form',form.id);}
  footer.append(button);
 }
 if(dialog.id==='word-link-dialog'){const title=content.querySelector('h2');if(title){header.prepend(title);header.classList.add('dialog-title-row');}}
 if(dialog.id==='recorder-dialog'){const actions=content.querySelector('.recorder-actions');if(actions)footer.append(actions);}
 if(dialog.id==='auto-link-dialog'){const actions=content.querySelector('#auto-candidate-actions');if(actions)footer.prepend(actions);}
 if(['language-dialog','language-delete-dialog'].includes(dialog.id)){
  const actions=content.querySelector('.language-dialog-actions');
  if(actions){for(const button of [...footer.children])actions.prepend(button);footer.append(actions);}
 }
 dialog.append(header,content,footer);
}
new MutationObserver(records=>{for(const r of records){if(r.type==='attributes'&&r.target.tagName==='DIALOG')dockDialog(r.target);else if(r.type==='childList')for(const n of r.addedNodes)if(n.nodeType===1&&n.tagName==='DIALOG')dockDialog(n);}}).observe(document.body,{subtree:true,childList:true,attributes:true,attributeFilter:['open']});

// Modal dialogs move by their title strip, heading or own padding; inline page editors and docked side
// panels stay put. Each opening starts centred again, and resizing the window recentres a moved dialog.
(()=>{
 const interactive='button,input,select,textarea,a,summary,label,option,[contenteditable="true"],[role="button"],[role="tab"]';
 const saved=new WeakMap();let drag=null;
 const restore=dialog=>{if(!saved.has(dialog))return;Object.assign(dialog.style,saved.get(dialog));saved.delete(dialog);delete dialog.dataset.dialogMoved;};
 document.addEventListener('pointerdown',e=>{
  const dialog=e.target.closest?.('dialog[open]');
  if(!dialog||e.button!==0||!dialog.matches(':modal')||dialog.matches('.page-editor,.workbench-inspector,[data-dialog-drag="off"]')||e.target.closest(interactive))return;
  const box=dialog.getBoundingClientRect();if(e.clientX<box.left||e.clientX>box.right||e.clientY<box.top||e.clientY>box.bottom)return;
  if(e.target===dialog){if(e.offsetX>=dialog.clientWidth||e.offsetY>=dialog.clientHeight)return;}
  else{const title=dialog.querySelector('h1,h2')||dialog.querySelector('h3');if(!e.target.closest('.dialog-top,.eyebrow')&&!title?.contains(e.target))return;}
  e.preventDefault();
  if(!saved.has(dialog)){const s=dialog.style;saved.set(dialog,{margin:s.margin,left:s.left,top:s.top,right:s.right,bottom:s.bottom,width:s.width});}
  Object.assign(dialog.style,{margin:'0',left:box.left+'px',top:box.top+'px',right:'auto',bottom:'auto',width:getComputedStyle(dialog).width});
  dialog.dataset.dialogMoved='true';dialog.dataset.dragging='true';dialog.setPointerCapture(e.pointerId);
  drag={dialog,pointer:e.pointerId,dx:e.clientX-box.left,dy:e.clientY-box.top,width:box.width};
 });
 document.addEventListener('pointermove',e=>{
  if(!drag||e.pointerId!==drag.pointer)return;
  drag.dialog.style.left=Math.min(Math.max(e.clientX-drag.dx,80-drag.width),innerWidth-80)+'px';
  drag.dialog.style.top=Math.min(Math.max(e.clientY-drag.dy,0),innerHeight-40)+'px';
 });
 const end=e=>{if(!drag||e.pointerId!==drag.pointer)return;const {dialog}=drag;drag=null;delete dialog.dataset.dragging;if(dialog.hasPointerCapture(e.pointerId))dialog.releasePointerCapture(e.pointerId);};
 document.addEventListener('pointerup',end);document.addEventListener('pointercancel',end);
 document.addEventListener('close',e=>{if(e.target.tagName==='DIALOG')restore(e.target);},true);
 addEventListener('resize',()=>{for(const dialog of document.querySelectorAll('dialog[data-dialog-moved]'))if(dialog!==drag?.dialog)restore(dialog);});
})();
