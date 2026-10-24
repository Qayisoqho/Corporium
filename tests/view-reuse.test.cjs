const test=require('node:test'),assert=require('node:assert/strict'),vm=require('node:vm'),fs=require('node:fs');
const source=fs.readFileSync('web/workspace-loading.js','utf8');
function setup(){const c={owner:'one',revision:'a'};vm.createContext(c);vm.runInContext(source.slice(0,source.indexOf('(()=>{'))+'\nthis.views=new CorporiumWorkspaceViews(()=>[owner,revision]);',c);return c;}
test('each workspace retains its completed view only for its own language and revision',async()=>{
 const c=setup(),v=c.views;for(const name of ['corpus','library','survey','timeline','homophones','analysis']){await v.run(name,async()=>{});assert.equal(v.current(name),true);}
 c.owner='two';assert.equal(v.current('corpus'),false);c.owner='one';assert.equal(v.current('corpus'),true);c.revision='b';assert.equal(v.current('corpus'),false);
});
test('a late render, invalidated read or language response cannot mark stale contents as current',async()=>{
 const c=setup(),v=c.views;let finish;const a=v.run('timeline',()=>new Promise(r=>finish=r));v.invalidateAll();finish();await a;assert.equal(v.current('timeline'),false);assert.equal(v.running.has('timeline'),false);
 let first;const old=v.run('corpus',()=>new Promise(r=>first=r));await v.run('corpus',async()=>{});first();await old;assert.equal(v.current('corpus'),true);
 let complete;const other=v.run('survey',()=>new Promise(r=>complete=r));c.owner='other';complete();await other;assert.equal(v.current('survey'),false);
});
test('only visible stale views refresh; errors and internally handled failures remain retryable',async()=>{
 const c=setup(),v=c.views;let active='corpus',calls=0;v.register('corpus',()=>active==='corpus',()=>v.run('corpus',async()=>{calls++;}));v.register('timeline',()=>active==='timeline',()=>v.run('timeline',async()=>{calls++;}));
 await v.refreshVisible();await v.refreshVisible();assert.equal(calls,1);c.revision='b';await v.refreshVisible();assert.equal(calls,2);
 await assert.rejects(v.run('timeline',async()=>{throw Error('offline');}));assert.equal(v.current('timeline'),false);assert.equal(v.running.has('timeline'),false);
 await v.run('timeline',async()=>false);assert.equal(v.current('timeline'),false);active='timeline';await v.refreshVisible();assert.equal(calls,3);
});
test('cached corpus activation skips data reloads and a changed revision refreshes its navigation too',async()=>{
 const c=setup();c.window={CorporiumViews:c.views};c.workspace='library';c.textReads=0;c.searches=0;c.setWorkspace=async name=>{c.workspace=name;};c.loadTexts=async()=>{c.textReads++;};c.search=async()=>{c.searches++;c.views.mark('corpus');};
 const line=fs.readFileSync('web/ui-tools.js','utf8').split('\n').find(s=>s.startsWith('const displayWorkspace='));vm.runInContext(line,c);
 c.views.mark('corpus');await c.setWorkspace('corpus');assert.equal(c.searches,0);c.revision='b';await c.setWorkspace('corpus');assert.equal(c.searches,1);assert.equal(c.textReads,1);await c.setWorkspace('corpus');assert.equal(c.searches,1);
});
test('survey navigation waits for autosave and a save error leaves the editor and workspace in place',async()=>{
 const c=setup();c.window={CorporiumViews:c.views};c.workspace='survey';c.parked=0;c.loaded=0;c.panel={};c.tab={setAttribute(){}};c.guard=fn=>fn;c.setWorkspace=async name=>{c.workspace=name;};c.parkEditor=()=>{c.parked++;};c.load=async()=>{c.loaded++;c.views.mark('survey');};c.flush=async()=>{if(c.fail)throw Error('not saved');};
 const line=fs.readFileSync('web/grammar-survey.js','utf8').split('\n').find(s=>s.startsWith('const oldWorkspace='));vm.runInContext(line.replace(/;tab\.onclick=.*$/,';'),c);
 c.views.mark('survey');c.fail=true;await assert.rejects(c.setWorkspace('library'));assert.equal(c.workspace,'survey');assert.equal(c.parked,0);
 c.fail=false;await c.setWorkspace('library');assert.equal(c.parked,1);await c.setWorkspace('survey');assert.equal(c.loaded,0);c.revision='b';await c.setWorkspace('survey');assert.equal(c.loaded,1);
});

test('changing analysis type refreshes a stale generated homophone table, but reuses an unchanged table',async()=>{
 const c=setup();c.window={CorporiumViews:c.views};c.activeLanguage='one';c.generated=true;c.nav={};c.safe=fn=>fn;c.choose=name=>{c.chosen=name;};let reads=0;
 c.run=()=>c.views.run('homophones',async()=>{reads++;});
 const line=fs.readFileSync('web/homophones.js','utf8').split('\n').find(s=>s.startsWith(' nav.onclick='));vm.runInContext(line,c);
 const event={target:{closest:()=>({dataset:{analysisType:'homophones'}})}};
 await c.nav.onclick(event);assert.equal(c.chosen,'homophones');assert.equal(reads,1);
 await c.nav.onclick(event);assert.equal(reads,1);c.revision='changed';await c.nav.onclick(event);assert.equal(reads,2);
 c.generated=false;c.views.invalidate('homophones');await c.nav.onclick(event);assert.equal(reads,2);
});
