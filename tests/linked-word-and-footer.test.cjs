const test=require('node:test'),assert=require('node:assert/strict'),fs=require('node:fs'),vm=require('node:vm');
const app=fs.readFileSync('web/app.js','utf8'),context={window:{},phonologicalBoundary:()=>false,rich:s=>s,richGloss:s=>s,esc:s=>s||'',renderExtraLayers:()=>''};
vm.createContext(context);vm.runInContext(app.slice(app.indexOf('function renderWord('),app.indexOf('function renderBody(')),context);
test('whole links and complete component links underline both clickable and independent word forms',()=>{
 for(const value of [{linked_lexeme:'word'},{morph_colors:[{linked:true},{linked:true}]},{dictionary_linked:true}]){
  assert.match(context.renderWord({form:'root-n',gloss:'root-GEN',unit_id:'u',...value},'ordos'),/form is-linked word-dictionary/);
  assert.match(context.renderWord({form:'root-n',gloss:'root-GEN',...value},'ordos'),/span class="form is-linked"/);
 }
});
test('missing, partial and empty component coverage never acquires an underline',()=>{
 for(const colors of [undefined,[],[{linked:false}],[{linked:true},{linked:false}]])assert.doesNotMatch(context.renderWord({form:'root-n',gloss:'root-GEN',unit_id:'u',morph_colors:colors},'ordos'),/is-linked/);
});

test('dictionary evidence marks the bound slot among identical spellings without changing shared data',()=>{
 const body={words:[{form:'n',gloss:'GEN'},{form:'n',gloss:'GEN'}]},before=JSON.stringify(body);
 context.renderEditableExample=b=>b.words.map(w=>context.renderWord(w,'ordos')).join('');
 const html=context.renderDictionaryExample(body,'corpus','e',[{active:1,word_position:1}]);
 assert.equal((html.match(/data-dictionary-evidence/g)||[]).length,1);assert.match(html,/data-dictionary-evidence="2"/);assert.equal(JSON.stringify(body),before);
 assert.doesNotMatch(context.renderDictionaryExample(body,'corpus','e',[{active:0,word_position:0},{active:1,word_position:1,needs_review:true}]),/data-dictionary-evidence/);
});

test('independent evidence can highlight several slots but never detached or stale targets',()=>{
 const body={words:Array.from({length:3},()=>({form:'n',gloss:'GEN'}))};
 const html=context.renderDictionaryExample(body,'independent','e',[{segmentation_ref:{word:0,key:'@word'}},{segmentation_ref:{word:2,key:'0:host'}},{segmentation_ref:{word:1,key:'@word',detached:true}},{segmentation_ref:{word:1,key:'@word'},segmentation_review:true}]);
 assert.match(html,/data-dictionary-evidence="1"/);assert.match(html,/data-dictionary-evidence="3"/);assert.doesNotMatch(html,/data-dictionary-evidence="2"/);
 assert.match(context.renderDictionaryExample(body,'independent','e',[{}]),/句级引用，未指定关联词格/);
 assert.doesNotMatch(context.renderWord({form:'n',gloss:'GEN',dictionary_evidence:'<unsafe>'},'ordos'),/data-dictionary-evidence/);
});

test('timeline reading key changes with the source sentence revision while interval and viewport remain unchanged',()=>{
 const source=fs.readFileSync('web/timeline.js','utf8'),s={sid:'t',data:{gloss_revision:'g1'}};vm.createContext(s);vm.runInContext(source.match(/^const intervalKey=[^\n]+/m)[0]+'\nthis.key=intervalKey;',s);
 const interval={id:'i',revision:2,entry_revision:3};assert.equal(s.key(interval),s.key({...interval}));assert.notEqual(s.key(interval),s.key({...interval,entry_revision:4}));assert.equal(s.key(null),'');
 const previous=s.key(interval);s.data.gloss_revision='g2';assert.notEqual(s.key(interval),previous);
});

test('automatic preview pairs use the effective language typography rather than interface boldface',()=>{
 const source=fs.readFileSync('web/lexicon-extra.js','utf8'),s={autoLanguage:'a',languageList:[{id:'a',metadata:'{"annotation_font":"Junicode"}'},{id:'b',metadata:'{"annotation_font":"Doulos SIL","morpheme_variant":"regular"}'}],languageTypography:m=>m.annotation_font,rich:context.rich,richGloss:(g,lid)=>g+':'+lid,esc:context.esc};
 vm.createContext(s);vm.runInContext(source.slice(source.indexOf('function autoMatchPair('),source.indexOf("$('auto-link-preview').onclick")),s);
 const html=s.autoMatchPair({form:'n',gloss:'GEN',effective_language_id:'b'});assert.match(html,/style="Doulos SIL"/);assert.match(html,/class="form">n/);assert.match(html,/GEN:b/);assert.doesNotMatch(html,/<strong>/);
});

class Node{
 constructor(tag,id=''){this.tag=tag;this.id=id;this.children=[];this.dataset={};this.open=true;}
 get firstChild(){return this.children[0];}
 append(...nodes){for(const n of nodes){if(n.parent)n.parent.children.splice(n.parent.children.indexOf(n),1);n.parent=this;this.children.push(n);}}
 prepend(n){this.append(n);this.children.unshift(this.children.pop());}
 querySelectorAll(selector){const matches=n=>selector==='form[method="dialog"]'?n.tag==='form':selector==='button.primary,button[type="submit"]'?n.tag==='button'&&n.primary:selector.startsWith('#')?n.id===selector.slice(1):n.tag===selector;return this.children.flatMap(n=>[...(matches(n)?[n]:[]),...n.querySelectorAll(selector)]);}
 querySelector(s){return this.querySelectorAll(s)[0];}
}
test('docking keeps candidate selection and confirmation beside the fixed primary action',()=>{
 const source=fs.readFileSync('web/ui-tools.js','utf8'),c={document:{createElement:tag=>new Node(tag)}};vm.createContext(c);vm.runInContext(source.slice(source.indexOf('function dockDialog('),source.indexOf('new MutationObserver(records=>')),c);
 const d=new Node('dialog','auto-link-dialog'),form=new Node('form'),content=new Node('div'),primary=new Node('button'),actions=new Node('span','auto-candidate-actions'),all=new Node('input'),confirm=new Node('button');primary.primary=true;
 const listener=()=>{};all.onchange=listener;actions.append(all,confirm);content.append(primary,actions);d.append(form,content);c.dockDialog(d);
 const footer=d.children.find(n=>n.className==='dialog-bottom');assert.equal(actions.parent,footer);assert.equal(primary.parent,footer);assert.equal(footer.children[0],actions);assert.equal(all.onchange,listener);assert.equal(all.parent,actions);assert.equal(confirm.parent,actions);
 c.dockDialog(d);assert.equal(d.children.filter(n=>n.className==='dialog-bottom').length,1);
});
