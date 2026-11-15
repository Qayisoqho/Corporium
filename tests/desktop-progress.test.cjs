const test=require('node:test'),assert=require('node:assert/strict'),fs=require('node:fs'),vm=require('node:vm');
const source=fs.readFileSync('web/desktop.js','utf8');
const fn=source.slice(source.indexOf(' async function completeStartup(){'),source.indexOf(' void completeStartup().catch'));
const deferred=()=>{let resolve;return {promise:new Promise(r=>resolve=r),resolve:()=>resolve()};};
const flush=async()=>{for(let n=0;n<12;n++)await Promise.resolve();};
test('desktop handoff waits for page data, fonts and native bridge, once',async()=>{
 const status=deferred(),fonts=deferred(),calls=[],listeners={},observers=[];
 const root={dataset:{appLoading:'true'}},body={};
 const c={status:status.promise,document:{documentElement:root,body,fonts:{ready:fonts.promise}},
  window:{addEventListener:(name,fn)=>listeners[name]=fn},
  MutationObserver:class{constructor(fn){this.fn=fn;observers.push(this);}observe(){}disconnect(){this.closed=true;}},
  getComputedStyle:node=>node===root?{fontSize:'24px'}:{fontFamily:'"Junicode", serif',fontWeight:'700',fontStyle:'italic'},
  clearTimeout,setTimeout};
 vm.createContext(c);vm.runInContext(fn,c);const ready=c.completeStartup();
 await flush();assert.equal(calls.length,0);status.resolve();await flush();
 c.window.pywebview={api:{startup_ready:async style=>calls.push(style)}};listeners.pywebviewready();await flush();
 assert.equal(calls.length,0);assert.equal(observers.length,1);
 root.dataset.appLoading='false';observers[0].fn();await flush();assert.equal(calls.length,0);
 fonts.resolve();await ready;assert.equal(observers[0].closed,true);assert.equal(calls.length,1);
 assert.equal(calls[0].scale,1.5);assert.equal(calls[0].font,'Junicode');assert.equal(calls[0].weight,700);assert.equal(calls[0].italic,true);
});
test('projectless startup completes without a missing workspace event',async()=>{
 let calls=0;const c={status:Promise.resolve(),document:{documentElement:{dataset:{}},body:{}},window:{pywebview:{api:{startup_ready:async()=>calls++}}},
  MutationObserver:class{observe(){}},getComputedStyle:()=>({fontSize:'16px',fontFamily:'Segoe UI',fontWeight:'400',fontStyle:'normal'}),clearTimeout,setTimeout};
 vm.createContext(c);vm.runInContext(fn,c);await c.completeStartup();assert.equal(calls,1);
});
