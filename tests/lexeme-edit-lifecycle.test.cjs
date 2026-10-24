const test=require('node:test');
const assert=require('node:assert/strict');
const fs=require('node:fs');
const vm=require('node:vm');

function editorState(){
 const app=fs.readFileSync('web/app.js','utf8'),lexicon=fs.readFileSync('web/lexicon.js','utf8');
 const outlets={notice:{textContent:''},'dictionary-notice':{textContent:''}};
 const editor=new EventTarget();editor.open=false;outlets['lexeme-editor']=editor;
 const context=vm.createContext({document:{getElementById:id=>outlets[id]},Event,editor});
 vm.runInContext(app.slice(app.indexOf("let corporiumStatusText="),app.indexOf('function guardDialogDiscard')),context);
 const start=lexicon.indexOf('function clearLexemeEditState()'),end=lexicon.indexOf("$('lexeme-editor').querySelector('.close')",start);
 vm.runInContext("let lexemeDirty=true,editingLexeme={id:'draft'};const $=id=>document.getElementById(id);"+lexicon.slice(start,end),context);
 return {context,editor,outlets,run:code=>vm.runInContext(code,context)};
}

test('closing a lexeme clears its dirty state and both copies of its editing hint',()=>{
 const s=editorState();s.run("corporiumStatus('请先保存或关闭正在编辑的词条。','lexeme-edit')");
 s.outlets['dictionary-notice'].textContent=s.outlets.notice.textContent;
 s.editor.dispatchEvent(new Event('close'));
 assert.equal(s.run('lexemeDirty'),false);assert.equal(s.run('editingLexeme'),null);
 assert.equal(s.outlets.notice.textContent,'');assert.equal(s.outlets['dictionary-notice'].textContent,'');
});

test('a queued close event cannot clear a newly opened lexeme draft',()=>{
 const s=editorState();s.editor.open=true;s.editor.dispatchEvent(new Event('close'));
 assert.equal(s.run('lexemeDirty'),true);assert.equal(s.run('editingLexeme.id'),'draft');
});

test('closing a lexeme preserves unrelated status messages and newer outlet errors',()=>{
 const s=editorState();s.run("corporiumStatus('已保存。')");s.editor.dispatchEvent(new Event('close'));
 assert.equal(s.outlets.notice.textContent,'已保存。');
 s.run("corporiumStatus('编辑保护提示','lexeme-edit')");s.outlets.notice.textContent='另一项操作的错误';
 s.editor.dispatchEvent(new Event('close'));assert.equal(s.outlets.notice.textContent,'另一项操作的错误');
});
