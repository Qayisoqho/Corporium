const test=require('node:test'),assert=require('node:assert/strict'),fs=require('node:fs'),vm=require('node:vm');
function setup(native=false){
 const source=fs.readFileSync(native?'web/morphemes.js':'web/lexicon.js','utf8'),lex=fs.readFileSync('web/lexicon.js','utf8');let exists=false;
 const nodes=new Map(),$=id=>{if(!nodes.has(id))nodes.set(id,{dataset:{},style:{},value:'30',textContent:'',innerHTML:'',scrollTop:0,nextElementSibling:{},querySelectorAll:()=>[],querySelector:()=>null});return nodes.get(id);};
 const c={$ ,URLSearchParams,CSS:{escape:v=>v},activeLanguage:'ordos',languageList:[],dictionaryPage:1,dictionaryRequest:0,dictionarySelection:'created',dictionaryMissingNotice:'',exampleFormOwner:null,exampleForm:'all',exampleRequest:0,selection:'created',request:0,page:1,mode:'morphemes',missingNotice:'',editor:{open:false},editing:null,window:{dictionarySearchParams:()=>({})},detail:$('morpheme-detail'),language(){},layout(){},remember(){},leaveSentenceDrafts:async()=>{},fetchWritingTypes:async()=>[],renderDictionaryList(){},topPagination(){},languageTypographyCSS:()=>'',api:async path=>{
  if(path.startsWith(native?'morpheme?id=':'lexeme?id=')){if(!exists)throw Error(native?'该语素不存在':'该词条不存在');return {id:'created',revision:2,language_id:'ordos',body:{variants:[]}};}
  if(path.startsWith('grammar-tags'))return [];
  return {items:[],total:exists?1:0,page:1,pages:1};
 }};
 vm.createContext(c);
 vm.runInContext(lex.slice(lex.indexOf('function clearDictionaryMissingNotice('),lex.indexOf('async function loadDictionary(')),c);
 if(native){
  vm.runInContext(source.slice(source.indexOf(' async function load(withDetail=true)'),source.indexOf(' window.corporiumRefreshDictionaryCounts=')),c);
  const start=source.indexOf(' async function show(id)'),end=source.indexOf("for(const b of $('morpheme-list')",start);
  vm.runInContext(source.slice(start,end)+"detail.innerHTML='opened:'+m.id;}",c);
 }else{
  vm.runInContext(source.slice(source.indexOf('async function loadDictionary(withDetail=true)'),source.indexOf('const loadLexemeListOnly=')),c);
  const start=source.indexOf('async function showLexeme('),end=source.indexOf('  const [examples,morphData]',start);
  vm.runInContext(source.slice(start,end)+"$('dictionary-detail').innerHTML='opened:'+x.id;}",c);
 }
 return {c,$,reload:()=>native?c.load():c.loadDictionary(),restore:()=>exists=true};
}
for(const native of [false,true])test((native?'morpheme':'lexeme')+' selection survives an undone creation and reopens after redo, clearing its old notice',async()=>{
 const h=setup(native),field=native?'selection':'dictionarySelection',detail=native?'morpheme-detail':'dictionary-detail';
 await h.reload();assert.equal(h.c[field],'created');assert.match(h.$(detail).innerHTML,/不存在/);
 h.$('notice').textContent=h.$('dictionary-notice').textContent=native?'该语素不存在':'该词条不存在';
 h.restore();await h.reload();assert.equal(h.c[field],'created');assert.equal(h.$(detail).innerHTML,'opened:created');
 assert.equal(h.$('notice').textContent,'');assert.equal(h.$('dictionary-notice').textContent,'');
 assert.equal(h.$(detail).dataset.referenceId,'created');assert.equal(h.$(detail).dataset.referenceRevision,'2');
});
