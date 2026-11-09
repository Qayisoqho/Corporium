const test=require('node:test'),assert=require('node:assert/strict'),vm=require('node:vm'),fs=require('node:fs');
function setup(){
  const c=vm.createContext({esc:s=>s});
  vm.runInContext(fs.readFileSync('web/fonts.js','utf8').split('let fontScanRequest')[0],c);
  vm.runInContext(fs.readFileSync('web/font-stack.js','utf8').split('function createFontStackEditor')[0],c);
  vm.runInContext(fs.readFileSync('web/typography.js','utf8').split('const variantOptions')[0],c);
  c.validFont=vm.runInContext('validFont',c);
  return c;
}
const plain=value=>JSON.parse(JSON.stringify(value));
test('single saved fonts migrate without losing priority; explicit arrays take precedence',()=>{
  const c=setup();assert.deepEqual(plain(c.savedFontStack({ui:'Junicode'})),['Junicode']);
  assert.deepEqual(plain(c.savedFontStack({ui:'Junicode',uiFonts:['KaiTi','Noto Sans','KaiTi']})),['KaiTi','Noto Sans']);
  for(const uiFonts of [[],{},null,['invalid',12]])assert.deepEqual(plain(c.savedFontStack({uiFonts})),['STIX Two Text','Microsoft JhengHei']);
  assert.equal(c.fontStackCSS(['Junicode','Noto Sans']),'"Junicode","Noto Sans",sans-serif');
});

