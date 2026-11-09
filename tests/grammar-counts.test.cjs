const test=require('node:test'),assert=require('node:assert/strict'),fs=require('node:fs'),vm=require('node:vm');

function setup(){
 class Element{
  constructor(tag='div'){this.tagName=tag;this.children=[];this.dataset={};this.attributes={};this.value='';this.classes=new Set();this.classList={add:(...xs)=>xs.forEach(x=>this.classes.add(x)),toggle:(x,on)=>on?this.classes.add(x):this.classes.delete(x)};this.listeners={};}
  append(...nodes){this.children.push(...nodes);}replaceChildren(...nodes){this.children=nodes;}
  setAttribute(k,v){this.attributes[k]=v;}addEventListener(k,fn){this.listeners[k]=fn;}after(){}
  closest(){return new Element('label');}matches(s){return s==='.filters';}
 }
 const nodes={},made=[],events=new EventTarget(),issue=new Element('select');issue.value='all';
 issue.options=['all','unknown','boundary','alias','pending','annotation','usage'].map(value=>({value,textContent:value}));
 nodes['grammar-issue']=issue;nodes['grammar-source']=Object.assign(new Element(),{value:'all'});nodes['grammar-lower']=new Element();nodes['grammar-query']=new Element();nodes['grammar-summary']=new Element();
 const root=nodes['grammar-workspace']=new Element(),heading=new Element(),checks=new Element();checks.nextElementSibling=new Element();
 root.querySelector=()=>heading;root.querySelectorAll=()=>[checks];
 const c={$:id=>nodes[id],window:{addEventListener:events.addEventListener.bind(events)},dispatchEvent:events.dispatchEvent.bind(events),CustomEvent,URLSearchParams,localStorage:{getItem(){return null;},setItem(){}},document:{createElement:tag=>{const el=new Element(tag);made.push(el);return el;}},grammarRequest:0,grammarPage:1,grammarFocus:'',grammarCandidateFocus:null,drawGrammarTags(){},grammarTypes:Object.fromEntries(issue.options.map(o=>[o.value,o.value]))};
 vm.createContext(c);
 const bench=fs.readFileSync('web/workbench.js','utf8'),a=bench.indexOf('/* Tags and checks:');
 vm.runInContext(bench.slice(a,bench.indexOf('/* Settings center:',a)),c);
 const grammar=fs.readFileSync('web/grammar.js','utf8'),start=grammar.indexOf('function publishGrammarAudit(');
 vm.runInContext(grammar.slice(start,grammar.indexOf(" for(const id of ['grammar-top'",start))+'\n}',c);
 // Installed after workbench.js, as the real task transport is. No raw
 // grammar-audit response traverses an earlier api wrapper.
 const waiting=[];c.api=path=>new Promise((resolve,reject)=>waiting.push({path,resolve,reject}));
 const list=made.find(e=>e.className==='grammar-type-list'),nav=made.find(e=>e.className==='grammar-types');
 return {c,nodes,waiting,nav,badges:()=>Object.fromEntries(list.children.map(e=>[e.dataset.issue,e.children[1].textContent])),result:(counts,total=0)=>({tags:[],page:1,sentences:34,total,counts})};
}

test('accepted background-task results populate every badge without a raw audit response',async()=>{
 const s=setup(),work=s.c.loadGrammar();assert.equal(s.badges().boundary,'—');assert.equal(s.nav.attributes['aria-busy'],'true');
 s.waiting[0].resolve(s.result({boundary:22,unknown:3},25));await work;
 assert.equal(s.badges().all,'25');assert.equal(s.badges().boundary,'22');assert.equal(s.badges().unknown,'3');assert.equal(s.badges().annotation,'0');assert.equal(s.nav.attributes['aria-busy'],'false');
 assert.match(s.nodes['grammar-summary'].textContent,/22/);
});

test('scope changes accept only the newest result, preserve type totals and show real zeroes',async()=>{
 const s=setup(),old=s.c.loadGrammar();s.nodes['grammar-source'].value='independent';const latest=s.c.loadGrammar();
 s.waiting[1].resolve(s.result({boundary:4,usage:12},4));await latest;
 s.waiting[0].resolve(s.result({boundary:90},90));await old;
 assert.equal(s.badges().all,'4');assert.equal(s.badges().boundary,'4');
 const empty=s.c.loadGrammar();assert.equal(s.badges().all,'—');s.waiting[2].resolve(s.result({}));await empty;assert.equal(s.badges().all,'0');assert.equal(s.badges().boundary,'0');
});

test('failed checks leave unavailable counts instead of zero; a stale failure cannot clear a newer result',async()=>{
 const s=setup(),failed=s.c.loadGrammar(),rejection=assert.rejects(failed,/failed/);s.waiting[0].reject(Error('failed'));await rejection;
 assert.equal(s.badges().all,'—');assert.equal(s.nav.attributes['aria-busy'],'false');
 const old=s.c.loadGrammar(),stale=assert.rejects(old,/stale/),latest=s.c.loadGrammar();s.waiting[2].resolve(s.result({pending:2},2));await latest;
 s.waiting[1].reject(Error('stale'));await stale;assert.equal(s.badges().pending,'2');assert.equal(s.badges().all,'2');
});
