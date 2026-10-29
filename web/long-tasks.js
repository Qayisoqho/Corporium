(() => {
 const normalApi=api,taskApi=originalApi;
 const progress=document.createElement('dialog');progress.className='long-task-dialog';progress.setAttribute('aria-labelledby','long-task-title');
 progress.innerHTML=(globalThis.CorporiumI18n?.f("5711a67ad7b9d8",()=>[])??'<h2 id="long-task-title" tabindex="-1" autofocus>正在处理</h2><p id="long-task-message" role="status"></p><progress id="long-task-progress" max="100" aria-label="任务进度"></progress><p class="long-task-hint">处理期间暂停其他操作。取消不会修改原数据。</p><button id="long-task-cancel" type="button">取消任务</button>');
 document.body.append(progress);progress.addEventListener('cancel',e=>e.preventDefault());
 let queue=Promise.resolve(),active=false,progressHolds=0;
 // Consecutive phases of one action keep their progress window open.
 window.corporiumWithTaskProgress=async function(action){
  progressHolds++;
  try{return await action();}
  finally{if(!--progressHolds){active=false;if(progress.open)progress.close();}}
 };
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
  const updating=progressHolds>0&&kind==='auto-match',hint=progress.querySelector?.('.long-task-hint');
  $('long-task-title').textContent=updating?(globalThis.CorporiumI18n?.ui('更新剩余候选','Updating remaining candidates')??'更新剩余候选'):title;
  if(hint)hint.textContent=updating?(globalThis.CorporiumI18n?.ui('关联已保存。取消只停止剩余候选的刷新。','Links have been saved. Cancelling only stops refreshing the remaining candidates.')??'关联已保存。取消只停止剩余候选的刷新。'):(globalThis.CorporiumI18n?.ui('处理期间暂停其他操作。取消不会修改原数据。','Other actions are paused while processing. Cancelling will not change the original data.')??'处理期间暂停其他操作。取消不会修改原数据。');
  $('long-task-message').textContent=(globalThis.CorporiumI18n?.f("96b6f7fc63bf08",()=>[])??'正在准备…');$('long-task-progress').removeAttribute('value');$('long-task-cancel').disabled=false;$('long-task-cancel').textContent=(globalThis.CorporiumI18n?.f("976c4962fc4a10",()=>[])??'取消任务');
  $('long-task-cancel').onclick=async()=>{cancelRequested=true;$('long-task-cancel').disabled=true;$('long-task-cancel').textContent=(globalThis.CorporiumI18n?.f("fb949a945e4c1d",()=>[])??'正在取消…');$('long-task-message').textContent=(globalThis.CorporiumI18n?.f("66b7a40120d863",()=>[])??'正在取消并清理临时文件…');if(id)try{await taskApi('task-cancel',{id});}catch(e){$('long-task-message').textContent=(globalThis.CorporiumI18n?.f("98e26d93a7b4a2",()=>[])??'取消请求暂未送达，正在重试…');}};
  let status=null,statusText=null,statusCancel=null;
  if(background){status=document.createElement('div');status.className='dictionary-search-progress';status.dataset.taskProgress='true';status.setAttribute('role','status');statusText=document.createElement('span');statusText.textContent=(globalThis.CorporiumI18n?.f("c6e69ac1211a99",()=>[])??'正在检索…');statusCancel=document.createElement('button');statusCancel.type='button';statusCancel.textContent=(globalThis.CorporiumI18n?.f("327a00b61f4aab",()=>[])??'取消');statusCancel.setAttribute('aria-label',(globalThis.CorporiumI18n?.f("78dc12a8b44205",()=>[])??'取消词典检索'));statusCancel.onclick=()=>{statusText.textContent=(globalThis.CorporiumI18n?.f("dcec169534621f",()=>[])??'正在取消检索…');statusCancel.disabled=true;return $('long-task-cancel').onclick();};status.append(statusText,statusCancel);$('dictionary-notice').after(status);}
  else if(!progress.open)progress.showModal();
  try{
   id=(await taskApi('task-start',{kind,request})).id;
   for(;;){
    if(cancelRequested)await taskApi('task-cancel',{id});
    const state=await taskApi('task-status?id='+encodeURIComponent(id));
    $('long-task-message').textContent=state.message;
    $('long-task-cancel').disabled=cancelRequested||state.state==='committing';
    $('long-task-cancel').textContent=cancelRequested?(globalThis.CorporiumI18n?.f("8081b8fc14b8e1",()=>[])??'正在取消…'):state.state==='committing'?(globalThis.CorporiumI18n?.f("de6fb1f4dc82fd",()=>[])??'正在提交…'):(globalThis.CorporiumI18n?.f("65ca0ffa8263f3",()=>[])??'取消任务');
    if(background){statusCancel.disabled=cancelRequested||!['queued','running'].includes(state.state);statusCancel.hidden=state.state==='committing';if(!cancelRequested)statusText.textContent=(globalThis.CorporiumI18n?.f("2aece9eb4ab57d",()=>[])??'正在检索…');}
    if(state.progress==null)$('long-task-progress').removeAttribute('value');else $('long-task-progress').value=state.progress;
    if(state.state==='done'){finished=true;return state.result;}
    if(state.state==='error'||state.state==='cancelled'){finished=true;if(background&&state.state==='cancelled')throw new DOMException((globalThis.CorporiumI18n?.f("1720e3a42617f8",()=>[])??'检索已取消'),'AbortError');throw Error(state.message);}
    await new Promise(resolve=>setTimeout(resolve,background?80:400));
   }
  }finally{
   const close=()=>{active=!background&&progressHolds>0;if(background)status?.remove();else if(!progressHolds&&progress.open)progress.close();};
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
  ['analysis-run',(globalThis.CorporiumI18n?.f("0eba070b55284e",()=>[])??'运行语料分析')],['analysis-save',(globalThis.CorporiumI18n?.f("a2c1f53c2a8284",()=>[])??'保存分析快照')],['import',(globalThis.CorporiumI18n?.f("4341f1a4be7adb",()=>[])??'导入文本')],['import-language',(globalThis.CorporiumI18n?.f("61a93f17e70024",()=>[])??'导入语言数据')],['language-package-import',(globalThis.CorporiumI18n?.f("0bf326130c8b7d",()=>[])??'导入语言数据包')],
  ['excel-inspect',(globalThis.CorporiumI18n?.f("be9fed147b6e19",()=>[])??'读取 Excel')],['excel-preview',(globalThis.CorporiumI18n?.f("1f777737b76813",()=>[])??'预览 Excel')],['excel-import',(globalThis.CorporiumI18n?.f("817457c5c8110e",()=>[])??'导入 Excel 文本')],
  ['text-replace-preview',(globalThis.CorporiumI18n?.f("dc0ead40eaad9c",()=>[])??'预览文本替换')],['text-replace-apply',(globalThis.CorporiumI18n?.f("8d9315581c5b8f",()=>[])??'应用文本替换')],
  ['dictionary-replace-preview',(globalThis.CorporiumI18n?.f("1ec1b918c8ea2b",()=>[])??'预览词典替换')],['dictionary-replace-apply',(globalThis.CorporiumI18n?.f("e5b82ae81988ce",()=>[])??'应用词典替换')],
  ['punctuation-preview',(globalThis.CorporiumI18n?.f("eeabd0a2f97a91",()=>[])??'预览标点拆分')],['punctuation-apply',(globalThis.CorporiumI18n?.f("627bf37ab4d1ac",()=>[])??'应用标点拆分')],['lexeme-auto-link',(globalThis.CorporiumI18n?.f("ed221d0390701e",()=>[])??'批量关联词典')],
  ['dictionary-batch-preview',(globalThis.CorporiumI18n?.f("534ea9b85cc6b5",()=>[])??'预览词条批量编辑')],['dictionary-batch-apply',(globalThis.CorporiumI18n?.f("a976334faee7bb",()=>[])??'批量编辑词条')],['dict-org-assign',(globalThis.CorporiumI18n?.f("5ac06e02fa45e4",()=>[])??'批量归类')],['homophone-phonology-save',(globalThis.CorporiumI18n?.f("f0f4ed8e474514",()=>[])??'保存音系与读音归类')],['morpheme-assign',(globalThis.CorporiumI18n?.f("ee98d0529d33b6",()=>[])??'整理组分语素')],['morpheme-merge',(globalThis.CorporiumI18n?.f("2365efb60f28ef",()=>[])??'归并语素')],
  ['move',(globalThis.CorporiumI18n?.f("ac9c8195a6b1ac",()=>[])??'移动句子')],['copy-text',globalThis.CorporiumI18n?.phrase('复制文本')??'复制文本'],['copy-entries',(globalThis.CorporiumI18n?.f("5082a78b4d102a",()=>[])??'复制句子')],['merge',(globalThis.CorporiumI18n?.f("bae65771ff285e",()=>[])??'合并文本')],['split',(globalThis.CorporiumI18n?.f("3c4e51b67d7b34",()=>[])??'拆分文本')],['word-transfer',(globalThis.CorporiumI18n?.f("e521852b9b3490",()=>[])??'转移词格')],
  ['lexeme-save',(globalThis.CorporiumI18n?.f("bd426a1a41a750",()=>[])??'保存词条')],['morpheme-save',(globalThis.CorporiumI18n?.f("132ad2c2a8adc9",()=>[])??'保存语素')]
 ]);
 api=async function(path,body){
  const url=new URL(path,'http://corporium.local/'),name=url.pathname.slice(1),params=Object.fromEntries(url.searchParams);
  if(!body&&name==='lexemes'){
   let spec={};try{spec=JSON.parse(params.search||'{}');}catch{return normalApi(path,body);}
   if(params.q?.trim()||spec?.conditions?.length||spec?.class_id)return run('dictionary',params,(globalThis.CorporiumI18n?.f("37e94bce460f0b",()=>[])??'检索词典'));
  }
  if(!body&&name==='lexeme-auto-preview')return run('auto-match',params,(globalThis.CorporiumI18n?.f("982ffa3716955a",()=>[])??'自动匹配词典'));
  if(!body&&name==='timeline-detail'&&params.complete==='1')return run('timeline',params,(globalThis.CorporiumI18n?.f("9693b67dd9f46d",()=>[])??'加载时间轴'));
  if(body&&name==='language-package-export')return run('language-package',body,(globalThis.CorporiumI18n?.f("eadeaf594e3aa7",()=>[])??'生成语言数据包'));
  if(!body&&['grammar-audit','statistics','analysis-result','homophones'].includes(name))return run(name,params,name==='grammar-audit'?(globalThis.CorporiumI18n?.f("a77f88a0f72c30",()=>[])??'标注检查'):name==='statistics'?(globalThis.CorporiumI18n?.f("a686589421083f",()=>[])??'统计词数与句数'):name==='homophones'?(globalThis.CorporiumI18n?.f("9d4aad2dc675ca",()=>[])??'整理同音语素表'):(globalThis.CorporiumI18n?.f("750222960c2575",()=>[])??'整理分析结果'));
  if(body&&operations.has(name)&&(!['lexeme-save','morpheme-save'].includes(name)||body.id)&&(name!=='analysis-save'||body.kind==='snapshot')){
   const result=await run('operation',{language:body._language||activeLanguage,operation:name,body},operations.get(name));
   // Outside the serial task promise: refreshing a view can itself enqueue a search.
   if(!name.startsWith('analysis-')&&!name.endsWith('-preview')&&name!=='excel-inspect'&&name!=='lexeme-auto-link')await refreshUndo().catch(()=>{});
   return result;
  }
  return normalApi(path,body);
 };
 const saving=document.createElement('dialog');saving.className='long-task-dialog';
 saving.innerHTML=(globalThis.CorporiumI18n?.f("074176e413c6f5",()=>[])??'<h2>文件已生成</h2><p id="long-task-file-summary"></p><button id="long-task-save" class="primary">选择保存位置</button> <button id="long-task-save-close">关闭</button><p id="long-task-save-status" role="status"></p>');
 document.body.append(saving);$('long-task-save-close').onclick=()=>saving.close();
 async function saveFile(data,name,kind){
  const url='/api/task-download?'+new URLSearchParams({token:data.token,kind,...(kind==='analysis-json'?{name}:{}),...(typeof desktopProjectStamp==='string'?{project:desktopProjectStamp}:{})});
  if(window.pywebview?.api?.save_task_export){const r=await window.pywebview.api.save_task_export(data.token,name,kind);if(r.error)throw Error(r.error);return r.cancelled?(globalThis.CorporiumI18n?.f("2767459c248a26",()=>[])??'已取消保存，生成的文件暂时保留。'):(globalThis.CorporiumI18n?.f("f943c0cbf94b42",()=>[r.path])??'已保存：'+r.path);}
  if(window.showSaveFilePicker){
   const handle=await window.showSaveFilePicker({suggestedName:name});const response=await fetch(url);if(!response.ok)throw Error((globalThis.CorporiumI18n?.f("655da52554eff5",()=>[])??'文件已过期，请重新生成'));
   const dest=await handle.createWritable();try{await response.body.pipeTo(dest);}catch(e){await dest.abort().catch(()=>{});throw e;}return (globalThis.CorporiumI18n?.f("610d4ba338a938",()=>[])??'文件已保存。');
  }
  const a=document.createElement('a');a.href=url;a.download=name;a.click();return (globalThis.CorporiumI18n?.f("b2736d5b6d4b69",()=>[])??'已开始下载，保存位置由浏览器下载设置决定。');
 }
 function offer(data,name,kind){
  $('long-task-file-summary').textContent=(globalThis.CorporiumI18n?.f("d007a0ba5b1786",()=>[name,(data.size/1048576).toFixed(1)])??name+' · '+(data.size/1048576).toFixed(1)+' MB。临时导出文件保留一小时，仅保留最近三份，请及时保存。');$('long-task-save-status').textContent='';
  $('long-task-save').onclick=async()=>{try{$('long-task-save-status').textContent=await saveFile(data,name,kind);}catch(e){if(e.name!=='AbortError')$('long-task-save-status').textContent=e.message;}};saving.showModal();
 }
 window.corporiumOfferTaskFile=offer;
 $('exchange-export-json').onclick=async()=>{try{const d=await run('language-json',{},(globalThis.CorporiumI18n?.f("df1b0c03e36acc",()=>[])??'生成语言 JSON'));offer(d,d.name.replace(/[\\/:*?"<>|]/g,'-')+'.json','language-json');}catch(e){await corporiumAlert(e.message);}};
 const backup=document.createElement('dialog');backup.className='long-task-dialog';
 backup.innerHTML=(globalThis.CorporiumI18n?.f("2fcc31da916c86",()=>[])??'<h2>完整项目备份</h2><p>保存 SQLite 数据库快照、项目内媒体及词条附件，保留关联和撤销记录。外部音视频默认保留链接。</p><label class="long-task-check"><input id="backup-linked-media" type="checkbox">同时携带外部链接的音视频</label><p>恢复时创建新项目，不覆盖现有项目。仍支持恢复旧版 JSON 备份。</p><button id="backup-create" class="primary">生成备份包</button> <button id="backup-close">取消</button>');
 document.body.append(backup);$('backup-close').onclick=()=>backup.close();$('backup').onclick=()=>backup.showModal();
 $('backup-create').onclick=async()=>{const include_media=$('backup-linked-media').checked;backup.close();try{const d=await run('backup',{include_media},(globalThis.CorporiumI18n?.f("b53701bced3ce0",()=>[])??'生成完整项目备份'));offer(d,d.name,'project-backup');}catch(e){await corporiumAlert(e.message);}};
 window.addEventListener('beforeunload',e=>{if(active){e.preventDefault();e.returnValue='';}});
})();
