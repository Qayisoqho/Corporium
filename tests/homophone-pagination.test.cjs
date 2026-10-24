const test=require('node:test'),assert=require('node:assert/strict'),fs=require('node:fs'),vm=require('node:vm');
const source=fs.readFileSync('web/homophones.js','utf8');
function setup(storage=new Map()){
 const nodes=new Map(),calls=[],pages=new Map();
 let created=0;
 const node=id=>{if(!nodes.has(id))nodes.set(id,{id,value:'',checked:false,innerHTML:'',textContent:'',hidden:false,disabled:false,labels:[],children:[],querySelector:()=>({textContent:''}),setAttribute(){},append(...es){this.children.push(...es);},prepend(e){this.labels.push(e);this.children.unshift(e);}});return nodes.get(id);};
 let pending=1,view='phonology';
 const c={URLSearchParams,activeLanguage:'one',languageList:[{id:'one',metadata:'{}'}],window:{},page:1,reviewPage:1,sequence:0,generated:false,filterSignature:null,pageSize:null,pageSizeView:null,panel:node('panel'),$:node,languageTypographyCSS:()=>'',esc:s=>s,projectStorageKey:k=>'project-one:'+k,localStorage:{getItem:k=>storage.get(k),setItem:(k,v)=>storage.set(k,v)},document:{createElement:()=>{const e=node('created'+created++);Object.defineProperty(e,'id',{set:id=>nodes.set(id,e)});return e;}}};
 c.phonologyUI={query:()=>({view,empty:false,pending_page:pending}),firstPage:()=>{pending=1;},render:()=>view==='phonology'};
 c.topPagination=(container,page,total,onPage)=>{container.children=[];pages.set(container.id,{page,total,onPage});};
 c.api=async path=>{const p=new URLSearchParams(path.split('?')[1]);calls.push(Object.fromEntries(p));if(c.fail)throw Error('offline');const count=c.singlePage?1:p.get('view')==='phonology'?(p.get('page_size')==='all'?1:Math.ceil(12/+p.get('page_size'))):2;return {page:Math.min(+p.get('page'),count),pages:count,review_page:+p.get('review_page'),review_pages:2,total:12,review_total:0,groups:[],review:[],writing_types:[]};};
 vm.createContext(c);const start=source.indexOf(' function readPageSize('),end=source.indexOf(' panel.onclick=',start);vm.runInContext(source.slice(start,end),c);
 return {c,node,calls,pages,setPending:p=>pending=p,getPending:()=>pending,setView:v=>view=v,submit:async()=>{node('homophone-form').onsubmit({preventDefault(){}});await new Promise(setImmediate);}};
}
test('regenerating after a second homophone is added keeps the current final-group page',async()=>{
 const {c,calls,pages,submit}=setup();await c.run();await pages.get('homophone-pages').onPage(2);
 await submit();assert.equal(calls.at(-1).page,'2');assert.equal(pages.get('homophone-pages').page,2);
});

test('page-size selectors synchronize, reset to page one and persist across reloads within the project',async()=>{
 const storage=new Map(),{c,node,calls,pages}=setup(storage);await c.run();await pages.get('homophone-pages').onPage(2);
 const bottom=node('homophone-bottom-pages-size');bottom.value='20';bottom.onchange();await new Promise(setImmediate);
 assert.equal(node('homophone-pages-size').value,'20');assert.equal(calls.at(-1).page_size,'20');assert.equal(calls.at(-1).page,'1');assert.equal(node('homophone-bottom-pages').hidden,false);
 const top=node('homophone-pages-size');top.value='all';top.onchange();await new Promise(setImmediate);assert.equal(node('homophone-bottom-pages-size').value,'all');
 const reloaded=setup(storage);await reloaded.c.run();assert.equal(reloaded.calls.at(-1).page_size,'all');assert.equal(reloaded.node('homophone-bottom-pages-size').value,'all');
 const other=setup(storage);other.c.projectStorageKey=k=>'other-project:'+k;await other.c.run();assert.equal(other.calls.at(-1).page_size,'10');
});

test('invalid or inaccessible preferences fall back to ten and a single page retains both size controls',async()=>{
 const storage=new Map([['project-one:corporium-homophone-final-page-size','1000']]),{c,node,calls}=setup(storage);c.singlePage=true;await c.run();assert.equal(calls.at(-1).page_size,'10');
 assert.equal(node('homophone-bottom-pages').hidden,false);assert.equal(node('homophone-pages-size').value,'10');assert.equal(node('homophone-bottom-pages-size').value,'10');
 const blocked=setup();blocked.c.localStorage.getItem=()=>{throw Error('disabled');};await blocked.c.run();assert.equal(blocked.calls.at(-1).page_size,'10');
 blocked.c.localStorage.setItem=()=>{throw Error('disabled');};const select=blocked.node('homophone-pages-size');select.value='50';select.onchange();await new Promise(setImmediate);assert.equal(blocked.calls.at(-1).page_size,'50');
});
test('filter changes restart the main, review and pending pagination while ordinary refresh preserves them',async()=>{
 const {c,node,calls,pages,submit,setPending,getPending}=setup();await c.run();await pages.get('homophone-pages').onPage(2);await pages.get('homophone-review-pages').onPage(2);setPending(2);
 await submit();assert.equal(calls.at(-1).page,'2');assert.equal(calls.at(-1).review_page,'2');assert.equal(getPending(),2);
 node('homophone-query').value='new filter';await submit();assert.equal(calls.at(-1).page,'1');assert.equal(calls.at(-1).review_page,'1');assert.equal(calls.at(-1).pending_page,'1');
});
test('bottom pagination uses the same current page and page callback as the top',async()=>{
 const {c,node,pages,setView}=setup();await c.run();assert.ok(pages.has('homophone-bottom-pages'));await pages.get('homophone-bottom-pages').onPage(2);
 assert.equal(pages.get('homophone-pages').page,2);assert.equal(pages.get('homophone-bottom-pages').page,2);assert.equal(node('homophone-bottom-pages').hidden,false);
 setView('reading');await c.run();assert.equal(pages.get('homophone-bottom-pages').page,1);
});

test('reading sizes persist independently and both selectors follow view switches',async()=>{
 const storage=new Map(),{c,node,calls,setView}=setup(storage);await c.run();
 node('homophone-pages-size').value='20';node('homophone-pages-size').onchange();await new Promise(setImmediate);
 setView('reading');await c.run();assert.equal(calls.at(-1).page_size,'10');
 node('homophone-bottom-pages-size').value='50';node('homophone-bottom-pages-size').onchange();await new Promise(setImmediate);
 assert.equal(node('homophone-pages-size').value,'50');assert.equal(storage.get('project-one:corporium-homophone-reading-page-size'),'50');
 setView('phonology');await c.run();assert.equal(calls.at(-1).page_size,'20');
 setView('reading');await c.run();assert.equal(calls.at(-1).page_size,'50');
 const reloaded=setup(storage);reloaded.setView('reading');await reloaded.c.run();assert.equal(reloaded.calls.at(-1).page_size,'50');
});
