const test=require('node:test'),assert=require('node:assert/strict'),fs=require('node:fs'),vm=require('node:vm');
function setup(store=new Map(),deny=false){
 const node=()=>({children:[],listeners:{},open:false,classList:{add(){}},before(n){this.insertedBefore=n;},append(...nodes){this.children.push(...nodes);},addEventListener(type,fn){this.listeners[type]=fn;}});
 const c={document:{createElement:node},localStorage:{getItem(k){if(deny)throw Error('blocked');return store.get(k)||null;},setItem(k,v){if(deny)throw Error('blocked');store.set(k,v);}}};vm.createContext(c);
 const s=fs.readFileSync('web/typography.js','utf8');vm.runInContext(s.slice(s.indexOf('function mountGlobalSettingsSection'),s.indexOf("makeDialog('typography-dialog'")),c);
 return {mount:(key,content=node())=>({content,section:c.mountGlobalSettingsSection(content,key,key)})};
}
test('sections remember independent folds across reloads without replacing their form controls',()=>{
 const store=new Map(),h=setup(store),fonts=h.mount('fonts'),colors=h.mount('colors');
 assert.equal(fonts.section.open,false);assert.equal(colors.section.open,false);assert.equal(fonts.content.insertedBefore,fonts.section);assert.equal(fonts.section.children[1],fonts.content);
 fonts.section.open=true;fonts.section.listeners.toggle();colors.section.listeners.toggle();
 const loaded=setup(store);assert.equal(loaded.mount('fonts').section.open,true);assert.equal(loaded.mount('colors').section.open,false);
});
test('unavailable or invalid saved preferences leave sections usable and collapsed',()=>{
 for(const h of [setup(new Map(),true),setup(new Map([['corporium-global-settings-section-fonts','invalid']]))]){
  const {section}=h.mount('fonts');assert.equal(section.open,false);section.open=true;assert.doesNotThrow(()=>section.listeners.toggle());
 }
});
