const test=require('node:test'),assert=require('node:assert/strict'),fs=require('node:fs'),vm=require('node:vm');
const source=fs.readFileSync(require.resolve('../web/grammar.js'),'utf8');
const fn=source.slice(source.indexOf('function grammarWordLocation('),source.indexOf('function drawGrammarTags('));
function location(item,english=false){
 const context={CorporiumI18n:{f:(key,args)=>english?' · Word '+args()[0]:' · 第 '+args()[0]+' 词',ui:(zh,en)=>english?en:zh}};
 vm.createContext(context);vm.runInContext(fn,context);return context.grammarWordLocation(item);
}
test('check locations use lexical ordinals in Chinese and English, preserving the physical cell',()=>{
 const item={word:29,word_number:13};
 assert.equal(location(item),' · 第 13 词');assert.equal(location(item,true),' · Word 13');
 assert.deepEqual(item,{word:29,word_number:13});
});
test('excluded cells have an explicit cell label and sentence-level reviews have no word number',()=>{
 assert.equal(location({word:2,word_number:null}),' · 第 2 格');
 assert.equal(location({word:2,word_number:null},true),' · Cell 2');
 assert.equal(location({}), '');assert.equal(location({},true),'');
});
test('older results retain their supplied word number',()=>{
 assert.equal(location({word:3},true),' · Word 3');
});
