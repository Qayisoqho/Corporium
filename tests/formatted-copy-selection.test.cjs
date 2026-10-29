const test=require('node:test'),assert=require('node:assert/strict'),fs=require('node:fs'),vm=require('node:vm');
function setup(shared=true){
 const nodes=[],events=new Map();
 function element(tag='span'){
  const names=new Set(),listeners=new Map(),el={tagName:tag.toUpperCase(),dataset:{},checked:false,disabled:false,isConnected:true,children:[],classList:{add:(...v)=>v.forEach(x=>names.add(x)),remove:(...v)=>v.forEach(x=>names.delete(x)),contains:x=>names.has(x)},setAttribute(){},addEventListener:(n,f)=>listeners.set(n,f),removeEventListener:(n,f)=>{if(listeners.get(n)===f)listeners.delete(n);},remove(){this.isConnected=false;this.children.forEach(c=>c.remove());},prepend(c){this.children.unshift(c);},append(...c){this.children.push(...c);},fire(){this.onchange?.();listeners.get('change')?.();},querySelector(){return null;}};
  Object.defineProperty(el,'className',{get:()=>[...names].join(' '),set:v=>{names.clear();v.split(' ').forEach(x=>names.add(x));}});nodes.push(el);return el;
 }
 const header=element(),box=shared?element('input'):null,entry=element(),card=element('section');card.dataset.formattedSource='one';card.closest=()=>entry;entry.querySelector=selector=>selector.includes('data-pick')?box:header;card.querySelector=()=>header;
 if(box){box.dataset.pick='source';box.checked=true;header.append(box);}
 const c={window:{CorporiumSentenceSelection:{lock(value){c.locked=value;if(box)box.disabled=value;}}},document:{documentElement:{classList:{add(){},remove(){}}},createElement:element,addEventListener:(n,f)=>events.set(n,f),querySelectorAll:selector=>nodes.filter(n=>n.isConnected&&selector.split(',').some(s=>n.classList.contains(s.trim().slice(1))))},core:{build:()=>({html:'html',plain:'plain',summary:{sentences:1,warnings:[]}}),numberSelection:x=>x},records:new Map(),groupKeys:new WeakMap(),boxes:new WeakMap(),borrowed:new Map(),selected:new Set(),active:false,busy:false,owner:null,pageKeys:'',inlineDrafts:new Map(),cards:()=>[card],scope:()=>null,groupFor:()=>null,labelFor:()=>'(1)',updateControls(){},itemFor:()=>({}),$(){},corporiumStatus(){},navigator:{clipboard:{write:async()=>{throw Error('denied');}}},ClipboardItem:class{},Blob:class{},Event:class{}};
 if(box)box.onchange=()=>events.get('corporium-sentence-selection')?.();
 vm.createContext(c);const s=fs.readFileSync('web/formatted-copy.js','utf8');vm.runInContext(s.slice(s.indexOf(' function finish()'),s.indexOf(' function controlsFor(')),c);
 return {c,box,card,header,nodes,events};
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
