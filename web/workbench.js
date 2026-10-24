/* Shared reading workbench: stable commands, contextual navigation and a nonmodal inspector. */
(()=>{
 // Release pointer-operated action controls, preserving text editing and keyboard navigation.
 const actionControl='button,input[type=checkbox],input[type=radio],input[type=range],input[type=button],input[type=submit],summary,[role=button],[role=slider],[role=checkbox],[role=switch]';
 let pointerControl=null;
 document.addEventListener('pointerdown',e=>{const label=e.target.closest('label');pointerControl=e.target.closest(actionControl)||(label?.control?.matches(actionControl)?label.control:null);},true);
 const releasePointer=()=>{const control=pointerControl;pointerControl=null;setTimeout(()=>{if(control&&document.activeElement===control)control.blur();},0);};
 document.addEventListener('pointerup',releasePointer,true);
 document.addEventListener('pointercancel',releasePointer,true);
 document.addEventListener('click',e=>{const control=e.target.closest(actionControl);if(e.detail>0&&control&&document.activeElement===control)control.blur();});
 const side=$('workspace-sidebar'),corpusNav=document.createElement('section'),moduleNav=document.createElement('section');
 corpusNav.id='workbench-corpus-nav';moduleNav.id='workbench-module-nav';
 const preferences=document.createElement('details');preferences.id='workbench-preferences';preferences.innerHTML='<summary>工作区域与备份设置</summary>';
 for(const el of [...side.children]){if(el.matches('.brand,.language-panel'))continue;if(el.matches('.theme-panel,footer'))preferences.append(el);else corpusNav.append(el);}
 corpusNav.querySelector('.eyebrow')?.remove();
 const backupButton=corpusNav.querySelector('#backup');if(backupButton){$('management-backup').append(backupButton);backupButton.addEventListener('click',()=>$('management-dialog').close(),{capture:true});}
 side.append(corpusNav,moduleNav,preferences);
 const languageMore=document.createElement('details');languageMore.className='workbench-language-options';languageMore.innerHTML='<summary>语言选项</summary>';
 for(const el of [...languagePanel.children])if(el.matches('.language-tools,#export-language'))languageMore.append(el);languagePanel.append(languageMore);
 const placements=new Map();
 function relocate(el,target){if(!el)return;if(!placements.has(el)){const marker=document.createComment('workbench-origin');el.before(marker);placements.set(el,marker);}target.append(el);}
 function restore(){for(const [el,marker] of placements)marker.after(el);}
 const toolToggle=document.createElement('button');toolToggle.id='workbench-tool-toggle';toolToggle.textContent='收起工具';toolToggle.title='折叠或展开常用工具';workspaceTabs.append(toolToggle);
 let toolsHidden=false;try{toolsHidden=localStorage.getItem('corporium-tools-hidden')==='true';}catch{}
 function tools(){toolbarRow.hidden=toolsHidden;toolToggle.textContent=toolsHidden?'展开工具':'收起工具';toolToggle.setAttribute('aria-expanded',String(!toolsHidden));}tools();toolToggle.onclick=()=>{toolsHidden=!toolsHidden;tools();try{localStorage.setItem('corporium-tools-hidden',String(toolsHidden));}catch{}};
 const textActions=corpusWorkspace.querySelector('header .actions'),more=document.createElement('details');more.className='workbench-menu';more.innerHTML='<summary>文本操作</summary><div class="workbench-menu-items"></div>';
 textActions.append(more);for(const b of [...textActions.children])if(b!==more&&b.id!=='add')more.lastElementChild.append(b);
 const searchFilters=document.createElement('details');searchFilters.className='workbench-search-options';searchFilters.innerHTML='<summary>检索选项</summary>';const filters=corpusWorkspace.querySelector('.search .filters');filters.before(searchFilters);searchFilters.append(filters);
 // Keep abbreviations directly accessible; document editing belongs to text actions.
 makeDialog('text-reading-dialog','<h2>文本信息与阅读设置</h2><label id="text-reading-target">文本<select id="text-reading-text" aria-label="选择要编辑元信息的文本"></select></label><p id="text-reading-empty" role="status"></p><div id="text-reading-settings"></div>');
 for(const el of [...corpusWorkspace.children])if(el.matches('.metadata-panel:not(.language-details),#dialogue-controls'))$('text-reading-settings').append(el);
 languageDetails.classList.add('workbench-document-info');
 const textSettings=document.createElement('button');textSettings.type='button';textSettings.textContent='文本信息与阅读设置';textSettings.id='text-reading-open';more.lastElementChild.prepend(textSettings);
 function syncTextReadingTarget(){
  const target=$('text-reading-text'),current=texts.find(t=>t.id===selected);target.innerHTML='<option value="">选择要编辑的文本</option>'+texts.map(t=>'<option value="'+esc(t.id)+'">'+esc(t.title)+'</option>').join('');target.value=current?.id||'';target.disabled=!texts.length;
  $('text-reading-empty').hidden=!!current;$('text-reading-empty').textContent=texts.length?'请先选择要编辑元信息的文本。':'当前语言没有文本，可先新建或导入。';
 }
 textSettings.onclick=()=>{more.open=false;renderInfo();syncTextReadingTarget();if(!info.hidden)info.open=true;$('text-reading-dialog').showModal();};
 $('text-reading-text').onchange=safe(async()=>{const target=$('text-reading-text');target.disabled=true;try{await selectText(target.value);renderInfo();if(!info.hidden)info.open=true;}finally{syncTextReadingTarget();}});
 const sideActions=corpusNav.querySelector('.side-actions'),createMenu=document.createElement('details');createMenu.className='workbench-menu sidebar-create';createMenu.innerHTML='<summary class="language-icon" aria-label="新建">＋<span>新建</span></summary><div class="workbench-menu-items"></div>';
 const newFolder=$('new-folder'),newText=$('new');newFolder.textContent='新建文件夹';newText.textContent='新建文本';createMenu.lastElementChild.append(newFolder,newText);
 sideActions.replaceChildren(createMenu,$('import'),$('export'));sideActions.classList.add('sidebar-text-actions');preferences.before(sideActions);
 for(const button of createMenu.querySelectorAll('button'))button.addEventListener('click',()=>createMenu.open=false);
 const resultTools=document.createElement('div');resultTools.className='workbench-result-tools';corpusWorkspace.querySelector('.result-bar').before(resultTools);resultTools.append(corpusWorkspace.querySelector('.result-bar'),$('corpus-top-pagination'));
 const batch=document.createElement('details');batch.className='workbench-batch';batch.innerHTML='<summary>批量操作</summary>';const organize=corpusWorkspace.querySelector('.organize-bar');organize.before(batch);batch.append(organize);
 let navOwner=null;const navOffsets=new Map();
 function contextNav(){const navKey=activeLanguage+'\0'+workspace,changed=navOwner!==navKey;if(changed){if(navOwner)navOffsets.set(navOwner,moduleNav.scrollTop);restore();moduleNav.replaceChildren();}const contextual=['dictionary','survey','analysis','timeline'].includes(workspace);corpusNav.hidden=contextual;moduleNav.hidden=!contextual;sideActions.hidden=contextual;languageMore.hidden=['library','survey','timeline'].includes(workspace);languagePanel.hidden=languageMore.hidden;if(languageMore.hidden)languageMore.open=false;document.documentElement.dataset.workbench=workspace;
  if(changed&&workspace==='dictionary'){relocate(dictionaryPanel.querySelector('.search-row'),moduleNav);relocate(dictionaryPanel.querySelector('.dictionary-list-panel'),moduleNav);}
  if(changed&&workspace==='timeline')relocate($('tl-navigation'),moduleNav);
  if(changed&&workspace==='survey')relocate($('survey-navigation'),moduleNav);
  if(changed&&workspace==='analysis'){relocate($('analysis-records'),moduleNav);$('analysis-records').hidden=false;}
  if(changed){navOwner=navKey;moduleNav.scrollTop=navOffsets.get(navKey)||0;}
  $('auto-link-open').hidden=!['corpus','dictionary','library'].includes(workspace);
 }
 // Workspace titles share one compact header; keep dynamic subtitle nodes hidden for existing renderers.
 for(const id of ['corpus-workspace','dictionary-workspace','survey-workspace','analysis-workspace','timeline-workspace','grammar-workspace','example-library']){
  const root=$(id),title=root?.querySelector('h1');if(!title)continue;
  let heading=title.closest('header,.dictionary-heading,.survey-heading,.analysis-heading,.tl-heading');
  if(!heading){heading=document.createElement('div');title.before(heading);heading.append(title);const intro=heading.nextElementSibling;if(intro?.tagName==='P')intro.hidden=true;if(id==='example-library'){const back=$('library-survey-back');if(back.nextElementSibling?.tagName==='P')back.nextElementSibling.hidden=true;heading.append(back);}}
  heading.classList.add('workbench-heading');
 }
 const sentenceInspector=createSentenceInspector(main);
 window.corporiumSentenceInspector=sentenceInspector;
 // Reuse the complete dictionary form in the page so all morphology/tag controls retain their handlers.
 const lexEditor=$('lexeme-editor'),lexHost=document.createElement('section');lexHost.id='dictionary-inline-editor';dictionaryPanel.querySelector('.dictionary-columns').before(lexHost);
 const showLexEditor=lexEditor.showModal.bind(lexEditor),closeLexEditor=lexEditor.close.bind(lexEditor);
 lexEditor.showModal=function(){if(workspace!=='dictionary'){showLexEditor();return;}lexHost.append(lexEditor);lexEditor.classList.add('page-editor');lexEditor.setAttribute('aria-label','原位编辑词条');lexEditor.show();dockDialog(lexEditor);lexEditor.querySelector('.close').textContent='取消编辑';lexEditor.scrollIntoView({block:'start'});};
 const nestedEditors=[$('grammar-editor')];
 for(const dialog of nestedEditors){const show=dialog.showModal.bind(dialog),close=dialog.close.bind(dialog);dialog.showModal=function(){if(!lexEditor.classList.contains('page-editor')||!lexEditor.open){show();return;}lexHost.append(dialog);dialog.classList.add('page-editor','nested-page-editor');dialog.show();dockDialog(dialog);dialog.scrollIntoView({block:'start'});};dialog.close=function(...args){close(...args);dialog.classList.remove('page-editor','nested-page-editor');document.body.append(dialog);};}
 lexEditor.close=function(...args){for(const dialog of nestedEditors)if(dialog.classList.contains('nested-page-editor'))dialog.close();closeLexEditor(...args);clearLexemeEditState();lexEditor.classList.remove('page-editor');lexEditor.querySelector('.close').textContent='×';document.body.append(lexEditor);};
 async function leaveLexeme(){if(!lexEditor.open||!lexEditor.classList.contains('page-editor'))return true;if(lexemeDirty&&!await corporiumConfirm('放弃尚未保存的词条修改？'))return false;lexemeDirty=false;lexEditor.close();return true;}
 const previousLexeme=showLexeme;showLexeme=async function(id,...args){if(lexEditor.open&&lexEditor.classList.contains('page-editor')&&id!==editingLexeme?.id&&!await leaveLexeme())return;return previousLexeme(id,...args);};
 const previousEditLexeme=openLexemeEditor;openLexemeEditor=async function(...args){if(lexEditor.open&&lexEditor.classList.contains('page-editor')&&!await leaveLexeme())return;await previousEditLexeme(...args);};
 window.corporiumActivateWorkspace=()=>{window.corporiumApplyWorkspaceSidebar?.();contextNav();window.corporiumLayoutNotes?.();};
 const previousWorkspace=setWorkspace;setWorkspace=async function(name){if(name!==workspace&&!await leaveLexeme())throw new Error('已保留尚未保存的词条修改。');if(name!==workspace)await sentenceInspector.leave();if(name!==workspace)await window.corporiumCheckWorkspace?.(name);await previousWorkspace(name);};
 const previousLanguage=switchLanguage;switchLanguage=async function(id){if(id!==activeLanguage&&!await leaveLexeme()){$('language-select').value=activeLanguage;throw new Error('已保留尚未保存的词条修改。');}if(id!==activeLanguage)await sentenceInspector.leave();await previousLanguage(id);};
 function simplifySentences(){for(const section of document.querySelectorAll('.editable-example')){const commands=section.querySelector('.inline-tools');if(!commands||commands.querySelector('[data-inline-save]')||commands.dataset.workbench)continue;commands.dataset.workbench='true';commands.classList.add('sentence-actions');section.prepend(commands);const entry=section.closest('.entry,.lex-example');if(entry?.classList.contains('lex-example')&&!entry.querySelector('.entry-head')&&entry.firstElementChild?.tagName==='DIV'&&!entry.firstElementChild.contains(section))entry.firstElementChild.classList.add('entry-head');if(entry?.classList.contains('lex-example')&&!entry.querySelector('.entry-head')&&entry.firstElementChild?.matches('.lex-tag')){const head=document.createElement('div');head.className='entry-head';entry.prepend(head);while(head.nextElementSibling?.matches('strong.lex-tag,small'))head.append(head.nextElementSibling);}
   if(entry?.querySelector('.entry-head'))entry.classList.add('has-sentence-actions');const menu=document.createElement('details');menu.className='workbench-menu sentence-menu';menu.innerHTML='<summary aria-label="更多句子操作">更多</summary><div class="workbench-menu-items"></div>';const items=menu.lastElementChild;
   for(const button of [...commands.querySelectorAll('button')])if(!button.matches('[data-inline-start],[data-sentence-gloss]'))items.append(button);
   const edit=commands.querySelector('[data-inline-start]'),complete=commands.querySelector('[data-sentence-gloss]');if(edit&&complete)edit.after(complete);
   const header=section.closest('.entry')?.querySelector('.entry-head>div');if(header)for(const button of [...header.querySelectorAll('button')])items.append(button);
   if(items.children.length)commands.append(menu);
   if(section.closest('#timeline-workspace')){const ipa=section.querySelector(':scope > .ipa, :scope > .language-body > .ipa');if(ipa){const row=document.createElement('div');row.className='sentence-reading-head';ipa.before(row);row.append(ipa,commands);if(section.closest('#timeline-workspace'))for(const control of section.querySelectorAll(':scope > .sentence-audio, :scope > .collaborator-badge'))commands.prepend(control);}}
  }sentenceInspector.markOrigin();}
 new MutationObserver(records=>{if(records.some(r=>[...r.addedNodes].some(n=>n.nodeType===1&&(n.matches('.editable-example,.inline-tools')||n.querySelector('.editable-example,.inline-tools')))))simplifySentences();}).observe(main,{childList:true,subtree:true});
 // Keep menus open after a first click: destructive commands use double-click confirmation.
 document.addEventListener('click',e=>{for(const menu of document.querySelectorAll('.workbench-menu[open]'))if(!menu.contains(e.target))menu.open=false;});
 contextNav();simplifySentences();
})();
