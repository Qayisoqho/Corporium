const test=require('node:test'),assert=require('node:assert/strict'),fs=require('node:fs'),vm=require('node:vm');
const source=fs.readFileSync(require.resolve('../web/lexicon-extra.js'),'utf8');
function harness(mode){
 const nodes={},calls=[],old={token:'old',text_id:'text',ignore_symbols:'-',ignore_position:'edges',matches:[{unit_id:'strict'}],suggestions:[{candidate_id:'picked',unit_id:'relaxed'},{candidate_id:'left',unit_id:'left',default_selected:true}]};
 const remaining={...old,token:'fresh',matches:mode==='strict'?[]:old.matches,suggestions:mode==='strict'?old.suggestions:[old.suggestions[1]]};
 const c={Set,URLSearchParams,autoPlan:old,autoCandidateSelection:{selected:new Set(['picked'])},autoShown:100,autoBusy:false,autoSequence:3,autoLanguage:'ordos',refreshUndo:async()=>calls.push('undo'),refreshExampleViews:async()=>calls.push('views'),$:id=>nodes[id]??=( {scrollTop:10,querySelector:()=>null,querySelectorAll:()=>[],textContent:''}),api:async(path,b)=>{calls.push({path,b});return b?{count:1}:remaining;},autoPreviewRequest:()=> 'lexeme-auto-preview?scope=original',resetAutoPlan(){c.autoPlan=null;},drawAutoPlan(plan,previous,shown){c.autoPlan=plan;c.autoCandidateSelection=c.createAutoCandidateSelection(plan.suggestions,previous);c.drawn={plan,previous,shown};}};
 vm.createContext(c);vm.runInContext(source.slice(source.indexOf('function createAutoCandidateSelection('),source.indexOf('function renderAutoSuggestions(')),c);
 vm.runInContext(source.slice(source.indexOf('function lockAutoLinks('),source.indexOf("$('auto-link-apply').onclick")),c);return {c,nodes,calls,remaining};
}
for(const mode of ['strict','candidates'])test(mode+' automatically refreshes the plan, retains untouched choices and enables the other action',async()=>{
 const {c,nodes,calls,remaining}=harness(mode);await c.applyAutoLinks(mode);
 assert.equal(c.autoPlan,remaining);assert.equal(c.autoPlan.token,'fresh');assert.equal(c.autoBusy,false);assert.equal(c.drawn.shown,100);
 assert.equal(calls[0].b.mode,mode);assert.deepEqual([...calls[0].b.selected],['picked']);assert.ok(calls[1].path.startsWith('lexeme-auto-preview'));
 assert.equal(nodes['auto-link-apply'].disabled,mode==='strict');assert.equal(nodes['auto-candidate-apply'].disabled,mode!=='strict');
 assert.deepEqual([...c.autoCandidateSelection.selected],mode==='strict'?['picked']:[]);
 assert.ok(!c.autoCandidateSelection.selected.has('left'),'an intentionally unselected candidate stays unselected');
 assert.ok(calls.includes('undo'));assert.ok(calls.includes('views'));
});
test('busy actions cannot submit twice and stale candidates cannot be adopted after a failed refresh',async()=>{
 const {c,calls}=harness('strict');c.autoBusy=true;await c.applyAutoLinks('strict');assert.equal(calls.length,0);
 c.autoBusy=false;c.api=async(path,b)=>{if(b)return {count:1};throw Error('refresh failed');};await c.applyAutoLinks('strict');
 assert.equal(c.autoPlan,null);assert.equal(c.autoBusy,false);assert.match(c.$('auto-link-error').textContent,/已关联 1/);
});
