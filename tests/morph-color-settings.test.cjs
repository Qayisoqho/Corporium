const test=require('node:test'),assert=require('node:assert/strict'),vm=require('node:vm'),fs=require('node:fs');
function setup(){const c={};vm.createContext(c);vm.runInContext(fs.readFileSync('web/morph-color-settings.js','utf8').split('(()=>{')[0],c);return c;}
test('palette defaults retain theme colors, and a master switch makes every role use IPA without changing shared gold',()=>{
 const c=setup(),p=c.normalizeMorphPalette(null),on=c.morphPaletteValues(p,'dawoid');assert.equal(Object.keys(on).length,8);assert.equal(on.affix,'var(--gold,var(--ink))');assert.equal(on.clitic,'var(--morph-clitic,var(--ink))');
 p.enabled=false;const off=c.morphPaletteValues(p,'dawoid');assert.ok(Object.values(off).every(v=>v==='var(--ipa,var(--ink))'));assert.ok(Object.keys(off).every(k=>!k.startsWith('--')));
});
test('existing palettes gain a source-only reduplication switch and independent colors for all skins',()=>{
 const c=setup(),p=c.normalizeMorphPalette({roles:{affix:false},colors:{docoid:{reduplication:'#9B4566'},night:{reduplication:'#D8A6BD'}}});
 assert.equal(p.roles.reduplication,true);assert.equal(p.roles.affix,false);
 for(const skin of ['docoid','dawoid','ivory','night','forest'])assert.equal(c.morphPaletteValues(p,skin).reduplication,p.colors[skin].reduplication||'var(--morph-reduplication,var(--ink))');
 p.roles.reduplication=false;assert.equal(c.morphPaletteValues(p,'docoid').reduplication,'var(--ipa,var(--ink))');assert.equal(p.colors.docoid.reduplication,'#9b4566');
 p.roles.reduplication=true;assert.equal(c.morphPaletteValues(p,'night').reduplication,'#d8a6bd');
});
test('role switches preserve custom colors and keep skin palettes independent',()=>{
 const c=setup(),p=c.normalizeMorphPalette({roles:{clitic:false},colors:{dawoid:{affix:'#F080A0',clitic:'#00aaff'},docoid:{affix:'#246810'}}});
 assert.equal(c.morphPaletteValues(p,'dawoid').affix,'#f080a0');assert.equal(c.morphPaletteValues(p,'docoid').affix,'#246810');assert.equal(c.morphPaletteValues(p,'dawoid').clitic,'var(--ipa,var(--ink))');assert.equal(p.colors.dawoid.clitic,'#00aaff');
 p.roles.clitic=true;assert.equal(c.morphPaletteValues(p,'dawoid').clitic,'#00aaff');assert.equal(c.morphPaletteValues(p,'forest').affix,'var(--gold,var(--ink))');
});
test('invalid persisted values and unknown fields cannot create arbitrary CSS',()=>{
 const c=setup();for(const bad of [false,[],null,0,'bad'])assert.equal(c.normalizeMorphPalette(bad).enabled,true);
 const p=c.normalizeMorphPalette({enabled:false,roles:{affix:false,infix:'false',unknown:false},colors:{dawoid:{base:'red; color:gold',affix:'url(x)',infix:'#123',clitic:'#12345678',circumfix:'#12abEF',unknown:'#ffffff'},unknown:{base:'#000000'}}});
 assert.equal(p.roles.affix,false);assert.equal(p.roles.infix,true);assert.deepEqual(JSON.parse(JSON.stringify(p.colors.dawoid)),{circumfix:'#12abef'});assert.ok(!Object.hasOwn(p.colors,'unknown'));
});
