const test=require('node:test'),assert=require('node:assert/strict'),vm=require('node:vm'),fs=require('node:fs');
const source=fs.readFileSync(require.resolve('../web/timeline.js'),'utf8');
function setup(){
 const s={activeLanguage:'ordos',data:{tracks:[{id:'s',kind:'sentence'},{id:'e',kind:'event'},{id:'l',kind:'language'}]},inlineKey:(kind,id)=>kind+':'+id,inlineDrafts:new Map()};
 vm.createContext(s);vm.runInContext(source.slice(source.indexOf('function sentenceBlockText('),source.indexOf('// Preview only visible references')),s);return s;
}
test('sentence blocks use an open draft without changing the saved interval text',()=>{
 const s=setup(),i={entry_id:'one',track_id:'s',text:'saved IPA'};
 s.inlineDrafts.set('corpus:one',{owner_language:'ordos',body:{ipa:'draft ɣəː',translation:'translation'}});
 assert.equal(s.sentenceBlockText(i),'draft ɣəː');assert.equal(i.text,'saved IPA');
 s.inlineDrafts.delete('corpus:one');assert.equal(s.sentenceBlockText(i),'saved IPA');
});
test('independent sentence drafts follow IPA, translation and empty-source fallback',()=>{
 const s=setup(),i={entry_id:'independent:one',track_id:'s',text:'saved'},d={owner_language:'ordos',body:{ipa:'draft',translation:'translation'}};
 s.inlineDrafts.set('independent:one',d);assert.equal(s.sentenceBlockText(i),'draft');
 d.body.ipa='';assert.equal(s.sentenceBlockText(i),'translation');d.body.translation='';assert.equal(s.sentenceBlockText(i),'未填写句子');
});
test('drafts cannot override event captions, language labels, missing sources or another language',()=>{
 const s=setup(),d={owner_language:'ordos',body:{ipa:'draft'}};s.inlineDrafts.set('corpus:one',d);
 for(const fields of [{track_id:'e'},{track_id:'l'},{track_id:'s',missing_entry:true},{track_id:'s',entry_id:'other'}])assert.equal(s.sentenceBlockText({entry_id:'one',text:'saved',...fields}),'saved');
 d.owner_language='other';assert.equal(s.sentenceBlockText({entry_id:'one',track_id:'s',text:'saved'}),'saved');
});
