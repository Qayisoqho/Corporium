const test=require('node:test'),assert=require('node:assert/strict'),vm=require('node:vm'),fs=require('node:fs');
const source=fs.readFileSync(require.resolve('../web/app.js'),'utf8').split('// Existing action-error outlets')[0];
function harness(){
 const dialogs=[];
 class Element{
  constructor(tag){this.tag=tag;this.children=[];this.handlers={};this.dataset={};this.isConnected=true;}
  get firstChild(){return this.children[0];}
  setAttribute(){} append(...nodes){this.children.push(...nodes);} addEventListener(name,fn){this.handlers[name]=fn;}
  showModal(){this.open=true;} close(){this.open=false;} remove(){this.isConnected=false;} focus(){} select(){}
 }
 const s={Promise,document:{activeElement:new Element('input'),createElement:tag=>{const e=new Element(tag);if(tag==='dialog')dialogs.push(e);return e;},body:new Element('body')}};
 vm.createContext(s);vm.runInContext(source,s);return {s,dialogs};
}
test('confirmation waits for choice; Cancel and Escape resolve false; queued dialogs open one at a time',async()=>{
 const {s,dialogs}=harness();const a=vm.runInContext("corporiumConfirm('删除？')",s),b=vm.runInContext("corporiumConfirm('替换？')",s);
 await Promise.resolve();assert.equal(dialogs.length,1);assert.equal(dialogs[0].open,true);
 dialogs[0].children.at(-1).children[0].onclick();assert.equal(await a,false);await Promise.resolve();
 assert.equal(dialogs.length,2);let prevented=false;dialogs[1].handlers.cancel({preventDefault(){prevented=true;}});assert.equal(await b,false);assert.ok(prevented);
});
test('prompt cancellation is null and affirmative confirmation is true',async()=>{
 const {s,dialogs}=harness();let p=vm.runInContext("corporiumPrompt('名称','原名')",s);await Promise.resolve();dialogs[0].handlers.cancel({preventDefault(){}});assert.equal(await p,null);
 p=vm.runInContext("corporiumConfirm('继续？')",s);await Promise.resolve();dialogs[1].children.at(-1).children[1].onclick();assert.equal(await p,true);
});
test('dirty editor cancel is prevented immediately and only closes after approval',async()=>{
 const {s,dialogs}=harness();let closed=0,prevented=0;const editor={open:true,dataset:{},close(){closed++;}};
 s.event={target:{closest:()=>editor},preventDefault(){prevented++;}};
 vm.runInContext("guardDialogDiscard(event,true,'放弃？')",s);assert.equal(prevented,1);assert.equal(closed,0);await Promise.resolve();dialogs[0].children.at(-1).children[0].onclick();await new Promise(setImmediate);assert.equal(closed,0);
 vm.runInContext("guardDialogDiscard(event,true,'放弃？')",s);await Promise.resolve();dialogs[1].children.at(-1).children[1].onclick();await new Promise(setImmediate);assert.equal(closed,1);
});
