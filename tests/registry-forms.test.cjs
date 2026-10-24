const test=require('node:test'),assert=require('node:assert/strict'),fs=require('node:fs'),vm=require('node:vm');
const source=fs.readFileSync('web/word-structure.js','utf8');
test('explicit variant identity selects its own spelling and pronunciation, while an absent reading inherits the base',()=>{
 const c=vm.createContext({esc:s=>String(s).replaceAll('"','&quot;').replaceAll('<','&lt;')});
 vm.runInContext(source.slice(source.indexOf('function wsRegistryRealization'),source.indexOf('function wsSetRegistryRecord')),c);
 const m={form:'n',body:{gloss:'GEN',readings:['n'],variants:[{id:'a',form:'ne',pronunciation:'nɛ',conditions:''},{id:'b',form:'ne',pronunciation:'ni'},{id:'c',form:'nu'}]}};
 const value=id=>JSON.parse(JSON.stringify(c.wsRegistryRealization(m,id)));
 assert.deepEqual(value(''),{form:'n',readings:['n'],gloss:'GEN'});
 assert.deepEqual(value('a'),{form:'ne',readings:['nɛ'],gloss:'GEN'});
 assert.deepEqual(value('b'),{form:'ne',readings:['ni'],gloss:'GEN'});
 assert.deepEqual(value('c'),{form:'nu',readings:['n'],gloss:'GEN'});
 assert.throws(()=>value('deleted'),/已不存在/);
 const html=c.wsRegistryFormOptions(m);assert.match(html,/value="a">变体 1/);assert.match(html,/value="b">变体 2/);assert.match(html,/基本形式/);
 assert.match(c.wsRegistryFormOptions({form:'<x>',body:{variants:[{id:'"x',form:'<bad>',conditions:'<script>'}]}}),/&quot;x/);
});
