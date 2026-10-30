const test=require('node:test'),assert=require('node:assert/strict'),vm=require('node:vm'),fs=require('node:fs');
async function setup(compact,clips=[{id:'first',session_name:'One',start_ms:0,end_ms:1000,play_start_ms:0,play_end_ms:1000,asset:'wav',proxy:0},{id:'second',session_name:'Two',start_ms:2000,end_ms:3000,play_start_ms:2000,play_end_ms:3000,asset:'wav',proxy:0}],brief=false){
 const listeners={},timers=[],alerts=[],audioEvents=[],status={textContent:''},select={value:'1',replaceChildren(...options){this.options=options;}};
 const holder={dataset:{audioEntry:'independent:example',...(compact?{audioCompact:'true'}:{})},isConnected:true,innerHTML:'',querySelector(s){return s==='select'?(this.innerHTML.includes('<select')?select:null):status;}};
 const audio={paused:true},button={textContent:'▶',isConnected:true,setAttribute(){},closest(){return holder;}};let played,onEnd;
 const modes=new Set(brief?['brief-mode']:[]);
 const context={esc:s=>s,renderEditableExample:()=>'',document:{documentElement:{classList:{contains:s=>modes.has(s)}},createElement:()=>audio,body:{append(){}},dispatchEvent:event=>audioEvents.push(event),querySelectorAll:()=>[holder],addEventListener:(k,fn)=>listeners[k]=fn},setTimeout:fn=>{timers.push(fn);return timers.length;},clearTimeout(){},MutationObserver:class{observe(){}},RangePlayback:class{constructor(media,done){onEnd=done;}stop(){audio.paused=true;}async start(a,b){played=[a,b];audio.paused=false;}},originalApi:async()=>({'independent:example':clips}),CustomEvent:class{constructor(type,options){Object.assign(this,{type,...options});}},Option:class{constructor(text,value){Object.assign(this,{text,value});}},URLSearchParams,localStorage:{getItem:()=>null},corporiumAlert:async m=>{alerts.push(m);}};
 context.window=context;vm.runInNewContext(fs.readFileSync(require.resolve('../web/sentence-audio.js'),'utf8'),context);
 await timers.shift()();
 return {holder,select,context,audio,alerts,status,modes,audioEvents,finish:()=>{audio.paused=true;onEnd();},play:async()=>{await listeners.click({target:{closest:()=>button},preventDefault(){},stopPropagation(){}});return played;}};
}
test('welcome audio has one playback button and uses the first available interval',async()=>{const s=await setup(true);assert.equal(s.holder.hidden,false);assert.ok(!s.holder.innerHTML.includes('<select'));assert.match(s.holder.innerHTML,/role="status" hidden/);assert.deepEqual(await s.play(),[0,1]);assert.match(s.context.sentenceAudioMarkup('independent:example',{compact:true}),/data-audio-compact="true"/);});
test('shared sentence views retain the interval selector and selected playback',async()=>{const s=await setup(false);assert.match(s.holder.innerHTML,/<select/);assert.equal(s.select.options.length,2);assert.deepEqual(await s.play(),[2,3]);assert.ok(!s.context.sentenceAudioMarkup('example').includes('compact'));});
test('sentences without audio keep their playback control hidden',async()=>{const s=await setup(true,[]);assert.equal(s.holder.hidden,true);assert.equal(s.holder.innerHTML,'');});
test('compact playback failures are reported instead of being hidden with the status text',async()=>{const s=await setup(true);await s.play();s.audio.onerror();assert.equal(s.audio.paused,true);assert.equal(s.alerts.length,1);assert.match(s.alerts[0],/播放失败/);const full=await setup(false);await full.play();full.audio.onerror();assert.match(full.status.textContent,/播放失败/);assert.equal(full.alerts.length,0);});
test('brief reading reports audio errors and preserves selected recordings when returning to full mode',async()=>{const s=await setup(false,undefined,true);assert.match(s.holder.innerHTML,/<select/);assert.deepEqual(await s.play(),[2,3]);s.audio.onerror();assert.equal(s.audio.paused,true);assert.match(s.alerts[0],/播放失败/);assert.equal(s.status.textContent,'');s.modes.delete('brief-mode');assert.deepEqual(await s.play(),[2,3]);s.audio.onerror();assert.equal(s.alerts.length,1);assert.match(s.status.textContent,/播放失败/);});

test('empty and linked audio both notify recording controls after discovery',async()=>{for(const clips of [[],[{id:'clip',asset:'audio',start_ms:0,end_ms:1000}]]){const s=await setup(false,clips);assert.equal(s.audioEvents[0].type,'corporium-sentence-audio-ready');assert.equal(s.audioEvents[0].detail,s.holder);assert.equal(s.holder._clips.length,clips.length);}});

test('playback state identifies its holder and ends on completion, stop and failure',async()=>{
 for(const finish of [s=>s.finish(),s=>s.context.stopSentenceAudio(),s=>s.audio.onerror()]){
  const s=await setup(true);await s.play();finish(s);
  const states=s.audioEvents.filter(e=>e.type==='corporium-sentence-audio-state');assert.deepEqual(states.map(e=>e.detail.active),[true,false]);assert.ok(states.every(e=>e.detail.holder===s.holder));
 }
});
test('loading immediately pauses the carousel; cancellation and rejected clip lookup release it',async()=>{
 const s=await setup(true);let resolve;s.context.originalApi=()=>new Promise(done=>resolve=done);const pending=s.play();
 const states=()=>s.audioEvents.filter(e=>e.type==='corporium-sentence-audio-state').map(e=>e.detail.active);assert.deepEqual(states(),[true]);
 s.context.stopSentenceAudio();resolve({});await pending;assert.deepEqual(states(),[true,false]);assert.equal(s.audio.paused,true);
 s.context.originalApi=async()=>({});await s.play();assert.deepEqual(states(),[true,false,true,false]);assert.equal(s.alerts.length,1);
});
