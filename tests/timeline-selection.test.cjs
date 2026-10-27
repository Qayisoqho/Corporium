const test=require('node:test'),assert=require('node:assert/strict'),vm=require('node:vm'),fs=require('node:fs');
const source=fs.readFileSync(require.resolve('../web/timeline.js'),'utf8');
const rangeUp=source.slice(source.indexOf("panel.addEventListener('pointerup',e=>"),source.indexOf("panel.addEventListener('pointercancel',()=>{rangeGesture=null"));
function harness(){
 const inputs={};const s={inlineDrafts:new Map(),rangeGesture:{pointer:7,moved:true,area:{dataset:{track:'second'},releasePointerCapture(){}}},timeSelection:[1234,4567],head:0,draftInterval:{track_id:'first'},pendingEntry:'sentence',selectedInterval:null,data:{tracks:[{id:'second',kind:'sentence'}]},dirtyInterval:false,$:id=>inputs[id]||=({}),sec:n=>(n/1000).toFixed(3),updateHead(){},panel:{addEventListener(name,fn){s.handler=fn;}}};
 s.timelineHasSentenceDraft=()=>s.inlineDrafts.size>0;vm.runInNewContext(rangeUp,s);s.fire=()=>s.handler({pointerId:7,preventDefault(){},stopImmediatePropagation(){}});return s;
}
test('range selection copies exact milliseconds and target sentence track to pending draft',()=>{
 const s=harness();s.fire();assert.equal(s.draftInterval.track_id,'second');assert.equal(s.$('tl-start').value,'1.234');assert.equal(s.$('tl-end').value,'4.567');assert.equal(s.draftInterval.end_ms-s.draftInterval.start_ms,3333);assert.equal(s.dirtyInterval,true);
});
test('selecting an event track cannot move a sentence draft onto the event track',()=>{
 const s=harness();s.data.tracks[0].kind='event';s.fire();assert.equal(s.draftInterval.track_id,'first');assert.equal(s.$('tl-start').value,'1.234');
});
test('playback selection does not overwrite an existing block timing',()=>{
 const s=harness();s.selectedInterval='existing';s.pendingEntry=null;s.fire();assert.equal(s.dirtyInterval,false);assert.equal(s.draftInterval.start_ms,undefined);assert.equal(s.head,0);
});
test('blank lane click clears the sentence without seeking; waveform click seeks',()=>{
 for(const lane of [true,false]){const s=harness();let cleared=false,seek=null;s.rangeGesture.moved=false;s.rangeGesture.start=2345;s.rangeGesture.area.classList={contains:()=>lane};s.clearSentence=()=>cleared=true;s.seek=n=>seek=n;s.setSelection=()=>{};s.fire();assert.equal(cleared,lane);assert.equal(seek,lane?null:2345);}
});

test('listening selection during sentence editing leaves its timing draft unchanged',()=>{
 const s=harness();s.inlineDrafts.set('sentence',{dirty:true});s.fire();assert.equal(s.draftInterval.start_ms,undefined);assert.equal(s.dirtyInterval,false);
});
test('blank lane click preserves the open sentence editor',()=>{
 const s=harness();s.inlineDrafts.set('sentence',{dirty:true});s.rangeGesture.moved=false;s.rangeGesture.area.classList={contains:()=>true};s.setSelection=()=>{};s.clearSentence=()=>assert.fail('editing sentence must remain selected');s.fire();
});
