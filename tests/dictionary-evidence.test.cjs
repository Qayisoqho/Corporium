const test=require('node:test'),assert=require('node:assert/strict'),fs=require('node:fs'),vm=require('node:vm');
const helperSource=fs.readFileSync('web/dictionary-evidence.js','utf8');
const lexiconSource=fs.readFileSync('web/lexicon.js','utf8');

// Small DOM surface for the real paging and selection functions. Original
// paging controls keep their identities and callbacks as they move into a row.
class Element {
 constructor(tag='div'){
  this.tagName=tag.toUpperCase();this.children=[];this.parentElement=null;this.dataset={};this.className='';this.hidden=false;this.disabled=false;this.checked=false;this.indeterminate=false;this.isConnected=true;
  this.classList={add:(...names)=>{this.className=[...new Set(this.className.split(/\s+/).filter(Boolean).concat(names))].join(' ');}};
 }
 get childNodes(){return this.children;}
 append(...nodes){for(const node of nodes){if(node.parentElement){const prior=node.parentElement.children;prior.splice(prior.indexOf(node),1);}node.parentElement=this;this.children.push(node);}}
 matches(selector){
  if(selector.startsWith('.'))return this.className.split(/\s+/).includes(selector.slice(1));
  const data=selector.match(/^\[data-([^\]]+)\]$/);
  if(data)return Object.hasOwn(this.dataset,data[1].replace(/-([a-z])/g,(_,letter)=>letter.toUpperCase()));
  return this.tagName===selector.toUpperCase();
 }
 querySelectorAll(selector){
  const descendants=node=>node.children.flatMap(child=>[child,...descendants(child)]);
  const result=[];
  for(const part of selector.split(',')){
   const direct=part.startsWith(':scope>'),match=direct?part.slice(7):part;
   for(const node of (direct?this.children:descendants(this)))if(node.matches(match)&&!result.includes(node))result.push(node);
  }
  return result;
 }
 querySelector(selector){return this.querySelectorAll(selector)[0]||null;}
 insertAdjacentHTML(position){
  assert.equal(position,'beforeend');
  const label=new Element('label');label.className='example-select-all';
  const all=new Element('input');all.dataset.exampleAll='';label.append(all);
  const unlink=new Element('button');unlink.dataset.exampleUnlinkSelected='';unlink.disabled=true;
  this.append(label,unlink);
 }
}
function pagingBar(pages){
 const bar=new Element('nav');bar.dataset.examplePageActions='';
 if(pages!==undefined)bar.dataset.examplePages=String(pages);
 const previous=new Element('button'),next=new Element('button');bar.append(previous,next);
 return {bar,previous,next};
}
function helper(){
 const c=vm.createContext({document:{createElement:tag=>new Element(tag)}});
 vm.runInContext(helperSource,c);
 return {c,evidence:c.CorporiumDictionaryEvidence};
}
function selection(unlink,pages=1){
 const {c,evidence}=helper(),section=new Element('section'),bars=[pagingBar(pages).bar,pagingBar(pages).bar];
 const boxes=Array.from({length:3},(_,i)=>{const box=new Element('input');box.dataset.exampleSelect=String(i);return box;});
 const single=new Element('button');single.dataset.exampleUnlink='1';section.append(...bars,...boxes,single);
 const states=[],prepared=[],errors=[],pageState=evidence.pageState,preparePage=evidence.preparePage;
 evidence.pageState=(bar,selected,busy)=>{states.push({bar:bars.indexOf(bar),selected,busy});pageState(bar,selected,busy);};
 evidence.preparePage=bar=>{prepared.push(bar);preparePage(bar);};
 c.dictSafe=fn=>async(...args)=>{try{return await fn(...args);}catch(error){errors.push(error);}};
 c.leaveSentenceDrafts=async()=>{};
 vm.runInContext(lexiconSource.slice(lexiconSource.indexOf('function wireExampleSelection('),lexiconSource.indexOf('function renderLexemeExamples(')),c);
 c.wireExampleSelection(section,[{id:'a'},{id:'b'},{id:'c'}],unlink);
 const all=bar=>bar.querySelector('[data-example-all]'),button=bar=>bar.querySelector('[data-example-unlink-selected]');
 return {c,section,bars,boxes,single,states,prepared,errors,all,button};
}

test('preparing a paging row preserves original controls and is idempotent',()=>{
 const {evidence}=helper(),{bar,previous,next}=pagingBar(3);let navigated=false;next.onclick=()=>navigated=true;
 evidence.preparePage(bar);const paging=bar.querySelector(':scope>.example-paging-controls');
 assert.deepEqual(paging.children,[previous,next]);assert.equal(bar.children.length,1);
 evidence.preparePage(bar);assert.equal(bar.children.length,1);assert.equal(bar.children[0],paging);
 next.onclick();assert.equal(navigated,true);
});

