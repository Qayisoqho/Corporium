const test=require('node:test'),assert=require('node:assert/strict'),vm=require('node:vm'),fs=require('node:fs');
const source=fs.readFileSync(require.resolve('../web/long-tasks.js'),'utf8');
function harness(status){
 const nodes={},calls=[],dialogs=[];
 const node=id=>nodes[id]??={id,disabled:false,textContent:'',after(el){el.parent=this.parent;el.afterOutlet=id;},append(){},setAttribute(){},removeAttribute(){},addEventListener(){}};
 const context={URL,URLSearchParams,DOMException,activeLanguage:'ordos',$:node,window:{addEventListener(){}},setTimeout:fn=>{fn();},refreshUndo:async()=>calls.push(['undo']),api:async(path,body)=>{calls.push(['normal',path,body]);return {};},originalApi:async(path,body)=>{
  calls.push([path,body]);if(path==='task-start'){if(context.startWait)await context.startWait;if(context.failStart)throw Error('start failed');return {id:'job'};}
  if(path==='task-forget'&&context.forgetWait)await context.forgetWait;
  if(path.startsWith('task-status'))return status.shift()||{state:'done',message:'done',result:{ok:true}};
  return {};
 },document:{body:{append(){}},createElement(tag){const d={tag,dataset:{},className:'',children:[],append(...es){this.children.push(...es);es.forEach(e=>e.parent=this);},remove(){d.removed=true;},setAttribute(){},addEventListener(){},showModal(){d.open=true;},close(){d.open=false;}};dialogs.push(d);return d;}}};
 vm.createContext(context);vm.runInContext(source,context);return {context,nodes,calls,dialogs};
}
test('all new read/write routes use the queue and preserve payload language',async()=>{
 const h=harness([]);
 for(const path of ['grammar-audit?source=all','analysis-result?id=r'])await h.context.api(path);
 for(const path of ['analysis-run','import','excel-import','dictionary-replace-apply','text-replace-apply','punctuation-apply','lexeme-auto-link','dict-org-assign','morpheme-assign','copy-entries'])await h.context.api(path,{_language:'other',token:'plan',keys:['one']});
 const requests=h.calls.filter(c=>c[0]==='task-start').map(c=>c[1]);assert.equal(requests.length,12);
 assert.ok(requests.slice(2).every(r=>r.kind==='operation'&&r.request.language==='other'&&r.request.body.token==='plan'));
 assert.ok(!h.calls.some(c=>c[0]==='normal'));assert.equal(h.dialogs[0].open,false);assert.equal(h.context.window.corporiumLongTaskActive(),false);
});
test('commit status disables cancellation, then finishes successfully',async()=>{
 const h=harness([{state:'committing',message:'正在提交'}]);let disabled;
 h.context.setTimeout=fn=>{disabled=h.nodes['long-task-cancel'].disabled;fn();};
 const result=await h.context.api('import',{title:'text',content:'data'});
 assert.equal(disabled,true);assert.equal(result.ok,true);assert.equal(h.dialogs[0].open,false);
});

