const test=require('node:test'),assert=require('node:assert/strict'),vm=require('node:vm'),fs=require('node:fs');
const source=fs.readFileSync('web/i18n.js','utf8');
function runtime(locale='zh-CN',blocked=false){
 const doc={documentElement:{dataset:{uiLanguage:locale}},cookie:''};
 const c={document:doc,location:{href:'http://corporium.local/'},URL,localStorage:{getItem(){if(blocked)throw Error('blocked');return null;},setItem(){if(blocked)throw Error('blocked');}},CorporiumMessages:{messages:{m:{zh:'共 ⟦0⟧ 条，名称：⟦1⟧',en:'Name: ⟦1⟧; count: ⟦0⟧'}},terms:{T:{zh:'指称',en:'deictic'}},phrases:{'保存':'Save'}}};
 vm.createContext(c);vm.runInContext(source,c);return c;
}
test('English formats authored text and preserves Chinese user data, symbols, empty values and markup parameters',()=>{
 const c=runtime('en'),i=c.CorporiumI18n,user='保存 话题 ⟦0⟧ <b>Q/A * a.</b>';
 assert.equal(i.f('m',[2,user]),`Name: ${user}; count: 2`);
 assert.equal(i.f('m',[0,'']), 'Name: ; count: 0');
 assert.equal(i.f('m',[null,undefined]),'Name: undefined; count: null');
 assert.equal(i.term('T','指称'),'deictic');assert.equal(i.term('unknown','用户标签'),'用户标签');
});
test('Chinese remains byte-for-byte equivalent and storage restrictions do not break startup',()=>{
 const c=runtime('zh-CN',true);assert.equal(c.CorporiumI18n.f('m',[2,'保存']),'共 2 条，名称：保存');
 assert.equal(c.document.documentElement.lang,'zh-CN');assert.equal(c.CorporiumI18n.valid('fr'),null);
});
test('lazy interpolation evaluates once and a missing catalog entry does not evaluate arguments before fallback',()=>{
 const c=runtime('en');c.calls=0;
 assert.equal(vm.runInContext("CorporiumI18n.f('m',()=>[++calls,'测试'])",c),'Name: 测试; count: 1');assert.equal(c.calls,1);
 assert.equal(vm.runInContext("CorporiumI18n.f('missing',()=>[++calls])??`fallback ${++calls}`",c),'fallback 2');assert.equal(c.calls,2);
});
test('plural agreement is decided before interpolation and never rewrites user text',()=>{
 const c=runtime('en');c.CorporiumMessages.messages.count={zh:'⟦0⟧ 句：⟦1⟧',en:'⟦0⟧ sentences: ⟦1⟧'};
 for(const n of [0,1,2])assert.equal(c.CorporiumI18n.f('count',[n,'1 sentences 用户']),`${n} ${n===1?'sentence':'sentences'}: 1 sentences 用户`);
});
test('reviewed terminology is contextual: IPA r differs from n, A is an agent, and TOP uses the approved correction',()=>{
 const c=runtime('en');c.CorporiumMessages=JSON.parse(fs.readFileSync('web/i18n-messages.json','utf8'));const i=c.CorporiumI18n;
 assert.equal(Object.keys(c.CorporiumMessages.terms).length,898);
 assert.match(i.ipa('r','龈鼻音'),/trill/i);assert.match(i.ipa('n','龈鼻音'),/nasal/i);
 assert.equal(i.reference({symbol:'A',description:'施事',category:'论元'}).description,'A argument');
 assert.equal(i.reference({symbol:'TOP',description:'话题',category:'信息结构'}).description,'Topic marker');
 assert.equal(i.reference({symbol:'DIST',description:'远指',category:'指称'}).category,'deictic');
 assert.equal(i.term('T0668','指称'),'deictic');
});
test('view adapters capture only the active workspace and retain values without translation',async()=>{
 const c=runtime('en'),i=c.CorporiumI18n;let restored;
 const adapter={capture:()=>({title:'保存',page:2}),restore:async value=>{restored=value;}};
 assert.equal(i.registerView('survey',adapter),adapter);i.registerView('analysis',{capture:()=>{throw Error('inactive');}});
 const saved=i.captureView('survey');assert.equal(saved.survey.title,'保存');await i.restoreView(saved);assert.equal(restored.page,2);
});
test('API locale header works with blocked storage and does not alter external requests or request bodies',async()=>{
 const calls=[],c=runtime('en',true);c.location.origin='http://corporium.local';c.Headers=Headers;
 c.fetch=async (...args)=>{calls.push(args);return 'ok';};vm.runInContext(source,c);
 const body='用户材料';await c.fetch('/api/save',{method:'POST',body,headers:{'Content-Type':'application/json'}});
 assert.equal(calls[0][1].headers.get('X-Corporium-UI-Language'),'en');assert.equal(calls[0][1].body,body);assert.equal(calls[0][1].method,'POST');
 await c.fetch('https://example.com/',{headers:{Test:'original'}});assert.deepEqual(calls[1][1],{headers:{Test:'original'}});
});
test('cached formatting matches every existing catalog message and preserves interpolation coercion order',()=>{
 const catalog=JSON.parse(fs.readFileSync('web/i18n-messages.json','utf8'));
 const singular={sentences:'sentence',examples:'example',items:'item',rows:'row',results:'result',characters:'character',words:'word',cells:'cell',tiers:'tier',groups:'group',backups:'backup',links:'link',entries:'entry',languages:'language',files:'file',intervals:'interval',seconds:'second',steps:'step',matches:'match',candidates:'candidate',definitions:'definition',occurrences:'occurrence',tokens:'token'};
 function previous(template,args,plurals){if(plurals)template=template.replace(/⟦(\d+)⟧ (sentences|examples|items|rows|results|characters|words|cells|tiers|groups|backups|links|entries|languages|files|intervals|seconds|steps|matches|candidates|definitions|occurrences|tokens)\b/gu,(all,i,noun)=>Number(args[Number(i)])===1?'⟦'+i+'⟧ '+singular[noun]:all);return template.replace(/⟦(\d+)⟧/gu,(_,i)=>String(args[Number(i)]));}
 for(const locale of ['zh-CN','en']){
  const c=runtime(locale);c.CorporiumMessages=catalog;const i=c.CorporiumI18n;
  for(const n of [0,1,2])for(const [id,row] of Object.entries(catalog.messages)){
   const args=Array.from({length:100},(_,k)=>k%3?n:'用户材料 ⟦0⟧ Q/A * <b>abc</b>');
   const expected=previous(locale==='en'?row.en:row.zh,args,locale==='en');
   assert.equal(i.f(id,args),expected,id);assert.equal(i.f(id,args),expected,id+' cached');
  }
  c.CorporiumMessages={messages:{m:{zh:'⟦1⟧ ⟦0⟧ ⟦0⟧',en:'⟦1⟧ ⟦0⟧ sentences ⟦0⟧'}}};
  const log=[],args=[{valueOf(){log.push('number');return 1;},toString(){log.push('text');return '材料';}},'Q/A'];
  const expected=previous(locale==='en'?c.CorporiumMessages.messages.m.en:c.CorporiumMessages.messages.m.zh,args,locale==='en'),order=log.slice();log.length=0;
  assert.equal(i.f('m',args),expected);assert.deepEqual(log,order);
 }
});
