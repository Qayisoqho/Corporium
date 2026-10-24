const {test}=require('node:test'),assert=require('node:assert/strict'),fs=require('node:fs'),vm=require('node:vm');
const source=fs.readFileSync('web/survey-search.js','utf8');
const escape=s=>String(s).replaceAll('&','&amp;').replaceAll('<','&lt;').replaceAll('>','&gt;').replaceAll('"','&quot;');
test('search highlight offsets preserve combining IPA, rich-run boundaries, emoji and whitespace',()=>{
 const c={Intl,esc:escape};vm.runInNewContext(source.slice(0,source.indexOf('function createSurveySearch')),c);
 const ranges=(text,q)=>JSON.parse(JSON.stringify(c.surveyTextRanges(text,q)));
 assert.deepEqual(ranges('🙂 e\u0301 É','é'),[[3,5],[6,7]]);
 assert.deepEqual(ranges('不\n   自然','不 自然'),[[0,7]]);
 assert.deepEqual(ranges('否定否定','否定'),[[0,2],[2,4]]);
 assert.deepEqual(ranges('ΟΣ','ος'),[[0,2]]);
 assert.equal(c.surveySnippet('<img>否定','否定'),'&lt;img&gt;<mark>否定</mark>');
});
function setup(){
 const elements={},calls=[],place={selection:'before',expanded:['parent']};let fail=false,reply=null;
 const item={node_id:'node',evidence_id:'evidence',kind:'independent',path:['上层','问题'],fields:[{field:'local_notes',label:'本处研究笔记',snippet:'否定'}]};
 const node=()=>({style:{setProperty(){}},classList:{toggle(){},add(){},remove(){}},hidden:false,disabled:false,innerHTML:'',value:'',textContent:'',scrollTop:50,getBoundingClientRect:()=>({height:60}),querySelectorAll:()=>[],setAttribute(){},contains(){return true;},getClientRects:()=>[{}],closest:()=>null,scrollIntoView(){calls.push('scroll');}});
 for(const id of ['survey-navigation','survey-tree','survey-search-query','survey-search-clear','survey-search-scope'])elements[id]=node();elements['survey-search-scope'].value='all';elements['survey-navigation'].prepend=(form,status,results)=>Object.assign(elements,{'survey-search':form,'survey-search-status':status,'survey-search-results':results});
 const adapter={async prepare(){calls.push('save');if(fail)throw Error('保存失败');},capture(){calls.push('capture');return place;},async restore(p){assert.equal(p,place);calls.push('restore');},async navigate(target){calls.push(['navigate',target.page]);return [node()];}};
 const c={activeLanguage:'ordos',$:id=>elements[id],esc:escape,Intl,URLSearchParams,ResizeObserver:class{observe(){}},window:{},document:{createElement:()=>node(),querySelectorAll:()=>[]},api:async path=>{calls.push(path);if(reply)return reply(path);return path.startsWith('survey-locate')?{node_id:'node',evidence_id:'evidence',page:3,field:'local_notes',matched:false}:{items:[item],nodes:1,total:1,page:1,pages:1};}};
 vm.createContext(c);vm.runInContext(source,c);const controller=c.createSurveySearch(adapter);elements['survey-search-query'].value='否定';
 return {c,calls,elements,controller,adapter,fail:value=>fail=value,reply:fn=>reply=fn,submit:()=>elements['survey-search'].onsubmit({preventDefault(){}}),clear:()=>elements['survey-search-clear'].onclick(),item};
}
test('search saves before reading, preserves results after stable-ID navigation, and restores outline on clear',async()=>{
 const s=setup();await s.submit();assert.deepEqual(s.calls.slice(0,2),['save','capture']);assert.ok(s.calls[2].startsWith('survey-search?'));assert.equal(s.elements['survey-tree'].hidden,true);
 const hit={dataset:{surveyHit:'0',hitField:'local_notes'}};await s.elements['survey-search-results'].onclick({target:{closest:selector=>selector==='[data-survey-hit]'?hit:null}});
 assert.ok(s.calls.some(call=>Array.isArray(call)&&call[0]==='navigate'&&call[1]===3));assert.equal(s.controller.active(),true);
 await s.clear();assert.equal(s.controller.active(),false);assert.equal(s.elements['survey-tree'].hidden,false);assert.ok(s.calls.includes('restore'));assert.equal(s.elements['survey-search-query'].value,'');
});
test('save failure blocks search and failed clear preserves results and query for retry',async()=>{
 const s=setup();s.fail(true);await s.submit();assert.deepEqual(s.calls,['save']);assert.equal(s.controller.active(),false);
 s.fail(false);await s.submit();s.fail(true);await s.clear();assert.equal(s.controller.active(),true);assert.equal(s.elements['survey-search-query'].value,'否定');assert.ok(s.elements['survey-search-status'].textContent.includes('保存失败'));
});
test('a late search response cannot appear in another language',async()=>{
 const s=setup();let release;s.reply(()=>new Promise(r=>release=r));const pending=s.submit();await new Promise(r=>setImmediate(r));s.c.activeLanguage='other';s.controller.refresh();release({items:[s.item],nodes:1,total:1,page:1,pages:1});await pending;
 assert.equal(s.controller.active(),false);assert.equal(s.elements['survey-tree'].hidden,false);assert.equal(s.elements['survey-search-query'].value,'');
});
test('a failed outline reload keeps the original search available for retry',async()=>{
 const s=setup();await s.submit();s.adapter.restore=async()=>{throw Error('读取失败');};
 await s.clear();assert.equal(s.controller.active(),true);assert.equal(s.elements['survey-tree'].hidden,true);assert.equal(s.elements['survey-search-query'].value,'否定');assert.ok(s.elements['survey-search-status'].textContent.includes('读取失败'));
});
test('a multiword form hit highlights only those form text nodes, leaving interlinear glosses untouched',()=>{
 const saved=[],root=()=>({nodes:[]}),a=root(),b=root();
 a.nodes=[{textContent:'ni',length:2,parentElement:{closest:()=>null}}];b.nodes=[{textContent:'hao',length:3,parentElement:{closest:()=>null}}];
 const css={highlights:{set:(name,value)=>saved.push(value)}};
 const c={Intl,NodeFilter:{SHOW_TEXT:4},CSS:css,window:{CSS:css,Highlight:true},Highlight:class{constructor(...ranges){this.ranges=ranges;}},document:{createTreeWalker:r=>{let i=0;return {nextNode:()=>r.nodes[i++]};},createRange:()=>({setStart(node,offset){this.startContainer=node;this.startOffset=offset;},setEnd(node,offset){this.endContainer=node;this.endOffset=offset;}})}};
 vm.createContext(c);vm.runInContext(source.slice(0,source.indexOf('function surveySnippet')),c);vm.runInContext(source.slice(source.indexOf(' function highlight('),source.indexOf(' async function navigate(')),c);
 assert.equal(c.highlight([a,b],'ni hao').count,1);assert.equal(saved[0].ranges.length,2);
 for(const range of saved[0].ranges)assert.equal(range.startContainer,range.endContainer);
 assert.equal(saved[0].ranges[0].startContainer,a.nodes[0]);assert.equal(saved[0].ranges[1].startContainer,b.nodes[0]);
});
