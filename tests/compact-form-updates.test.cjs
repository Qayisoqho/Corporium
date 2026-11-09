const test=require('node:test'),assert=require('node:assert/strict'),vm=require('node:vm'),fs=require('node:fs');
function setup(){
 const source=fs.readFileSync('web/dictionary-layout.js','utf8'),begin=source.indexOf('function createCompactFormUpdates('),end=source.indexOf('/* Forms are compared',begin);
 const callbacks=new Map(),roots=new Map(['lexeme-variants','morpheme-variants','dictionary-detail','morpheme-detail'].map(id=>[id,{id}])),frames=[],observed=[];let updates=0,mutation;
 const doc={getElementById:id=>roots.get(id),addEventListener:(name,fn)=>callbacks.set(name,fn)},Observer=class{constructor(fn){mutation=fn;}observe(node,options){observed.push({node,options});}};
 const c=vm.createContext({});vm.runInContext(source.slice(begin,end),c);c.createCompactFormUpdates(doc,()=>updates++,fn=>(frames.push(fn),frames.length),Observer);
 const flush=()=>{for(let i=0;frames.length&&i<5;i++)frames.shift()();assert.equal(frames.length,0);};flush();
 return {roots,observed,callbacks,mutation,flush,updates:()=>updates};
}
test('sentence input and changes do not refresh hidden lexicon form tables',()=>{
 const h=setup(),count=h.updates();for(const type of ['input','change'])h.callbacks.get(type)({target:{closest:()=>null}});h.flush();assert.equal(h.updates(),count);
});
test('both form editors still update their summaries, coalescing one input/change burst',()=>{
 const h=setup();for(const id of ['lexeme-variants','morpheme-variants']){const before=h.updates();for(const type of ['input','change'])h.callbacks.get(type)({target:{closest:()=>h.roots.get(id)}});h.flush();assert.equal(h.updates(),before+1);}
});
test('new forms, reading results and explicit layout changes keep the table layout current',()=>{
 const h=setup();assert.deepEqual(h.observed.map(x=>x.node.id),[...h.roots.keys()]);assert.ok(h.observed.every(x=>x.options.childList&&x.options.subtree));const before=h.updates();h.mutation([]);h.callbacks.get('lx-layout')({});h.flush();assert.equal(h.updates(),before+1);
});
