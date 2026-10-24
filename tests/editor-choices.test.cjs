const test=require('node:test'),assert=require('node:assert/strict'),vm=require('node:vm'),fs=require('node:fs');
const source=fs.readFileSync('web/morphology.js','utf8');
function setup(){const c={lexemePlainLabel:x=>x.headword+(x.body.homonym_number?'_'+x.body.homonym_number:''),esc:s=>String(s??'').replace(/[&<>"]/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;'}[c])),Option:class{constructor(text,value){this.textContent=text;this.value=value;}}};vm.createContext(c);vm.runInContext(source.slice(source.indexOf('const lexemeChoiceIndexes'),source.indexOf('function fillMorphEntry')),c);return c;}
test('5000 reference candidates stay in memory, expose only 50 matches plus the current selection, and search the complete catalog',()=>{
 const c=setup(),entries=Array.from({length:5000},(_,i)=>({id:String(i),headword:'word-'+String(i).padStart(4,'0'),body:JSON.stringify({homonym_number:i===4999?2:null})})),rows=c.lexemeChoiceRows(entries);
 assert.equal(c.lexemeChoiceRows(entries),rows);assert.equal(rows.length,5000);assert.equal(rows.at(-1).label,'word-4999_2');
 const all=c.boundedLexemeChoices(rows,'4999');assert.equal(all.items.length,51);assert.equal(all.items[0].id,'4999');assert.equal(all.total,5000);
 const found=c.boundedLexemeChoices(rows,'4999','WORD-4998');assert.deepEqual(Array.from(found.items,r=>r.id),['4999','4998']);assert.equal(found.total,1);
 assert.equal(c.boundedLexemeChoices(rows,'','missing').items.length,0);assert.equal(rows.length,5000);
 assert.notEqual(c.lexemeChoiceRows([...entries]),rows); // A refreshed revision gets a fresh index.
 const ids=new Set();for(let p=1;p<=100;p++){const batch=c.boundedLexemeChoices(rows,'','',50,p);assert.equal(batch.items.length,50);for(const r of batch.items)ids.add(r.id);}assert.equal(ids.size,5000);
 assert.equal(c.boundedLexemeChoices(rows,'','',50,101).page,100);
});
test('rendering searches keeps selected references even if unavailable, and does not silently select a new match',()=>{
 const c=setup(),rows=[{id:'one',label:'<one>'},{id:'two',label:'two'}],select={selectedOptions:[{value:'missing',textContent:'原来的关联'}],add(o){this.extra=o;},value:'missing'},status={};
 c.fillLexemeChoices(select,rows,'missing','two','不关联',status);assert.equal(select.value,'missing');assert.equal(select.extra.textContent,'原来的关联');assert.equal(select.extra.value,'missing');assert.equal(status.hidden,true);
 c.fillLexemeChoices(select,rows,'','','不关联',status);assert.equal(select.value,'');assert.match(select.innerHTML,/&lt;one&gt;/);
});
