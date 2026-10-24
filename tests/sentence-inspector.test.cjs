const {test}=require('node:test'),assert=require('node:assert/strict'),vm=require('node:vm'),fs=require('node:fs');
function setup(){
 const calls=[],questions=[],answers=[],elements={},listeners={},observers=[],metrics={scans:0};
 function dialog(){const handlers={},tabs=['dictionary','morphology'].map(tab=>({dataset:{inspectorTab:tab},setAttribute(){}}));return {open:false,hidden:false,handlers,classList:{add(){}},setAttribute(){},show(){this.open=true;},close(){this.open=false;},querySelector(s){if(s==='.sentence-inspector-tabs')return {};if(s==='form[method="dialog"]')return {addEventListener(){},removeEventListener(){}};return null;},querySelectorAll(){return tabs;},addEventListener(type,fn){handlers[type]=fn;},removeEventListener(){}};}
 elements['word-link-dialog']=dialog();elements['segmentation-dialog']=dialog();elements['segment-word']={value:'0',onchange:async()=>{}};elements['link-unit']={value:'unit'};
 const words=[{form:'a-b',unit_id:'word-0'},{form:'c-d',unit_id:'word-1'}],entry={id:'sentence',title:'source',position:4,words,text_language_id:'one'};
 const c={console,items:[entry],activeLanguage:'one',segmentBusy:false,segmentDirty:false,segmentClose(){},linkUnit:{id:'unit'},MutationObserver:class{constructor(fn){observers.push(fn);}observe(){}},queueMicrotask,URLSearchParams,
  $:id=>elements[id],dockDialog(){},safe:fn=>fn,linkSafe:fn=>fn,
  document:{activeElement:{isConnected:true,focus(){}},documentElement:{classList:{add(){},remove(){}}},addEventListener:(name,fn)=>listeners[name]=fn,querySelector(){return null;}},
  api:async path=>{await new Promise(r=>setImmediate(r));return {body:{words},language_id:'one'};},
  corporiumConfirm:async message=>{questions.push(message);return answers.shift()??false;},loadLinkUnit:async()=>{},refreshSegmentation:async()=>{},
  openWordLink:async(e,w,options)=>{c.dictionaryOptions=options;calls.push(['dictionary',e.id,w.unit_id,e.independentLink?.word]);elements['word-link-dialog'].showModal();await c.loadLinkUnit();},
  openSegmentation:async(kind,id,word)=>{calls.push(['morphology',kind,id,word]);elements['segment-word'].value=String(word);c.segmentDirty=false;elements['segmentation-dialog'].showModal();}
 };
 vm.createContext(c);vm.runInContext(fs.readFileSync('web/sentence-inspector.js','utf8'),c);const inspector=c.createSentenceInspector({querySelectorAll:()=>{metrics.scans++;return [];}});
 return {c,elements,calls,questions,answers,entry,inspector,observers,metrics,listeners};
}
test('dictionary and morphology tabs retain the selected word and reuse unsaved forms',async()=>{
 const {c,calls,entry,elements}=setup();await c.openWordLink(entry,entry.words[1]);await c.openSegmentation('corpus','sentence');
 assert.deepEqual(calls,[['dictionary','sentence','word-1',undefined],['morphology','corpus','sentence',1]]);
 c.segmentDirty=true;await c.openWordLink(entry,entry.words[1]);assert.equal(calls.length,2);assert.equal(c.segmentDirty,true);assert.equal(elements['segmentation-dialog'].hidden,true);
 await c.openSegmentation('corpus','sentence');assert.equal(calls.length,2);assert.equal(elements['segmentation-dialog'].hidden,false);assert.equal(c.segmentDirty,true);
});
test('cancelled word/workspace switches preserve both dirty tabs; confirmation discards together',async()=>{
 const {c,calls,entry,elements,inspector,answers}=setup();await c.openWordLink(entry,entry.words[1]);elements['word-link-dialog'].handlers.input();
 await c.openSegmentation('corpus','sentence');c.segmentDirty=true;
 await c.openWordLink(entry,entry.words[0]);assert.equal(calls.length,2);assert.equal(c.segmentDirty,true);
 await assert.rejects(inspector.leave(),/已保留/);assert.equal(elements['segmentation-dialog'].open,true);
 answers.push(true);await c.openWordLink(entry,entry.words[0]);assert.deepEqual(calls.at(-1).slice(0,3),['dictionary','sentence','word-0']);assert.equal(c.segmentDirty,false);
 await inspector.leave();assert.equal(elements['word-link-dialog'].open,false);assert.equal(elements['segmentation-dialog'].open,false);
});
test('pending morphology writes block navigation; independent examples retain their own word index',async()=>{
 const {c,calls,entry,inspector}=setup();await c.openWordLink(entry,entry.words[0]);c.segmentBusy=true;
 await assert.rejects(c.openWordLink(entry,entry.words[1]),/正在保存/);await assert.rejects(inspector.leave(),/正在保存/);assert.equal(calls.length,1);
 await assert.rejects(c.openSegmentation('corpus','sentence'),/正在保存/);
 c.segmentBusy=false;const independent={...entry,independentLink:{id:'independent-id',word:1}};await c.openWordLink(independent,entry.words[1]);await c.openSegmentation('independent','independent-id');
 assert.deepEqual(calls.at(-2),['dictionary','independent-id','word-1',1]);assert.deepEqual(calls.at(-1),['morphology','independent','independent-id',1]);
});
test('rapid word requests finish in click order without a late response replacing the active context',async()=>{
 const {c,calls,entry}=setup();await Promise.all([c.openWordLink(entry,entry.words[0]),c.openWordLink(entry,entry.words[1])]);await c.openSegmentation('corpus','sentence');
 assert.deepEqual(calls.map(x=>x[0]),['dictionary','dictionary','morphology']);assert.equal(calls.at(-1)[3],1);
});
test('playback time text updates do not trigger sentence-wide inspector scans',async()=>{
 const {observers,metrics}=setup();metrics.scans=0;observers[0]([{addedNodes:[{nodeType:3}]}]);await new Promise(r=>setImmediate(r));assert.equal(metrics.scans,0);
 observers[0]([{addedNodes:[{nodeType:1,matches:()=>true}]}]);await new Promise(r=>setImmediate(r));assert.ok(metrics.scans>0);
});

