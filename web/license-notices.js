/* Shared About page and on-demand, plain-text licenses; no project reads or writes. */
(()=>{
 const standalone=document.getElementById('legal-page-content');
 let host=standalone,dialog=null,loaded=false,sequence=0,info=null;
 if(!host){
  makeDialog('legal-notices-dialog','<h2>关于与许可</h2><div id="legal-notices-content"></div>');
  dialog=document.getElementById('legal-notices-dialog');host=document.getElementById('legal-notices-content');
  const button=document.createElement('button');button.type='button';button.id='legal-notices-open';button.textContent='关于与许可';
  document.getElementById('management-backup').append(button);
  button.onclick=()=>{document.getElementById('management-dialog').close();dialog.showModal();void open();};
 }
 host.classList.add('legal-notices-content');
 host.innerHTML='<section class="about-summary" aria-label="软件与开发者"><div class="about-title"><strong class="about-name">Corporium</strong><span class="about-version"></span></div><p class="about-description">面向田野语言学调查的本地语料工作区。</p><p class="about-credit">开发者 <span class="about-developer"></span></p><div class="about-actions"><a class="about-project" target="_blank" rel="noopener noreferrer" hidden>项目主页</a><a class="about-issues" target="_blank" rel="noopener noreferrer" hidden>问题反馈 · Issues</a><button class="about-copy" type="button" disabled>复制版本信息</button></div><p class="about-status" role="status"></p></section><details class="legal-notices-section"><summary>许可与第三方组件</summary><p class="legal-notices-intro">本程序及第三方组件的许可文件随软件保存，可在此离线查看。</p><label class="legal-notices-choice">许可文件<select aria-label="选择许可文件"></select></label><p class="legal-notices-status" role="status"></p><pre class="legal-notices-text" tabindex="0" aria-label="许可全文"></pre></details>';
 const select=host.querySelector('select'),status=host.querySelector('.legal-notices-status'),text=host.querySelector('pre'),section=host.querySelector('details');
 const aboutStatus=host.querySelector('.about-status'),copy=host.querySelector('.about-copy');
 async function read(url){const r=await fetch(url),body=await r.json();if(!r.ok||body.error)throw Error(body.error||'读取许可失败');return body;}
 async function show(){const ticket=++sequence;status.textContent='正在读取…';text.textContent='';try{const r=await read('/licenses/document?'+new URLSearchParams({id:select.value}));if(ticket!==sequence)return;text.textContent=r.text;text.scrollTop=0;status.textContent='';}catch(e){if(ticket===sequence)status.textContent=e.message;}}
 async function open(){
  if(loaded){aboutStatus.textContent='';return;}aboutStatus.textContent='正在读取…';
  try{
   const r=await read('/licenses/catalog');info=r.about;
   host.querySelector('.about-name').textContent=info.name;host.querySelector('.about-version').textContent=info.version;
   host.querySelector('.about-description').textContent=info.description;host.querySelector('.about-developer').textContent=info.developer;
   for(const [selector,url] of [['.about-project',info.project_url],['.about-issues',info.issues_url]]){const link=host.querySelector(selector);link.href=url;link.hidden=false;}
   select.replaceChildren();for(const item of r.items){const option=document.createElement('option');option.value=item.id;option.textContent=item.title;select.append(option);}
   if(!r.items.length)status.textContent='未找到随程序保存的许可文件';
   copy.disabled=false;loaded=true;aboutStatus.textContent='';if(section.open&&select.value)await show();
  }catch(e){aboutStatus.textContent=e.message;}
 }
 copy.onclick=async()=>{
  if(!info)return;
  const platform=navigator.userAgentData?.platform||navigator.platform||'未知';
  const value=info.name+' '+info.version+'\n系统：'+platform+'\n运行方式：'+(window.pywebview?'桌面版':'浏览器版');
  try{await navigator.clipboard.writeText(value);aboutStatus.textContent='已复制版本信息';}catch{aboutStatus.textContent='未能写入剪贴板，可复制上方的版本号。';}
 };
 section.ontoggle=()=>{if(section.open&&loaded&&select.value&&!text.textContent)void show();};
 select.onchange=()=>void show();if(standalone)void open();
})();
