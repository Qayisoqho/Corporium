const test=require('node:test'),assert=require('node:assert/strict'),fs=require('node:fs'),vm=require('node:vm');
const source=fs.readFileSync('web/inline-editor.js','utf8'),ctx=vm.createContext({});
vm.runInContext(source.slice(source.indexOf('function inlineRemove('),source.indexOf("document.addEventListener('click',async e=>{",source.indexOf('function inlineRemove('))),ctx);
test('merge keeps the surviving identity and retains removed endpoint evidence for backend review',()=>{
 const relation={id:'r',source:{word_id:'right',snapshot:'go'},base:{word_id:'left',snapshot:'go'}};
 const d={words:[{id:'slot-a'},{id:'slot-b'}],body:{words:[{form:'go',gloss:'go',redup_id:'left'},{form:'go',gloss:'RED',redup_id:'right'}],reduplications:[relation]},cells:[]};
 ctx.inlineMerge(d,0);assert.equal(d.body.words[0].redup_id,'left');assert.equal(d.body.reduplications[0],relation);assert.equal(relation.source.word_id,'right');assert.equal(d.body.words[0].form,'gogo');
});
const partsContext=vm.createContext({});const display=fs.readFileSync('web/display-tools.js','utf8');
vm.runInContext(display.slice(display.indexOf('function glossEditParts('),display.indexOf('function lexemeLabel(')),partsContext);
test('tilde creates editable matching form and gloss pieces without splitting bracketed labels or infixes',()=>{
 assert.equal(JSON.stringify(partsContext.glossEditParts('je~jepasu',false)),JSON.stringify(['je','~','jepasu']));
 assert.equal(JSON.stringify(partsContext.glossEditParts('RED~go',true)),JSON.stringify(['RED','~','go']));
 assert.equal(JSON.stringify(partsContext.glossEditParts('b<um>i~bili',false)),JSON.stringify(['b<um>i','~','bili']));
 assert.equal(JSON.stringify(partsContext.glossEditParts('[a~b]~go',true)),JSON.stringify(['[a~b]','~','go']));
});

test('shared relation summary preserves review and candidate information in read-only analysis cards',()=>{
 const js=fs.readFileSync('web/reduplication.js','utf8');
 const c=vm.createContext({esc:s=>s.replaceAll('<','&lt;').replaceAll('"','&quot;')});
 vm.runInContext(js.slice(js.indexOf(' const kinds='),js.indexOf(' let state=')),c);
 vm.runInContext(js.slice(js.indexOf(' function summary('),js.indexOf(' window.CorporiumReduplication=')),c);
 const body={reduplication_info:{relations:[{source:{form:'<je>'},base:{form:'jepasu'},type:'partial',review:true}],candidates:[{}]}};
 const html=c.summary(body,false);assert.match(html,/重叠关系 1 · 待核对/);assert.match(html,/&lt;je> → jepasu/);assert.match(html,/~ 候选 1/);assert.doesNotMatch(html,/<button/);
 assert.match(c.summary(body),/data-redup-open/);assert.equal(c.summary({}), '');
 body.reduplication_info.relations[0].type='modified';assert.match(c.summary(body,false),/变形重叠/);
});
