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

const html=fs.readFileSync('web/desktop-start.html','utf8'),bootstrap=html.match(/<script>([\s\S]*?)<\/script>/)[1];
function preferences(saved={}){
 const values={},root={dataset:{theme:'docoid'},style:{setProperty:(name,value)=>values[name]=value}};
 const context={document:{documentElement:root},localStorage:{getItem:key=>saved[key]??null}};
 vm.createContext(context);vm.runInContext(bootstrap,context);return {root,values};
}
test('startup applies local font order, scale and density without project APIs',()=>{
 const s=preferences({'corporium-typography':JSON.stringify({uiFonts:['Junicode','Microsoft JhengHei'],uiVariant:'bolditalic'}),'ordos-text-scale':'1.5','corporium-density':'compact'});
 assert.equal(s.values['--global-font-stack'],'"Junicode","Microsoft JhengHei",sans-serif');
 assert.equal(s.values['--ui-weight'],'700');assert.equal(s.values['--ui-style'],'italic');assert.equal(s.values['--text-scale'],'1.5');assert.equal(s.root.dataset.density,'compact');
});
test('startup accepts an installed family and retains safe fallbacks for project-only fonts',()=>{
 const family='STIX Two Text',id='systemfont-'+Buffer.from(family).toString('hex'),folder='localfont-'+'a'.repeat(24);
 const s=preferences({'corporium-typography':JSON.stringify({uiFonts:[id,folder,'sans-serif']})});
 assert.equal(s.values['--global-font-stack'],'"STIX Two Text","'+folder+'",sans-serif');
});
test('startup handles legacy defaults, corrupt preferences and unavailable storage',()=>{
 const old=preferences({'corporium-typography':JSON.stringify({uiFonts:['Noto Sans','Source Han Sans SC']})});
 assert.equal(old.values['--global-font-stack'],'"STIX Two Text","Microsoft JhengHei",sans-serif');
 assert.doesNotThrow(()=>preferences({'corporium-typography':'{bad json'}));
 assert.doesNotThrow(()=>vm.runInNewContext(bootstrap,{document:{documentElement:{}},localStorage:{getItem(){throw Error('blocked');}}}));
 assert.equal(preferences({'ordos-theme':'untrusted','ordos-text-scale':'999'}).root.dataset.theme,'docoid');
});
