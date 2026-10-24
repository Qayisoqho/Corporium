const test=require('node:test'),assert=require('node:assert/strict'),vm=require('node:vm'),fs=require('node:fs');
const geometry=require('../web/timeline-geometry.js');
test('outer border pixels resize, interior moves, and narrow blocks choose nearest edge',()=>{
 for(const x of [100,100.1,101,109,110])assert.equal(geometry.edgeMode(x,100,200),'left');
 for(const x of [190,199,199.9,200])assert.equal(geometry.edgeMode(x,100,200),'right');
 assert.equal(geometry.edgeMode(150,100,200),'move');
 assert.equal(geometry.edgeMode(101,100,106),'left');assert.equal(geometry.edgeMode(105,100,106),'right');
});
test('display gain scales mono and stereo about each channel center, with separate clipping',()=>{
 const source=fs.readFileSync(require.resolve('../web/timeline.js'),'utf8');
 for(const count of [1,2]){
  const rects=[],fills=[],ctx={clearRect(){},save(){},restore(){},beginPath(){},rect(...r){rects.push(r);},clip(){},fillRect(...r){fills.push(r);}};
  const canvas={width:100,height:100,getContext:()=>ctx},wave={ready:true,start_ms:0,step_ms:100,channels:Array.from({length:count},()=>[[-.1,.1]])};
  const s={CorporiumWaveform:require('../web/waveform.js'),waveGain:4,from:0,span:100,head:0,assetId:'m',waveCache:new Map(),waveOverview:null,wave,panel:{},$:id=>id==='tl-wave'?canvas:null,getComputedStyle:()=>({getPropertyValue:()=> '#123'})};
  vm.createContext(s);vm.runInContext(source.slice(source.indexOf('function drawWave(){'),source.indexOf('async function pending()')),s);vm.runInContext('drawWave()',s);
  assert.equal(rects.length,count);
  for(let n=0;n<count;n++){const h=100/count,mid=(n+.5)*h;assert.deepEqual(rects[n],[0,n*h,100,h]);assert.ok(Math.abs(fills[n][1]-(mid-.1*h*.45*4))<1e-8);assert.ok(Math.abs(fills[n][3]-(.2*h*.45*4))<1e-8);}
 }
});

test('moving the playhead does not repaint the waveform',()=>{
 const source=fs.readFileSync(require.resolve('../web/timeline.js'),'utf8');let paints=0;
 const s={followPlayback(){},$:()=>({}),time:()=>'',head:10,from:0,span:100,media:{paused:false},transportIcon(){},panel:{querySelectorAll:()=>[{style:{}}]},drawWave(){paints++;}};
 vm.createContext(s);vm.runInContext(source.slice(source.indexOf('function updateHead(){'),source.indexOf('function updateHead(){')+source.slice(source.indexOf('function updateHead(){')).indexOf('\n')),s);
 for(let i=0;i<120;i++)s.updateHead();assert.equal(paints,0);
});
test('gain input redraw requests coalesce into one frame',()=>{
 const source=fs.readFileSync(require.resolve('../web/timeline.js'),'utf8');let paints=0,frames=[];
 const s={requestAnimationFrame:f=>(frames.push(f),frames.length),drawWave(){paints++;}};vm.createContext(s);
 vm.runInContext(source.slice(source.indexOf('let waveDrawFrame=0;'),source.indexOf('function drawWave(){')),s);
 for(let i=0;i<100;i++)s.scheduleWaveDraw();assert.equal(frames.length,1);frames[0]();assert.equal(paints,1);
});

test('4x dense stereo fills stay inside their own channel and the viewport',()=>{
 const source=fs.readFileSync(require.resolve('../web/timeline.js'),'utf8'),fills=[];
 const ctx={clearRect(){},save(){},restore(){},beginPath(){},rect(){},clip(){},fillRect(...r){fills.push(r);}};
 const canvas={width:100,height:100,getContext:()=>ctx};
 const wave={ready:true,start_ms:0,step_ms:10,channels:[Array.from({length:1000},()=>[-1,1]),Array.from({length:1000},()=>[-1,1])]};
 const s={CorporiumWaveform:require('../web/waveform.js'),waveGain:4,from:100,span:100,head:100,assetId:'m',waveCache:new Map(),waveOverview:null,wave,panel:{},$:id=>id==='tl-wave'?canvas:null,getComputedStyle:()=>({getPropertyValue:()=> '#123'})};
 vm.createContext(s);vm.runInContext(source.slice(source.indexOf('function drawWave(){'),source.indexOf('async function pending()')),s);s.drawWave();
 assert.equal(fills.length,20);for(let i=0;i<20;i++){assert.equal(fills[i][1],i<10?0:50);assert.equal(fills[i][3],50);assert.ok(fills[i][0]>=0&&fills[i][0]+fills[i][2]<=100);}
});
