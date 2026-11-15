const test=require('node:test'),assert=require('node:assert/strict'),fs=require('node:fs'),vm=require('node:vm');
const source=fs.readFileSync('web/lexicon.js','utf8');
function setup({history=true,context=true}={}){
 const calls=[],record={id:'entry',revision:1,body:{notes:'',usages:[{senses:[{short_gloss:'old',definition:'',notes:''}]}]}};
 const sense={replaceChildren(...children){calls.push(['sense',...children]);}};
 const nodes={
  'dictionary-detail':{dataset:{referenceRevision:'1'},querySelector:()=>({innerHTML:'',hidden:true}),querySelectorAll:selector=>{assert.equal(selector,'.lex-usage-view .lex-sense-view','definitions can be nested in media columns');return [sense];}},
  'corpus-examples-section':{refreshCurrentExamples:async value=>calls.push(['corpus',value.kind,value.id])},
  'standalone-examples':{refreshCurrentExamples:async value=>calls.push(['independent',value.kind,value.id])}
 };
 const view={record,base:'base',current:()=>true,sameDetail:()=>true,requery:false};
 const saved={id:'entry',revision:2,body:{notes:'',usages:[{senses:[{short_gloss:'new',definition:'',notes:''}]}]},
  _view_update:{kind:'lexeme',id:'entry',base:'base',current:'new-revision',before_revision:1,revision:2,sense_text:true}};
 const c=vm.createContext({$:id=>nodes[id],window:{corporiumWorkspaceRevision:'new-revision',
  corporiumRefreshSavedHistory:async()=>history,corporiumMarkSavedView:()=>calls.push(['saved'])},
  displayedLexemeContext:context?{record,request:1,morphData:{}}:null,exampleRequest:1,
  document:{createElement:()=>({content:{querySelectorAll:()=>[{childNodes:['new-content']}]}})},
  lexemeDetailHTML:()=>'<section></section>',rich:value=>value,
  showLexeme:()=>assert.fail('sense save reread the entire detail'),
  refreshDictionaryListOnly:()=>assert.fail('unfiltered sense save reloaded the list')});
 vm.runInContext(source.slice(source.indexOf('async function updateSavedLexeme('),source.indexOf('async function showLexeme(')),c);
 return {c,view,saved,calls,record};
}
test('existing sense strings refresh only their markup and evidence using the shared record',async()=>{
 const h=setup();assert.equal(await h.c.updateSavedLexeme(h.view,h.saved),true);
 assert.equal(h.record.body.usages[0].senses[0].short_gloss,'new');assert.equal(h.record.revision,2);
 assert.deepEqual(h.calls,[['sense','new-content'],['corpus','lexeme','entry'],['independent','lexeme','entry'],['saved']]);
});
test('a different committed project revision rejects local sense refresh',async()=>{
 const h=setup({history:false});assert.equal(await h.c.updateSavedLexeme(h.view,h.saved),false);
 assert.equal(h.record.revision,1);assert.deepEqual(h.calls,[]);
});
test('missing rendering context returns to the full verified refresh path',async()=>{
 const h=setup({context:false});assert.equal(await h.c.updateSavedLexeme(h.view,h.saved),false);
 assert.deepEqual(h.calls,[]);
});
