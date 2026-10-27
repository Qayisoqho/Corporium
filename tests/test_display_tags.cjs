const fs=require('fs'),vm=require('vm'),assert=require('node:assert/strict');
const ctx={activeLanguage:'test',languageList:[{id:'test',metadata:JSON.stringify({glossary:{'neg#sub[POT]':'potential negative','sg':'singular'}})}],esc:s=>String(s??'').replaceAll('&','&amp;').replaceAll('<','&lt;').replaceAll('>','&gt;'),localStorage:{getItem:()=>null},document:{documentElement:{classList:{toggle(){}}}}};
vm.createContext(ctx);vm.runInContext(fs.readFileSync('web/display-tools.js','utf8'),ctx);
assert.equal(ctx.richGloss('neg#sub[POT]'),'<span class="grammar-label" title="potential negative">neg<sub>POT</sub></span>');
assert.match(ctx.grammarLabel('neg#super[2]'),/neg<sup>2<\/sup>/);
assert.match(ctx.richGloss('neg#sub[POT]-SG'),/<\/span>-<span class="grammar-label" title="singular">SG/);
assert.ok(!ctx.grammarLabel('<img>').includes('<img>'));
for(const registered of [true,false]){
 ctx.languageList[0].metadata=JSON.stringify({glossary:registered?{'neg#sub[POT]':'negative','prt':'particle'}:{'prt':'particle'}});
 const result=ctx.richGloss('打<neg#sub[POT]>过+来=PRT');
 if(registered)assert.match(result, /打<span class="gloss-infix">&lt;<span class="grammar-label"[^>]*>neg<sub>POT<\/sub><\/span>&gt;<\/span>过\+来=/);
 if(!registered){assert.match(result,/neg<sub>POT<\/sub>/);assert.equal((result.match(/grammar-label/g)||[]).length,1);}
 assert.ok(!result.includes('gloss-relation'));
 if(registered)assert.match(ctx.richGloss('[neg#sub[POT]]'), /class="gloss-bracket">\[<span class="grammar-label"[^>]*>neg<sub>POT/);
}
// All sentence workspaces share richGloss; exercise both superscript spellings,
// combined scripts, registered aliases, brackets, and HTML escaping.
for (const syntax of ['sup','super']) {
 ctx.languageList[0].metadata=JSON.stringify({glossary:{['neg#'+syntax+'[2]']:'negative'}});
 assert.equal(ctx.richGloss('neg#'+syntax+'[2]'),'<span class="grammar-label" title="negative">neg<sup>2</sup></span>');
 assert.match(ctx.richGloss('打<neg#sub[POT]#'+syntax+'[2]>来'), /neg<sub>POT<\/sub><sup>2<\/sup>/);
 assert.match(ctx.richGloss('[neg#'+syntax+'[2]]'), /gloss-bracket.*grammar-label.*<sup>2<\/sup>/);
}
assert.equal(ctx.grammarLabel('neg#sub[POT]#sup[2]'),'<span class="grammar-label">neg<sub>POT</sub><sup>2</sup></span>');
assert.ok(!ctx.grammarLabel('neg#sub[<img>]#sup[<svg>]').includes('<img>'));
assert.ok(!ctx.richGloss('<neg#sub[<img>]>').includes('<img>'));
console.log('19 script-tag rendering assertions passed');
