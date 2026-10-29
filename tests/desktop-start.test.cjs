const test=require('node:test'),assert=require('node:assert/strict'),vm=require('node:vm'),fs=require('node:fs');
const source=fs.readFileSync('web/i18n-settings.js','utf8');
function startup(locale='zh-CN',ready=true,error=false){
 const node=()=>({children:[],append(...children){this.children.push(...children);},setAttribute(name,value){this[name]=value;}});
 const ids={'startup-language':node(),'desktop-recent':node(),'desktop-error':node()},events={},saved=[],calls=[];
 const document={documentElement:{dataset:{desktop:'true'}},createElement:node,createTextNode:text=>({textContent:text}),getElementById:id=>ids[id],querySelectorAll:()=>[]};
 const c={document,URL,location:{href:'http://corporium.local/',replace(url){calls.push(['reload',url]);}},sessionStorage:{getItem:()=>null,setItem(){}},CorporiumI18n:{locale,ui:(zh,en)=>locale==='en'?en:zh,valid:x=>['zh-CN','en'].includes(x),persist:x=>{saved.push(x);return true;},captureView:()=>({})},addEventListener:(name,fn)=>{events[name]=fn;}};
 c.window=c;c.bridge={set_ui_language:async x=>{calls.push(['bridge',x]);return error?{error:'write failed'}:{ok:true};}};
 if(ready)c.pywebview={api:c.bridge};vm.createContext(c);vm.runInContext(source,c);
 const field=ids['startup-language'].children[0],select=field.children[1];return {c,ids,field,select,events,saved,calls};
}
test('first-run language control is bilingual, mounted at the top and waits for native readiness',()=>{
 const s=startup('zh-CN',false);assert.equal(s.field.children[0].textContent,'语言 / Language');assert.equal(s.select.value,'zh-CN');assert.equal(s.select.disabled,true);
 s.c.pywebview={api:s.c.bridge};s.events.pywebviewready();assert.equal(s.select.disabled,false);
});
test('startup switches both directions through native persistence before reloading',async()=>{
 for(const [before,after] of [['zh-CN','en'],['en','zh-CN']]){
  const s=startup(before);s.select.value=after;const promise=s.select.onchange();assert.equal(s.select.disabled,true);await promise;
  assert.deepEqual(s.calls,[['bridge',after],['reload','http://corporium.local/']]);assert.deepEqual(s.saved,[after]);assert.equal(s.select.disabled,false);
 }
});
test('failed desktop preference write stays on startup and restores the current selection',async()=>{
 const s=startup('zh-CN',true,true);s.select.value='en';await s.select.onchange();
 assert.deepEqual(s.saved,[]);assert.deepEqual(s.calls,[['bridge','en']]);assert.equal(s.select.value,'zh-CN');assert.equal(s.select.disabled,false);assert.equal(s.ids['desktop-error'].textContent,'write failed');
});
