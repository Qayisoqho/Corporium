const test=require('node:test'),assert=require('node:assert/strict'),fs=require('node:fs'),vm=require('node:vm');
const source=fs.readFileSync('web/paradigms.js','utf8');
function setup(){const c=vm.createContext({crypto:require('node:crypto')});vm.runInContext(fs.readFileSync('web/sense-gloss.js','utf8'),c);vm.runInContext(source.split('(()=>{')[0],c);return c;}
test('removing an unrelated sense does not change stable references or meaning metadata',()=>{
 const c=setup(),m={id:'meaning',base_sense_id:'second',gloss_mode:'inherit',gloss_addition:'ACC',notes:'keep'};
 assert.equal(c.paradigmDetachSense(m,{id:'first',short_gloss:'other'}),m);
});
test('removing the actual base freezes the composed gloss and preserves meaning identity',()=>{
 const c=setup(),m={id:'meaning',base_sense_id:'second',gloss_mode:'inherit',gloss_addition:'ACC',short_gloss:'',definition:'sense',notes:'keep'};
 const r=c.paradigmDetachSense(m,{id:'second',short_gloss:'1SG'});
 assert.equal(r.short_gloss,'1SG.ACC');assert.equal(r.base_sense_id,'');assert.equal(r.gloss_mode,undefined);assert.equal(r.gloss_addition,undefined);
 for(const k of ['id','definition','notes'])assert.equal(r[k],m[k]);assert.equal(m.base_sense_id,'second');
 const independent={...m,gloss_mode:'independent',short_gloss:'custom'};assert.equal(c.paradigmDetachSense(independent,{id:'second'}).short_gloss,'custom');
});
test('base sense numbering is rebuilt from current order while IDs stay unchanged',()=>{
 const c=setup(),rows=['first','second','third'].map(id=>({dataset:{id},querySelector:()=>({value:id})}));
 c.$=()=>({children:[{dataset:{id:'usage'},querySelector:()=>({children:rows})}]});c.id=()=>{throw Error('must not replace stable IDs');};
 const a=source.indexOf(' function baseSenses('),b=source.indexOf(' function tagSelect(',a);vm.runInContext(source.slice(a,b),c);
 assert.equal(c.baseSenses('usage')[1].label,'2. second');rows.shift();assert.equal(c.baseSenses('usage')[0].label,'1. second');assert.equal(c.baseSenses('usage')[0].id,'second');
});
