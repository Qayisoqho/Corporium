const test=require('node:test'),assert=require('node:assert/strict'),vm=require('node:vm'),fs=require('node:fs');
const source=fs.readFileSync('web/code-switching.js','utf8');
function setup(){
 const c={window:{},activeLanguage:'one',languageList:[{id:'one',metadata:JSON.stringify({glossary:{GEN:'genitive',SG:'singular',CL:'clitic',PL:'plural'}})}],document:{documentElement:{classList:{toggle(){}}}},localStorage:{getItem:()=>null},esc:s=>String(s??'').replace(/[&<>"']/g,ch=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[ch]))};
 c.escape=c.esc;c.rich=s=>c.esc(s).replace(/#(sub|sup|super)\[([^\[\]]*)\]/g,(_,k,v)=>'<'+(k==='sub'?'sub':'sup')+'>'+v+'</'+(k==='sub'?'sub':'sup')+'>');
 vm.createContext(c);vm.runInContext(fs.readFileSync('web/display-tools.js','utf8'),c);vm.runInContext(fs.readFileSync('web/morpheme-colors.js','utf8'),c);
 vm.runInContext(source.slice(source.indexOf(' function word(w)'),source.indexOf(' function stats(s)')),c);
 c.window.CorporiumCodes={pair:c.pair,gloss:c.gloss};return c;
}
const mark={span_id:'span',name:'Other <language>',short:'ZH',notes:'quotation & test',end:true,start:true};
function word(){return {form:'root-na=ke',gloss:'家-GEN.SG=CL',code_cells:[
 {form:[0,4],gloss:[0,1],key:'root',mark},
 {form:[4,5],gloss:[1,2],key:null},
 {form:[5,7],gloss:[2,8],key:'suffix'},
 {form:[7,8],gloss:[8,9],key:null},
 {form:[8,10],gloss:[9,11],key:'clitic'}]};}
const visible=s=>s.replace(/<[^>]+>/g,'').replaceAll('&lt;','<').replaceAll('&gt;','>');

test('only tagged morpheme cells receive highlights and a separate final label column',()=>{
 const c=setup(),w=word(),before=JSON.stringify(w),p=c.pair(w,'one',{});
 assert.equal(p.code,true);assert.equal(p.columns,6);
 assert.equal((p.form.match(/class="interlinear-part code-morpheme"/g)||[]).length,1);
 assert.equal((p.gloss.match(/code-word-label/g)||[]).length,1);
 assert.equal(visible(p.form),w.form);assert.equal(visible(p.gloss),'家ZH-GEN.SG=CL');
 assert.match(p.gloss,/grammar-label/);assert.match(p.gloss,/&lt;language&gt;/);assert.match(p.form,/code-label-space/);
 assert.equal(JSON.stringify(w),before);
 c.CorporiumI18n={ui:(zh,en)=>en,f:()=>undefined};
 const uncertain=c.word({code_mark:{...mark,code_id:null,name:'未确定',short:'?'}});
 assert.match(uncertain,/Uncertain/);assert.doesNotMatch(uncertain,/未确定/);
});

test('morpheme code backgrounds retain affix and reduplicant colors and script formatting',()=>{
 const c=setup(),w=word();w.code_cells[0].mark=undefined;w.code_cells[2].mark=mark;
 w.morph_colors=[{tone:'affix',form:[[5,7]],gloss:[[2,8]]}];
 w.redup_colors=[{tone:'reduplication',form:[[0,4]],gloss:[[0,1]]}];
 const p=c.pair(w,'one',{});assert.match(p.form,/morph-tone-affix/);assert.match(p.form,/morph-tone-reduplication/);
 assert.match(p.gloss,/grammar-label[^>]*><span class="morph-tone morph-tone-affix">GEN/);
 const form='a#sup[21]-b',gloss='A#sub[GEN]-PL',f=form.indexOf('-'),g=gloss.indexOf('-');
 const scripted=c.pair({form,gloss,code_cells:[{form:[0,f],gloss:[0,g],key:'a',mark},{form:[f,f+1],gloss:[g,g+1],key:null},{form:[f+1,form.length],gloss:[g+1,gloss.length],key:'b'}]},'one',{});
 assert.equal(visible(scripted.form),'a21-b');assert.match(scripted.form,/<sup>21<\/sup>/);assert.match(scripted.gloss,/<sub>(?:<span[^>]*>)?GEN/);
});

test('a discontinuous unit marks all fragments without coloring the intervening root',()=>{
 const c=setup(),w=word();w.code_cells[0].mark=mark;w.code_cells[4].mark=mark;
 const p=c.pair(w,'one',{});assert.equal(p.columns,7);assert.equal((p.gloss.match(/code-word-label/g)||[]).length,2);
 assert.doesNotMatch(p.form,/code-morpheme[^>]*>na/);assert.equal(visible(p.form),w.form);
});

test('malformed projections fall back to the original complete rich pair',()=>{
 const c=setup(),w=word(),base={form:'original form',gloss:'original gloss'};
 for(const cells of [[{form:[0,2],gloss:[0,1],mark}],w.code_cells.map((cell,i)=>i===1?{...cell,form:[2,5]}:cell)]){
  assert.equal(c.pair({...w,code_cells:cells},'one',base),base);
 }
});

test('shared sentence renderer uses the same morpheme grid in reading and analysis contexts',()=>{
 const c=setup(),app=fs.readFileSync('web/app.js','utf8');c.renderExtraLayers=()=>'<span class="extra-layer">custom</span>';
 vm.runInContext(app.slice(app.indexOf('function renderWord('),app.indexOf('function renderBody(')),c);
 const w={...word(),unit_id:'word',dictionary_linked:true};
 for(const context of [false,true]){const html=c.renderWord(w,'one',false,context);assert.match(html,/code-interlinear-word/);assert.match(html,/--word-columns:6/);assert.match(html,/extra-layer/);assert.equal(html.includes('word-dictionary'),!context);}
});

test('editor groups cells by word, exposes whole-word picking and localizes without translating material',()=>{
 for(const locale of ['zh','en']){
  const c=setup(),u={id:'["word","0:host"]',form:'root',gloss:'GEN.SG'};
  c.globalThis=c;c.CorporiumI18n={ui:(zh,en)=>locale==='en'?en:zh,f:()=>undefined};c.document.activeElement=null;
  c.state={panel:{innerHTML:'',querySelector:()=>({value:''})},data:{language_id:'one',profile:{base_name:'源语言'},words:[{id:'word',form:'root-na',selectable:true,live:true,morphemes:[u]}],codes:[],intervals:[],spans:[]},selected:new Set([u.id]),code:'',notes:'<notes>',editing:null};
  vm.runInContext(source.slice(source.indexOf(' const t='),source.indexOf(' async function open(card)')),c);vm.runInContext('draw()',c);
  const html=c.state.panel.innerHTML;assert.match(html,/data-code-pick-word="word"/);assert.match(html,/data-code-pick="\[&quot;word/);assert.match(html,/aria-pressed="true"/);assert.match(html,/&lt;notes&gt;/);assert.match(html,/源语言/);
  assert.ok(html.includes(locale==='en'?'Morpheme languages':'语素语码'));assert.ok(html.includes(locale==='en'?'1 morpheme selected':'已选 1 个语素'));
 }
});

test('formatted copy retains code distinctions separately from grammatical small caps',()=>{
 const core=require('../web/formatted-copy-format.js'),r=core.build([{key:'one',label:'(1)',body:{ipa:'a',translation:'b',words:[{form:[{text:'root',code:true},{text:'-na'}],gloss:[{text:'GEN',smallCaps:true,code:true},{text:' ZH ',codeLabel:true,smallCaps:true}]}]}}]);
 assert.match(r.html,/background:#eef1f3/);assert.match(r.html,/font-variant:normal;font-style:normal;font-weight:normal[^>]*> ZH /);
 assert.match(r.html,/font-variant:small-caps/);assert.match(r.plain,/GEN ZH/);
});

test('clipboard DOM reader keeps code marks on glyphs and clears small caps on language names',()=>{
 const node=(tag,classes,children=[])=>({nodeType:1,tagName:tag,classList:{contains:name=>classes.includes(name)},childNodes:children});
 const text=s=>({nodeType:3,nodeValue:s}),tree=[node('SPAN',['code-morpheme'],[node('SPAN',['grammar-label'],[text('GEN')])]),node('SPAN',['code-word-label'],[text('ZH')])];
 const c={document:{createElement:()=>({childNodes:tree})}};vm.createContext(c);const s=fs.readFileSync('web/formatted-copy.js','utf8');
 vm.runInContext(s.slice(s.indexOf(' function readRuns('),s.indexOf(' function itemFor(')),c);
 const runs=c.readRuns('fixture');assert.equal(runs[0].code,true);assert.equal(runs[0].smallCaps,true);
 const lang=runs.find(r=>r.text==='ZH');assert.equal(lang.codeLabel,true);assert.equal(lang.smallCaps,false);assert.equal(lang.italic,false);
});


test('catalog refresh cannot silently adopt a changed segmentation or another saved annotation',()=>{
 const c={};vm.createContext(c);vm.runInContext(source.slice(0,source.indexOf('window.CorporiumCodes')),c);
 const before={revision:1,words:[{id:'word',form:'root-na',morphemes:[{key:'root'}]}],spans:[{id:'span',revision:1,code_id:'zh',word_ids:['word'],snapshot:{word:'root-na'},notes:'',name:'Old'}],intervals:[]};
 const changed=JSON.parse(JSON.stringify(before));changed.words[0].form='new-na';assert.equal(c.codeContextChanged(before,changed),true);
 changed.words=before.words;changed.spans[0].name='Renamed language';assert.equal(c.codeContextChanged(before,changed),false);
 changed.spans[0].revision++;assert.equal(c.codeContextChanged(before,changed),true);
});

test('editing legacy metadata retains every original word until morphemes are explicitly reselected',async()=>{
 for(const selectionChanged of [false,true]){
  let payload;const legacy={id:'span',legacy:true,word_ids:['valid-word','unsegmented-word'],morpheme_ids:['valid-morpheme']};
  const c={state:{kind:'corpus',id:'sentence',editing:'span',selectionChanged,selected:new Set(['valid-morpheme']),code:'zh',notes:'edited',data:{spans:[legacy],owner_language:'one',token:'snapshot'},panel:{inert:false}},busy:false,read(){},originalApi:async(path,b)=>payload=b,api:async()=>({}),close(){c.state=null;},refresh:async()=>{},document:{querySelectorAll:()=>[]},workspace:'corpus',URLSearchParams,corporiumStatus(){}};
  vm.createContext(c);vm.runInContext(source.slice(source.indexOf(' async function apply('),source.indexOf(" document.addEventListener('click'")),c);await vm.runInContext("apply('save')",c);
  assert.equal('morpheme_ids' in payload,selectionChanged);assert.equal('word_ids' in payload,!selectionChanged);
  if(!selectionChanged)assert.deepEqual(Array.from(payload.word_ids),legacy.word_ids);
 }
});

test('an explicit legacy conversion is an unapplied draft even when its visible selection is unchanged',()=>{
 const c={};vm.createContext(c);vm.runInContext(source.slice(0,source.indexOf('window.CorporiumCodes')),c);
 assert.equal(c.codeDraftChanged({selected:new Set(['a']),code:'zh',notes:'',selectionChanged:true},{legacy:true,morpheme_ids:['a'],code_id:'zh',notes:''}),true);
});
