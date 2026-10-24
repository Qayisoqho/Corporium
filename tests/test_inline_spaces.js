const test=require('node:test'),assert=require('node:assert/strict'),fs=require('node:fs'),vm=require('node:vm');
const source=fs.readFileSync('web/inline-editor.js','utf8');
const context=vm.createContext({crypto:require('node:crypto').webcrypto});
vm.runInContext(source.slice(source.indexOf('function inlineSplitSpaces(d){'),source.indexOf("document.addEventListener('change',e=>{if(!e.target.matches('[data-slot-split]'))")),context);
const draft=()=>({words:[{id:'original',protected:false}],body:{words:[{form:'a b c',gloss:'A B C'}]},cells:[]});
test('split preserves alignment, original slot and fresh following identities',()=>{const d=draft();context.inlineSplitSpaces(d);assert.deepEqual(Array.from(d.body.words,w=>[w.form,w.gloss]),[['a','A'],['b','B'],['c','C']]);assert.equal(d.words[0].id,'original');assert.equal(new Set(d.words.map(w=>w.id)).size,3);});
test('blank gloss remains aligned; one unsplit gloss stays on the first word',()=>{for(const gloss of ['', 'meaning']){const d=draft();d.body.words[0].gloss=gloss;context.inlineSplitSpaces(d);assert.deepEqual(Array.from(d.body.words,w=>w.gloss),[gloss,'','']);}});
test('mismatched gloss rejects without partial changes',()=>{const d=draft();d.body.words[0].gloss='A B';assert.throws(()=>context.inlineSplitSpaces(d),/数量不一致/);assert.equal(d.words.length,1);assert.equal(d.body.words[0].form,'a b c');});
test('linked or annotated words require explicit handling',()=>{for(const kind of ['link','annotation']){const d=draft();if(kind==='link')d.words[0].protected=true;else d.cells=[{unit_id:'original',value:'note'}];assert.throws(()=>context.inlineSplitSpaces(d),/先处理/);assert.equal(d.words.length,1);}});
