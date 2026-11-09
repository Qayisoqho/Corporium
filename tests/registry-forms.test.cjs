const test=require('node:test'),assert=require('node:assert/strict'),fs=require('node:fs'),vm=require('node:vm');
const source=fs.readFileSync('web/word-structure.js','utf8');
function readingPresentation(){
 const text=fs.readFileSync('web/morphemes.js','utf8'),c=vm.createContext({});
 vm.runInContext(text.slice(text.indexOf('function componentRegistryPresentation('),text.indexOf('/* Morphemes are language-local')),c);
 return (component,link)=>JSON.parse(JSON.stringify(c.componentRegistryPresentation(component,link)));
}
test('reading shares the known linked base label, while a distinct component gloss stays visible',()=>{
 const present=readingPresentation(),link={morpheme:{id:'linked',form:'a\u0301',body:{gloss:'mother'}}};
 assert.deepEqual(present({form:'á',gloss:'mother'},link),{inline:true,sameGloss:true});
 assert.deepEqual(present({form:'á',gloss:'elder'},link),{inline:true,sameGloss:false});
 const numbered={...link,morpheme:{...link.morpheme,display_number:2}};
 assert.deepEqual(present({form:'á',gloss:'mother'},numbered),{inline:true,sameGloss:true});
 assert.equal(numbered.morpheme.display_number,2,'sharing the label must retain the linked identity number');
 assert.deepEqual(present({form:'local',gloss:'mother'},link),{inline:false,sameGloss:false});
 assert.deepEqual(present({form:'Á',gloss:'mother'},link),{inline:false,sameGloss:false});
 assert.equal(link.morpheme.form,'a\u0301','presentation must not normalize stored research text');
});
test('reading never merges a selected variant, stale source, or unassigned component into a base label',()=>{
 const present=readingPresentation(),component={form:'root',gloss:'meaning'},morpheme={id:'linked',form:'root',body:{gloss:'meaning'}};
 for(const link of [null,{morpheme,form_id:'explicit-variant'},{morpheme,source_missing:true}])assert.deepEqual(present(component,link),{inline:false,sameGloss:false});
 assert.deepEqual(present({form:'',gloss:''},{morpheme:{form:'',body:{gloss:''}}}),{inline:false,sameGloss:false});
});
test('explicit variant identity selects its own spelling and pronunciation, while an absent reading inherits the base',()=>{
 const c=vm.createContext({esc:s=>String(s).replaceAll('"','&quot;').replaceAll('<','&lt;')});
 vm.runInContext(source.slice(source.indexOf('function wsRegistryRealization'),source.indexOf('function wsSetRegistryRecord')),c);
 const m={form:'n',body:{gloss:'GEN',readings:['n'],variants:[{id:'a',form:'ne',pronunciation:'nɛ',conditions:''},{id:'b',form:'ne',pronunciation:'ni'},{id:'c',form:'nu'}]}};
 const value=id=>JSON.parse(JSON.stringify(c.wsRegistryRealization(m,id)));
 assert.deepEqual(value(''),{form:'n',readings:['n'],gloss:'GEN'});
 assert.deepEqual(value('a'),{form:'ne',readings:['nɛ'],gloss:'GEN'});
 assert.deepEqual(value('b'),{form:'ne',readings:['ni'],gloss:'GEN'});
 assert.deepEqual(value('c'),{form:'nu',readings:['n'],gloss:'GEN'});
 assert.throws(()=>value('deleted'),/已不存在/);
 const html=c.wsRegistryFormOptions(m);assert.match(html,/value="a">变体 1/);assert.match(html,/value="b">变体 2/);assert.match(html,/基本形式/);
 assert.match(c.wsRegistryFormOptions({form:'<x>',body:{variants:[{id:'"x',form:'<bad>',conditions:'<script>'}]}}),/&quot;x/);
});
