const test=require('node:test'),assert=require('node:assert/strict'),vm=require('node:vm'),fs=require('node:fs');
const source=fs.readFileSync('web/workbench.js','utf8');
function setup(){
 const c={ui:(zh,en)=>zh,put:(el,value)=>{el.textContent=value;},Event,document:{activeElement:null,addEventListener(){}},setTimeout:fn=>fn()};vm.createContext(c);
 vm.runInContext(source.slice(source.indexOf(' const optionalKinds='),source.indexOf(' // Paradigm tables:')),c);
 const chips={},blocks={},row={children:[],querySelector:s=>s==='.lx-tray'?tray:chips[s.match(/data-lx-reveal="([^"]+)"/)?.[1]],closest:()=>({dispatchEvent(){}})},tray={querySelector:s=>chips[s.match(/data-lx-reveal="([^"]+)"/)?.[1]]};
 for(const kind of ['tags','features','notes']){
  const attrs={},chip=chips[kind]={dataset:{lxReveal:kind},hidden:true,getAttribute:k=>attrs[k],setAttribute:(k,v)=>attrs[k]=v,closest:()=>row};
  const block=blocks[kind]={tagName:'DETAILS',dataset:{},hidden:false,open:false,attrs:{},inputs:[],checked:false,isConnected:true,parentElement:row,setAttribute(k,v){this.attrs[k]=v;},contains:node=>block.inputs.includes(node)};
  const input={value:'',focus:()=>{c.document.activeElement=input;}};if(kind==='notes'||kind==='features')block.inputs.push(input);
  const tags={addEmptyTag(){block.inputs.push({value:'',focus(){c.document.activeElement=this;}});}};
  block.querySelectorAll=s=>s==='.tag-row input'&&kind==='tags'?block.inputs:[];
  block.querySelector=s=>{
   if(s===':is(.usage-tags,.sense-tags)'||s==='.usage-tags,.sense-tags')return kind==='tags'?tags:null;
   if(s==='.lx-feature-picker')return kind==='features'?{}:null;
   if(s===':is(.usage-notes,.sense-notes)'||s==='textarea')return kind==='notes'?input:null;
   if(s==='.morph-features input:checked')return kind==='features'&&block.checked?{}:null;
   if(s==='.tag-row')return kind==='tags'&&block.inputs.length?{}:null;
   if(s==='.lx-feature-query,textarea,.tag-row input')return block.inputs[0];
   return null;
  };
  row.children.push(block);
 }
 return {c,row,chips,blocks,refresh:()=>c.trays(row,row),click:kind=>c.reveal(chips[kind])};
}
test('all three optional fields can be opened and hidden repeatedly, keeping their buttons available',()=>{
 const s=setup();s.refresh();for(const kind of ['tags','features','notes']){
  assert.equal(s.blocks[kind].hidden,true);assert.equal(s.chips[kind].hidden,false);
  for(let i=0;i<3;i++){s.click(kind);s.refresh();assert.equal(s.blocks[kind].hidden,false);assert.equal(s.chips[kind].getAttribute('aria-expanded'),'true');s.click(kind);s.refresh();assert.equal(s.blocks[kind].hidden,true);assert.equal(s.chips[kind].getAttribute('aria-expanded'),'false');}
 }
 assert.equal(s.blocks.tags.inputs.length,1,'reopening must reuse the original blank tag row');
});
test('closing populated optional fields keeps every draft value and feature selection through refresh',()=>{
 const s=setup();s.blocks.notes.inputs[0].value='Research note';s.blocks.tags.inputs.push({value:'Western'});s.blocks.features.checked=true;s.refresh();
 for(const kind of ['tags','features','notes']){assert.equal(s.blocks[kind].hidden,false);s.click(kind);s.refresh();assert.equal(s.blocks[kind].hidden,true);s.click(kind);s.refresh();assert.equal(s.blocks[kind].open,true);}
 assert.equal(s.blocks.notes.inputs[0].value,'Research note');assert.equal(s.blocks.tags.inputs[0].value,'Western');assert.equal(s.blocks.features.checked,true);
});
test('an empty optional field hides on leaving, while editing focus or meaningful content keeps it open',()=>{
 const s=setup();s.refresh();s.click('notes');s.c.collapseEmptyOptional(s.blocks.notes);assert.equal(s.blocks.notes.hidden,false);
 s.c.document.activeElement=null;s.c.collapseEmptyOptional(s.blocks.notes);assert.equal(s.blocks.notes.hidden,true);
 s.click('tags');s.blocks.tags.inputs[0].value='Dialect';s.c.document.activeElement=null;s.c.collapseEmptyOptional(s.blocks.tags);assert.equal(s.blocks.tags.hidden,false);
 s.blocks.tags.inputs[0].value=' ';s.c.collapseEmptyOptional(s.blocks.tags);assert.equal(s.blocks.tags.hidden,true);
 s.click('features');s.blocks.features.checked=true;s.c.document.activeElement=null;s.c.collapseEmptyOptional(s.blocks.features);assert.equal(s.blocks.features.hidden,false);
 s.blocks.features.checked=false;s.c.collapseEmptyOptional(s.blocks.features);assert.equal(s.blocks.features.hidden,true);
});

