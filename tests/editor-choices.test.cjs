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

function remoteSetup(api){
 const c=setup(),elements={};
 const select={value:'',dataset:{},isConnected:true,options:[],add(o){this.options.push(o);}};
 Object.defineProperty(select,'selectedOptions',{get(){return this.options.filter(o=>o.value===this.value);}});
 Object.defineProperty(select,'innerHTML',{get(){return this.html;},set(value){this.html=value;this.options=[...value.matchAll(/<option value="([^"]*)"[^>]*>(.*?)<\/option>/g)].map(m=>({value:m[1],textContent:m[2]}));}});
 const status={hidden:false,querySelectorAll(){return [...(this.innerHTML||'').matchAll(/data-choice-page="([^"]*)"/g)].map(m=>({dataset:{choicePage:m[1]}}));}},query={value:'',hidden:true};
 elements['lexeme-language']={value:'ordos'};elements['lexeme-editor']={open:true};elements['lexeme-form']={querySelector(){return null;}};
 Object.assign(c,{$:id=>elements[id],api,setTimeout,clearTimeout,URLSearchParams,editingLexeme:{id:'owner'},lexemeDirty:false});
 c.morphEditorData={remote_choices:true,language_id:'ordos',entries:[{id:'chosen',headword:'selected',body:'{}'}]};
 return {c,elements,select,status,query};
}
const flush=async()=>{for(let i=0;i<8;i++)await Promise.resolve();};

test('remote choices keep the current reference while fetching bounded pages and never auto-select search matches',async()=>{
 const calls=[],{c,select,status,query}=remoteSetup(async path=>{calls.push(path);return {items:[{id:'match',headword:'match',body:{}}],total:245,page:Number(new URL('http://test/'+path).searchParams.get('page')),pages:5};});
 c.remoteLexemeChoices(select,query,status,'chosen','none');await flush();
 assert.equal(select.value,'chosen');assert.equal(select.options.length,3);assert.match(status.innerHTML,/245/);
 assert.match(calls[0],/exclude=owner/);assert.match(calls[0],/page=1/);
 query.value='match';query.oninput();await new Promise(r=>setTimeout(r,160));await flush();
 assert.equal(select.value,'chosen');assert.match(calls[1],/q=match/);assert.equal(c.lexemeDirty,false);
 assert.equal(c.morphEditorData.entries.length,1);
});

test('out-of-order searches and responses after closing cannot replace a newer choice list',async()=>{
 const requests=[],{c,select,status,query,elements}=remoteSetup(path=>new Promise(resolve=>requests.push({path,resolve})));
 const response=id=>({items:[{id,headword:id,body:{}}],total:60,page:1,pages:2});
 c.remoteLexemeChoices(select,query,status,'chosen','none');query.value='new';query.oninput();
 await new Promise(r=>setTimeout(r,160));requests[1].resolve(response('new'));await flush();
 assert.match(select.innerHTML,/value="new"/);const current=select.innerHTML;
 requests[0].resolve(response('old'));await flush();assert.equal(select.innerHTML,current);
 query.value='closed';query.oninput();await new Promise(r=>setTimeout(r,160));elements['lexeme-editor'].open=false;
 requests[2].resolve(response('closed'));await flush();assert.equal(select.innerHTML,current);
});

test('only selected reference drafts are loaded, and a foreign-language response is rejected',async()=>{
 const calls=[],{c}=remoteSetup(async path=>{calls.push(path);return {id:path.includes('foreign')?'foreign':'new',language_id:path.includes('foreign')?'other':'ordos',headword:'new',body:{usages:[{id:'u'}],variants:[{id:'f'}]}};});
 const catalog=c.morphEditorData;
 await c.morphChoiceTarget(catalog,'chosen');assert.equal(calls.length,0);
 const record=await c.morphChoiceTarget(catalog,'new');assert.equal(JSON.parse(record.body).variants[0].id,'f');
 await c.morphChoiceTarget(catalog,'new');assert.equal(calls.length,1);assert.equal(catalog.entries.length,2);
 await assert.rejects(c.morphChoiceTarget(catalog,'foreign'));
 assert.equal(catalog.entries.length,2);
});

test('saving waits for reference fields and reports a failed reference load',async()=>{
 const {c,elements}=remoteSetup(async()=>{}),catalog=c.morphEditorData;
 let resolve;const pending=new Promise(r=>resolve=r).finally(()=>catalog.pending.delete(pending));catalog.pending=new Map([[pending,()=>true]]);
 let finished=false;const waiting=c.waitForMorphChoices().then(()=>finished=true);await flush();assert.equal(finished,false);
 resolve();await waiting;assert.equal(finished,true);
 elements['lexeme-form'].querySelector=()=>({dataset:{morphChoiceError:'reference could not load'}});
 await assert.rejects(c.waitForMorphChoices(),/reference could not load/);
});

test('obsolete reference work does not delay saving a newer selection or removed row',async()=>{
 const {c}=remoteSetup(async()=>{});c.morphEditorData.pending=new Map([[new Promise(()=>{}),()=>false]]);
 await c.waitForMorphChoices();
});
