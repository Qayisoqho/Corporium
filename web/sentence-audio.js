/* Batch-discover current alignments for corpus references in every shared sentence view. */
function sentenceAudioMarkup(id,{compact=false}={}){return `<span class="sentence-audio" data-audio-entry="${esc(id)}"${compact?' data-audio-compact="true"':''} hidden></span>`;}
(()=>{
 const render=renderEditableExample;
 renderEditableExample=function(e,kind,id){let html=render(e,kind,id);if(['corpus','independent'].includes(kind))html=html.replace(/(<section\b[^>]*>)/,'$1'+sentenceAudioMarkup((kind==='independent'?'independent:':'')+id));return html;};
 const audio=document.createElement('audio');audio.id='sentence-audio-player';audio.preload='metadata';audio.hidden=true;document.body.append(audio);
 let activeButton=null,activeClip=null,sequence=0,scanTimer=null,running=false,again=false;
 const player=new RangePlayback(audio,resetButton);
 function resetButton(){if(activeButton?.isConnected){activeButton.textContent='▶';activeButton.title='播放句子音频';activeButton.setAttribute('aria-label','播放句子音频');}activeButton=null;}
 function stop(){sequence++;player.stop();resetButton();}
 window.stopSentenceAudio=stop;
 document.addEventListener('corporium-playback-start',e=>{if(e.detail!==audio)stop();});
 audio.onerror=()=>{const holder=activeButton?.closest('.sentence-audio'),message='播放失败，请到时间轴检查媒体或生成兼容副本';if(holder?.dataset.audioCompact==='true'||document.documentElement.classList.contains('brief-mode')){stop();void corporiumAlert(message);return;}player.stop();if(holder)holder.querySelector('.sentence-audio-status').textContent=message;resetButton();};
 function renderControls(holder,clips){if(holder.dataset.audioInterval)clips=clips.filter(c=>c.id===holder.dataset.audioInterval);holder._clips=clips;holder.dataset.audioReady='1';holder.hidden=!clips.length;if(!clips.length)return;
  const compact=holder.dataset.audioCompact==='true';
  holder.innerHTML='<button type="button" class="sentence-audio-play" title="播放句子音频" aria-label="播放句子音频">▶</button>'+(!compact&&clips.length>1?'<select class="sentence-audio-choice" aria-label="选择句子音频区间" title="此句有多个时间区间"></select>':'')+'<span class="sentence-audio-status" role="status"'+(compact?' hidden':'')+'></span>';
  const select=holder.querySelector('select');if(select)select.replaceChildren(...clips.map((c,i)=>new Option(c.session_name+' · '+(c.start_ms/1000).toFixed(2)+'–'+(c.end_ms/1000).toFixed(2)+' 秒',i)));
  holder.title='播放当前时间轴对齐的录音'+(clips.some(c=>c.clipped)?'；超出媒体的部分不播放':'');
 }
 async function scan(){if(running){again=true;return;}const nodes=[...document.querySelectorAll('.sentence-audio:not([data-audio-ready])')];if(!nodes.length)return;running=true;const ids=[...new Set(nodes.map(n=>n.dataset.audioEntry))];try{for(let at=0;at<ids.length;at+=200){const data=await originalApi('timeline-clips?ids='+encodeURIComponent(ids.slice(at,at+200).join(',')));for(const n of nodes)if(n.isConnected&&Object.hasOwn(data,n.dataset.audioEntry))renderControls(n,data[n.dataset.audioEntry]);}}catch(error){for(const n of nodes)n.dataset.audioReady='error';}finally{running=false;if(again){again=false;schedule();}}}
 function schedule(){clearTimeout(scanTimer);scanTimer=setTimeout(scan,60);}
 new MutationObserver(records=>{if(records.some(r=>[...r.addedNodes].some(n=>n.nodeType===1&&(n.matches?.('.sentence-audio:not([data-audio-ready])')||n.querySelector?.('.sentence-audio:not([data-audio-ready])')))))schedule();}).observe(document.body,{childList:true,subtree:true});
 document.addEventListener('corporium-alignment-changed',()=>{stop();for(const n of document.querySelectorAll('.sentence-audio')){n.removeAttribute('data-audio-ready');n.hidden=true;}schedule();});
 document.addEventListener('click',async e=>{const button=e.target.closest('.sentence-audio-play');if(!button)return;e.preventDefault();e.stopPropagation();const holder=button.closest('.sentence-audio');if(activeButton===button&&!audio.paused){stop();return;}stop();const ticket=sequence;activeButton=button;button.textContent='…';const status=holder.querySelector('.sentence-audio-status');status.textContent='';try{
  // Fetch again on activation so source replacement/undo never plays a stale asset.
  const data=await originalApi('timeline-clips?ids='+encodeURIComponent(holder.dataset.audioEntry));if(ticket!==sequence)return;const selected=holder._clips[Number(holder.querySelector('select')?.value||0)];const clip=data[holder.dataset.audioEntry]?.find(c=>c.id===selected?.id);if(!clip)throw Error('这个对齐区间已改变，请刷新例句');activeClip=clip;
  const q=new URLSearchParams({asset:clip.asset,proxy:String(clip.proxy)});if(typeof desktopProjectStamp==='string')q.set('project',desktopProjectStamp);audio.src='/api/timeline-file?'+q;
  audio.volume=Math.max(0,Math.min(1,Number(localStorage.getItem('corporium-media-volume')??.3)));await player.start(clip.play_start_ms/1000,clip.play_end_ms/1000);if(ticket!==sequence)return;button.textContent='■';button.title='停止句子音频';button.setAttribute('aria-label','停止句子音频');
 }catch(error){if(ticket===sequence){player.stop();resetButton();void corporiumAlert(error.message);}}});
 document.addEventListener('change',e=>{if(e.target.matches('.sentence-audio-choice'))stop();});
 schedule();
})();
