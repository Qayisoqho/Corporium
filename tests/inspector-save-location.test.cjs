const {test}=require('node:test'),assert=require('node:assert/strict'),fs=require('node:fs'),vm=require('node:vm');
function setup(independent=false){
 const calls=[],elements={};
 const c={window:{corporiumSentenceInspector:{current:()=>({kind:independent?'independent':'corpus',id:'sentence',word:4})},corporiumRefreshExampleSource:async source=>calls.push(['refresh',JSON.parse(JSON.stringify(source))])},
  independentLink:independent?{id:'sentence',word:4,data:{revision:8,language_id:'one'}}:null,
  linkUnit:{id:'unit',entry_id:'sentence',kind:'word',revision:2,entry_revision:8,language_id:'one',link:{id:'link',revision:1,index:0}},linkColorWord:{},linkLexeme:{id:'lexeme',revision:3},
  linkSafe:fn=>fn,$:id=>elements[id]??(elements[id]={value:id==='link-unit'?'@word':'',textContent:''}),
  originalApi:async(path,body)=>calls.push(['write',path,body]),api:()=>assert.fail('a second automatic history/detail refresh was requested'),readComponentSelection:()=>null,readFeatures:()=>[]};
 const s=fs.readFileSync('web/lexicon.js','utf8');vm.createContext(c);
 vm.runInContext(s.slice(s.indexOf('function linkedSentenceSource('),s.indexOf("$('view-linked-lexeme').onclick"))+s.slice(s.indexOf('async function saveIndependentLink('),s.indexOf("document.addEventListener('click',linkSafe(async e=>")),c);
 return {c,elements,calls};
}
test('text links refresh their actual source once with its selected word and part',async()=>{
 const {elements,calls}=setup();await elements['save-link'].onclick();
 assert.equal(calls[0][1],'lexeme-link');assert.deepEqual(calls[1],['refresh',{kind:'corpus',id:'sentence',word:4,key:'@word'}]);assert.equal(calls.length,2);
});
test('independent save and unlink keep the current source instead of opening the library',async()=>{
 for(const remove of [false,true]){const {c,calls}=setup(true);await c.saveIndependentLink(remove);assert.equal(calls[0][1],'segmentation-link');assert.deepEqual(calls[1],['refresh',{kind:'independent',id:'sentence',word:4,key:'@word'}]);assert.equal(calls.length,2);}
});
test('unlinking a corpus occurrence refreshes the same sentence without rebuilding another view',async()=>{
 const {elements,calls}=setup();await elements['unlink-unit'].onclick();assert.equal(calls[0][1],'lexeme-unlink');assert.equal(calls[1][1].id,'sentence');assert.equal(calls.length,2);
});
