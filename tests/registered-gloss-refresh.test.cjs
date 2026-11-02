const test=require('node:test'),assert=require('node:assert/strict'),fs=require('node:fs'),vm=require('node:vm');
test('free glosses recognize current definitions and new registrations in their own language without changing input',()=>{
 const languageList=[{id:'one',metadata:JSON.stringify({glossary:{PST:'Past'}})},{id:'two',metadata:'{}'}];
 const c=vm.createContext({esc:String,activeLanguage:'one',languageList});vm.runInContext(fs.readFileSync('web/display-tools.js','utf8').split('let briefMode')[0],c);require('./display-scripts-helpers.js')(c);
 const value='go.pst.direct';let html=c.richGloss(value,'one');assert.match(html,/>pst<\/span>/);assert.doesNotMatch(html,/>direct<\/span>/);
 languageList[0].metadata=JSON.stringify({glossary:{PST:'Past tense',DIRECT:'Direct evidence'}});
 html=c.richGloss(value,'one');assert.match(html,/title="Past tense"/);assert.match(html,/>direct<\/span>/);
 assert.doesNotMatch(c.richGloss(value,'two'),/grammar-label/);assert.equal(value,'go.pst.direct');
});
