const test=require('node:test'),assert=require('node:assert/strict'),fs=require('node:fs'),vm=require('node:vm');
const source=fs.readFileSync('web/sentence-dictionary.js','utf8');
test('intake offers only this language’s root word classes and escapes names',async()=>{
 const calls=[],scope={posOptions:{},request:async path=>{calls.push(path);return [{kind:'pos',name:'Noun',parent_id:null},{kind:'pos',name:'Subtype',parent_id:'noun'},{kind:'grammar',name:'Other'},{kind:'pos',name:'A<B',parent_id:null}]},esc:s=>s.replaceAll('<','&lt;')};vm.createContext(scope);
 vm.runInContext(source.match(/ async function loadIntakeClasses[^\n]+/)[0],scope);await scope.loadIntakeClasses('current');
 assert.deepEqual(calls,['classes?language=current']);assert.match(scope.posOptions.innerHTML,/Noun/);assert.match(scope.posOptions.innerHTML,/A&lt;B/);assert.doesNotMatch(scope.posOptions.innerHTML,/Subtype|Other/);
});
function setup(){const calls=[],section={refreshCurrentExamples:async()=>{calls.push('examples')}},card={getBoundingClientRect:()=>({top:180}),closest:()=>section},scope={workspace:'dictionary',dictionarySelection:'entry',activeLanguage:'one',CSS:{escape:s=>s},document:{querySelector:()=>card},refreshDictionaryListOnly:async detail=>calls.push(['list',detail]),loadDictionary:async()=>calls.push('full'),window:{scrollBy:x=>calls.push(['scroll',x]),corporiumInvalidateViews:()=>calls.push('invalidate'),corporiumRefreshDictionaryCounts:async()=>calls.push('counts'),corporiumRefreshUndoState:async()=>calls.push('undo'),corporiumSentenceInspector:{refresh:async()=>calls.push('inspector')}}};vm.createContext(scope);vm.runInContext(source.slice(source.indexOf(' async function refreshSource('),source.indexOf(" $('intake-form').onsubmit")),scope);return {scope,calls,section};}
test('saving from a dictionary example refreshes its current evidence page without rebuilding the entry',async()=>{
 const {scope,calls}=setup();await scope.refreshSource({kind:'corpus',id:'one'});assert.ok(calls.includes('examples'));assert.ok(calls.includes('inspector'));assert.ok(calls.includes('counts'));assert.ok(!calls.includes('full'));assert.ok(calls.some(c=>Array.isArray(c)&&c[0]==='list'&&c[1]===false));assert.ok(calls.filter(c=>Array.isArray(c)&&c[0]==='scroll').every(c=>c[1].top===0&&c[1].behavior==='instant'));
});
test('a navigation during saving does not scroll the new workspace',async()=>{
 const {scope,calls,section}=setup();section.refreshCurrentExamples=async()=>{scope.workspace='library'};await scope.refreshSource({kind:'independent',id:'one'});assert.ok(!calls.some(c=>Array.isArray(c)&&c[0]==='scroll'));
});

test('choosing another entry while saving does not scroll the new entry',async()=>{const {scope,calls,section}=setup();section.refreshCurrentExamples=async()=>{scope.dictionarySelection='another'};await scope.refreshSource({kind:'corpus',id:'one'});assert.ok(!calls.some(c=>Array.isArray(c)&&c[0]==='scroll'));});
test('both sentence kinds refresh the current workspace inside the shared location guard',async()=>{
 for(const owner of ['corpus','library','survey','timeline','analysis','grammar'])for(const kind of ['corpus','independent']){
  const {scope,calls}=setup();scope.workspace=owner;scope.loadGrammar=async()=>calls.push(owner);
  scope.window.corporiumRefreshVisibleWorkspace=async()=>calls.push(owner);
  scope.window.corporiumPreserveExampleLocation=async(source,run)=>{calls.push(['anchor',source.kind,source.id]);return run();};
  await scope.refreshSource({kind,id:'sentence',word:3});
  assert.ok(calls.includes(owner),owner);assert.ok(calls.includes('inspector'));
  assert.deepEqual(calls.find(c=>Array.isArray(c)&&c[0]==='anchor'),['anchor',kind,'sentence']);
  assert.ok(!calls.some(c=>Array.isArray(c)&&c[0]==='scroll'));
 }
});

test('the compact class picker always reopens the full list while preserving free input',async()=>{
 const input={value:'custom',dispatchEvent:e=>events.push(e.type)},events=[],posOptions={value:'',innerHTML:''};
 const c=vm.createContext({posOptions,$:()=>input,Event:class{constructor(type){this.type=type;}}});
 vm.runInContext(source.split('\n').find(s=>s.startsWith(' posOptions.onchange=')),c);
 for(const name of ['N','V','N']){posOptions.value=name;posOptions.onchange();assert.equal(input.value,name);assert.equal(posOptions.value,'');}
 input.value='new class';posOptions.onchange();assert.equal(input.value,'new class');assert.deepEqual(events,['input','input','input']);
});
test('intake submits separate grammar additions only for native morpheme meanings',()=>{
 const values={'intake-mode':'new','intake-kind':'morpheme'},c=vm.createContext({$ :id=>({value:values[id]||''}),intake:{source:{kind:'corpus',id:'sentence'},target:null},intakeAddition:{},readGlossAddition:()=>({gloss_addition:'LOC',show_gloss_addition:false})});
 vm.runInContext(source.split('\n').find(s=>s.startsWith(' const intakeGrammarActive='))+source.split('\n').find(s=>s.startsWith(' function payload()')),c);
 assert.equal(c.payload().gloss_addition,'LOC');assert.equal(c.payload().show_gloss_addition,false);
 for(const mode of ['existing','variant']){values['intake-mode']=mode;assert.equal(c.payload().gloss_addition,undefined);}
 values['intake-mode']='sense';c.intake.target={target_kind:'morpheme'};assert.equal(c.payload().gloss_addition,'LOC');
 c.intake.target.target_kind='lexeme';assert.equal(c.payload().gloss_addition,undefined);
 values['intake-mode']='new';values['intake-kind']='lexeme';assert.equal(c.payload().gloss_addition,undefined);
});
