const test=require('node:test'),assert=require('node:assert/strict'),fs=require('node:fs'),vm=require('node:vm');
for(const kind of ['lexeme','morpheme'])for(const outcome of ['saved','navigate','refresh-fails'])test(`${kind} copy ${outcome}: one creation and one owned refresh`,async()=>{
 const source=fs.readFileSync(require.resolve(kind==='lexeme'?'../web/lexicon.js':'../web/morphemes.js'),'utf8');
 const start=source.indexOf('copyButton.onclick=dictSafe('),end=source.indexOf(kind==='lexeme'?"\n  $('delete-lexeme').onclick":'\n const typographyHolder',start);
 const calls=[],c={copyButton:{disabled:false},dictSafe:f=>f,workspace:'dictionary',activeLanguage:'ordos',dictionarySelection:'source',selection:'source',mode:'morphemes',x:{id:'source',revision:4,language_id:'ordos'},m:{id:'source',revision:4,language_id:'ordos'},leaveSentenceDrafts:async()=>{},leaveEditor:async()=>true,loadDictionary:async()=>calls.push('load'),load:async()=>calls.push('load'),window:{dictionaryEntryKind:()=>kind,corporiumInvalidateViews:()=>calls.push('invalidate'),corporiumRefreshUndoState:async()=>{calls.push('history');if(outcome==='refresh-fails')throw Error('offline');}},originalApi:async(path,body)=>{calls.push({path,body});if(outcome==='navigate')c.workspace='library';return {id:'copy'};}};
 vm.createContext(c);vm.runInContext(source.slice(start,end),c);
 if(outcome==='refresh-fails')await assert.rejects(c.copyButton.onclick(),/副本已保存/);else await c.copyButton.onclick();
 const writes=calls.filter(c=>c.path);assert.equal(writes.length,1);assert.equal(writes[0].path,'dictionary-copy');assert.equal(writes[0].body.kind,kind);assert.equal(writes[0].body.revision,4);assert.equal(c.copyButton.disabled,false);
 assert.equal(calls.filter(c=>c==='load').length,outcome==='saved'?1:0);if(outcome==='navigate')assert.equal(c.workspace,'library');
});
