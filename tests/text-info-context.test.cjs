const test=require('node:test'),assert=require('node:assert/strict'),vm=require('node:vm'),fs=require('node:fs');
test('metadata without a selected text hides and disables the docked save button; selecting a text restores it without replacing an existing draft',()=>{
 const source=fs.readFileSync('web/metadata.js','utf8'),button={hidden:false,disabled:false},c={texts:[],selected:'',info:{hidden:false},infoText:{id:'old'},infoDirty:true,$:()=>button};
 vm.createContext(c);vm.runInContext(source.slice(source.indexOf('function renderInfo(){'),source.indexOf('function folderStateKey()')),c);
 c.renderInfo();assert.equal(c.info.hidden,true);assert.equal(button.hidden,true);assert.equal(button.disabled,true);assert.equal(c.infoText,null);
 c.texts=[{id:'t'}];c.selected='t';c.infoText={id:'t',draft:'keep'};c.infoDirty=true;c.renderInfo();assert.equal(button.hidden,false);assert.equal(button.disabled,false);assert.equal(c.info.hidden,false);assert.equal(c.infoText.draft,'keep');assert.equal(c.infoDirty,true);
});
