const {test}=require('node:test'),assert=require('node:assert/strict'),fs=require('node:fs'),vm=require('node:vm');
const read=path=>fs.readFileSync('web/'+path,'utf8');
test('native morpheme choices do not inherit parts of speech, including converted usages',()=>{
 const c={};vm.createContext(c);for(const name of ['lexemePlainLabel','usageLabel','dictionaryTargetDescription','dictionaryCandidateLabel'])vm.runInContext(read('display-tools.js').match(new RegExp('function '+name+'[^\\n]+'))[0],c);
 const body={usages:[{pos:'词类待定',senses:[{short_gloss:'GEN'},{short_gloss:'GEN'}]}]};
 assert.equal(c.dictionaryTargetDescription({target_kind:'morpheme',body}),'GEN');
 assert.equal(c.dictionaryCandidateLabel({target_kind:'morpheme',headword:'n',pos:'名词'}),'语素 · n');
 assert.equal(c.dictionaryCandidateLabel({target_kind:'lexeme',headword:'n',pos:'名词'}),'n / 名词');
});
test('converted meanings render once and retain source tags, notes and features without a POS disclosure',()=>{
 const c={esc:String,activeLanguage:'one',variantTags:[],richGloss:String,showTags:tags=>tags.map(t=>t.value).join(''),featuresView:features=>features.join('')};vm.createContext(c);
 const source=read('morphemes.js');vm.runInContext(source.slice(source.indexOf(' function morphemeMeanings'),source.indexOf(' function convertedInfo')),c);
 const html=c.morphemeMeanings({primary_sense_id:'a',gloss:'GEN',definition:'主要功能',tags:[{value:'条目标签'}],senses:[{id:'b',gloss:'PL',definition:'其他功能'}],usages:[{pos:'名词',notes:'用法资料',senses:[{id:'a',short_gloss:'GEN',definition:'主要功能',tags:[{value:'原意义标签'}],notes:'原意义备注',features:['feature']},{id:'b',short_gloss:'PL',definition:'其他功能'}]}]});
 assert.ok(!html.includes('名词'));assert.ok(!html.includes('<details'));for(const text of ['主要功能','其他功能','用法资料','原意义备注','feature','条目标签','原意义标签'])assert.ok(html.includes(text),text);
 assert.equal(html.split('其他功能').length-1,1);assert.equal(html.split('主要功能').length-1,1);
});
test('replacement warnings follow the actual remaining matches, across result pages',()=>{
 const c={};vm.createContext(c);vm.runInContext(read('text-tools.js').match(/function restrictReplacePlan[^\n]+/)[0],c);
 const changes=Array.from({length:81},(_,i)=>({key:String(i),id:String(i),word:0}));const plan={changes,conflicts:[{id:'80',word:0,reason:'切分变化'}],blocked:[{id:'0',reason:'无法导出'}]};
 assert.equal(c.restrictReplacePlan(plan).conflicts.length,1);
 const remaining=c.restrictReplacePlan(plan,changes.slice(0,80));assert.equal(remaining.conflicts.length,0);assert.equal(remaining.blocked.length,1);
 const last=c.restrictReplacePlan(plan,changes.slice(80));assert.equal(last.conflicts.length,1);assert.equal(last.blocked.length,0);
});
test('undo may reselect the same text without resetting its page, while explicit navigation still resets',async()=>{
 const nodes={};const c={selected:'text',page:4,texts:[{id:'text',title:'Text',errors:'[]'},{id:'other',title:'Other',errors:'[]'}],$:id=>nodes[id]??=( {}),loadTexts:async()=>{},search:async()=>{}};vm.createContext(c);
 const source=read('app.js');vm.runInContext(source.slice(source.indexOf('async function selectText'),source.indexOf('async function search')),c);
 await c.selectText('text',{preservePage:true});assert.equal(c.page,4);
 await c.selectText('other',{preservePage:true});assert.equal(c.page,1);
 c.page=5;await c.selectText('other');assert.equal(c.page,1);
});
