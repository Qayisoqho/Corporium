const test=require('node:test'),assert=require('node:assert/strict'),fs=require('node:fs'),vm=require('node:vm');
test('full analysis exports retain run and frozen selection and offer the staged JSON file',async()=>{
 const source=fs.readFileSync('web/analysis-workspace.js','utf8');
 const handler=source.split("$('analysis-export').onclick=safeAnalysis(")[1].split('\n')[0].trim().replace(/\);$/,'');
 for(const frozen of [true,false]){
  const calls=[],c={runId:'selected-result',frozen,Date,api(){throw Error('full JSON response should not cross the browser');},download(){throw Error('full browser serialization should not be needed');},window:{async corporiumRunTask(kind,b,title){calls.push({kind,b,title});return {token:'staged',size:123};},corporiumOfferTaskFile(data,name,kind){calls.push({data,name,kind});}}};
  vm.createContext(c);await vm.runInContext('('+handler+')()',c);
  assert.equal(calls[0].kind,'analysis-export');assert.equal(calls[0].b.id,'selected-result');assert.equal(calls[0].b.snapshot,String(frozen));
  assert.equal(calls[1].data.token,'staged');assert.equal(calls[1].kind,'analysis-json');assert.match(calls[1].name,/^Corporium-analysis-\d{4}-\d{2}-\d{2}\.json$/);
 }
});
