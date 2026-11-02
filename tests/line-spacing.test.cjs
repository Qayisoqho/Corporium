const test=require('node:test'),assert=require('node:assert/strict'),fs=require('node:fs'),vm=require('node:vm');
const spacing=require('../web/line-spacing.js');
const esc=s=>String(s??'').replaceAll('&','&amp;').replaceAll('"','&quot;').replaceAll('<','&lt;');
test('tier internal spacing supports positive and negative values, resets, and follows copy output',()=>{
 assert.equal(spacing.style({line_spacing:25}),'line-height:1.6;');
 assert.equal(spacing.style({line_spacing:-25}),'line-height:1.1;');
 assert.equal(spacing.style({line_spacing:-300}),'line-height:0;');
 assert.equal(spacing.style({line_spacing:null}),'');
 const css={},node={hasAttribute:k=>k==='data-line-layer',style:{setProperty(k,v){css[k]=v;},removeProperty(k){delete css[k];}}};
 spacing.apply(node,{line_spacing:-25});assert.equal(css['line-height'],'1.1');
 spacing.apply(node,{line_spacing:null});assert.equal(css['line-height'],undefined);
 const core=require('../web/formatted-copy-format.js');
 const result=core.build([{key:'internal',body:{ipa:'IPA',translation:'Translation',words:[{form:'a',gloss:'A'}]},sentenceLayers:[{value:'One\nTwo',line_spacing:-25,pt:10}]}]);
 assert.match(result.html,/line-height:11pt;mso-line-height-rule:exactly/);
});
test('reading headers keep all attached IPA tiers together and leave words and translation in place',()=>{
 class Element{
  constructor(cls){this.className=cls;this.children=[];this.parentElement=null;}
  get nextElementSibling(){const p=this.parentElement;return p?.children[p.children.indexOf(this)+1];}
  matches(selector){return selector==='.'+this.className;}
  detach(){if(this.parentElement){const p=this.parentElement;p.children.splice(p.children.indexOf(this),1);}}
  append(...nodes){for(const node of nodes){node.detach();node.parentElement=this;this.children.push(node);}}
  before(node){node.detach();node.parentElement=this.parentElement;this.parentElement.children.splice(this.parentElement.children.indexOf(this),0,node);}
 }
 const c=vm.createContext({document:{createElement:()=>new Element('')}});vm.runInContext(fs.readFileSync('web/line-spacing.js','utf8'),c);
 const card=new Element('card'),ipa=new Element('ipa'),a=new Element('sentence-layer'),b=new Element('sentence-layer'),words=new Element('words'),translation=new Element('translation'),translatedTier=new Element('sentence-layer');
 card.append(ipa,a,b,words,translation,translatedTier);const column=c.CorporiumLineSpacing.readingLines(ipa);
 assert.equal(column.className,'sentence-reading-lines');assert.deepEqual(column.children,[ipa,a,b]);assert.deepEqual(card.children,[column,words,translation,translatedTier]);
 const bare=new Element('ipa');card.append(bare);assert.equal(c.CorporiumLineSpacing.readingLines(bare),bare);
});
test('default spacing is distinct from zero; spacing scales with its own line and never fixes line height',()=>{
 assert.equal(spacing.style({}),'');assert.equal(spacing.style({space_before:null,space_after:null}),'');
 assert.equal(spacing.style({space_before:0,space_after:125}),'margin-top:0em;margin-bottom:1.25em;');
 assert.equal(spacing.style({space_before:12.5}),'margin-top:0.125em;');
 for(const invalid of [-301,301,NaN,Infinity,'30',true])assert.equal(spacing.style({space_before:invalid}),'');
 assert.doesNotMatch(spacing.style({space_before:300,space_after:300}),/line-height|height:|overflow/);
});
test('word and sentence tiers, editor rows and writing renderers consume the same per-definition values',()=>{
 const c=vm.createContext({esc,validFont:()=>true});require('./display-spacing-helpers.js')(c);
 const app=fs.readFileSync('web/app.js','utf8');
 vm.runInContext(app.slice(app.indexOf('function renderExtraLayers'),app.indexOf('\n',app.indexOf('function renderSentenceLayers'))),c);
 const inline=fs.readFileSync('web/inline-editor.js','utf8');vm.runInContext(inline.slice(inline.indexOf('function inlineWordLayer')),c);
 const l={id:'one',visible:true,name:'Tier',anchor:'ipa',font:'Junicode',size:150,space_before:40,space_after:0,value:'a̋'};
 for(const result of [c.renderExtraLayers({extra_layers:[l]}),c.inlineWordLayer(l,{words:[{id:'w'}]},0,new Map([['w|one','a̋']]))]){
  assert.match(result,/data-line-layer="one"/);assert.match(result,/margin-top:0.4em;margin-bottom:0em/);assert.match(result,/--layer-scale:1.5/);
 }
 const sentence=c.renderSentenceLayers({sentence_layers:[l]},'ipa');
 assert.match(sentence,/data-line-block data-line-before data-line-after/);
 assert.match(sentence,/margin-top:0;padding-top:0.4em;margin-bottom:0;padding-bottom:0em/);
 assert.equal(c.renderExtraLayers({extra_layers:[{...l,visible:false}]}),'');
 assert.match(c.writingDisplayAttrs({...l,type_id:'script'}),/data-line-writing="script"/);
 assert.match(c.writingDisplayAttrs({...l,type_id:'script'}),/display:inline-block/);
 assert.doesNotMatch(c.writingDisplayAttrs({id:'other'}),/margin-top|margin-bottom|inline-block/);
});

