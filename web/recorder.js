/* One project recorder for dictionary, independent examples, and timelines. */
(()=>{
 'use strict';
 const text=(zh,en)=>window.CorporiumI18n?.ui(zh,en)??zh;
 const live=t=>t&&['starting','recording','stopping'].includes(t.state);
 let context=null,take=null,devices=[],pending=[],timer=null,busy=false,failure='';
 const label=text('录音','Record');
 const markup=(kind,id)=>`<button type="button" data-record-kind="${esc(kind)}" data-record-id="${esc(id)}">${label}</button>`;
 window.CorporiumRecorder={button(kind,id){const host=document.createElement('span');host.innerHTML=markup(kind,id);return host.firstElementChild;},open};
 const timelineButton=$('tl-new');if(timelineButton){const button=window.CorporiumRecorder.button('timeline','');button.id='tl-record';button.textContent='●';button.title=label;button.setAttribute('aria-label',label);timelineButton.after(button);}
 const css=document.createElement('link');css.rel='stylesheet';css.href='/recorder.css';document.head.append(css);
 makeDialog('recorder-dialog',`<h2>${text('现场录音','Record audio')}</h2>
  <p id="recorder-destination"></p>
  <div class="recorder-grid">
   <label>${text('麦克风','Microphone')}<select id="recorder-device"></select></label>
   <label>${text('发言人','Speaker')}<select id="recorder-speaker"></select></label>
   <label id="recorder-target-label">${text('对应词形','Word form')}<select id="recorder-target"></select></label>
   <label>${text('名称','Name')}<input id="recorder-name" maxlength="160"></label>
  </div>
  <details class="recorder-settings"><summary>${text('录音规格','Recording settings')}</summary><div class="recorder-grid">
   <label>${text('采样率','Sample rate')}<select id="recorder-rate"><option value="48000">48 kHz</option><option value="44100">44.1 kHz</option><option value="96000">96 kHz</option></select></label>
   <label>${text('位深','Bit depth')}<select id="recorder-bits"><option value="24">24 bit</option><option value="16">16 bit</option></select></label>
   <label>${text('声道','Channels')}<select id="recorder-channels"><option value="1">${text('单声道','Mono')}</option><option value="2">${text('双声道','Stereo')}</option></select></label>
  </div><p>${text('保存无压缩 PCM WAV。请关闭设备或系统的降噪、自动增益等音效，以保留原始语音。','Saves uncompressed PCM WAV. Turn off device or system noise suppression, automatic gain and other enhancements to preserve the original speech.')}</p></details>
  <p id="recorder-format-note"></p>
  <div class="recorder-monitor"><output id="recorder-time">00:00.0</output><meter id="recorder-meter" min="-96" max="0" low="-45" high="-6" optimum="-18" value="-96" aria-label="${text('输入电平','Input level')}"></meter><output id="recorder-level">−96 dBFS</output></div>
  <p id="recorder-status" role="status"></p><p id="recorder-error" role="alert" data-inline-message></p>
  <audio id="recorder-preview" controls preload="none" hidden></audio>
  <div class="recorder-actions"><button id="recorder-test" type="button">${text('试音 10 秒','Test for 10 s')}</button><button id="recorder-start" type="button" class="primary">${text('开始录音','Record')}</button><button id="recorder-stop" type="button" hidden>${text('停止','Stop')}</button><button id="recorder-download" type="button" disabled>${text('下载','Download')}</button><button id="recorder-keep" type="button" class="primary" disabled>${text('保存并关联','Save and link')}</button><button id="recorder-timeline" type="button" hidden>${text('打开时间轴','Open timeline')}</button></div>
  <details id="recorder-pending"><summary>${text('未关联录音','Unlinked recordings')}</summary><div class="recorder-pending-row"><select id="recorder-takes" aria-label="${text('选择未关联录音','Choose an unlinked recording')}"></select><button id="recorder-resume" type="button">${text('打开','Open')}</button><button id="recorder-discard" type="button">${text('放弃关联','Discard link')}</button></div></details>
  <p class="recorder-help">${text('正式录音自动保存在项目的 media/recordings 中。试音仅供试听或下载，不自动保存；关闭后清除。','Recordings are saved automatically in the project’s media/recordings folder. Test audio is only available for playback or download; it is cleared when closed.')}</p>`);
 const dialog=$('recorder-dialog'),preview=$('recorder-preview');
 const bar=document.createElement('div');bar.id='recorder-bar';bar.hidden=true;
 const reopen=document.createElement('button'),barStop=document.createElement('button');reopen.type=barStop.type='button';barStop.textContent=text('停止录音','Stop recording');bar.append(reopen,barStop);document.querySelector('main').prepend(bar);
 const request=(path,body)=>originalApi('recorder-'+path,body?{_language:context.language_id,...body}:undefined);
 const safe=fn=>async()=>{if(busy)return;busy=true;failure='';paint();try{await fn();}catch(error){failure=error.message;if(!dialog.open)await corporiumAlert(error.message);}finally{busy=false;paint();}};
 function format(t){const config=t?.config||{rate:Number($('recorder-rate').value),bits:Number($('recorder-bits').value),channels:Number($('recorder-channels').value)};return `${config.rate/1000} kHz · ${config.bits} bit · ${config.channels===1?text('单声道','Mono'):text('双声道','Stereo')} · WAV`;}
 function clock(ms){const seconds=ms/1000;return String(Math.floor(seconds/60)).padStart(2,'0')+':'+(seconds%60).toFixed(1).padStart(4,'0');}
 function showText(id,value){const el=$(id);if(el.textContent!==value)el.textContent=value;}
 function paint(){
  const recording=live(take),ready=take?.state==='ready'&&take.bytes>0;
  for(const id of ['device','rate','bits','channels','speaker','target','name'])$('recorder-'+id).disabled=busy||recording||take?.state==='linked';
  $('recorder-start').hidden=recording;$('recorder-test').hidden=recording;$('recorder-stop').hidden=!recording;
  $('recorder-start').disabled=$('recorder-test').disabled=busy||!devices.length||take?.state==='linked';
  $('recorder-stop').disabled=busy||take?.state==='stopping';$('recorder-keep').disabled=busy||!ready||take.trial;
  $('recorder-download').disabled=busy||!take?.bytes||recording;
  $('recorder-timeline').hidden=!take?.session_id||take.state!=='linked'||context.kind!=='timeline';
  for(const id of ['resume','discard','takes'])$('recorder-'+id).disabled=busy||recording;
  const elapsed=clock(take?.duration_ms||0);$('recorder-time').value=elapsed;$('recorder-meter').value=take?.peak_db??-96;$('recorder-level').value=(take?.peak_db??-96)+' dBFS';
  bar.hidden=!recording;reopen.textContent='● '+text('正在录音','Recording')+' · '+elapsed;barStop.disabled=busy;
  $('recorder-start').textContent=ready&&!take.trial?text('另录一次','Record another take'):text('开始录音','Record');
  let status='';
  if(recording)status=(take.trial?text('正在试音','Testing input'):text('正在录音','Recording'))+' · '+format(take);
  else if(take?.state==='linked')status=text('录音已保存并关联。','Recording saved and linked.');
  else if(ready)status=(take.recovered?text('已恢复中断录音，可试听并关联。','Interrupted recording recovered. Listen and link it.'):take.trial?text('试音已结束，可试听或下载；不会自动保存。','Test finished. Listen or download; test audio is not saved automatically.'):text('已停止并保存原件。试听后可关联或另录一次。','Stopped; original saved. Listen, link it, or record another take.'))+' '+format(take);
  else if(!take)status=text('先试音，确认麦克风和音量。','Test the microphone and level before recording.');
  else if(take.state==='ready')status=text('未录到声音，请检查设备后重试。','No audio was captured. Check the device and try again.');
  showText('recorder-status',status);
  const warnings=[];
  if(take?.error)warnings.push(take.error);
  if(take?.clipped)warnings.push(text('检测到过载，请降低输入音量后重录。','Clipping detected. Lower the input level and record again.'));
  if(take?.buffer_warning)warnings.push(text('采集曾跟不上，可能缺失声音，建议重录。','Capture fell behind; audio may be missing. A retake is recommended.'));
  if(recording&&take.duration_ms>2000&&take.peak_db<-45)warnings.push(text('输入声音很小，请检查麦克风和距离。','Input is very quiet. Check the microphone and distance.'));
  showText('recorder-error',[failure,...warnings].filter(Boolean).join(' '));
 }
 function playTake(){preview.pause();preview.hidden=!take?.bytes||live(take);if(!preview.hidden){const q=new URLSearchParams({token:take.token});if(typeof desktopProjectStamp==='string')q.set('project',desktopProjectStamp);preview.src='/api/recorder-file?'+q;}}
 function clearTrial(){if(!take?.trial||live(take))return;const token=take.token;take=null;preview.pause();preview.removeAttribute('src');preview.hidden=true;void request('release',{token}).catch(()=>{});}
 function previewFinished(){if(take?.trial&&!dialog.open)clearTrial();else playTake();}
 async function poll(){clearTimeout(timer);if(!live(take))return;try{take=await request('status?token='+take.token);paint();if(!live(take)){previewFinished();await listPending();}}catch(error){failure=error.message;paint();}finally{if(live(take))timer=setTimeout(poll,250);}}
 function deviceChanged(){
  const supported=devices.find(d=>String(d.id)===$('recorder-device').value)?.formats||[];
  const desired={rate:Number($('recorder-rate').value),bits:Number($('recorder-bits').value),channels:Number($('recorder-channels').value)};
  const match=supported.find(c=>Object.keys(desired).every(k=>c[k]===desired[k]));
  if(!match){const best=supported.find(c=>c.rate===48000&&c.bits===24&&c.channels===1)||supported.find(c=>c.rate===48000&&c.channels===1)||supported[0];if(best){for(const key of ['rate','bits','channels'])$('recorder-'+key).value=String(best[key]);$('recorder-format-note').textContent=text('已选设备支持的规格：','Supported format selected: ')+format();}else $('recorder-format-note').textContent=text('此设备没有可用的录音规格。','No supported recording format for this device.');}
  else $('recorder-format-note').textContent=format();
 }
 async function listPending(){
  const data=await request('pending?language='+encodeURIComponent(context.language_id));pending=data.items;
  const matching=pending.filter(t=>t.context.kind===context.kind&&t.context.record_id===context.record_id);
  $('recorder-takes').replaceChildren(...matching.map(t=>new Option(new Date(t.created).toLocaleString()+' · '+clock(t.duration_ms)+(t.recovered?' · '+text('已恢复','Recovered'):''),t.token)));
  $('recorder-pending').hidden=!matching.length;
  return matching;
 }
 async function open(kind,id){
  $('recorder-error').textContent='';
  if(live(take)){if(!dialog.open)dialog.showModal();return;}
  if(inlineDrafts.size)throw Error(text('请先保存或取消正在编辑的例句。','Save or cancel the example being edited first.'));
  if(kind==='timeline')await window.corporiumPrepareRecording?.();
  const descriptor=await originalApi('recorder-context?'+new URLSearchParams({kind,id}));context=descriptor.context;take=null;
  $('recorder-destination').textContent=kind==='timeline'?text('保存为新时间轴，保留已有媒体。','Saves as a new timeline; existing media is retained.'):text('关联当前条目或例句。','Links to this entry or example.');
  $('recorder-name').value=text('现场录音 ','Recording ')+new Date().toLocaleString();preview.pause();preview.hidden=true;preview.removeAttribute('src');
  const [deviceData,people]=await Promise.all([request('devices'),originalApi('collaborators')]);
  devices=deviceData.devices; $('recorder-device').replaceChildren(...devices.map(d=>new Option(d.name,d.id)));
  $('recorder-speaker').replaceChildren(new Option(text('未指定','Unspecified'),''),...people.speakers.map(p=>new Option(p.name,p.id)));
  $('recorder-target-label').hidden=!['lexeme','morpheme'].includes(kind);$('recorder-target').replaceChildren(new Option(text('整个词条','Whole entry'),''),...descriptor.targets.map(t=>new Option(t.label,t.id)));
  deviceChanged();await listPending();if(!devices.length)$('recorder-error').textContent=text('没有可用麦克风。请检查设备连接和系统麦克风权限。','No microphone is available. Check the device connection and system microphone permissions.');
  if(!devices.length)failure=text('没有可用麦克风。请检查设备连接和系统麦克风权限。','No microphone is available. Check the device connection and system microphone permissions.');
  paint();if(!dialog.open)dialog.showModal();
 }
 async function start(trial){
  preview.pause();preview.hidden=true;$('recorder-error').textContent='';
  take=await request('start',{...context,name:$('recorder-name').value,speaker:$('recorder-speaker').value,target_id:$('recorder-target').value,device:Number($('recorder-device').value),rate:Number($('recorder-rate').value),bits:Number($('recorder-bits').value),channels:Number($('recorder-channels').value),trial});
  void poll();
 }
 const stop=safe(async()=>{take=await request('stop',{token:take.token});paint();if(live(take))void poll();else{clearTimeout(timer);previewFinished();await listPending();}});
 $('recorder-start').onclick=safe(()=>start(false));$('recorder-test').onclick=safe(()=>start(true));$('recorder-stop').onclick=barStop.onclick=stop;
 $('recorder-device').onchange=deviceChanged;for(const key of ['rate','bits','channels'])$('recorder-'+key).onchange=()=>{$('recorder-format-note').textContent=format();};
 $('recorder-keep').onclick=safe(async()=>{
  const result=await request('keep',{token:take.token,name:$('recorder-name').value,speaker:$('recorder-speaker').value,target_id:$('recorder-target').value,track_name:text('句子','Sentence')});
  take=await request('status?token='+take.token);window.corporiumInvalidateViews?.();
  await window.CorporiumObjectMedia?.recorded(context.kind,context.record_id);
  document.dispatchEvent(new Event('corporium-alignment-changed'));await window.corporiumRefreshUndoState?.();await listPending();
  if(context.kind==='timeline'&&result.id)take.session_id=result.id;
 });
 $('recorder-timeline').onclick=safe(async()=>{await window.corporiumOpenRecordedTimeline?.(take.session_id);dialog.close();});
 $('recorder-resume').onclick=safe(async()=>{const token=$('recorder-takes').value;if(!token)return;take=await request('status?token='+token);context={...take.context};$('recorder-speaker').value=context.speaker;$('recorder-target').value=context.target_id;playTake();if(live(take))void poll();});
 $('recorder-discard').onclick=safe(async()=>{const token=$('recorder-takes').value;if(!token)return;if(!await corporiumConfirm(text('放弃这次关联？录音文件仍保留在项目中。','Discard this link? The audio file will remain in the project.')))return;await request('discard',{token,confirmed:true});if(take?.token===token){take=null;preview.pause();preview.hidden=true;}await listPending();});
 $('recorder-download').onclick=safe(async()=>{
  if(document.documentElement.dataset.desktop==='true'&&window.pywebview?.api?.save_recording){const result=await window.pywebview.api.save_recording(take.token);if(result.error)throw Error(result.error);return;}
  const q=new URLSearchParams({token:take.token});if(typeof desktopProjectStamp==='string')q.set('project',desktopProjectStamp);
  const response=await fetch('/api/recorder-file?'+q);if(!response.ok)throw Error((await response.json()).error);
  const url=URL.createObjectURL(await response.blob()),a=document.createElement('a');a.href=url;a.download=take.filename;document.body.append(a);a.click();a.remove();setTimeout(()=>URL.revokeObjectURL(url),1000);
 });
 reopen.onclick=()=>{if(!dialog.open)dialog.showModal();};dialog.addEventListener('close',()=>{preview.pause();clearTrial();});
 preview.addEventListener('play',()=>document.dispatchEvent(new CustomEvent('corporium-playback-start',{detail:preview})));
 document.addEventListener('corporium-playback-start',e=>{if(e.detail!==preview)preview.pause();});
 window.addEventListener('beforeunload',e=>{if(live(take)){e.preventDefault();e.returnValue='';}});
 document.addEventListener('click',e=>{const button=e.target.closest('[data-record-kind]');if(!button)return;e.preventDefault();e.stopPropagation();void safe(()=>open(button.dataset.recordKind,button.dataset.recordId))();});
 document.dispatchEvent(new Event('corporium-recorder-ready'));
})();
