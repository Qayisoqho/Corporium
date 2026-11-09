const test=require('node:test'),assert=require('node:assert/strict'),fs=require('node:fs'),vm=require('node:vm');
const source=fs.readFileSync('web/workbench.js','utf8'),part=source.slice(source.indexOf('/* Timeline: a time selection'),source.indexOf('/* Text navigator:'));
function harness(existing=false,disabled=false){
 const node=()=>({children:[],style:{},hidden:false,textContent:'',offsetWidth:140,setAttribute(){},append(...nodes){this.children.push(...nodes);},getBoundingClientRect(){return {left:0,top:0,right:800,width:800};}});
 const label=node(),commit=node(),workspace=node(),stage=node(),highlight=node(),observers=new Map(),timers=new Map();label.textContent='Selected 0:10–0:20';commit.disabled=disabled;
 highlight.closest=()=>({});highlight.getClientRects=()=>[{}];highlight.getBoundingClientRect=()=>({left:100,top:60,right:300,width:200});stage.querySelectorAll=()=>[highlight];let id=0,calls=0;
 commit.click=()=>calls++;const nodes={'tl-selection-label':label,'tl-commit':commit,'timeline-workspace':workspace};
 const state={existing,document:{readyState:'complete',querySelector:()=>stage,createElement:node},$:key=>nodes[key],MutationObserver:class{constructor(callback){this.callback=callback;}observe(target){observers.set(target,this.callback);}},setInterval:fn=>{timers.set(++id,fn);return id;},clearInterval:n=>timers.delete(n),CorporiumI18n:{ui:(zh,en)=>en}};
 state.window=state;state.corporiumTimelineHasSelectedInterval=()=>state.existing;vm.runInNewContext(part,state);const chip=stage.children[0];
 return {state,label,commit,workspace,chip,timers,notify:()=>observers.get(label)(),tick:()=>[...timers.values()].forEach(fn=>fn()),calls:()=>calls};
}
test('existing interval selection keeps the footer range while suppressing the duplicate confirmation chip',()=>{
 const h=harness(true);h.notify();assert.equal(h.chip.hidden,true);assert.equal(h.label.textContent,'Selected 0:10–0:20');h.tick();assert.equal(h.chip.hidden,true);
});
test('a new selected range retains its original confirmation action',()=>{
 const h=harness();h.notify();assert.equal(h.chip.hidden,false);assert.equal(h.timers.size,1);assert.equal(h.chip.children[0].textContent,h.label.textContent);h.chip.children[1].onclick();assert.equal(h.calls(),1);
});
test('selection changes hide an existing interval chip and restore a new draft even when its time label is unchanged',()=>{
 const h=harness();h.notify();h.state.existing=true;h.notify();assert.equal(h.chip.hidden,true);h.state.existing=false;h.tick();assert.equal(h.chip.hidden,false);h.label.textContent='';h.notify();assert.equal(h.chip.hidden,true);assert.equal(h.timers.size,0);
});
test('new ranges without a sentence preserve their helper and disabled confirmation',()=>{
 const h=harness(false,true);h.notify();assert.equal(h.chip.hidden,false);assert.match(h.chip.children[0].textContent,/Choose a sentence/);assert.equal(h.chip.children[1].disabled,true);h.chip.children[1].onclick();assert.equal(h.calls(),0);
});