function reading(english=false){
 function node(text='',className=''){return {textContent:text,className,children:[],querySelector(selector){return this.children.find(n=>'.'+n.className===selector)||null;},replaceChildren(...children){this.children=children;},prepend(child){this.children.unshift(child);}};}
 const identity=node('义项 1.1','brief-empty'),heading=node('1. 名词','brief-empty'),body=node('Definition and note remain here'),sense={identity,body,querySelector:()=>identity};
 const subclass=node('子类：测试内容','usage-subclass-view'),usageHeading=node(),usage={querySelector:s=>s===':scope>.usage-subclass-view'?(subclass.parentElement===usage?subclass:null):heading,querySelectorAll:()=>[sense]},definitions=node(),detail={querySelectorAll:()=>[usage],querySelector:()=>definitions};
 subclass.parentElement=usage;usageHeading.children=[heading];heading.after=child=>{usageHeading.children.splice(usageHeading.children.indexOf(heading)+1,0,child);child.parentElement=usageHeading;};
 definitions.querySelector=()=>definitions.children.find(n=>n.className==='lex-senses-title')||null;
 const c={detail,ui:(zh,en)=>english?en:zh,document:{createElement:()=>node()}};vm.createContext(c);
 vm.runInContext(source.slice(source.indexOf(' function readingSenses(){'),source.indexOf(' function arrange(){',source.indexOf(' function readingSenses(){'))),c);
 return {c,identity,heading,body,sense,definitions,subclass,usageHeading};
}
test('reading decoration adds a clear number hierarchy once while retaining the original sense nodes and brief-mode flags',()=>{
 const s=reading(),identity=s.identity,body=s.body;s.c.readingSenses();s.c.readingSenses();
 assert.equal(s.definitions.children.length,0,'the number hierarchy must not insert an extra section heading');
 assert.deepEqual(s.heading.children.map(n=>n.textContent),['1','名词']);assert.deepEqual(s.identity.children.map(n=>n.textContent),['1.1','义项']);
 assert.equal(s.sense.identity,identity);assert.equal(s.sense.body,body);assert.equal(body.textContent,'Definition and note remain here');assert.equal(identity.className,'brief-empty');assert.equal(s.heading.className,'brief-empty');
 assert.equal(s.usageHeading.children.length,2);assert.equal(s.usageHeading.children[1],s.subclass);assert.equal(s.subclass.textContent,'子类：测试内容');
});
test('the reading hierarchy uses the English label without translating or replacing research text',()=>{
 const s=reading(true);s.c.readingSenses();assert.equal(s.definitions.children.length,0);assert.equal(s.identity.children[1].textContent,'Sense');assert.equal(s.heading.children[1].textContent,'名词');assert.equal(s.body.textContent,'Definition and note remain here');
});
