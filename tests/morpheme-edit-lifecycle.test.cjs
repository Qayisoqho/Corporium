const test=require('node:test'),assert=require('node:assert/strict'),fs=require('node:fs'),vm=require('node:vm');
const lexicon=fs.readFileSync('web/lexicon.js','utf8'),morphemes=fs.readFileSync('web/morphemes.js','utf8'),undo=fs.readFileSync('web/undo.js','utf8');
function harness({existing=false,fail=false}={}){
 const nodes={},loads=[],calls=[];
 const node=id=>nodes[id]??={value:'',disabled:false,textContent:'',open:false};
 node('morpheme-gloss').parentElement={parentElement:{}};const editor=node('morpheme-editor');editor.open=true;
 for(const [id,value] of Object.entries({'morpheme-form-value':'-new','morpheme-gloss':'GEN','morpheme-type':'affix','morpheme-function':'inflection','morpheme-position':'suffix'}))node(id).value=value;
 const c={workspace:'dictionary',activeLanguage:'ordos',editing:existing?{id:'same',revision:1,language_id:'ordos'}:null,editorDirty:true,selection:'old',editor,$:node,dictSafe:f=>f,readGlossAddition:()=>({}),readTags:()=>[],readVariants:()=>[],readMorphemeSenses:()=>[],wsReadWritings:()=>[],edit(){},refreshUndo:async()=>calls.push('history'),originalApi:async(path,body)=>{calls.push({path,body});if(fail)throw Error('保存失败');return {id:existing?'same':'new'};},loadDictionary:async()=>{loads.push({open:editor.open,selection:c.selection,dirty:c.editorDirty});if(editor.open&&c.selection!==c.editing?.id)calls.push('discard-prompt');}};
 editor.close=()=>{editor.open=false;c.editing=null;c.editorDirty=false;calls.push('close');};
 c.prepareDictionaryLinkChanges=async request=>request;
 vm.createContext(c);
 vm.runInContext(lexicon.slice(lexicon.indexOf('const lexiconRefreshUndo='),lexicon.indexOf('const lexiconSwitchLanguage=')),c);
 vm.runInContext(undo.slice(undo.indexOf('api=async function(path,body)'),undo.indexOf('async function undoCommand(')),c);
 vm.runInContext(morphemes.match(/ async function changed\(\)[^\n]+/)[0],c);
 vm.runInContext(morphemes.match(/^ \$\('morpheme-new'\)\.onclick=[^\n]+/m)[0],c);
 const button={disabled:false};
 return {c,nodes,loads,calls,button,save:()=>node('morpheme-form').onsubmit({preventDefault(){},submitter:button})};
}
test('creating a morpheme skips the old selection refresh until the committed draft closes',async()=>{
 const h=harness();await h.save();assert.equal(h.calls.filter(c=>c==='discard-prompt').length,0);assert.equal(h.calls.filter(c=>c==='close').length,1);
 assert.deepEqual(h.loads,[{open:false,selection:'new',dirty:false}]);assert.equal(h.c.editorDirty,false);assert.equal(h.button.disabled,false);
 const sent=h.calls.find(c=>c.path==='morpheme-save');assert.equal(sent.body.form,'-new');assert.equal(sent.body.body.gloss,'GEN');assert.equal(sent.body.id,undefined);
});
test('editing an existing morpheme refreshes its saved detail only after closing the editor',async()=>{
 const h=harness({existing:true});await h.save();assert.deepEqual(h.loads,[{open:false,selection:'same',dirty:false}]);assert.equal(h.calls.find(c=>c.path==='morpheme-save').body.id,'same');
});
test('a rejected save retains the dirty draft and entered values, without changing selection or reloading',async()=>{
 const h=harness({fail:true});await h.save();assert.equal(h.c.editor.open,true);assert.equal(h.c.editorDirty,true);assert.equal(h.c.selection,'old');assert.equal(h.nodes['morpheme-form-value'].value,'-new');assert.equal(h.nodes['morpheme-gloss'].value,'GEN');assert.equal(h.nodes['morpheme-error'].textContent,'保存失败');assert.equal(h.loads.length,0);assert.equal(h.button.disabled,false);
});
test('the actual leave guard still requires confirmation for unsaved changes',async()=>{
 const h=harness();let prompts=0,accept=false;h.c.corporiumConfirm=async()=>{prompts++;return accept;};vm.runInContext(morphemes.match(/ async function leaveEditor\(\)[^\n]+/)[0],h.c);
 assert.equal(await h.c.leaveEditor(),false);assert.equal(h.c.editor.open,true);assert.equal(h.c.editorDirty,true);accept=true;assert.equal(await h.c.leaveEditor(),true);assert.equal(h.c.editor.open,false);assert.equal(prompts,2);
});
test('history refresh before the morpheme editor is mounted remains valid',async()=>{
 let reads=0;const c={workspace:'dictionary',$:id=>id==='lexeme-editor'?{open:false}:null,refreshUndo:async()=>{},loadDictionary:async()=>reads++};vm.createContext(c);vm.runInContext(lexicon.slice(lexicon.indexOf('const lexiconRefreshUndo='),lexicon.indexOf('const lexiconSwitchLanguage=')),c);await c.refreshUndo();assert.equal(reads,1);
});
