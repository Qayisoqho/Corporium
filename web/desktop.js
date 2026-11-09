(()=>{
 const css=document.createElement('style');css.textContent='#desktop-error{white-space:pre-wrap;color:var(--danger,#a32626)}';document.head.append(css);
 const ui=(zh,en)=>globalThis.CorporiumI18n?.ui(zh,en)??zh;
 // Pages without the application status bar keep the original fixed project bar.
 const legacyBar='body:has(#desktop-toolbar){padding-top:var(--project-bar-height,42px)}body:has(#desktop-toolbar)>aside{top:var(--project-bar-height,42px)}#desktop-toolbar{position:fixed;z-index:90;top:0;left:0;right:0;height:42px;display:flex;align-items:center;gap:8px;padding:4px 12px;background:var(--sidebar,var(--paper));color:var(--ink);border-bottom:1px solid var(--line);font:12px var(--ui-font,"Segoe UI"),"Microsoft YaHei",sans-serif}#desktop-toolbar button{padding:3px 9px;font-size:12px}#desktop-project{overflow:hidden;text-overflow:ellipsis;white-space:nowrap;flex:1}';
 let busy=false;
 let minimumRunning=false,minimumAgain=false,minimumApplied=null;
 async function syncSidebarMinimum(){
  if(!window.pywebview?.api?.set_sidebar_collapsed)return;
  if(minimumRunning){minimumAgain=true;return;}
  minimumRunning=true;
  try{do{minimumAgain=false;const collapsed=document.documentElement.classList.contains('sidebar-collapsed');if(collapsed!==minimumApplied){const r=await window.pywebview.api.set_sidebar_collapsed(collapsed);if(r.error)throw Error(r.error);minimumApplied=collapsed;}}while(minimumAgain||minimumApplied!==document.documentElement.classList.contains('sidebar-collapsed'));}
  catch(error){corporiumStatus((globalThis.CorporiumI18n?.f("b47bd6d897e7da",()=>[error.message])??'窗口宽度限制更新失败：'+error.message));}
  finally{minimumRunning=false;}
 }
 document.addEventListener('corporium-sidebar-layout',()=>void syncSidebarMinimum());
 window.addEventListener('pywebviewready',()=>void syncSidebarMinimum());void syncSidebarMinimum();
 // The project path and project commands open from the status bar, above the workspace.
 function installProjectMenu(host,bar,project){
  const ui=(zh,en)=>globalThis.CorporiumI18n?.ui(zh,en)??zh;
  const button=document.createElement('button');button.type='button';button.id='desktop-project-menu';button.setAttribute('aria-haspopup','true');button.setAttribute('aria-expanded','false');button.setAttribute('aria-controls','desktop-toolbar');
  button.innerHTML='<svg viewBox="0 0 24 24" width="13" height="13" fill="none" stroke="currentColor" stroke-width="2" stroke-linejoin="round" aria-hidden="true"><path d="M3 6a2 2 0 0 1 2-2h4l2 2h8a2 2 0 0 1 2 2v10a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2z"/></svg><span></span><svg viewBox="0 0 24 24" width="10" height="10" fill="none" stroke="currentColor" stroke-width="2.6" stroke-linecap="round" aria-hidden="true"><path d="m6 15 6-6 6 6"/></svg>';
  button.querySelector('span').textContent=project.split(/[\\/]/).filter(Boolean).pop()||project;button.title=ui('项目位置、新建、打开、恢复备份','Project location, new, open, restore backup');
  bar.hidden=true;bar.setAttribute('aria-label',ui('项目','Project'));host.append(button,bar);
  const close=(focus=false)=>{if(bar.hidden)return;bar.hidden=true;button.setAttribute('aria-expanded','false');if(focus)button.focus();};
  button.onclick=()=>{bar.hidden=!bar.hidden;button.setAttribute('aria-expanded',String(!bar.hidden));if(!bar.hidden)bar.querySelector('button')?.focus();};
  document.addEventListener('pointerdown',e=>{if(!host.contains(e.target))close();});
  bar.addEventListener('keydown',e=>{if(e.key==='Escape'){e.preventDefault();close(true);}});
  bar.addEventListener('click',e=>{if(e.target.closest('[data-project-action]'))close();});
 }
 function installCollapse(bar){
  let collapsed=false;try{collapsed=localStorage.getItem('corporium-project-bar-collapsed')==='true';}catch{}
  const toggle=document.createElement('button');toggle.id='desktop-bar-toggle';bar.append(toggle);
  const apply=()=>{document.documentElement.classList.toggle('project-bar-collapsed',collapsed);document.documentElement.style.setProperty('--project-bar-height',collapsed?'16px':'42px');toggle.innerHTML='<svg viewBox="0 0 16 16" width="14" height="14" aria-hidden="true"><path d="'+(collapsed?'M4 6l4 4 4-4':'M4 10l4-4 4 4')+'" fill="none" stroke="currentColor" stroke-width="1.5" stroke-linecap="round" stroke-linejoin="round"/></svg>';toggle.title=collapsed?(globalThis.CorporiumI18n?.f("69ee23a4851608",()=>[])??'展开项目路径栏'):(globalThis.CorporiumI18n?.f("ba19bddad2c18f",()=>[])??'收起项目路径栏');toggle.setAttribute('aria-label',toggle.title);toggle.setAttribute('aria-expanded',String(!collapsed));};
  toggle.onclick=()=>{collapsed=!collapsed;apply();try{localStorage.setItem('corporium-project-bar-collapsed',String(collapsed));}catch{}};apply();
 }
 const legacyCollapse='#desktop-toolbar{box-sizing:border-box}#desktop-toolbar #desktop-bar-toggle{flex:0 0 28px;display:inline-flex;align-items:center;justify-content:center;align-self:center;width:28px;height:26px;line-height:1;padding:0;margin:0;min-height:0;box-sizing:border-box}#desktop-bar-toggle svg{display:block;flex:none}html.project-bar-collapsed #desktop-toolbar{height:16px;padding:0 12px;justify-content:flex-end}html.project-bar-collapsed #desktop-toolbar>:not(#desktop-bar-toggle){display:none}html.project-bar-collapsed #desktop-toolbar #desktop-bar-toggle{height:15px;border:0;background:transparent}';
 const status=fetch('/desktop-status').then(r=>r.json()).then(s=>{
  if(s.startup_error)document.getElementById('desktop-error').textContent=s.startup_error;
  if(s.project){const bar=document.createElement('nav');bar.id='desktop-toolbar';bar.innerHTML=(globalThis.CorporiumI18n?.f("94e5bcbc566fed",()=>[s.version])??'<span>Corporium '+s.version+'</span><span id="desktop-project"></span><button data-project-action="new">新建项目</button><button data-project-action="open">打开项目</button><button data-project-action="restore">恢复备份</button><button data-project-action="folder">项目文件夹</button>');const host=document.querySelector('#app-status .app-status-project');
   if(host)installProjectMenu(host,bar,s.project);else{css.textContent+=legacyBar+legacyCollapse;document.body.prepend(bar);installCollapse(bar);}
   document.getElementById('desktop-project').textContent=s.project;document.getElementById('desktop-project').title=s.project;}
  else {
   const list=document.getElementById('desktop-recent');list.replaceChildren();
   for(const path of s.recent){
    const button=document.createElement('button');button.type='button';button.className='startup-recent';button.dataset.projectAction='recent';button.dataset.path=path;button.title=path;
    button.innerHTML='<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linejoin="round" aria-hidden="true"><path d="M3 6a2 2 0 0 1 2-2h4l2 2h8a2 2 0 0 1 2 2v10a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2Z"/></svg><span class="startup-recent-text"><strong class="startup-recent-name"></strong><small class="startup-recent-path ui-help"></small></span><svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><path d="m9 5 7 7-7 7"/></svg>';
    button.querySelector('.startup-recent-name').textContent=path.split(/[\\/]/).filter(Boolean).pop()||path;button.querySelector('.startup-recent-path').textContent=path;list.append(button);
   }
   if(!s.recent.length){const empty=document.createElement('div');empty.className='startup-empty';const title=document.createElement('p');title.className='ui-text';title.textContent=ui('暂无最近项目。','No recent projects.');const help=document.createElement('p');help.className='ui-help';help.textContent=ui('打开的项目会显示在这里。','Projects you open will appear here.');empty.append(title,help);list.append(empty);}
   const version=document.getElementById('startup-version');if(version){version.textContent=s.version;version.setAttribute('aria-label',ui('版本 '+s.version+'，关于与许可','Version '+s.version+', about and licenses'));}
  }
 });
 document.addEventListener('click',async e=>{
  const button=e.target.closest('[data-project-action]');if(!button||busy)return;
  const action=button.dataset.projectAction;
  try{if(action!=='folder'){if(await window.corporiumLeaveCodes?.()===false)return;await window.corporiumFlushSurvey?.();await window.corporiumFlushNotes?.();await window.corporiumFlushTimeline?.();}}catch(error){corporiumStatus(error.message);return;}
  if(action!=='folder'&&((typeof inlineDrafts!=='undefined'&&[...inlineDrafts.values()].some(d=>d.dirty||d.saving))||window.corporiumTimelineDirty?.()||document.querySelector('dialog[open]'))&&!await corporiumConfirm((globalThis.CorporiumI18n?.f("2d697d444cbaca",()=>[])??'切换项目会放弃未保存的修改，继续吗？')))return;
  const label=action==='example'?button.querySelector('.ui-button-label'):null,originalLabel=label?.textContent;
  busy=true;button.disabled=true;button.setAttribute('aria-busy','true');
  if(label)label.textContent=ui('正在准备 Tëlira 示例…','Preparing Tëlira example…');
  try{if(!window.pywebview?.api)throw Error((globalThis.CorporiumI18n?.f("4194a0934529ce",()=>[])??'桌面接口尚未就绪，请稍后重试。'));const result=await window.pywebview.api.project_action(action,button.dataset.path||null);if(result.error)throw Error(result.error);if(result.ok&&action!=='folder'){if(typeof inlineDrafts!=='undefined')inlineDrafts.clear();for(const dialog of document.querySelectorAll('dialog[open]'))dialog.close();location.href='/';}}
  catch(error){let target=document.getElementById('desktop-error');if(!target){target=document.createElement('p');target.id='desktop-error';document.querySelector('main').prepend(target);}target.textContent=error.message;}
  finally{busy=false;button.disabled=false;button.removeAttribute('aria-busy');if(label)label.textContent=originalLabel;}
 });
})();
