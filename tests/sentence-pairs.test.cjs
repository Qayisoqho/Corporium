const test=require('node:test'),assert=require('node:assert/strict'),vm=require('node:vm'),fs=require('node:fs');
const source=fs.readFileSync(require.resolve('../web/sentence-pairs.js'),'utf8');
const scope={};vm.runInNewContext(source.slice(source.indexOf('function parse('),source.indexOf('window.CorporiumPairs')),scope);
test('Tab pairs allow empty sentences and unfinished glosses without losing punctuation',()=>{
 assert.equal(scope.parse(' \n').length,0);
 assert.equal(JSON.stringify(scope.parse('a\tA\n#\t\nyabu-na\t')),JSON.stringify([{form:'a',gloss:'A'},{form:'#',gloss:''},{form:'yabu-na',gloss:''}]));
});
test('ambiguous Tab input is rejected instead of silently dropping fields',()=>{
 assert.throws(()=>scope.parse('a A'),/Tab/);assert.throws(()=>scope.parse('a\tA\textra'),/Tab/);
});
