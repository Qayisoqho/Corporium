/* A single bounded playback controller per media element. End checks also run in background tabs. */
class RangePlayback{
 constructor(media,onEnd=()=>{}){this.media=media;this.onEnd=onEnd;this.range=null;this.generation=0;this.timer=null;this.repeat=false;media.addEventListener('timeupdate',()=>this.check());media.addEventListener('ended',()=>this.check(true));media.addEventListener('play',()=>this.arm());media.addEventListener('pause',()=>clearTimeout(this.timer));}
 arm(){clearTimeout(this.timer);if(!this.media.paused&&this.range)this.timer=setTimeout(()=>{this.check();this.arm();},20);}
 check(ended=false){if(!this.range)return;const [a,z]=this.range;if(ended||this.media.currentTime>=z){if(this.repeat&&!ended){this.media.currentTime=a;return;}this.media.pause();this.media.currentTime=z;this.range=null;clearTimeout(this.timer);this.onEnd();}}
 stop(){this.generation++;this.range=null;clearTimeout(this.timer);this.media.pause();}
 async start(start,end,{repeat=false}={}){
  this.stop();const ticket=this.generation,m=this.media;
  if(!Number.isFinite(start)||!Number.isFinite(end)||end<=start)throw Error('播放范围无效');
  if(m.readyState<1)await new Promise((resolve,reject)=>{const cleanup=()=>{clearTimeout(timeout);m.removeEventListener('loadedmetadata',ok);m.removeEventListener('error',bad);};const ok=()=>{cleanup();resolve();},bad=()=>{cleanup();reject(Error('媒体无法播放，请在时间轴中检查媒体或生成兼容副本。'));};const timeout=setTimeout(bad,15000);m.addEventListener('loadedmetadata',ok);m.addEventListener('error',bad);if(m.error)bad();});
  if(ticket!==this.generation)return;
  const a=Math.max(0,start),z=Math.min(Number.isFinite(m.duration)?m.duration:end,end);if(z<=a)throw Error('该区间在媒体范围之外');
  this.range=[a,z];this.repeat=repeat;m.currentTime=a;
  document.dispatchEvent(new CustomEvent('corporium-playback-start',{detail:m}));
  try{await m.play();if(ticket!==this.generation)return;this.arm();}catch(error){if(ticket===this.generation)this.stop();throw error;}
 }
}
if(typeof module!=='undefined')module.exports=RangePlayback;
