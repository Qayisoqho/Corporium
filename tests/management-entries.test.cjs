const test=require('node:test'),assert=require('node:assert/strict'),fs=require('node:fs'),vm=require('node:vm');
function setup(){
 class Node{
  constructor(tag){this.tag=tag;this.children=[];this.dataset={};this.attrs={};}
  append(...nodes){for(const n of nodes){if(n.parent)n.parent.children.splice(n.parent.children.indexOf(n),1);this.children.push(n);n.parent=this;}}
  before(n){const list=this.parent.children;list.splice(list.indexOf(this),0,n);n.parent=this.parent;}
  setAttribute(k,v){this.attrs[k]=v;}getAttribute(k){return this.attrs[k]||null;}
  querySelectorAll(){return this.children.filter(n=>n.tag==='button');}
 }
 const c={document:{createElement:tag=>new Node(tag)}};vm.createContext(c);
 const s=fs.readFileSync('web/workbench.js','utf8');vm.runInContext(s.slice(0,s.indexOf('/* Shared reading workbench:')),c);
 return {c,make:tag=>new Node(tag)};
}
test('management list preserves manager buttons, handlers and existing accessible descriptions',()=>{
 const {c,make}=setup(),list=make('div'),button=make('button');button.id='writing-manager-open';let clicked=0;button.onclick=()=>clicked++;button.setAttribute('aria-describedby','original-note');list.append(button);
 c.arrangeManagementEntries(list,{'writing-manager-open':'Lexicon writing systems'});
 const row=list.children[0];assert.equal(row.children[0],button);button.onclick();assert.equal(clicked,1);
 assert.equal(row.attrs.role,'listitem');assert.equal(row.children[1].textContent,'Lexicon writing systems');
 assert.equal(button.attrs['aria-describedby'],'original-note management-note-writing-manager-open');
 c.arrangeManagementEntries(list,{'writing-manager-open':'Lexicon writing systems'});assert.equal(list.children.length,1);
});
test('managers mounted later get their scope description without disturbing earlier entries',()=>{
 const {c,make}=setup(),list=make('div'),first=make('button'),late=make('button');first.id='layers-open';late.dataset.managementEntry='speaker';
 const descriptions={'layers-open':'Text tiers',speaker:'Shared contributors'};list.append(first);c.arrangeManagementEntries(list,descriptions);const row=list.children[0];
 list.append(late);c.arrangeManagementEntries(list,descriptions);assert.equal(list.children[0],row);assert.equal(list.children[1].children[0],late);assert.equal(list.children[1].children[1].textContent,'Shared contributors');
});
