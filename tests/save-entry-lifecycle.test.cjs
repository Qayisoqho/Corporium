const test=require('node:test'),assert=require('node:assert/strict'),fs=require('node:fs'),vm=require('node:vm');
const read=name=>fs.readFileSync('web/'+name+'.js','utf8');
const lexicon=read('lexicon'),undo=read('undo'),inline=read('inline-editor');
function history(c){
 vm.runInContext(lexicon.slice(lexicon.indexOf('const lexiconRefreshUndo='),lexicon.indexOf('const lexiconSwitchLanguage=')),c);
 vm.runInContext(undo.slice(undo.indexOf('api=async function(path,body)'),undo.indexOf('async function undoCommand(')),c);
}
test('a text save can keep its view only while the active language and both revisions match',async()=>{
 const accepted=[];
 let state,resolve;
 const c=vm.createContext({window:{corporiumWorkspaceRevision:'base'},activeLanguage:'ordos',
  originalApi:()=>new Promise(done=>{resolve=done;}),renderUndoState:s=>accepted.push(s.workspace_revision)});
 const start=undo.indexOf('window.corporiumRefreshSavedHistory=');
 vm.runInContext(undo.slice(start,undo.indexOf('api=async function(path,body)',start)),c);
 const update={base:'base',current:'committed'};
 state=c.window.corporiumRefreshSavedHistory(update);resolve({workspace_revision:'other-write'});
 assert.equal(await state,false);
 state=c.window.corporiumRefreshSavedHistory(update);c.activeLanguage='other';resolve({workspace_revision:'committed'});
 assert.equal(await state,false);
 c.activeLanguage='ordos';state=c.window.corporiumRefreshSavedHistory(update);resolve({workspace_revision:'committed'});
 assert.equal(await state,true);assert.deepEqual(accepted,['committed']);
});
function lexeme({existing=false,quick=false,fail=false}={}){
 const nodes={},calls=[],sent=[],node=id=>nodes[id]??={value:'',children:[],open:false,textContent:'',querySelector:()=>null};
 node('lexeme-editor').open=true;node('lexeme-quick-editor').open=quick;node('lexeme-language').value='ordos';node('lexeme-headword').value='new';
 const c=vm.createContext({$ :node,workspace:'dictionary',activeLanguage:'ordos',dictionaryPage:1,CSS:{escape:s=>s},createdDictionaryPage:async()=>4,revealCreatedRecord:async()=>{},revealCreatedDictionaryItem:async()=>{},captureLexemeView:()=>null,editingLexeme:existing?{id:'same',revision:2,headword:'new',body:{}}:null,lexemeDirty:true,dictionarySelection:'old',URLSearchParams,
  waitForMorphChoices:async()=>{},readMorphEntry:()=>({}),readMorphForm:row=>row.fields,readTags:()=>[],pruneNewLexemeRows:()=>{},prepareMorphemeSave:async()=>({}),prepareDictionaryLinkChanges:async request=>request,refreshUndo:async()=>calls.push('history'),
  originalApi:async(path,body)=>{if(path.startsWith('homonym-preview'))return {peers:[],token:'confirmed'};calls.push(path);sent.push(body);if(fail)throw Error('保存失败');return {id:existing?'same':'new'};},
  loadDictionary:async()=>{calls.push('reload');assert.equal(node('lexeme-editor').open,false,'a view refresh must not navigate away from an open lexeme draft');},
  setWorkspace:async()=>{assert.equal(c.lexemeDirty,false);assert.equal(node('lexeme-editor').open,false);calls.push('workspace');},
  corporiumConfirm:async()=>{throw Error('unexpected discard');}});
 node('lexeme-editor').close=()=>{calls.push('close');node('lexeme-editor').open=false;node('lexeme-quick-editor').open=false;};
 history(c);vm.runInContext(lexicon.slice(lexicon.indexOf("$('lexeme-form').onsubmit="),lexicon.indexOf("makeDialog('word-link-dialog'")),c);
 return {c,calls,nodes,sent,save:()=>node('lexeme-form').onsubmit({preventDefault(){}})};
}
for(const existing of [false,true])for(const quick of [false,true])test(`${existing?'existing':'new'} lexeme ${quick?'quick':'full'} save does not navigate while dirty`,async()=>{
 const h=lexeme({existing,quick});await h.save();assert.equal(h.nodes['lexeme-error']?.textContent||'','');assert.deepEqual(h.calls,['lexeme-save','history','close',existing?'workspace':'reload']);if(!existing)assert.equal(h.c.dictionaryPage,4);assert.equal(h.c.dictionarySelection,existing?'same':'new');
});
test('failed lexeme writes preserve both the full and quick editor and draft',async()=>{
 for(const quick of [false,true]){const h=lexeme({quick,fail:true});await h.save();assert.equal(h.c.lexemeDirty,true);assert.equal(h.nodes['lexeme-editor'].open,true);assert.equal(h.nodes['lexeme-quick-editor'].open,quick);assert.equal(h.nodes['lexeme-headword'].value,'new');assert.equal(h.nodes['lexeme-error'].textContent,'保存失败');assert.equal(h.nodes['save-lexeme'].disabled,false);assert.deepEqual(h.calls,['lexeme-save']);}
});
test('quick base spelling save preserves every hidden variant ID and its own form in the normal save payload',async()=>{
 const h=lexeme({existing:true,quick:true});h.nodes['lexeme-headword'].value='-na';
 h.c.$('lexeme-variants').children=['first','second'].map(id=>({dataset:{id},fields:{pronunciation:'ne',conditions:id},querySelector:selector=>({value:selector==='.variant-form'?'-ne':id})}));
 await h.save();assert.equal(h.sent.length,1);const payload=h.sent[0];
 assert.equal(payload.id,'same');assert.equal(payload.revision,2);assert.equal(payload.headword,'-na');
 assert.deepEqual(JSON.parse(JSON.stringify(payload.body.variants)).map(v=>[v.id,v.form,v.pronunciation,v.conditions]),[['first','-ne','ne','first'],['second','-ne','ne','second']]);
 assert.equal(h.nodes['lexeme-error']?.textContent||'','');assert.deepEqual(h.calls,['lexeme-save','history','close','workspace']);
});

