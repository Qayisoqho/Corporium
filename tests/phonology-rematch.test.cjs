const test=require('node:test'),assert=require('node:assert/strict'),vm=require('node:vm'),fs=require('node:fs');
const source=fs.readFileSync(require.resolve('../web/homophone-phonology.js'),'utf8');

test('rematched unique rows offer bulk checkboxes while ambiguous and temporary rows do not',()=>{
 const start=source.indexOf('data.pending.map(g=>{')+'data.pending.map(g=>{'.length,end=source.indexOf("}).join('')||",start);
 const s={entries:[],data:{writing_types:[]},esc:String,choiceLabel:()=>'',item:()=>''};vm.createContext(s);
 vm.runInContext('function row(g){'+source.slice(start,end)+'}',s);
 const g={reading:'ma55',classification:{state:'candidate',reason:'按当前音系清单重新匹配，结果唯一，可批量确认'},items:[{provisional:false}]};
 assert.match(s.row(g),/data-hp-unique="ma55"/);
 for(const state of ['ambiguous','stale','unmatched'])assert.doesNotMatch(s.row({...g,classification:{state}}),/data-hp-unique=/);
 assert.doesNotMatch(s.row({...g,items:[{provisional:true}]}),/data-hp-unique=/);
});

test('manual review keeps a previous explicit choice available for ambiguous rematches',()=>{
 const nodes={},s={editingReading:'',editingLanguage:null,activeLanguage:'ordos',axes:['initials','finals','tones'],names:['声母','韵母','声调'],esc:String,entries:[{reading:'ma55',classification:{choice:null,previous_choice:{initials:'m',finals:'a',tones:'55'},candidates:[],reason:'存在多种划分'}}],config:{initials:[{id:'m',label:'m'}],finals:[{id:'a',label:'a'}],tones:[{id:'55',label:'55'}]},$:id=>nodes[id]??={showModal(){}}};
 vm.createContext(s);vm.runInContext(source.match(/ function classify[^\n]+/)[0],s);s.classify('ma55');
 for(const id of ['m','a','55'])assert.ok(nodes['hp-choice'].innerHTML.includes('value="'+id+'" selected'));
});

test('batch confirmation uses the current token and includes checked rematched readings',async()=>{
 const calls=[],s={config:{token:'new-inventory-token'},panel:{querySelectorAll:()=>[{dataset:{hpUnique:'ma55'}}]},corporiumConfirm:async text=>{assert.match(text,/重新匹配/);return true;},api:async(path,body)=>calls.push({path,body}),loadLanguages:async()=>{},rerun:async()=>{}};
 vm.createContext(s);vm.runInContext(source.match(/ async function bulk[^\n]+/)[0],s);await s.bulk(false);await s.bulk(true);
 assert.equal(calls.length,2);
 for(const {body} of calls){assert.equal(body.action,'confirm_unique');assert.equal(body.token,'new-inventory-token');assert.deepEqual(Array.from(body.readings),['ma55']);}
 assert.equal(calls[0].body.all,false);assert.equal(calls[1].body.all,true);
});
