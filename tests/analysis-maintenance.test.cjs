const test=require('node:test'),assert=require('node:assert/strict'),fs=require('node:fs'),vm=require('node:vm');
const source=fs.readFileSync('web/analysis-workspace.js','utf8');
function setup(){
 const timers=[],events={},calls=[];let now=10000;
 const c=vm.createContext({Date:{now:()=>now},setTimeout:f=>{timers.push(f);return timers.length;},document:{hidden:false},
  window:{addEventListener:(name,fn)=>events[name]=fn},api:async(...args)=>{calls.push(args);return{pending:false};}});
 vm.runInContext(source.slice(source.indexOf('let maintenanceTimer='),source.indexOf('async function loadRecords')),c);
 return {c,timers,events,calls,advance:ms=>now+=ms,schedule:()=>c.scheduleMaintenance()};
}
test('idle cleanup coalesces catalogue refreshes and stops when complete',async()=>{
 const x=setup();x.schedule();x.schedule();assert.equal(x.timers.length,1);await x.timers.shift()();
 assert.equal(JSON.stringify(x.calls),JSON.stringify([['analysis-maintenance',{}]]));assert.equal(x.timers.length,0);
});
test('typing, hidden documents and long tasks postpone every cleanup batch',async()=>{
 const x=setup();x.events.input();x.schedule();await x.timers.shift()();assert.equal(x.calls.length,0);
 x.advance(5001);x.c.document.hidden=true;await x.timers.shift()();assert.equal(x.calls.length,0);
 x.c.document.hidden=false;x.c.window.corporiumLongTaskActive=()=>true;await x.timers.shift()();assert.equal(x.calls.length,0);
 x.c.window.corporiumLongTaskActive=()=>false;await x.timers.shift()();assert.equal(x.calls.length,1);
});
test('pending collection resumes later and optional errors leave future refreshes usable',async()=>{
 const x=setup();x.c.api=async()=>({pending:true});x.schedule();await x.timers.shift()();assert.equal(x.timers.length,1);
 x.c.api=async()=>{throw Error('project switched');};await x.timers.shift()();assert.equal(x.timers.length,0);
 x.schedule();assert.equal(x.timers.length,1);
});
