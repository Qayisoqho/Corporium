const test=require('node:test'),assert=require('node:assert/strict'),fs=require('node:fs'),vm=require('node:vm');
const source=fs.readFileSync(require.resolve('../web/lexicon-extra.js'),'utf8');
const context={};vm.createContext(context);vm.runInContext(source.slice(source.indexOf('function createAutoCandidateSelection('),source.indexOf('function renderAutoSuggestions(')),context);
const row=(candidate_id,unit_id=candidate_id)=>({candidate_id,unit_id});
test('select all includes candidates beyond the lazy display batch and clears them together',()=>{
 const rows=Array.from({length:75},(_,i)=>row('candidate-'+i)),s=context.createAutoCandidateSelection(rows);
 assert.equal(s.state().count,0);s.toggleAll(true);assert.equal(s.state().count,75);assert.ok(s.selected.has('candidate-74'));assert.equal(s.state().checked,true);
 s.toggle('candidate-70',false);assert.equal(s.state().indeterminate,true);s.toggleAll(false);assert.equal(s.state().count,0);assert.equal(s.state().indeterminate,false);
});
test('bulk selection skips competing targets without guessing and retains a manual choice',()=>{
 const s=context.createAutoCandidateSelection([row('single'),row('a','same'),row('b','same')]);
 s.toggleAll(true);assert.deepEqual([...s.selected],['single']);assert.equal(s.state().ambiguous,1);
 s.toggle('b',true);assert.equal(s.state().ambiguous,0);s.toggleAll(true);assert.deepEqual([...s.selected],['single','b']);
 s.toggle('a',true);assert.ok(!s.selected.has('b'));assert.ok(s.selected.has('a'));s.toggleAll(false);assert.equal(s.selected.size,0);
});
test('a new preview starts unselected and cannot accept stale candidate identities',()=>{
 const old=context.createAutoCandidateSelection([row('old')]);old.toggleAll(true);const fresh=context.createAutoCandidateSelection([row('new')]);fresh.toggle('old',true);assert.equal(fresh.selected.size,0);assert.equal(old.selected.size,1);
});
test('unique morpheme defaults include undisplayed rows but competing choices remain manual',()=>{
 const rows=Array.from({length:75},(_,i)=>({...row('m-'+i),default_selected:true}));
 rows.push({...row('a','same'),default_selected:true},{...row('b','same'),default_selected:true},row('word'));
 const s=context.createAutoCandidateSelection(rows);assert.equal(s.selected.size,75);assert.ok(s.selected.has('m-74'));
 assert.ok(!s.selected.has('a'));assert.ok(!s.selected.has('b'));assert.ok(!s.selected.has('word'));assert.equal(s.state().ambiguous,1);
 s.toggle('m-74',false);assert.equal(s.selected.size,74);s.toggle('b',true);assert.ok(s.selected.has('b'));s.toggleAll(false);assert.equal(s.selected.size,0);
});
