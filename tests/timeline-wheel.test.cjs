const test=require('node:test'),assert=require('node:assert/strict'),vm=require('node:vm'),fs=require('node:fs');
const source=fs.readFileSync(require.resolve('../web/timeline.js'),'utf8');
const listener=source.slice(source.indexOf("panel.addEventListener('wheel'"),source.indexOf('let resizing=null;'));
function harness(){
 const inputs={},state={from:-10000,span:60000,request:0,data:{},wheelTimer:null,TimelineGeometry:require('../web/timeline-geometry.js'),sec:n=>String(n/1000),$ :id=>inputs[id]||=( {} ),noDraft(){},renderTracks(){},drawWave(){},syncSpan(){},safeTL:fn=>fn,load(){},clearTimeout(){},setTimeout(fn){state.pending=fn;return 1;},panel:{addEventListener(type,fn,options){state.handler=fn;assert.equal(options.passive,false);}}};
 state.frames=[];state.panFrame=0;state.requestAnimationFrame=fn=>state.frames.push(fn);state.remember=()=>{state.remembered=state.from;};state.loadWave=()=>{state.waveAt=state.from;};state.renderTracks=()=>{state.rendered=state.from;};
 vm.runInNewContext(source.match(/function schedulePan[^\n]+/)[0]+'\n'+listener,state);return state;
}
function wheel(s,values={}){const e={ctrlKey:false,shiftKey:true,deltaX:0,deltaY:100,deltaMode:0,clientX:300,target:{closest:()=>({getBoundingClientRect:()=>({left:100,width:1000})})},preventDefault(){this.prevented=true;},...values};s.handler(e);return e;}
test('Ctrl wheel over an axis zooms at cursor without changing heights or editing data',()=>{
 const s=harness(),data=s.data;let prevented=false;
 s.handler({ctrlKey:true,deltaY:-100,deltaMode:0,clientX:300,target:{closest:()=>({getBoundingClientRect:()=>({left:100,width:1000})})},preventDefault(){prevented=true;}});
 assert.ok(prevented);assert.ok(s.span<60000);assert.ok(Math.abs(s.from+.2*s.span-2000)<1);assert.equal(s.data,data);assert.equal(s.request,1);assert.equal(typeof s.pending,'function');
});
test('ordinary wheel keeps its scroll behavior and a dirty sentence editor still permits viewport zoom',()=>{
 const s=harness();s.handler({ctrlKey:false});assert.equal(s.span,60000);
 s.noDraft=()=>{throw Error('save first');};s.handler({ctrlKey:true,deltaY:-100,deltaMode:0,clientX:300,target:{closest:()=>({getBoundingClientRect:()=>({left:100,width:1000})})},preventDefault(){}});assert.ok(s.span<60000);
});
test('Shift wheel pans waveform and lanes at the current scale, coalescing paint and wave requests with a dirty editor',()=>{
 for(const selector of ['.tl-wave','.tl-lane']){
  const s=harness();Object.assign(s,{from:30000,span:10000,head:32000,selectedInterval:'one',data:{extent:[0,120000],intervals:[{id:'one',start_ms:31000,end_ms:33000}]},noDraft(){throw Error('save first');}});const data=JSON.stringify(s.data);
  const target={closest:query=>{assert.ok(query.includes(selector));return {getBoundingClientRect:()=>({width:1000})};}};
  assert.ok(wheel(s,{target}).prevented);wheel(s,{target});wheel(s,{target});
  assert.equal(s.from,33000);assert.equal(s.span,10000);assert.equal(s.head,32000);assert.equal(s.selectedInterval,'one');assert.equal(JSON.stringify(s.data),data);assert.equal(s.frames.length,1);assert.equal(s.waveAt,undefined);
  s.frames.shift()();assert.equal(s.rendered,33000);assert.equal(s.waveAt,33000);assert.equal(s.remembered,33000);assert.equal(s.pending,undefined);
 }
});
test('Shift wheel accepts browser horizontal deltas, line/page units and one-millisecond views',()=>{
 for(const [values,expected] of [[{},31000],[{deltaX:100,deltaY:0},31000],[{deltaX:100,deltaY:100},31000],[{deltaY:2,deltaMode:1},30320],[{deltaY:-1,deltaMode:2},20000],[{deltaY:0},30000]]){
  const s=harness();Object.assign(s,{from:30000,span:10000,data:{extent:[0,120000]}});wheel(s,values);assert.equal(s.from,expected);assert.equal(s.span,10000);
 }
 const s=harness();Object.assign(s,{from:30000,span:1,data:{extent:[0,120000]}});wheel(s);assert.equal(s.from,30001);assert.equal(s.span,1);
});
test('Shift wheel clamps to the timeline bounds, stays out of other controls and leaves Ctrl zoom in charge',()=>{
 const s=harness();Object.assign(s,{from:0,span:10000,data:{extent:[0,120000]}});
 assert.ok(wheel(s,{deltaY:-100}).prevented);assert.equal(s.from,0);assert.equal(s.request,0);assert.equal(s.frames.length,0);
 s.from=110000;wheel(s);assert.equal(s.from,110000);assert.equal(s.frames.length,0);
 assert.ok(!wheel(s,{target:{closest:()=>null}}).prevented);assert.equal(s.from,110000);
 s.from=30000;wheel(s,{ctrlKey:true,deltaY:-100});assert.ok(s.span<10000);assert.equal(s.frames.length,0);assert.equal(typeof s.pending,'function');
});
test('ordinary wheel is contained only when axes overflow, including at the bottom',()=>{
 const start=source.indexOf("panel.querySelector('.tl-scroll-axes').addEventListener('wheel'");
 let handler;vm.runInNewContext(source.slice(start,source.indexOf('let wheelTimer;',start)),{panel:{querySelector:()=>({addEventListener:(type,fn)=>handler=fn})}});
 for(const overflow of [false,true]){let prevented=false;const axes={scrollHeight:overflow?300:100,clientHeight:100,scrollTop:200};handler({ctrlKey:false,currentTarget:axes,deltaY:50,deltaMode:0,preventDefault(){prevented=true;}});assert.equal(prevented,overflow);assert.equal(axes.scrollTop,overflow?250:200);}
 for(const ctrlKey of [false,true]){let prevented=false;const axes={scrollHeight:300,clientHeight:100,scrollTop:50};handler({ctrlKey,shiftKey:true,target:{closest:()=>({})},currentTarget:axes,deltaY:50,deltaMode:0,preventDefault(){prevented=true;}});assert.equal(prevented,false);assert.equal(axes.scrollTop,50);}
});
