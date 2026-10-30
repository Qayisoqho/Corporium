const test=require('node:test'),assert=require('node:assert/strict'),vm=require('node:vm'),fs=require('node:fs');
function setup(){
 const source=fs.readFileSync('web/home.js','utf8'),listeners={},timers=new Map(),holder={};let now=0,identity=0;
 const nodes=new Map(),node=id=>{if(!nodes.has(id))nodes.set(id,{textContent:'',classList:{toggle(){}},style:{},contains:n=>id==='home-example-audio'&&n===holder});return nodes.get(id);};
 const c={window:{stopSentenceAudio(){}},document:{hidden:false,addEventListener:(type,fn)=>listeners[type]=fn},performance:{now:()=>now},$:node,
  setTimeout(fn,delay){const id=++identity;timers.set(id,{at:now+delay,fn});return id;},clearTimeout:id=>timers.delete(id),
  sentenceAudioMarkup:()=>'',applyLanguageTypography(){},languageList:[],validFont:()=>true,scheduleHomeFit(){},matchMedia:()=>({matches:true}),showHome(){throw Error('Unexpected sample fetch');}};
 vm.createContext(c);vm.runInContext(source.split('\n')[0]+'\n'+source.slice(source.indexOf('function stopHomeTimer()'),source.indexOf('async function showHome()')),c);
 const run=s=>vm.runInContext(s,c);
 run("homeVisible=true;homeData={samples:[0,1,2].map(id=>({id,kind:'corpus',ipa:'ipa',translation:'translation',language_name:'Language'}))};drawHomeExample();scheduleHome();");
 return {c,holder,run,timers,state:()=>run('({index:homeIndex,remaining:homeRemaining,playing:homeAudioPlaying})'),
  audio(active,target=holder){listeners['corporium-sentence-audio-state']({detail:{holder:target,active}});},
  advance(ms){const end=now+ms;for(;;){const next=[...timers].sort((a,b)=>a[1].at-b[1].at)[0];if(!next||next[1].at>end)break;now=next[1].at;timers.delete(next[0]);next[1].fn();}now=end;}};
}
test('audio loading and playback pause accumulated reading time, then finish the remaining ten seconds',()=>{
 const s=setup();s.advance(3000);s.audio(true);s.advance(25000);assert.equal(s.state().index,0);assert.equal(s.state().remaining,7000);assert.equal(s.timers.size,0);
 s.audio(false);s.advance(6999);assert.equal(s.state().index,0);s.advance(1);assert.equal(s.state().index,1);s.advance(10000);assert.equal(s.state().index,2);
});
test('stop, load failure and repeated playback resume the same remaining time',()=>{
 const s=setup();s.advance(8000);s.audio(true);s.advance(20000);s.audio(false);s.advance(500);s.audio(true);s.advance(20000);s.audio(false);
 s.advance(1499);assert.equal(s.state().index,0);s.advance(1);assert.equal(s.state().index,1);
});
test('other sentence controls cannot pause or prematurely resume home audio',()=>{
 const s=setup();s.advance(1000);s.audio(true,{});assert.equal(s.state().playing,false);s.audio(true);s.audio(false,{});s.advance(14000);assert.equal(s.state().index,0);
 s.audio(false);s.advance(9000);assert.equal(s.state().index,1);
});
test('manual pause, focus, hover and background visibility preserve time without overlapping timers',()=>{
 const s=setup();s.advance(2000);s.run('homeHovered=true;scheduleHome()');s.advance(20000);s.run('homeHovered=false;homeFocused=true;scheduleHome()');s.advance(20000);
 s.run('homeFocused=false;homePaused=true;scheduleHome()');s.advance(20000);s.run('homePaused=false;document.hidden=true;scheduleHome()');s.advance(20000);
 s.run('document.hidden=false;scheduleHome();scheduleHome()');assert.equal(s.timers.size,1);s.advance(7999);assert.equal(s.state().index,0);s.advance(1);assert.equal(s.state().index,1);
});
test('manual next starts a fresh countdown and detached playback notifications do not affect it',()=>{
 const s=setup();s.advance(4000);s.audio(true);s.run('nextHomeExample()');assert.equal(s.state().index,1);assert.equal(s.state().playing,false);
 s.advance(2000);s.audio(false);s.advance(7999);assert.equal(s.state().index,1);s.advance(1);assert.equal(s.state().index,2);
});
test('single, empty and hidden home screens do not rotate',()=>{
 for(const expression of ['homeVisible=false','homeData.samples.length=1','homeData.samples.length=0']){
  const s=setup();s.run(expression+';scheduleHome()');assert.equal(s.timers.size,0);s.advance(30000);assert.equal(s.state().index,0);
 }
});
