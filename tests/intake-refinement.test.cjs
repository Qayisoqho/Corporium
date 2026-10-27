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
