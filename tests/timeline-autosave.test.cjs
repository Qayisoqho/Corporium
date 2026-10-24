const test=require('node:test'),assert=require('node:assert/strict'),vm=require('node:vm'),fs=require('node:fs');
const source=fs.readFileSync(require.resolve('../web/timeline.js'),'utf8');
function harness(existing=true){
 const nodes={};for(const id of ['tl-start','tl-end','tl-set-in','tl-set-out','tl-commit','tl-delete','tl-split','tl-merge','tl-time-save-state','tl-editor'])nodes[id]={value:'',dataset:{},addEventListener(){},removeAttribute(){}};
 nodes['tl-start'].value='1';nodes['tl-end'].value='2';
 const interval={id:existing?'one':null,track_id:'track',entry_id:'sentence',start_ms:1000,end_ms:2000,status:'review',label:'',parent_id:null,code_id:null};
 const ctx={dirtyInterval:false,draftInterval:existing?null:interval,flushTime:null,timeSave:null,$:id=>nodes[id],bindDependencies(){},safeTL:fn=>fn,sec:n=>(n/1000).toFixed(3),head:1500,currentInterval:()=>interval,intervalKey:()=>interval.id,setSelection(){},save:async()=>{}};
 vm.createContext(ctx);vm.runInContext(source.slice(source.indexOf('async function flushIntervalTime'),source.indexOf('window.corporiumFlushTimeline')),ctx);
 vm.runInContext(source.slice(source.indexOf('function intervalPayload'),source.indexOf('const intervalKey=')),ctx);ctx.bindFields(interval);
 return {ctx,nodes,interval,edit(value){nodes['tl-end'].value=value;nodes['tl-end'].oninput();},flush:()=>ctx.flushIntervalTime()};
}
test('autosave serializes concurrent edits and retains existing review status',async()=>{
 const h=harness(),writes=[];let release;
 h.ctx.save=async(action,payload)=>{writes.push({...payload});if(writes.length===1)await new Promise(r=>release=r);};
 h.edit('3');const first=h.flush();h.edit('4');const second=h.flush();release();await Promise.all([first,second]);
 assert.deepEqual(writes.map(p=>p.end_ms),[3000,4000]);assert.ok(writes.every(p=>p.status==='review'));
 assert.equal(h.ctx.dirtyInterval,false);assert.equal(h.interval.end_ms,4000);
});
test('invalid or rejected times remain unsaved and can be corrected',async()=>{
 const h=harness();let writes=0;h.ctx.save=async()=>{writes++;throw Error('区间碰撞');};
 h.edit('');await assert.rejects(h.flush(),/有效数字/);assert.equal(writes,0);
 h.edit('0.5');await assert.rejects(h.flush(),/晚于起点/);assert.equal(writes,0);
 h.edit('3');await assert.rejects(h.flush(),/碰撞/);assert.equal(h.ctx.dirtyInterval,true);assert.equal(h.interval.end_ms,2000);
 h.ctx.save=async()=>{};await h.flush();assert.equal(h.ctx.dirtyInterval,false);
});
test('unchanged values do not create writes, and draft times do not auto-create intervals',async()=>{
 for(const existing of [true,false]){const h=harness(existing);let writes=0;h.ctx.save=async()=>writes++;h.edit(existing?'2.000':'3');await h.flush();assert.equal(writes,0);assert.equal(h.ctx.dirtyInterval,!existing);}
});
