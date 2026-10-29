const test=require('node:test'),assert=require('node:assert/strict'),fs=require('node:fs'),vm=require('node:vm');
const copy=require('../web/formatted-copy-format.js');
function setup(){const c=vm.createContext({activeLanguage:'one',languageList:[{id:'one',metadata:JSON.stringify({glossary:{PST:'past','neg#sub[POT]':'negative',NOM_SG:'one tag'}})}],esc:s=>String(s??'').replaceAll('&','&amp;').replaceAll('<','&lt;').replaceAll('>','&gt;'),localStorage:{getItem:()=>null},document:{documentElement:{classList:{toggle(){}}}},compactWord:()=>false});
 vm.runInContext(fs.readFileSync('web/display-tools.js','utf8'),c);const inline=fs.readFileSync('web/inline-editor.js','utf8');vm.runInContext(inline.slice(inline.indexOf('function inlineWordParts('),inline.indexOf('function renderEditableExample(')),c);vm.runInContext(fs.readFileSync('web/sense-gloss.js','utf8'),c);vm.runInContext(fs.readFileSync('web/paradigms.js','utf8').split('(()=>{')[0],c);return c;}
test('old underscore glosses open as one editable cell without altering any characters',()=>{
 const c=setup();for(const text of ['look_after','看_起来','_edge_','look__after','NOM_SG','neg#sub[POT]_meaning']){
  assert.deepEqual(Array.from(c.glossEditParts(text)),[text]);assert.equal(c.inlineWordLayout({form:'x',gloss:text}).columns,1);
 }
});
test('real morpheme and dot label boundaries still align around underscore text',()=>{
 const c=setup(),w={form:'x-y',gloss:'look_after.PST-PL'};assert.deepEqual(Array.from(c.glossEditParts(w.gloss)),['look_after','.','PST','-','PL']);const p=c.inlineWordLayout(w);assert.equal(p.form[2].column,p.gloss[4].column);assert.equal(c.glossEditParts('look_after-x',false)[0],'look_after');
});
test('underscores do not expose embedded registered tags, including scripts and grammatical brackets',()=>{
 const c=setup();for(const text of ['look_PST','PST_look','[look_PST]','look_neg#sub[POT]','neg#sub[POT]_look','看_neg#sub[POT]'])assert.doesNotMatch(c.richGloss(text),/grammar-label/,text);
 assert.match(c.richGloss('look_after.PST'),/grammar-label/);assert.match(c.richGloss('NOM_SG'),/grammar-label/);assert.doesNotMatch(c.richGloss('NOM_SG_extra'),/grammar-label/);
 assert.match(c.richGloss('look_neg#sub[POT]'),/look_neg<sub>POT<\/sub>/);
});
test('formatted copy preserves underscore spelling and styles only whole registered atoms',()=>{
 for(const value of ['look_PST','PST_look','look_neg#sub[POT]','neg#sub[POT]_look']){
  const runs=copy.runs(value,{PST:'past','neg#sub[POT]':'negative'});assert.ok(runs.every(r=>!r.smallCaps),value);assert.equal(runs.map(r=>r.text).join(''),value.replace(/#sub\[([^\]]*)\]/g,'$1'));
 }
 assert.equal(copy.runs('NOM_SG',{NOM_SG:'one tag'}).filter(r=>r.smallCaps).length,1);
 assert.equal(copy.runs('look_after.PST',{PST:'past'}).filter(r=>r.smallCaps).length,1);
});
test('paradigm templates compose underscore glosses and additions without flattening atoms',()=>{
 const c=setup();assert.equal(c.paradigmCompose('look_after','PST'),'look_after.PST');assert.equal(c.paradigmCompose('NOM_SG','NOM.SG'),'NOM_SG.NOM.SG');assert.equal(c.paradigmAddition('NOM_SG.NOM_SG'),'NOM_SG');
 for(const value of ['look-after','look=after','look<after>','look after'])assert.throws(()=>c.paradigmCompose(value,'PST'));
});
test('private-use source characters do not collide with script masking',()=>{
 const c=setup(),text='\ue0000\ue000_look_neg#sub[POT].PST';assert.match(c.richGloss(text),/\ue0000\ue000_look_neg<sub>POT<\/sub>/);assert.equal((c.richGloss(text).match(/grammar-label/g)||[]).length,1);
 const runs=copy.runs(text,{PST:'past'});assert.equal(runs.filter(r=>r.smallCaps).length,1);assert.equal(runs.map(r=>r.text).join(''),text.replace('#sub[POT]','POT'));
});
