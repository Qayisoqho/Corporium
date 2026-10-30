const test=require('node:test'),assert=require('node:assert/strict'),fs=require('node:fs'),vm=require('node:vm');
const source=fs.readFileSync(require.resolve('../web/morphemes.js'),'utf8');
const scope={};vm.createContext(scope);vm.runInContext(source.match(/^function dictionaryLinkNote[^\n]+/m)[0],scope);
test('automatic batch-link provenance is hidden without hiding surrounding research notes',()=>{
 assert.equal(scope.dictionaryLinkNote('形式与简短标注释义完全匹配，批量关联'),'');
 assert.equal(scope.dictionaryLinkNote('人工判断\n形式与简短标注释义完全匹配，批量关联\n需要回访'),'人工判断\n需要回访');
 assert.equal(scope.dictionaryLinkNote('我认为“形式与简短标注释义完全匹配，批量关联”有待核查'),'我认为“形式与简短标注释义完全匹配，批量关联”有待核查');
});
test('empty and ordinary link notes remain well-defined',()=>{
 assert.equal(scope.dictionaryLinkNote(null),'');assert.equal(scope.dictionaryLinkNote('保留\n完整备注'),'保留\n完整备注');
});
const morphology=fs.readFileSync(require.resolve('../web/morphology.js'),'utf8');
scope.esc=String;scope.richGloss=String;scope.componentEvidence=()=>'<span>组分依据</span>';scope.featuresView=features=>features.join(',');vm.runInContext(morphology.match(/^function morphEvidence[^\n]+/m)[0],scope);
test('unassigned concrete forms add no placeholder, while component evidence survives',()=>{
 const html=scope.morphEvidence({}, {variants:[]},[]);assert.match(html,/组分依据/);assert.doesNotMatch(html,/已关联词条|选择具体形式/);assert.match(html,/hidden/);
});
test('concrete form and grammatical evidence are retained',()=>{
 const html=scope.morphEvidence({form_id:'v',features:['PL']},{variants:[{id:'v',form:'tan',features:['HON']}]},[]);assert.match(html,/具体形式：tan/);assert.match(html,/HON/);assert.match(html,/PL/);assert.doesNotMatch(html,/hidden/);
});
test('shared tag choices use the supplied language catalogue before any lexeme editor has opened',()=>{
 const classes=fs.readFileSync(require.resolve('../web/classes.js'),'utf8');scope.lexemeClasses=[];scope.tagNames={region:'地域'};
 vm.runInContext(classes.slice(classes.indexOf('function usageTagOptions('),classes.indexOf('function refreshUsageTagOptions(')),scope);
 const html=scope.usageTagOptions('region',[{id:'r',kind:'usage_tag',name:'地域'},{id:'c',kind:'usage_tag',name:'自定限制'},{id:'p',kind:'pos',name:'名词'}]);
 assert.match(html,/自定限制/);assert.match(html,/value="地域" selected/);assert.doesNotMatch(html,/名词/);assert.equal(scope.lexemeClasses.length,0);
});


test('current exact, boundary-ignored and multipart operation notes are hidden without losing research text',()=>{
 const generated=[
  '词形一致；简短释义「go」 完整匹配',
  '词形一致；简短释义「go」＋固有特征 PST 完整匹配；使用已登记形式「went」',
  '词形与完整标注唯一匹配此义项；具体形式有多个候选，未细分形式',
  '忽略标记 =（仅首尾）：词典「=uron」与语料「uron」均为「uron」；简短释义与适用特征完整匹配，须人工确认',
  '组合 2 个不连续部分；词形一致；简短释义「PST」 完整匹配；与多部分组合共用片段，请选择一种关联'
 ];
 for(const note of generated){assert.equal(scope.dictionaryLinkNote(note),'');assert.equal(scope.dictionaryLinkNote('  field note\n'+note+'\nfollow up  '),'  field note\nfollow up  ');}
 for(const note of ['我认为“须人工确认”应作为研究记录','忽略标记 = 是本人的分析备注','词形一致；这是我写的备注'])assert.equal(scope.dictionaryLinkNote(note),note);
});
test('cleaned operation notes emit no empty paragraph while research markup is escaped',()=>{
 const c={esc:v=>String(v).replace(/&/g,'&amp;').replace(/</g,'&lt;').replace(/>/g,'&gt;')};vm.createContext(c);
 vm.runInContext(source.match(/^function dictionaryLinkNote[^\n]+/m)[0]+'\n'+source.match(/^function dictionaryLinkNoteHtml[^\n]+/m)[0],c);
 assert.equal(c.dictionaryLinkNoteHtml('词形一致；简短释义「go」 完整匹配'),'');assert.equal(c.dictionaryLinkNoteHtml('  '),'');
 assert.equal(c.dictionaryLinkNoteHtml('<b>research</b>'),'<p class="preserve-lines dictionary-link-notes">&lt;b&gt;research&lt;/b&gt;</p>');
});