test('default order uses bundled STIX then system JhengHei; only the exact previous default follows the change',()=>{
  const c=setup(),settings={uiFonts:['Noto Sans','Source Han Sans SC']},copy=JSON.stringify(settings);
  assert.deepEqual(plain(c.savedFontStack(settings)),['STIX Two Text','Microsoft JhengHei']);
  assert.equal(JSON.stringify(settings),copy);
  assert.deepEqual(plain(c.savedFontStack({uiFonts:['Noto Sans','Junicode','Source Han Sans SC']})),['Noto Sans','Junicode','Source Han Sans SC']);
  assert.equal(c.fontStackCSS([]),'"STIX Two Text","Microsoft JhengHei",sans-serif');
  assert.equal(c.validFont('STIX Two Text'),true);assert.equal(c.validFont('Microsoft JhengHei'),true);
  assert.equal(vm.runInContext("fontSources['Microsoft JhengHei'].source",c),'preset');
  assert.equal(vm.runInContext("fontSources['Noto Sans'].source",c),'preset');
});
test('missing system and folder fonts retain their IDs, labels and fallback position',()=>{
  const c=setup(),name='研究 Sans "A"',id='systemfont-'+Buffer.from(name).toString('hex'),folder='localfont-'+ 'a'.repeat(24);
  assert.equal(c.systemFontName(id),name);assert.equal(c.fontLabel(id),name);assert.equal(c.validFont(id),true);
  assert.deepEqual(plain(c.savedFontStack({uiFonts:[id,folder,'Junicode']})),[id,folder,'Junicode']);
  assert.equal(c.fontStackCSS([id,'Junicode']),JSON.stringify(id)+',"Junicode",sans-serif');
  for(const bad of ['systemfont-ff','systemfont-0a','systemfont-40766f6964','systemfont-41'.repeat(300),'systemfont-','x";color:red'])assert.equal(c.validFont(bad),false,bad);
});
test('reordering preserves every font once and does not mutate saved settings',()=>{
  const c=setup(),saved=['Junicode','Noto Sans','Source Han Sans SC'];
  assert.deepEqual(plain(c.moveFontInStack(saved,'Source Han Sans SC',0)),['Source Han Sans SC','Junicode','Noto Sans']);
  assert.deepEqual(plain(c.moveFontInStack(saved,'Junicode',99)),['Noto Sans','Source Han Sans SC','Junicode']);
  assert.deepEqual(saved,['Junicode','Noto Sans','Source Han Sans SC']);assert.deepEqual(plain(c.moveFontInStack(saved,'absent',0)),saved);
});
test('follow-global and preferred fonts use the same chain in every row while variants remain independent',()=>{
  const c=setup(),settings={ipa_font:'@global',annotation_font:'@global',gloss_font:'Junicode',translation_font:'@global',morpheme_variant:'italic',gloss_variant:'bold',ipa_scale:1.2};
  const css=c.languageTypographyCSS(settings);
  assert.ok(css.includes('--ipa-font:var(--global-font-stack,var(--default-ui-font))'));
  assert.ok(css.includes('--annotation-font:var(--global-font-stack,var(--default-ui-font))'));
  assert.ok(css.includes('--gloss-font:"Junicode",var(--global-font-stack,var(--default-ui-font))'));
  assert.ok(css.includes('--translation-font:var(--global-font-stack,var(--default-ui-font))'));
  for(const property of ['--form-style:italic','--gloss-weight:700','--ipa-scale:1.2'])assert.ok(css.includes(property));
});
test('installed faces are local-only aliases, keeping bundled fonts separate and preserving face attributes',()=>{
  const c=setup(),css=c.fontFaceCSS({families:[],builtins:[],system:{families:[{id:'systemfont-5365726966',faces:[{local:['Serif Bold Italic','Serif-BoldItalic'],style:'italic',weight:'700',stretch:5}]}]}});
  assert.match(css,/font-family:"systemfont-5365726966"/);assert.match(css,/src:local\("Serif Bold Italic"\),local\("Serif-BoldItalic"\)/);
  assert.match(css,/font-style:italic;font-weight:700;font-stretch:100%/);assert.doesNotMatch(css,/url\(/);
});
test('clipboard fonts resolve actual installed family names and never expose the row sentinel or app aliases',()=>{
  const c=setup(),id='systemfont-'+Buffer.from('Research Sans').toString('hex');
  vm.runInContext(`var typography={uiFonts:[${JSON.stringify(id)},'Noto Sans']};`,c);
  assert.deepEqual(plain(c.clipboardFontStack('@global')),['Research Sans','Noto Sans','sans-serif']);
  assert.deepEqual(plain(c.clipboardFontStack('Junicode')),['Junicode','Research Sans','Noto Sans','sans-serif']);
});

// A small event/element surface exercises the real draft controller without
// starting a project or replacing the font ordering/rendering functions.
function editorSetup(saved){
 const c=setup(),nodes=new Map();let hit=null;
 class Element{
  constructor(tag='div'){this.tagName=tag.toUpperCase();this.children=[];this.dataset={};this.style={};this.value='';this.className='';this.listeners=new Map();this.attrs={};this.classList={add:(...a)=>a.forEach(v=>this.classes.add(v)),remove:(...a)=>a.forEach(v=>this.classes.delete(v))};this.classes=new Set();this.captured=new Set();}
  append(...children){for(const child of children){if(child.tagName==='#FRAGMENT'){this.append(...[...child.children]);continue;}if(child.parentElement)child.parentElement.children=child.parentElement.children.filter(n=>n!==child);child.parentElement=this;this.children.push(child);}}
  replaceChildren(...children){this.children=[];this.append(...children);}
  set innerHTML(html){for(const m of html.matchAll(/<(input|select|ol|div|p|button)[^>]* id="([^"]+)"/g)){const child=new Element(m[1]);child.id=m[2];nodes.set(child.id,child);this.append(child);}}
  setAttribute(k,v){this.attrs[k]=v;}getAttribute(k){return this.attrs[k];}
  addEventListener(type,fn){if(!this.listeners.has(type))this.listeners.set(type,new Set());this.listeners.get(type).add(fn);}
  removeEventListener(type,fn){this.listeners.get(type)?.delete(fn);}
  dispatchEvent(event){for(const fn of [...this.listeners.get(event.type)||[]])fn(event);if(event.bubbles)this.parentElement?.dispatchEvent(event);}
  querySelectorAll(selector){const match=el=>selector==='button'?el.tagName==='BUTTON':selector==='[data-font-add]'?Object.hasOwn(el.dataset,'fontAdd'):selector.startsWith('.')?el.className.split(' ').includes(selector.slice(1)):false;return this.children.flatMap(el=>[...(match(el)?[el]:[]),...el.querySelectorAll(selector)]);}
  querySelector(s){return this.querySelectorAll(s)[0];}
  closest(s){for(let el=this;el;el=el.parentElement)if(s.startsWith('.')&&el.className.split(' ').includes(s.slice(1))||s==='dialog[open]'&&el.tagName==='DIALOG'&&el.open)return el;return null;}
  contains(node){return node===this||this.children.some(child=>child.contains(node));}
  get firstChild(){return this.children[0]||null;}get childNodes(){return this.children;}
  focus(){c.document.activeElement=this;}
  setPointerCapture(p){this.captured.add(p);}hasPointerCapture(p){return this.captured.has(p);}releasePointerCapture(p){this.captured.delete(p);}
 }
 const form=new Element('form'),host=new Element(),dialog=new Element('dialog');dialog.open=true;dialog.append(form);form.append(host);nodes.set('typography-form',form);
 c.Event=class{constructor(type,options={}){this.type=type;this.bubbles=!!options.bubbles;}preventDefault(){}};
 c.$=id=>nodes.get(id);c.window=new Element('window');c.document=Object.assign(new Element('document'),{createElement:tag=>new Element(tag),createDocumentFragment:()=>new Element('#fragment'),elementFromPoint:()=>hit});c.variantOptions='';
 vm.runInContext(fs.readFileSync('web/font-stack.js','utf8'),c);const editor=c.createFontStackEditor(host);editor.load(saved);
 c.globalFontEditor=editor;c.typography=saved;
 const hook=fs.readFileSync('web/typography.js','utf8').split('\n').find(line=>line.includes("addEventListener('corporium-settings-discard'"));vm.runInContext(hook,c);
 return {c,nodes,editor,form,dialog,setHit:el=>hit=el,tags:()=>nodes.get('global-font-stack').children};
}
test('discard restores saved tags immediately even while external settings are still loading, and cancels a pending drag',()=>{
 const saved={uiFonts:['Junicode','Noto Sans'],uiVariant:'italic'},before=JSON.stringify(saved),s=editorSetup(saved);
 const results=s.nodes.get('font-catalog-results');results.children.find(el=>el.dataset.fontAdd==='Source Han Sans SC').onclick();
 assert.deepEqual(plain(s.editor.settings().uiFonts),['Junicode','Noto Sans','Source Han Sans SC']);
 const handle=s.tags()[2].querySelector('button');handle.onkeydown({key:'Home',preventDefault(){}});
 assert.deepEqual(plain(s.editor.settings().uiFonts),['Source Han Sans SC','Junicode','Noto Sans']);
 const drag=s.tags()[0].querySelector('button');drag.onpointerdown({button:0,pointerId:7,clientX:1,clientY:1,preventDefault(){}});
 s.setHit(s.tags()[2]);drag.dispatchEvent({type:'pointermove',pointerId:7,clientX:100,clientY:1});
 s.form.dispatchEvent(new s.c.Event('corporium-settings-discard'));
 assert.deepEqual(plain(s.editor.settings().uiFonts),saved.uiFonts);assert.equal(s.editor.settings().uiVariant,'italic');assert.equal(JSON.stringify(saved),before);
 assert.equal(drag.hasPointerCapture(7),false);assert.equal(drag.listeners.get('pointerup').size,0);
});
test('a font catalog refresh keeps the unsaved order, and removing a tag does not change the saved preference',()=>{
 const saved={uiFonts:['Junicode','Noto Sans','Source Han Sans SC']},s=editorSetup(saved);
 s.tags()[0].querySelector('button').onkeydown({key:'End',preventDefault(){}});
 s.c.window.dispatchEvent(new s.c.Event('corporium-fonts-changed'));
 assert.deepEqual(plain(s.editor.settings().uiFonts),['Noto Sans','Source Han Sans SC','Junicode']);
 s.tags()[0].children.at(-1).onclick();assert.deepEqual(plain(s.editor.settings().uiFonts),['Source Han Sans SC','Junicode']);
 assert.deepEqual(saved.uiFonts,['Junicode','Noto Sans','Source Han Sans SC']);
 s.form.dispatchEvent(new s.c.Event('corporium-settings-discard'));assert.deepEqual(plain(s.editor.settings().uiFonts),saved.uiFonts);
});
test('closed catalogs leave the page tree and reopen with the same buttons, handlers and draft order',()=>{
 const saved={uiFonts:['Junicode','Noto Sans']},s=editorSetup(saved),results=s.nodes.get('font-catalog-results'),buttons=[...results.children];
 buttons.find(n=>n.dataset.fontAdd==='Source Han Sans SC').onclick();const draft=plain(s.editor.settings().uiFonts);
 s.c.document.dispatchEvent({type:'beforetoggle',target:s.dialog,newState:'closed'});s.dialog.open=false;assert.equal(results.children.length,0);
 s.c.document.dispatchEvent({type:'beforetoggle',target:s.dialog,newState:'open'});s.dialog.open=true;assert.deepEqual(results.children,buttons);assert.deepEqual(plain(s.editor.settings().uiFonts),draft);
 buttons.find(n=>n.dataset.fontAdd==='KaiTi').onclick();assert.ok(s.editor.settings().uiFonts.includes('KaiTi'));assert.deepEqual(saved.uiFonts,['Junicode','Noto Sans']);
});
