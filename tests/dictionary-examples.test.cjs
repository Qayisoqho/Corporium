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