test('lexeme save waits for selected reference hydration and preserves the draft on a failed load',async()=>{
 const h=lexeme({existing:true});let resolve;
 h.c.waitForMorphChoices=()=>new Promise(r=>resolve=r);
 const saving=h.save();await Promise.resolve();assert.equal(h.sent.length,0);assert.equal(h.nodes['save-lexeme'].disabled,true);
 resolve();await saving;assert.equal(h.sent.length,1);
 const failed=lexeme({quick:true});failed.c.waitForMorphChoices=async()=>{throw Error('reference unavailable');};
 await failed.save();assert.equal(failed.sent.length,0);assert.equal(failed.c.lexemeDirty,true);
 assert.equal(failed.nodes['lexeme-editor'].open,true);assert.equal(failed.nodes['lexeme-quick-editor'].open,true);
 assert.equal(failed.nodes['lexeme-error'].textContent,'reference unavailable');
});
function inlineSave({kind='corpus',workspace='corpus',isNew=false,fail=false}={}){
 const calls=[],sent=[],listeners={},drafts=new Map(),key='draft';
 const d={kind,id:'entry',isNew,dirty:true,owner_language:'ordos',body:{ipa:'a',words:[{form:'a',gloss:'A'}]},words:[{id:'slot'}],layers:[],cells:[],host:{remove(){calls.push('remove');}},onSaved:async()=>{assert.equal(drafts.size,0);calls.push('saved-callback');}};drafts.set(key,d);
 const card={dataset:{exampleKey:key},append(){throw Error('unexpected outer error');}},button={closest:()=>card,hasAttribute:a=>a==='data-inline-save'};
 const c=vm.createContext({inlineDrafts:drafts,inlineOpening:new Map(),workspace,window:{corporiumRefreshUndoState:async()=>{assert.equal(drafts.size,0);calls.push('history');}},document:{addEventListener:(type,fn)=>listeners[type]=fn,querySelectorAll:()=>[]},inlineSlotEmpty:(_,i)=>!d.body.words[i].form&&!d.body.words[i].gloss&&!d.words[i].protected,repaintInline:()=>calls.push('paint'),
  originalApi:async(path,body)=>{assert.equal(d.saving,true);assert.equal(drafts.size,1);sent.push(body);calls.push(path);if(fail)throw Error('保存失败');return {id:'saved'};},
  api:()=>{throw Error('save must bypass premature workspace refresh');},
  refreshUndo:async()=>{assert.equal(drafts.size,0);calls.push('history');},loadTexts:async()=>calls.push('texts'),refreshExampleViews:async()=>{assert.equal(drafts.size,0);calls.push('views');}});
 const start=inline.indexOf("document.addEventListener('click',async e=>{"),end=inline.indexOf("window.addEventListener('beforeunload'",start);
 vm.runInContext(inline.slice(inline.indexOf('function clearInlineEditView('),inline.indexOf('// Cached panels can contain')),c);
 vm.runInContext(inline.slice(start,end),c);
 return {d,drafts,calls,sent,save:()=>listeners.click({target:{closest:()=>button},preventDefault(){}})};
}
for(const workspace of ['corpus','library','dictionary','survey','timeline'])for(const isNew of [false,true])test(`${workspace} ${isNew?'new':'existing'} inline sentence ends draft before callbacks and refresh`,async()=>{
 const h=inlineSave({workspace,isNew,kind:workspace==='library'?'independent':'corpus'});await h.save();assert.equal(h.drafts.size,0);assert.deepEqual(h.calls,['paint',isNew?'sentence-create':'inline-save','saved-callback','remove','history','views']);
});
test('failed inline sentence save keeps dirty draft available without navigation or refresh',async()=>{
 const h=inlineSave({fail:true});await h.save();assert.equal(h.drafts.size,1);assert.equal(h.d.dirty,true);assert.equal(h.d.saving,false);assert.equal(h.d.error,'保存失败');assert.deepEqual(h.calls,['paint','inline-save','paint']);
});
for(const fail of [false,true])test(`cleared protected and unprotected pairs are sent for atomic cleanup${fail?' and retained if saving fails':''}`,async()=>{
 const h=inlineSave({fail});h.d.body.words=[{form:'',gloss:''},{form:'a',gloss:'A'},{form:'',gloss:''}];h.d.words=[{id:'linked',protected:true},{id:'kept'},{id:'cleared'}];
 await h.save();assert.equal(h.sent.length,1);assert.deepEqual(Array.from(h.sent[0].slot_ids),['linked','kept','cleared']);assert.equal(h.sent[0].body.words.length,3);
 if(fail){assert.equal(h.drafts.size,1);assert.equal(h.d.words.length,3);assert.equal(h.d.error,'保存失败');}
});
function loadStandaloneSubmit(context){
 const source=read('dictionary-manager');
 vm.runInContext(source.slice(source.indexOf('const standaloneSourceFields'),source.indexOf('let writingTypes=')),context);
 vm.runInContext(source.slice(source.indexOf("$('standalone-form').onsubmit="),source.indexOf('async function renderStandalone')),context);
}
for(const workspace of ['dictionary','library'])test(`${workspace} independent Tab editor save closes directly without discard`,async()=>{
 const nodes={},calls=[],node=id=>nodes[id]??={value:'',children:[],open:false,textContent:''};node('standalone-editor').open=true;
 const c=vm.createContext({window:{corporiumSentenceInspector:{afterExampleSave:async source=>{assert.equal(source.kind,'independent');assert.equal(source.id,'example');calls.push('inspector');}}},$:node,workspace,standaloneCommit:null,standaloneSourceSnapshot:null,standaloneEditing:{id:'example',revision:1},standaloneLexeme:{id:'lexeme',language_id:'ordos'},standaloneDirty:true,
  CorporiumPairs:{parse:()=>[{form:'a',gloss:'A'}]},originalApi:async()=>{calls.push('write');return {id:'example'};},refreshUndo:async()=>{},loadDictionary:async()=>{},
  showLexeme:async()=>{assert.equal(c.standaloneDirty,false);assert.equal(node('standalone-editor').open,false);calls.push('view');},refreshExampleViews:async()=>{assert.equal(c.standaloneDirty,false);assert.equal(node('standalone-editor').open,false);calls.push('view');},
  document:{dispatchEvent(){calls.push('event');}},CustomEvent:class{}});
 node('standalone-editor').close=()=>{calls.push('close');node('standalone-editor').open=false;};
 history(c);loadStandaloneSubmit(c);
 await node('standalone-form').onsubmit({preventDefault(){}});assert.equal(node('standalone-error').textContent,'');assert.deepEqual(calls,['write','close','view','inspector','event']);assert.equal(node('standalone-save').disabled,false);
});
test('rejected independent Tab save retains values and dirty protection without closing or refreshing',async()=>{
 const nodes={},node=id=>nodes[id]??={value:'draft',children:[],open:true,textContent:''};
 const c=vm.createContext({window:{},$:node,standaloneCommit:null,standaloneSourceSnapshot:null,standaloneEditing:{id:'example',revision:1},standaloneLexeme:{language_id:'ordos'},standaloneDirty:true,
  CorporiumPairs:{parse:()=>[{form:'a',gloss:'A'}]},api:async()=>{throw Error('版本冲突');}});
 node('standalone-editor').close=()=>assert.fail('a failed save must not close');
 loadStandaloneSubmit(c);
 await node('standalone-form').onsubmit({preventDefault(){}});assert.equal(c.standaloneDirty,true);assert.equal(node('standalone-translation').value,'draft');assert.equal(node('standalone-error').textContent,'版本冲突');assert.equal(node('standalone-save').disabled,false);
});
test('changing only an independent example association sends identities and skips the source parser',async()=>{
 const nodes={},node=id=>nodes[id]??={value:'draft',children:[],textContent:''};
 node('standalone-targets').children=[{dataset:{targetIndex:'2'},querySelector:key=>({value:key==='.target-lexeme'?'target':''})}];
 node('standalone-editor').close=()=>{};
 const sent=[];
 const c=vm.createContext({window:{},$:node,workspace:'library',standaloneCommit:null,standaloneSourceSnapshot:Array(7).fill('draft'),
  standaloneEditing:{id:'example',revision:3},standaloneLexeme:{language_id:'ordos'},standaloneDirty:true,readFeatures:()=>[],
  CorporiumPairs:{parse:()=>assert.fail('association-only save parsed the sentence')},refreshExampleViews:async()=>{},
  api:async(path,body)=>{sent.push([path,JSON.parse(JSON.stringify(body))]);return {};},document:{dispatchEvent(){}},CustomEvent:class{}});
 loadStandaloneSubmit(c);
 await node('standalone-form').onsubmit({preventDefault(){}});
 assert.equal(node('standalone-error').textContent,'');
 assert.deepEqual(sent,[['example-links-save',{id:'example',revision:3,_language:'ordos',
  targets:[{lexeme_id:'target',usage_id:'',sense_id:'',form_id:'',features:[],index:2}]}]]);
});
for(const fail of [false,true])test(`corpus Tab save ${fail?'retains the editor on failure':'closes directly after success'}`,async()=>{
 const nodes={},calls=[],node=id=>nodes[id]??={open:true,textContent:''};node('editor').close=()=>{calls.push('close');node('editor').open=false;};
 const c=vm.createContext({window:{},$:node,current:{id:'entry',revision:2},readEditor:()=>({translation:'draft'}),api:async(path,body)=>{assert.equal(path,'save');assert.equal(body.translation,'draft');calls.push('write');if(fail)throw Error('保存失败');return {};},search:async()=>{assert.equal(node('editor').open,false);calls.push('refresh');},corporiumStatus:()=>calls.push('status')});
 vm.runInContext(read('app').split('\n').find(line=>line.startsWith("$('save').onclick=")),c);await node('save').onclick();
 assert.deepEqual(calls,fail?['write']:['write','close','refresh','status']);assert.equal(node('editor').open,fail);assert.equal(node('save').disabled,false);if(fail)assert.equal(node('edit-error').textContent,'保存失败');
});
