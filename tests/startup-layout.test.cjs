const test=require('node:test'),assert=require('node:assert/strict'),vm=require('node:vm'),fs=require('node:fs');
const app=fs.readFileSync(require.resolve('../web/app.js'),'utf8');
const helper=app.slice(app.indexOf('function nextLayoutFrame('),app.indexOf('async function api('));
function setup(){
 const handlers=new Map(),frames=new Map();let id=0;
 const c={document:{hidden:false,documentElement:{dataset:{appLoading:'false'}},addEventListener:(n,f)=>handlers.set(n,f),removeEventListener:n=>handlers.delete(n)},requestAnimationFrame:f=>{frames.set(++id,f);return id;},cancelAnimationFrame:n=>frames.delete(n)};
 vm.createContext(c);vm.runInContext(helper,c);return {c,handlers,frames};
}
test('startup and hidden workspace restoration do not wait for suspended animation frames',async()=>{
 const {c,frames}=setup();c.document.documentElement.dataset.appLoading='true';await c.nextLayoutFrame();assert.equal(frames.size,0);
 c.document.documentElement.dataset.appLoading='false';c.document.hidden=true;await c.nextLayoutFrame();assert.equal(frames.size,0);
});
test('visible layout waits for a frame and releases its visibility listener',async()=>{
 const {c,handlers,frames}=setup();let done=false;const p=c.nextLayoutFrame().then(()=>done=true);await Promise.resolve();assert.equal(done,false);
 [...frames.values()][0]();await p;assert.equal(done,true);assert.equal(handlers.size,0);assert.equal(frames.size,0);
});
test('hiding a window during a layout wait releases pending restoration',async()=>{
 const {c,handlers,frames}=setup();const p=c.nextLayoutFrame();c.document.hidden=true;handlers.get('visibilitychange')();await p;assert.equal(frames.size,0);assert.equal(handlers.size,0);
});
