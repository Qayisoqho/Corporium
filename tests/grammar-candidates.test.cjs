const test=require('node:test'),assert=require('node:assert/strict'),fs=require('node:fs'),vm=require('node:vm');
const source=fs.readFileSync('web/grammar-candidates.js','utf8');
function helpers(){const c={};vm.createContext(c);vm.runInContext(source.slice(source.indexOf('function grammarCandidateSelection'),source.indexOf('function drawGrammarCandidates')),c);return c;}
test('candidate batches reject mixed languages, empty and oversized selections',()=>{const c=helpers();assert.throws(()=>c.grammarCandidateSelection([],[]),/勾选/);assert.throws(()=>c.grammarCandidateSelection([{language_id:'a'},{language_id:'b'}],[0,1]),/同一种语言/);assert.throws(()=>c.grammarCandidateSelection(Array(201).fill({language_id:'a'}),Array.from({length:201},(_,i)=>i)),/200/);assert.equal(c.grammarCandidateSelection([{symbol:'NOM',language_id:'a'}],[0])[0].symbol,'NOM');});
test('batch drafts coalesce case variants, prefill suggestions and keep spelling and aliases',()=>{const c=helpers();const rows=c.grammarRegistrationRows([{symbol:'nom',reference:{description:'主格',category:'格'}},{symbol:'NOM',reference:{description:'duplicate'}},{symbol:'X',aliases:['Y']}]);assert.equal(JSON.stringify(rows),JSON.stringify([{symbol:'nom',description:'主格',category:'格',aliases:[]},{symbol:'X',description:'',category:'',aliases:['Y']}]));});
test('only registered tags and aliases receive small caps; normal English and other languages retain text',()=>{
 const c={activeLanguage:'a',languageList:[{id:'a',metadata:JSON.stringify({glossary:{NOM:'主格',Nominative:'主格',sg:'单数'}})},{id:'b',metadata:'{}'}],esc:s=>String(s??'').replaceAll('&','&amp;').replaceAll('<','&lt;').replaceAll('>','&gt;'),document:{documentElement:{classList:{toggle(){}}}},localStorage:{getItem(){}}};vm.createContext(c);vm.runInContext(fs.readFileSync('web/display-tools.js','utf8'),c);
 for(const value of ['NOM','nom','Nom','Nominative','nominative'])assert.match(c.richGloss(value),/class="grammar-label"/);
 assert.equal((c.richGloss('NOM~word.SG').match(/class="grammar-label"/g)||[]).length,2);
 assert.match(c.richGloss('NOM~word.SG'),/<\/span>~word\./);
 for(const value of ['house','come.out','all','house[house]','1go','NOMINAL'])assert.doesNotMatch(c.richGloss(value),/grammar-label/);
 assert.doesNotMatch(c.richGloss('NOM','b'),/grammar-label/);
 c.languageList[1].metadata=JSON.stringify({glossary:{nom:'主格'}});assert.match(c.richGloss('NOM','b'),/grammar-label/);
 c.languageList[1].metadata=JSON.stringify({glossary:{ALL:'向格'}});assert.equal(c.richGloss('all','b'),'all');assert.match(c.richGloss('ALL','b'),/grammar-label/);
 c.languageList[1].metadata=JSON.stringify({glossary:{all:'旧小写标签'}});assert.match(c.richGloss('all','b'),/grammar-label/);
 assert.match(fs.readFileSync('web/style.css','utf8'),/\.grammar-label\{[^}]*font-variant-caps:all-small-caps/);
});
