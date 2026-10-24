const test=require('node:test'),assert=require('node:assert/strict'),vm=require('node:vm'),fs=require('node:fs');
const source=fs.readFileSync('web/dictionary-list.js','utf8');
test('virtual dictionary ranges include every visible variable-height row and remain bounded at either end',()=>{
 const c={};vm.createContext(c);vm.runInContext(source,c);const offsets=[0];for(let i=0;i<5000;i++)offsets.push(offsets.at(-1)+(i%11===0?56:40));
 for(const top of [0,1,800,offsets[2500]+10,offsets.at(-1)-600,offsets.at(-1)+100]){
  const [start,end]=c.dictionaryVisibleRange(offsets,top,600);assert.ok(start>=0&&end<=5000&&start<end);assert.ok(end-start<40);assert.ok(offsets[start]<=top||start===0);assert.ok(offsets[end]>=Math.min(top+600,offsets.at(-1)));
 }
 assert.equal(c.dictionaryVisibleRange(offsets,offsets.at(-1)-10,600)[1],5000);
});

test('class folding retains its own heading, hides descendants and preserves sibling branches and child state',()=>{
 const c={};vm.createContext(c);vm.runInContext(source,c);
 const word=(id,...keys)=>({id,body:{},sort_path:keys.map(key=>({key,label:key==='a'?'同名子类':key}))});
 const items=[word('1','root','a'),word('2','root','a'),word('3','root','b'),word('4','other','a')];
 const closed=new Set(['["root","a"]']);
 const summarize=()=>Array.from(c.dictionaryClassRows(items,closed),r=>r.dictionaryClass?(r.dictionaryClass.closed?'closed:':'open:')+r.dictionaryClass.path:r.id);
 assert.deepEqual(summarize(),['open:["root"]','closed:["root","a"]','open:["root","b"]','3','open:["other"]','open:["other","a"]','4']);
 closed.add('["root"]');assert.deepEqual(summarize(),['closed:["root"]','open:["other"]','open:["other","a"]','4']);
 closed.delete('["root"]');assert.ok(summarize().includes('closed:["root","a"]'));assert.ok(!summarize().includes('1'));
 closed.clear();assert.equal(c.dictionaryClassRows(items,closed).filter(r=>r.id).length,4);assert.equal(items.length,4);
 // A page can start partway through a class; it still gets all ancestor headings.
 assert.deepEqual(Array.from(c.dictionaryClassRows(items.slice(1,2),closed),r=>r.dictionaryClass?.path||r.id),['["root"]','["root","a"]','2']);
 assert.deepEqual(Array.from(c.dictionaryClassRows([{id:'ungrouped'}],closed),r=>r.id),['ungrouped']);
});

test('collapsing a 5000-word branch removes its rows before mounting, and rebuilding keeps the source intact',()=>{
 const host={style:{},scrollTop:0,hidden:false,isConnected:true,addEventListener(){},removeEventListener(){},removeAttribute(){}};
 const c={window:{},document:{getElementById:()=>host},ResizeObserver:class{disconnect(){}},requestAnimationFrame(){}};vm.createContext(c);vm.runInContext(source,c);
 const items=Array.from({length:5000},(_,i)=>({id:String(i),body:{},sort_path:[{key:'root',label:'词类'}]})),closed=new Set(['["root"]']);
 assert.equal(c.dictionaryClassRows(items,closed).length,1);
 c.renderDictionaryList(host,items,{transform:rows=>c.dictionaryClassRows(rows,closed),html:r=>r.dictionaryClass?'heading':r.id,attribute:'data-word',select(){},empty:'empty'});
 assert.equal(host.innerHTML,'heading');assert.equal(items.length,5000);
 host.dictionaryViewport.rebuild();assert.equal(host.innerHTML,'heading');
 closed.clear();assert.equal(c.dictionaryClassRows(items,closed).filter(r=>r.id).length,5000);
});
