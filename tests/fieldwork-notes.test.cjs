const test=require('node:test'),assert=require('node:assert/strict'),fs=require('node:fs'),vm=require('node:vm');
const source=fs.readFileSync(require.resolve('../web/fieldwork-notes.js'),'utf8');
function harness(write){const state={};vm.createContext(state);vm.runInContext(source.slice(source.indexOf('class NoteDraft{'),source.indexOf('const panel='))+'\nthis.Draft=NoteDraft;',state);let value='first';const statuses=[];const d=new state.Draft({id:'note',language_id:'lang-a',revision:1},()=>({body:[{text:value}],title:''}),write,(...args)=>statuses.push(args));return {d,statuses,change(v){value=v;d.changed();}};}

test('autosave serializes newer typing and uses the revision returned by the first save',async()=>{
 const writes=[];let release;const h=harness(async b=>{writes.push(b);if(writes.length===1)await new Promise(r=>release=r);return {...b,language_id:'lang-a',revision:b.revision+1};});
 h.change('first');const p=h.d.flush();h.change('second');const concurrent=h.d.flush();assert.equal(p,concurrent);release();await p;
 assert.deepEqual(writes.map(b=>[b.body[0].text,b.revision]),[['first',1],['second',2]]);assert.equal(h.d.row.revision,3);assert.equal(h.d.dirty,false);assert.equal(h.statuses.at(-1)[0],'已保存');
});
test('failed saves retain the complete draft and retry without advancing its revision',async()=>{
 let fail=true,writes=0;const h=harness(async b=>{writes++;if(fail)throw Error('离线');return {...b,revision:2};});h.change('不会丢失的笔记');await assert.rejects(h.d.flush(),/离线/);assert.equal(h.d.dirty,true);assert.equal(h.d.row.revision,1);assert.equal(h.statuses.at(-1)[1],true);
 fail=false;await h.d.flush();assert.equal(h.d.row.body[0].text,'不会丢失的笔记');assert.equal(h.d.dirty,false);await h.d.flush();assert.equal(writes,2);
});
test('IME composition is not committed midway and a later edit is not cleared by an older reply',async()=>{
 let release;const writes=[];const h=harness(async b=>{writes.push(b);if(writes.length===1)await new Promise(r=>release=r);return {...b,revision:b.revision+1};});
 h.change('拼音');h.d.composing=true;await assert.rejects(h.d.flush(),/完成正在输入/);assert.equal(writes.length,0);assert.equal(h.d.dirty,true);
 h.d.composing=false;const p=h.d.flush();h.change('汉字');release();await p;assert.equal(h.d.row.body[0].text,'汉字');assert.equal(writes.length,2);
});
test('saving a captured note keeps its owner even while external selection changes',async()=>{
 let currentLanguage='lang-a';const owners=[];const owner=currentLanguage;const h=harness(async b=>{owners.push(owner);return {...b,language_id:owner,revision:2};});h.change('原语言笔记');currentLanguage='lang-b';await h.d.flush();assert.equal(h.d.row.language_id,'lang-a');assert.deepEqual(owners,['lang-a']);
});
test('the shared survey editor escapes text and preserves rich flags and writing types',()=>{
 const s={window:{},esc:v=>String(v).replaceAll('&','&amp;').replaceAll('<','&lt;').replaceAll('>','&gt;').replaceAll('"','&quot;'),validFont:()=>true};vm.createContext(s);vm.runInContext(fs.readFileSync(require.resolve('../web/rich-text.js'),'utf8'),s);
 const html=s.window.CorporiumRichText.markup([{text:'<script>词形</script>',bold:true,italic:true,highlight:true,type_id:'ipa'}],[{id:'ipa',font:'IPAPANNEW'}]);assert.match(html,/&lt;script&gt;/);assert.doesNotMatch(html,/<script>/);assert.match(html,/<b><i><mark>/);assert.match(html,/data-writing-type="ipa"/);assert.match(html,/IPAPANNEW/);
});
test('a lost save response can be reconciled despite JSON property order, without accepting changed formatting',()=>{
 const s={};vm.createContext(s);vm.runInContext(source.match(/const sameRuns=[^\n]+/)[0]+'\nthis.compare=sameRuns;',s);
 assert.equal(s.compare([{text:'文字',bold:true,type_id:'ipa'}],[{bold:true,type_id:'ipa',text:'文字'}]),true);
 assert.equal(s.compare([{text:'文字',bold:true}],[{text:'文字'}]),false);
 assert.equal(s.compare([{text:'文字',type_id:'ipa'}],[{text:'文字',type_id:'other'}]),false);
});
test('autosave refreshes only the history controls without starting a dictionary reload',async()=>{
 let history=0;const s={clearTimeout(){},timer:null,draft:{flush:async()=>1},window:{corporiumRefreshUndoState:async()=>history++},refreshUndo:async()=>{throw Error('dictionary must not reload');},message:{textContent:''}};
 vm.createContext(s);vm.runInContext(source.slice(source.indexOf('async function flush(){'),source.indexOf('async function settle(){')),s);await s.flush();assert.equal(history,1);assert.equal(s.message.textContent,'');
});
test('background jobs wait for pending note saves before locking project writes',async()=>{
 const tasks=fs.readFileSync(require.resolve('../web/long-tasks.js'),'utf8'),calls=[];let release;
 const s={active:false,window:{corporiumFlushNotes:()=>new Promise(r=>release=r)},$:()=>({removeAttribute(){}}),progress:{showModal(){calls.push('modal');},close(){}},taskApi:async name=>{calls.push(name);return name==='task-start'?{id:'job'}:name.startsWith('task-status')?{state:'done',result:'ok'}:{};}};
 vm.createContext(s);vm.runInContext(tasks.slice(tasks.indexOf('async function execute('),tasks.indexOf(' function run(')),s);
 const result=s.execute('backup',{},'备份');await Promise.resolve();assert.deepEqual(calls,[]);assert.equal(s.active,false);release();assert.equal(await result,'ok');assert.deepEqual(calls.slice(0,2),['modal','task-start']);assert.equal(s.active,false);
});
