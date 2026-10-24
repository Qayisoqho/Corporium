const test=require('node:test'),assert=require('node:assert/strict'),vm=require('node:vm'),fs=require('node:fs');
const source=fs.readFileSync(require.resolve('../web/timeline.js'),'utf8');

test('original context uses the saved sentence number after an automatic time save',async()=>{
 const stale={id:'interval',entry_id:'sentence',text_id:'text',position:2},fresh={...stale,position:24},events=[];
 const s={data:{intervals:[stale]},page:1,noDraft:async()=>{s.data.intervals=[fresh];},setWorkspace:async v=>events.push(v),clearFilters(){},loadTexts:async()=>{},window:{CorporiumDialogue:{showOriginal:v=>events.push(v)}},selectText:async v=>events.push(v),pageSize:()=>20,search:async()=>events.push(s.page),$:id=>({scrollIntoView:()=>events.push(id)})};
 vm.createContext(s);vm.runInContext(source.slice(source.indexOf('async function openOriginal(i)'),source.indexOf('async function editor(){')),s);
 await s.openOriginal(stale);assert.equal(s.page,2);assert.deepEqual(events,['corpus','text','text',2,'entry-sentence']);
});

test('offscreen selected sentence and independent examples retain their original targets',async()=>{
 let target='';const stale={id:'interval',entry_id:'sentence',text_id:'text',position:1};
 const s={data:{intervals:[],selected_interval:{...stale,position:42}},noDraft:async()=>{},setWorkspace:async()=>{},clearFilters(){},loadTexts:async()=>{},window:{CorporiumSurvey:{openExample:async id=>{target=id;}}},selectText:async()=>{},pageSize:()=>20,search:async()=>{},$:()=>null};
 vm.createContext(s);vm.runInContext(source.slice(source.indexOf('async function openOriginal(i)'),source.indexOf('async function editor(){')),s);
 await s.openOriginal(stale);assert.equal(s.page,3);
 s.data.selected_interval={...stale,entry_id:'independent:example'};await s.openOriginal(stale);assert.equal(target,'example');
});
