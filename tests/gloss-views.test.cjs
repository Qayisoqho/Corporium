const test=require('node:test'),assert=require('node:assert/strict'),fs=require('node:fs'),vm=require('node:vm');
const esc=s=>String(s??'').replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
function setup(){
 const c={esc,rich:s=>esc(s).replace(/#sub\[([^\]]*)\]/g,'<sub>$1</sub>'),senseGloss:s=>s.short_gloss||'',languageList:[{id:'a',metadata:JSON.stringify({glossary:{'POSTP#sub[SIM]':'a grammatical label',GEN:'genitive'}})},{id:'b',metadata:'{}'}],languageTypography:()=>'',activeLanguage:'b'};
 vm.createContext(c);
 const display=fs.readFileSync('web/display-tools.js','utf8'),synonyms=fs.readFileSync('web/synonyms.js','utf8');
 vm.runInContext(display.slice(0,display.indexOf('function glossEditParts(')),c);
 vm.runInContext(synonyms.slice(0,synonyms.indexOf('function focusSynonymDestination(')),c);
 return c;
}
test('synonym gloss keeps decorated labels and separates ordinary POS and definition text',()=>{
 const c=setup(),parts=[{kind:'text',text:'GEN'},{kind:'gloss',text:'postp#sub[SIM].#sub[GEN]'},{kind:'text',text:'GEN <unsafe>'}];
 const html=c.synonymSenseLabel({label_parts:parts},'a');
 assert.match(html,/^GEN · <span class="gloss"/);
 assert.match(html,/grammar-label[^>]*>postp<sub>SIM<\/sub>/);
 assert.match(html,/<sub><span class="grammar-label"[^>]*>GEN<\/span><\/sub>/);
 assert.match(html,/ · GEN &lt;unsafe&gt;$/);
 assert.equal((html.match(/class="grammar-label"/g)||[]).length,2);
});
test('gloss display uses the requested inventory and refreshes it after an edit',()=>{
 const c=setup();assert.doesNotMatch(c.glossDisplay('postp#sub[SIM]','b'),/grammar-label/);
 c.languageList[1].metadata=JSON.stringify({glossary:{'POSTP#sub[SIM]':'new label'}});
 assert.match(c.glossDisplay('postp#sub[SIM]','b'),/class="grammar-label" title="new label"/);
 assert.match(c.glossDisplay('<img onerror=x>','a'),/&lt;img onerror=x&gt;/);
});
test('legacy or missing synonym descriptions remain escaped ordinary text',()=>{
 const c=setup();assert.equal(c.synonymSenseLabel({label:'GEN <unsafe>'},'a'),'GEN &lt;unsafe&gt;');
 assert.equal(c.senseDisplay({definition:'GEN <unsafe>'},'a'),'GEN &lt;unsafe&gt;');
 assert.match(c.senseDisplay({short_gloss:'GEN'},'a'),/class="grammar-label"/);
});
