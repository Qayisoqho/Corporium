const test=require('node:test'),assert=require('node:assert/strict'),fs=require('node:fs'),vm=require('node:vm');
function setup(){
 const c=vm.createContext({window:{},activeLanguage:'one',languageList:[{id:'one',metadata:JSON.stringify({glossary:{'NEG#sup[POT]':'negative','NEG#super[POT]':'negative','NOM#sub[2]':'nominal'}})}],esc:s=>String(s??'').replace(/[&<>"']/g,ch=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[ch])),document:{documentElement:{classList:{toggle(){}}}},localStorage:{getItem:()=>null}});
 c.validFont=()=>true;require('./display-spacing-helpers.js')(c);
 vm.runInContext(fs.readFileSync('web/display-tools.js','utf8'),c);
 vm.runInContext(fs.readFileSync('web/morpheme-colors.js','utf8'),c);return c;
}
const strip=s=>s.replace(/<[^>]*>/g,'');
test('shared text and registered gloss render all scripts, repeated Unicode and escaped HTML safely',()=>{
 const c=setup();assert.equal(c.rich('<img>t#sub[2]#sup[h]#super[𐐀á]'), '&lt;img&gt;t<sub>2</sub><sup>h</sup><sup>𐐀á</sup>');
 for(const syntax of ['sup','super']){const gloss='NEG#'+syntax+'[POT]';assert.match(c.grammarLabel(gloss),/title="negative"[^>]*>NEG<sup>POT<\/sup>/);assert.match(c.richGloss('stem<'+gloss+'>-NOM#sub[2]'),/gloss-infix/);assert.match(c.richGloss(gloss),/NEG<sup>POT<\/sup>/);}
 assert.match(c.rich('#sup[<script>]'),/<sup>&lt;script&gt;<\/sup>/);assert.equal(c.rich('#unknown[x]'), '#unknown[x]');
});
test('source notation remains one editable atom and displayed headwords keep homonym subscripts',()=>{
 const c=setup();for(const syntax of ['sub','sup','super'])assert.deepEqual(Array.from(c.glossEditParts('go-NOM#'+syntax+'[A.B-C].SG')),['go','-','NOM#'+syntax+'[A.B-C]','.','SG']);
 assert.equal(c.lexemeLabel({headword:'t#sup[h]#super[2]',body:{homonym_number:3}}),'t<sup>h</sup><sup>2</sup><sub>3</sub>');
});
test('shared word, sentence tier and inline reading render the same scripts without changing source',()=>{
 const c=setup(),source=fs.readFileSync('web/app.js','utf8');
 for(const name of ['renderExtraLayers','renderSentenceLayers','layerStyle'])vm.runInContext(source.match(new RegExp('^function '+name+'[^\\n]+','m'))[0],c);
 const tier={id:'one',name:'Tier',visible:true,anchor:'ipa',value:'x#sup[1]#sub[2]#super[3]'},body={extra_layers:[tier],sentence_layers:[tier]};
 for(const html of [c.renderExtraLayers(body),c.renderSentenceLayers(body,'ipa')])assert.match(html,/<sup>1<\/sup><sub>2<\/sub><sup>3<\/sup>/);
 assert.equal(tier.value,'x#sup[1]#sub[2]#super[3]');
});
test('infix inspector and whole sentence coloring retain superscripts and exact displayed characters',()=>{
 const c=setup(),api=c.window.CorporiumMorphColors;
 for(const script of ['sub','sup','super']){
  const form='ta<ŋ#'+script+'[h]>ri',gloss='hit<NEG#'+script+'[POT]>',a=form.indexOf('ŋ'),z=form.indexOf('>'),g=gloss.indexOf('NEG'),gz=gloss.indexOf('>');
  const u={key:'0:infix:0',form:'ŋh',display_form:'ŋ#'+script+'[h]',gloss:'NEGPOT',display_gloss:'NEG#'+script+'[POT]'},w={form,gloss,morphemes:[u],morph_colors:[{key:u.key,tone:'infix',form:[[a,z]],gloss:[[g,gz]]}]};
  for(const p of [api.pair(w,'one'),api.unit(w,u,'one')]){assert.match(p.form,new RegExp('<'+(script==='sub'?'sub':'sup')+'>'));assert.match(p.form,/morph-tone-infix/);assert.match(p.gloss,/morph-tone-infix/);assert.doesNotMatch(p.form,/#(?:sub|sup|super)\[/);}
  assert.equal(strip(api.unit(w,u,'one').form),'ŋh');
 }
});
test('partial reduplication in a scripted group maps plain fragments back to the original script ranges',()=>{
 const c=setup(),api=c.window.CorporiumMorphColors,u={key:'group:stem',form:'je2…su',display_form:'je#sup[2]…su',gloss:'stem',fragments:[{start:0,end:3,text:'je2'},{start:5,end:7,text:'su'}]},w={redup_colors:[{key:'r:0:host',form:[[0,9]],fragments:[{start:0,end:3,text:'je2'}]}]};
 const p=api.unit(w,u,'one');assert.equal(strip(p.form),'je2…su');assert.match(p.form,/<sup><span class="morph-tone morph-tone-reduplication"[^>]*>2<\/span><\/sup>/);assert.match(p.form,/morph-tone-base[^>]*>…su/);
});
test('rich note editor keeps literal functions through editing while reading renders scripts',()=>{
 const c=setup();vm.runInContext(fs.readFileSync('web/rich-text.js','utf8'),c);const r=[{text:'t#sup[h] #sub[2] #super[3]',bold:true}],rt=c.window.CorporiumRichText;
 assert.match(rt.markup(r),/<b>t<sup>h<\/sup> <sub>2<\/sub> <sup>3<\/sup><\/b>/);
 const html=rt.box('draft','Notes',r);assert.match(html,/contenteditable="true">.*#sup\[h\]/);assert.doesNotMatch(html,/<sup>|<sub>/);assert.equal(r[0].text,'t#sup[h] #sub[2] #super[3]');
});
