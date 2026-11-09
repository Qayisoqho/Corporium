const test=require('node:test'),assert=require('node:assert/strict'),fs=require('node:fs'),vm=require('node:vm');
const source=fs.readFileSync('web/word-structure.js','utf8');
const esc=value=>String(value??'').replace(/&/g,'&amp;').replace(/</g,'&lt;').replace(/"/g,'&quot;');
function referenceHarness(){
 const listeners={},observed=[],form={querySelectorAll:s=>s==='.ws-usage'?[scope]:[reference],addEventListener:(type,fn)=>listeners['form:'+type]=fn};
 const scope={value:'u2',matches:s=>s==='.ws-usage'},reference={value:'v2',matches:s=>s==='.ws-variant',closest:()=>part},part={};
 const usages={children:[['u1','Noun'],['u2','Verb']].map(([id,value])=>({dataset:{id},querySelector:()=>({value})})),addEventListener:(type,fn)=>listeners['usages:'+type]=fn};
 const variants={children:[['v1','aduu'],['v2','aduun']].map(([id,value])=>({dataset:{id},querySelector:()=>({value})})),addEventListener:(type,fn)=>listeners['variants:'+type]=fn};
 const nodes={'lexeme-form':form,'lexeme-usages':usages,'lexeme-variants':variants};
 const c=vm.createContext({esc,$:id=>nodes[id],wsUi:(zh,en)=>en,wsRefreshPart:row=>assert.equal(row,part),MutationObserver:class{constructor(callback){this.callback=callback;}observe(node){observed.push({callback:this.callback,node});}}});
 vm.runInContext(source.slice(source.indexOf('const wsOptions='),source.indexOf('function wsMoveButtons(')),c);
 vm.runInContext(source.slice(source.indexOf('function wsUsages('),source.indexOf('function wsWritings(')),c);
 return {c,listeners,observed,usages,variants,scope,reference};
}
test('a relocated membership refreshes its form reference from the stable editor form',()=>{
 const h=referenceHarness();h.variants.children.push({dataset:{id:'v3'},querySelector:()=>({value:'new unsaved form'})});
 h.listeners['form:focusin']({target:h.reference});
 assert.match(h.reference.innerHTML,/value="v3"[^>]*>new unsaved form/);
 assert.match(h.reference.innerHTML,/value="v2" selected>aduun/);
 assert.equal(h.reference.value,'v2');
});
test('renaming a local form updates labels without changing reference identity',()=>{
 const h=referenceHarness();h.variants.children.reverse();h.variants.children[0].querySelector=()=>({value:'edited genitive'});
 h.listeners['variants:input']();assert.match(h.reference.innerHTML,/value="v2" selected>edited genitive/);
 assert.equal(h.reference.value,'v2');
});
test('deleting a form keeps an explicit missing identity rather than selecting another row',()=>{
 const h=referenceHarness();h.variants.children=h.variants.children.filter(r=>r.dataset.id!=='v2');
 h.observed.find(o=>o.node===h.variants).callback();
 assert.match(h.reference.innerHTML,/selected value="v2"/);assert.equal(h.reference.value,'v2');
 assert.doesNotMatch(h.reference.innerHTML,/value="v1" selected/);
});
test('POS scope options also refresh after memberships leave the analysis container',()=>{
 const h=referenceHarness();h.usages.children.reverse();h.listeners['usages:input']();
 assert.match(h.scope.innerHTML,/value="u2" selected>1\. Verb/);assert.equal(h.scope.value,'u2');
 h.listeners['form:focusin']({target:h.scope});assert.match(h.scope.innerHTML,/Whole entry/);
});
test('opening a row detail does not mark the research draft dirty or reorder rows',()=>{
 const tools={},row={matches:()=>false,append(){},parentElement:{dispatchEvent(){throw Error('unexpected row mutation');}},classList:{contains:()=>false}};
 const c=vm.createContext({document:{createElement:()=>tools},lexemeDirty:false,wsUi:(zh,en)=>en});
 vm.runInContext(source.slice(source.indexOf('function wsMoveButtons('),source.indexOf('// Class-level principal-parts template')),c);
 c.wsMoveButtons(row);tools.onclick({target:{closest:()=>({matches:()=>false})}});assert.equal(c.lexemeDirty,false);
});
test('template supplementation preserves filled rows and adds each missing item once',()=>{
 const existing={id:'keep',label:'NOM.SG',form:'custom',features:['GEN']},added=[],list={children:[existing]},button={};
 const r={querySelector:selector=>selector==='.ws-apply-template'?button:selector==='.ws-class'?{value:'c'}:list};
 const c=vm.createContext({r,lexemeClasses:[{id:'c',template:{slots:[{label:'NOM.SG',notes:'shared'},{label:'GEN.SG',notes:'genitive'},{label:'GEN.SG',notes:'duplicate'}]}}],wsVal:row=>row.label,wsPart:(container,p)=>{added.push({...p});container.children.push(p);return {querySelector:()=>({focus(){}})};},info(){},lexemeDirty:false});
 const start=source.indexOf("r.querySelector('.ws-apply-template').onclick="),end=source.indexOf(';r.querySelector(\'.ws-membership-head\')',start);
 vm.runInContext(source.slice(start,end)+';',c);button.onclick();
 assert.equal(list.children[0],existing);assert.equal(existing.form,'custom');assert.deepEqual(existing.features,['GEN']);assert.equal(added.length,1);assert.equal(added[0].label,'GEN.SG');
 button.onclick();assert.equal(added.length,1);assert.equal(c.lexemeDirty,true);
});
function readingHarness(){
 const c=vm.createContext({esc,rich:esc,wsUi:(zh,en)=>en,usageLabel:u=>u.pos,featuresView:ids=>ids.length?'<span>FEATURES</span>':'',wsWritingsView:rows=>rows?.length?'<span>WRITINGS</span>':''});
 vm.runInContext(source.slice(source.indexOf('function wsMembershipsView('),source.indexOf('// Keep the core entry form')),c);
 const x={body:{usages:[{id:'u',pos:'Noun'}],variants:[{id:'v',form:'aduun'}],word_structure:{memberships:[{class_id:'c',usage_id:'u',parts:[{label:'NOM.SG',form:'aduu'},{label:'GEN.SG',variant_id:'v'}]}]}}};
 const data={classes:[{id:'c',name:'N-stem nouns',template:{title:'Morphology hints',slots:[]}}],tags:[]};
 return {c,x,data,render:()=>c.wsMembershipsView(x,data)};
}
test('header shows class name and compact pairs, resolving a referenced form live',()=>{
 const h=readingHarness();let html=h.render();assert.match(html,/<details class="ws-membership-main" open>/);
 assert.match(html,/N-stem nouns/);assert.match(html,/NOM\.SG<\/span><span class="dictionary-wordform">aduu/);
 assert.match(html,/GEN\.SG<\/span><span class="dictionary-wordform">aduun/);assert.doesNotMatch(html,/Morphology hints|ws-parts-view|<dl/);
 h.x.body.variants[0].form='changed';html=h.render();assert.match(html,/dictionary-wordform">changed/);assert.doesNotMatch(html,/>aduun</);
});
test('compact header retains class notes, written forms, features and exceptions without a scope caption',()=>{
 const h=readingHarness();h.data.classes[0].notes='shared <note>';const membership=h.x.body.word_structure.memberships[0];
 membership.notes='entry exception';membership.title='custom module';Object.assign(membership.parts[0],{features:['f'],writings:[{text:'甲'}],notes:'part note'});
 const html=h.render();for(const value of ['shared &lt;note>','entry exception','custom module','FEATURES','WRITINGS','part note'])assert.ok(html.includes(value),value);
 assert.doesNotMatch(html,/Applies to:|适用于/);assert.equal(membership.usage_id,'u');
 assert.match(html,/<details class="ws-membership-extra">/);
});
test('direct principal form keeps priority and unavailable references remain visible',()=>{
 const h=readingHarness(),parts=h.x.body.word_structure.memberships[0].parts;parts[1].form='override';
 let html=h.render();assert.match(html,/dictionary-wordform">override/);assert.match(html,/Reference: /);
 h.x.body.variants=[];parts[1].form='';html=h.render();assert.match(html,/Reference unavailable/);assert.match(html,/referenced form is unavailable/);
});
test('empty class-template instructions do not create an empty header form',()=>{
 const h=readingHarness();h.data.classes[0].template.slots=[{label:'PST',notes:'template only'}];
 h.x.body.word_structure.memberships[0].parts.push({label:'PST',notes:'template only'});assert.doesNotMatch(h.render(),/>PST</);
 h.x.body.word_structure.memberships=[];assert.equal(h.render(),'');
});
test('header safely escapes user class names, labels and forms',()=>{
 const h=readingHarness();h.data.classes[0].name='<script>';h.x.body.word_structure.memberships[0].parts[0]={label:'<label>',form:'<img>'};
 const html=h.render();assert.doesNotMatch(html,/<script>|<label>|<img>/);assert.match(html,/&lt;script>/);assert.match(html,/&lt;img>/);
});
