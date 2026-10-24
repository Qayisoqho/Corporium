const test=require('node:test'),assert=require('node:assert/strict'),vm=require('node:vm'),fs=require('node:fs');
function setup(){
 const source=fs.readFileSync('web/paradigms.js','utf8'),start=source.indexOf("   tbody.addEventListener('keydown',e=>{"),end=source.indexOf('   for(const category',start);
 let handler,focused,selected;
 const rows=Array.from({length:3},(_,r)=>Array.from({length:2},(_,c)=>({r,c,disabled:false,matches:()=>true,focus(){focused=this;},select(){selected=this;}})));
 const tbody={addEventListener:(name,fn)=>handler=fn,querySelectorAll:()=>rows.map(inputs=>({querySelectorAll:()=>inputs}))};
 vm.runInNewContext(source.slice(start,end),{tbody});
 function key(r,c,key,extra={}){let prevented=false;focused=selected=undefined;handler({target:rows[r][c],key,preventDefault(){prevented=true;},...extra});return {focused,selected,prevented};}
 return {rows,key};
}
test('Tab moves between entry fields and leaves the sheet normally at its boundaries',()=>{
 const {rows,key}=setup();assert.equal(key(0,0,'Tab').focused,rows[0][1]);assert.equal(key(0,1,'Tab').focused,rows[1][0]);
 assert.equal(key(1,0,'Tab',{shiftKey:true}).focused,rows[0][1]);assert.equal(key(0,0,'Tab',{shiftKey:true}).prevented,false);assert.equal(key(2,1,'Tab').prevented,false);
});
test('Enter keeps the column, skips disabled rows and never submits the dictionary form',()=>{
 const {rows,key}=setup();rows[1].forEach(input=>input.disabled=true);
 let result=key(0,1,'Enter');assert.equal(result.focused,rows[2][1]);assert.equal(result.selected,result.focused);assert.equal(result.prevented,true);
 result=key(2,0,'Enter',{shiftKey:true});assert.equal(result.focused,rows[0][0]);
 result=key(2,1,'Enter');assert.equal(result.focused,undefined);assert.equal(result.prevented,true);
});
test('IME composition, modifier shortcuts and advanced controls retain native key handling',()=>{
 const {rows,key}=setup();assert.equal(key(0,0,'Enter',{isComposing:true}).prevented,false);
 for(const modifier of ['ctrlKey','altKey','metaKey'])assert.equal(key(0,0,'Enter',{[modifier]:true}).prevented,false);
 rows[0][0].matches=()=>false;assert.equal(key(0,0,'Enter').prevented,false);
});
