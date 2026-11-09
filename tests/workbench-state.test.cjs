const test=require('node:test'),assert=require('node:assert/strict'),fs=require('node:fs'),vm=require('node:vm');
const source=fs.readFileSync('web/workbench.js','utf8');
class Node{
 constructor(classes='',id=''){this.nodeType=1;this.id=id;this.className=classes;this.children=[];this.parentElement=null;this.attrs={};this.reads=0;this.writes=0;this.isConnected=true;
  this.classList={contains:name=>this.className.split(/\s+/).includes(name),toggle:(name,on)=>{this.writes++;this.className=this.className.split(/\s+/).filter(x=>x&&x!==name).concat(on?[name]:[]).join(' ');},add:(...names)=>{for(const name of names)if(!this.classList.contains(name))this.classList.toggle(name,true);}};
 }
 append(...nodes){for(const node of nodes){node.parentElement=this;this.children.push(node);}}
 matches(selector){return selector.split(',').some(part=>part[0]==='.'?this.classList.contains(part.slice(1)):part[0]==='#'?this.id===part.slice(1):/^\[[\w-]+\]$/.test(part)?Object.hasOwn(this.attrs,part.slice(1,-1)):this.tagName?.toLowerCase()===part);}
 querySelectorAll(selector){this.reads++;return this.children.flatMap(n=>[...(n.matches(selector)||(selector==='.workbench-batch[open]'&&n.matches('.workbench-batch')&&Object.hasOwn(n.attrs,'open'))?[n]:[]),...n.querySelectorAll(selector)]);}
 querySelector(selector){return this.querySelectorAll(selector)[0]||null;}
 getAttribute(name){return name==='class'?this.className:this.attrs[name]??null;}
}
function setup(){
 let deliver;const c=vm.createContext({MutationObserver:class{constructor(callback){deliver=callback;}observe(root,options){this.target=root;this.options=options;}disconnect(){}}});
 vm.runInContext(source.slice(0,source.indexOf('// Add scope explanations')),c);
 const body=new Node(),corpus=new Node('','corpus-workspace'),card=new Node('entry existing'),head=new Node('entry-head'),box=new Node(),example=new Node('editable-example');head.append(box);card.append(head,example);corpus.append(card);body.append(corpus);
 const html=new Node();html.append(body);body.ownerDocument={documentElement:html};
 const observer=c.createWorkbenchStyleState(body);return {c,body,html,corpus,card,head,box,example,observer,deliver:changes=>deliver(changes)};
}
const childList=(target,addedNodes=[],removedNodes=[])=>({type:'childList',target,addedNodes,removedNodes});
const attribute=(target,attributeName,oldValue)=>({type:'attributes',target,attributeName,oldValue});

test('caption presentation classes do not invalidate structural sentence state',()=>{
 const h=setup(),reads=h.card.reads;
 h.box.className='ui-optical-control';h.deliver([attribute(h.box,'class','')]);
 assert.equal(h.card.reads,reads);assert.equal(h.card.classList.contains('wb-has-editor'),true);
 h.box.className='ui-optical-control formatted-copy-pick';h.deliver([attribute(h.box,'class','ui-optical-control')]);
 assert.equal(h.head.classList.contains('wb-has-copy-pick'),true);
});

