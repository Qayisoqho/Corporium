const test=require('node:test'),assert=require('node:assert/strict'),vm=require('node:vm'),fs=require('node:fs'),source=fs.readFileSync('web/ipa-keyboard.js','utf8');
test('normal typing captures input selections without checking layout or writing keyboard DOM',()=>{
 const target={isConnected:true,selectionStart:3,selectionEnd:7,selectionDirection:'backward',getClientRects(){throw Error('typing must not force layout');}},c={target,editable:t=>t,selection:null,valid(){throw Error('typing must not check layout');},el(){throw Error('typing must not change keyboard DOM');}};
 vm.createContext(c);vm.runInContext(source.slice(source.indexOf(' function remember('),source.indexOf(" document.addEventListener('focusin'")),c);c.remember();assert.deepEqual(JSON.parse(JSON.stringify(c.selection)),{start:3,end:7,direction:'backward'});
 target.isConnected=false;c.selection=null;c.remember();assert.equal(c.selection,null);
});
test('rich text caret snapshots still clone the live range without changing focus or content',()=>{
 const cloned={},node={},c={target:{isConnected:true,isContentEditable:true,contains:n=>n===node},editable:t=>t,selection:null,getSelection:()=>({rangeCount:1,anchorNode:node,focusNode:node,getRangeAt:()=>({cloneRange:()=>cloned})})};
 vm.createContext(c);vm.runInContext(source.slice(source.indexOf(' function remember('),source.indexOf(" document.addEventListener('focusin'")),c);c.remember();assert.equal(c.selection,cloned);
});
test('ordinary text edits do not reposition the tool, while modals, visibility changes and target removal do',()=>{
 const target={},host={contains:n=>n==='keyboard'},c={host,target};vm.createContext(c);vm.runInContext(source.slice(source.indexOf(' function layoutChanged('),source.indexOf(' new MutationObserver(records=>{if(layoutChanged')),c);
 const element=(relevant=false,contains=false)=>({nodeType:1,matches:()=>relevant,querySelector:()=>null,contains:n=>contains&&n===target}),record=(added=[],removed=[])=>({type:'childList',target:'outside',addedNodes:added,removedNodes:removed});
 assert.equal(c.layoutChanged([record([{nodeType:3}])]),false);assert.equal(c.layoutChanged([record([element()])]),false);assert.equal(c.layoutChanged([{type:'attributes',target:'keyboard'}]),false);
 assert.equal(c.layoutChanged([{type:'attributes',target:'dialog'}]),true);assert.equal(c.layoutChanged([record([element(true)])]),true);assert.equal(c.layoutChanged([record([],[element(false,true)])]),true);
});
test('keyboard avoids visible inspector save footers and fixed add buttons, including modal ownership',()=>{
 const make=(footer,position='static',visible=true)=>({footer,position,getClientRects:()=>visible?[{}]:[],matches:()=>footer,getBoundingClientRect(){return this;}});
 const footer=make(true),add=make(false,'fixed'),ordinary=make(false),hidden=make(true,'static',false),nodes=[footer,add,ordinary,hidden];let active=null,selector='';
 const c={document:{querySelectorAll:s=>(selector=s,nodes)},modal:()=>active,getComputedStyle:n=>({visibility:'visible',position:n.position})};vm.createContext(c);vm.runInContext(source.slice(source.indexOf(' function floatingButtons('),source.indexOf(' function position(')),c);
 assert.deepEqual(Array.from(c.floatingButtons()),[footer,add]);assert.match(selector,/dialog\[open\]:not\(\[hidden\]\) \.dialog-bottom/);
 active={contains:n=>n===footer};assert.deepEqual(Array.from(c.floatingButtons()),[footer]);
});
