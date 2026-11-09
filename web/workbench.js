// Cache only the relational states used by the hot brief/copy rules. Updating
// affected ancestors before paint avoids document-wide :has() invalidation.
function createWorkbenchStyleState(root,Observer=MutationObserver,decorateControls=()=>{}){
 const parents='.entry,.lex-example,.editable-example,.entry-head,#corpus-workspace';
 const editors=new Set(),html=root.ownerDocument?.documentElement;
 const set=(node,name,on)=>{if(node.classList.contains(name)!==on)node.classList.toggle(name,on);};
 const sync=node=>{
  if(node.matches('.entry,.lex-example')){set(node,'wb-has-editor',!!node.querySelector('.editable-example'));set(node,'wb-has-save',!!node.querySelector('[data-inline-save]'));}
  if(node.matches('.editable-example')){const saving=!!node.querySelector('[data-inline-save]');set(node,'wb-has-save',saving);if(saving)editors.add(node);else editors.delete(node);}
  if(node.matches('.entry-head'))set(node,'wb-has-copy-pick',!!node.querySelector('.formatted-copy-pick'));
  if(node.id==='corpus-workspace'){set(node,'wb-batch-owner',true);set(node,'wb-batch-open',!!node.querySelector('.workbench-batch[open]'));}
 };
 const syncEditors=()=>{if(!html)return;for(const node of editors)if(!node.isConnected||!node.matches('.editable-example'))editors.delete(node);set(html,'wb-editor-state',true);set(html,'wb-has-inline-save',editors.size>0);};
 const collect=(node,found)=>{if(node.nodeType!==1)return;if(node.matches(parents))found.add(node);for(const parent of node.querySelectorAll(parents))found.add(parent);};
 const semanticClass=value=>(value||'').split(/\s+/).filter(x=>x&&!x.startsWith('wb-')&&x!=='ui-optical-control'&&x!=='ui-optical-label').join(' ');
 const observer=new Observer(changes=>{
  const found=new Set();
  for(const change of changes){
   if(change.type==='attributes'&&change.attributeName==='hidden')continue;
   if(change.type==='attributes'&&change.attributeName==='class'&&semanticClass(change.oldValue)===semanticClass(change.target.getAttribute('class')))continue;
   // Caption wrapping cannot introduce an editor, a save command or a pick.
   if(change.type==='childList'&&[...change.addedNodes,...change.removedNodes].every(n=>n.nodeType===3||(n.nodeType===1&&n.tagName==='UI-LABEL'&&n.classList.contains('ui-button-label'))))continue;
   for(let node=change.target;node&&node!==root.parentElement;node=node.parentElement)if(node.nodeType===1&&node.matches(parents))found.add(node);
   if(change.type==='childList')for(const node of change.addedNodes)collect(node,found);
  }
  for(const node of found)if(node.isConnected)sync(node);
  syncEditors();
  decorateControls(changes);
 });
 const initial=new Set();collect(root,initial);for(const node of initial)sync(node);syncEditors();
 observer.observe(root,{childList:true,subtree:true,attributes:true,attributeOldValue:true,attributeFilter:['class','open','hidden','data-inline-save']});
 return observer;
}

// Give ordinary control text its own box, so font leading can be trimmed
// without moving icons or replacing buttons and their handlers. Reuse the
// existing mutation delivery; examine only changed controls and new subtrees.
function createInterfaceTextLabels(doc){
 const controls='button,.workbench-menu>summary,.folder-group>summary,#workspace-toolbar h1,.folder-name';
 const excluded='#ipa-keyboard,#app-status,.ui-content,.ui-list,.ui-list-item,.tl-pending,.inline-words,.inline-ipa,.inline-gloss,.inline-translation,.word-dictionary,.dictionary-wordform,.judgment-mark,.code-language,.tl-ipa,.tl-block,.tl-handle,.hp-row-grip,.lx-sort-handle,.font-stack-grip,[data-font-add],.font-stack-preview';
 const ignoreText='.ui-button-label,svg,script,style,input,select,textarea,kbd,.ipa,.tl-ipa,.gloss,.form,.translation,.grammar-label,sub,sup';
 const processed=new WeakSet(),pending=new Set();let queued=false;
 const visible=node=>{
  if(node.closest('[hidden]'))return false;
  for(let parent=node.parentElement;parent&&parent!==doc.body;parent=parent.parentElement){
   if(parent.tagName==='DIALOG'&&!parent.open)return false;
   if(parent.tagName==='DETAILS'&&!parent.open&&!parent.querySelector(':scope>summary')?.contains(node))return false;
  }
  return true;
 };
 const label=node=>{
  if(!node.isConnected||!visible(node)||node.closest(excluded)||node.matches('#undo-action,#redo-action,#history-toggle'))return;
  processed.add(node);
  const walker=doc.createTreeWalker(node,4),text=[];
  for(let t=walker.nextNode();t;t=walker.nextNode()){
   const owner=t.parentElement;
   if(!/[\p{L}\p{N}]/u.test(t.data)||owner.closest(ignoreText)||owner.closest(controls)!==node)continue;
   text.push(t);
  }
  if(!text.length)return;
  const script=(el,value)=>{const cjk=/[\u2e80-\u9fff\uac00-\ud7af\uf900-\ufaff]/u.test(value);if(cjk!==el.hasAttribute('data-ui-cjk'))el.toggleAttribute('data-ui-cjk',cjk);};
  if(!node.classList.contains('ui-optical-control'))node.classList.add('ui-optical-control');
  script(node,node.textContent);
  for(const t of text){
   const owner=t.parentElement;
   if(owner!==node){if(!owner.classList.contains('ui-optical-label'))owner.classList.add('ui-optical-label');script(owner,owner.textContent);continue;}
   // A neutral inline tag avoids legacy selectors that restyle every span in
   // a brand, title or counter. Flex/grid blockifies only its direct labels.
   const span=doc.createElement('ui-label');span.className='ui-button-label';if(node.tagName==='H1')span.classList.add('ui-title-label');script(span,t.data);
   t.replaceWith(span);span.append(t);
  }
 };
 const collect=(node,found)=>{
  if(node.nodeType!==1||node.matches('.ui-button-label')||node.closest(excluded))return;
  if(node.matches(controls)&&!processed.has(node))found.add(node);
  for(const control of node.querySelectorAll(controls))if(!processed.has(control))found.add(control);
 };
 const flush=()=>{queued=false;const batch=[...pending];pending.clear();for(const node of batch)label(node);};
 const schedule=()=>{if(pending.size&&!queued){queued=true;queueMicrotask(flush);}};
 // Menus are assembled by the other existing observers first. Their closed
 // commands are labelled when opened, instead of on every sentence render.
 collect(doc.body,pending);schedule();
 return changes=>{
  for(const change of changes){
   if(change.type==='attributes'){
    if((change.attributeName==='open'&&change.target.open)||(change.attributeName==='hidden'&&!change.target.hidden))collect(change.target,pending);
    continue;
   }
   if(change.type!=='childList')continue;
   if(change.target.nodeType===1&&change.target.tagName==='UI-LABEL'&&change.target.classList.contains('ui-button-label'))continue;
   if(change.addedNodes.length&&[...change.addedNodes].every(n=>n.nodeType===1&&n.tagName==='UI-LABEL'&&n.classList.contains('ui-button-label'))&&[...change.removedNodes].every(n=>n.nodeType===3))continue;
   const parent=change.target.nodeType===1?change.target:change.target.parentElement;
   const owner=parent?.closest('button,summary,h1,.folder-name');if(owner&&(owner.matches(controls)||processed.has(owner))){processed.delete(owner);pending.add(owner);}
   for(const node of change.addedNodes)collect(node,pending);
  }
  schedule();
 };
}

