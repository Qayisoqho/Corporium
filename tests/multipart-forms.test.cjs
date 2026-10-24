const test=require('node:test'),assert=require('node:assert/strict'),fs=require('node:fs'),vm=require('node:vm');
const {format,infer,reconcile}=require('../web/multipart-forms.js');
test('multipart editor keeps boundaries and each ordered part',()=>{
 const parts=[{text:'am',left:'',right:'-'},{text:'os',left:'-',right:'-'},{text:'em',left:'-',right:''}];
 assert.equal(format(parts),'am-…-os-…-em');
 assert.deepEqual(infer('display',{form_parts:parts}),['am-','-os-','-em']);
 assert.deepEqual(infer('we…la',{entry_type:'affix',affix_position:'circumfix'}),['we','la']);
 assert.deepEqual(infer('a…b',{entry_type:'root'}),[]);
});
test('compact paradigm edits update the same multipart draft without dropping parts',()=>{
 assert.deepEqual(reconcile('wu-…-lu',['we-','-la']),['wu-','-lu']);
 const same=['we-','-la'];assert.equal(reconcile('we-…-la',same),same);
 assert.throws(()=>reconcile('single',same),/保留各部分/);
 assert.throws(()=>reconcile('we-…',same),/保留各部分/);
});
test('overlapping multipart and atom choices cannot be bulk selected together',()=>{
 const code=fs.readFileSync(require.resolve('../web/lexicon-extra.js'),'utf8');
 const begin=code.indexOf('function createAutoCandidateSelection('),end=code.indexOf('\nfunction renderAutoSuggestions',begin);
 const context=vm.createContext({});vm.runInContext(code.slice(begin,end),context);
 const make=context.createAutoCandidateSelection;
 const rows=[{candidate_id:'left',unit_id:'group1',default_selected:true,conflicts:['right','atom']},
 {candidate_id:'right',unit_id:'group2',default_selected:true,conflicts:['left']},
 {candidate_id:'atom',unit_id:'atom',default_selected:true,conflicts:['left']},
 {candidate_id:'safe',unit_id:'safe',default_selected:true}];
 const s=make(rows);assert.deepEqual([...s.selected],['safe']);
 s.toggle('left',true);s.toggle('right',true);assert.deepEqual([...s.selected],['safe','right']);
 s.toggle('left',true);s.toggle('atom',true);assert.deepEqual([...s.selected],['safe','atom']);
 s.toggleAll(false);s.toggleAll(true);assert.deepEqual([...s.selected],['safe']);
});
