const test=require('node:test'),assert=require('node:assert/strict');
const waveform=require('../web/waveform.js');
function context(){const fills=[],lines=[],clips=[];return {fills,lines,clips,clearRect(){},save(){},restore(){},beginPath(){},rect(...r){clips.push(r);},clip(){},fillRect(...r){fills.push(r);},moveTo(...p){lines.push(['move',...p]);},lineTo(...p){lines.push(['line',...p]);},stroke(){}};}
function fixture(count=200){return {ready:true,mode:'peaks',start_ms:0,step_ms:1,count,channels:[new Int16Array(count*2).fill(16000)]};}
test('compact native samples decode without time or amplitude rounding',()=>{
 const native=new Float32Array([0,.12345678,-.33333334,.875]);
 const result=waveform.decode({ready:true,mode:'samples',channel_count:2,count:2,step_ms:1000/48000,encoding:'f32',values:Buffer.from(native.buffer).toString('base64')});
 assert.deepEqual(Array.from(result.channels[0]),Array.from(native.slice(0,2)));assert.deepEqual(Array.from(result.channels[1]),Array.from(native.slice(2)));assert.equal(result.values,undefined);
});
test('compact peak amplitudes retain both signs and separate channels',()=>{
 const native=new Int16Array([-20000,30000,-10000,15000]);
 const result=waveform.decode({mode:'peaks',channel_count:2,count:1,encoding:'i16',values:Buffer.from(native.buffer).toString('base64')});
 assert.deepEqual(Array.from(result.channels[0]),[-20000,30000]);assert.deepEqual(Array.from(result.channels[1]),[-10000,15000]);
});
test('corrupt compact data is rejected before drawing',()=>{
 assert.throws(()=>waveform.decode({mode:'peaks',channel_count:2,count:3,encoding:'i16',values:'AAAAAA=='}),/不完整/);
});

test('a covering detail skips the hidden overview; partial details keep surrounding context',()=>{
 const overview={ready:true,start_ms:0,step_ms:100,count:1000,channels:[new Int16Array(2000)]};
 const detail={ready:true,start_ms:1000,step_ms:1,mode:'samples',channels:[new Float32Array(1000)]};
 assert.deepEqual(waveform.renderSources(overview,detail,1000,1000),[detail]);
 assert.deepEqual(waveform.renderSources(overview,detail,500,2000),[overview,detail]);
 assert.deepEqual(waveform.renderSources(overview,null,0,1000),[overview]);
 assert.deepEqual(waveform.renderSources(overview,overview,0,1000),[overview]);
 const peaks={ready:true,start_ms:1000,step_ms:10,channels:[new Int16Array(200)]};
 assert.deepEqual(waveform.renderSources(overview,peaks,1000,1000),[peaks]);
 assert.deepEqual(waveform.renderSources(overview,peaks,1000,1500),[overview,peaks]);
});
test('sample view draws the native alternating waveform as a connected line',()=>{
 const c=context(),wave={ready:true,mode:'samples',step_ms:1,start_ms:100,channels:[new Float32Array([0,1,-1,0])]};
 waveform.draw(c,wave,100,4,1,400,100);
 assert.deepEqual(c.lines,[['move',0,50],['line',100,5],['line',200,95],['line',300,50]]);
 assert.equal(c.fills.length,4);assert.deepEqual(c.clips,[[0,0,400,100]]);
});
test('rendering work is limited to the visible sample range of a long waveform',()=>{
 const c=context(),wave=fixture(1000000);waveform.draw(c,wave,501000,10,4,100,100);
 assert.equal(c.fills.length,10);assert.ok(c.fills.every(r=>r[0]>=0&&r[0]+r[2]<=100));
});
test('byte budget includes the overview and drops least recently used views',()=>{
 const wave=fixture(),cost=waveform.bytes(wave),cache=new waveform.Cache(cost*3);
 cache.setOverview(wave);cache.set('a',wave);cache.set('b',wave);cache.get('a');cache.set('c',wave);
 assert.equal(cache.has('b'),false);assert.equal(cache.has('a'),true);assert.equal(cache.bytes,cost*3);
 cache.setBudget(cost*2);assert.equal(cache.size,1);assert.ok(cache.bytes<=cache.limit);
 cache.clear();assert.equal(cache.bytes,0);assert.equal(cache.overview,null);
});
test('replacing a cached view does not double count its bytes',()=>{
 const cache=new waveform.Cache(10000),wave=fixture();cache.set('one',wave);cache.set('one',wave);assert.equal(cache.bytes,waveform.bytes(wave));
});
test('high gain clips sample lines independently within stereo channels',()=>{
 const c=context(),wave={ready:true,mode:'samples',start_ms:0,step_ms:1,channels:[new Float32Array([-1,1]),new Float32Array([1,-1])]};
 waveform.draw(c,wave,0,2,4,200,100);assert.deepEqual(c.clips,[[0,0,200,50],[0,50,200,50]]);assert.equal(c.lines.length,4);
});

test('settings save works after the shared dialog docks its submit button outside the form',async()=>{
 const fs=require('node:fs'),vm=require('node:vm'),source=fs.readFileSync(require.resolve('../web/timeline.js'),'utf8');
 const start=source.indexOf("$('tl-wave-settings-form').onsubmit="),end=source.indexOf('\n};',start)+3;
 const button={disabled:false},form={},dialog={querySelector:()=>button,close(){this.closed=true;}},nodes={'tl-wave-settings-form':form,'tl-wave-settings-dialog':dialog,'tl-wave-memory':{value:'64'},'tl-wave-disk':{value:'512'},'tl-wave-settings-error':{textContent:''}};
 const s={$:id=>nodes[id],waveCache:new waveform.Cache(),wave:null,assetId:null,Promise,call:async(path,body)=>{assert.deepEqual({...body},{memory_mb:64,disk_mb:512});return {browser_bytes:16*1024**2};},showWaveSettings(){},applyWaveBudget(value){s.waveCache.setBudget(value.browser_bytes);}};
 vm.runInNewContext(source.slice(start,end),s);await form.onsubmit({preventDefault(){},currentTarget:{querySelector:()=>null}});
 assert.equal(dialog.closed,true);assert.equal(button.disabled,false);assert.equal(s.waveCache.limit,16*1024**2);
 s.call=async()=>{throw Error('cannot save');};dialog.closed=false;await form.onsubmit({preventDefault(){}});
 assert.equal(nodes['tl-wave-settings-error'].textContent,'cannot save');assert.equal(dialog.closed,false);assert.equal(nodes['tl-wave-memory'].value,'64');assert.equal(button.disabled,false);
});

test('late waveform replies cannot undo a newer cache budget',()=>{
 const fs=require('node:fs'),vm=require('node:vm'),source=fs.readFileSync(require.resolve('../web/timeline.js'),'utf8');
 const start=source.indexOf('function applyWaveBudget('),end=source.indexOf('async function ensureWaveSettings',start);
 const state={waveBudgetRevision:-1,wave:null,waveCache:new waveform.Cache()};vm.createContext(state);vm.runInContext(source.slice(start,end),state);
 state.applyWaveBudget({browser_bytes:32*1024**2,settings_revision:10});state.applyWaveBudget({browser_bytes:4*1024**2,settings_revision:12});state.applyWaveBudget({browser_bytes:32*1024**2,settings_revision:11});
 assert.equal(state.waveCache.limit,4*1024**2);state.applyWaveBudget({browser_bytes:16*1024**2,settings_revision:13});assert.equal(state.waveCache.limit,16*1024**2);
});
