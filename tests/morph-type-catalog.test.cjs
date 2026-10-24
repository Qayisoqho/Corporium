const test=require('node:test'),assert=require('node:assert/strict'),fs=require('node:fs'),vm=require('node:vm');
test('dictionary color roles have entry types while reduplication remains an independent sentence relation',()=>{
 const source=fs.readFileSync('web/morphology.js','utf8'),types=vm.runInNewContext('('+source.match(/const morphEntryTypes=(.*);/)[1]+')'),morphemes=vm.runInNewContext('('+source.match(/const morphemeEntryTypes=(.*);/)[1]+')');
 const c=vm.createContext({});vm.runInContext(fs.readFileSync('web/morph-color-settings.js','utf8').split('(()=>{')[0],c);
 const roles=vm.runInContext('Object.keys(morphPaletteRoles)',c);
 for(const role of roles)assert.ok(role==='base'||role==='reduplication'||types[role]||morphemes[role],role+' has no selectable entry type');
 assert.ok(roles.includes('reduplication'));assert.equal(types.reduplication,undefined);assert.equal(morphemes.reduplication,undefined);
 assert.equal(types.morpheme,undefined);assert.equal(morphemes.affix,'词缀');assert.equal(types.clitic,'附着成分');assert.equal(types.connector,'连接成分');
});
