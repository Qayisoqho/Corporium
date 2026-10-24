(() => {
 const normalApi=api,taskApi=originalApi;
 const progress=document.createElement('dialog');progress.className='long-task-dialog';progress.setAttribute('aria-labelledby','long-task-title');
 progress.innerHTML='<h2 id="long-task-title" tabindex="-1" autofocus>正在处理</h2><p id="long-task-message" role="status"></p><progress id="long-task-progress" max="100" aria-label="任务进度"></progress><p class="long-task-hint">处理期间暂停其他操作。取消不会修改原数据。</p><button id="long-task-cancel" type="button">取消任务</button>';
 document.body.append(progress);progress.addEventListener('cancel',e=>e.preventDefault());
 let queue=Promise.resolve(),active=false;
 window.corporiumLongTaskActive=()=>active;
 async function execute(kind,request,title){
  const background=kind==='dictionary';
  if(!background){
  await window.corporiumFlushSurvey?.();
  await window.corporiumFlushNotes?.();
  const savingMorpheme=kind==='operation'&&request.operation==='morpheme-save'&&request.body?.id;
  if(!savingMorpheme&&await window.corporiumLeaveMorpheme?.()===false)throw new DOMException('','AbortError');
  if(await window.corporiumLeaveCodes?.()===false)throw new DOMException('','AbortError');
  }
  let id=null,cancelRequested=false,finished=false;active=!background;
  $('long-task-title').textContent=title;$('long-task-message').textContent='正在准备…';$('long-task-progress').removeAttribute('value');$('long-task-cancel').disabled=false;$('long-task-cancel').textContent='取消任务';
  $('long-task-cancel').onclick=async()=>{cancelRequested=true;$('long-task-cancel').disabled=true;$('long-task-cancel').textContent='正在取消…';$('long-task-message').textContent='正在取消并清理临时文件…';if(id)try{await taskApi('task-cancel',{id});}catch(e){$('long-task-message').textContent='取消请求暂未送达，正在重试…';}};
  let status=null,statusText=null,statusCancel=null;
  if(background){status=document.createElement('div');status.className='dictionary-search-progress';status.dataset.taskProgress='true';status.setAttribute('role','status');statusText=document.createElement('span');statusText.textContent='正在检索…';statusCancel=document.createElement('button');statusCancel.type='button';statusCancel.textContent='取消';statusCancel.setAttribute('aria-label','取消词典检索');statusCancel.onclick=()=>{statusText.textContent='正在取消检索…';statusCancel.disabled=true;return $('long-task-cancel').onclick();};status.append(statusText,statusCancel);$('dictionary-notice').after(status);}
  else progress.showModal();
  try{
   id=(await taskApi('task-start',{kind,request})).id;
   for(;;){
    if(cancelRequested)await taskApi('task-cancel',{id});
    const state=await taskApi('task-status?id='+encodeURIComponent(id));
    $('long-task-message').textContent=state.message;
    $('long-task-cancel').disabled=cancelRequested||state.state==='committing';
    $('long-task-cancel').textContent=cancelRequested?'正在取消…':state.state==='committing'?'正在提交…':'取消任务';
    if(background){statusCancel.disabled=cancelRequested||!['queued','running'].includes(state.state);statusCancel.hidden=state.state==='committing';if(!cancelRequested)statusText.textContent='正在检索…';}
    if(state.progress==null)$('long-task-progress').removeAttribute('value');else $('long-task-progress').value=state.progress;
    if(state.state==='done'){finished=true;return state.result;}
    if(state.state==='error'||state.state==='cancelled'){finished=true;if(background&&state.state==='cancelled')throw new DOMException('检索已取消','AbortError');throw Error(state.message);}
    await new Promise(resolve=>setTimeout(resolve,background?80:400));
   }
  }finally{
   const close=()=>{active=false;if(background)status?.remove();else if(progress.open)progress.close();};
   // Finished results must dismiss their UI even if forgetting a job is slow.
   if(finished||background)close();
   try{if(id){if(!finished)await taskApi('task-cancel',{id}).catch(()=>{});else void taskApi('task-forget',{id}).catch(()=>{});}}
   finally{close();}
  }
 }
 function run(kind,request,title){
  const scoped={language:activeLanguage,...request};
  const task=queue.then(()=>execute(kind,scoped,title));queue=task.catch(()=>{});return task;
 }
 window.corporiumRunTask=run;
 const operations=new Map([
  ['analysis-run','运行语料分析'],['analysis-save','保存分析快照'],['import','导入文本'],['import-language','导入语言数据'],['language-package-import','导入语言数据包'],
  ['excel-inspect','读取 Excel'],['excel-preview','预览 Excel'],['excel-import','导入 Excel 文本'],
  ['text-replace-preview','预览文本替换'],['text-replace-apply','应用文本替换'],
  ['dictionary-replace-preview','预览词典替换'],['dictionary-replace-apply','应用词典替换'],
  ['punctuation-preview','预览标点拆分'],['punctuation-apply','应用标点拆分'],['lexeme-auto-link','批量关联词典'],
  ['dictionary-batch-preview','预览词条批量编辑'],['dictionary-batch-apply','批量编辑词条'],['dict-org-assign','批量归类'],['homophone-phonology-save','保存音系与读音归类'],['morpheme-assign','整理组分语素'],['morpheme-merge','归并语素'],
  ['move','移动句子'],['copy-entries','复制句子'],['merge','合并文本'],['split','拆分文本'],['word-transfer','转移词格'],
  ['lexeme-save','保存词条'],['morpheme-save','保存语素']
 ]);
 api=async function(path,body){
  const url=new URL(path,'http://corporium.local/'),name=url.pathname.slice(1),params=Object.fromEntries(url.searchParams);
  if(!body&&name==='lexemes'){
   let spec={};try{spec=JSON.parse(params.search||'{}');}catch{return normalApi(path,body);}
   if(params.q?.trim()||spec?.conditions?.length||spec?.class_id)return run('dictionary',params,'检索词典');
  }
  if(!body&&name==='lexeme-auto-preview')return run('auto-match',params,'自动匹配词典');
  if(!body&&name==='timeline-detail'&&params.complete==='1')return run('timeline',params,'加载时间轴');
  if(body&&name==='language-package-export')return run('language-package',body,'生成语言数据包');
  if(!body&&['grammar-audit','statistics','analysis-result','homophones'].includes(name))return run(name,params,name==='grammar-audit'?'标注检查':name==='statistics'?'统计词数与句数':name==='homophones'?'整理同音语素表':'整理分析结果');
  if(body&&operations.has(name)&&(!['lexeme-save','morpheme-save'].includes(name)||body.id)&&(name!=='analysis-save'||body.kind==='snapshot')){
   const result=await run('operation',{language:body._language||activeLanguage,operation:name,body},operations.get(name));
   // Outside the serial task promise: refreshing a view can itself enqueue a search.
   if(!name.startsWith('analysis-')&&!name.endsWith('-preview')&&name!=='excel-inspect')await refreshUndo().catch(()=>{});
   return result;
  }
  return normalApi(path,body);
 };
 const saving=document.createElement('dialog');saving.className='long-task-dialog';
 saving.innerHTML='<h2>文件已生成</h2><p id="long-task-file-summary"></p><button id="long-task-save" class="primary">选择保存位置</button> <button id="long-task-save-close">关闭</button><p id="long-task-save-status" role="status"></p>';
 document.body.append(saving);$('long-task-save-close').onclick=()=>saving.close();
 async function saveFile(data,name,kind){
  const url='/api/task-download?'+new URLSearchParams({token:data.token,kind,...(kind==='analysis-json'?{name}:{}),...(typeof desktopProjectStamp==='string'?{project:desktopProjectStamp}:{})});
  if(window.pywebview?.api?.save_task_export){const r=await window.pywebview.api.save_task_export(data.token,name,kind);if(r.error)throw Error(r.error);return r.cancelled?'已取消保存，生成的文件暂时保留。':'已保存：'+r.path;}
  if(window.showSaveFilePicker){
   const handle=await window.showSaveFilePicker({suggestedName:name});const response=await fetch(url);if(!response.ok)throw Error('文件已过期，请重新生成');
   const dest=await handle.createWritable();try{await response.body.pipeTo(dest);}catch(e){await dest.abort().catch(()=>{});throw e;}return '文件已保存。';
  }
  const a=document.createElement('a');a.href=url;a.download=name;a.click();return '已开始下载，保存位置由浏览器下载设置决定。';
 }
 function offer(data,name,kind){
  $('long-task-file-summary').textContent=name+' · '+(data.size/1048576).toFixed(1)+' MB。临时导出文件保留一小时，仅保留最近三份，请及时保存。';$('long-task-save-status').textContent='';
  $('long-task-save').onclick=async()=>{try{$('long-task-save-status').textContent=await saveFile(data,name,kind);}catch(e){if(e.name!=='AbortError')$('long-task-save-status').textContent=e.message;}};saving.showModal();
 }
 window.corporiumOfferTaskFile=offer;
 $('exchange-export-json').onclick=async()=>{try{const d=await run('language-json',{},'生成语言 JSON');offer(d,d.name.replace(/[\\/:*?"<>|]/g,'-')+'.json','language-json');}catch(e){await corporiumAlert(e.message);}};
 const backup=document.createElement('dialog');backup.className='long-task-dialog';
 backup.innerHTML='<h2>完整项目备份</h2><p>保存 SQLite 数据库快照、项目内媒体及词条附件，保留关联和撤销记录。外部音视频默认保留链接。</p><label class="long-task-check"><input id="backup-linked-media" type="checkbox">同时携带外部链接的音视频</label><p>恢复时创建新项目，不覆盖现有项目。仍支持恢复旧版 JSON 备份。</p><button id="backup-create" class="primary">生成备份包</button> <button id="backup-close">取消</button>';
 document.body.append(backup);$('backup-close').onclick=()=>backup.close();$('backup').onclick=()=>backup.showModal();
 $('backup-create').onclick=async()=>{const include_media=$('backup-linked-media').checked;backup.close();try{const d=await run('backup',{include_media},'生成完整项目备份');offer(d,d.name,'project-backup');}catch(e){await corporiumAlert(e.message);}};
 window.addEventListener('beforeunload',e=>{if(active){e.preventDefault();e.returnValue='';}});
})();