// Scroll anchoring is disabled on scrolling boxes during location restoration,
// not on every research glyph. Derive a conservative candidate set from the
// existing overflow rules, including inactive media/theme variants. Extra
// candidates are harmless: these properties do not create a scrolling box.
function createWorkbenchScrollRegions(doc,Observer=MutationObserver){
 const selectors=new Set(['input','select','textarea','dialog','[style*="overflow"]']),attributes=new Set(['class','id','style']);
 // Use positive keys from the subject compound where available. Dropping
 // ancestor/state restrictions creates a safe superset and avoids repeatedly
 // evaluating long theme/relational selectors for each inserted sentence.
 const candidates=text=>{
  const parts=[];let start=0,depth=0,quote='';
  for(let i=0;i<=text.length;i++){const c=text[i];if(quote){if(c==='\\')i++;else if(c===quote)quote='';continue;}if(c==='"'||c==="'"){quote=c;continue;}if(c==='('||c==='[')depth++;else if(c===')'||c===']')depth--;if((c===','&&!depth)||i===text.length){parts.push(text.slice(start,i).trim());start=i+1;}}
  for(const part of parts){if(part.includes('::'))continue;let last=0;depth=0;quote='';for(let i=0;i<part.length;i++){const c=part[i];if(quote){if(c==='\\')i++;else if(c===quote)quote='';continue;}if(c==='"'||c==="'"){quote=c;continue;}if(!depth&&/[\s>+~]/.test(c))last=i+1;if(c==='('||c==='[')depth++;else if(c===')'||c===']')depth--;}
   const subject=part.slice(last),key=subject.match(/^(?:[a-z][\w-]*)?[#.][\w-]+/i)?.[0]||subject.match(/^[a-z][\w-]*/i)?.[0];
   if(key)selectors.add(key);
   else if(/^:(?:is|where)\([\s\S]*\)$/.test(subject))candidates(subject.slice(subject.indexOf('(')+1,-1));
   else if(/^\[[\w-]+[^\]]*\]$/.test(subject)){const name=subject.match(/^\[([\w-]+)/)[1];attributes.add(name);selectors.add('['+name+']');}
   else selectors.add('*'); // A future unkeyed rule must remain correct.
  }
 };
 const read=rules=>{for(const rule of rules){
  if(rule.selectorText&&['overflow','overflow-x','overflow-y'].some(name=>{const value=rule.style.getPropertyValue(name);return value&&!/^(visible|clip|initial|unset)$/.test(value);})){
   // Pseudo-elements cannot be scroll restoration targets. Existing overflow
   // rules use ordinary selector lists, so ignore only pseudo-element rules.
   candidates(rule.selectorText);
  }else if(rule.cssRules)read(rule.cssRules);
 }};
 for(const sheet of doc.styleSheets)try{read(sheet.cssRules);}catch{/* Bundled application sheets are same-origin. */}
 const selector=[...selectors].join(',');
 const mark=root=>{if(root.nodeType===1&&root.matches(selector)&&!root.classList.contains('wb-scroll-region'))root.classList.add('wb-scroll-region');for(const node of root.querySelectorAll(selector))if(!node.classList.contains('wb-scroll-region'))node.classList.add('wb-scroll-region');};
 const observer=new Observer(changes=>{
  const roots=new Set();
  for(const change of changes){
   if(change.type==='attributes'){
    if(change.target.classList.contains('wb-scroll-region'))continue;
    if(change.attributeName==='style'&&!String(change.oldValue).includes('overflow')&&!change.target.getAttribute('style')?.includes('overflow'))continue;
    // Candidate keys depend only on the element, never on an ancestor state.
    // Attribute changes therefore cannot require rescanning its descendants.
    if(change.target.matches(selector))change.target.classList.add('wb-scroll-region');
   }else for(const node of change.addedNodes)if(node.nodeType===1&&!(node.tagName==='UI-LABEL'&&node.classList.contains('ui-button-label')&&!node.classList.contains('ui-title-label')))roots.add(node);
  }
  for(const root of roots){if(!root.isConnected)continue;let covered=false;for(let p=root.parentElement;p;p=p.parentElement)if(roots.has(p)){covered=true;break;}if(!covered)mark(root);}
 });
 mark(doc.body);
 observer.observe(doc.body,{childList:true,subtree:true,attributes:true,attributeOldValue:true,attributeFilter:[...attributes]});
 return observer;
}
// Add scope explanations without replacing manager buttons or their handlers.
function arrangeManagementEntries(entries,descriptions){
 for(const button of entries.querySelectorAll(':scope>button')){
  const key=button.dataset.managementEntry||button.id,description=descriptions[key];if(!description)continue;
  const row=document.createElement('div');row.className='management-entry';row.setAttribute('role','listitem');
  const note=document.createElement('p');note.className='ui-help';note.id='management-note-'+key;note.textContent=description;
  const ids=(button.getAttribute('aria-describedby')||'').split(/\s+/).filter(Boolean);button.setAttribute('aria-describedby',[...new Set([...ids,note.id])].join(' '));
  button.before(row);row.append(button,note);
 }
}
// Sentence menus keep their original buttons and event ancestry. A native
// popover escapes clipped cards/scroll panes without moving the research UI.
function sentenceMenuPlacement(anchor,size,viewport,gap){
 const leftEdge=(viewport.left||0)+gap,topEdge=(viewport.top||0)+gap;
 const rightEdge=(viewport.left||0)+viewport.width-gap,bottomEdge=(viewport.top||0)+viewport.height-gap;
 const above=Math.max(0,Math.min(anchor.top-gap,bottomEdge)-topEdge),below=Math.max(0,bottomEdge-Math.max(anchor.bottom+gap,topEdge));
 const up=size.height>below&&(size.height<=above||above>below),maxHeight=up?above:below;
 const height=Math.min(size.height,maxHeight),width=Math.min(size.width,Math.max(0,rightEdge-leftEdge));
 return {left:Math.max(leftEdge,Math.min(anchor.right-width,rightEdge-width)),top:up?Math.max(topEdge,anchor.top-gap-height):Math.max(topEdge,anchor.bottom+gap),maxHeight,maxWidth:Math.max(0,rightEdge-leftEdge),up};
}
function createSentenceMenus(doc=document,win=window){
 let active=null,frame=0,sequence=0;
 const buttons=items=>[...items.querySelectorAll('button')].filter(b=>!b.disabled&&!b.hidden&&b.getClientRects().length);
 function close(){const old=active;if(!old)return;active=null;old.menu.open=false;old.summary.setAttribute('aria-expanded','false');if(old.items.hidePopover&&old.items.matches(':popover-open'))old.items.hidePopover();}
 function position(){
  frame=0;if(!active)return;
  const {menu,summary,items}=active,r=summary.getBoundingClientRect(),view=win.visualViewport;
  const viewport={left:view?.offsetLeft||0,top:view?.offsetTop||0,width:view?.width||doc.documentElement.clientWidth,height:view?.height||doc.documentElement.clientHeight};
  if(!menu.isConnected||!menu.open||!r.width||!r.height||r.bottom<=viewport.top||r.top>=viewport.top+viewport.height||r.right<=viewport.left||r.left>=viewport.left+viewport.width){close();return;}
  // Close when the trigger scrolls out of an inner panel, even though the
  // popover itself is deliberately outside that panel's clipping boundary.
  for(let parent=summary.parentElement;parent&&parent!==doc.body;parent=parent.parentElement){
   const style=win.getComputedStyle(parent),box=parent.getBoundingClientRect();
   if((/(auto|scroll|hidden|clip)/.test(style.overflowY)&&(r.bottom<=box.top||r.top>=box.bottom))||(/(auto|scroll|hidden|clip)/.test(style.overflowX)&&(r.right<=box.left||r.left>=box.right))){close();return;}
  }
  const gap=(parseFloat(win.getComputedStyle(doc.documentElement).fontSize)||16)/2;
  Object.assign(items.style,{position:'fixed',inset:'auto',margin:'0',boxSizing:'border-box',width:'max-content',minWidth:Math.min(190,Math.max(0,viewport.width-2*gap))+'px',maxWidth:Math.max(0,viewport.width-2*gap)+'px',overflowY:'auto',overflowX:'hidden'});
  const box=items.getBoundingClientRect(),size={width:box.width,height:items.scrollHeight+box.height-items.clientHeight},p=sentenceMenuPlacement(r,size,viewport,gap);
  Object.assign(items.style,{left:p.left+'px',top:p.top+'px',maxHeight:p.maxHeight+'px'});items.dataset.menuDirection=p.up?'up':'down';
 }
 function schedule(){if(active&&!frame)frame=win.requestAnimationFrame(position);}
 function mount(menu){
  if(menu.dataset.floatingSentenceMenu)return;menu.dataset.floatingSentenceMenu='true';
  const summary=menu.querySelector(':scope>summary'),items=menu.querySelector(':scope>.workbench-menu-items');
  items.dataset.floatingSentenceMenu='true';items.id||='sentence-menu-'+(++sequence);summary.setAttribute('aria-controls',items.id);summary.setAttribute('aria-expanded','false');
  if(items.showPopover)items.setAttribute('popover','manual');
  function open(){
   const fresh=active?.menu!==menu;if(fresh){close();active={menu,summary,items};}
   summary.setAttribute('aria-expanded','true');
   if(items.showPopover&&!items.matches(':popover-open'))items.showPopover();position();if(fresh)items.scrollTop=0;
  }
  menu.addEventListener('toggle',e=>{if(e.target!==menu)return;if(menu.open)open();else if(active?.menu===menu)close();});
  summary.addEventListener('keydown',e=>{if(!['ArrowDown','ArrowUp'].includes(e.key))return;e.preventDefault();menu.open=true;open();const rows=buttons(items);(e.key==='ArrowUp'?rows.at(-1):rows[0])?.focus();});
  items.addEventListener('keydown',e=>{if(!['ArrowDown','ArrowUp','Home','End'].includes(e.key))return;const rows=buttons(items);if(!rows.length)return;e.preventDefault();const current=rows.indexOf(doc.activeElement),index=e.key==='Home'?0:e.key==='End'?rows.length-1:(current+(e.key==='ArrowUp'?-1:1)+rows.length)%rows.length;rows[index].focus();});
  menu.addEventListener('focusout',()=>queueMicrotask(()=>{if(active?.menu===menu&&!menu.contains(doc.activeElement))close();}));
 }
 doc.addEventListener('keydown',e=>{if(e.key==='Escape'&&active){e.preventDefault();e.stopPropagation();const target=active.summary;close();target.focus({preventScroll:true});}},true);
 doc.addEventListener('scroll',e=>{if(!active?.items.contains(e.target))schedule();},true);win.addEventListener('resize',schedule);win.visualViewport?.addEventListener('resize',schedule);win.visualViewport?.addEventListener('scroll',schedule);
 new MutationObserver(()=>{if(active&&!active.menu.isConnected)close();}).observe(doc.body,{childList:true,subtree:true});
 return {mount,close};
}
/* Shared reading workbench: stable commands, contextual navigation and a nonmodal inspector. */
createWorkbenchStyleState(document.body,MutationObserver,createInterfaceTextLabels(document));
createWorkbenchScrollRegions(document);
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
 const preferences=document.createElement('details');preferences.id='workbench-preferences';preferences.innerHTML=(globalThis.CorporiumI18n?.f("e33244a4ca02ca",()=>[])??'<summary>工作区域与备份设置</summary>');
 for(const el of [...side.children]){if(el.matches('.brand,.language-panel'))continue;if(el.matches('.theme-panel,footer'))preferences.append(el);else corpusNav.append(el);}
 corpusNav.querySelector('.eyebrow')?.remove();
 const backupButton=corpusNav.querySelector('#backup');if(backupButton){$('management-backup').append(backupButton);backupButton.addEventListener('click',()=>$('management-dialog').close(),{capture:true});}
 side.append(corpusNav,moduleNav,preferences);
 const languageMore=document.createElement('details');languageMore.className='workbench-language-options';languageMore.innerHTML=(globalThis.CorporiumI18n?.f("1bbb3177589b82",()=>[])??'<summary>语言选项</summary>');
 for(const el of [...languagePanel.children])if(el.matches('.language-tools,#export-language'))languageMore.append(el);languagePanel.append(languageMore);
 const placements=new Map();
 function relocate(el,target){if(!el)return;if(!placements.has(el)){const marker=document.createComment('workbench-origin');el.before(marker);placements.set(el,marker);}target.append(el);}
 function restore(){for(const [el,marker] of placements)marker.after(el);}
 const toolToggle=document.createElement('button');toolToggle.id='workbench-tool-toggle';toolToggle.textContent=(globalThis.CorporiumI18n?.f("1f2c61ff49d309",()=>[])??'收起工具');toolToggle.title=(globalThis.CorporiumI18n?.f("d125869384d763",()=>[])??'折叠或展开常用工具');workspaceTabs.append(toolToggle);
 let toolsHidden=false;try{toolsHidden=localStorage.getItem('corporium-tools-hidden')==='true';}catch{}
 function tools(){toolbarRow.hidden=toolsHidden;toolToggle.textContent=toolsHidden?(globalThis.CorporiumI18n?.f("6083d5b7698e53",()=>[])??'展开工具'):(globalThis.CorporiumI18n?.f("197adefbe26c04",()=>[])??'收起工具');toolToggle.setAttribute('aria-expanded',String(!toolsHidden));}tools();toolToggle.onclick=()=>{toolsHidden=!toolsHidden;tools();try{localStorage.setItem('corporium-tools-hidden',String(toolsHidden));}catch{}};
 const textActions=corpusWorkspace.querySelector('header .actions'),more=document.createElement('details');more.className='workbench-menu';more.innerHTML=(globalThis.CorporiumI18n?.f("4e5a02ef0f1ffb",()=>[])??'<summary>文本操作</summary><div class="workbench-menu-items"></div>');
 $('add').classList.add('primary');$('library-new')?.classList.add('primary');$('library-add')?.classList.add('primary');
 textActions.classList.add('text-reading-actions');textActions.append(more);for(const b of [...textActions.children])if(b!==more&&b.id!=='add')more.lastElementChild.append(b);
 const textVolume=document.createElement('span');textVolume.id='text-playback-volume';textVolume.hidden=true;more.before(textVolume);
 const refreshTextVolume=window.CorporiumVolume.mountInline(textVolume,()=>selected?{key:'text:'+selected,label:globalThis.CorporiumI18n?.ui('文本音量','Text volume')??'文本音量'}:null);
 let textVolumeRequest=0;
 async function syncTextVolume(){const ticket=++textVolumeRequest,id=selected;textVolume.hidden=true;if(!id)return;try{const result=await api('text-audio?id='+encodeURIComponent(id));if(ticket!==textVolumeRequest||selected!==id)return;textVolume.hidden=!result.has_audio;refreshTextVolume();}catch{/* Playback controls remain usable if discovery fails. */}}
 const selectVolumeText=selectText;selectText=async function(...args){textVolumeRequest++;textVolume.hidden=true;await selectVolumeText(...args);};
 const loadVolumeTexts=loadTexts;loadTexts=async function(...args){await loadVolumeTexts(...args);void syncTextVolume();};
 document.addEventListener('corporium-alignment-changed',syncTextVolume);void syncTextVolume();
 const searchFilters=document.createElement('details');searchFilters.className='workbench-search-options';searchFilters.innerHTML=(globalThis.CorporiumI18n?.f("b5a7f930ac5d1f",()=>[])??'<summary>检索选项</summary>');const filters=corpusWorkspace.querySelector('.search .filters');filters.before(searchFilters);searchFilters.append(filters);
 // Keep abbreviations directly accessible; document editing belongs to text actions.
 makeDialog('text-reading-dialog',(globalThis.CorporiumI18n?.f("e15a9ba384ece7",()=>[])??'<h2>文本信息与阅读设置</h2><label id="text-reading-target">文本<select id="text-reading-text" aria-label="选择要编辑元信息的文本"></select></label><p id="text-reading-empty" role="status"></p><div id="text-reading-settings"></div>'));
 for(const el of [...corpusWorkspace.children])if(el.matches('.metadata-panel:not(.language-details),#dialogue-controls'))$('text-reading-settings').append(el);
 languageDetails.classList.add('workbench-document-info');
 const textSettings=document.createElement('button');textSettings.type='button';textSettings.textContent=(globalThis.CorporiumI18n?.f("14d0bdd87b5184",()=>[])??'文本信息与阅读设置');textSettings.id='text-reading-open';more.lastElementChild.prepend(textSettings);
 function syncTextReadingTarget(){
  const target=$('text-reading-text'),current=texts.find(t=>t.id===selected);target.innerHTML=(globalThis.CorporiumI18n?.f("cda578f7831aae",()=>[texts.map(t=>'<option value="'+esc(t.id)+'">'+esc(t.title)+'</option>').join('')])??'<option value="">选择要编辑的文本</option>'+texts.map(t=>'<option value="'+esc(t.id)+'">'+esc(t.title)+'</option>').join(''));target.value=current?.id||'';target.disabled=!texts.length;
  $('text-reading-empty').hidden=!!current;$('text-reading-empty').textContent=texts.length?(globalThis.CorporiumI18n?.f("3b7b502b897a48",()=>[])??'请先选择要编辑元信息的文本。'):(globalThis.CorporiumI18n?.f("ab5f3d985b43e1",()=>[])??'当前语言没有文本，可先新建或导入。');
 }
 textSettings.onclick=()=>{more.open=false;renderInfo();syncTextReadingTarget();if(!info.hidden)info.open=true;$('text-reading-dialog').showModal();};
 $('text-reading-text').onchange=safe(async()=>{const target=$('text-reading-text');target.disabled=true;try{await selectText(target.value);renderInfo();if(!info.hidden)info.open=true;}finally{syncTextReadingTarget();}});
 const sideActions=corpusNav.querySelector('.side-actions'),createMenu=document.createElement('details');createMenu.className='workbench-menu sidebar-create';createMenu.innerHTML=(globalThis.CorporiumI18n?.f("fdf81ab4a6e0a5",()=>[])??'<summary class="language-icon" aria-label="新建">＋<span>新建</span></summary><div class="workbench-menu-items"></div>');
 const newFolder=$('new-folder'),newText=$('new');newFolder.textContent=(globalThis.CorporiumI18n?.f("ce05b9d4eee7a8",()=>[])??'新建文件夹');newText.textContent=(globalThis.CorporiumI18n?.f("434b902ff4e0a4",()=>[])??'新建文本');createMenu.lastElementChild.append(newFolder,newText);
 sideActions.replaceChildren(createMenu,$('import'),$('export'));sideActions.classList.add('sidebar-text-actions');preferences.before(sideActions);
 for(const button of createMenu.querySelectorAll('button'))button.addEventListener('click',()=>createMenu.open=false);
 const resultTools=document.createElement('div');resultTools.className='workbench-result-tools';corpusWorkspace.querySelector('.result-bar').before(resultTools);resultTools.append(corpusWorkspace.querySelector('.result-bar'),$('corpus-top-pagination'));
 const batch=document.createElement('details');batch.className='workbench-batch';batch.innerHTML=(globalThis.CorporiumI18n?.f("1a9a61ddc86608",()=>[])??'<summary>批量操作</summary>');const organize=corpusWorkspace.querySelector('.organize-bar');organize.before(batch);batch.append(organize);
 let navOwner=null;const navOffsets=new Map();
 function contextNav(){const navKey=activeLanguage+'\0'+workspace,changed=navOwner!==navKey;if(changed){if(navOwner)navOffsets.set(navOwner,moduleNav.scrollTop);restore();moduleNav.replaceChildren();}const contextual=['dictionary','survey','analysis','timeline'].includes(workspace);const hide=(node,value)=>{if(node.hidden!==value)node.hidden=value;};hide(corpusNav,contextual);hide(moduleNav,!contextual);hide(sideActions,contextual);hide(languageMore,['library','survey','timeline'].includes(workspace));hide(languagePanel,languageMore.hidden);if(languageMore.hidden&&languageMore.open)languageMore.open=false;if(document.documentElement.dataset.workbench!==workspace)document.documentElement.dataset.workbench=workspace;
  if(changed&&workspace==='dictionary'){relocate(dictionaryPanel.querySelector('.search-row'),moduleNav);relocate(dictionaryPanel.querySelector('.dictionary-list-panel'),moduleNav);}
  if(changed&&workspace==='timeline')relocate($('tl-navigation'),moduleNav);
  if(changed&&workspace==='survey')relocate($('survey-navigation'),moduleNav);
  if(changed&&workspace==='analysis'){relocate($('analysis-records'),moduleNav);$('analysis-records').hidden=false;}
  if(changed){navOwner=navKey;moduleNav.scrollTop=navOffsets.get(navKey)||0;}
  const auto=$('auto-link-open'),hidden=!['corpus','dictionary','library'].includes(workspace);if(auto.hidden!==hidden)auto.hidden=hidden;
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
 lexEditor.showModal=function(){if(workspace!=='dictionary'){showLexEditor();return;}lexHost.append(lexEditor);lexEditor.classList.add('page-editor');lexEditor.setAttribute('aria-label',(globalThis.CorporiumI18n?.f("7b5a3006502ede",()=>[])??'原位编辑词条'));lexEditor.show();dockDialog(lexEditor);lexEditor.querySelector('.close').textContent=(globalThis.CorporiumI18n?.f("463c2d32a1ec03",()=>[])??'取消编辑');lexEditor.scrollIntoView({block:'start'});};
 const nestedEditors=[$('grammar-editor')];
 for(const dialog of nestedEditors){const show=dialog.showModal.bind(dialog),close=dialog.close.bind(dialog);dialog.showModal=function(){if(!lexEditor.classList.contains('page-editor')||!lexEditor.open){show();return;}lexHost.append(dialog);dialog.classList.add('page-editor','nested-page-editor');dialog.show();dockDialog(dialog);dialog.scrollIntoView({block:'start'});};dialog.close=function(...args){close(...args);dialog.classList.remove('page-editor','nested-page-editor');document.body.append(dialog);};}
 lexEditor.close=function(...args){for(const dialog of nestedEditors)if(dialog.classList.contains('nested-page-editor'))dialog.close();closeLexEditor(...args);clearLexemeEditState();lexEditor.classList.remove('page-editor');lexEditor.querySelector('.close').textContent='×';document.body.append(lexEditor);};
 async function leaveLexeme(){if(!lexEditor.open||!lexEditor.classList.contains('page-editor'))return true;if(lexemeDirty&&!await corporiumConfirm((globalThis.CorporiumI18n?.f("851ce82e0a93ad",()=>[])??'放弃尚未保存的词条修改？')))return false;lexemeDirty=false;lexEditor.close();return true;}
 const previousLexeme=showLexeme;showLexeme=async function(id,...args){if(lexEditor.open&&lexEditor.classList.contains('page-editor')&&id!==editingLexeme?.id&&!await leaveLexeme())return;return previousLexeme(id,...args);};
 const previousEditLexeme=openLexemeEditor;openLexemeEditor=async function(...args){if(lexEditor.open&&lexEditor.classList.contains('page-editor')&&!await leaveLexeme())return;await previousEditLexeme(...args);};
 window.corporiumActivateWorkspace=()=>{window.corporiumApplyWorkspaceSidebar?.();contextNav();window.corporiumLayoutNotes?.();};
 const previousWorkspace=setWorkspace;setWorkspace=async function(name){if(name!==workspace&&!await leaveLexeme())throw new Error((globalThis.CorporiumI18n?.f("64cc1185655d2a",()=>[])??'已保留尚未保存的词条修改。'));if(name!==workspace)await sentenceInspector.leave();if(name!==workspace)await window.corporiumCheckWorkspace?.(name);await previousWorkspace(name);};
 const previousLanguage=switchLanguage;switchLanguage=async function(id){if(id!==activeLanguage&&!await leaveLexeme()){$('language-select').value=activeLanguage;throw new Error((globalThis.CorporiumI18n?.f("5b76bc9cdfd599",()=>[])??'已保留尚未保存的词条修改。'));}if(id!==activeLanguage)await sentenceInspector.leave();await previousLanguage(id);};
 const sentenceMenus=createSentenceMenus();
 function simplifySentences(){for(const section of document.querySelectorAll('.editable-example')){const commands=section.querySelector('.inline-tools');if(!commands||commands.querySelector('[data-inline-save]')||commands.dataset.workbench)continue;commands.dataset.workbench='true';commands.classList.add('sentence-actions');section.prepend(commands);const entry=section.closest('.example-group-member,.entry,.lex-example');if(entry?.classList.contains('lex-example')&&!entry.querySelector('.entry-head')&&entry.firstElementChild?.tagName==='DIV'&&!entry.firstElementChild.contains(section))entry.firstElementChild.classList.add('entry-head');if(entry?.classList.contains('lex-example')&&!entry.querySelector('.entry-head')&&entry.firstElementChild?.matches('.lex-tag')){const head=document.createElement('div');head.className='entry-head';entry.prepend(head);while(head.nextElementSibling?.matches('strong.lex-tag,small'))head.append(head.nextElementSibling);}
   if(entry?.querySelector('.entry-head'))entry.classList.add('has-sentence-actions');const menu=document.createElement('details');menu.className='workbench-menu sentence-menu';menu.innerHTML=(globalThis.CorporiumI18n?.f("061376d2b431df",()=>[])??'<summary aria-label="更多句子操作">更多</summary><div class="workbench-menu-items"></div>');const items=menu.lastElementChild;
   if(section.dataset.libraryNumber&&!entry?.classList.contains('independent-library-entry')&&!entry?.querySelector('.example-source-number')){const badge=document.createElement('span');badge.className='example-source-number';badge.textContent=(globalThis.CorporiumI18n?.f("c16dcb634f3aed",()=>[section.dataset.libraryNumber])??'例 '+section.dataset.libraryNumber);const caption=entry?.querySelector(':scope>.entry-head>span');if(caption){badge.append(' · ');caption.prepend(badge);}else commands.prepend(badge);}
   for(const button of [...commands.querySelectorAll('button')])if(!button.matches('[data-inline-start],[data-sentence-gloss]'))items.append(button);
   const edit=commands.querySelector('[data-inline-start]'),complete=commands.querySelector('[data-sentence-gloss]');if(edit&&complete)edit.after(complete);
   // A sentence can have a source header and a separate independent-example
   // header. Gather every header belonging to this sentence, including its
   // punctuation checkbox, without taking commands from another group member.
   for(const head of entry?.querySelectorAll('.entry-head')||[]){if(head.closest('.example-group-member,.entry,.lex-example')!==entry)continue;for(const control of [...head.querySelectorAll('button')])items.append(control);if(head.classList.contains('example-group-member-actions')){const number=head.querySelector('.example-source-number');if(number)commands.prepend(number);head.remove();}}
   if(items.children.length){commands.append(menu);sentenceMenus.mount(menu);}
   // Notes and commands share one footer row. The original disclosure remains
   // intact, so opening notes gives its body the full width below that row.
   if(section.closest('#results,#library-results')){
    commands.classList.add('sentence-footer-actions');const footer=document.createElement('div');footer.className='sentence-footer';
    const notes=section.querySelector('.example-notes');if(notes){notes.before(footer);footer.append(notes);}else section.append(footer);
    footer.append(commands);
   }
   if(section.closest('#timeline-workspace')){const ipa=section.querySelector(':scope > .ipa, :scope > .language-body > .ipa');if(ipa){const row=document.createElement('div');row.className='sentence-reading-head';ipa.before(row);row.append(CorporiumLineSpacing.readingLines(ipa),commands);if(section.closest('#timeline-workspace'))for(const control of section.querySelectorAll(':scope > .sentence-audio, :scope > .collaborator-badge'))commands.prepend(control);}}
  }sentenceInspector.markOrigin();}
 new MutationObserver(records=>{if(records.some(r=>[...r.addedNodes].some(n=>n.nodeType===1&&(n.matches('.editable-example,.inline-tools')||n.querySelector('.editable-example,.inline-tools')))))simplifySentences();}).observe(document.body,{childList:true,subtree:true});
 // Keep menus open after a first click: destructive commands use double-click confirmation.
 document.addEventListener('click',e=>{for(const menu of document.querySelectorAll('.workbench-menu[open]'))if(!menu.contains(e.target))menu.open=false;});
 contextNav();simplifySentences();
})();
/* Application shell: identity, modules and global commands share one top bar; each module's
   title and tools share one sticky row; project, save state and background work sit in a status bar. */
(()=>{
 const ui=(zh,en)=>globalThis.CorporiumI18n?.ui(zh,en)??zh;
 const icon=d=>'<svg viewBox="0 0 24 24" width="17" height="17" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true">'+d+'</svg>';
 const paths={search:'<circle cx="11" cy="11" r="7"/><path d="m20 20-3.5-3.5"/>',moon:'<path d="M20 14.5A8 8 0 0 1 9.5 4a8 8 0 1 0 10.5 10.5z"/>',sun:'<circle cx="12" cy="12" r="4"/><path d="M12 2v2M12 20v2M4.9 4.9l1.4 1.4M17.7 17.7l1.4 1.4M2 12h2M20 12h2M4.9 19.1l1.4-1.4M17.7 6.3l1.4-1.4"/>',enter:'<path d="M9 10 4 15l5 5"/><path d="M20 4v7a4 4 0 0 1-4 4H4"/>'};
 const root=document.documentElement;root.dataset.shell='workbench';
 const bar=document.createElement('header');bar.id='app-bar';
 const identity=document.createElement('div');identity.className='app-identity';
 const brand=$('workspace-sidebar').querySelector('.brand'),languageRow=brand.querySelector('.brand-language-row');
 // One keyboard-accessible language button owns the full name and menu arrow.
 languageRow.insertBefore($('brand-native'),brandLanguagePicker);brandLanguagePicker.prepend($('brand-language'));
 brandLanguagePicker.setAttribute('aria-describedby','brand-language');identity.append(brand);
 languageRow.title=brandLanguagePicker.title;
 languageRow.addEventListener('click',e=>{if(!e.target.closest('.brand-language-picker'))brandLanguagePicker.click();});
 // Language actions belong to the language menu, after the list of languages.
 const languageTools=document.querySelector('.workbench-language-options .language-tools');
 if(languageTools){languageTools.classList.add('brand-language-tools');new MutationObserver(()=>{if(!brandLanguageMenu.hidden&&languageTools.parentElement!==brandLanguageMenu)brandLanguageMenu.append(languageTools);}).observe(brandLanguageMenu,{attributes:true,attributeFilter:['hidden'],childList:true});
  languageTools.addEventListener('click',e=>{if(e.target.closest('button'))closeBrandLanguageMenu();});}
 const tools=document.createElement('div');tools.className='app-bar-tools';
 const command=document.createElement('button');command.type='button';command.id='app-command';command.setAttribute('aria-haspopup','dialog');command.setAttribute('aria-expanded','false');
 command.innerHTML=icon(paths.search)+'<span>'+esc(ui('搜索文本、词条或命令','Search texts, entries or commands'))+'</span><kbd>Ctrl K</kbd>';
 const separator=document.createElement('span');separator.className='app-bar-separator';separator.setAttribute('aria-hidden','true');
 const themeToggle=document.createElement('button');themeToggle.type='button';themeToggle.id='app-theme-toggle';
 historyToggle.title=ui('历史记录与撤销步数','History and undo steps');
 tools.append(command,$('undo-action'),$('redo-action'),historyToggle,separator,themeToggle);
  tools.prepend($('management-open'));
 bar.append(identity,workspaceTabs,tools,historyPanel);
 document.body.prepend(bar);
 $('workbench-tool-toggle').hidden=true;toolbarRow.hidden=false;
 const closeHistory=()=>{if(historyPanel.hidden)return;historyPanel.hidden=true;historyToggle.setAttribute('aria-expanded','false');};
 document.addEventListener('pointerdown',e=>{if(!historyPanel.contains(e.target)&&!historyToggle.contains(e.target))closeHistory();});
 document.addEventListener('keydown',e=>{if(e.key==='Escape'&&!historyPanel.hidden){closeHistory();historyToggle.focus();}});
 // Day/night switching keeps the theme menu, its saved preference and every listener authoritative.
 const themeSelect=$('theme-select'),darkThemes=['dawoid','night'];
 function syncTheme(){const dark=darkThemes.includes(root.dataset.theme);themeToggle.innerHTML=icon(dark?paths.sun:paths.moon);themeToggle.title=dark?ui('切换到日间（Docoid）','Switch to the day theme (Docoid)'):ui('切换到夜间（DAWoid）','Switch to the night theme (DAWoid)');themeToggle.setAttribute('aria-label',themeToggle.title);}
 themeToggle.onclick=()=>{themeSelect.value=darkThemes.includes(root.dataset.theme)?'docoid':'dawoid';themeSelect.dispatchEvent(new Event('change'));};
 themeSelect.addEventListener('change',syncTheme);syncTheme();
 // Reading mode is a two-state choice; the original checkbox stays the single source of truth.
 const brief=$('brief-mode'),briefChoice=document.createElement('div');briefChoice.className='app-segmented brief-choice';briefChoice.setAttribute('role','group');briefChoice.setAttribute('aria-label',ui('阅读模式','Reading mode'));
 briefChoice.innerHTML='<button type="button" data-brief="false">'+esc(ui('完整','Full'))+'</button><button type="button" data-brief="true">'+esc(ui('简要','Brief'))+'</button>';
 const syncBrief=()=>{for(const b of briefChoice.children)b.setAttribute('aria-pressed',String((b.dataset.brief==='true')===brief.checked));};
 briefChoice.onclick=e=>{const b=e.target.closest('[data-brief]');if(!b)return;const want=b.dataset.brief==='true';if(brief.checked!==want){brief.checked=want;brief.dispatchEvent(new Event('change',{bubbles:true}));}syncBrief();};
 brief.addEventListener('change',syncBrief);briefLabel.classList.add('brief-source');briefLabel.after(briefChoice);syncBrief();
 // The active module's heading joins the shared tools in one sticky row; it returns home on a switch.
 const roots={corpus:'corpus-workspace',dictionary:'dictionary-workspace',library:'example-library',grammar:'grammar-workspace',survey:'survey-workspace',timeline:'timeline-workspace',analysis:'analysis-workspace'};
 const headings=new Map(),homes=new Map();let mounted=null;
 function headingFor(name){
  if(!headings.has(name)){const heading=$(roots[name])?.querySelector(':scope>.workbench-heading');if(heading){const marker=document.createComment('module-heading');heading.before(marker);homes.set(heading,marker);heading.dataset.module=name;}headings.set(name,heading||null);}
  return headings.get(name);
 }
 function mountModuleToolbar(){
  const heading=headingFor(workspace);
  if(mounted&&mounted!==heading){homes.get(mounted).after(mounted);mounted.classList.remove('module-heading');}
  if(heading&&mounted!==heading){toolbar.prepend(heading);heading.classList.add('module-heading');}
  mounted=heading;
  if(workspace==='dictionary'&&$('morpheme-new')&&$('morpheme-new').parentElement!==$('new-lexeme')?.parentElement)$('new-lexeme')?.after($('morpheme-new'));
 }
 const activate=window.corporiumActivateWorkspace;window.corporiumActivateWorkspace=()=>{activate();mountModuleToolbar();};
 // Later modules still read their headings in place while loading.
 if(document.readyState==='loading')document.addEventListener('DOMContentLoaded',mountModuleToolbar,{once:true});else mountModuleToolbar();
 // Status bar: project, save state, the latest status message, playback and background work.
 const status=document.createElement('footer');status.id='app-status';
 status.innerHTML='<div class="app-status-project"></div><span class="app-status-save" data-state="saved"><i aria-hidden="true"></i><span></span></span><span class="app-status-message" role="status" aria-live="polite"></span><span class="app-status-fill"></span><span class="app-status-player" hidden></span><span class="app-status-task"></span><span class="app-status-ipa" aria-hidden="true"></span>';
 const statusBrand=document.createElement('span');statusBrand.className='app-status-brand';
 const homeLink=$('brand-home');homeLink.title=ui('返回首页','Return to home');homeLink.setAttribute('aria-label',ui('Corporium · 返回首页','Corporium · Return to home'));
 const version=document.createElement('button');version.type='button';version.id='app-status-version';version.textContent=ui('版本','Version');version.title=ui('关于与许可','About and licenses');version.setAttribute('aria-label',version.title);
 statusBrand.append(homeLink,version);status.prepend(statusBrand);
 document.body.append(status);
 const save=status.querySelector('.app-status-save'),message=status.querySelector('.app-status-message'),player=status.querySelector('.app-status-player'),task=status.querySelector('.app-status-task');
  const dirty=()=>{try{return Boolean(($('lexeme-editor')?.open&&lexemeDirty)||($('editor')?.open&&entryEditorDirty())||infoDirty||[...inlineDrafts.values()].some(d=>d.dirty||d.saving)||window.corporiumGlobalSettingsDirty?.()||window.corporiumMorphemeDirty?.()||window.corporiumTimelineDirty?.()||window.corporiumSurveyDirty?.()||window.corporiumNotesDirty?.()||window.corporiumCodesDirty?.());}catch{return null;}};
 let revision=null,savedAt=null;
 const put=(el,text)=>{if(el.textContent===text)return;const node=el.firstChild;if(node?.nodeType===3&&node===el.lastChild)node.data=text;else el.textContent=text;};
 function syncStatus(){
  const current=window.corporiumWorkspaceRevision;if(current!==undefined){if(revision!==null&&current!==revision)savedAt=new Date();revision=current;}
   const pending=dirty(),state=pending===null?'unknown':pending?'dirty':'saved';if(save.dataset.state!==state)save.dataset.state=state;
   put(save.lastElementChild,pending===null?ui('保存状态待确认','Save status unavailable'):pending?ui('有未保存的修改','Unsaved changes'):savedAt?ui('已保存','Saved')+' · '+savedAt.toLocaleTimeString([], {hour:'2-digit',minute:'2-digit'}):ui('已保存','Saved'));
  const running=window.corporiumLongTaskActive?.(),active=String(Boolean(running));if(task.dataset.active!==active)task.dataset.active=active;put(task,running?ui('后台任务进行中','Background task running'):ui('无后台任务','No background task'));
 }
 let statusFrame=0;const queueStatus=event=>{
  if(event&&['input','keyup'].includes(event.type)&&save.dataset.state==='dirty'){
   const card=event.target.closest?.('.editable-example'),draft=card&&inlineDrafts.get(card.dataset.exampleKey);
   // An ordinary keystroke cannot clear an inline draft's dirty flag. Its
   // first edit, saving/cancel clicks and the regular task/revision poll still
   // take the full path; do not reschedule an identical caption on every key.
   if(draft?.dirty&&!draft.saving)return;
  }
  if(!statusFrame)statusFrame=requestAnimationFrame(()=>{statusFrame=0;syncStatus();});
 };
 for(const type of ['input','change','click','keyup'])document.addEventListener(type,queueStatus,true);
 setInterval(syncStatus,1500);syncStatus();
 const mirror=()=>{const text=$('notice').textContent.trim();put(message,text);message.title=text;};
 new MutationObserver(mirror).observe($('notice'),{childList:true,characterData:true,subtree:true});mirror();
 const syncPlayer=()=>{const playing=[...document.querySelectorAll('audio,video')].some(m=>!m.paused&&!m.ended);player.hidden=!playing;put(player,playing?ui('正在播放','Playing'):'');};
 for(const type of ['play','pause','ended','emptied'])document.addEventListener(type,syncPlayer,true);
 // Command search: modules, visible commands and a search in the current module, from one field.
 const palette=document.createElement('div');palette.id='app-command-palette';palette.setAttribute('role','dialog');palette.setAttribute('aria-label',ui('搜索与命令','Search and commands'));palette.hidden=true;
 palette.innerHTML='<div class="app-command-field">'+icon(paths.search)+'<input id="app-command-query" type="search" autocomplete="off" spellcheck="false" role="combobox" aria-expanded="true" aria-controls="app-command-results" aria-autocomplete="list"></div><div id="app-command-results" role="listbox"></div><p class="app-command-hint"></p>';
 document.body.append(palette);
 const query=$('app-command-query'),results=$('app-command-results'),hint=palette.querySelector('.app-command-hint');
 query.placeholder=ui('输入要检索的内容或命令名称','Type a search or a command name');
 hint.textContent=ui('↑↓ 选择 · Enter 执行 · Esc 关闭','↑↓ select · Enter run · Esc close');
 const searchTargets={corpus:{input:'query',run:'search',label:ui('在文本语料中检索','Search the text corpus')},dictionary:{input:'dictionary-query',run:'dictionary-search',open:'dictionary-search-panel',label:ui('在词典中检索','Search the dictionary')}};
 const visible=el=>!el.disabled&&!el.closest('[hidden]:not(.settings-page)')&&!el.matches('.danger');
 const labelOf=el=>(el.getAttribute('aria-label')||el.textContent||el.title||'').replace(/\s+/g,' ').trim();
 function commands(){
  const list=[],seen=new Set();
  const add=(label,group,run)=>{const key=group+'\0'+label;if(!label||seen.has(key))return;seen.add(key);list.push({label,group,run});};
  for(const tab of workspaceTabs.querySelectorAll('button'))if(visible(tab))add(labelOf(tab),ui('转到','Go to'),()=>tab.click());
  const sources=['#workspace-toolbar button','#workspace-toolbar summary + .workbench-menu-items button','#management-entries button','#management-backup button','.sidebar-text-actions button','.brand-language-tools button','#global-settings'];
  for(const button of document.querySelectorAll(sources.join(',')))if(visible(button)&&!/删除|Delete/.test(labelOf(button))&&button!==command)add(labelOf(button),ui('命令','Command'),()=>button.click());
  return list;
 }
 let options=[],active=0,entries=[],entryQuery='',entryTimer=0,entrySequence=0;
 // Entries come from the dictionary's own search, shortly after typing pauses.
 function findEntries(raw){
  clearTimeout(entryTimer);if(!raw){entries=[];entryQuery='';return;}if(raw===entryQuery)return;
  entryTimer=setTimeout(async()=>{const ticket=++entrySequence;try{const result=await api('lexemes?'+new URLSearchParams({q:raw,page:1,page_size:10,summary:'1'}));if(ticket!==entrySequence||query.value.trim()!==raw||palette.hidden)return;entries=result.items||[];entryQuery=raw;render();}catch{}},220);
 }
 function render(){
  const raw=query.value.trim(),q=raw.toLowerCase(),target=searchTargets[workspace];
  options=commands().filter(o=>!q||o.label.toLowerCase().includes(q)||o.group.toLowerCase().includes(q));
  // Texts by title and dictionary entries open their own pages.
  if(q){
   const textMatches=(Array.isArray(texts)?texts:[]).filter(t=>String(t.title||'').toLowerCase().includes(q)).slice(0,6).map(t=>({label:t.title,group:ui('文本','Text'),run:async()=>{await setWorkspace('corpus');await selectText(t.id);}}));
   const entryMatches=(entryQuery===raw?entries:[]).map(x=>({label:lexemePlainLabel(x)+(activeLanguage==='all'&&x.language_name?' · '+x.language_name:''),group:ui('词条','Entry'),run:async()=>{await setWorkspace('dictionary');await showLexeme(x.id);}}));
   options=[...textMatches,...entryMatches,...options];
  }
  findEntries(raw);
  if(q&&target&&$(target.input))options.unshift({label:target.label+'：'+query.value.trim(),group:ui('检索','Search'),run:()=>{const details=target.open&&$(target.open);if(details&&!details.open)details.open=true;const input=$(target.input);input.value=query.value.trim();input.dispatchEvent(new Event('input',{bubbles:true}));$(target.run)?.click();input.focus();}});
  active=Math.min(active,Math.max(0,options.length-1));
  results.innerHTML=options.length?options.map((o,i)=>'<div role="option" id="app-command-'+i+'" aria-selected="'+(i===active)+'" data-index="'+i+'"><span>'+esc(o.label)+'</span><small>'+esc(o.group)+'</small></div>').join(''):'<p class="app-command-empty">'+esc(ui('没有匹配的命令','No matching command'))+'</p>';
  query.setAttribute('aria-activedescendant',options.length?'app-command-'+active:'');
  results.querySelector('[aria-selected="true"]')?.scrollIntoView({block:'nearest'});
 }
 function openPalette(){if(root.dataset.home==='true')return;palette.hidden=false;command.setAttribute('aria-expanded','true');query.value='';active=0;render();query.focus();}
 function closePalette(focus=true){if(palette.hidden)return;palette.hidden=true;command.setAttribute('aria-expanded','false');if(focus)command.focus();}
 function runActive(){const option=options[active];if(!option)return;closePalette(false);void safe(option.run)();}
 command.onclick=()=>palette.hidden?openPalette():closePalette();
 query.addEventListener('input',()=>{active=0;render();});
 query.addEventListener('keydown',e=>{
  if(e.key==='ArrowDown'||e.key==='ArrowUp'){e.preventDefault();if(options.length){active=(active+(e.key==='ArrowDown'?1:-1)+options.length)%options.length;render();}}
  else if(e.key==='Enter'&&!e.isComposing){e.preventDefault();runActive();}
  else if(e.key==='Escape'){e.preventDefault();closePalette();}
 });
 results.addEventListener('pointerdown',e=>e.preventDefault());
 results.addEventListener('click',e=>{const option=e.target.closest('[data-index]');if(!option)return;active=Number(option.dataset.index);runActive();});
 document.addEventListener('pointerdown',e=>{if(!palette.hidden&&!palette.contains(e.target)&&!command.contains(e.target))closePalette(false);});
 document.addEventListener('keydown',e=>{if((e.ctrlKey||e.metaKey)&&!e.altKey&&!e.shiftKey&&e.key.toLowerCase()==='k'&&!document.querySelector('dialog[open]:modal')){e.preventDefault();palette.hidden?openPalette():closePalette();}});
})();

/* Dictionary entry and morpheme editors: one page per item. Every existing control keeps its element,
   listeners and validation; the page only groups them into cards under a sticky header that stays inside
   the form, with paradigm tables and word-formation analyses opened in place or beside the entry.
   Moved controls remember their original place, so the quick editor can still borrow the plain form. */
(()=>{
 const ui=(zh,en)=>globalThis.CorporiumI18n?.ui(zh,en)??zh;
 const make=(tag,cls,text)=>{const n=document.createElement(tag);if(cls)n.className=cls;if(text!==undefined)n.textContent=text;return n;};
 const put=(node,text)=>{if(node&&node.textContent!==text)node.textContent=text;};
 const button=(cls,text,title)=>{const b=make('button',cls,text);b.type='button';if(title){b.title=title;b.setAttribute('aria-label',title);}return b;};
 const icons={toggle:'<svg viewBox="0 0 24 24" width="15" height="15" fill="none" stroke="currentColor" stroke-width="2.2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><path d="m6 9 6 6 6-6"/></svg>',more:'<svg viewBox="0 0 24 24" width="15" height="15" fill="currentColor" aria-hidden="true"><circle cx="5" cy="12" r="1.8"/><circle cx="12" cy="12" r="1.8"/><circle cx="19" cy="12" r="1.8"/></svg>'};
 const count=(n,zh,en)=>globalThis.CorporiumI18n?.english?n+' '+en+(n===1?'':'s'):n+' '+zh;
 // Shorter captions for fields shown in a header; the full caption stays as the tooltip.
 function caption(label,text){const node=label&&[...label.childNodes].find(n=>n.nodeType===3&&n.textContent.trim());if(!node||node.textContent===text)return;if(!label.title)label.title=node.textContent.trim();node.textContent=text;}
 function card(map,key,title){const c=make('section','lx-card');c.dataset.lx=key;const head=make('header','lx-card-head');head.append(make('h3','',title));c.append(head);map[key]=c;return c;}
 function field(container,label){const row=make('div','lx-field'),value=make('div','lx-field-value');row.append(make('span','lx-field-label',label),value);container.append(row);return value;}
 // One layout per editor: containers are built once. Each placement step remembers where its control
 // first came from; a control that another module rebuilds in place keeps that original position.
 function layout(form){
  const steps=[],swept=new Map();
  const mark=(holder,node)=>{if(!holder.home&&node.isConnected){holder.home=document.createComment('editor-home');node.before(holder.home);}};
  const current=step=>{if(step.own)return step.get();const node=step.get();if(node)step.node=node;return step.node?.isConnected?step.node:null;};
  return {
   // Controls are given as functions that find them; nodes created by the layout itself are given directly.
   at:(target,...nodes)=>{for(const node of nodes)steps.push(typeof node==='function'?{get:node,target}:{get:()=>node,target,own:true});},
   // Nodes already in their target and order are left alone, so repeated passes cause no mutations.
   apply(rest,keep){
    const groups=new Map();
    for(const step of steps){const node=current(step);if(!node||node===step.target)continue;if(!step.own)mark(step,node);if(!groups.has(step.target))groups.set(step.target,[]);if(!groups.get(step.target).includes(node))groups.get(step.target).push(node);}
    for(const [target,nodes] of groups){const ordered=nodes.every((n,i)=>n.parentElement===target&&(i===0||nodes[i-1].compareDocumentPosition(n)&Node.DOCUMENT_POSITION_FOLLOWING));if(!ordered)target.append(...nodes);}
    for(const node of [...form.children])if(!keep.includes(node)){if(!swept.has(node))swept.set(node,{});mark(swept.get(node),node);rest.append(node);}
   },
   // Every control returns to its original position; one whose original parent is gone stays in the form.
   restore(){
    const back=(holder,node)=>{if(!node?.isConnected)return;if(holder.home?.isConnected)holder.home.after(node);else form.append(node);};
    for(const step of steps)if(!step.own)back(step,current(step));
    for(const [node,holder] of swept){if(node.isConnected)back(holder,node);else{holder.home?.remove();swept.delete(node);}}
   }
  };
 }
 function header(editor,form){
  const head=make('div','lx-formhead'),row=make('div','lx-head'),info=make('div','lx-meta'),title=make('div','lx-title'),commands=make('div','lx-commands');
  const state=make('span','lx-state');state.setAttribute('role','status');state.setAttribute('aria-live','polite');
  const cancel=button('lx-cancel',ui('取消编辑','Cancel'));cancel.onclick=()=>editor.querySelector('.dialog-top .close')?.click();
  const index=make('nav','lx-index');index.setAttribute('aria-label',ui('分区','Sections'));
  commands.append(cancel);row.append(title,state,make('span','lx-spacer'),commands);info.append(index);head.append(row,info);
  new ResizeObserver(()=>editor.style.setProperty('--lx-head-height',head.offsetHeight+'px')).observe(head);
  return {head,title,info,commands,cancel,state,index};
 }
 function renderIndex(index,sections){const key=sections.map(s=>s.join(':')).join('|');if(index.dataset.key===key)return;index.dataset.key=key;index.setAttribute('role','tablist');index.replaceChildren(...sections.map(([id,label])=>{const b=button('lx-index-item',label);b.dataset.lxIndex=id;b.setAttribute('role','tab');return b;}));}
 // Task navigation changes visibility only. Original fields stay enabled and
 // remain in the same form, including all drafts in the inactive sections.
 function taskSection(form,index,cards,groups,fallback){
  const current=Object.hasOwn(groups,form.dataset.lxSection)?form.dataset.lxSection:fallback;
  form.dataset.lxSection=current;
  for(const [key,node] of Object.entries(cards)){
   const visible=groups[current].includes(key);node.classList.toggle('lx-task-hidden',!visible);
   node.id||=form.id+'-section-'+key;node.setAttribute('role','tabpanel');
  }
  for(const grid of form.querySelectorAll(':scope>.lx-main>.lx-grid'))grid.classList.toggle('lx-task-grid-empty',[...grid.children].every(node=>node.classList.contains('lx-task-hidden')||node.hidden));
  for(const tab of index.querySelectorAll('[data-lx-index]')){
   const selected=tab.dataset.lxIndex===current;tab.setAttribute('aria-selected',String(selected));tab.tabIndex=selected?0:-1;
   tab.id||=form.id+'-tab-'+tab.dataset.lxIndex;
   const targets=(groups[tab.dataset.lxIndex]||[]).map(key=>cards[key]).filter(Boolean);if(targets.length)tab.setAttribute('aria-controls',targets.map(node=>node.id).join(' '));
   for(const node of targets)node.setAttribute('aria-labelledby',tab.id);
  }
  return current;
 }
 document.addEventListener('keydown',event=>{
  const tab=event.target.closest?.('.lx-index [role=tab]');if(!tab||event.isComposing||event.altKey||event.ctrlKey||event.metaKey||!['ArrowLeft','ArrowRight','Home','End'].includes(event.key))return;
  const tabs=[...tab.parentElement.querySelectorAll('[role=tab]')],at=tabs.indexOf(tab),next=event.key==='Home'?0:event.key==='End'?tabs.length-1:(at+(event.key==='ArrowRight'?1:-1)+tabs.length)%tabs.length;
  event.preventDefault();tabs[next].click();tabs[next].focus({preventScroll:true});
 });
 function setCollapsed(row,collapsed){row.classList.toggle('lx-collapsed',collapsed);const toggle=row.querySelector(':scope>.lx-toggle,:scope>.lex-row-heading>.lx-toggle');if(toggle){toggle.setAttribute('aria-expanded',String(!collapsed));const label=collapsed?ui('展开详情','Show details'):ui('收起详情','Hide details');toggle.title=label;toggle.setAttribute('aria-label',label);}}
 // Rows only receive a summary and a toggle; their own controls are arranged by the stylesheet.
 function decorateRow(row,host,expand){if(row.dataset.lxRow)return;row.dataset.lxRow='true';const toggle=button('lx-toggle','');toggle.innerHTML=icons.toggle;const remove=host.querySelector(':scope>:is(.remove-sense,.remove-variant)');const peek=make('span','lx-row-text');host===row?row.prepend(peek,toggle):remove?host.insertBefore(toggle,remove):host.append(toggle);if(host!==row)host.insertBefore(peek,toggle);setCollapsed(row,!expand);}
 // Reorder the original draft rows. A sense can only move inside its own usage.
 let editorSort=null;
 function moveEditorRow(row,target,where){
  if(!row?.isConnected||!target?.isConnected||row===target||row.parentElement!==target.parentElement)return false;
  if(where!=='before'&&where!=='after')return false;
  if(where==='before'&&row.nextElementSibling===target||where==='after'&&row.previousElementSibling===target)return false;
  target[where](row);row.dispatchEvent(new Event('input',{bubbles:true}));return true;
 }
 function clearEditorSort(){
  const drag=editorSort;editorSort=null;if(!drag)return;
  cancelAnimationFrame(drag.frame);drag.target?.removeAttribute('data-lx-drop');drag.row.classList.remove('lx-row-dragging');document.body.classList.remove('lx-editor-sorting');
  if(drag.handle.hasPointerCapture(drag.pointer))drag.handle.releasePointerCapture(drag.pointer);
 }
 function editorSortTarget(drag){
  const target=document.elementFromPoint(drag.x,drag.y)?.closest(drag.row.matches('.usage-editor')?'.usage-editor':'.sense-editor');
  const valid=target&&target!==drag.row&&target.parentElement===drag.parent&&drag.row.parentElement===drag.parent;
  const where=valid?(drag.y<target.getBoundingClientRect().top+target.getBoundingClientRect().height/2?'before':'after'):null;
  if(drag.target!==target||drag.where!==where){drag.target?.removeAttribute('data-lx-drop');drag.target=valid?target:null;drag.where=where;if(drag.target)drag.target.dataset.lxDrop=where;}
 }
 function editorSortScroll(){
  const drag=editorSort;if(!drag?.moved)return;
  if(!drag.row.isConnected||!drag.handle.closest('.lx-arranged')){clearEditorSort();return;}
  const area=drag.scroll,root=area===document.scrollingElement,rect=root?{top:0,bottom:window.innerHeight}:area.getBoundingClientRect();
  const head=drag.row.closest('form').querySelector('.lx-formhead'),top=Math.max(rect.top,head?.getBoundingClientRect().bottom||0),bottom=Math.min(rect.bottom,window.innerHeight-($('app-status')?.offsetHeight||0));
  const step=drag.y<top+36?-14:drag.y>bottom-36?14:0;
  if(step)area.scrollTop+=step;editorSortTarget(drag);drag.frame=requestAnimationFrame(editorSortScroll);
 }
 function editorSortDown(event,row,handle){
  if(event.button!==0||!row.closest('.lx-arranged'))return;
  event.preventDefault();clearEditorSort();
  let scroll=row.parentElement;
  while(scroll&&(!/(auto|scroll)/.test(getComputedStyle(scroll).overflowY)||scroll.scrollHeight<=scroll.clientHeight))scroll=scroll.parentElement;
  editorSort={row,handle,parent:row.parentElement,pointer:event.pointerId,startX:event.clientX,startY:event.clientY,x:event.clientX,y:event.clientY,scroll:scroll||document.scrollingElement};
  handle.setPointerCapture(event.pointerId);handle.focus({preventScroll:true});
 }
 function editorSortMove(event){
  const drag=editorSort;if(!drag||event.pointerId!==drag.pointer)return;
  drag.x=event.clientX;drag.y=event.clientY;
  if(!drag.moved&&Math.hypot(drag.x-drag.startX,drag.y-drag.startY)<5)return;
  if(!drag.moved){drag.moved=true;drag.row.classList.add('lx-row-dragging');document.body.classList.add('lx-editor-sorting');drag.frame=requestAnimationFrame(editorSortScroll);}
  event.preventDefault();editorSortTarget(drag);
 }
 function editorSortUp(event){
  const drag=editorSort;if(!drag||event.pointerId!==drag.pointer)return;
  const target=drag.target,where=drag.where;clearEditorSort();
  if(drag.moved&&drag.row.parentElement===drag.parent&&target?.parentElement===drag.parent&&moveEditorRow(drag.row,target,where))drag.handle.focus({preventScroll:true});
 }
 function decorateEditorSort(row,label){
  const head=row.querySelector(':scope>.lex-row-heading');if(!head)return;
  let actions=head.querySelector(':scope>.lx-row-actions'),identity=head.querySelector(':scope>.lx-row-identity'),handle=identity?.querySelector('.lx-sort-handle');
  if(!actions){
   const remove=head.querySelector(':scope>.remove-usage,:scope>.remove-sense');if(!remove)return;
   actions=make('div','lx-row-actions');remove.before(actions);actions.append(remove);
  }
  if(!identity){
   identity=make('div','lx-row-identity');handle=button('lx-sort-handle','⠿');const number=make('span','lx-row-number');number.setAttribute('aria-hidden','true');identity.append(number,handle);head.prepend(identity);
   handle.onpointerdown=event=>editorSortDown(event,row,handle);handle.onlostpointercapture=()=>{if(editorSort?.handle===handle)clearEditorSort();};
   handle.onkeydown=event=>{if(!['ArrowUp','ArrowDown'].includes(event.key)||event.altKey||event.ctrlKey||event.metaKey||event.shiftKey)return;event.preventDefault();clearEditorSort();const target=event.key==='ArrowUp'?row.previousElementSibling:row.nextElementSibling;if(target&&moveEditorRow(row,target,event.key==='ArrowUp'?'before':'after'))handle.focus({preventScroll:true});};
  }
  put(identity.querySelector('.lx-row-number'),head.dataset.lxNumber);
  if(row.matches('.usage-editor')){const tray=head.querySelector(':scope>.lx-tray');if(tray)actions.prepend(tray);}
  const title=label+' · '+ui('拖动排序，↑↓ 调整位置','Drag to reorder; use ↑↓ to move');handle.title=title;handle.setAttribute('aria-label',title);
 }
 function restoreEditorSort(form){
  clearEditorSort();for(const actions of form.querySelectorAll('.lx-row-actions')){const tray=actions.querySelector('.lx-tray'),remove=actions.querySelector('.remove-usage,.remove-sense');if(tray)actions.before(tray);if(remove)actions.before(remove);actions.remove();}for(const identity of form.querySelectorAll('.lx-row-identity'))identity.remove();
 }
 document.addEventListener('pointermove',editorSortMove,{passive:false});document.addEventListener('pointerup',editorSortUp);document.addEventListener('pointercancel',clearEditorSort);
 document.addEventListener('keydown',event=>{if(event.key==='Escape'&&editorSort){event.preventDefault();event.stopImmediatePropagation();clearEditorSort();}},true);
 window.addEventListener('blur',clearEditorSort);
 function variantSummary(row){
  const kind=row.querySelector('.morph-kind'),features=row.querySelectorAll('.morph-features input:checked').length,conditions=row.querySelector('.morph-conditions')?.value.trim()||row.querySelectorAll('.morph-condition-types input:checked').length;
  put(row.querySelector('.lx-row-text'),[kind?.selectedOptions[0]?.textContent.trim(),features?count(features,'项特征','feature'):'',conditions?ui('有分布条件','Conditioned'):''].filter(Boolean).join(' · '));
 }
 function decorateOrthography(row){if(row.querySelector(':scope>.lx-more'))return;const more=button('lx-more','',ui('名称、字体与移除','Name, font and removal'));more.innerHTML=icons.more;more.setAttribute('aria-expanded','false');row.append(more);}
 // Grammatical features: chosen tags stay visible as chips; others are found by searching.
 let featureSequence=0;
 function decorateFeatures(picker){
  picker.classList.add('lx-feature-picker');
  if(picker.previousElementSibling?.matches('.lx-feature-field'))return;
  const box=make('div','lx-feature-field'),query=make('input','lx-feature-query'),options=make('div','lx-feature-options');
  query.type='search';query.autocomplete='off';query.spellcheck=false;query.dataset.lexemeChoiceQuery='';query.placeholder=ui('搜索已登记的语法标签','Search registered grammatical labels');query.setAttribute('aria-label',query.placeholder);
  options.id='lx-feature-options-'+(++featureSequence);options.setAttribute('aria-label',query.placeholder);
  query.setAttribute('role','combobox');query.setAttribute('aria-expanded','false');query.setAttribute('aria-controls',options.id);query.setAttribute('aria-autocomplete','list');options.setAttribute('role','listbox');options.hidden=true;
  box.append(query,options);picker.before(box);
 }
 function decorateCompact(form){
  for(const picker of form.querySelectorAll(':has(>.morph-features)'))decorateFeatures(picker);
  // Compact tag and feature editors stay open; long notes keep their disclosure.
  for(const details of form.querySelectorAll('details:has(>.lx-feature-picker,>.usage-tags,>.sense-tags,>.variant-tags,>.lx-feature-field,>#lexeme-tags,>#morpheme-tags)'))if(!details.classList.contains('lx-inline-details')){details.classList.add('lx-inline-details');details.open=true;}
 }
 function featureLabels(query){const picker=query.closest('.lx-feature-field')?.nextElementSibling;return picker?[...picker.querySelectorAll('.morph-features>label')].filter(l=>l.querySelector('input[type=checkbox]')):[];}
 function renderOptions(query,active=0){
  const box=query.parentElement.querySelector('.lx-feature-options'),q=query.value.trim().toLowerCase();
  const matches=featureLabels(query).filter(l=>!l.querySelector('input').checked&&(!q||l.textContent.toLowerCase().includes(q))).slice(0,40);
  active=Math.min(Math.max(0,active),Math.max(0,matches.length-1));
  box.replaceChildren(...matches.map((label,i)=>{const option=button('lx-feature-option','');option.id=box.id+'-option-'+i;option.tabIndex=-1;option.setAttribute('role','option');option.setAttribute('aria-selected',String(i===active));option.dataset.value=label.querySelector('input').value;
   option.append(make('span','lx-feature-tag',label.querySelector('.grammar-label')?.textContent||label.textContent.trim()),make('span','lx-feature-desc',label.querySelector('small')?.textContent||''));return option;}));
  if(!matches.length)box.append(make('p','lx-feature-empty',q?ui('没有匹配的已登记标签','No matching registered label'):ui('所有标签都已选择','Every label is selected')));
  box.hidden=false;query.setAttribute('aria-expanded','true');
  const selected=box.querySelector('[aria-selected="true"]');if(selected)query.setAttribute('aria-activedescendant',selected.id);else query.removeAttribute('aria-activedescendant');
 }
 function closeFeatures(query){const box=query.parentElement?.querySelector('.lx-feature-options');if(box)box.hidden=true;query.setAttribute('aria-expanded','false');query.removeAttribute('aria-activedescendant');}
 function choose(option){
  const box=option.closest('.lx-feature-options'),query=box.parentElement.querySelector('.lx-feature-query');
  const label=featureLabels(query).find(l=>l.querySelector('input').value===option.dataset.value),input=label?.querySelector('input');
  if(input&&!input.checked){input.checked=true;input.dispatchEvent(new Event('input',{bubbles:true}));input.dispatchEvent(new Event('change',{bubbles:true}));}
  query.value='';renderOptions(query);query.focus();
 }
 // Empty labels, features and notes of a part of speech or sense take no rows: they wait as “＋” chips.
 const optionalKinds=[['tags',':is(.usage-tags,.sense-tags)',ui('使用标签','Usage tag'),b=>![...b.querySelectorAll('.tag-row input')].some(input=>input.value.trim())],['features','.lx-feature-picker',ui('语法特征','Features'),b=>!b.querySelector('.morph-features input:checked')],['notes',':is(.usage-notes,.sense-notes)',ui('备注','Note'),b=>!b.querySelector('textarea')?.value.trim()]];
 let optionalSequence=0;
 function optionalBlock(row,selector){return [...row.children].find(c=>c.tagName==='DETAILS'&&c.querySelector(selector));}
 function optionalState(block,chip,label,open){
  block.hidden=!open;block.open=open;chip.hidden=false;
  if(chip.getAttribute('aria-expanded')!==String(open))chip.setAttribute('aria-expanded',String(open));
  put(chip,(open?'− ':'＋ ')+label);chip.title=(open?ui('收起','Hide'):ui('展开','Show'))+' '+label;
 }
 function trays(row,host){
  let tray=row.querySelector('.lx-tray');
  if(!tray){tray=make('div','lx-tray');for(const [kind,,label] of optionalKinds){const b=button('lx-tray-add','＋ '+label);b.dataset.lxReveal=kind;b.hidden=true;tray.append(b);}const remove=host.querySelector(':scope>:is(.remove-usage,.remove-sense)');if(host===row)row.append(tray);else remove?host.insertBefore(tray,remove):host.append(tray);}
  for(const [kind,selector,label,empty] of optionalKinds){
   const block=optionalBlock(row,selector),chip=tray.querySelector('[data-lx-reveal="'+kind+'"]');if(!block){chip.hidden=true;continue;}
   block.dataset.lxOptional=kind;block.id||='lx-optional-'+(++optionalSequence);chip.setAttribute('aria-controls',block.id);block.setAttribute('aria-label',label);
   optionalState(block,chip,label,block.dataset.lxRevealed?block.dataset.lxRevealed==='true':!empty(block));
  }
 }
 function reveal(chip){
  const row=chip.closest('.usage-editor,.sense-editor'),[,selector,label]=optionalKinds.find(k=>k[0]===chip.dataset.lxReveal);
  const block=optionalBlock(row,selector);if(!block)return;
  const open=block.hidden||!block.open;block.dataset.lxRevealed=String(open);optionalState(block,chip,label,open);
  if(open){
   if(chip.dataset.lxReveal==='tags'&&!block.querySelector('.tag-row'))block.querySelector('.usage-tags,.sense-tags')?.addEmptyTag?.();
   (block.querySelector('.lx-feature-query,textarea,.tag-row input')||block).focus?.();
  }
  row.closest('dialog')?.dispatchEvent(new Event('lx-layout'));
 }
 function collapseEmptyOptional(block){
  const row=block?.parentElement,kind=optionalKinds.find(k=>k[0]===block?.dataset.lxOptional);if(!row||!kind||block.contains(document.activeElement)||!kind[3](block))return;
  const chip=row.querySelector('[data-lx-reveal="'+kind[0]+'"]');if(!chip)return;
  block.dataset.lxRevealed='false';optionalState(block,chip,kind[2],false);
 }
 document.addEventListener('focusout',event=>{const block=event.target.closest?.('.lx-arranged details[data-lx-optional]');if(block)setTimeout(()=>{if(block.isConnected)collapseEmptyOptional(block);},0);});
 // Paradigm tables: a grid of the table's cells chooses the row whose fields open beside it; each cell
 // shows its forms or its state. Rows stay in place, so reading and saving the table are unchanged.
 const paradigmStates=[['filled',ui('已填写','Filled')],['unfilled',ui('未填写','Not filled')],['missing',ui('无此形式','No such form')]];
 function paradigmCell(info){
  const b=button('paradigm-cell','');b.dataset.paradigmRow=info.row.dataset.id;b.dataset.state=info.state;b.setAttribute('aria-pressed',String(info.open));
  const label=info.labels.filter(Boolean).join(' · ')||ui('新行','New row');b.title=label;
  const text=info.state==='missing'?ui('无此形式','No such form'):info.forms.join(' / ')||(info.state==='filled'?ui('待选形式','Form pending'):ui('未填写','Not filled'));
  b.append(make('span','paradigm-cell-form',text));return b;
 }
 function decorateParadigm(table){
  const rows=table.querySelector(':scope>.paradigm-rows');if(!rows)return;
  const hint=ui('在左侧表格中选择一个格，查看并编辑它的形式与意义。','Choose a cell in the table to see and edit its forms and meanings.');if(rows.dataset.empty!==hint)rows.dataset.empty=hint;
  let overview=table.querySelector(':scope>.paradigm-overview');if(!overview){overview=make('div','paradigm-overview');rows.before(overview);}
  const dims=(table.querySelector('[data-p="dimensions"]')?.value||'').split('|').map(s=>s.trim()).filter(Boolean);
  const info=[...rows.querySelectorAll(':scope>.paradigm-row')].map(row=>({row,open:row.open,state:row.querySelector('.paradigm-state')?.value||'unfilled',
   labels:[...row.querySelectorAll('.paradigm-labels input')].map(i=>i.value.trim()),
   forms:[...row.querySelectorAll('.paradigm-realization')].map(r=>{const s=r.querySelector('.paradigm-form');return (s?.value?s.selectedOptions[0]?.textContent.split(' · ')[0].trim():'')||r.querySelector('.paradigm-new-form input')?.value.trim()||'';}).filter(Boolean)}));
  for(const {row,state} of info)decorateParadigmRow(row,state);
  const key=JSON.stringify([dims,info.map(i=>[i.row.dataset.id,i.labels,i.state,i.forms,i.open])]);if(overview.dataset.key===key)return;overview.dataset.key=key;
  if(!info.length){overview.replaceChildren(make('p','paradigm-overview-empty',ui('此表还没有行，可用下方“添加一行”或应用栏目。','This table has no rows yet; add a row below or apply the columns.')));return;}
  if(dims.length===2){
   // Two dimensions read as a matrix: the first gives the rows, the second the columns.
   const unique=values=>[...new Set(values)],rowValues=unique(info.map(i=>i.labels[0]||'')),colValues=unique(info.map(i=>i.labels[1]||''));
   const grid=make('table','paradigm-matrix'),head=grid.createTHead().insertRow(),body=grid.createTBody();
   head.append(make('th','',dims[0]+' \\ '+dims[1]));for(const c of colValues)head.append(make('th','',c||'—'));
   for(const r of rowValues){const tr=body.insertRow();tr.append(make('th','',r||'—'));for(const c of colValues){const td=tr.insertCell();for(const cell of info.filter(i=>(i.labels[0]||'')===r&&(i.labels[1]||'')===c))td.append(paradigmCell(cell));if(!td.children.length)td.append(make('span','paradigm-cell-none','—'));}}
   overview.replaceChildren(grid);
  }else{const list=make('div','paradigm-cell-list');for(const cell of info){const b=paradigmCell(cell);b.prepend(make('strong','',cell.labels.filter(Boolean).join(' · ')||ui('新行','New row')));list.append(b);}overview.replaceChildren(list);}
 }
 function decorateParadigmRow(row,state){
  let choice=row.querySelector(':scope>.paradigm-state-choice');
  if(!choice){choice=make('div','app-segmented paradigm-state-choice');choice.setAttribute('role','group');choice.setAttribute('aria-label',ui('此行状态','State of this row'));
   for(const [value,label] of paradigmStates){const b=button('',label);b.dataset.paradigmState=value;choice.append(b);}
   row.querySelector(':scope>label:has(.paradigm-state)')?.after(choice);}
  for(const b of choice.children){const on=b.dataset.paradigmState===state;if(b.getAttribute('aria-pressed')!==String(on))b.setAttribute('aria-pressed',String(on));}
 }
 function chooseParadigmRow(cell){
  const table=cell.closest('.paradigm-table-editor'),target=[...table.querySelectorAll(':scope>.paradigm-rows>.paradigm-row')].find(r=>r.dataset.id===cell.dataset.paradigmRow);if(!target)return;
  for(const row of table.querySelectorAll(':scope>.paradigm-rows>.paradigm-row'))row.open=row===target;
  table.closest('dialog')?.dispatchEvent(new Event('lx-layout'));target.querySelector('summary')?.focus({preventScroll:true});
 }
 function setParadigmState(button){
  const select=button.closest('.paradigm-row')?.querySelector('.paradigm-state');if(!select||select.value===button.dataset.paradigmState)return;
  // The row's own handler keeps “filled” while it still has forms; the buttons follow its decision.
  select.value=button.dataset.paradigmState;select.dispatchEvent(new Event('change',{bubbles:true}));
  decorateParadigmRow(button.closest('.paradigm-row'),select.value);button.closest('dialog')?.dispatchEvent(new Event('lx-layout'));
 }
 // Behaviour shared by both editors.
 document.addEventListener('click',e=>{
  const t=e.target.closest('.lx-arranged button');if(!t)return;
  if(t.matches('.paradigm-cell')){chooseParadigmRow(t);return;}
  if(t.dataset.paradigmState){setParadigmState(t);return;}
  if(t.matches('.lx-toggle')){const row=t.closest('.sense-editor,.variant-editor');if(row){const opening=row.classList.contains('lx-collapsed');if(opening&&row.matches('.variant-editor'))for(const sibling of row.parentElement.querySelectorAll(':scope>.variant-editor'))if(sibling!==row)setCollapsed(sibling,true);setCollapsed(row,!opening);t.closest('dialog')?.dispatchEvent(new Event('lx-layout'));}}
  else if(t.matches('.lx-more')){const row=t.closest('.orthography-editor');const open=!row.classList.contains('lx-more-open');row.classList.toggle('lx-more-open',open);t.setAttribute('aria-expanded',String(open));}
  else if(t.matches('.lx-feature-option'))choose(t);
  else if(t.dataset.lxReveal)reveal(t);
 });
 document.addEventListener('input',e=>{if(e.target.matches?.('.lx-arranged .lx-feature-query')&&!e.isComposing)renderOptions(e.target);});
 document.addEventListener('compositionend',e=>{if(e.target.matches?.('.lx-arranged .lx-feature-query'))renderOptions(e.target);});
 document.addEventListener('keydown',e=>{
  if(!e.target.matches?.('.lx-arranged .lx-feature-query')||e.isComposing||e.keyCode===229)return;
  const box=e.target.parentElement.querySelector('.lx-feature-options'),options=[...box.querySelectorAll('.lx-feature-option')],current=options.findIndex(o=>o.getAttribute('aria-selected')==='true');
  if(e.key==='ArrowDown'||e.key==='ArrowUp'){e.preventDefault();if(box.hidden){renderOptions(e.target);return;}const next=options.length?(current+(e.key==='ArrowDown'?1:-1)+options.length)%options.length:0;renderOptions(e.target,next);box.querySelector('[aria-selected="true"]')?.scrollIntoView({block:'nearest'});}
  else if(e.key==='Enter'){e.preventDefault();if(options[current])choose(options[current]);}
  else if(e.key==='Escape'&&!box.hidden){e.preventDefault();e.stopPropagation();closeFeatures(e.target);}
 },true);
 document.addEventListener('focusout',e=>{if(e.target.matches?.('.lx-arranged .lx-feature-query'))setTimeout(()=>{const box=e.target.parentElement?.querySelector('.lx-feature-options');if(box&&!box.contains(document.activeElement)&&document.activeElement!==e.target)closeFeatures(e.target);},150);});
 // Native validation keeps its original constraints. Reveal the first invalid field before focusing it,
 // including fields inside collapsed rows, optional blocks and the borrowed quick-edit form.
 function revealInvalidField(target,form){
  for(let node=target.parentElement;node&&node!==form;node=node.parentElement){
   if(node.matches('.sense-editor,.variant-editor'))setCollapsed(node,false);
   if(node.matches('.orthography-editor')){node.classList.add('lx-more-open');node.querySelector(':scope>.lx-more')?.setAttribute('aria-expanded','true');}
   if(node.tagName==='DETAILS'){node.open=true;node.dataset.lxRevealed='true';}
   if(node.hidden)node.hidden=false;
  }
 }
 // Rebuild summaries once per frame after the editor's own renderers change it.
 function watch(editor,form,refresh,opened,revealInvalid){
  let frame=0;const queue=()=>{if(!frame)frame=requestAnimationFrame(()=>{frame=0;refresh();});};
  const error=form.querySelector('[id$="-error"]');if(error)error.dataset.inlineMessage='true';
  let invalidTarget=null;
  form.addEventListener('invalid',event=>{
   event.preventDefault();event.target.setAttribute('aria-invalid','true');if(invalidTarget)return;
   invalidTarget=event.target;
   // A quick editor may hide fields intentionally; return its one form before revealing the field.
   if(form.closest('#lexeme-quick-editor'))form.dispatchEvent(new Event('corporium-quick-edit-return'));
   revealInvalid?.(invalidTarget);revealInvalidField(invalidTarget,form);
   if(error){error.dataset.lxValidation='true';error.textContent=ui('请补全或修正已定位的字段后保存。','Complete or correct the focused field before saving.');const described=(invalidTarget.getAttribute('aria-describedby')||'').split(/\s+/).filter(Boolean);if(!described.includes(error.id))described.push(error.id);invalidTarget.setAttribute('aria-describedby',described.join(' '));}
   requestAnimationFrame(()=>{const target=invalidTarget;invalidTarget=null;if(!target?.isConnected)return;revealInvalid?.(target);revealInvalidField(target,form);target.scrollIntoView({block:'center'});target.focus({preventScroll:true});});
  },true);
  form.addEventListener('input',event=>{
   if(event.target.validity?.valid)event.target.removeAttribute('aria-invalid');
   if(error?.dataset.lxValidation&&![...form.elements].some(field=>field.willValidate&&!field.validity.valid)){error.textContent='';delete error.dataset.lxValidation;}
  });
  for(const type of ['input','change','lx-layout'])editor.addEventListener(type,queue);
  new MutationObserver(queue).observe(editor,{childList:true,subtree:true});
  new MutationObserver(()=>{if(editor.open&&editor.querySelector('.dialog-top')){if(!editor.dataset.lxOpened){editor.dataset.lxOpened='true';opened();refresh();}}else delete editor.dataset.lxOpened;}).observe(editor,{attributes:true,attributeFilter:['open','class']});
  document.addEventListener('corporium-sidebar-layout',queue);
  return queue;
 }

 // ----- Entry editor -----
 (()=>{
  const editor=$('lexeme-editor'),form=$('lexeme-form'),placeKey='corporium-entry-panel-place';
  let built=false,arranged=false,borrowed=false,fresh=false,main,aside,rest,frame,addbar,plan,relationBody,relationSummary,relationEdit,relationClear,relationEditing=false,queue=()=>{};const cards={},summaries={},panels={},revealed=new Set();
  const taskGroups={usages:['usages'],writing:['writing'],morphology:['morphology'],identity:['relations','identity','notes']};
  function build(){
   if(built)return;built=true;plan=layout(form);const at=plan.at;
   frame=header(editor,form);
   const headword=()=>$('lexeme-headword').closest('.multipart-form-editor')||$('lexeme-headword').closest('label');
   at(frame.title,headword);at(frame.commands,()=>$('lexeme-quick-open'),()=>$('save-lexeme'),frame.cancel);
   const meta=['lexeme-number','morph-entry-type','lexeme-language'].map(id=>()=>$(id)?.closest('label'));
   const metadata=make('details','lx-entry-metadata');metadata.append(make('summary','',ui('条目信息','Entry information')));at(metadata,...meta);at(frame.info,metadata,frame.index);
   // Written forms and variants | morphological identity.
   const writing=card(cards,'writing',ui('书写形式','Written forms')),variantHead=make('header','lx-card-head lx-subhead');variantHead.append(make('h3','',ui('变体','Variants')));
   at(writing.querySelector('.lx-card-head'),()=>$('add-orthography'));at(writing,()=>$('lexeme-orthographies'),variantHead,()=>$('lexeme-variants'));
   at(variantHead,()=>$('add-variant'),()=>$('lexeme-variants').closest('details')?.querySelector(':scope>button:not(#add-variant)'));
   const relations=card(cards,'relations',ui('条目间关系','Relations between entries'));
   const relationLine=make('div','lx-relation-line');relationSummary=make('p','lx-relation-summary');relationEdit=button('lx-relation-edit','');relationClear=button('lx-relation-clear',ui('解除关联','Remove link'));
   relationLine.append(relationSummary,relationEdit,relationClear);relationBody=make('div','lx-relation-fields');relations.append(relationLine,relationBody);
   at(relationBody,()=>$('morph-base-query'),()=>$('morph-base')?.closest('.morph-base-relation-fields'),()=>$('morph-base-count'));
   relationEdit.onclick=()=>{relationEditing=!relationEditing;refreshRelation();if(relationEditing)(!$('morph-base-query').hidden?$('morph-base-query'):$('morph-base')).focus();};
   relationClear.onclick=()=>{const target=$('morph-base');target.value='';target.dispatchEvent(new Event('change',{bubbles:true}));target.dispatchEvent(new Event('input',{bubbles:true}));relationEditing=false;refreshRelation();};
   const identity=card(cards,'identity',ui('分类与标签','Classification and usage tags')),fields=make('div','lx-fields lx-classification-fields');identity.append(fields);
   const semantic=field(fields,ui('语义分类','Semantic class')),semanticTools=make('div','lx-field-tools ui-controls ui-controls--compact'),semanticManage=button('lx-manage-semantic',ui('管理语义类','Manage semantic classes'));
   semanticManage.onclick=safe(()=>openClasses($('lexeme-language').value,'semantic'));semanticTools.append(semanticManage);semantic.parentElement.append(semanticTools);
   at(semantic,()=>$('lexeme-semantic-field'));
   const tags=field(fields,ui('使用标签','Usage tags')),tagTools=make('div','lx-field-tools ui-controls ui-controls--compact');tags.parentElement.append(tagTools);
   at(tags,()=>$('lexeme-tags').closest('details'));at(tagTools,()=>manageTagTypes);
   at(field(fields,ui('固有语法特征','Inherent features')),()=>$('morph-entry-features')?.closest('details'));
   at(relations,()=>$('morph-entry-editor'));
   const grid=make('div','lx-grid');grid.append(writing,relations,identity);
   // Parts of speech and senses.
   const usages=card(cards,'usages',ui('词类用法与义项','Parts of speech and senses'));
   const expandAll=button('lx-expand-all','');expandAll.onclick=()=>{const senses=[...form.querySelectorAll('.sense-editor')],open=senses.some(s=>s.classList.contains('lx-collapsed'));for(const s of senses)setCollapsed(s,!open);refresh();};
   const usageHead=usages.querySelector('.lx-card-head');usageHead.append(expandAll);
   at(usageHead,()=>$('add-usage'),...[...form.querySelectorAll(':scope>button:not([id])')].map(b=>()=>b));at(usages,()=>$('lexeme-usages'));
   // Morphology: one summary row per table kind; the editors open in place or at the right.
   const morphology=card(cards,'morphology',ui('形态与变化','Morphology and inflection'));
   const membership=make('section','lx-membership-section'),membershipHead=make('header','lx-card-head');membershipHead.append(make('h3','',ui('形态类与主要部分','Morphological classes & principal parts')));membership.append(membershipHead);morphology.append(membership);
   at(membershipHead,()=>$('ws-add-membership'),()=>$('ws-manage-classes'));at(membership,()=>$('ws-memberships'));
   for(const [key,label] of [['paradigm',ui('变形表','Paradigm tables')],['analysis',ui('构词分析','Word formation')]]){
    const row=make('div','lx-summary');row.dataset.panel=key;
    const open=button('lx-open',ui('编辑','Edit'));open.dataset.lxOpen=key;
    row.append(make('strong','',label),make('span','lx-summary-text'),make('span','lx-spacer'),open);morphology.append(row);summaries[key]=row;
   }
   morphology.append(make('p','lx-empty-help',ui('为当前条目添加变形表或构词分析。','Add a paradigm table or word-formation analysis for this entry.')));
   // Notes appear when used; otherwise they are offered in the add bar.
   const notes=card(cards,'notes',ui('备注与说明','Notes'));
   at(notes,()=>$('lexeme-notes').closest('details'),()=>$('lexeme-homonym').closest('label'));
   addbar=make('div','lx-addbar');addbar.append(make('span','lx-addbar-label',ui('添加','Add')));
   for(const [key,label] of [['paradigm',ui('变形表','Paradigm table')],['analysis',ui('构词分析','Word formation')],['notes',ui('词条备注','Entry note')],['homonym',ui('同形区分说明','Homograph note')]]){const b=button('lx-add','＋ '+label);b.dataset.lxAdd=key;addbar.append(b);}
   // Paradigm and analysis editors share one panel frame with a way back to the entry.
   aside=make('div','lx-aside');
   for(const [key,label,node] of [['paradigm',ui('变形表','Paradigm tables'),()=>$('paradigm-editor')],['analysis',ui('构词分析','Word formation'),()=>$('word-structure-editor')]]){
    const panel=make('section','lx-panel');panel.dataset.panel=key;
    const bar=make('div','lx-panel-bar'),back=button('lx-back','← '+ui('返回词条','Back to entry'));back.dataset.lxClose='';
    const crumb=make('span','lx-crumb');crumb.append(make('span','lx-crumb-entry'),' › ',make('strong','',label));
    const place=button('lx-place','');place.dataset.lxSwitch=key;
    bar.append(back,crumb,make('span','lx-spacer'),place);panel.append(bar);at(panel,node);aside.append(panel);panels[key]=panel;
   }
   main=make('div','lx-main');rest=make('div','lx-rest');main.append(grid,usages,morphology,notes,addbar,rest);
   editor.addEventListener('click',click);
   // Borrow only after the settings request succeeds, and restore on its actual close/failure.
   editor.addEventListener('corporium-quick-edit',event=>{
    const phase=event.detail.phase;
    if(phase==='prepare'){borrowed=true;unarrange();}
    else if(phase==='opened')borrowed=false;
    else if(phase==='restored'||phase==='settled'&&!$('lexeme-quick-editor')?.open){borrowed=false;if(editor.open&&!arranged)arrange();}
   });
  }
  function arrange(){
   if(arranged)return;arranged=true;
   form.prepend(frame.head);form.append(main,aside);
   plan.apply(rest,[frame.head,main,aside,$('lexeme-error')]);
   caption($('lexeme-number').closest('label'),ui('同形号','Homograph'));caption($('morph-entry-type')?.closest('label'),ui('条目类型','Entry type'));caption($('lexeme-language').closest('label'),ui('语言','Language'));
   form.classList.add('lx-arranged');editor.classList.add('lx-editor');queue();
  }
  function unarrange(){
   if(!arranged)return;arranged=false;
   restoreEditorSort(form);
   setPanel('');plan.restore();frame.head.remove();main.remove();aside.remove();
   form.classList.remove('lx-arranged');editor.classList.remove('lx-editor');
  }
  // Open the current task at full width. A side-by-side placement remains an
  // explicit option inside the panel rather than a persistent default.
  const preferredPlace=()=>'focus';
  function setPanel(key,place,resetPresentation=true){
   if(key){form.dataset.lxSection='morphology';if(key==='paradigm'&&resetPresentation)window.CorporiumParadigms?.setCompactPresentation?.(true);}
   form.dataset.lxPanel=key||'';form.dataset.lxMode=key?place:'';
   if(key)try{localStorage.setItem(placeKey,place);}catch{}
   for(const panel of Object.values(panels))put(panel.querySelector('.lx-place'),place==='side'?ui('在编辑区显示','Show in the editor'):ui('在右栏显示','Show at right'));
   if(key&&place==='focus')editor.scrollIntoView({block:'start'});
   queue();
  }
  function click(e){
   const t=e.target.closest('button');if(!t||!arranged||!editor.contains(t))return;
   if(t.dataset.lxOpen)setPanel(t.dataset.lxOpen,t.dataset.lxPlace||preferredPlace());
   else if(t.matches('[data-lx-close]'))setPanel('');
   else if(t.dataset.lxSwitch)setPanel(t.dataset.lxSwitch,form.dataset.lxMode==='side'?'focus':'side');
   else if(t.dataset.lxAdd){const key=t.dataset.lxAdd;if(key==='paradigm'||key==='analysis'){setPanel(key,preferredPlace());return;}revealed.add(key);refresh();const target=key==='notes'?$('lexeme-notes'):$('lexeme-homonym');const details=target.closest('details');if(details)details.open=true;target.focus();}
   else if(t.dataset.lxIndex){setPanel('');form.dataset.lxSection=t.dataset.lxIndex;refresh();}
  }
  function refreshRelation(){
   if(!relationBody)return;
   const base=$('morph-base'),relation=$('morph-relation');if(!base||!relation)return;
   caption(base.closest('label'),ui('关联条目','Linked entry'));caption(relation.closest('label'),ui('关系类型','Relation type'));
   const query=$('morph-base-query');query.placeholder=ui('输入词形筛选关联条目','Filter linked entries by form');query.setAttribute('aria-label',ui('筛选关联条目','Filter linked entries'));
   base.setAttribute('aria-label',ui('关联条目','Linked entry'));relation.setAttribute('aria-label',ui('当前条目与所选条目的关系','Relation of this entry to the selected entry'));
   const target=base.selectedOptions[0]?.textContent.trim()||'',kind=relation.value;
   const statements={stem:ui('当前条目是 {entry} 的词干形式。','This entry is a stem form of {entry}.'),inflection:ui('当前条目是 {entry} 的屈折形式。','This entry is an inflected form of {entry}.'),derivation:ui('当前条目由 {entry} 派生。','This entry is derived from {entry}.'),allomorph:ui('当前条目是 {entry} 的语素变体。','This entry is an allomorph of {entry}.')};
   put(relationSummary,base.value?(statements[kind]||ui('当前条目与 {entry} 相关联。','This entry is linked to {entry}.')).replace('{entry}',target):ui('尚未关联其他条目。','No other entry is linked.'));
   put(relationEdit,relationEditing?ui('收起','Done'):base.value?ui('更改','Change'):ui('关联条目','Link an entry'));
   relationBody.classList.toggle('lx-relation-collapsed',!relationEditing);relationEdit.setAttribute('aria-expanded',String(relationEditing));relationBody.id||='lexeme-relation-fields';relationEdit.setAttribute('aria-controls',relationBody.id);relationClear.hidden=!base.value;
  }
  // Summaries, optional sections and the section index follow the current form contents.
  function refresh(){
   if(!built||!arranged)return;const opening=fresh;
   // Controls created or moved by other modules after opening join their place again.
   plan.apply(rest,[frame.head,main,aside,$('lexeme-error')]);
   for(const toggle of form.querySelectorAll('.multipart-toggle'))caption(toggle,ui('多部分','Multipart'));
   const usages=[...form.querySelectorAll('#lexeme-usages>.usage-editor')];let first=true;
   usages.forEach((usage,u)=>{
    usage.querySelector(':scope>.lex-row-heading')?.setAttribute('data-lx-number',String(u+1));
    [...usage.querySelectorAll('.sense-editor')].forEach((sense,s)=>{const head=sense.querySelector(':scope>.lex-row-heading');if(!head)return;head.dataset.lxNumber=(u+1)+'.'+(s+1);
     const input=sense.querySelector(':scope>label>.sense-short');if(input){const label=input.parentElement;if(!input.hasAttribute('aria-label'))input.setAttribute('aria-label',ui('简短标注释义','Short gloss'));if(!label.querySelector('.lx-sense-caption')){for(const node of [...label.childNodes])if(node.nodeType===3)node.remove();label.prepend(make('span','lx-sense-caption',ui('简短标注','Short gloss')));}}
     decorateRow(sense,head,fresh?first:true);first=false;
     const definition=sense.querySelector('.sense-definition')?.value.trim().split('\n')[0]||'';put(sense.querySelector('.lx-row-text'),definition.length>48?definition.slice(0,48)+'…':definition);});
   });
   for(const row of form.querySelectorAll('#lexeme-variants>.variant-editor')){decorateRow(row,row,false);variantSummary(row);}
   for(const row of form.querySelectorAll('#lexeme-orthographies>.orthography-editor'))decorateOrthography(row);
   for(const table of form.querySelectorAll('#paradigm-tables>.paradigm-table-editor'))decorateParadigm(table);
   decorateCompact(form);
   for(const usage of usages){trays(usage,usage.querySelector(':scope>.lex-row-heading'));for(const sense of usage.querySelectorAll('.sense-editor'))trays(sense,sense);}
   usages.forEach((usage,u)=>{decorateEditorSort(usage,ui('词类用法 ','POS group ')+(u+1));[...usage.querySelectorAll('.sense-editor')].forEach((sense,s)=>decorateEditorSort(sense,ui('义项 ','Sense ')+(u+1)+'.'+(s+1)));});
   fresh=false;
   const senses=[...form.querySelectorAll('.sense-editor')],expandAll=cards.usages.querySelector('.lx-expand-all');
   expandAll.hidden=senses.length<2;put(expandAll,senses.some(s=>s.classList.contains('lx-collapsed'))?ui('全部展开','Expand all'):ui('全部收起','Collapse all'));
   const tables=[...($('paradigm-tables')?.querySelectorAll(':scope>.paradigm-table-editor')||[])],analyses=[...($('ws-analyses')?.querySelectorAll(':scope>.ws-analysis')||[])];
   put(summaries.paradigm.querySelector('.lx-summary-text'),tables.map(t=>(t.querySelector('input')?.value.trim()||ui('未命名表格','Untitled table'))+' · '+count(t.querySelectorAll('.paradigm-rows>*').length,'行','row')).join('；'));
   put(summaries.analysis.querySelector('.lx-summary-text'),analyses.map((a,i)=>(a.querySelector('input')?.value.trim()||ui('分析','Analysis')+' '+(i+1))+' · '+count(a.querySelectorAll('.ws-components>*').length,'个组分','component')).join('；'));
   summaries.paradigm.hidden=!tables.length;summaries.analysis.hidden=!analyses.length;cards.morphology.hidden=false;
   cards.morphology.querySelector('.lx-empty-help').hidden=!!(tables.length||analyses.length);
   const notes=$('lexeme-notes').value.trim()||revealed.has('notes'),homonym=$('lexeme-homonym').value.trim()||revealed.has('homonym');
   const noteDetails=$('lexeme-notes').closest('details'),homonymLabel=$('lexeme-homonym').closest('label');
   if(noteDetails)noteDetails.hidden=!notes;if(homonymLabel)homonymLabel.hidden=!homonym;cards.notes.hidden=!notes&&!homonym;
   if(opening&&$('lexeme-notes').value.trim()&&noteDetails)noteDetails.open=true;
   const section=form.dataset.lxSection||'usages',adds={paradigm:section==='morphology'&&!tables.length,analysis:section==='morphology'&&!analyses.length,notes:section==='identity'&&!notes,homonym:section==='identity'&&!homonym};
   for(const b of addbar.querySelectorAll('[data-lx-add]'))b.hidden=!adds[b.dataset.lxAdd];addbar.hidden=!Object.values(adds).some(Boolean);
   const name=$('lexeme-headword').value.trim();for(const node of aside.querySelectorAll('.lx-crumb-entry'))put(node,name||ui('新词条','New entry'));
   refreshRelation();
   renderIndex(frame.index,[['usages',ui('义项','Senses')+(senses.length?' '+senses.length:'')],['writing',ui('形式','Forms')],['morphology',ui('形态与变化','Morphology')],['identity',ui('关系与分类','Relations and classes')]]);
   taskSection(form,frame.index,cards,taskGroups,'usages');
   put(frame.state,lexemeDirty?ui('未保存的修改','Unsaved changes'):'');
  }
  queue=watch(editor,form,refresh,()=>{build();borrowed=false;arrange();fresh=true;revealed.clear();relationEditing=false;form.dataset.lxSection='usages';setPanel('');},target=>{
   if(!arranged)return;
   const panel=target.closest('.lx-panel');setPanel(panel?.dataset.panel||'',panel?'focus':'',false);
   const owner=Object.entries(cards).find(([,node])=>node.contains(target))?.[0];
   if(owner)form.dataset.lxSection=Object.keys(taskGroups).find(key=>taskGroups[key].includes(owner))||'usages';
   if(relationBody?.contains(target)){relationEditing=true;refreshRelation();}
   if(cards.notes.contains(target)){revealed.add(target.id==='lexeme-homonym'?'homonym':'notes');cards.notes.hidden=false;}
   refresh();
  });
  // Leaving the page editor returns every control to its original place.
  editor.addEventListener('close',()=>{if(built){unarrange();}});
 })();

 // ----- Morpheme editor (created by a later module) -----
 const morphemes=()=>{
  const editor=$('morpheme-editor'),form=$('morpheme-form');if(!editor||!form)return;
  let built=false,fresh=false,frame,addbar,plan,main,rest;const cards={},revealed=new Set();
  const taskGroups={gloss:['gloss','meaning','notes'],writing:['writing'],variants:['variants']};
  function build(){
   if(built)return;built=true;plan=layout(form);const at=plan.at;
   frame=header(editor,form);
   at(frame.title,()=>$('morpheme-form-value').closest('.multipart-form-editor')||$('morpheme-form-value').closest('label'));
   at(frame.commands,()=>editor.querySelector('.dialog-bottom button[type=submit],.dialog-bottom button.primary'),frame.cancel);
   at(frame.info,()=>form.querySelector('.morpheme-type-fields'),frame.index);
   const panelContent=id=>[...($(id)?.children||[])].filter(n=>n.tagName!=='SUMMARY');
   // Short gloss and its additions | meaning and function | readings and writing | allomorphs.
   const gloss=card(cards,'gloss',ui('简短标注','Short gloss'));at(gloss,()=>$('morpheme-gloss')?.closest('label'),()=>form.querySelector('.morpheme-core-fields .sense-addition-controls'));
   const meaning=card(cards,'meaning',ui('意义／功能','Meaning and function')),writing=card(cards,'writing',ui('读音与书写','Readings and writing')),variants=card(cards,'variants',ui('语素变体','Allomorphs'));
   for(const [target,id] of [[meaning,'morpheme-meaning-panel'],[writing,'morpheme-writing-panel']])for(const child of panelContent(id))at(target,()=>child);
   at(variants.querySelector('.lx-card-head'),()=>$('morpheme-variant-add'));for(const child of panelContent('morpheme-variants-panel'))if(child.id!=='morpheme-variant-add')at(variants,()=>child);
   const notes=card(cards,'notes',ui('备注','Notes'));at(notes,()=>form.querySelector('details.dictionary-note:has(#morpheme-notes)'));
   addbar=make('div','lx-addbar');addbar.append(make('span','lx-addbar-label',ui('添加','Add')));const addNote=button('lx-add','＋ '+ui('备注','Note'));addNote.dataset.lxAdd='notes';addbar.append(addNote);
   const grid=make('div','lx-grid');grid.append(meaning,writing);
   main=make('div','lx-main');rest=make('div','lx-rest');main.append(gloss,grid,variants,notes,addbar,rest);
   form.prepend(frame.head);form.append(main);plan.apply(rest,[frame.head,main,$('morpheme-error')]);
   form.classList.add('lx-arranged','lx-morpheme');editor.classList.add('lx-editor');
   caption(form.querySelector('.lx-title .multipart-toggle'),ui('多部分','Multipart'));
   editor.addEventListener('click',e=>{const t=e.target.closest('button');if(!t)return;
    if(t.dataset.lxIndex){form.dataset.lxSection=t.dataset.lxIndex;refresh();}
    else if(t.dataset.lxAdd==='notes'){revealed.add('notes');refresh();const details=$('morpheme-notes').closest('details');if(details)details.open=true;$('morpheme-notes').focus();}});
  }
  function refresh(){
   if(!built)return;
   plan.apply(rest,[frame.head,main,$('morpheme-error')]);
   for(const toggle of form.querySelectorAll('.multipart-toggle'))caption(toggle,ui('多部分','Multipart'));
   for(const row of form.querySelectorAll('#morpheme-variants>.variant-editor')){decorateRow(row,row,false);variantSummary(row);}
   decorateCompact(form);fresh=false;
   const notes=$('morpheme-notes')?.value.trim()||revealed.has('notes');cards.notes.hidden=!notes;addbar.hidden=!!notes||(form.dataset.lxSection||'gloss')!=='gloss';
   const variants=form.querySelectorAll('#morpheme-variants>.variant-editor').length;
   renderIndex(frame.index,[['gloss',ui('意义／功能','Meaning and function')],['writing',ui('读音与书写','Readings')],['variants',ui('变体','Allomorphs')+(variants?' '+variants:'')]]);
   taskSection(form,frame.index,cards,taskGroups,'gloss');
   put(frame.state,window.corporiumMorphemeDirty?.()?ui('未保存的修改','Unsaved changes'):'');
  }
  watch(editor,form,refresh,()=>{build();fresh=true;revealed.clear();form.dataset.lxSection='gloss';},target=>{
   const owner=Object.entries(cards).find(([,node])=>node.contains(target))?.[0];
   if(owner)form.dataset.lxSection=Object.keys(taskGroups).find(key=>taskGroups[key].includes(owner))||'gloss';
   if(cards.notes?.contains(target)){revealed.add('notes');cards.notes.hidden=false;}
   refresh();
  });
 };
 if(document.readyState==='loading')document.addEventListener('DOMContentLoaded',morphemes,{once:true});else morphemes();
})();

/* Dictionary reading page: editing is the primary command, rarely used commands share one menu,
   and a section index leads to senses, morphology and examples. */
(()=>{
 const ui=(zh,en)=>globalThis.CorporiumI18n?.ui(zh,en)??zh;
 const detail=$('dictionary-detail');if(!detail)return;
 const targets=()=>[['heading',ui('概览','Overview'),detail.querySelector(':scope>.lexeme-heading')],['senses',ui('义项','Senses')+' '+detail.querySelectorAll('.lex-sense-view').length,detail.querySelector(':scope>.dictionary-core-columns')],['morphology',ui('形态与变化','Morphology'),detail.querySelector(':scope>.dictionary-morphology-block')],['examples',ui('例证','Examples'),$('dictionary-example-controls')]].filter(t=>t[2]&&!t[2].hidden);
 function readingSenses(){
  const usages=[...detail.querySelectorAll('.lex-usage-view')];
  for(const [u,usage] of usages.entries()){
   const heading=usage.querySelector(':scope>.usage-heading>h3'),subclass=usage.querySelector(':scope>.usage-subclass-view');
   if(heading&&subclass)heading.after(subclass);
   if(heading&&!heading.querySelector('.usage-number')){
    const number=document.createElement('span'),label=document.createElement('span');number.className='usage-number';number.textContent=String(u+1);label.className='usage-name';label.textContent=heading.textContent.replace(/^\d+\.\s*/,'');heading.replaceChildren(number,label);
   }
   for(const [s,sense] of [...usage.querySelectorAll(':scope>.lex-sense-view')].entries()){
    const identity=sense.querySelector('.sense-identity>strong');if(!identity||identity.querySelector('.sense-number'))continue;
    const number=document.createElement('span'),label=document.createElement('span');number.className='sense-number';number.textContent=(u+1)+'.'+(s+1);label.className='sense-kind';label.textContent=ui('义项','Sense');identity.replaceChildren(number,label);
   }
  }
 }
  async function editReadingMorphology(kind){
   const owner=dictionarySelection,edit=$('edit-lexeme');if(!edit?.onclick)return;
   await edit.onclick();
   const editor=$('lexeme-editor');if(!editor?.open||editingLexeme?.id!==owner||dictionarySelection!==owner)return;
   editor.querySelector('[data-lx-index="'+(kind==='forms'?'writing':'morphology')+'"]')?.click();
   if(kind==='forms'){
    $('add-variant')?.click();
    $('lexeme-variants')?.lastElementChild?.querySelector('input:not([type=checkbox])')?.focus();
   }else{
    editor.querySelector('[data-lx-open=analysis],[data-lx-add=analysis]')?.click();
    $('ws-add-analysis')?.click();
   }
  }
  function readingMorphology(){
   const block=detail.querySelector(':scope>.dictionary-morphology-block');if(!block)return;
   const put=(node,text)=>{if(node&&node.textContent!==text)node.textContent=text;};
   const make=(tag,cls,text)=>{const node=document.createElement(tag);node.className=cls;if(text!==undefined)node.textContent=text;return node;};
   const summary=block.querySelector(':scope>summary');put(summary,ui('形态与关系','Morphology & relations'));
   block.classList.add('reading-morphology');
   const structure=block.querySelector(':scope>.word-structure-view'),forms=block.querySelector(':scope>.morphology-view');
   if(structure){
    let head=structure.querySelector(':scope>.reading-morphology-heading');
    const hasAnalysis=!!structure.querySelector(':scope>.ws-analysis-view');
    if(!head){
     const title=hasAnalysis?structure.querySelector(':scope>h3'):null;
     head=make('div','reading-morphology-heading');structure.prepend(head);head.append(title||make('h3','',ui('语素构成','Morphemic structure')));
     const empty=make('span','reading-morphology-empty ui-help',ui('尚未登记','Not registered'));
     const tools=make('div','reading-morphology-tools ui-controls--compact'),add=make('button','',ui('添加分析','Add analysis'));add.type='button';add.dataset.readingAddAnalysis='';add.onclick=dictSafe(()=>editReadingMorphology('analysis'));tools.append(add);head.append(empty,tools);
    }
    structure.classList.toggle('reading-structure-empty',!hasAnalysis);head.classList.toggle('brief-empty',!hasAnalysis);
    head.querySelector('.reading-morphology-empty').hidden=hasAnalysis;
    head.querySelector('[data-reading-add-analysis]').hidden=hasAnalysis;
    const organize=block.querySelector('[data-organize-morphemes]'),tools=head.querySelector('.reading-morphology-tools');
    if(organize){
     if(organize.parentElement!==tools)tools.prepend(organize);
     put(organize,ui('关联语素','Assign morphemes'));organize.hidden=organize.dataset.components==='0';
     let status=head.querySelector('.reading-morphology-status');
     if(!status){status=make('span','reading-morphology-status ui-help');tools.before(status);}
     const total=organize.dataset.components;status.hidden=!total||total==='0';
     if(total)put(status,ui('已关联 '+organize.dataset.assigned+'/'+total,'Assigned '+organize.dataset.assigned+'/'+total));
    }
   }
   if(forms&&!forms.dataset.readingMorphology){
    forms.dataset.readingMorphology='true';const title=forms.querySelector(':scope>h3');
    if(!title)return;
    // Keep entry-level features and relationships as their original nodes.
    const metadata=[];for(const node of [...forms.childNodes]){if(node===title)break;if(node.nodeType!==3||node.textContent.trim())metadata.push(node);}
    if(metadata.length){const related=make('section','reading-morphology-relations'),heading=make('h3','',ui('条目关系与特征','Relations & features'));related.append(heading,...metadata);block.append(related);}
    const populated=!!forms.querySelector(':scope>.morph-form-view'),head=make('div','reading-morphology-heading');title.before(head);head.append(title);put(title,ui('词形与变体','Forms & variants'));
    if(!populated){
     forms.classList.add('reading-forms-empty','brief-empty');const empty=forms.querySelector(':scope>p.brief-empty');
     if(empty){empty.classList.add('reading-morphology-empty','ui-help');put(empty,ui('尚未登记','Not registered'));head.append(empty);}
     const tools=make('div','reading-morphology-tools ui-controls--compact'),add=make('button','',ui('添加形式','Add form'));add.type='button';add.onclick=dictSafe(()=>editReadingMorphology('forms'));tools.append(add);head.append(tools);
    }
   }
   const related=block.querySelector(':scope>.reading-morphology-relations');
   const groups=[structure,forms,related].filter(Boolean),populated=node=>node===related||!!node.querySelector(':scope>.ws-analysis-view,:scope>ul,:scope>.morph-form-view');
   groups.sort((a,b)=>Number(populated(b))-Number(populated(a)));
   let previous=summary;for(const group of groups){if(previous.nextElementSibling!==group)previous.after(group);previous=group;}
  }
  function arrange(){
   readingSenses();readingMorphology();
  const actions=detail.querySelector(':scope>.lexeme-heading .lexeme-actions');
  if(actions){
   $('edit-lexeme')?.classList.add('primary');
   let menu=actions.querySelector(':scope>.reading-more');
   if(!menu){menu=document.createElement('details');menu.className='workbench-menu reading-more';
    menu.innerHTML='<summary aria-label="'+esc(ui('更多词条操作','More entry commands'))+'" title="'+esc(ui('更多词条操作','More entry commands'))+'">⋯</summary><div class="workbench-menu-items"></div>';
    menu.lastElementChild.addEventListener('click',e=>{if(e.target.closest('button'))menu.open=false;});actions.append(menu);}
   // Recording and media stay visible; commands other modules add later join the menu, deletion last.
   const items=menu.lastElementChild;
   for(const media of items.querySelectorAll('.object-media-controls'))menu.before(media);
   for(const b of actions.querySelectorAll(':scope>button:not(#edit-lexeme)'))items.append(b);
   const remove=$('delete-lexeme');if(remove&&remove.parentElement===items&&items.lastElementChild!==remove)items.append(remove);
   menu.hidden=!items.children.length;
  }
  const heading=detail.querySelector(':scope>.lexeme-heading');if(!heading)return;
  let nav=detail.querySelector(':scope>.reading-index');
  if(!nav){nav=document.createElement('nav');nav.className='reading-index';nav.setAttribute('aria-label',ui('词条分区','Entry sections'));heading.after(nav);
   nav.onclick=e=>{const b=e.target.closest('[data-reading]');if(!b)return;const target=targets().find(t=>t[0]===b.dataset.reading)?.[2];if(target){if(target.tagName==='DETAILS')target.open=true;target.scrollIntoView({block:'start',behavior:'smooth'});}};}
  const list=targets(),key=list.map(t=>t[0]+t[1]).join('|');
  if(nav.dataset.key!==key){nav.dataset.key=key;nav.replaceChildren(...list.map(([id,label])=>{const b=document.createElement('button');b.type='button';b.className='reading-index-item';b.dataset.reading=id;b.textContent=label;return b;}));}
 }
 detail.addEventListener('morpheme-links-ready',arrange);
 let frame=0;new MutationObserver(()=>{if(!frame)frame=requestAnimationFrame(()=>{frame=0;arrange();});}).observe(detail,{childList:true,subtree:true});
})();

/* Text corpus reading: the sentence in focus shows its commands; a single text does not repeat its title. */
(()=>{
 const results=$('results');if(!results)return;
 const syncScope=()=>{document.documentElement.dataset.corpusScope=selected?'text':'all';};
 const previousSelect=selectText;selectText=async function(...args){const result=await previousSelect(...args);syncScope();return result;};
 syncScope();
 const lists='#results,#library-results';
 document.addEventListener('pointerdown',e=>{
  const entry=e.target.closest('#results>article.entry,#library-results article');if(!entry)return;
  for(const other of document.querySelectorAll(':is('+lists+') .is-current'))if(other!==entry)other.classList.remove('is-current');
  entry.classList.add('is-current');
 });
})();

/* Inline sentence editing: the long usage hint becomes the title's tooltip; tools stay on one compact row. */
(()=>{
 const tidy=root=>{for(const tools of root.querySelectorAll('.inline-tools:has(>[data-inline-save],>strong)')){const hint=tools.querySelector(':scope>small');const title=tools.querySelector(':scope>strong');if(hint&&title&&!hint.hidden){title.title=hint.textContent.trim()+'\n'+(globalThis.CorporiumI18n?.ui('方向键：↑↓ 在同一词格的语素行、标注行和附加层之间切换；光标在字段两端时，←→ 移到相邻的语素或词格。','Arrow keys: ↑↓ switch between the morpheme, gloss and tier rows of one box; at either end of a field, ←→ move to the neighbouring piece or box.')??'方向键：↑↓ 在同一词格的语素行、标注行和附加层之间切换；光标在字段两端时，←→ 移到相邻的语素或词格。');title.classList.add('inline-hint-title');hint.hidden=true;}}};
 let frame=0;new MutationObserver(()=>{if(!frame)frame=requestAnimationFrame(()=>{frame=0;tidy(document.querySelector('main')||document);});}).observe(document.querySelector('main')||document.body,{childList:true,subtree:true});
})();

/* Tags and checks: the tag library and the annotation checks are two views of one module. */
(()=>{
 const root=$('grammar-workspace'),heading=root?.querySelector(':scope>.workbench-heading');if(!root||!heading)return;
 const ui=(zh,en)=>globalThis.CorporiumI18n?.ui(zh,en)??zh;
 const checks=[...root.querySelectorAll(':scope>h2')].find(h=>h.nextElementSibling?.matches('.filters'));if(!checks)return;
 checks.classList.add('grammar-checks-title');
 const choice=document.createElement('div');choice.className='app-segmented grammar-views';choice.setAttribute('role','tablist');choice.setAttribute('aria-label',ui('标签与检查视图','Labels and checks views'));
 for(const [view,label] of [['tags',ui('标签库','Label library')],['checks',ui('标注检查','Annotation checks')]]){const b=document.createElement('button');b.type='button';b.setAttribute('role','tab');b.dataset.grammarView=view;b.textContent=label;choice.append(b);}
 heading.append(choice);
 function show(view){root.dataset.grammarView=view;for(const b of choice.children){const on=b.dataset.grammarView===view;b.setAttribute('aria-selected',String(on));b.setAttribute('aria-pressed',String(on));}try{localStorage.setItem('corporium-grammar-view',view);}catch{}}
 choice.onclick=e=>{const b=e.target.closest('[data-grammar-view]');if(b)show(b.dataset.grammarView);};
 // Viewing a tag's examples fills the check results.
 root.addEventListener('click',e=>{if(e.target.closest('[data-tag-uses]'))show('checks');},true);
 let saved='tags';try{saved=localStorage.getItem('corporium-grammar-view')||'tags';}catch{}show(saved==='checks'?'checks':'tags');
 // Check types with their counts lead the check view; the type menu stays the single source of truth.
 const issue=$('grammar-issue');if(!issue)return;
 const types=document.createElement('nav');types.className='grammar-types';types.setAttribute('aria-label',ui('检查类型','Check types'));
 const list=document.createElement('div');list.className='grammar-type-list';
 const extras=document.createElement('div');extras.className='grammar-type-options';
 for(const id of ['grammar-source','grammar-lower']){const label=$(id)?.closest('label');if(label)extras.append(label);}
 types.append(Object.assign(document.createElement('h3'),{textContent:ui('检查类型','Check types')}),list,extras);checks.after(types);
 let counts=null,pending=false;
 function renderTypes(){
  types.setAttribute('aria-busy',String(pending));
  const options=[...issue.options].filter(o=>o.value!=='usage'||issue.value==='usage'),total=counts===null?null:Object.entries(counts).filter(([k])=>k!=='usage').reduce((sum,[,v])=>sum+v,0);
  list.replaceChildren(...options.map(o=>{const b=document.createElement('button');b.type='button';b.dataset.issue=o.value;b.setAttribute('aria-pressed',String(o.value===issue.value));
   const n=counts===null?null:o.value==='all'?total:counts[o.value]||0;b.append(Object.assign(document.createElement('span'),{textContent:o.textContent}),Object.assign(document.createElement('small'),{textContent:n===null?'—':String(n)}));
   b.title=counts!==null?ui('按当前语言、来源和候选范围统计，包含全部检查类型','Counts include every check type for the current language, source and candidate scope'):pending?ui('正在等待检查结果','Waiting for check results'):ui('尚无可用检查结果','No check result available');
   b.classList.toggle('is-empty',n===0&&o.value!=='all'&&o.value!==issue.value);return b;}));
 }
 list.onclick=e=>{const b=e.target.closest('[data-issue]');if(!b||b.dataset.issue===issue.value)return;issue.value=b.dataset.issue;issue.dispatchEvent(new Event('change',{bubbles:true}));renderTypes();};
 // Use the accepted view result: the background-task transport may bypass api wrappers.
 window.addEventListener('corporium-grammar-audit',event=>{pending=!!event.detail.pending;counts=event.detail.counts??null;renderTypes();});
 issue.addEventListener('change',renderTypes);renderTypes();
})();

/* Settings center: the management dialog groups settings by scope; appearance offers the two main
   themes as cards, the classic palettes, automatic switching and text size. */
(()=>{
 const ui=(zh,en)=>globalThis.CorporiumI18n?.ui(zh,en)??zh;
 // Interface density is a local preference, applied before the settings center exists.
 const densityKey='corporium-density';
 try{if(localStorage.getItem(densityKey)==='compact')document.documentElement.dataset.density='compact';}catch{}
 const build=()=>{
  const dialog=$('management-dialog');if(!dialog||dialog.classList.contains('settings-center'))return;
  // Dock the management shell before mounting forms: the generic dialog
  // docker must not pull their submit buttons into a separate dialog footer.
  if(!dialog.dataset.docked){
   const top=document.createElement('div'),body=document.createElement('div');top.className='dialog-top';body.className='dialog-content';
   const close=dialog.querySelector(':scope>form[method=dialog]');if(close)top.append(close);
   while(dialog.firstChild)body.append(dialog.firstChild);dialog.append(top,body);dialog.dataset.docked='true';
  }
  const content=dialog.querySelector('.dialog-content');
  dialog.classList.add('settings-center');
  const themeSelect=$('theme-select'),root=document.documentElement;
  const layout=document.createElement('div');layout.className='settings-layout';
  const nav=document.createElement('nav');nav.className='settings-nav';nav.setAttribute('aria-label',ui('设置分区','Settings sections'));
  const pages=document.createElement('div');pages.className='settings-pages';
  const groups=[[ui('本机设置','This computer'),ui('外观与全局阅读设置','Appearance and global reading settings'),[['appearance',ui('外观','Appearance')],['fonts',ui('全局设置','Global settings')]]],[ui('项目与语言','Project and language'),ui('语言内容与项目共用资料','Language content and shared project data'),[['project',ui('项目内容','Project content')],['backup',ui('备份与关于','Backup and about')]]]];
  const page={};
  for(const [title,note,items] of groups){
   const scope=document.createElement('section');scope.className='settings-scope';scope.setAttribute('aria-label',title);
   const head=document.createElement('div');head.className='settings-group';head.append(Object.assign(document.createElement('strong'),{textContent:title}),Object.assign(document.createElement('small'),{textContent:note}));scope.append(head);nav.append(scope);
   for(const [id,label] of items){const b=document.createElement('button');b.type='button';b.dataset.settingsPage=id;b.textContent=label;scope.append(b);const section=document.createElement('section');section.className='settings-page';section.dataset.settingsPage=id;const h=document.createElement('h3');h.textContent=label;section.append(h);pages.append(section);page[id]=section;}
  }
  // Appearance: theme cards, classic palettes, automatic switching and text size.
  const cards=document.createElement('div');cards.className='theme-cards';cards.setAttribute('role','radiogroup');cards.setAttribute('aria-label',ui('界面主题','Interface theme'));
  for(const [id,name,note] of [['docoid','Docoid',ui('日间 · 文档阅读','Day · document reading')],['dawoid','DAWoid',ui('夜间 · 工作站','Night · workstation')]]){const b=document.createElement('button');b.type='button';b.setAttribute('role','radio');b.dataset.themeChoice=id;b.innerHTML='<span class="theme-swatch" data-swatch="'+id+'"><i></i><i></i><i></i></span><strong></strong><small></small>';b.querySelector('strong').textContent=name;b.querySelector('small').textContent=note;cards.append(b);}
  const classic=document.createElement('label');classic.className='settings-field';classic.append(ui('经典配色','Classic palettes'));
  const classicSelect=document.createElement('select');classicSelect.innerHTML='<option value=""></option>';for(const id of ['ivory','night','forest']){const o=themeSelect.querySelector('option[value="'+id+'"]');if(o)classicSelect.add(new Option(o.textContent,id));}
  classicSelect.options[0].textContent=ui('不使用','None');classic.append(classicSelect);
  const auto=document.createElement('fieldset');auto.className='theme-auto';auto.innerHTML='<legend></legend><div class="settings-choices"></div><span class="theme-schedule"><label><span></span><input type="time" data-auto-time="day"></label><label><span></span><input type="time" data-auto-time="night"></label></span>';
  auto.querySelector('legend').textContent=ui('自动切换','Automatic switching');
  for(const [mode,label] of [['fixed',ui('固定','Fixed')],['system',ui('跟随系统','Follow the system')],['schedule',ui('按时段','By time of day')]]){const l=document.createElement('label');const r=document.createElement('input');r.type='radio';r.name='theme-auto';r.value=mode;l.append(r,' '+label);auto.querySelector('.settings-choices').append(l);}
  const [dayLabel,nightLabel]=auto.querySelectorAll('.theme-schedule>label>span');dayLabel.textContent=ui('日间自','Day from');nightLabel.textContent=ui('夜间自','Night from');
  const scale=$('text-scale'),scaleLabel=document.querySelector('label[for="text-scale"]');
  const size=document.createElement('div');size.className='settings-field settings-text-scale';if(scaleLabel){scaleLabel.textContent=ui('全局文字大小','Global text size');size.append(scaleLabel);}if(scale)size.append(scale);
  const sizeNote=document.createElement('small');sizeNote.textContent=ui('立即生效，保存在本机；语言内各行的比例继续保留。','Applies immediately on this computer; language-specific row scales are preserved.');size.append(sizeNote);
  const themeLabel=document.querySelector('label[for="theme-select"]');const hidden=document.createElement('div');hidden.hidden=true;if(themeLabel)hidden.append(themeLabel);hidden.append(themeSelect);
  const density=document.createElement('fieldset');density.className='theme-auto settings-density';density.innerHTML='<legend></legend><div class="settings-choices"></div>';
  density.querySelector('legend').textContent=ui('界面密度','Density');
  for(const [value,label] of [['standard',ui('标准','Standard')],['compact',ui('紧凑','Compact')]]){const l=document.createElement('label');const r=document.createElement('input');r.type='radio';r.name='ui-density';r.value=value;r.checked=(root.dataset.density==='compact')===(value==='compact');l.append(r,' '+label);density.querySelector('.settings-choices').append(l);}
  density.addEventListener('change',e=>{const compact=e.target.value==='compact';if(compact)root.dataset.density='compact';else delete root.dataset.density;try{localStorage.setItem(densityKey,compact?'compact':'standard');}catch{}window.dispatchEvent(new Event('resize'));});
  const sizeLink=document.createElement('button');sizeLink.type='button';sizeLink.className='settings-size-link';sizeLink.textContent=ui('调整全局字号与字体 →','Adjust text size and fonts →');sizeLink.onclick=()=>show('fonts');
  page.appearance.append(cards,classic,auto,density,sizeLink,hidden);
  page.fonts.append(size);window.CorporiumGlobalSettings.mount(page.fonts);
  const scan=document.querySelector('#workbench-preferences .font-panel');if(scan)page.fonts.append(scan);
  const font=page.fonts.querySelector('.font-panel');if(font)font.open=true;
  const entries=$('management-entries');
  if(entries){
   page.project.append(entries);entries.setAttribute('role','list');
   const descriptions={
    'writing-manager-open':ui('词典：设置本语言词条与语素的书写形式、字体和排序。','Lexicon: writing systems, fonts and sorting for this language’s entries and morphemes.'),
    'layers-open':ui('文本与例句：设置本语言的附加标注层、适用单位和显示方式。','Texts and examples: extra annotation tiers, unit scopes and display settings for this language.'),
    'classes-open':ui('词典：管理本语言的词类、子类及条目分类。','Lexicon: parts of speech, subclasses and entry classifications for this language.'),
    speaker:ui('项目共用：管理合作者姓名、研究编号及引用信息。','Shared project data: contributor names, research identifiers and references.'),
    code:ui('项目共用：管理正文与轨道使用的语言名称和简称。','Shared project data: language names and abbreviations used in texts and tracks.'),
    'quick-edit-manager-open':ui('词典：选择本语言快捷编辑时显示的字段。','Lexicon: fields shown when quick-editing entries in this language.'),
    'paradigm-template-open':ui('词典：设置本语言的变形表模板与语法特征组合。','Lexicon: paradigm templates and grammatical feature combinations for this language.'),
    'judgment-manage-open':ui('例句：管理本语言的合法性判断符号与类型。','Examples: grammaticality judgment symbols and types for this language.')
   };
   const arrange=()=>arrangeManagementEntries(entries,descriptions);arrange();
   // Some managers mount after the settings shell. Decorate their original
   // buttons too, retaining their click handlers and the dialog close guard.
   new MutationObserver(arrange).observe(entries,{childList:true});
  }
  for(const node of [$('management-backup'),document.querySelector('#workbench-preferences footer')])if(node)page.backup.append(node);
  const title=content.querySelector(':scope>h2');if(title)title.textContent=ui('管理与设置','Management and settings');
  layout.append(nav,pages);content.append(layout);
  const leftovers=document.querySelector('#workbench-preferences .theme-panel');if(leftovers&&!leftovers.querySelector('button,select,input,details'))leftovers.hidden=true;
  $('workbench-preferences')?.classList.add('settings-moved');
  function show(id){for(const b of nav.querySelectorAll('[data-settings-page]'))b.setAttribute('aria-current',String(b.dataset.settingsPage===id));for(const s of pages.children)s.hidden=s.dataset.settingsPage!==id;try{localStorage.setItem('corporium-settings-page',id);}catch{}if(id==='fonts'&&dialog.open)void window.CorporiumGlobalSettings.load();}
  nav.onclick=e=>{const b=e.target.closest('[data-settings-page]');if(b)show(b.dataset.settingsPage);};
  let start='appearance';try{start=localStorage.getItem('corporium-settings-page')||start;}catch{}show(page[start]?start:'appearance');
  const globalSettings=window.CorporiumGlobalSettings;
  globalSettings.open=()=>{if(!dialog.open)dialog.showModal();show('fonts');void globalSettings.load();};
  dialog.addEventListener('close',()=>globalSettings.discard());
  new MutationObserver(()=>{if(dialog.open&&!page.fonts.hidden)void globalSettings.load();}).observe(dialog,{attributes:true,attributeFilter:['open']});
  const guardSettingsClose=event=>{
   if(globalSettings.busy()){event.preventDefault();return;}
   if(globalSettings.dirty())guardDialogDiscard(event,true,ui('放弃尚未保存的全局设置？','Discard unsaved global settings?'));
  };
  dialog.addEventListener('cancel',guardSettingsClose);
  dialog.querySelector('.dialog-top .close,form[method=dialog] .close')?.addEventListener('click',guardSettingsClose);
  dialog.addEventListener('click',event=>{
   const button=event.target.closest('#management-entries button,#management-backup button');if(!button||(!globalSettings.dirty()&&!globalSettings.busy()))return;
   event.preventDefault();event.stopImmediatePropagation();if(globalSettings.busy())return;
   void corporiumConfirm(ui('放弃尚未保存的全局设置并继续？','Discard unsaved global settings and continue?')).then(yes=>{if(yes&&button.isConnected){globalSettings.discard();button.click();}});
  },true);
  // Theme state: cards and the classic menu reflect the theme menu, the single source of truth.
  const key='corporium-theme-auto';let state={mode:'fixed',day:'07:00',night:'19:00'},applying=false;
  try{Object.assign(state,JSON.parse(localStorage.getItem(key)||'{}'));}catch{}
  const save=()=>{try{localStorage.setItem(key,JSON.stringify(state));}catch{}};
  const choose=theme=>{if(themeSelect.value!==theme){themeSelect.value=theme;themeSelect.dispatchEvent(new Event('change'));}};
  function sync(){const theme=root.dataset.theme;for(const b of cards.children)b.setAttribute('aria-checked',String(b.dataset.themeChoice===theme));classicSelect.value=['ivory','night','forest'].includes(theme)?theme:'';for(const r of auto.querySelectorAll('[name=theme-auto]'))r.checked=r.value===state.mode;auto.querySelector('[data-auto-time=day]').value=state.day;auto.querySelector('[data-auto-time=night]').value=state.night;auto.classList.toggle('scheduled',state.mode==='schedule');}
  const dark=matchMedia('(prefers-color-scheme: dark)');
  function desired(){
   if(state.mode==='system')return dark.matches?'dawoid':'docoid';
   if(state.mode!=='schedule')return null;
   const minutes=t=>{const [h,m]=String(t).split(':').map(Number);return (h||0)*60+(m||0);},now=new Date(),m=now.getHours()*60+now.getMinutes(),d=minutes(state.day),n=minutes(state.night);
   return (d<n?m>=d&&m<n:m>=d||m<n)?'docoid':'dawoid';
  }
  function applyAuto(){const theme=desired();if(!theme)return;applying=true;try{choose(theme);}finally{applying=false;}sync();}
  // A theme chosen by hand fixes the theme until automatic switching is chosen again.
  themeSelect.addEventListener('change',()=>{if(!applying&&state.mode!=='fixed'){state.mode='fixed';save();}sync();});
  cards.onclick=e=>{const b=e.target.closest('[data-theme-choice]');if(b)choose(b.dataset.themeChoice);};
  classicSelect.onchange=()=>{if(classicSelect.value)choose(classicSelect.value);};
  auto.addEventListener('change',e=>{if(e.target.name==='theme-auto')state.mode=e.target.value;else if(e.target.dataset.autoTime)state[e.target.dataset.autoTime]=e.target.value||state[e.target.dataset.autoTime];save();applyAuto();sync();});
  dark.addEventListener('change',applyAuto);setInterval(applyAuto,60000);applyAuto();sync();
 };
 if(document.readyState==='loading')document.addEventListener('DOMContentLoaded',build,{once:true});else build();
})();

/* Keep selection and numbering outside the repaintable draft. Measure only
   changed cards; offsets are relative to each card, not its page position. */
function createSentenceMeasurements(lists,doc=document,win=window){
 const observed=new Map(),dirty=new Set();let frame=0,all=true,rebuild=true,cards=[];
 const queue=()=>{if(!frame)frame=win.requestAnimationFrame(sync);};
 const invalidate=()=>{all=true;queue();};
 function sync(){
  frame=0;
  if(rebuild){
   rebuild=false;cards=lists.flatMap(list=>[...list.querySelectorAll(':scope>article.entry,.example-group-member')]);const current=new Set(cards);
   for(const [card,observer] of observed)if(!current.has(card)||!card.isConnected){observer.disconnect();observed.delete(card);dirty.delete(card);}
   for(const card of cards)if(!observed.has(card)){const observer=new ResizeObserver(entries=>{for(const entry of entries)dirty.add(entry.target);queue();});observer.observe(card);observed.set(card,observer);dirty.add(card);}
  }
  const pending=all?cards:cards.filter(card=>dirty.has(card));all=false;dirty.clear();
  const positions=[],footers=[];
  for(const card of pending){const check=card.querySelector(':scope>.entry-head input[data-pick],:scope>.example-group-pick input[data-group-select]');const selectable=!!check;if(card.classList.contains('sentence-selectable')!==selectable)card.classList.toggle('sentence-selectable',selectable);}
  // Finish state reads/writes for every affected card before measuring lines.
  const lines=[];
  for(const card of pending){
   const check=card.querySelector(':scope>.entry-head input[data-pick],:scope>.example-group-pick input[data-group-select]');if((!check&&!card.querySelector(':scope>.sentence-number'))||!card.getClientRects().length)continue;
   const source=card.querySelector(':scope>.entry-head>span'),sourceVisible=!!source?.getClientRects().length;
   lines.push({card,source,sourceVisible});
  }
  for(const {card,sourceVisible} of lines)if(card.classList.contains('sentence-number-in-header')!==sourceVisible)card.classList.toggle('sentence-number-in-header',sourceVisible);
  for(const {card,source,sourceVisible} of lines){
   const line=sourceVisible?source:card.querySelector('.editable-example .ipa:not(textarea)')||card.querySelector('.editable-example [data-inline-field=ipa]');if(!line)continue;
   const style=win.getComputedStyle(line),lineHeight=parseFloat(style.lineHeight)||parseFloat(style.fontSize)*1.45,number=card.querySelector(':scope>.sentence-number');
   positions.push([card,Math.round((line.getBoundingClientRect().top-card.getBoundingClientRect().top+(parseFloat(style.paddingTop)||0)+lineHeight/2)*10)/10,number?.getBoundingClientRect().width||0]);
  }
  const seen=new Set();for(const card of pending)for(const footer of card.querySelectorAll('.sentence-footer')){if(seen.has(footer))continue;seen.add(footer);const actions=footer.querySelector('.sentence-footer-actions');if(actions)footers.push([footer,Math.ceil(actions.getBoundingClientRect().width)]);}
  for(const [card,y,width] of positions){if(card.style.getPropertyValue('--sentence-pick-offset')!==y+'px')card.style.setProperty('--sentence-pick-offset',y+'px');if(card.style.getPropertyValue('--sentence-number-width')!==width+'px')card.style.setProperty('--sentence-number-width',width+'px');}
  for(const [footer,width] of footers)if(footer.style.getPropertyValue('--sentence-actions-width')!==width+'px')footer.style.setProperty('--sentence-actions-width',width+'px');
 }
 for(const list of lists)new MutationObserver(records=>{
  for(const record of records){
   const target=record.target.nodeType===1?record.target:record.target.parentElement,card=target?.closest('article.entry,.example-group-member');
   if(card)dirty.add(card);
   for(const node of [...record.addedNodes,...record.removedNodes])if(node.nodeType===1&&(node.matches('article.entry,.example-group-member')||node.querySelector('article.entry,.example-group-member'))){rebuild=true;break;}
  }
  queue();
 }).observe(list,{childList:true,subtree:true});
 doc.fonts?.ready.then(invalidate);win.addEventListener('resize',invalidate);
 new MutationObserver(invalidate).observe(doc.documentElement,{attributes:true,attributeFilter:['style','class','data-density']});queue();
 return {invalidate};
}
(()=>{const lists=[$('results'),$('library-results')].filter(Boolean);if(lists.length)createSentenceMeasurements(lists);})();
/* Timeline: a time selection offers its confirmation beside the selection itself. */
(()=>{
 const ui=(zh,en)=>globalThis.CorporiumI18n?.ui(zh,en)??zh;
 const start=()=>{
  const label=$('tl-selection-label'),commit=$('tl-commit'),stage=document.querySelector('#timeline-workspace .tl-stage');if(!label||!commit||!stage)return;
  const chip=document.createElement('div');chip.className='tl-inline-confirm';chip.hidden=true;chip.setAttribute('role','group');chip.setAttribute('aria-label',ui('当前选区','Current selection'));
  const text=document.createElement('span'),confirm=document.createElement('button');confirm.type='button';confirm.className='primary';confirm.textContent=ui('✓ 确认区间','✓ Confirm interval');
  confirm.onclick=()=>{if(!commit.disabled)commit.click();};chip.append(text,confirm);stage.append(chip);
  let timer=0;
  function place(){
   const selected=label.textContent.trim(),workspace=$('timeline-workspace');
   if(!selected||workspace?.hidden){chip.hidden=true;clearInterval(timer);timer=0;return;}
   if(window.corporiumTimelineHasSelectedInterval?.()){chip.hidden=true;return;}
   const highlights=[...stage.querySelectorAll('.tl-range-highlight')].filter(h=>!h.hidden&&h.getClientRects().length),highlight=highlights.find(h=>h.closest('.tl-lane'))||highlights[0];
   if(!highlight){chip.hidden=true;return;}
   const box=highlight.getBoundingClientRect(),frame=stage.getBoundingClientRect();
   const ready=!commit.disabled;confirm.disabled=!ready;text.textContent=ready?selected:ui('先在左侧选择待对齐句子','Choose a sentence on the left first');
   chip.hidden=false;const width=chip.offsetWidth;
   const left=box.right-frame.left+6+width<=frame.width?box.right-frame.left+6:Math.max(8,box.left-frame.left-width-6);
   chip.style.left=Math.round(Math.max(8,Math.min(left,frame.width-width-8)))+'px';chip.style.top=Math.round(Math.max(4,box.top-frame.top+4))+'px';
  }
  new MutationObserver(()=>{place();if(label.textContent.trim()&&!timer)timer=setInterval(place,120);}).observe(label,{childList:true,characterData:true,subtree:true});
  new MutationObserver(place).observe(commit,{attributes:true,attributeFilter:['disabled']});
 };
 if(document.readyState==='loading')document.addEventListener('DOMContentLoaded',start,{once:true});else start();
})();

/* Text navigator: a filter above the texts narrows the list by title. */
(()=>{
 const ui=(zh,en)=>globalThis.CorporiumI18n?.ui(zh,en)??zh;
 const nav=$('workbench-corpus-nav'),list=$('texts');if(!nav||!list)return;
 const field=document.createElement('input');field.type='search';field.className='text-filter';field.autocomplete='off';field.placeholder=ui('筛选文本','Filter texts');field.setAttribute('aria-label',field.placeholder);
 nav.prepend(field);
 function apply(){
  const q=field.value.trim().toLowerCase();
  for(const item of list.querySelectorAll('[data-text]'))item.classList.toggle('nav-filtered-out',!!q&&!item.textContent.toLowerCase().includes(q));
  for(const group of list.querySelectorAll('details'))group.classList.toggle('nav-filtered-out',!!q&&!group.querySelector('[data-text]:not(.nav-filtered-out)'));
 }
 field.addEventListener('input',apply);
 new MutationObserver(()=>{if(field.value)apply();}).observe(list,{childList:true,subtree:true});
})();

/* Document-blue navigation with short, illustrated labels. These are the same
   buttons and commands: their handlers, IDs and draft guards remain in place. */
(()=>{
 const root=document.documentElement,bar=$('app-bar'),nav=bar?.querySelector('.workspace-tabs');if(!bar||!nav)return;
 const ui=(zh,en)=>globalThis.CorporiumI18n?.ui(zh,en)??zh;
 const paths={
  text:'M6 3h8l4 4v14H6zM14 3v5h4M9 12h6M9 16h6',
  dictionary:'M12 6c-3-2-6-2-9-1v15c3-1 6-1 9 1 3-2 6-2 9-1V5c-3-1-6-1-9 1zm0 0v15',
  examples:'M4 4h16v13H9l-5 4V4zm4 5h2v3H7V9l2-2m6 2h2v3h-3V9l2-2',
  survey:'M8 4H5v17h14V4h-3M9 2h6v4H9zM8 11l1 1 2-2m2 1h3m-8 6 1 1 2-2m2 1h3',
  tracks:'M3 5h18M3 12h18M3 19h18M7 3v18M10 7h7v3h-7zm3 7h7v3h-7z',
  analysis:'M4 3v18h17M8 16v-5m5 5V7m5 9V4',
  tags:'M3 4h10l8 8-9 9-9-9V4zm4 3h.01M10 13l2 2 5-5',
  manage:'M3 4h18v16H3zM3 9h18M9 9v11M6 6.5h.01M9 6.5h.01',
  replace:'M4 7h15m-4-4 4 4-4 4M20 17H5m4-4-4 4 4 4',
  copy:'M9 8h12v13H9zM16 8V3H3v13h6',
  link:'M10 13a5 5 0 0 0 7 0l3-3a5 5 0 0 0-7-7l-2 2m3 6a5 5 0 0 0-7 0l-3 3a5 5 0 0 0 7 7l2-2',
  punctuation:'M5 4v8m0 4h.01M11 16h.01M17 14h3v3h-3zm3 3a4 4 0 0 1-3 4'
 };
 function decorate(button,key,short,full){
  if(!button)return;
  const svg=document.createElementNS('http://www.w3.org/2000/svg','svg');svg.setAttribute('viewBox','0 0 24 24');svg.setAttribute('aria-hidden','true');svg.setAttribute('focusable','false');svg.classList.add('chrome-icon');
  const path=document.createElementNS(svg.namespaceURI,'path');path.setAttribute('d',paths[key]);svg.append(path);
  const caption=document.createElement('span');caption.className='chrome-caption';caption.textContent=short;
  button.replaceChildren(svg,caption);button.title=full;button.setAttribute('aria-label',full);
 }
 const labels=[
  ['corpus','text','文本','Texts','文本语料','Text corpus'],
  ['dictionary','dictionary','词典','Lexicon','词典','Lexicon'],
  ['library','examples','例句','Examples','独立例句库','Independent examples'],
  ['survey','survey','调查','Survey','语法调查','Grammar survey'],
  ['timeline','tracks','轨道','Tracks','时间轴','Timeline'],
  ['analysis','analysis','分析','Analysis','语料分析','Corpus analysis'],
  ['grammar','tags','标签与检查','Labels & checks','标签与检查','Labels and checks']
 ];
 function installNavigation(){
  for(const [name,key,zh,en,fullZh,fullEn] of labels)decorate($('workspace-'+name),key,ui(zh,en),ui(fullZh,fullEn));
  decorate($('management-open'),'manage',ui('管理','Manage'),ui('管理与设置','Management and settings'));
 }
 installNavigation();
 const management=$('management-open'),managementDialog=$('management-dialog');
 $('workspace-grammar').after(management);
 management.setAttribute('aria-haspopup','dialog');management.setAttribute('aria-controls',managementDialog.id);
 const syncManagement=()=>management.setAttribute('aria-expanded',String(managementDialog.open));
 new MutationObserver(syncManagement).observe(managementDialog,{attributes:true,attributeFilter:['open']});syncManagement();
 const syncCurrent=()=>{for(const [name] of labels){const button=$('workspace-'+name);if(button.getAttribute('aria-pressed')==='true')button.setAttribute('aria-current','page');else button.removeAttribute('aria-current');}};
 new MutationObserver(()=>{syncCurrent();schedule();}).observe(nav,{subtree:true,attributes:true,attributeFilter:['aria-pressed']});syncCurrent();
 function installCommands(){
  const row=$('workspace-toolbar')?.querySelector('.toolbar-row');if(!row)return;
  const find=$('sentence-search-grip'),replace=$('toolbar-replace-open'),copy=$('formatted-copy-open'),link=$('auto-link-open'),punctuation=$('punctuation-text');
  decorate(replace,'replace',ui('替换','Replace'),ui('查找替换','Find and replace'));
  const copyHelp=copy?.title||'';decorate(copy,'copy',ui('复制','Copy'),ui('带格式复制','Formatted copy')+(copyHelp?' · '+copyHelp:''));
  decorate(link,'link',ui('关联','Link'),ui('自动关联词典','Automatically link dictionary entries'));
  decorate(punctuation,'punctuation',ui('标点','Punctuation'),ui('识别并拆分标点','Identify and split punctuation'));
  if(replace)replace.setAttribute('aria-haspopup','dialog');
  if(punctuation){punctuation.type='button';punctuation.setAttribute('aria-haspopup','dialog');punctuation.setAttribute('aria-controls','punctuation-dialog');}
  const group=(key,label)=>{let node=row.querySelector('[data-chrome-group="'+key+'"]');if(!node){node=document.createElement('div');node.className='toolbar-command-group';node.dataset.chromeGroup=key;node.setAttribute('role','group');node.setAttribute('aria-label',label);row.append(node);}return node;};
  const edit=group('edit',ui('查找、替换与复制','Find, replace and copy')),links=group('link',ui('关联与标点','Links and punctuation'));
  if(find)edit.append(find);if(replace)edit.append(replace);if(copy)edit.append(copy.closest('.formatted-copy-controls'));if(link)links.append(link);if(punctuation)links.append(punctuation);
  // This is the original text-scoped command. Moving it out of the corpus
  // heading must not expose it in another workspace or change its scope.
  const syncPunctuation=()=>{if(punctuation)punctuation.hidden=workspace!=='corpus';};
  new MutationObserver(syncPunctuation).observe(root,{attributes:true,attributeFilter:['data-workbench']});syncPunctuation();
  function visibleGroups(){for(const node of [edit,links]){const hidden=[...node.children].every(child=>child.hidden);if(node.hidden!==hidden)node.hidden=hidden;}}
  new MutationObserver(visibleGroups).observe(row,{subtree:true,attributes:true,attributeFilter:['hidden']});visibleGroups();
 }
 // Later modules finish naming their original buttons before this final pass.
 if(document.readyState==='loading')document.addEventListener('DOMContentLoaded',()=>{installNavigation();installCommands();},{once:true});else installCommands();
 let frame=0;
 const schedule=()=>{if(!frame)frame=requestAnimationFrame(layout);};
 function layout(){
  frame=0;if(!bar.getClientRects().length)return;const identity=bar.querySelector('.app-identity'),tools=bar.querySelector('.app-bar-tools');
  const style=getComputedStyle(nav),buttons=[...nav.children].filter(node=>!node.hidden&&getComputedStyle(node).display!=='none');
  const natural=buttons.reduce((sum,node)=>sum+node.getBoundingClientRect().width,0)+(parseFloat(style.paddingLeft)||0)+(parseFloat(style.paddingRight)||0)+(parseFloat(style.columnGap)||0)*Math.max(0,buttons.length-1);
  root.classList.toggle('chrome-nav-wrapped',natural+identity.getBoundingClientRect().width+tools.getBoundingClientRect().width>bar.clientWidth+1);
  const active=nav.querySelector('[aria-current=page]');
  if(active&&nav.scrollWidth>nav.clientWidth){const left=active.getBoundingClientRect().left-nav.getBoundingClientRect().left+nav.scrollLeft,right=left+active.offsetWidth;if(left<nav.scrollLeft)nav.scrollLeft=left;else if(right>nav.scrollLeft+nav.clientWidth)nav.scrollLeft=right-nav.clientWidth;}
  const height=Math.ceil(bar.getBoundingClientRect().height),minimum=parseFloat(getComputedStyle(bar).minHeight);
  // The CSS fallback already supplies an unwrapped bar's height. Do not write
  // zero while home hides it, or replace an identical fallback on entry: both
  // writes invalidate inherited properties and wake hidden timeline layouts.
  const measured=Math.abs(height-minimum)<.01?'':height+'px';
  if(root.style.getPropertyValue('--app-bar-measured-height')!==measured){if(measured)root.style.setProperty('--app-bar-measured-height',measured);else root.style.removeProperty('--app-bar-measured-height');document.dispatchEvent(new Event('corporium-chrome-layout'));}
 }
 const resize=new ResizeObserver(schedule);for(const node of [bar,nav,bar.querySelector('.app-identity'),bar.querySelector('.app-bar-tools')])resize.observe(node);
 document.fonts?.ready.then(schedule);document.fonts?.addEventListener('loadingdone',schedule);window.addEventListener('resize',schedule);
 new MutationObserver(schedule).observe(root,{attributes:true,attributeFilter:['style','data-home','data-density']});schedule();
})();
