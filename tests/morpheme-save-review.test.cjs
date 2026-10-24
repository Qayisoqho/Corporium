const test=require('node:test'),assert=require('node:assert/strict'),vm=require('node:vm'),fs=require('node:fs');
const source=fs.readFileSync('web/morphemes.js','utf8').split('// Reading cards')[0];

function review(values,{cancel=false,invalid=false}={}){
 const choices=values.map((value,n)=>({value,dataset:{choice:String(n)},reportValidity:()=>!invalid}));
 const keyboard={value:'vowel',dataset:{},reportValidity:()=>true};
 const buttons={'[data-confirm]':{},'[data-cancel]':{}};
 const dialog={closed:false,removed:false,querySelector:s=>buttons[s],querySelectorAll:s=>s==='select'?choices.concat(keyboard):s==='select[data-choice]'?choices:[],showModal(){queueMicrotask(()=>cancel?buttons['[data-cancel]'].onclick():buttons['[data-confirm]'].onclick());},close(){this.closed=true;},remove(){this.removed=true;}};
 const body={word_structure:{analyses:[]}},items=values.map((_,n)=>({analysis_id:'a',component_id:'c'+n,form:'ma',component:{},peers:[{id:'existing'}],manual:false}));
 const c={document:{querySelectorAll:()=>[],createElement:()=>dialog,body:{append(){}}},wsRead:()=>body.word_structure,api:async()=>({items,token:'preview-token'}),esc:String,richGloss:String,wsRegistryLabel:()=> 'ma'};
 vm.createContext(c);vm.runInContext(source,c);
 return {dialog,result:c.prepareMorphemeSave(body,'word','ordos')};
}

test('homonym confirmation ignores the floating IPA keyboard select and saves independent and existing identities',async()=>{
 const {dialog,result}=review(['@new','existing']);
 const value=JSON.parse(JSON.stringify(await result));
 assert.deepEqual(value,{morpheme_confirmation:'preview-token',morpheme_choices:[{analysis_id:'a',component_id:'c0',morpheme_id:null},{analysis_id:'a',component_id:'c1',morpheme_id:'existing'}],morpheme_assignments:[]});
 assert.equal(dialog.closed,true);assert.equal(dialog.removed,true);
});

test('returning from homonym confirmation keeps the edit draft and cleans up the dialog',async()=>{
 const {dialog,result}=review(['@new'],{cancel:true});assert.equal(await result,null);assert.equal(dialog.closed,true);assert.equal(dialog.removed,true);
});