test('a judgment mark on a no-IPA word remains available to its own editor',()=>{
 const {listeners,calls}=setup(),word={matches:()=>false};
 const target={closest:s=>s.startsWith('.editable-example')?word:s.includes('[data-judgment-edit]')?{}:null};
 listeners.click({target,preventDefault(){assert.fail('judgment click was intercepted');},stopImmediatePropagation(){assert.fail('judgment editor was blocked');}});
 assert.equal(calls.length,0);
});

test('dictionary assistance waits for selection loading and refreshes both tabs after a save',async()=>{
 const {c,calls,entry,inspector}=setup();
 const pending=c.openWordLink(entry,entry.words[1]);
 assert.equal(await inspector.prepare(),true);await pending;
 assert.equal(inspector.current().word,1);
 await c.openSegmentation('corpus','sentence');
 const count=calls.length;await inspector.refresh();
 assert.equal(calls.length,count+1);assert.equal(inspector.current().word,1);
});

test('post-intake refresh keeps the selected part and loads its saved association directly',async()=>{
 const {c,entry,inspector}=setup();await c.openWordLink(entry,entry.words[1]);
 await inspector.refresh({kind:'corpus',id:'sentence',word:1,key:'1:host'});
 assert.equal(c.dictionaryOptions.unitKey,'1:host');assert.equal(c.dictionaryOptions.linkedOnly,true);
 await inspector.refresh({kind:'corpus',id:'different-sentence',word:1,key:'@word'});
 assert.equal(c.dictionaryOptions,undefined);
});
