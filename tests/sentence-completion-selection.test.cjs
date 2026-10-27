const test=require('node:test'),assert=require('node:assert/strict'),fs=require('node:fs'),vm=require('node:vm');
const source=fs.readFileSync('web/sentence-dictionary.js','utf8');
function setup(kind,rows,analyses=[]){
 const controls={},calls=[];
 controls['sentence-gloss-rows']={selects:[],set innerHTML(value){this.html=value;this.selects=Array.from(value.matchAll(/<select data-gloss-row="(\d+)"/g),m=>({dataset:{glossRow:m[1]},value:''}));},querySelectorAll(){return this.selects;}};
 const $=id=>controls[id]??(controls[id]={});
 const context=vm.createContext({$,plan:{data:{kind,language_id:'ordos',rows,analyses,skipped:[]}},busy:false,esc:String,rich:String,richGloss:String,fontStyle:()=>'',request:(...args)=>calls.push(args)});
 vm.runInContext(source.slice(source.indexOf(' function syncCompletion('),source.indexOf(' async function previewCompletion(')),context);
 context.drawCompletion();return {controls,calls,context};
}
const candidate=(id,form)=>({id,headword:form,matched_form:form,gloss:'说',target_kind:'lexeme',sense_label:'1.1',relaxed:true,reason:'忽略引用标记，确认后填入'});
test('unique marker candidates preselect and enable confirmation for both saved sources',()=>{
 for(const kind of ['corpus','independent'])for(const form of ['say-','=say','say.','s-ay']){
  const {controls,calls}=setup(kind,[{word:0,key:'@word',form:'say',automatic:true,candidates:[candidate('unique',form)]}]);
  assert.equal(controls['sentence-gloss-rows'].selects[0].value,'unique');
  assert.equal(controls['sentence-gloss-apply'].disabled,false);
  assert.match(controls['sentence-gloss-apply'].textContent,/1/);
  assert.equal(calls.length,0);
 }
});
test('whole-word analysis requires an explicit choice and excludes morpheme choices in the same slot',()=>{
 const rows=[{word:0,key:'@word',form:'homeka',automatic:true,candidates:[candidate('word','homeka')]},
             {word:1,key:'@word',form:'other',automatic:true,candidates:[candidate('other','other')]}];
 const analyses=[{word:0,key:'@analysis',form:'homeka',automatic:false,candidates:[{id:'memory',form:'home-ka',gloss:'house-LOC',count:2,sources:[{kind:'corpus',word:0}]}]}];
 const {controls,context,calls}=setup('corpus',rows,analyses),selects=controls['sentence-gloss-rows'].selects;
 assert.equal(selects[0].value,'');assert.equal(selects[1].value,'word');assert.equal(selects[2].value,'other');
 selects[0].value='memory';selects[0].onchange();assert.equal(selects[1].value,'');assert.equal(selects[2].value,'other');
 selects[1].value='word';selects[1].onchange();assert.equal(selects[0].value,'');assert.equal(selects[2].value,'other');
 assert.match(controls['sentence-gloss-rows'].html,/home-ka — house-LOC/);assert.equal(calls.length,0);
});
test('multiple matching meanings stay unselected until the user chooses',()=>{
 for(const kind of ['corpus','independent']){
  const {controls,calls}=setup(kind,[{word:0,key:'@word',form:'kele',automatic:false,candidates:[candidate('noun','kele'),candidate('verb','kele-')]}]);
  const select=controls['sentence-gloss-rows'].selects[0];
  assert.equal(select.value,'');assert.equal(controls['sentence-gloss-apply'].disabled,true);
  select.value='verb';select.onchange();assert.equal(controls['sentence-gloss-apply'].disabled,false);
  assert.equal(calls.length,0);
 }
});
