const test=require('node:test'),assert=require('node:assert/strict'),fs=require('node:fs'),vm=require('node:vm');
function setup(shared=true,{grouped=false}={}){
 const library=shared==='library',libraryChosen=new Set(library?['source']:[]),cards=[],sharedBoxes=[];
 const nodes=[],events=new Map();
 function element(tag='span'){
  const names=new Set(),listeners=new Map(),el={tagName:tag.toUpperCase(),dataset:{},checked:false,disabled:false,isConnected:true,children:[],classList:{add:(...v)=>v.forEach(x=>names.add(x)),remove:(...v)=>v.forEach(x=>names.delete(x)),contains:x=>names.has(x)},setAttribute(){},addEventListener:(n,f)=>listeners.set(n,f),removeEventListener:(n,f)=>{if(listeners.get(n)===f)listeners.delete(n);},remove(){this.isConnected=false;this.children.forEach(c=>c.remove());},prepend(c){this.children.unshift(c);},append(...c){this.children.push(...c);},dispatchEvent(event){this.onchange?.(event);listeners.get(event.type)?.(event);return true;},fire(){this.dispatchEvent({type:'change'});},querySelector(){return null;}};
  Object.defineProperty(el,'className',{get:()=>[...names].join(' '),set:v=>{names.clear();v.split(' ').forEach(x=>names.add(x));}});nodes.push(el);return el;
 }
 const header=element(),box=shared?element('input'):null,entry=element(),card=element('section');card.dataset.formattedSource='one';card.closest=()=>entry;entry.querySelector=selector=>selector.includes('data-pick')?box:header;card.querySelector=()=>header;
 if(box){if(library){box.dataset.groupSelect='source';sharedBoxes.push(box);}else box.dataset.pick='source';box.checked=true;header.append(box);}cards.push(card);
 const c={window:{CorporiumSentenceSelection:{lock(value){c.locked=value;if(box&&!library)box.disabled=value;}}},document:{documentElement:{classList:{add(){},remove(){}}},createElement:element,addEventListener:(n,f)=>events.set(n,f),querySelectorAll:selector=>nodes.filter(n=>n.isConnected&&selector.split(',').some(s=>n.classList.contains(s.trim().slice(1))))},core:{build:()=>({html:'html',plain:'plain',summary:{sentences:1,warnings:[]}}),numberSelection:x=>x},records:new Map(),groupKeys:new WeakMap(),boxes:new WeakMap(),borrowed:new Map(),selected:new Set(),active:false,busy:false,owner:null,pageKeys:'',inlineDrafts:new Map(),cards:()=>cards,scope:()=>null,groupFor:()=>null,labelFor:()=>'(1)',updateControls(){},itemFor:()=>({}),$(){},corporiumStatus(){},navigator:{clipboard:{write:async()=>{throw Error('denied');}}},ClipboardItem:class{},Blob:class{},Event:class{constructor(type){this.type=type;}}};
 const publishLibrary=()=>{for(const b of sharedBoxes)b.checked=libraryChosen.has(b.dataset.groupSelect);c.libraryCount=libraryChosen.size;events.get('corporium-library-selection')?.();};
 const wire=b=>{b.onchange=()=>{b.checked?libraryChosen.add(b.dataset.groupSelect):libraryChosen.delete(b.dataset.groupSelect);publishLibrary();};};
 if(library){let locked=false;c.window.CorporiumLibrarySelection={lock(value){if(value===locked)return;locked=value;c.libraryLocked=value;sharedBoxes.forEach(b=>b.disabled=value);publishLibrary();}};wire(box);}else if(box)box.onchange=()=>events.get('corporium-sentence-selection')?.();
 const group=grouped?element('article'):null,groupHeading=element('strong');let groupBox;
 if(group){group.querySelector=selector=>selector.includes('formatted-copy-group-pick')?groupBox:{querySelector:()=>groupHeading};groupHeading.prepend=b=>{groupBox=b;};c.groupFor=value=>value.group===group?group:null;card.group=group;}
 const addLibraryCard=(key,id,inGroup=true)=>{const b=element('input'),e=element('article'),n=element('section');b.dataset.groupSelect=id;b.checked=libraryChosen.has(id);n.dataset.formattedSource=key;n.group=inGroup?group:null;n.closest=()=>e;e.querySelector=selector=>selector.includes('data-group-select')?b:header;n.querySelector=()=>header;cards.push(n);sharedBoxes.push(b);wire(b);return {box:b,card:n};};
 vm.createContext(c);const s=fs.readFileSync('web/formatted-copy.js','utf8');vm.runInContext(s.slice(s.indexOf(' function finish()'),s.indexOf(' function controlsFor(')),c);
 return {c,box,card,header,nodes,events,libraryChosen,publishLibrary,addLibraryCard,groupBox:()=>groupBox};
}
test('formatted selection reuses the text checkbox and adopts existing choices',async()=>{
 const {c,box,card,nodes,events}=setup();await c.clickCopy(null);assert.equal(c.boxes.get(card),box);assert.equal(c.selected.size,1);assert.equal(nodes.filter(n=>n.tagName==='INPUT').length,1);
 box.checked=false;box.fire();assert.equal(c.selected.size,0);
 box.checked=true;events.get('corporium-sentence-selection')();assert.equal(c.selected.size,1);
 c.finish();assert.equal(box.isConnected,true);assert.equal(box.checked,true);assert.equal(box.classList.contains('formatted-copy-pick'),false);assert.equal(c.locked,false);
 await c.clickCopy(null);assert.equal(c.boxes.get(card),box);assert.equal(c.selected.size,1);
});
test('failed clipboard writes preserve shared selection and unlock text operations',async()=>{
 const {c,box}=setup();await c.clickCopy(null);await assert.rejects(c.clickCopy(null),/denied/);
 assert.equal(c.active,true);assert.equal(c.selected.size,1);assert.equal(box.isConnected,true);assert.equal(box.checked,true);assert.equal(box.disabled,false);assert.equal(c.busy,false);
});
test('successful clipboard writes retain text-operation selection after copy mode ends',async()=>{
 const {c,box}=setup();c.navigator.clipboard.write=async()=>{};await c.clickCopy(null);await c.clickCopy(null);
 assert.equal(c.active,false);assert.equal(box.checked,true);assert.equal(box.isConnected,true);assert.equal(box.disabled,false);
});
test('other sentence views place one temporary checkbox in the header without a number gutter',async()=>{
 const {c,header,nodes}=setup(false);await c.clickCopy(null);
 assert.equal(header.children[0].className,'formatted-copy-choice');assert.equal(nodes.some(n=>n.classList.contains('formatted-copy-gutter')),false);
 c.finish();assert.equal(header.children[0].isConnected,false);
 await c.clickCopy(null);assert.equal(nodes.filter(n=>n.tagName==='INPUT'&&n.isConnected).length,1);
});

