const test=require('node:test'),assert=require('node:assert/strict'),ipa=require('../web/ipa-symbols.js');
test('IPA inventory contains pulmonic/non-pulmonic consonants, vowels and prosody without duplicate inserts',()=>{
 assert.equal(new Set(ipa.symbols.map(s=>s.text)).size,ipa.symbols.length);
 for(const symbol of ['ŋ','ʄ','ǂ','ɐ','ɞ','ʰ','ː','˥','ꜜ','͡'])assert.ok(ipa.symbols.some(s=>s.text===symbol),symbol);
 for(const category of Object.keys(ipa.categories))assert.ok(ipa.find('',category).length>0);
});
test('combining marks display a dotted-circle placeholder but insert only the Unicode mark',()=>{
 for(const s of ipa.symbols.filter(s=>/^\p{M}/u.test(s.text))){assert.equal(s.display,'◌'+s.text);assert.ok(!s.text.includes('◌'));}
 const ring=ipa.find('清化').find(s=>s.text==='\u0325');assert.equal('n'+ring.text,'n̥');
});
test('lookup accepts symbol, Chinese, English and Unicode codepoint',()=>{
 for(const q of ['ŋ','软腭鼻音','velar nasal','u+014b'])assert.ok(ipa.find(q).some(s=>s.text==='ŋ'),q);
 assert.equal(ipa.find('not-a-symbol-name').length,0);
});

test('reviewed Chinese names are used verbatim and unchanged names remain available',()=>{
 const names=new Map(ipa.symbols.map(s=>[s.text,s.name]));
 for(const [text,name] of [['p','双唇爆发音（清）'],['t','龈爆发音（清）'],['i','高前不圆唇元音'],['ʊ','高后圆唇元音（央化）'],['r','龈鼻音'],['w','唇软腭擦音（浊）'],['ˈ','主重读'],['\u0324','气嗓声'],['ŋ','软腭鼻音']])assert.equal(names.get(text),name);
 assert.ok(ipa.find('爆发音').some(s=>s.text==='p'));
 assert.ok(ipa.find('高前不圆唇').some(s=>s.text==='i'));
 assert.equal(ipa.find('塞音').length,0); // Old generated Chinese terms must not leak from English keywords.
});

test('the five deleted tone contours are absent while individual tone bars remain',()=>{
 for(const text of ['˩˥','˥˩','˧˥','˩˧','˥˩˥']){assert.equal(ipa.symbols.some(s=>s.text===text),false);assert.equal(ipa.find(text).length,0);}
 for(const text of ['˥','˦','˧','˨','˩'])assert.ok(ipa.symbols.some(s=>s.text===text));
});

test('ten supplementary symbols have their own category, real Unicode characters and searchable names',()=>{
 assert.equal(ipa.symbols.length,183);assert.equal(ipa.categories.sinitic,'汉语语言学符号');
 const expected={'ȶ':0x0236,'ȡ':0x0221,'ȵ':0x0235,'ȴ':0x0234,'ɿ':0x027f,'ʮ':0x02ae,'ʅ':0x0285,'ʯ':0x02af,'ᴇ':0x1d07,'ᴀ':0x1d00};
 assert.equal(ipa.find('','sinitic').length,10);
 for(const [text,cp] of Object.entries(expected)){const s=ipa.symbols.find(s=>s.text===text);assert.equal(s.category,'sinitic');assert.equal(s.text.codePointAt(0),cp);assert.ok(ipa.find('u+'+cp.toString(16).padStart(4,'0')).some(s=>s.text===text));}
 assert.ok(ipa.find('龈腭爆发音').some(s=>s.text==='ȶ'));
 assert.ok(ipa.find('apical alveolar rounded vowel').some(s=>s.text==='ʮ'));
 assert.ok(ipa.symbols.some(s=>s.text==='ɣ')); // U+0263 in the supplement was a typo for ȶ, not a replacement of ɣ.
});

test('every key tooltip shows the current approved name and actual inserted Unicode sequence',()=>{
 const fs=require('node:fs'),vm=require('node:vm'),source=fs.readFileSync('web/ipa-keyboard.js','utf8'),context={favorites:[],esc:s=>String(s).replace(/[&<>"]/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;'}[c]))};
 vm.createContext(context);vm.runInContext(source.slice(source.indexOf(' function keys('),source.indexOf(' function render(')),context);
 for(const s of ipa.symbols){const title=s.name+' · '+[...s.text].map(c=>'U+'+c.codePointAt(0).toString(16).toUpperCase().padStart(4,'0')).join(' ');assert.ok(context.keys([s]).includes('title="'+context.esc(title)+'"'),s.text);}
});

test('favorites and recent entries discard removed tone combinations without losing other saved symbols',()=>{
 const fs=require('node:fs'),vm=require('node:vm'),source=fs.readFileSync('web/ipa-keyboard.js','utf8'),context={known:new Map(ipa.symbols.map(s=>[s.text,s])),storage:k=>k,localStorage:{getItem:()=>JSON.stringify(['˩˥','ŋ','˥˩˥','ȶ','ŋ'])}};
 vm.createContext(context);vm.runInContext(source.slice(source.indexOf(' function read('),source.indexOf(' function save(')),context);
 assert.deepEqual([...context.read('favorites')],['ŋ','ȶ']);assert.deepEqual([...context.read('recent')],['ŋ','ȶ']);
});
