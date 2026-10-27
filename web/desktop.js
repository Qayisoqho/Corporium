(()=>{
 const css=document.createElement('style');css.textContent='body:has(#desktop-toolbar){padding-top:var(--project-bar-height,42px)}body:has(#desktop-toolbar)>aside{top:var(--project-bar-height,42px)}#desktop-toolbar{position:fixed;z-index:90;top:0;left:0;right:0;height:42px;display:flex;align-items:center;gap:8px;padding:4px 12px;background:var(--sidebar,var(--paper));color:var(--ink);border-bottom:1px solid var(--line);font:12px var(--ui-font,"Segoe UI"),"Microsoft YaHei",sans-serif}#desktop-toolbar button{padding:3px 9px;font-size:12px}#desktop-project{overflow:hidden;text-overflow:ellipsis;white-space:nowrap;flex:1}#desktop-error{white-space:pre-wrap;color:#a14535}';document.head.append(css);
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
 function installCollapse(bar){
  let collapsed=false;try{collapsed=localStorage.getItem('corporium-project-bar-collapsed')==='true';}catch{}
  const toggle=document.createElement('button');toggle.id='desktop-bar-toggle';bar.append(toggle);
  const apply=()=>{document.documentElement.classList.toggle('project-bar-collapsed',collapsed);document.documentElement.style.setProperty('--project-bar-height',collapsed?'16px':'42px');toggle.innerHTML='<svg viewBox="0 0 16 16" width="14" height="14" aria-hidden="true"><path d="'+(collapsed?'M4 6l4 4 4-4':'M4 10l4-4 4 4')+'" fill="none" stroke="currentColor" stroke-width="1.5" stroke-linecap="round" stroke-linejoin="round"/></svg>';toggle.title=collapsed?(globalThis.CorporiumI18n?.f("69ee23a4851608",()=>[])??'展开项目路径栏'):(globalThis.CorporiumI18n?.f("ba19bddad2c18f",()=>[])??'收起项目路径栏');toggle.setAttribute('aria-label',toggle.title);toggle.setAttribute('aria-expanded',String(!collapsed));};
  toggle.onclick=()=>{collapsed=!collapsed;apply();try{localStorage.setItem('corporium-project-bar-collapsed',String(collapsed));}catch{}};apply();
 }
 css.textContent+='#desktop-toolbar{box-sizing:border-box}#desktop-toolbar #desktop-bar-toggle{flex:0 0 28px;display:inline-flex;align-items:center;justify-content:center;align-self:center;width:28px;height:26px;line-height:1;padding:0;margin:0;min-height:0;box-sizing:border-box}#desktop-bar-toggle svg{display:block;flex:none}html.project-bar-collapsed #desktop-toolbar{height:16px;padding:0 12px;justify-content:flex-end}html.project-bar-collapsed #desktop-toolbar>:not(#desktop-bar-toggle){display:none}html.project-bar-collapsed #desktop-toolbar #desktop-bar-toggle{height:15px;border:0;background:transparent}';
 const status=fetch('/desktop-status').then(r=>r.json()).then(s=>{
  if(s.startup_error)document.getElementById('desktop-error').textContent=s.startup_error;
  if(s.project){const bar=document.createElement('nav');bar.id='desktop-toolbar';bar.innerHTML=(globalThis.CorporiumI18n?.f("94e5bcbc566fed",()=>[s.version])??'<span>Corporium '+s.version+'</span><span id="desktop-project"></span><button data-project-action="new">新建项目</button><button data-project-action="open">打开项目</button><button data-project-action="restore">恢复备份</button><button data-project-action="folder">项目文件夹</button>');document.body.prepend(bar);document.getElementById('desktop-project').textContent=s.project;document.getElementById('desktop-project').title=s.project;installCollapse(bar);}
  else {const list=document.getElementById('desktop-recent');for(const path of s.recent){const button=document.createElement('button');button.textContent=path;button.dataset.projectAction='recent';button.dataset.path=path;list.append(button);}if(!s.recent.length)list.textContent=(globalThis.CorporiumI18n?.f("bb950395e1dfcf",()=>[])??'暂无最近项目。');}
 });
 document.addEventListener('click',async e=>{
  const button=e.target.closest('[data-project-action]');if(!button||busy)return;
  const action=button.dataset.projectAction;
  try{if(action!=='folder'){if(await window.corporiumLeaveCodes?.()===false)return;await window.corporiumFlushSurvey?.();await window.corporiumFlushNotes?.();await window.corporiumFlushTimeline?.();}}catch(error){corporiumStatus(error.message);return;}
  if(action!=='folder'&&((typeof inlineDrafts!=='undefined'&&[...inlineDrafts.values()].some(d=>d.dirty||d.saving))||window.corporiumTimelineDirty?.()||document.querySelector('dialog[open]'))&&!await corporiumConfirm((globalThis.CorporiumI18n?.f("2d697d444cbaca",()=>[])??'切换项目会放弃未保存的修改，继续吗？')))return;
  busy=true;button.disabled=true;
  try{if(!window.pywebview?.api)throw Error((globalThis.CorporiumI18n?.f("4194a0934529ce",()=>[])??'桌面接口尚未就绪，请稍后重试。'));const result=await window.pywebview.api.project_action(action,button.dataset.path||null);if(result.error)throw Error(result.error);if(result.ok&&action!=='folder'){if(typeof inlineDrafts!=='undefined')inlineDrafts.clear();for(const dialog of document.querySelectorAll('dialog[open]'))dialog.close();location.href='/';}}
  catch(error){let target=document.getElementById('desktop-error');if(!target){target=document.createElement('p');target.id='desktop-error';document.querySelector('main').prepend(target);}target.textContent=error.message;}
  finally{busy=false;button.disabled=false;}
 });
})();
