const test=require('node:test'),assert=require('node:assert/strict'),fs=require('node:fs'),vm=require('node:vm');
const source=fs.readFileSync('web/docx-exchange.js','utf8');
function model(groups){const c={structuredClone,Error};vm.createContext(c);vm.runInContext(source.slice(0,source.indexOf('(()=>{'))+';this.Model=CorporiumDocxDraft;',c);return new c.Model(groups);}
test('merge split reset sequence preserves a complete ordered partition',()=>{
 const m=model([{start:0,end:8},{start:8,end:9},{start:9,end:15}]);m.split(0,4);m.merge(1,{},{});
 assert.deepEqual(JSON.parse(JSON.stringify(m.groups)),[{start:0,end:4},{start:4,end:9},{start:9,end:15}]);m.reset();assert.equal(m.groups.length,3);assert.equal(m.groups[0].end,8);
});
test('merge retains custom sentence fields and split keeps the edit on the first part',()=>{
 const m=model([{start:0,end:5,translation:'edited'},{start:5,end:9}]);m.merge(0,{ipa:'a',translation:'edited',notes:'',original:''},{ipa:'b',translation:'second',notes:'note',original:''});
 assert.equal(m.groups[0].translation,'edited\nsecond');m.split(0,6);assert.equal(m.groups[0].notes,'note');assert.equal(m.groups[1].notes,undefined);
});
test('invalid splits and nonadjacent merges leave the recipe unchanged',()=>{
 const m=model([{start:0,end:4},{start:5,end:9}]);for(const at of [0,4,-1,8,1.5])assert.throws(()=>m.split(0,at));assert.throws(()=>m.merge(0,{},{}));assert.equal(m.groups.length,2);
});
test('preview title changes cannot reuse an old commit receipt',()=>{
 const c={receipt:'old',nodes:{'docx-commit':{disabled:false}}};c.$=id=>c.nodes[id];vm.createContext(c);const start=source.indexOf(' function invalidate()');vm.runInContext(source.slice(start,source.indexOf(' function payload()',start)),c);c.invalidate();assert.equal(c.receipt,null);assert.equal(c.nodes['docx-commit'].disabled,true);
});
test('Word read-only preparation does not refresh history or invalidate cached workspaces',async()=>{
 const undo=fs.readFileSync('web/undo.js','utf8'),calls=[],c={originalApi:async()=>calls.push('request'),refreshUndo:async()=>calls.push('history'),window:{corporiumRefreshUndoState:async()=>calls.push('history')}};
 vm.createContext(c);vm.runInContext(undo.slice(undo.indexOf('api=async function(path,body)'),undo.indexOf('async function undoCommand(')),c);
 for(const action of ['inspect','preview','export','template'])await c.api('docx-'+action,{});assert.deepEqual(calls,['request','request','request','request']);
});
test('format chooser routes Word into its dedicated compact dialog',()=>{
 const script=fs.readFileSync('web/text-exchange.js','utf8');assert.match(script,/<option value="docx">Word（\.docx）<\/option>/);assert.match(script,/await CorporiumDocxExchange\.open\(mode\)/);
});
