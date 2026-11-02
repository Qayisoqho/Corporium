const test=require('node:test'),assert=require('node:assert/strict'),fs=require('node:fs'),vm=require('node:vm');
function setup(){const c=vm.createContext({esc:s=>String(s??'').replace(/[&<>"']/g,ch=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[ch])),layerStyle:()=>'',CorporiumI18n:{locale:'zh-CN',ui:(zh,en)=>c.CorporiumI18n.locale==='en'?en:zh}});require('./display-scripts-helpers.js')(c);vm.runInContext(fs.readFileSync('web/dictionary-layers.js','utf8'),c);return c;}
test('derived tiers preserve scripts, safely link to sources, and never emit editable cells',()=>{
 const c=setup(),layer={id:'layer',name:'Type',unit_id:'word',derived:true,segments:[{key:'0',values:['word#sup[h]'],refs:[{id:'entry',headword:'safe" <entry>'}],state:'value'}]};
 const html=c.renderDictionaryLayer(layer);assert.match(html,/<sup>h<\/sup>/);assert.match(html,/data-layer-open="entry"/);assert.match(html,/safe&amp;quot;|safe&quot;/);assert.doesNotMatch(html,/<input|<textarea|contenteditable|data-inline-layer/);
});
test('plain copy text uses locale-specific type labels and retains missing segment positions',()=>{
 const c=setup(),layer={derived:true,entry_type_labels:{affix:['词缀','Affix']},segments:[{values:[]},{values:['affix']}]};
 assert.equal(c.dictionaryLayerText(layer),'— - 词缀');c.CorporiumI18n.locale='en';assert.equal(c.dictionaryLayerText(layer),'— - Affix');
});
test('missing and stale values explain their state without inventing a dictionary target',()=>{
 const c=setup(),html=c.renderDictionaryLayer({id:'l',name:'Gloss',derived:true,segments:[{values:[],refs:[],state:'stale'}]});
 assert.match(html,/请核对词典关联/);assert.doesNotMatch(html,/data-layer-open=/);assert.match(html,/>—<\/span>/);
});
test('each displayed value points at a dictionary source that actually supplies it',()=>{
 const c=setup(),html=c.renderDictionaryLayer({id:'l',name:'Class',derived:true,segments:[{values:['N','V'],refs:[{id:'noun',headword:'noun entry',values:['N']},{id:'verb',headword:'verb entry',values:['V']}],state:'value'}]});
 assert.match(html,/data-layer-open="noun"[^>]*>N<\/button>/);assert.match(html,/data-layer-open="verb"[^>]*>V<\/button>/);
});
