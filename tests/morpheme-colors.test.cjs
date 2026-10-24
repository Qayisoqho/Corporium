const test=require('node:test'),assert=require('node:assert/strict'),vm=require('node:vm'),fs=require('node:fs');
function setup(){const c={window:{},activeLanguage:'one',languageList:[{id:'one',metadata:JSON.stringify({glossary:{PST:'past',CL:'clitic',NEG:'negative','neg#sub[POT]':'potential negative'}})}],esc:s=>String(s??'').replace(/[&<>"']/g,ch=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[ch])),document:{documentElement:{classList:{toggle(){}}}},localStorage:{getItem:()=>null}};
 vm.createContext(c);vm.runInContext(fs.readFileSync('web/display-tools.js','utf8'),c);c.rich=s=>c.esc(s).replace(/#sub\[([^\[\]]*)\]/g,'<sub>$1</sub>').replace(/\\([~?\[\]#])/g,'$1');vm.runInContext(fs.readFileSync('web/morpheme-colors.js','utf8'),c);return c;}
const stripTone=s=>s.replace(/<span class="morph-tone[^>]*>([^<]*)<\/span>/g,'$1');
test('dictionary reading columns align morphological boundaries without splitting tags or script markup',()=>{
 const c=setup(),api=c.window.CorporiumMorphColors,w={form:'root#sub[2]-na=ke',gloss:'家-GEN.SG=CL',morph_colors:[{tone:'base',form:[[0,10]],gloss:[[0,1]]},{tone:'affix',form:[[11,13]],gloss:[[2,8]]},{tone:'clitic',form:[[14,16]],gloss:[[9,11]]}]};
 const p=api.aligned(w,'one');assert.equal(p.columns,5);assert.equal((p.form.match(/class="interlinear-part"/g)||[]).length,5);assert.equal((p.gloss.match(/class="interlinear-part"/g)||[]).length,5);
 assert.match(p.form,/<sub>/);assert.match(p.gloss,/GEN.SG/);assert.match(p.form,/morph-tone-affix/);assert.match(p.gloss,/morph-tone-clitic/);
 const text=html=>html.replace(/<[^>]*>/g,'');assert.equal(text(p.form),'root2-na=ke');assert.equal(text(p.gloss),w.gloss);
 const infix=api.aligned({form:'ta<ŋ>ri-n',gloss:'打<neg#sub[POT]>过-GEN',morphemes:[{kind:'infix'}]},'one');assert.equal(infix.columns,7);assert.match(infix.gloss,/<sub>POT<\/sub>/);
 const unknown=api.aligned({form:'ta<ŋ>ri-n',gloss:'打<unlisted#sub[2]>过-GEN',morphemes:[{kind:'infix'}]},'one');assert.match(unknown.gloss,/unlisted<sub>2/);assert.doesNotMatch(unknown.gloss,/grammar-label[^>]*>unlisted/);assert.doesNotMatch(unknown.gloss,/gloss-relation/);
 for(const pair of [{form:'a-b',gloss:'A=B'},{form:'a',gloss:'A.SG'},{form:'a-b',gloss:'A-B-C'}])assert.equal(api.aligned(pair,'one').columns,undefined);
});
test('confirmed reduplicant overlays override dictionary tones without changing the base or tilde',()=>{
 const c=setup(),api=c.window.CorporiumMorphColors,w={form:'je~jepasu',gloss:'RED~go',morph_colors:[{tone:'affix',form:[[0,2]],gloss:[[0,3]]},{tone:'clitic',form:[[3,9]],gloss:[[4,6]]}],redup_colors:[{tone:'reduplication',form:[[0,2]],gloss:[[0,3]]}]};
 for(const p of [api.pair(w,'one'),api.aligned(w,'one')]){assert.match(p.form,/morph-tone-reduplication[^>]*>je<\/span>/);assert.match(p.gloss,/morph-tone-reduplication[^>]*>RED<\/span>/);assert.match(p.form,/morph-tone-clitic[^>]*>jepasu/);assert.doesNotMatch(p.form,/morph-tone-reduplication[^>]*>~/);}
 const p=api.pair({...w,redup_colors:[]},'one');assert.match(p.form,/morph-tone-affix[^>]*>je/);assert.doesNotMatch(p.form,/morph-tone-reduplication/);
});
test('source overlays preserve text, scripts and overlapping source ranges over whole-word dictionary tones',()=>{
 const c=setup(),api=c.window.CorporiumMorphColors,form='𐐀á#sub[2]~base',gloss='RED#sub[2]~go',w={form,gloss,morph_colors:[{tone:'affix',form:[[0,Array.from(form).length]],gloss:[[0,gloss.length]]}],redup_colors:[{tone:'reduplication',form:[[0,4],[0,10]],gloss:[[0,10]]}]};
 const p=api.pair(w,'one');assert.equal(stripTone(p.form),c.rich(form));assert.equal(stripTone(p.gloss),c.richGloss(gloss));assert.match(p.form,/<sub><span class="morph-tone morph-tone-reduplication"[^>]*>2/);
});
test('inspector projects partial source fragments and leaves a custom combined gloss uncolored',()=>{
 const c=setup(),api=c.window.CorporiumMorphColors,overlay={key:'r:0:host',tone:'reduplication',form:[[0,2]],gloss:[[0,3]],fragments:[{start:0,end:2,text:'je'}],gloss_fragments:[{start:0,end:3,text:'RED'}]},w={redup_colors:[overlay]};
 const source=api.unit(w,{key:'r:0:host',form:'je',gloss:'RED'},'one');assert.match(source.form,/morph-tone-reduplication/);assert.match(source.gloss,/morph-tone-reduplication/);
 const group={key:'group:stem',form:'je…su',gloss:'stem',fragments:[{start:0,end:2,text:'je'},{start:4,end:6,text:'su'}],gloss_fragments:[{start:0,end:3,text:'RED'},{start:5,end:7,text:'go'}]};
 const p=api.unit(w,group,'one');assert.match(p.form,/morph-tone-reduplication[^>]*>je<\/span>/);assert.match(p.form,/morph-tone-base[^>]*>…su/);assert.doesNotMatch(p.gloss,/morph-tone-reduplication/);
 const blank=api.unit({redup_colors:[{...overlay,gloss:[]}]},{key:'r:0:host',form:'je',gloss:'unpaired'},'one');assert.doesNotMatch(blank.gloss,/morph-tone-reduplication/);
});
test('paired coloring preserves registered labels, punctuation, and every source character',()=>{
 const c=setup(),w={form:'root-na=ke',gloss:'root-PST=CL',morph_colors:[{tone:'base',form:[[0,4]],gloss:[[0,4]]},{tone:'affix',form:[[5,7]],gloss:[[5,8]]},{tone:'clitic',form:[[8,10]],gloss:[[9,11]]}]};
 const pair=c.window.CorporiumMorphColors.pair(w,'one');assert.equal(stripTone(pair.form),c.rich(w.form));assert.equal(stripTone(pair.gloss),c.richGloss(w.gloss));
 assert.match(pair.form,/morph-tone-affix[^>]*>na<\/span>/);assert.match(pair.gloss,/grammar-label[^>]*><span class="morph-tone morph-tone-affix">PST/);
 assert.match(pair.form,/morph-tone-clitic[^>]*>ke/);assert.match(pair.gloss,/morph-tone-clitic">CL/);
});
test('infix color survives bracket context and Typst subscripts without changing gloss typography',()=>{
 const c=setup(),form='ta<ŋ>ri',gloss='打<neg#sub[POT]>过',w={form,gloss,morph_colors:[{tone:'base',form:[[0,2],[5,7]],gloss:[[0,1],[15,16]]},{tone:'infix',form:[[3,4]],gloss:[[2,14]]}]};
 const p=c.window.CorporiumMorphColors.pair(w,'one');assert.equal(stripTone(p.form),c.rich(form));assert.equal(stripTone(p.gloss),c.richGloss(gloss));assert.match(p.gloss,/<sub><span class="morph-tone morph-tone-infix">POT<\/span><\/sub>/);
});
test('astral characters, combining marks and script runs use code points on both lines',()=>{
 const c=setup(),raw='𐐀á#sub[21]-ŋ',html=c.rich(raw),colored=c.window.CorporiumMorphColors.decorate(raw,html,[{tone:'infix',form:[[0,11]]}],'form');assert.equal(stripTone(colored),html);assert.match(colored,/morph-tone-infix/);
});
test('unsupported or mismatched markup falls back safely and tone names cannot inject HTML',()=>{
 const c=setup(),api=c.window.CorporiumMorphColors;assert.equal(api.decorate('different','<sub>x</sub>',[{tone:'infix',form:[[0,3]]}],'form'),'<sub>x</sub>');
 const html=api.decorate('x','x',[{tone:'bad" onclick="x',form:[[0,1]]}],'form');assert.equal(html,'<span class="morph-tone morph-tone-base">x</span>');
});
test('inspector units reuse source roles including grouped members without recoloring shared tag definitions',()=>{
 const c=setup(),api=c.window.CorporiumMorphColors,roles=['base','affix','clitic','infix','circumfix','connector','multipart'];
 const w={form:'root-na',gloss:'root-PST',morphemes:roles.map((tone,i)=>({key:String(i),members:['member-'+i]})),morph_colors:roles.map((tone,i)=>({key:String(i),tone}))};
 const original=c.grammarLabel('PST');
 for(const [i,tone] of roles.entries()){
  for(const key of [String(i),'member-'+i]){const p=api.unit(w,{key,form:'á#sub[2]',display_gloss:'neg#sub[POT]'},'one');assert.match(p.form,new RegExp('morph-tone-'+tone));assert.match(p.gloss,new RegExp('morph-tone-'+tone));assert.match(p.form,/<sub>/);assert.match(p.gloss,/<sub>/);}
 }
 assert.equal(c.grammarLabel('PST'),original);assert.doesNotMatch(original,/morph-tone/);
 assert.match(api.unit(w,{key:'unlinked',form:'na',gloss:'PST'},'one').gloss,/morph-tone-base/);
 assert.equal(api.unit(w,w,'one').form,api.pair(w,'one').form);
 assert.equal(api.unit({morph_colors:[]},{form:'na',gloss:'PST'},'one').gloss,'<span class="morph-unclassified">'+c.richGloss('PST','one')+'</span>'); // Ambiguous analyses have no authoritative role.
});
