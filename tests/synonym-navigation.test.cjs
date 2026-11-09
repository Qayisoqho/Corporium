const test=require('node:test'),assert=require('node:assert/strict'),fs=require('node:fs'),vm=require('node:vm');
const source=fs.readFileSync('web/synonyms.js','utf8');

function setup(){
 const document=new EventTarget(),timers=new Map(),nodes=new Map(),calls=[];let nextTimer=0;
 class Element extends EventTarget{
  constructor(){super();this.dataset={};this.children=[];this.buttons=new Map();this.classes=new Set();this.isConnected=true;this.classList={add:name=>this.classes.add(name),remove:name=>this.classes.delete(name)};}
  set innerHTML(html){this.html=html;}
  querySelector(selector){if(!this.buttons.has(selector))this.buttons.set(selector,new Element());return this.buttons.get(selector);}
  querySelectorAll(){return [];}
  append(child){this.children.push(child);}
  scrollIntoView(options){this.scrolled=options.block;}
  focus(options){const old=document.activeElement;document.activeElement=this;if(old&&old!==this)old.dispatchEvent(new Event('blur'));this.preventScroll=options.preventScroll;}
 }
 document.createElement=()=>new Element();
 const c=vm.createContext({document,URLSearchParams,makeDialog:()=>{},$:id=>{if(!nodes.has(id))nodes.set(id,new Element());return nodes.get(id);},
  safe:fn=>fn,rich:value=>value,esc:value=>value,activeLanguage:'first',showLexeme:async()=>{},
  switchLanguage:async id=>{calls.push(['language',id]);c.activeLanguage=id;},
  openDictionaryLexeme:async id=>calls.push(['lexeme',id]),openMorphemeRecord:async id=>calls.push(['morpheme',id]),
  setTimeout:(fn,ms)=>{const id=++nextTimer;timers.set(id,{fn,ms});return id;},clearTimeout:id=>timers.delete(id)});
 vm.runInContext(source,c);
 return {c,document,timers,nodes,calls,element:()=>new Element(),focus:dest=>c.focusSynonymDestination(dest),highlighted:dest=>dest.classes.has('synonym-destination')};
}

for(const kind of ['lexeme','morpheme'])test(`${kind} synonym opens its specific sense, then clears the temporary cue automatically`,async()=>{
 const h=setup(),container=h.element(),section=h.element(),wrong=h.element(),dest=h.element();
 container.firstElementChild={};container.querySelectorAll=selector=>selector==='.sense-synonyms'?[]:[section];
 wrong.dataset.synonymSense='another-sense';dest.dataset.synonymSense='target-sense';
 const root=h.element();root.querySelectorAll=()=>[wrong,dest];h.nodes.set(kind==='lexeme'?'dictionary-detail':'morpheme-detail',root);
 h.c.api=async()=>({language_id:'second',senses:[{sense:'source-sense'}],links:[{ends:[{kind,id:'source',sense:'source-sense'},{kind,id:'target',sense:'target-sense',form:'other',label:'meaning'}]}]});
 await h.c.renderSenseSynonyms(container,kind,'source','first');
 await section.children[0].children[0].querySelector('[data-open-synonym]').onclick();
 assert.deepEqual(h.calls,[['language','second'],[kind,'target']]);
 assert.equal(h.highlighted(dest),true);assert.equal(h.highlighted(wrong),false);
 assert.equal(h.document.activeElement,dest);assert.equal(dest.tabIndex,-1);assert.equal(dest.scrolled,'center');assert.equal(dest.preventScroll,true);
 const timer=[...h.timers.values()][0];assert.equal(timer.ms,1500);timer.fn();
 assert.equal(h.highlighted(dest),false);assert.equal(h.timers.size,0);assert.equal(h.document.activeElement,dest);
});

for(const action of ['pointerdown','keydown','blur'])test(`${action} clears the synonym cue without consuming normal interaction`,()=>{
 const h=setup(),dest=h.element();h.focus(dest);
 const event=new Event(action,{cancelable:true});(action==='blur'?dest:h.document).dispatchEvent(event);
 assert.equal(h.highlighted(dest),false);assert.equal(h.timers.size,0);assert.equal(event.defaultPrevented,false);
});

test('repeated synonym jumps replace the previous cue and do not leave stale handlers or timers',()=>{
 const h=setup(),first=h.element(),second=h.element();h.focus(first);h.focus(second);
 assert.equal(h.highlighted(first),false);assert.equal(h.highlighted(second),true);assert.equal(h.timers.size,1);
 first.dispatchEvent(new Event('blur'));assert.equal(h.highlighted(second),true);
 h.document.dispatchEvent(new Event('pointerdown'));assert.equal(h.highlighted(second),false);assert.equal(h.timers.size,0);
 h.focus(second);assert.equal(h.highlighted(second),true);assert.equal(h.timers.size,1);
 [...h.timers.values()][0].fn();assert.equal(h.highlighted(second),false);assert.equal(h.timers.size,0);
});
