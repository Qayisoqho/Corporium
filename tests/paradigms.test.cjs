const test=require('node:test'),assert=require('node:assert/strict'),vm=require('node:vm'),fs=require('node:fs'),crypto=require('node:crypto');
function setup(){const c={crypto,esc:v=>String(v??'').replace(/[&<>"']/g,v=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[v])),richGloss:v=>String(v).replaceAll('<','&lt;'),usageLabel:u=>u.pos||''};vm.createContext(c);vm.runInContext(fs.readFileSync('web/sense-gloss.js','utf8'),c);vm.runInContext(fs.readFileSync('web/paradigms.js','utf8').split('(()=>{')[0],c);return c;}
function body(){return {usages:[{id:'u',pos:'V',senses:[{id:'base',short_gloss:'go'}]}],variants:[{id:'past',form:'went'},{id:'part',form:'gone'}],paradigms:[{id:'t',title:'Verb',usage_id:'u',dimensions:['Tense','Number','Person'],rows:[{id:'r',labels:['Past','Any','Any'],state:'filled',realizations:[{id:'f',form_id:'past',meanings:[{id:'m',short_gloss:'go.PST',definition:'past'},{id:'m2',short_gloss:'go.PST',definition:'other'}]}]},{id:'missing',labels:['X','X','X'],state:'missing',realizations:[]},{id:'empty',labels:['Y','Y','Y'],state:'unfilled',realizations:[]}]}]};}
test('manual pickers keep ambiguous form meanings distinct and filter by concrete form',()=>{const c=setup(),b=body(),before=JSON.stringify(b);assert.deepEqual(Array.from(c.paradigmUsages(b,'past')[0].senses,s=>s.id),['base','m','m2']);assert.deepEqual(Array.from(c.paradigmUsages(b,'part')[0].senses,s=>s.id),['base']);assert.deepEqual(Array.from(c.paradigmUsages(b,'')[0].senses,s=>s.id),['base']);assert.equal(c.paradigmUsages(b)[0].senses[1].paradigm_form_id,'past');assert.equal(JSON.stringify(b),before);});
test('a template produces fresh identities and copies layout without meanings or forms',()=>{const c=setup(),t=body().paradigms[0],a=c.paradigmFromTemplate(t),b=c.paradigmFromTemplate(t);assert.notEqual(a.id,b.id);assert.equal(a.template_id,t.id);assert.notEqual(a.rows[0].id,b.rows[0].id);assert.equal(a.rows.every(r=>r.state==='unfilled'&&r.realizations.length===0),true);assert.equal(a.dimensions.length,3);a.dimensions[0]='Changed';assert.equal(t.dimensions[0],'Tense');a.rows[0].labels[0]='Changed';assert.equal(t.rows[0].labels[0],'Past');});
test('reading table retains meaning order, missing states, labels and safe text',()=>{const c=setup(),b=body();b.paradigms[0].title='<unsafe>';b.variants[0].form='<word>';const html=c.paradigmView({language_id:'x',body:b});assert.match(html,/&lt;unsafe&gt;/);assert.match(html,/&lt;word&gt;/);assert.match(html,/rowspan="2"/);assert.match(html,/无此形式/);assert.match(html,/未填写/);assert.ok(html.indexOf('past</td>')<html.indexOf('other</td>'));assert.equal(c.paradigmView({body:{}}),'');});
test('pending forms reuse stable records and refuse to guess among homographs',()=>{
 const c=setup(),forms=[{id:'a',form:'gone'},{id:'b',form:'gone'},{id:'past',form:'went'}];
 assert.equal(c.paradigmPendingForm(' gone ','b',forms).id,'b');
 assert.equal(c.paradigmPendingForm('went','',forms).id,'past');
 assert.throws(()=>c.paradigmPendingForm('gone','',forms),/同形形式有多个/);
 assert.equal(c.paradigmPendingForm('  ','past',forms),null);
 const fresh=c.paradigmPendingForm(' going ','',forms);assert.equal(fresh.form,'going');assert.equal(fresh.kind,'inflected');assert.ok(fresh.id);
 assert.equal(c.paradigmPendingForm('going','',[...forms,fresh]).id,fresh.id);
 assert.equal(forms.length,3);
});
test('composed form glosses share one projection for pickers and the reading table',()=>{
 const c=setup(),b=body(),m=b.paradigms[0].rows[0].realizations[0].meanings[0];
 m.base_sense_id='base';m.gloss_mode='inherit';m.gloss_addition='PST';m.short_gloss='stale';
 const before=JSON.stringify(b);assert.equal(c.paradigmUsages(b,'past')[0].senses[1].short_gloss,'go.PST');
 assert.match(c.paradigmView({language_id:'x',body:b}),/go.PST/);assert.equal(JSON.stringify(b),before);
 b.usages[0].senses[0].short_gloss='leave';assert.equal(c.paradigmUsages(b)[0].senses[1].short_gloss,'leave.PST');
});
test('composition deduplicates complete atoms and preserves scope and decorations',()=>{
 const c=setup();assert.equal(c.paradigmCompose('1SG','NOM'),'1SG.NOM');assert.equal(c.paradigmCompose('go.NOM','nom.SG.NOM'),'go.NOM.SG');assert.equal(c.paradigmCompose('1SG','NOM.SG.NOM'),'1SG.NOM');
 assert.equal(c.paradigmCompose('1#sub[POT]','ACC'),'1#sub[POT].ACC');assert.equal(c.paradigmCompose('go-PST',''),'go-PST');
 for(const [base,extra] of [['','NOM'],['go-PST','NOM'],['1SG','ACC..SG'],['1SG','ACC-SG'],['1SG','ACC GEN']])assert.throws(()=>c.paradigmCompose(base,extra));
});
test('template snapshots keep row presets without capturing base-sense identities',()=>{
 const c=setup(),t=body().paradigms[0];t.default_base_sense_id='base';t.rows[0].gloss_addition='NOM';
 const copy=c.paradigmFromTemplate(t);assert.equal(copy.rows[0].gloss_addition,'NOM');assert.equal(copy.default_base_sense_id,undefined);
 copy.rows[0].gloss_addition='ACC';assert.equal(t.rows[0].gloss_addition,'NOM');
});
test('digit-final glosses append their next label directly in senses and tables',()=>{
 const c=setup();assert.equal(c.paradigmCompose('pron.3','sg.dat'),'pron.3sg.dat');assert.equal(c.senseGloss({short_gloss:'pron.3',gloss_addition:'SG.DAT'}),'pron.3SG.DAT');
 assert.equal(c.paradigmCompose('1SG','NOM'),'1SG.NOM');assert.equal(c.paradigmCompose('3#sub[POT]','SG'),'3#sub[POT].SG');
 assert.equal(c.paradigmCompose(c.senseGloss({short_gloss:'pron.3',gloss_addition:'SG'}),'SG.DAT'),'pron.3SG.DAT');
});
test('blank forms retain their labels in the reading table and are absent from sense pickers',()=>{
 const c=setup(),b=body();b.paradigms[0].rows[0].realizations[0].form_id='';b.variants=[];
 c.validateParadigmForms(b);assert.deepEqual(Array.from(c.paradigmUsages(b)[0].senses,s=>s.id),['base']);
 const html=c.paradigmView({body:b});assert.match(html,/go.PST/);assert.doesNotMatch(html,/形式已不存在/);assert.doesNotMatch(html,/data-morph-form=""/);
});
test('an all-empty table can be kept or removed and cancellation preserves the entire proposal',async()=>{
 const c=setup(),b=body();b.paradigms[0].rows[0].realizations[0].form_id='';b.variants=[];
 const before=JSON.stringify(b);assert.equal(c.emptyParadigmTables(b).length,1);
 assert.equal(await c.prepareEmptyParadigms(b,async()=>null),false);assert.equal(JSON.stringify(b),before);
 assert.equal(await c.prepareEmptyParadigms(b,async()=> 'keep'),true);assert.equal(JSON.stringify(b),before);
 assert.equal(await c.prepareEmptyParadigms(b,async()=> 'remove'),true);assert.equal(b.paradigms.length,0);
 const filled=body();assert.equal(await c.prepareEmptyParadigms(filled,async()=>{throw Error('must not prompt for filled table');}),true);
});