test('existing dictionary saves use cancellable tasks while new records keep the quick save path',async()=>{
 const h=harness([]);let leaves=0;h.context.window.corporiumLeaveMorpheme=async()=>{leaves++;return true;};
 for(const path of ['lexeme-save','morpheme-save'])await h.context.api(path,{body:{notes:'new'}});
 assert.equal(h.calls.filter(c=>c[0]==='normal').length,2);assert.equal(leaves,0);
 await h.context.api('lexeme-save',{id:'word',_language:'other',body:{notes:'edit'}});
 assert.equal(leaves,1);
 h.context.window.corporiumLeaveMorpheme=async()=>{throw Error('cannot discard the morpheme being saved');};
 await h.context.api('morpheme-save',{id:'part',body:{gloss:'edit'}});
 const requests=h.calls.filter(c=>c[0]==='task-start').map(c=>c[1].request);
 assert.deepEqual(requests.map(r=>r.operation),['lexeme-save','morpheme-save']);assert.equal(requests[0].language,'other');
});
test('large snapshots use a cancellable task and keep language and draft fields, while favorites save directly',async()=>{
 const h=harness([]);
 await h.context.api('analysis-save',{kind:'query',name:'favorite'});
 await h.context.api('analysis-save',{kind:'snapshot',name:'snapshot',notes:'research note',run_id:'run',_language:'all'});
 const starts=h.calls.filter(c=>c[0]==='task-start');assert.equal(starts.length,1);
 assert.equal(starts[0][1].request.operation,'analysis-save');assert.equal(starts[0][1].request.language,'all');assert.equal(starts[0][1].request.body.notes,'research note');
 assert.equal(h.calls.filter(c=>c[0]==='normal').length,1);assert.ok(!h.calls.some(c=>c[0]==='undo'));
});
test('cancelled task closes modal without undo refresh and permits retry',async()=>{
 const h=harness([{state:'cancelled',message:'已取消'}]);await assert.rejects(h.context.api('excel-import',{token:'same'}),/已取消/);
 assert.ok(!h.calls.some(c=>c[0]==='undo'));assert.ok(h.calls.some(c=>c[0]==='task-forget'));
 assert.equal((await h.context.api('excel-import',{token:'same'})).ok,true);assert.equal(h.dialogs[0].open,false);
});
test('undo refresh can queue another task without deadlock',async()=>{
 const h=harness([]);h.context.refreshUndo=async()=>{await h.context.api('grammar-audit?source=all');};
 await h.context.api('import',{content:'test'});assert.equal(h.calls.filter(c=>c[0]==='task-start').length,2);
});
test('empty dictionary controls use an ordinary read; real searches stay cancellable without opening or discarding editors',async()=>{
 const h=harness([]);h.context.window.corporiumLeaveMorpheme=async()=>{throw Error('must keep editor');};h.context.window.corporiumFlushSurvey=async()=>{throw Error('must not autosave a read');};
 await h.context.api('lexemes?search='+encodeURIComponent(JSON.stringify({field:'all',case:false,combine:'all',class_id:'',conditions:[]})));
 assert.equal(h.calls.filter(c=>c[0]==='task-start').length,0);
 await h.context.api('lexemes?q=word&summary=1');
 assert.equal(h.calls.filter(c=>c[0]==='task-start').length,1);
 assert.equal(h.calls.find(c=>c[0]==='task-start')[1].request.summary,'1');
 assert.ok(!h.dialogs[0].open);assert.equal(h.context.window.corporiumLongTaskActive(),false);
});
test('search progress stays outside message outlets, retains a real cancel button, and cleans up after cancellation',async()=>{
 const h=harness([{state:'cancelled',message:'已取消'}]);let release;h.context.startWait=new Promise(r=>release=r);
 // Trigger cancellation between the start request and its first status poll.
 const nodes=h.dialogs;
 const pending=h.context.api('lexemes?q=test');await Promise.resolve();await Promise.resolve();
 const status=nodes.find(n=>n.dataset.taskProgress==='true');assert.ok(status);assert.equal(status.afterOutlet,'dictionary-notice');assert.notEqual(status.parent,h.nodes['dictionary-notice']);
 const cancel=status.children.find(n=>n.tag==='button');assert.equal(typeof cancel.onclick,'function');await cancel.onclick();release();
 await assert.rejects(pending,e=>e.name==='AbortError');assert.equal(status.removed,true);assert.equal(cancel.disabled,true);
 assert.ok(h.calls.some(c=>c[0]==='task-cancel'));assert.ok(!nodes[0].open);
});
test('completed searches and other tasks return results and dismiss progress before slow job cleanup',async()=>{
 for(const path of ['lexemes?q=test','homophones','analysis-result?id=result']){
  const h=harness([]);let release;h.context.forgetWait=new Promise(r=>release=r);let timer;
  const result=await Promise.race([h.context.api(path),new Promise((_,reject)=>timer=setTimeout(()=>reject(Error('job cleanup blocked results')),250))]);clearTimeout(timer);release();assert.equal(result.ok,true);assert.ok(!h.dialogs[0].open);
  const status=h.dialogs.find(n=>n.dataset.taskProgress==='true');if(status)assert.equal(status.removed,true);
 }
});
test('search progress is removed after startup and execution errors',async()=>{
 for(const failStart of [false,true]){const h=harness([{state:'error',message:'search failed'}]);h.context.failStart=failStart;await assert.rejects(h.context.api('lexemes?q=test'),/failed/);assert.equal(h.dialogs.find(n=>n.dataset.taskProgress==='true').removed,true);}
});

for(const fail of [false,true])test('one automatic-link progress window spans both phases and closes on '+(fail?'failure':'success'),async()=>{
 const h=harness([]);let opens=0,closes=0;const dialog=h.dialogs[0];dialog.showModal=()=>{opens++;dialog.open=true;};dialog.close=()=>{closes++;dialog.open=false;};
 const action=h.context.window.corporiumWithTaskProgress(async()=>{
  await h.context.api('lexeme-auto-link',{token:'plan'});
  assert.equal(dialog.open,true);assert.equal(h.context.window.corporiumLongTaskActive(),true);
  if(fail)h.context.failStart=true;
  return h.context.api('lexeme-auto-preview?language=ordos');
 });
 if(fail)await assert.rejects(action,/start failed/);else await action;
 assert.equal(opens,1);assert.equal(closes,1);assert.equal(dialog.open,false);assert.equal(h.context.window.corporiumLongTaskActive(),false);
 assert.equal(h.calls.filter(c=>c[0]==='undo').length,0);
});
