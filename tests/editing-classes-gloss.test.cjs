const test=require('node:test'),assert=require('node:assert/strict'),fs=require('node:fs'),vm=require('node:vm');
const source=name=>fs.readFileSync('web/'+name+'.js','utf8');
test('optional gloss tags keep free text intact and support empty bases and duplicate symbols',()=>{
 const c=vm.createContext({});vm.runInContext(source('sense-gloss'),c);
 const s={short_gloss:'toward the north.LOC',gloss_addition:'loc.PL'};
 assert.equal(c.senseGloss(s),'toward the north.LOC.PL');assert.equal(s.short_gloss,'toward the north.LOC');
 assert.equal(c.senseGloss({...s,show_gloss_addition:false}),s.short_gloss);
 assert.equal(c.senseGloss({gloss:'北方',gloss_addition:'LOC'},'gloss'),'北方.LOC');
 assert.equal(c.senseGloss({gloss_addition:'LOC'}),'LOC');
});
test('class consumers update an open draft without navigating or refreshing its detail',async()=>{
 const nodes={'lexeme-editor':{open:true},'lexeme-language':{value:'ordos'},'grammar-editor':{open:false},'lexeme-usages':{children:[{}]},'lexeme-variants':{children:[{}]}},calls=[];
 const c=vm.createContext({$:id=>nodes[id],classLanguage:'ordos',classRows:[{id:'new'}],workspace:'dictionary',window:{},fillUsageClasses:()=>calls.push('pos'),fillFormClasses:()=>calls.push('form'),refreshUndo:async()=>calls.push('history'),loadDictionary:async()=>calls.push('reload')});
 const s=source('classes');vm.runInContext(s.slice(s.indexOf('async function refreshClassConsumers()'),s.indexOf('function fillFormClasses(')),c);
 await c.refreshClassConsumers();assert.deepEqual(calls,['pos','form','history']);
 nodes['lexeme-editor'].open=false;await c.refreshClassConsumers();assert.equal(calls.at(-1),'reload');
});
test('class edits accept only the revision they changed and retain unrelated draft fields',()=>{
 const nodes={'lexeme-form':{querySelectorAll:()=>[]}},c=vm.createContext({$:id=>nodes[id],window:{},editingLexeme:{id:'x',revision:3,headword:'a',body:{}}});
 const s=source('classes');vm.runInContext(s.slice(s.indexOf('function acceptClassChange('),s.indexOf('function classOptions(')),c);
 c.acceptClassChange({editor_before_revision:2,editor_target:{id:'x',revision:8}});assert.equal(c.editingLexeme.revision,3);
 c.acceptClassChange({editor_before_revision:3,editor_target:{id:'x',revision:4,body:{updated:true}}});assert.equal(c.editingLexeme.revision,4);assert.equal(c.editingLexeme.headword,'a');
});
test('new sentence card replaces only its own draft and retains current list and filters',async()=>{
 const calls=[],card={getBoundingClientRect:()=>({top:80}),querySelector:()=>({})},host={getBoundingClientRect:()=>({top:80}),replaceWith:el=>{assert.equal(el,card);calls.push('replace');}},items=[{id:'existing'}];
 const c=vm.createContext({api:async path=>{calls.push(path);return {body:{ipa:'new',words:[]},owner_language:'ordos',revision:1};},texts:[{id:'t',title:'Text'}],document:{createElement:()=>({firstElementChild:card})},corpusEntryCard:()=>'<article>',items,safe:f=>f,edit(){},loadTexts:async()=>calls.push('counts'),window:{scrollBy:()=>calls.push('anchor')}});
 const s=source('sentence-create');vm.runInContext(s.slice(s.indexOf('async function saveNewCorpusInPlace('),s.indexOf('(()=>{')),c);
 assert.equal(await c.saveNewCorpusInPlace({id:'new',text_id:'t',position:28},{host}),true);
 assert.equal(items[0].id,'existing');assert.equal(items[1].id,'new');assert.deepEqual(calls,['annotations?kind=corpus&id=new','replace','counts','anchor']);
});
test('dragging orders sibling classes only and carries their stable revisions',async()=>{
 const rows=[{id:'a',parent_id:null,revision:2},{id:'b',parent_id:null,revision:5},{id:'c',parent_id:'a',revision:1}],nodes=rows.map(r=>({dataset:{classRow:r.id},classList:{add(){},remove(){}},prepend(b){this.handle=b;}})),calls=[];
 const host={querySelectorAll:s=>s==='[data-class-row]'?nodes:s==='button'?nodes.map(n=>n.handle):[]},c=vm.createContext({window:{},document:{createElement:()=>({setAttribute(){}})},corporiumAlert:async m=>{throw Error(m);}});
 vm.runInContext(source('class-order'),c);c.window.CorporiumClassOrder.mount(host,rows,async(items,parent)=>calls.push({ids:items.map(r=>r.id),revisions:items.map(r=>r.revision),parent}));
 const transfer={setData(){}};nodes[0].handle.ondragstart({dataTransfer:transfer});nodes[2].ondrop({preventDefault(){}});assert.equal(calls.length,0);
 nodes[1].ondrop({preventDefault(){}});assert.deepEqual(Array.from(calls[0].ids),['b','a']);assert.deepEqual(Array.from(calls[0].revisions),[5,2]);assert.equal(calls[0].parent,null);
});
test('the semantic manager preserves reorder options for the ordinary class editor',async()=>{
 const calls=[],c=vm.createContext({$:id=>({value:'pos'}),loadClasses:async value=>calls.push(value),normalClassContent:{},semanticContent:{}});
 const s=source('dictionary-organization');vm.runInContext(s.match(/ const oldLoadClasses=loadClasses;loadClasses=async function[^\n]+/)[0],c);
 await c.loadClasses(true);assert.deepEqual(calls,[true]);
});