test('block tier space does not use collapsible margins and resetting restores defaults on both sides',()=>{
 const css={},attrs=new Set(['data-line-block']);
 const node={hasAttribute:k=>attrs.has(k),toggleAttribute(k,on){on?attrs.add(k):attrs.delete(k);},style:{setProperty(k,v){css[k]=v;},removeProperty(k){delete css[k];}}};
 spacing.apply(node,{space_before:50,space_after:100});
 assert.deepEqual(css,{'margin-top':'0','padding-top':'0.5em','margin-bottom':'0','padding-bottom':'1em'});
 assert.ok(attrs.has('data-line-before'));assert.ok(attrs.has('data-line-after'));
 spacing.apply(node,{space_before:0,space_after:null});
 assert.deepEqual(css,{'margin-top':'0','padding-top':'0em'});assert.ok(attrs.has('data-line-before'));assert.ok(!attrs.has('data-line-after'));
 spacing.apply(node,{});assert.deepEqual(css,{});assert.deepEqual([...attrs],['data-line-block']);
});

test('sentence editor reserves tier space outside the control, retaining its content and accessible name',()=>{
 const c=vm.createContext({esc,validFont:()=>true});require('./display-spacing-helpers.js')(c);
 const app=fs.readFileSync('web/app.js','utf8');vm.runInContext(app.slice(app.indexOf('function layerStyle'),app.indexOf('\n',app.indexOf('function layerStyle'))),c);
 const source=fs.readFileSync('web/inline-editor.js','utf8');vm.runInContext(source.slice(source.indexOf('function inlineSentenceLayers'),source.indexOf('\n',source.indexOf('function inlineSentenceLayers'))),c);
 const l={id:'l',name:'Tier',anchor:'ipa',visible:true,font:'Junicode',size:125,space_before:75,space_after:0};
 const result=c.inlineSentenceLayers({layers:[l],cells:[{unit_id:'@sentence',layer_id:'l',value:'Unsaved a̋'}]},'ipa');
 assert.match(result,/<label[^>]*data-line-layer="l"[^>]*padding-top:0.75em/);
 assert.match(result,/<textarea[^>]*aria-label="Tier"[^>]*>Unsaved a̋<\/textarea>/);
 assert.doesNotMatch(result.match(/<textarea[^>]*>/)[0],/padding-top|padding-bottom|margin-top|margin-bottom/);
});
test('live setting changes and reset update only matching rows while preserving draft text',()=>{
 const node=id=>({id,css:{},getAttribute(){return id;},style:{setProperty(k,v){this.owner.css[k]=v;},removeProperty(k){delete this.owner.css[k];}}});
 const a=node('a'),b=node('b');a.style.owner=a;b.style.owner=b;
 const draft={layers:[{id:'a',revision:1}],cells:[{value:'Unsaved'}]};
 const c=vm.createContext({document:{querySelectorAll:()=>[a,b]},inlineDrafts:new Map([['draft',draft]])});
 vm.runInContext(fs.readFileSync('web/line-spacing.js','utf8'),c);
 c.CorporiumLineSpacing.update('layer',[{id:'a',revision:2,space_before:50,space_after:0}]);
 assert.deepEqual(a.css,{'margin-top':'0.5em','margin-bottom':'0em'});assert.deepEqual(b.css,{});
 assert.equal(draft.layers[0].revision,2);assert.equal(draft.cells[0].value,'Unsaved');
 c.CorporiumLineSpacing.update('layer',[{id:'a',space_before:null,space_after:null}]);assert.deepEqual(a.css,{});
});
test('formatted copying preserves tier spacing without changing sentence text',()=>{
 const core=require('../web/formatted-copy-format.js');
 const row={key:'one',body:{ipa:'IPA',translation:'Translation',words:[{form:'a',gloss:'A'}]},layers:[{name:'Tier',values:['extra'],space_before:100,space_after:50}],sentenceLayers:[{anchor:'ipa',value:'Sentence tier',space_before:0,space_after:200,pt:11}]};
 const baseline=core.build([{...row,layers:row.layers.map(l=>({...l,space_before:null,space_after:null})),sentenceLayers:row.sentenceLayers.map(l=>({...l,space_before:null,space_after:null}))}]);
 const result=core.build([row]);assert.equal(result.plain,baseline.plain);
 assert.match(result.html,/margin-top:11pt;mso-margin-top-alt:11pt;margin-bottom:5.5pt/);
 assert.match(result.html,/margin-top:0pt;mso-margin-top-alt:0pt;margin-bottom:22pt/);
});

test('negative tier spacing survives rendering, live edits, reset and formatted copying',()=>{
 assert.equal(spacing.style({space_before:-50,space_after:-25}),'margin-top:-0.5em;margin-bottom:-0.25em;');
 assert.match(spacing.style({space_before:-50},'block'),/padding-top:0em;--line-top-tighten:-0.5em/);
 const css={},node={hasAttribute:()=>true,toggleAttribute(){},style:{setProperty(k,v){css[k]=v;},removeProperty(k){delete css[k];}}};
 spacing.apply(node,{space_before:-50,space_after:-25});assert.equal(css['--line-top-tighten'],'-0.5em');assert.equal(css['padding-top'],'0em');
 spacing.apply(node,{space_before:0});assert.equal(css['--line-top-tighten'],undefined);assert.equal(css['--line-bottom-tighten'],undefined);
 const core=require('../web/formatted-copy-format.js');const result=core.build([{key:'negative',body:{ipa:'IPA',translation:'Translation',words:[{form:'a',gloss:'A'}]},sentenceLayers:[{value:'Tier',space_before:-50,space_after:-25,pt:10}]}]);
 assert.match(result.html,/margin-top:-5pt/);assert.match(result.html,/margin-bottom:-2.5pt/);
});
