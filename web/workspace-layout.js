// Persistent layout preferences, independent of corpus data and undo history.
const sidebar=document.querySelector('body>aside');sidebar.id='workspace-sidebar';
const toolbar=document.createElement('div');toolbar.id='workspace-toolbar';
const toolbarRow=document.createElement('div');toolbarRow.className='toolbar-row';
const sidebarToggle=document.createElement('button');sidebarToggle.id='sidebar-toggle';sidebarToggle.setAttribute('aria-controls',sidebar.id);
const historyToggle=document.createElement('button');historyToggle.id='history-toggle';historyToggle.textContent=(globalThis.CorporiumI18n?.f("366d3ee37054e2",()=>[])??'历史记录与步数 ▾');historyToggle.setAttribute('aria-expanded','false');historyToggle.setAttribute('aria-controls','workspace-history');
const historyPanel=document.createElement('div');historyPanel.id='workspace-history';historyPanel.hidden=true;
makeDialog('management-dialog',(globalThis.CorporiumI18n?.f("45ab57b86b5c1e",()=>[])??'<h2>管理</h2><div id="management-entries"></div><div id="management-backup"></div>'));
const managementButton=document.createElement('button');managementButton.id='management-open';managementButton.textContent=(globalThis.CorporiumI18n?.f("bd6421171cf233",()=>[])??'管理');managementButton.onclick=()=>$('management-dialog').showModal();workspaceTabs.append(managementButton);
for(const id of ['writing-manager-open','layers-open','classes-open']){const b=$(id);$('management-entries').append(b);b.addEventListener('click',()=>$('management-dialog').close(),{capture:true});}
document.body.append(sidebarToggle);
toolbarRow.append(briefLabel,$('auto-link-open'),$('undo-action'),$('redo-action'),historyToggle);
historyPanel.append(undoPanel);
historyPanel.querySelector('details').open=true;
toolbar.append(workspaceTabs,toolbarRow,historyPanel);main.prepend(toolbar);
historyToggle.onclick=()=>{historyPanel.hidden=!historyPanel.hidden;historyToggle.setAttribute('aria-expanded',String(!historyPanel.hidden));historyToggle.textContent=(globalThis.CorporiumI18n?.f("eb04c88b2fb877",()=>[historyPanel.hidden?'▾':'▴'])??'历史记录与步数 '+(historyPanel.hidden?'▾':'▴'));};
let sidebarWidth=260,sidebarCollapsed=false;
let sidebarScope=workspace==='dictionary'?'dictionary':'shared';
const sidebarWidthKey=()=>sidebarScope==='dictionary'?'corporium-dictionary-sidebar-width':'corporium-sidebar-width';
const sidebarDefaultWidth=()=>sidebarScope==='dictionary'?480:260;
try{sidebarWidth=Number(localStorage.getItem(sidebarWidthKey()))||sidebarDefaultWidth();sidebarCollapsed=localStorage.getItem('corporium-sidebar-collapsed')==='true';}catch{}
const resizeHandle=document.createElement('div');resizeHandle.id='sidebar-resize';resizeHandle.tabIndex=0;resizeHandle.role='separator';resizeHandle.setAttribute('aria-label',(globalThis.CorporiumI18n?.f("c16ac9baed1b99",()=>[])??'调整侧栏宽度'));resizeHandle.setAttribute('aria-orientation','vertical');resizeHandle.setAttribute('aria-controls',sidebar.id);resizeHandle.title=(globalThis.CorporiumI18n?.f("26a0b64297c794",()=>[])??'拖动调整宽度；方向键微调；双击恢复默认');document.body.append(resizeHandle);
function applySidebar(save=false){
 const max=Math.max(220,Math.min(480,innerWidth*.6));sidebarWidth=Math.round(Math.max(220,Math.min(max,sidebarWidth)));
 document.documentElement.style.setProperty('--sidebar-width',sidebarWidth+'px');document.documentElement.classList.toggle('sidebar-collapsed',sidebarCollapsed);
 sidebar.hidden=sidebarCollapsed;sidebarToggle.innerHTML='<svg viewBox="0 0 10 24" aria-hidden="true"><path d="M7 6 3 12 7 18"/></svg>';sidebarToggle.title=sidebarCollapsed?(globalThis.CorporiumI18n?.f("0ea8ce584e433b",()=>[])??'展开侧栏'):(globalThis.CorporiumI18n?.f("bf8ac5603de64d",()=>[])??'收起侧栏');sidebarToggle.setAttribute('aria-label',sidebarToggle.title);sidebarToggle.setAttribute('aria-expanded',String(!sidebarCollapsed));
 resizeHandle.setAttribute('aria-valuemin','220');resizeHandle.setAttribute('aria-valuemax',String(Math.round(max)));resizeHandle.setAttribute('aria-valuenow',String(sidebarWidth));
 if(save)try{localStorage.setItem(sidebarWidthKey(),String(sidebarWidth));localStorage.setItem('corporium-sidebar-collapsed',String(sidebarCollapsed));}catch{}
 document.dispatchEvent(new CustomEvent('corporium-sidebar-layout',{detail:{collapsed:sidebarCollapsed}}));
}
sidebarToggle.onclick=()=>{sidebarCollapsed=!sidebarCollapsed;applySidebar(true);};
resizeHandle.onpointerdown=e=>{if(e.button!==0)return;e.preventDefault();resizeHandle.setPointerCapture(e.pointerId);document.documentElement.classList.add('sidebar-dragging');};
resizeHandle.onpointermove=e=>{if(!resizeHandle.hasPointerCapture(e.pointerId))return;sidebarWidth=e.clientX;applySidebar();};
function endResize(){document.documentElement.classList.remove('sidebar-dragging');applySidebar(true);}
resizeHandle.onpointerup=resizeHandle.onpointercancel=endResize;resizeHandle.onlostpointercapture=endResize;
resizeHandle.ondblclick=()=>{sidebarWidth=sidebarDefaultWidth();applySidebar(true);};
resizeHandle.onkeydown=e=>{if(['ArrowLeft','ArrowRight','Home','End'].includes(e.key)){e.preventDefault();sidebarWidth=e.key==='Home'?220:e.key==='End'?480:sidebarWidth+(e.key==='ArrowRight'?10:-10);applySidebar(true);}};
window.corporiumApplyWorkspaceSidebar=()=>{
 const scope=workspace==='dictionary'?'dictionary':'shared';
 if(scope!==sidebarScope){
  sidebarScope=scope;sidebarWidth=sidebarDefaultWidth();
  try{sidebarWidth=Number(localStorage.getItem(sidebarWidthKey()))||sidebarDefaultWidth();}catch{}
  applySidebar();
 }
};
window.addEventListener('resize',()=>applySidebar());applySidebar();
new ResizeObserver(()=>document.documentElement.style.setProperty('--toolbar-height',toolbar.offsetHeight+'px')).observe(toolbar);
const briefDetailShow=showLexeme;showLexeme=async function(...args){await briefDetailShow(...args);const controls=$('dictionary-example-controls');if(controls)controls.classList.toggle('brief-empty',$('corpus-examples-section')?.classList.contains('brief-empty')&&$('standalone-examples')?.classList.contains('brief-empty'));};
