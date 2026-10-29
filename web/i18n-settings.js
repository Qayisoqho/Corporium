(()=>{
 'use strict';
 const I=window.CorporiumI18n;if(!I)return;
 const label=I.ui('界面语言','Interface language');
 const select=document.createElement('select');select.id='interface-language';select.setAttribute('aria-label',label);
 select.innerHTML='<option value="zh-CN">中文</option><option value="en">English</option>';select.value=I.locale;
 const projectKey=()=>typeof projectStorageKey==='function'?projectStorageKey('corporium-interface-resume'):'corporium-interface-resume';
 function capture(){
  const filters=[...document.querySelectorAll('.search input[id],.search select[id],.filters input[id],.filters select[id],.search-row input[id],.search-row select[id],#example-group-filter,#library-sort,#grammar-query,#grammar-source,#grammar-issue,#grammar-lower')].filter(e=>e.type!=='file').map(e=>({id:e.id,value:e.value,checked:e.type==='checkbox'?e.checked:undefined}));
  const containers=[...document.querySelectorAll('[id]')].filter(e=>e.scrollTop||e.scrollLeft).map(e=>({id:e.id,x:e.scrollLeft,y:e.scrollTop}));
  return {home:typeof homeVisible!=='undefined'?homeVisible:true,workspace:typeof workspace!=='undefined'?workspace:'',page:typeof page!=='undefined'?page:1,libraryPage:typeof libraryPage!=='undefined'?libraryPage:1,dictionaryPage:typeof dictionaryPage!=='undefined'?dictionaryPage:1,grammarPage:typeof grammarPage!=='undefined'?grammarPage:1,views:I.captureView(typeof workspace!=='undefined'?workspace:''),filters,containers,x:window.scrollX,y:window.scrollY};
 }
 async function readyToSwitch(){
  if(I.locale===select.value)return true;
  try{
   await window.corporiumFlushSurvey?.();await window.corporiumFlushNotes?.();await window.corporiumFlushTimeline?.();
   const event=new Event('beforeunload',{cancelable:true});
   if(!window.dispatchEvent(event)){
    const message=I.ui('请先保存或取消尚未完成的编辑，再切换界面语言。','Save or cancel unfinished edits before changing the interface language.');
    if(typeof corporiumAlert==='function')await corporiumAlert(message);else window.alert(message);
    return false;
   }
   return true;
  }catch(error){if(typeof corporiumAlert==='function')await corporiumAlert(error.message);else window.alert(error.message);return false;}
 }
 async function apply(){
  const value=select.value;if(!I.valid(value)||value===I.locale)return;
  if(document.documentElement.dataset.desktop==='true'){
   if(!window.pywebview?.api?.set_ui_language)throw Error(I.ui('桌面接口尚未就绪，请稍后重试。','The desktop interface is not ready. Try again shortly.'));
   const result=await window.pywebview.api.set_ui_language(value);if(result.error)throw Error(result.error);
  }
  if(typeof saveHomePlace==='function')saveHomePlace();
  try{sessionStorage.setItem(projectKey(),JSON.stringify(capture()));}catch{}
  const stored=I.persist(value),url=new URL(location.href);
  if(!stored||url.searchParams.has('ui'))url.searchParams.set('ui',value);
  location.replace(url.href);
 }
 const form=document.getElementById('typography-form');
 if(form){
  const content=document.createElement('div');content.id='global-interface-settings';content.className='interface-language-setting';
  const field=document.createElement('label');field.append(document.createTextNode(label),select);content.append(field);
  form.prepend(content);
  if(typeof mountGlobalSettingsSection==='function')mountGlobalSettingsSection(content,'interface',I.ui('语言设置','Language'));
  const open=document.getElementById('global-settings').onclick;
  document.getElementById('global-settings').onclick=async function(...args){select.value=I.locale;return open?.apply(this,args);};
  const submit=form.onsubmit;
  form.onsubmit=async function(event){
   event.preventDefault();const changed=select.value!==I.locale;
   if(changed&&!await readyToSwitch())return;
   await submit.call(this,event);
   if(changed&&!document.getElementById('typography-dialog').open){
    try{await apply();}catch(error){document.getElementById('typography-dialog').showModal();if(typeof corporiumAlert==='function')await corporiumAlert(error.message);}
   }
  };
 }else if(document.getElementById('desktop-recent')){
  const field=document.createElement('label');field.className='startup-interface-language';field.append(document.createTextNode(I.ui('语言 / Language','Language / 语言')),select);
  document.getElementById('startup-language').append(field);
  // The control is visible immediately; wait for the native preferences bridge.
  select.disabled=document.documentElement.dataset.desktop==='true'&&!window.pywebview?.api?.set_ui_language;
  window.addEventListener('pywebviewready',()=>{select.disabled=false;},{once:true});
  select.onchange=async()=>{
   select.disabled=true;
   try{await apply();}catch(error){document.getElementById('desktop-error').textContent=error.message;select.value=I.locale;}
   finally{select.disabled=false;}
  };
 }
 async function restore(){
  let state;try{state=JSON.parse(sessionStorage.getItem(projectKey())||'null');sessionStorage.removeItem(projectKey());}catch{}
  if(!state||typeof homeRestored==='undefined')return;
  document.documentElement.dataset.uiRestoring='true';
  try{
   await homeRestored;
   if(!state.home&&typeof enterHomeWorkspace==='function')await enterHomeWorkspace();
   for(const saved of state.filters||[]){const el=document.getElementById(saved.id);if(!el)continue;if(saved.checked!==undefined)el.checked=saved.checked;else el.value=saved.value;}
   if(typeof workspace!=='undefined'&&workspace===state.workspace){
    if(workspace==='corpus'){page=state.page||1;await search();}
    else if(workspace==='library'){libraryPage=state.libraryPage||1;await loadLibrary();}
    else if(workspace==='dictionary'){dictionaryPage=state.dictionaryPage||1;await loadDictionary();}
    else if(workspace==='grammar'){grammarPage=state.grammarPage||1;await loadGrammar();}
   }
   await I.restoreView(state.views);
   await new Promise(requestAnimationFrame);
   for(const pos of state.containers||[]){const el=document.getElementById(pos.id);if(el){el.scrollTop=pos.y;el.scrollLeft=pos.x;}}
   window.scrollTo({left:state.x||0,top:state.y||0,behavior:'instant'});
  }finally{document.documentElement.dataset.uiRestoring='false';}
 }
 void restore().catch(error=>{if(typeof corporiumAlert==='function')void corporiumAlert(error.message);});
})();
