const test=require('node:test'),assert=require('node:assert/strict'),fs=require('node:fs'),vm=require('node:vm');
const source=fs.readFileSync(require.resolve('../web/sentence-search.js'),'utf8').split('/* Shared custom-field choices;')[1];
function harness(){
 class Node{constructor(value='',text=''){this.value=value;this.text=text;this.dataset={};this.children=[];this.events={};}append(node){node.parent=this;this.children.push(node);}add(node){this.append(node);}get options(){return this.children.flatMap(n=>n.group?n.children:[n]);}remove(){this.parent.children=this.parent.children.filter(n=>n!==this);}querySelectorAll(){return this.children.filter(n=>Object.hasOwn(n.dataset,'customSearchFields'));}addEventListener(type,fn){this.events[type]=fn;}}
 const nodes=Object.fromEntries(['field','library-field','survey-search-scope'].map(id=>{const n=new Node('all');n.add(new Node('all','全部'));return [id,n];})),calls=[];
 const c={$:id=>nodes[id],activeLanguage:'ordos',window:{},loadTexts:async()=>{},corporiumAlert:e=>{throw Error(e);},Option:function(text,value){return new Node(value,text);},document:{createElement(){const n=new Node();n.group=true;return n;}},api:async path=>{calls.push(path);return {fields:[{group:'layer',id:'layer:'+c.activeLanguage,name:'用户层名'},{group:'writing',id:'writing:'+c.activeLanguage,name:'用户书写'}]};}};
 vm.createContext(c);vm.runInContext('/* Shared custom-field choices;'+source,c);return {c,nodes,calls};
}
test('custom fields load immediately even when reopening directly into the library or survey',async()=>{
 const h=harness();await new Promise(setImmediate);
 for(const select of Object.values(h.nodes))assert.ok(select.options.some(o=>o.value==='layer:ordos')&&select.options.some(o=>o.value==='writing:ordos'));
 assert.equal(h.nodes['library-field'].options.find(o=>o.value==='layer:ordos').text,'用户层名');
 const groups=h.nodes.field.children.filter(n=>n.group);await h.c.window.corporiumRefreshSentenceSearchFields();
 assert.equal(h.nodes.field.children.filter(n=>n.group)[0],groups[0],'unchanged catalog keeps the native dropdown intact');
});
test('language changes replace custom choices and clear foreign-language field selections',async()=>{
 const h=harness();await new Promise(setImmediate);h.nodes.field.value='layer:ordos';h.c.activeLanguage='other';await h.c.window.corporiumRefreshSentenceSearchFields();
 assert.equal(h.nodes.field.value,'all');assert.ok(!h.nodes.field.options.some(o=>o.value==='layer:ordos'));assert.ok(h.nodes.field.options.some(o=>o.value==='layer:other'));
});
