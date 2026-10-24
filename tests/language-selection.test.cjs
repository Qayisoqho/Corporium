const {test}=require('node:test');
const assert=require('node:assert/strict');
const fs=require('node:fs');
const vm=require('node:vm');
const path=require('node:path');
const source=fs.readFileSync(path.join(__dirname,'../web/languages.js'),'utf8');
const selection=source.slice(source.indexOf('function projectStorageKey'),source.indexOf('function renderLanguage'));
function context(rows,selected='deleted-language',project){
 const nodes={};const saved=new Map();
 const c={activeLanguage:selected,languageList:[],localStorage:{setItem:(k,v)=>saved.set(k,v)},
  api:async()=>rows,$:id=>nodes[id]||(nodes[id]={value:'',innerHTML:''}),languageOptions:()=>'',renderLanguage:()=>{}};
 if(project)c.desktopProjectKey=project;
 vm.createContext(c);vm.runInContext(selection,c);return {c,saved,nodes};
}
test('stale selected language resolves to a valid project language and persists it',async()=>{
 const {c,saved,nodes}=context([{id:'ordos',name:'Tëlira'}]);await c.loadLanguages();
 assert.equal(c.activeLanguage,'ordos');assert.equal(nodes['language-select'].value,'ordos');assert.equal(saved.get('corpus-language'),'ordos');
});
test('catalogue without the legacy default selects its first actual language',async()=>{
 const {c}=context([{id:'telira-only',name:'Tëlira'}]);await c.loadLanguages();assert.equal(c.activeLanguage,'telira-only');
});
test('all-language preference remains valid, including an empty catalogue',async()=>{
 const {c}=context([],'all');await c.loadLanguages();assert.equal(c.activeLanguage,'all');
});
test('desktop projects isolate language selection and last-location storage',async()=>{
 const a=context([{id:'a'}],'a','project-a'),b=context([{id:'b'}],'b','project-b');
 await a.c.loadLanguages();await b.c.loadLanguages();
 assert.equal(a.saved.get('corpus-language:project:project-a'),'a');
 assert.equal(b.saved.get('corpus-language:project:project-b'),'b');
 assert.notEqual(a.c.projectStorageKey('corporium-last-place'),b.c.projectStorageKey('corporium-last-place'));
});
