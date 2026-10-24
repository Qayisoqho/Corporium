const test=require('node:test'),assert=require('node:assert/strict'),vm=require('node:vm'),fs=require('node:fs');
const source=fs.readFileSync(require.resolve('../web/sentence-create.js'),'utf8');
const scope={inlineDrafts:new Map(),Error};vm.runInNewContext(source.slice(0,source.indexOf('async function beginSentenceDraft')),scope);
const empty=()=>({isNew:true,body:{ipa:'',translation:'',words:[{form:'',gloss:''}]},cells:[]});
test('only unsaved empty new sentences are discarded; saved blanks and saving drafts survive',()=>{
 scope.inlineDrafts.clear();let removed=0;
 scope.inlineDrafts.set('empty',{...empty(),dirty:true,host:{remove(){removed++;}}});
 scope.inlineDrafts.set('saved',{...empty(),isNew:false});scope.inlineDrafts.set('saving',{...empty(),saving:true});
 scope.discardEmptySentenceDrafts();assert.equal(removed,1);assert.deepEqual([...scope.inlineDrafts.keys()],['saved','saving']);
});
test('notes, unfinished glosses and extra layer values protect a new sentence',async()=>{
 for(const field of ['notes','gloss','layer']){
  scope.inlineDrafts.clear();const d=empty();if(field==='notes')d.body.notes='研究';if(field==='gloss')d.body.words[0].gloss='N';if(field==='layer')d.cells=[{value:'内容'}];
  scope.inlineDrafts.set('draft',d);await assert.rejects(scope.leaveSentenceDrafts(),/保存/);assert.equal(scope.inlineDrafts.size,1);
 }
});
