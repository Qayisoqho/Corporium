const test=require('node:test'),assert=require('node:assert/strict'),vm=require('node:vm'),fs=require('node:fs');
const source=fs.readFileSync(require.resolve('../web/timeline.js'),'utf8');

test('horizontal resizing does not remeasure every block line height',()=>{
 const calls=[],block={};const s={blockHeights:new WeakMap(),fitBlockTexts:els=>calls.push(els)};
 vm.createContext(s);vm.runInContext(source.match(/function fitResizedBlockTexts[^\n]+/)[0],s);
 const entry=height=>({target:block,borderBoxSize:[{blockSize:height}]});
 s.fitResizedBlockTexts([entry(54)]);s.fitResizedBlockTexts([entry(54)]);s.fitResizedBlockTexts([entry(54)]);
 assert.equal(calls.length,1);s.fitResizedBlockTexts([entry(80)]);assert.equal(calls.length,2);
});

test('viewport repaint preserves retained block identity and only observes entering blocks',()=>{
 const removed=[],observed=[],unobserved=[],fonts=[];
 const make=id=>({dataset:{interval:id},style:{},remove(){removed.push(id);}});
 const kept=make('keep'),gone=make('gone');kept.focused=true;
 const lane={dataset:{track:'track'},querySelectorAll:()=>[kept,gone],insertAdjacentHTML(where,html){assert.equal(where,'beforeend');this.lastElementChild=make(html);}};
 const interval=(id,a,z)=>({id,track_id:'track',start_ms:a,end_ms:z,entry_id:id,language_id:'language'});
 const playhead={style:{}},s={data:{complete:true,intervals:[interval('keep',0,80),interval('enter',90,150),interval('enter2',100,180),interval('outside',201,300)]},from:50,span:150,head:200,syncPan(){},waveTime:String,block:i=>i.id,ipaStyle:lid=>(fonts.push(lid),'font'),$:id=>id==='tl-tracks'?{querySelectorAll:()=>[lane]}:{},panel:{querySelectorAll:()=>[playhead]},blockTextObserver:{observe:el=>observed.push(el.dataset.interval),unobserve:el=>unobserved.push(el.dataset.interval)},paintSelection(){s.selectionPainted=true;}};
 vm.createContext(s);vm.runInContext(source.slice(source.indexOf('function renderViewport(){'),source.indexOf('function block(')),s);s.renderViewport();
 assert.equal(kept.focused,true);assert.equal(kept.style.left,'0%');assert.equal(kept.style.width,'20%');
 assert.deepEqual(observed,['enter','enter2']);assert.deepEqual(unobserved,['gone']);assert.deepEqual(removed,['gone']);assert.deepEqual(fonts,['language']);
 assert.equal(playhead.style.left,'calc(100% - 1px)');assert.equal(s.selectionPainted,true);
});

test('playback follow waits during a zoom gesture and resumes at the next settled frame',()=>{
 let repaints=0,requests=0;
 const s={media:{paused:false},data:{complete:true,extent:[0,10000]},workspace:'timeline',gesture:null,rangeGesture:null,viewportBusy:true,from:0,span:100,head:250,request:0,TimelineGeometry:require('../web/timeline-geometry.js'),renderViewport:()=>repaints++,drawWave(){},remember(){},loadWave:()=>requests++};
 vm.createContext(s);vm.runInContext(source.slice(source.indexOf('function followPlayback(){'),source.indexOf('async function refreshPlaybackWindow(){')),s);
 s.followPlayback();assert.equal(s.from,0);assert.equal(repaints,0);assert.equal(requests,0);
 s.viewportBusy=false;s.followPlayback();assert.equal(s.from,250);assert.equal(repaints,1);assert.equal(requests,1);
});

test('new blocks entering on the left keep keyboard order without moving retained blocks',()=>{
 const kept={dataset:{interval:'keep'},style:{}},nodes=[kept];let moved;
 const lane={dataset:{track:'t'},querySelectorAll:()=>nodes.slice(),insertAdjacentHTML(_,id){this.lastElementChild={dataset:{interval:id},style:{}};nodes.push(this.lastElementChild);},insertBefore(el,next){moved=el;nodes.splice(nodes.indexOf(el),1);nodes.splice(nodes.indexOf(next),0,el);}};
 const s={data:{complete:true,intervals:[{id:'enter',track_id:'t',start_ms:0,end_ms:20},{id:'keep',track_id:'t',start_ms:30,end_ms:50}]},from:0,span:100,head:0,syncPan(){},waveTime:String,block:i=>i.id,$:id=>id==='tl-tracks'?{querySelectorAll:()=>[lane]}:{},panel:{querySelectorAll:()=>[]},blockTextObserver:{observe(){},unobserve(){}},paintSelection(){}};
 vm.createContext(s);vm.runInContext(source.slice(source.indexOf('function renderViewport(){'),source.indexOf('function block(')),s);s.renderViewport();
 assert.deepEqual(nodes.map(el=>el.dataset.interval),['enter','keep']);assert.equal(moved.dataset.interval,'enter');assert.equal(nodes[1],kept);
});
