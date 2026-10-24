/* Native sample rendering and byte-bounded waveform data, independent of playback. */
(function(root){
'use strict';
function bytes(wave){
 if(!wave)return 0;
 return 256+(wave.channels||[]).reduce((sum,c)=>sum+(c.byteLength||c.length*(Array.isArray(c[0])?16:8)),0);
}
function decode(wave){
 if(!wave?.values)return wave;
 const raw=Uint8Array.from(atob(wave.values),c=>c.charCodeAt(0));
 const data=wave.encoding==='f32'?new Float32Array(raw.buffer):new Int16Array(raw.buffer);
 const stride=wave.count*(wave.mode==='samples'?1:2),channels=[];
 if(data.length!==stride*wave.channel_count)throw Error('波形片段数据不完整，请重试');
 for(let n=0;n<wave.channel_count;n++)channels.push(data.subarray(n*stride,(n+1)*stride));
 const result={...wave,channels};delete result.values;return result;
}
class Cache extends Map{
 constructor(limit=32*1024**2){super();this.limit=limit;this.bytes=0;this.overview=null;}
 get(key){const value=super.get(key);if(value){super.delete(key);super.set(key,value);}return value;}
 set(key,value){this.delete(key);super.set(key,value);this.bytes+=bytes(value);this.trim();return this;}
 delete(key){const value=super.get(key);if(value)this.bytes-=bytes(value);return super.delete(key);}
 clear(){super.clear();this.overview=null;this.bytes=0;}
 setOverview(value){this.bytes-=bytes(this.overview);this.overview=value;this.bytes+=bytes(value);this.trim();}
 setBudget(value){if(Number.isFinite(value)&&value>0)this.limit=value;this.trim();}
 trim(){while(this.size&&this.bytes>this.limit)this.delete(this.keys().next().value);}
}
function draw(ctx,source,from,span,gain,width,height){
 if(!source?.ready||!source.channels?.length||!source.step_ms)return;
 const samples=source.mode==='samples',channels=source.channels;
 channels.forEach((channel,n)=>{
  const typed=ArrayBuffer.isView(channel),count=samples?channel.length:(typed?channel.length/2:channel.length);
  const h=height/channels.length,mid=(n+.5)*h,scale=h*.45*gain;
  const first=Math.max(0,Math.floor((from-source.start_ms)/source.step_ms)-(samples?1:0));
  const last=Math.min(count,Math.ceil((from+span-source.start_ms)/source.step_ms)+(samples?1:0));
  ctx.save();ctx.beginPath();ctx.rect(0,n*h,width,h);ctx.clip();
  if(samples){
   ctx.beginPath();ctx.lineWidth=1;
   for(let i=first;i<last;i++){
    const x=(source.start_ms+i*source.step_ms-from)/span*width,y=mid-channel[i]*scale;
    if(i===first)ctx.moveTo(x,y);else ctx.lineTo(x,y);
   }
   ctx.stroke();
   if(source.step_ms/span*width>=7){
    for(let i=first;i<last;i++){
     const x=(source.start_ms+i*source.step_ms-from)/span*width,y=mid-channel[i]*scale;
     if(x>=0&&x<=width&&y>=n*h&&y<=(n+1)*h)ctx.fillRect(x-1,y-1,2,2);
    }
   }
  }else{
   for(let i=first;i<last;i++){
    const lo=typed?channel[2*i]/32767:channel[i][0],hi=typed?channel[2*i+1]/32767:channel[i][1];
    const left=Math.max(0,(source.start_ms+i*source.step_ms-from)/span*width),right=Math.min(width,(source.start_ms+(i+1)*source.step_ms-from)/span*width);
    const top=Math.max(n*h,mid-hi*scale),bottom=Math.min((n+1)*h,mid-lo*scale);
    if(right>left)ctx.fillRect(left,top,Math.min(width-left,Math.max(1,right-left)),Math.max(1,bottom-top));
   }
  }
  ctx.restore();
 });
}
const api={Cache,decode,draw,bytes};
if(typeof module!=='undefined'&&module.exports)module.exports=api;
else root.CorporiumWaveform=api;
})(typeof window==='undefined'?globalThis:window);