test('library copy borrows its ordinary checkbox while grouping is active and retains the choice on cancel',async()=>{
 const h=setup('library');h.c.$=()=>({getAttribute:()=> 'true'});
 await h.c.clickCopy(null);assert.equal(h.c.boxes.get(h.card),h.box);assert.equal(h.nodes.filter(n=>n.tagName==='INPUT').length,1);assert.equal(h.c.selected.size,1);
 h.box.checked=false;h.box.fire();assert.equal(h.libraryChosen.size,0);assert.equal(h.c.selected.size,0);
 h.box.checked=true;h.box.fire();h.c.finish();assert.equal(h.libraryChosen.size,1);assert.equal(h.box.checked,true);assert.equal(h.box.isConnected,true);
});
test('a pending or failed library copy locks grouping actions and preserves ordinary choices',async()=>{
 const h=setup('library');let reject;h.c.navigator.clipboard.write=()=>new Promise((_,r)=>reject=r);await h.c.clickCopy(null);
 const copying=h.c.clickCopy(null);assert.equal(h.c.libraryLocked,true);assert.equal(h.box.disabled,true);
 reject(Error('denied'));await assert.rejects(copying,/denied/);assert.equal(h.c.active,true);assert.equal(h.c.libraryLocked,false);assert.equal(h.box.disabled,false);assert.equal(h.libraryChosen.size,1);
});
test('copying a library group updates ordinary choices and includes each visible occurrence in display order',async()=>{
 const h=setup('library',{grouped:true});h.libraryChosen.clear();h.box.checked=false;
 const second=h.addLibraryCard('two','second'),duplicate=h.addLibraryCard('three','source',false);h.libraryChosen.add('off-page');
 let copied;h.c.core.build=items=>{copied=items;return {html:'html',plain:'plain',summary:{sentences:items.length,warnings:[]}};};h.c.itemFor=c=>({key:c.dataset.formattedSource});h.c.navigator.clipboard.write=async()=>{};
 await h.c.clickCopy(null);h.groupBox().checked=true;h.groupBox().fire();
 assert.equal(h.libraryChosen.size,3);assert.equal(h.box.checked,true);assert.equal(second.box.checked,true);assert.equal(duplicate.box.checked,true);assert.equal(h.c.selected.size,3);assert.equal(h.groupBox().indeterminate,false);
 await h.c.clickCopy(null);assert.deepEqual(Array.from(copied,x=>x.key),['one','two','three']);assert.equal(h.libraryChosen.size,3);assert.equal(h.box.isConnected,true);assert.equal(h.c.active,false);
 await h.c.clickCopy(null);h.libraryChosen.clear();h.publishLibrary();assert.equal(h.c.selected.size,0);assert.equal(h.groupBox().checked,false);assert.equal(h.groupBox().indeterminate,false);h.c.finish();
});
test('all-language library selection remains read-only and cannot enable group creation',()=>{
 const nodes=new Map(),node=id=>{if(!nodes.has(id))nodes.set(id,{setAttribute(){},querySelectorAll:()=>[]});return nodes.get(id);};
 const c={selectionBar:{},selectButton:{setAttribute(){}},selecting:true,selectionLocked:false,chosen:new Map([['a',{language_id:'one'}],['b',{language_id:'two'}]]),activeLanguage:'all',$:node,document:{dispatchEvent(){}},Event:class{}};
 vm.createContext(c);const src=fs.readFileSync('web/example-groups.js','utf8');vm.runInContext(src.slice(src.indexOf(' function selectedState(){'),src.indexOf(' window.CorporiumLibrarySelection=')),c);c.selectedState();assert.equal(node('example-group-create').disabled,true);assert.equal(node('example-group-clear').disabled,false);
});