test('wrapping existing caption text preserves state without rescanning a sentence',()=>{
 const h=setup(),label=new Node('ui-button-label'),reads=h.card.reads;label.tagName='UI-LABEL';
 h.box.append(label);h.deliver([childList(h.box,[label],[{nodeType:3}])]);
 assert.equal(h.card.reads,reads);assert.equal(h.card.classList.contains('wb-has-editor'),true);
 const save=new Node();save.attrs['data-inline-save']='';h.example.append(save);h.deliver([childList(h.example,[save])]);
 assert.equal(h.card.classList.contains('wb-has-save'),true);
});
test('sentence state follows dynamically inserted and removed editor controls without replacing nodes',()=>{
 const h=setup(),save=new Node();save.attrs['data-inline-save']='';
 assert.equal(h.card.classList.contains('wb-has-editor'),true);assert.equal(h.example.classList.contains('wb-has-save'),false);
 h.example.append(save);h.deliver([childList(h.example,[save])]);
 assert.equal(h.example.classList.contains('wb-has-save'),true);assert.equal(h.card.classList.contains('wb-has-save'),true);
 assert.equal(h.html.classList.contains('wb-has-inline-save'),true);
 assert.equal(h.head.children[0],h.box);assert.equal(h.card.classList.contains('existing'),true);
 h.example.children=[];save.isConnected=false;h.deliver([childList(h.example,[],[save])]);
 assert.equal(h.example.classList.contains('wb-has-save'),false);assert.equal(h.card.classList.contains('wb-has-save'),false);
 assert.equal(h.html.classList.contains('wb-has-inline-save'),false);
});
test('borrowing an existing selection checkbox updates brief-copy state even without adding nodes',()=>{
 const h=setup();h.box.className='formatted-copy-pick';h.deliver([attribute(h.box,'class','')]);assert.equal(h.head.classList.contains('wb-has-copy-pick'),true);
 h.box.className='';h.deliver([attribute(h.box,'class','formatted-copy-pick')]);assert.equal(h.head.classList.contains('wb-has-copy-pick'),false);assert.equal(h.head.children[0],h.box);
});
test('batch visibility follows open state and dynamic sentence subtrees are initialized',()=>{
 const h=setup(),batch=new Node('workbench-batch');h.corpus.append(batch);batch.attrs.open='';h.deliver([attribute(batch,'open',null)]);assert.equal(h.corpus.classList.contains('wb-batch-open'),true);
 delete batch.attrs.open;h.deliver([attribute(batch,'open','')]);assert.equal(h.corpus.classList.contains('wb-batch-open'),false);
 const nested=new Node('lex-example'),example=new Node('editable-example');nested.append(example);h.body.append(nested);h.deliver([childList(h.body,[nested])]);assert.equal(nested.classList.contains('wb-has-editor'),true);
});
test('internal bookkeeping does not rescan the page or form an observer loop',()=>{
 const h=setup(),reads=h.body.reads,writes=h.card.writes;h.deliver([attribute(h.card,'class','entry existing')]);
 assert.equal(h.body.reads,reads);assert.equal(h.card.writes,writes);assert.deepEqual(Array.from(h.observer.options.attributeFilter),['class','open','hidden','data-inline-save']);
 h.deliver([attribute(h.card,'hidden','')]);assert.equal(h.body.reads,reads);assert.equal(h.card.writes,writes);
});
test('scroll candidates include inactive theme rules and dynamic nodes without registering glyphs or global state scans',()=>{
 const h=setup(),pane=new Node('pane'),glyph=new Node('form'),input=new Node();input.tagName='INPUT';pane.append(glyph,input);h.body.append(pane);
 const style={getPropertyValue:name=>name==='overflow-y'?'auto':''},doc={body:h.body,documentElement:h.html,styleSheets:[{cssRules:[{selectorText:'html[data-home=false] .parent .pane:not([hidden])',style},{selectorText:'html[data-theme=night] :is(#later,#other)',style},{selectorText:'[data-text]',style}]}]};
 const observer=h.c.createWorkbenchScrollRegions(doc);assert.equal(observer.target,h.body);assert.equal(pane.classList.contains('wb-scroll-region'),true);assert.equal(input.classList.contains('wb-scroll-region'),true);assert.equal(glyph.classList.contains('wb-scroll-region'),false);
 const before=h.body.reads,childReads=glyph.reads;pane.className+=' is-current';h.deliver([attribute(pane,'class','pane wb-scroll-region')]);assert.equal(h.body.reads,before);assert.equal(glyph.reads,childReads);
 const later=new Node('','later');h.body.append(later);h.deliver([childList(h.body,[later])]);assert.equal(later.classList.contains('wb-scroll-region'),true);assert.equal(h.body.reads,before);
 glyph.attrs['data-text']='one';h.deliver([attribute(glyph,'data-text',null)]);assert.equal(glyph.classList.contains('wb-scroll-region'),true);assert.ok(observer.options.attributeFilter.includes('data-text'));
});

test('caption decoration leaves compound preview choices and timeline IPA untouched after insertion and text updates',()=>{
 const h=setup(),pending=new Node('tl-pending'),sentence=new Node(),choice=new Node('ui-list-item'),ipa=new Node('tl-ipa'),command=new Node(),queued=[],walked=[];
 for(const node of [h.body,pending,sentence,choice,ipa,command])node.closest=function(selector){for(let n=this;n;n=n.parentElement)if(n.matches(selector))return n;return null;};
 for(const node of [sentence,choice,ipa,command])node.tagName='BUTTON';
 pending.append(sentence);h.body.append(pending,choice,ipa,command);
 const doc={body:h.body,createTreeWalker(node){walked.push(node);return {nextNode:()=>null};}};
 h.c.queueMicrotask=fn=>queued.push(fn);
 const decorate=h.c.createInterfaceTextLabels(doc),flush=()=>{while(queued.length)queued.shift()();};flush();
 assert.deepEqual(walked,[command]);
 decorate([childList(sentence,[{nodeType:3}],[]),childList(ipa,[{nodeType:3}],[])]);flush();
 assert.deepEqual(walked,[command]);
 for(const node of [sentence,choice,ipa])assert.equal(node.classList.contains('ui-optical-control'),false);
 assert.equal(pending.children[0],sentence);
});
