const {test}=require('node:test'),assert=require('node:assert/strict'),fs=require('node:fs'),vm=require('node:vm');
const source=fs.readFileSync('web/lexicon.js','utf8');
function setup({excluded=false}={}){
 const calls=[],nodes={'dictionary-query':{value:'prefix'},'dictionary-page-size':{value:'20'}};
 const scope=vm.createContext({URLSearchParams,$:id=>nodes[id],window:{
  dictionaryOrganizationParams:()=>({sort_order:'custom-order'}),corporiumMorphemeOrder:()=>'@added-desc',dictionarySearchParams:()=>({search:'conditions'}),
  corporiumClearDictionarySearch:()=>{calls.push('clear');nodes['dictionary-query'].value='';}},
  api:async route=>{calls.push(route);return {focus_found:!excluded||nodes['dictionary-query'].value==='',page:4};}});
 vm.runInContext(source.slice(source.indexOf('async function createdDictionaryPage('),source.indexOf("$('lexeme-form').onsubmit=")),scope);
 return {scope,calls,nodes};
}
for(const kind of ['lexeme','morpheme'])test(`new ${kind} retains matching filters and sort while locating its identity`,async()=>{
 const h=setup();assert.equal(await h.scope.createdDictionaryPage(kind,'new id',()=>true),4);
 assert.equal(h.calls.length,1);assert.equal(h.nodes['dictionary-query'].value,'prefix');
 const q=new URLSearchParams(h.calls[0].split('?')[1]);assert.equal(q.get('focus'),'new id');assert.equal(q.get('page_size'),'20');
 assert.equal(q.get('sort_order'),kind==='lexeme'?'custom-order':'@added-desc');assert.equal(q.get('search'),'conditions');
});
test('an excluded new item clears search conditions once and locates again without changing sort',async()=>{
 const h=setup({excluded:true});assert.equal(await h.scope.createdDictionaryPage('lexeme','new',()=>true),4);
 assert.equal(h.calls[1],'clear');assert.equal(h.calls.length,3);assert.equal(new URLSearchParams(h.calls[2].split('?')[1]).get('sort_order'),'custom-order');
});
test('a completed location lookup cannot clear filters after the user navigates elsewhere',async()=>{
 const h=setup({excluded:true});assert.equal(await h.scope.createdDictionaryPage('morpheme','new',()=>false),null);
 assert.equal(h.calls.length,1);assert.equal(h.nodes['dictionary-query'].value,'prefix');
});
