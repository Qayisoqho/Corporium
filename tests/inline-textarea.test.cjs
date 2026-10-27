const test=require('node:test'),assert=require('node:assert/strict'),vm=require('node:vm'),fs=require('node:fs');
const source=fs.readFileSync('web/inline-editor.js','utf8');
const context=vm.createContext({});
vm.runInContext(source.slice(source.indexOf('function fitInlineTextareas('),source.indexOf("document.addEventListener('input',e=>{if(e.target.matches('.editable-example textarea'))")),context);
test('multiple visible textareas resize together and hidden or detached fields are untouched',()=>{
 const events=[];
 function field(id,height,visible=true,connected=true){return {isConnected:connected,getClientRects(){events.push('visible '+id);return visible?[{}]:[];},get scrollHeight(){events.push('measure '+id);return height;},style:{set height(value){events.push('height '+id+' '+value);}}};}
 const a=field('a',30),b=field('b',80),hidden=field('hidden',90,false),removed=field('removed',100,true,false);
 context.fitInlineTextareas([a,b,hidden,removed]);
 assert.deepEqual(events,['visible a','visible b','visible hidden','height a auto','height b auto','measure a','measure b','height a 32px','height b 82px']);
});
test('textarea input can shrink as well as grow without touching text or the caret',()=>{
 const field={isConnected:true,value:'用户内容 Q/A',selectionStart:4,selectionEnd:4,style:{},getClientRects(){return [{}];},scrollHeight:100};
 context.fitInlineTextarea(field);assert.equal(field.style.height,'102px');field.scrollHeight=22;context.fitInlineTextarea(field);
 assert.equal(field.style.height,'24px');assert.equal(field.value,'用户内容 Q/A');assert.equal(field.selectionStart,4);assert.equal(field.selectionEnd,4);
});
