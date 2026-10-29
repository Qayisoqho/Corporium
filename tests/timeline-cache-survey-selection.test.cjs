const test=require('node:test'),assert=require('node:assert/strict'),vm=require('node:vm'),fs=require('node:fs');
const CorporiumWaveform=require('../web/waveform.js');
const source=fs.readFileSync(require.resolve('../web/timeline.js'),'utf8');
function harness(){const requests=[],state={sid:'one',assetId:'media-one',activeLanguage:'ordos',data:{media:{metadata:{duration_ms:60000}}},from:0,span:1000,wave:null,waveOverview:null,waveCache:new CorporiumWaveform.Cache(),CorporiumWaveform,applyWaveBudget(){},waveLoading:false,waveAgain:false,URLSearchParams,drawWave(){state.draws++;},draws:0,$(){return {};},call(url){return new Promise(resolve=>requests.push({url,resolve}));}};vm.createContext(state);vm.runInContext(source.slice(source.indexOf('async function loadWave(){'),source.indexOf('function drawWave(){')),state);return {state,requests,load:()=>vm.runInContext('loadWave()',state)};}
const wave={ready:true,start_ms:0,step_ms:10,channels:[[[0,1]]]};
test('continuous panning coalesces requests and keeps the full-media envelope',async()=>{const {state:s,requests:r,load}=harness();const initial=load();assert.match(r[0].url,/end=60000/);r.shift().resolve(wave);await Promise.resolve();await Promise.resolve();s.from=20000;await load();s.from=30000;await load();assert.equal(r.length,1);r.shift().resolve(wave);await initial;assert.equal(s.waveOverview,wave);assert.equal(s.wave,null);assert.match(r[0].url,/start=30000/);r.shift().resolve({...wave,start_ms:30000});await Promise.resolve();await Promise.resolve();assert.equal(s.wave.start_ms,30000);assert.equal(s.waveCache.size,2);});
test('old media replies never contaminate a switched timeline',async()=>{const {state:s,requests:r,load}=harness();const initial=load();s.sid='two';s.assetId='media-two';await load();r.shift().resolve(wave);await initial;assert.equal(s.waveOverview,null);assert.equal(s.waveCache.size,0);assert.match(r[0].url,/id=two/);});
const survey=fs.readFileSync(require.resolve('../web/grammar-survey.js'),'utf8');
test('Shift range includes both endpoints, reverse ranges and a missing anchor',()=>{const s={};vm.createContext(s);vm.runInContext(survey.match(/function selectionRange[^\n]+/)[0],s);const run=(a,b)=>Array.from(s.selectionRange(['a','b','c','d'],a,b));assert.deepEqual(run('a','c'),['a','b','c']);assert.deepEqual(run('d','b'),['b','c','d']);assert.deepEqual(run('hidden','b'),['b']);});
test('pan input paints the latest position on the next frame without waiting for release or network',async()=>{
 const element={value:'10000'},frames=[],s={from:0,request:0,panFrame:0,viewportBusy:false,waveOnFrame:false,wheelTimer:null,clearTimeout(){},setTimeout(){return 1;},syncSpan(){},$:()=>element,safeTL:f=>f,requestAnimationFrame:f=>{frames.push(f);return frames.length;},renderViewport(){s.rendered=s.from;},drawWave(){s.painted=s.from;},remember(){},loadWave(){s.loaded=s.from;}};
 vm.createContext(s);vm.runInContext(source.match(/function schedulePan[^\n]+/)[0]+'\n'+source.match(/\$\('tl-pan'\)\.oninput=[^\n]+/)[0],s);
 element.oninput();element.value='80000';element.oninput();assert.equal(frames.length,1);frames[0]();assert.equal(s.rendered,80000);assert.equal(s.painted,80000);assert.equal(s.loaded,80000);
});

test('wave viewport cache remains bounded after many distinct views',async()=>{
 const {state:s,requests:r,load}=harness();s.waveOverview=wave;s.waveCache.setOverview(wave);s.waveCache.setBudget(2048);
 for(let i=0;i<40;i++){s.from=i*1000;const pending=load();r.shift().resolve({...wave,start_ms:s.from});await pending;}
 assert.ok(s.waveCache.size<10);assert.ok(s.waveCache.bytes<=2048);assert.equal(s.waveOverview,wave);
});
