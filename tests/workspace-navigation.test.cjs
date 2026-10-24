const {test}=require('node:test');
const assert=require('node:assert/strict');
const vm=require('node:vm');
const fs=require('node:fs');
const script=fs.readFileSync(require('node:path').join(__dirname,'../web/workspace-navigation.js'),'utf8');
function setup(){
 const classes=new Set(),roots={};
 const c={activeLanguage:'one',workspace:'analysis',requestAnimationFrame:fn=>setImmediate(fn)};
 c.window={scrollX:0,scrollY:1400,scrollTo:({top})=>c.window.scrollY=Math.max(0,top)};
 for(const name of ['analysis','corpus']){
  const root={hidden:name!=='analysis',nodes:[],querySelectorAll:()=>root.nodes};roots[name+'-workspace']=root;
  const node={id:name==='corpus'?'entry-sentence':'',dataset:name==='analysis'?{navigationAnchor:'sentence-word-2'}:{},y:name==='analysis'?1500:800,getClientRects:()=>root.hidden?[]:[{}],getBoundingClientRect:()=>({top:node.y-c.window.scrollY,bottom:node.y-c.window.scrollY+250})};root.nodes=[node];
 }
 c.$=id=>id==='workspace-toolbar'?{getBoundingClientRect:()=>({bottom:90})}:roots[id];
 c.document={querySelectorAll:()=>[],documentElement:{dataset:{home:'false'},classList:{add:x=>classes.add(x),remove:x=>classes.delete(x),contains:x=>classes.has(x)}}};
 c.setWorkspace=async name=>{c.workspace=name;for(const [id,r] of Object.entries(roots))r.hidden=id!==name+'-workspace';c.window.scrollY=0;await new Promise(r=>setImmediate(r));};
 vm.createContext(c);vm.runInContext(script,c);return {c,roots,classes};
}
test('analysis and corpus keep independent sentence offsets across repeated reloads',async()=>{
 const {c,roots,classes}=setup();await c.setWorkspace('corpus');assert.equal(c.window.scrollY,0);
 c.window.scrollY=650; // A source jump occurs after setWorkspace resolves.
 await c.setWorkspace('analysis');assert.equal(c.window.scrollY,1400);
 roots['corpus-workspace'].nodes[0].y=1000; // Changed preceding layout still preserves the sentence position.
 await c.setWorkspace('corpus');assert.equal(c.window.scrollY,850);
 await c.setWorkspace('analysis');assert.equal(c.window.scrollY,1400);assert.equal(classes.size,0);
});
test('rapid workspace switches finish in click order without a late scroll overwrite',async()=>{
 const {c}=setup();await c.setWorkspace('corpus');c.window.scrollY=600;
 await Promise.all([c.setWorkspace('analysis'),c.setWorkspace('corpus'),c.setWorkspace('analysis')]);
 assert.equal(c.workspace,'analysis');assert.equal(c.window.scrollY,1400);
});
test('missing anchors fall back to stored position; another language has its own position',async()=>{
 const {c,roots}=setup();await c.setWorkspace('corpus');roots['analysis-workspace'].nodes=[];
 await c.setWorkspace('analysis');assert.equal(c.window.scrollY,1400);
 c.activeLanguage='two';await c.setWorkspace('corpus');assert.equal(c.window.scrollY,0);
});
test('undo preserves the visible sentence offset after layout changes and restores nested scroll containers',async()=>{
 const {c,roots,classes}=setup(),side={id:'side',scrollTop:300,scrollLeft:20,getClientRects:()=>[{}]};
 const original=c.$;c.$=id=>id==='side'?side:original(id);c.document.querySelectorAll=()=>[side];
 await c.window.corporiumPreserveLocation(async()=>{c.window.scrollY=0;roots['analysis-workspace'].nodes[0].y+=200;side.scrollTop=0;side.scrollLeft=0;});
 assert.equal(c.window.scrollY,1600);assert.equal(side.scrollTop,300);assert.equal(side.scrollLeft,20);assert.equal(classes.size,0);
});
test('undo with a deleted anchor falls back to its prior scroll and never restores over another workspace',async()=>{
 const {c,roots}=setup();await c.window.corporiumPreserveLocation(async()=>{c.window.scrollY=0;roots['analysis-workspace'].nodes=[];});assert.equal(c.window.scrollY,1400);
 await c.window.corporiumPreserveLocation(async()=>{c.workspace='corpus';c.window.scrollY=50;});assert.equal(c.window.scrollY,50);
});
