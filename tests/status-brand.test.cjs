const test=require('node:test'),assert=require('node:assert/strict'),fs=require('node:fs'),vm=require('node:vm');
const workbench=fs.readFileSync('web/workbench.js','utf8');
const licenses=fs.readFileSync('web/license-notices.js','utf8');

// The small DOM keeps real node identities, handlers and parsed descendants.
// Only the actual status-bar construction and complete license viewer execute.
class Element {
 constructor(tag='div'){
  this.tagName=tag.toUpperCase();this.children=[];this.parentElement=null;this.className='';this.attributes={};this.hidden=false;this.disabled=false;this.open=false;this.clicks=0;this.shows=0;this.closes=0;this.listeners=new Map();this._text='';
  this.classList={add:(...names)=>this.className=[...new Set(this.className.split(/\s+/).filter(Boolean).concat(names))].join(' ')};
 }
 append(...nodes){for(const node of nodes){node.remove();node.parentElement=this;this.children.push(node);}}
 prepend(...nodes){for(const node of [...nodes].reverse()){node.remove();node.parentElement=this;this.children.unshift(node);}}
 remove(){if(this.parentElement){const siblings=this.parentElement.children;siblings.splice(siblings.indexOf(this),1);this.parentElement=null;}}
 replaceChildren(...nodes){for(const child of [...this.children])child.remove();this._text='';this.append(...nodes);}
 setAttribute(name,value){this.attributes[name]=String(value);if(name==='class')this.className=String(value);if(name==='id')this.id=String(value);if(name==='hidden'||name==='disabled')this[name]=true;}
 getAttribute(name){return this.attributes[name]??null;}
 addEventListener(name,handler){if(!this.listeners.has(name))this.listeners.set(name,[]);this.listeners.get(name).push(handler);}
 click(){this.clicks++;const event={target:this,defaultPrevented:false,preventDefault(){this.defaultPrevented=true;}};for(const listener of this.listeners.get('click')||[])listener(event);return this.onclick?.(event);}
 close(){this.closes++;this.open=false;}
 showModal(){this.shows++;this.open=true;}
 matches(selector){if(selector[0]==='#')return this.id===selector.slice(1);if(selector[0]==='.')return this.className.split(/\s+/).includes(selector.slice(1));return this.tagName===selector.toUpperCase();}
 querySelectorAll(selector){return this.children.flatMap(child=>[...(child.matches(selector)?[child]:[]),...child.querySelectorAll(selector)]);}
 querySelector(selector){return this.querySelectorAll(selector)[0]||null;}
 get textContent(){return this._text+this.children.map(child=>child.textContent).join('');}
 set textContent(value){this.replaceChildren();this._text=String(value);}
 get value(){return this._value??(this.tagName==='SELECT'?this.children[0]?.value:'')??'';}
 set value(value){this._value=value;}
 set innerHTML(html){
  this.replaceChildren();const stack=[this];
  for(const token of html.matchAll(/<\/?([\w-]+)\b([^>]*)>/g)){
   if(token[0].startsWith('</')){if(stack.length>1)stack.pop();continue;}
   const node=new Element(token[1]);for(const attribute of token[2].matchAll(/([\w-]+)(?:="([^"]*)")?/g))node.setAttribute(attribute[1],attribute[2]??'');
   stack.at(-1).append(node);if(!['INPUT','BR','HR','IMG','META','LINK'].includes(node.tagName))stack.push(node);
  }
 }
}
function deferred(){let resolve,reject;const promise=new Promise((yes,no)=>{resolve=yes;reject=no;});return {promise,resolve,reject};}
const settle=()=>new Promise(setImmediate);
const catalog={about:{name:'Corporium',version:'0.9.01108',description:'A local workspace',developer:'Erči',project_url:'https://example.invalid/project',issues_url:'https://example.invalid/issues'},items:[{id:'program-license',title:'Program license'}]};
const response=body=>({ok:true,json:async()=>body});
function setup(locale='zh-CN'){
 const body=new Element('body'),brandParent=new Element('div'),brand=new Element('a'),management=new Element('dialog'),backup=new Element('div');
 brand.id='brand-home';brand.textContent='Corporium';management.id='management-dialog';backup.id='management-backup';brandParent.append(brand);body.append(brandParent,management,backup);
 const requests=[],document={body,createElement:tag=>new Element(tag),getElementById:id=>body.querySelector('#'+id)};
 const c={document,URLSearchParams,navigator:{clipboard:{writeText:async()=>{}}},ui:(zh,en)=>locale==='en'?en:zh,fetch:url=>{const request={url,...deferred()};requests.push(request);return request.promise;}};
 c.window=c;c.$=id=>document.getElementById(id);c.makeDialog=(id,html)=>{const dialog=new Element('dialog');dialog.id=id;dialog.innerHTML=html;body.append(dialog);};
 vm.createContext(c);
 const start=workbench.indexOf("const status=document.createElement('footer');"),end=workbench.indexOf('const save=status.querySelector(',start);
 assert.ok(start>=0&&end>start,'The actual status-bar construction is available');
 return {c,body,brand,brandParent,management,backup,requests,mount:()=>vm.runInContext(workbench.slice(start,end),c),loadLicenses:()=>vm.runInContext(licenses,c),get:id=>document.getElementById(id)};
}

test('the footer moves the existing home link with its click handlers before the project area',()=>{
 const s=setup('en');let homeCalls=0,listenerCalls=0;
 const navigate=event=>{event.preventDefault();homeCalls++;};s.brand.onclick=navigate;s.brand.addEventListener('click',()=>listenerCalls++);
 s.mount();const footer=s.get('app-status'),brandGroup=footer.querySelector('.app-status-brand');
 assert.equal(s.get('brand-home'),s.brand);assert.equal(s.brand.onclick,navigate);assert.equal(s.brandParent.children.length,0);
 assert.equal(footer.children[0],brandGroup);assert.equal(footer.children[1].className,'app-status-project');
 assert.deepEqual(brandGroup.children,[s.brand,s.get('app-status-version')]);
 s.brand.click();assert.equal(homeCalls,1);assert.equal(listenerCalls,1);assert.equal(s.brand.title,'Return to home');
});

test('the version button uses the original About opener and shares its in-flight catalog response',async()=>{
 const s=setup();s.mount();s.loadLicenses();const version=s.get('app-status-version'),opener=s.get('legal-notices-open'),dialog=s.get('legal-notices-dialog'),host=s.get('legal-notices-content');
 assert.equal(s.requests.length,1);assert.equal(s.requests[0].url,'/licenses/catalog');
 version.click();assert.equal(opener.clicks,1);assert.equal(s.management.closes,1);assert.equal(dialog.shows,1);assert.equal(s.requests.length,1);
 s.requests[0].resolve(response(catalog));await settle();
 assert.equal(version.textContent,catalog.about.version);assert.equal(host.querySelector('.about-version').textContent,catalog.about.version);
 assert.equal(host.querySelector('.about-name').textContent,catalog.about.name);assert.equal(host.querySelector('.about-copy').disabled,false);
 assert.equal(host.querySelector('select').children[0].value,'program-license');assert.equal(host.querySelector('.about-status').textContent,'');
 dialog.close();version.click();await settle();assert.equal(opener.clicks,2);assert.equal(dialog.shows,2);assert.equal(s.requests.length,1);
});

test('a failed initial catalog load can be retried through the version button',async()=>{
 const s=setup();s.mount();s.loadLicenses();const version=s.get('app-status-version'),host=s.get('legal-notices-content');
 version.click();s.requests[0].reject(Error('temporarily unavailable'));await settle();
 assert.equal(host.querySelector('.about-status').textContent,'temporarily unavailable');assert.equal(host.querySelector('.about-copy').disabled,true);
 assert.equal(version.textContent,'版本');s.get('legal-notices-dialog').close();version.click();assert.equal(s.requests.length,2);
 s.requests[1].resolve(response(catalog));await settle();
 assert.equal(version.textContent,catalog.about.version);assert.equal(host.querySelector('.about-version').textContent,catalog.about.version);
 assert.equal(host.querySelector('.about-status').textContent,'');assert.equal(host.querySelector('.about-copy').disabled,false);
});

test('loading the footer version keeps full license documents lazy until the viewer expands them',async()=>{
 const s=setup();s.mount();s.loadLicenses();s.requests[0].resolve(response(catalog));await settle();
 assert.equal(s.get('app-status-version').textContent,catalog.about.version);assert.equal(s.get('legal-notices-dialog').open,false);assert.equal(s.requests.length,1);
 s.get('app-status-version').click();await settle();const host=s.get('legal-notices-content'),section=host.querySelector('details');
 assert.equal(s.requests.length,1);section.open=true;section.ontoggle();assert.equal(s.requests.length,2);assert.equal(s.requests[1].url,'/licenses/document?id=program-license');
 s.requests[1].resolve(response({text:'Full program license'}));await settle();assert.equal(host.querySelector('pre').textContent,'Full program license');
});
