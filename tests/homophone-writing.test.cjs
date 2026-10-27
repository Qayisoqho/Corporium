const test=require('node:test'),assert=require('node:assert/strict'),fs=require('node:fs'),vm=require('node:vm');
function setup(){const s=fs.readFileSync('web/homophone-phonology.js','utf8'),c={entries:[],activeLanguage:'one',writing:'han',orthographyStyle:s=>s,esc:s=>String(s||'').replace(/[&<>"']/g,v=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[v])),richGloss:s=>s};c.$=()=>({value:c.writing});vm.createContext(c);vm.runInContext(s.slice(s.indexOf(' function item('),s.indexOf(' async function inspect(')),c);return c;}
test('tone rows show selected writings beside the tone, with no underlying form, IPA heading, gloss or slash separators',()=>{
 const c=setup(),r={identity:'m',form:'underlying',number:2,gloss:'gloss',writings:[{type_id:'han',text:'甲'},{type_id:'han',text:'乙'}]},types=[{id:'han',font:'TestFont'}];
 const html=c.tone({tone:{label:'55'},groups:[{reading:'ma55',items:[r,{...r,identity:'n',writings:[{type_id:'han',text:'丙'}]}]}]},types);
 assert.match(html,/<h4>55<\/h4><button/);assert.equal((html.match(/data-hp-item=/g)||[]).length,2);assert.match(html,/font-family:TestFont/);assert.doesNotMatch(html,/<h[1-6][^>]*>ma55|class="form"|class="gloss"| \/ /);
 const visible=html.replace(/<[^>]*>/g,'');assert.equal(visible,'55甲乙丙');assert.equal(c.entries[0].row.identity,'m');assert.equal(c.entries[0].reading,'ma55');
});
test('missing chosen writings do not fall back to underlying forms, and unselected placeholders remain inspectable',()=>{
 const c=setup(),row={form:'underlying',writings:[],gloss:'g'};assert.equal(c.item(row,{reading:'ma'},[],true),'');c.writing='';
 const html=c.item(row,{reading:'ma'},[],true);assert.match(html,/未填书写/);assert.doesNotMatch(html,/class="form"/);assert.equal(c.entries.length,1);
 assert.match(c.item(row,{reading:'ma'},[],false),/class="form"/); // Pending classification keeps its existing detailed view.
});

test('review records without the selected writing remain visible and inspectable without substituting the underlying form',()=>{
 const source=fs.readFileSync('web/homophones.js','utf8'),c={writing:'han',activeLanguage:'one',orthographyStyle:s=>s,esc:s=>String(s||''),richGloss:s=>s};c.$=()=>({value:c.writing});vm.createContext(c);vm.runInContext(source.slice(source.indexOf(' function entry('),source.indexOf(' function readPageSize(')),c);
 const row={identity:'m',form:'underlying',gloss:'meaning',writings:[],readings:[],sources:[],origin:'语素',reason:'缺少读音'};
 for(const writings of [[],[{type_id:'han',text:'  \t '}]]){
  const html=c.entry({...row,writings},[{id:'han',name:'汉字'}],true);assert.match(html,/class="homophone-entry"/);assert.match(html,/未填写所选书写/);assert.match(html,/meaning/);assert.match(html,/缺少读音/);assert.match(html,/data-homophone-morpheme="m"/);assert.doesNotMatch(html,/underlying/);
  assert.equal(c.entry({...row,writings},[],false),'');
 }
 c.writing='';assert.match(c.entry(row,[],true),/underlying/);
 c.writing='han';const written=c.entry({...row,writings:[{type_id:'han',text:'甲'}]},[{id:'han',name:'汉字',font:'Junicode'}],true);assert.match(written,/甲/);assert.doesNotMatch(written,/未填写所选书写/);
});