test('a single page shows selection actions only while selected or busy',()=>{
 const {evidence}=helper(),{bar}=pagingBar();evidence.preparePage(bar);bar.insertAdjacentHTML('beforeend','selection controls');
 const paging=bar.querySelector(':scope>.example-paging-controls'),label=bar.querySelector('.example-select-all'),unlink=bar.querySelector('[data-example-unlink-selected]');
 evidence.pageState(bar,0,false);assert.equal(bar.hidden,true);assert.equal(paging.hidden,true);assert.equal(label.hidden,true);assert.equal(unlink.hidden,true);
 evidence.pageState(bar,2,false);assert.equal(bar.hidden,false);assert.equal(paging.hidden,true);assert.equal(label.hidden,false);assert.equal(unlink.hidden,false);
 evidence.pageState(bar,0,true);assert.equal(bar.hidden,false);assert.equal(paging.hidden,true);assert.equal(unlink.hidden,false);
 evidence.pageState(bar,0,false);assert.equal(bar.hidden,true);assert.equal(label.hidden,true);
});

test('multiple pages keep navigation visible without exposing inactive batch controls',()=>{
 const {evidence}=helper(),{bar}=pagingBar('4');evidence.preparePage(bar);bar.insertAdjacentHTML('beforeend','selection controls');
 const paging=bar.querySelector(':scope>.example-paging-controls'),unlink=bar.querySelector('[data-example-unlink-selected]');
 evidence.pageState(bar,0,false);assert.equal(bar.hidden,false);assert.equal(paging.hidden,false);assert.equal(unlink.hidden,true);
 evidence.pageState(bar,1,false);assert.equal(bar.hidden,false);assert.equal(paging.hidden,false);assert.equal(unlink.hidden,false);
 evidence.pageState(bar,0,false);assert.equal(bar.hidden,false);assert.equal(paging.hidden,false);assert.equal(unlink.hidden,true);
});

test('page selection sends shared selected and busy states to both action rows',()=>{
 const s=selection(async()=>{});assert.deepEqual(s.prepared,s.bars);
 assert.deepEqual(s.states,[{bar:0,selected:0,busy:false},{bar:1,selected:0,busy:false}]);
 assert.ok(s.bars.every(bar=>bar.hidden));
 s.boxes[1].checked=true;s.boxes[1].onchange();
 assert.deepEqual(s.states.slice(-2),[{bar:0,selected:1,busy:false},{bar:1,selected:1,busy:false}]);
 assert.ok(s.bars.every(bar=>!bar.hidden&&s.all(bar).indeterminate&&!s.button(bar).disabled));
 s.all(s.bars[0]).onchange({target:{checked:true}});assert.equal(s.boxes.filter(box=>box.checked).length,3);assert.equal(s.all(s.bars[1]).checked,true);
 s.all(s.bars[1]).onchange({target:{checked:false}});assert.ok(s.bars.every(bar=>bar.hidden));
 assert.deepEqual(s.states.slice(-2),[{bar:0,selected:0,busy:false},{bar:1,selected:0,busy:false}]);
});

test('failed pending unlink keeps selected rows and visible actions available for retry',async()=>{
 let reject,started,attempt=0;const submitted=[],began=new Promise(resolve=>started=resolve);
 const s=selection(rows=>{submitted.push(Array.from(rows,row=>row.id));attempt++;started();return attempt===1?new Promise((resolve,fail)=>reject=fail):Promise.resolve();});
 for(const i of [0,2]){s.boxes[i].checked=true;s.boxes[i].onchange();}
 const pending=s.button(s.bars[0]).onclick();await began;
 assert.deepEqual(s.states.slice(-2),[{bar:0,selected:2,busy:true},{bar:1,selected:2,busy:true}]);
 assert.ok(s.bars.every(bar=>!bar.hidden&&s.all(bar).disabled&&s.button(bar).disabled));
 await s.button(s.bars[1]).onclick();assert.equal(attempt,1);
 reject(Error('conflict'));await pending;
 assert.equal(s.errors.length,1);assert.deepEqual(s.boxes.map(box=>box.checked),[true,false,true]);
 assert.ok(s.bars.every(bar=>!bar.hidden&&!s.button(bar).disabled));
 await s.button(s.bars[1]).onclick();assert.deepEqual(submitted,[['a','c'],['a','c']]);
});

test('a single-row unlink exposes its pending state without manufacturing a selection',async()=>{
 let finish,rows,started;const began=new Promise(resolve=>started=resolve),s=selection(items=>{rows=Array.from(items,row=>row.id);started();return new Promise(resolve=>finish=resolve);});
 const pending=s.single.onclick();await began;assert.deepEqual(rows,['b']);
 assert.ok(s.boxes.every(box=>!box.checked));assert.ok(s.bars.every(bar=>!bar.hidden));
 assert.deepEqual(s.states.slice(-2),[{bar:0,selected:0,busy:true},{bar:1,selected:0,busy:true}]);
 finish();await pending;
 assert.ok(s.bars.every(bar=>bar.hidden));assert.equal(s.single.disabled,false);
 assert.deepEqual(s.states.slice(-2),[{bar:0,selected:0,busy:false},{bar:1,selected:0,busy:false}]);
});
