const test=require('node:test'),assert=require('node:assert/strict'),fs=require('node:fs'),vm=require('node:vm');

test('a late single-sentence lookup cannot overwrite the group picker',async()=>{
 const source=fs.readFileSync('web/grammar-survey.js','utf8'),start=source.indexOf('let pickerRequest=0;'),end=source.indexOf("\n$('survey-picker-search').onclick=",start),nodes={};
 const node=id=>nodes[id]??={value:'',textContent:'',innerHTML:'',replaceChildren(){},querySelectorAll:()=>[]};
 let finish;const pending=new Promise(resolve=>finish=resolve);let grouped=false;
 const c={URLSearchParams,$:node,pickerPage:1,pickerNode:'question',state:{},topPagination(){},esc:s=>s,api:()=>pending};
 c.window=c;c.CorporiumExampleGroups={pickerActive:()=>grouped,pick:async()=>{node('survey-picker-results').innerHTML='group candidates';}};
 vm.createContext(c);vm.runInContext(source.slice(start,end),c);
 const first=c.picker();grouped=true;await c.picker();finish({items:[],page:1,pages:1});await first;
 assert.equal(node('survey-picker-results').innerHTML,'group candidates');
});

test('a delayed group editor read cannot open in another language or workspace',async()=>{
 const source=fs.readFileSync('web/example-groups.js','utf8'),start=source.indexOf('async function open('),end=source.indexOf("\n $('example-group-create')",start);
 for(const changed of ['activeLanguage','workspace']){
  let finish,started;const ready=new Promise(resolve=>started=resolve),pending=new Promise(resolve=>finish=resolve),opened=[];
  const c={URLSearchParams,editorRequest:0,activeLanguage:'one',workspace:'library',requireSaved(){},showEditor:g=>opened.push(g),request:()=>{started();return pending;}};
  c.window=c;c.corporiumFlushSurvey=async()=>{};vm.createContext(c);vm.runInContext(source.slice(start,end),c);
  const first=c.open('group','one');await ready;c[changed]='other';finish({id:'group'});await first;
  assert.deepEqual(opened,[]);
 }
});

test('group save distinguishes a failed write from a committed save whose refresh failed',async()=>{
 const source=fs.readFileSync('web/example-groups.js','utf8'),start=source.indexOf('async function saveEditor('),end=source.indexOf("\n $('example-group-form').onsubmit",start);
 for(const writeFails of [false,true]){
  const nodes={},messages=[],saved={id:'new-group'},original={id:null,language_id:'one',body:{},members:[]};let closes=0;
  const node=id=>nodes[id]??={disabled:false,inert:false,textContent:''};
  const c={busy:false,dirty:true,editor:original,selecting:true,chosen:new Map(),$:node,collect(){},selectedState(){},corporiumStatus:t=>messages.push(t),groupDialog:{querySelector:()=>node('form'),close:()=>closes++},request:async()=>{if(writeFails)throw Error('write refused');return saved;},refreshed:async()=>{throw Error('refresh offline');}};
  vm.createContext(c);vm.runInContext(source.slice(start,end),c);const result=await c.saveEditor();
  if(writeFails){assert.equal(result,null);assert.equal(c.editor,original);assert.equal(c.dirty,true);assert.equal(closes,0);assert.match(node('example-group-error').textContent,/write refused/);}
  else{assert.equal(result,saved);assert.equal(c.editor,null);assert.equal(c.dirty,false);assert.equal(closes,1);assert.match(messages[0],/已保存.*刷新失败/);assert.equal(node('example-group-error').textContent,'');}
 }
});
