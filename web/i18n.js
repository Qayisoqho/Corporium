/* UI localization is applied to authored messages, never to rendered corpus data. */
(()=>{
 'use strict';
 const supported=new Set(['zh-CN','en']),key='corporium-ui-language';
 const valid=value=>supported.has(value)?value:null;
 const cookie=()=>{try{return valid(document.cookie.split(';').map(x=>x.trim()).find(x=>x.startsWith(key+'='))?.slice(key.length+1));}catch{return null;}};
 let saved=null;try{saved=valid(localStorage.getItem(key));}catch{}
 let requested=null;try{requested=valid(new URL(location.href).searchParams.get('ui'));}catch{}
 const locale=valid(document.documentElement.dataset.uiLanguage)||requested||saved||cookie()||'zh-CN';
 document.documentElement.dataset.uiLanguage=locale;
 document.documentElement.lang=locale;
 const english=locale==='en';
 const catalog=()=>globalThis.CorporiumMessages||{messages:{},terms:{},phrases:{}};
 const own=(map,key)=>Object.hasOwn(map,key)?map[key]:undefined;
 const singular={sentences:'sentence',examples:'example',items:'item',rows:'row',results:'result',characters:'character',words:'word',cells:'cell',tiers:'tier',groups:'group',backups:'backup',links:'link',entries:'entry',languages:'language',files:'file',intervals:'interval',seconds:'second',steps:'step',matches:'match',candidates:'candidate',definitions:'definition',occurrences:'occurrence',tokens:'token'};
 const pluralNoun=/^ (sentences|examples|items|rows|results|characters|words|cells|tiers|groups|backups|links|entries|languages|files|intervals|seconds|steps|matches|candidates|definitions|occurrences|tokens)\b/u;
 const formats=new WeakMap();
 function prepare(template,plurals){
  const split=template.split(/⟦(\d+)⟧/u),parts=[],counts=[];
  for(let i=1;i<split.length;i+=2){
   const index=Number(split[i]),text=split[i+1],noun=plurals?pluralNoun.exec(text):null;
   const part={index,text};if(noun){part.one=' '+singular[noun[1]]+text.slice(noun[0].length);counts.push(part);}
   parts.push(part);
  }
  return {template,start:split[0],parts,counts};
 }
 function format(plan,args){
  if(!plan.parts.length)return plan.start;
  // Resolve only authored plural slots before coercing or inserting values.
  // User text is never parsed, translated, or used to construct executable code.
  const choices=plan.counts.length?plan.counts.map(part=>Number(args[part.index])===1):null;
  let value=plan.start,count=0;
  for(const part of plan.parts){value+=String(args[part.index]);value+=part.one!==undefined?(choices[count++]?part.one:part.text):part.text;}
  return value;
 }
 function expand(template,args,plurals=false){return format(prepare(template,plurals),args);}
 function f(id,args=[]){
  const record=own(catalog().messages,id);
  if(!record)return undefined;
  if(typeof args==='function')args=args();
  const template=english?record.en:record.zh;
  let plan=formats.get(record);if(!plan||plan.template!==template){plan=prepare(template,english);formats.set(record,plan);}
  return format(plan,args);
 }
 function term(id,original){
  const record=own(catalog().terms,id);
  return english&&record?record.en:original??record?.zh??'';
 }
 function ui(zh,en){return english?en:zh;}
 function phrase(value){return english?(own(catalog().phrases,value)??value):value;}
 let indices=null;
 function termIndices(){
  if(indices)return indices;
  const ipa=new Map(),reference=new Map(),categories=new Map();
  for(const [id,t] of Object.entries(catalog().terms)){
   if(t.category?.startsWith('IPA 名称')&&t.symbol)ipa.set(t.symbol.replace(/^◌/u,''),id);
   if(t.category?.startsWith('语法参考／')&&t.symbol)reference.set(t.symbol.toUpperCase(),id);
   if(t.category==='语法参考／分类')categories.set(t.zh,id);
  }
  indices={ipa,reference,categories};return indices;
 }
 function ipa(symbol,original){return term(termIndices().ipa.get(symbol),original);}
 function reference(row){
  if(!english)return row;
  return {...row,source_description:row.description,source_category:row.category,
   description:term(termIndices().reference.get(String(row.symbol).toUpperCase()),row.description),
   category:term(termIndices().categories.get(row.category),phrase(row.category))};
 }
 // Called once, before application scripts or API data exist on the page.
 // Dynamic content must use f()/term(); it is never scanned or observed.
 function localizeStatic(root){
  if(english){
   const walker=document.createTreeWalker(root,NodeFilter.SHOW_TEXT);
   for(let node=walker.nextNode();node;node=walker.nextNode()){
    if(node.parentElement?.closest('script,style,code,pre'))continue;
    const text=node.nodeValue,trim=text.trim(),translated=own(catalog().phrases,trim);
    if(translated!==undefined&&translated!==trim){
     if(node.parentElement?.tagName==='OPTION'&&!node.parentElement.hasAttribute('value'))node.parentElement.setAttribute('value',trim);
     node.nodeValue=text.replace(trim,translated);
    }
   }
   for(const node of root.querySelectorAll('[title],[placeholder],[aria-label],[aria-description],[alt]')){
    for(const attr of ['title','placeholder','aria-label','aria-description','alt'])if(node.hasAttribute(attr))node.setAttribute(attr,phrase(node.getAttribute(attr)));
   }
  }
  document.documentElement.dataset.uiReady='true';
 }
 function persist(value){
  if(!valid(value))throw Error('Unsupported interface language');
  let stored=false;
  try{localStorage.setItem(key,value);stored=localStorage.getItem(key)===value;}catch{}
  try{document.cookie=key+'='+value+'; Path=/; SameSite=Strict; Max-Age=31536000';stored=cookie()===value||stored;}catch{}
  return stored;
 }
 persist(locale);
 // Explicit request metadata keeps API messages in the selected UI language
 // even when the browser blocks persistent cookies or local storage.
 if(typeof globalThis.fetch==='function'){
  const fetch=globalThis.fetch;
  globalThis.fetch=function(input,init){
   try{
    const url=new URL(typeof input==='string'||input instanceof URL?input:input.url,location.href);
    if(url.origin===location.origin&&(url.pathname.startsWith('/api/')||['/licenses/catalog','/desktop-status'].includes(url.pathname))){
     const headers=new Headers(init?.headers??input?.headers);headers.set('X-Corporium-UI-Language',locale);
     return fetch.call(this,input,{...init,headers});
    }
   }catch{}
   return fetch.call(this,input,init);
  };
 }
 const views=new Map();
 function registerView(name,adapter){views.set(name,adapter);return adapter;}
 function captureView(workspace){return Object.fromEntries([...views].filter(([name])=>name.split(':')[0]===workspace).map(([name,adapter])=>[name,adapter.capture()]));}
 async function restoreView(state){for(const [name,value] of Object.entries(state||{})){const adapter=views.get(name);if(adapter)await adapter.restore(value,()=>true);}}
 globalThis.CorporiumI18n={locale,english,f,term,ui,phrase,ipa,reference,localizeStatic,persist,valid,expand,registerView,captureView,restoreView,has:id=>Object.hasOwn(catalog().messages,id)};
})();
