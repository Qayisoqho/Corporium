const test=require('node:test'),assert=require('node:assert/strict'),vm=require('node:vm'),fs=require('node:fs');
const source=fs.readFileSync('web/timeline.js','utf8');
test('block sizing reads the full batch before writes and unchanged sizing does not mutate styles',()=>{
 const events=[],make=(height,line)=>{const values=new Map();const text={line,style:{getPropertyValue:k=>values.get(k)||'',setProperty(k,v){events.push('write');values.set(k,v);}}};return {get clientHeight(){events.push('height');return height;},querySelector:()=>text,text};};
 const blocks=[make(64,20),make(112,24),make(0,20)],c={getComputedStyle(t){events.push('line');return {lineHeight:String(t.line)};}};
 vm.createContext(c);vm.runInContext(source.slice(source.indexOf('function fitBlockTexts('),source.indexOf('const blockTextObserver=')),c);c.fitBlockTexts(blocks);
 assert.deepEqual(events,['height','line','height','line','height','write','write']);
 assert.equal(blocks[0].text.style.getPropertyValue('--tl-text-lines'),'3');assert.equal(blocks[1].text.style.getPropertyValue('--tl-text-lines'),'4');
 events.length=0;c.fitBlockTexts(blocks);assert.ok(!events.includes('write'));
 blocks[0].text.line=32;c.fitBlockTexts(blocks);assert.equal(blocks[0].text.style.getPropertyValue('--tl-text-lines'),'1');
});
test('large timeline rendering preserves track order, closed window edges and current typography without repeating conversions',()=>{
 const nodes={},styles=[],tracks=[{id:'a',name:'A',kind:'sentence'},{id:'b',name:'B',kind:'sentence'}];let font='old';
 const intervals=[{id:'left',track_id:'a',start_ms:-50,end_ms:0},{id:'outside',track_id:'a',start_ms:-10,end_ms:-1},{id:'inside',track_id:'a',start_ms:10,end_ms:200},{id:'b',track_id:'b',start_ms:25,end_ms:50},{id:'right',track_id:'a',start_ms:100,end_ms:120}].map(i=>({...i,entry_id:'sentence',language_id:i.track_id,text:i.id,status:'confirmed'}));
 const c={data:{tracks,intervals,speakers:[],count:30000,extent:[0,10000]},from:0,span:100,head:0,selectedInterval:'inside',collapsedTracks:new Set(),TimelineTree:{colors:()=>new Map(),rows:()=>tracks.map(track=>({track,depth:0}))},blockTextObserver:{disconnect(){},observe(){}},syncPan(){},waveTime:String,time:String,esc:String,trackHeight:()=>64,CorporiumPeople:{label:x=>x},ipaStyle(lid){styles.push(lid);return font+lid;},safeTL:f=>f,paintSelection(){},$:id=>nodes[id]??={querySelectorAll:()=>[]}};
 vm.createContext(c);vm.runInContext(source.slice(source.indexOf('function renderTracks(){'),source.indexOf('async function save(')),c);c.renderTracks();
 const html=nodes['tl-tracks'].innerHTML;assert.deepEqual([...html.matchAll(/data-interval="([^"]+)"/g)].map(m=>m[1]),['left','inside','right','b']);assert.deepEqual(styles,['a','b']);
 assert.match(html,/class="tl-block selected /);assert.match(html,/style="olda"/);assert.match(nodes['tl-range-note'].textContent,/30000/);
 styles.length=0;font='new';c.renderTracks();assert.match(nodes['tl-tracks'].innerHTML,/style="newa"/);assert.deepEqual(styles,['a','b']);
});
