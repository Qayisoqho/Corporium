const test=require('node:test'),assert=require('node:assert/strict'),vm=require('node:vm'),fs=require('node:fs');
function setup(){const c=vm.createContext({compactWord:w=>!!w.compact});const display=fs.readFileSync('web/display-tools.js','utf8'),inline=fs.readFileSync('web/inline-editor.js','utf8');vm.runInContext(display.slice(display.indexOf('function glossEditParts('),display.indexOf('function lexemeLabel(')),c);vm.runInContext(inline.slice(inline.indexOf('function inlineWordParts('),inline.indexOf('function renderEditableExample(')),c);return c;}
test('all labels before a morpheme boundary share the corresponding form column',()=>{
 const c=setup(),w={form:'opened-ne',gloss:'开.pst-sg'},before=JSON.stringify(w),p=c.inlineWordLayout(w);
 assert.equal(p.form[0].column,1);assert.equal(p.form[0].span,3);
 assert.equal(p.form[1].column,p.gloss[3].column);
 assert.equal(p.form[2].column,p.gloss[4].column);assert.equal(p.columns,5);assert.equal(JSON.stringify(w),before);
});
test('clitic, reduplication, compound and decorated/infix labels retain their boundaries',()=>{
 const c=setup();for(const boundary of ['-','=','+','~','＝']){
  const p=c.inlineWordLayout({form:'stem'+boundary+'suffix',gloss:'STEM.PST'+boundary+'SG'});
  assert.equal(p.form[2].column,p.gloss[4].column,boundary);assert.equal(p.form[1].column,p.gloss[3].column);
 }
 const p=c.inlineWordLayout({form:'h<i>j-ne',gloss:'H<I.PST>J.LOC-SG#sub[2]'});
 assert.equal(p.form[2].column,p.gloss[4].column);assert.equal(p.columns,5);
});
test('real boundary mismatches preserve every editable value, and compact symbols remain single cells',()=>{
 const c=setup(),w={form:'opened=ne',gloss:'开.pst-sg'},p=c.inlineWordLayout(w);
 assert.equal(p.form[2].column,3);assert.equal(p.gloss[4].column,5);
 assert.equal(c.inlineWordLayout({form:'?',gloss:'',compact:true}).columns,1);
 assert.equal(c.inlineWordParts(w,'gloss').join(''),w.gloss);
});
