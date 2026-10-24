const test=require('node:test'),assert=require('node:assert/strict'),vm=require('node:vm'),fs=require('node:fs');
const source=fs.readFileSync('web/paradigms.js','utf8').replace(/\r\n/g,'\n');
function setup(){
 const c={crypto:require('node:crypto')};vm.createContext(c);vm.runInContext(source.split('(()=>{')[0],c);return c;
}
function table(title='变格',form='f'){
 return {title,rows:[{labels:['单数','宾格'],realizations:[{form_id:form,meanings:[{id:'m1'},{id:'m2'}]}]}]};
}
test('a detached referenced form is restored with its identity and metadata instead of merging homographs',()=>{
 const c=setup(),saved={id:'f',form:'namai',kind:'inflected',notes:'keep',features:['ACC'],pronunciation:'namaɪ',tags:[{type:'source',value:'field'}]};
 const result=c.paradigmPendingForm('','f',[{id:'homograph',form:'namai'}],saved);
 assert.equal(JSON.stringify(result),JSON.stringify(saved));assert.notEqual(result,saved);
 assert.equal(c.paradigmPendingForm('namai','f',[],saved).id,'f');
 assert.notEqual(c.paradigmPendingForm('different','f',[],saved).id,'f');
 assert.equal(c.paradigmPendingForm('','other',[],saved),null);
});
test('save preflight accepts registered forms and reports the exact broken table row without changing the draft',()=>{
 const c=setup(),body={variants:[{id:'f',form:'namai'}],paradigms:[table()]},before=JSON.stringify(body);
 c.validateParadigmForms(body);assert.equal(JSON.stringify(body),before);
 body.variants=[];const broken=JSON.stringify(body);
 assert.throws(()=>c.validateParadigmForms(body),/变格.*单数 · 宾格.*重新选择或填写/);
 assert.equal(JSON.stringify(body),broken);
 body.variants=[{id:'f',form:'namai'}];c.validateParadigmForms(body);
 body.variants[0].form=' ';assert.throws(()=>c.validateParadigmForms(body),/变格.*宾格.*词形已被清空/);
 assert.equal(body.variants[0].form,' ');
});
test('removal retains the complete draft and save registration restores it only once',()=>{
 const c=setup(),list={children:[]};let removed=0;
 c.detachedForms=new Map();c.readMorphForm=()=>({kind:'inflected',features:['ACC'],form_parts:[],pronunciation:'namaɪ'});c.readTags=()=>[{type:'source',value:'field'}];
 c.$=()=>list;
 c.addVariant=v=>{const button={onclick(){list.children=list.children.filter(r=>r!==row);removed++;}},row={dataset:{id:v.id},querySelector:s=>s==='.remove-variant'?button:s==='.variant-notes'?{value:'keep'}:{value:v.form}};list.children.push(row);list.lastElementChild=row;};
 const start=source.indexOf(' const addForm=addVariant;'),end=source.indexOf("\n\n $('paradigm-add')",start);
 vm.runInContext(source.slice(start,end),c);c.addVariant({id:'f',form:'namai'});
 list.lastElementChild.querySelector('.remove-variant').onclick({});assert.equal(removed,1);assert.equal(list.children.length,0);
 assert.equal(c.detachedForms.get('f').notes,'keep');assert.equal(c.detachedForms.get('f').features[0],'ACC');
 c.wsVariants=()=>list.children.map(r=>({id:r.dataset.id,label:r.querySelector('.variant-form').value}));c.options=()=>'';
 const registerStart=source.indexOf(' function registerPending('),registerEnd=source.indexOf(' function flushPending()',registerStart);
 vm.runInContext(source.slice(registerStart,registerEnd),c);
 const input={value:''},select={value:'f'},realization={querySelector:s=>s==='.paradigm-form'?select:input};
 c.registerPending(realization);c.registerPending(realization);
 assert.equal(list.children.length,1);assert.equal(list.children[0].dataset.id,'f');assert.equal(list.children[0].querySelector('.variant-form').value,'namai');
 assert.equal(c.detachedForms.has('f'),false);
});
test('the actual save pruning hook checks form references after empty new rows are pruned',()=>{
 const c=setup();c.pruneNewLexemeRows=b=>{b.variants=b.variants.filter(v=>v.form.trim());return b;};
 const start=source.indexOf(' const prune=pruneNewLexemeRows;'),end=source.indexOf(' // Keep a detached draft',start);
 vm.runInContext(source.slice(start,end),c);
 assert.throws(()=>c.pruneNewLexemeRows({variants:[{id:'f',form:''}],paradigms:[table()]},{}),/变格.*宾格/);
 const b={variants:[{id:'f',form:'namai'}],paradigms:[table()]};assert.equal(c.pruneNewLexemeRows(b,{}),b);
});
