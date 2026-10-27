const test=require('node:test'),assert=require('node:assert/strict');
const core=require('../web/formatted-copy-format.js'),fixtures=require('./formatted-copy-fixtures.cjs');
const clone=x=>JSON.parse(JSON.stringify(x));
const row=()=>clone(fixtures.rows[0]);
const frozen=x=>{if(x&&typeof x==='object'){Object.values(x).forEach(frozen);Object.freeze(x);}return x;};
const cells=(html,key)=>[...html.matchAll(new RegExp('<tr[^>]* data-copy-row="'+key+'">([\\s\\S]*?)</tr>','g'))].map(m=>(m[1].match(/<td\b/g)||[]).length);

test('Word numbers follow only selected occurrences, with one number per group and original member labels',()=>{
 const a=row(),b=row(),c=row(),d=row();[a,b,c,d].forEach((x,i)=>{x.key='position'+i;x.label='('+[127,205,300,400][i]+')';});
 b.group={key:'group',name:'问答',context:''};b.label='b. Q:';c.group={...b.group};c.label='c. A:';d.sourceId=a.sourceId;
 const input=frozen([a,b,c,d]),out=core.numberSelection(input);
 assert.deepEqual(out.map(x=>x.label),['(1)','b. Q:','c. A:','(3)']);assert.equal(out[1].group.number,'(2)');assert.equal(out[2].group.number,'(2)');assert.equal(a.label,'(127)');assert.equal(b.group.number,undefined);
 const payload=core.build(out);assert.match(payload.plain,/\(2\) 问答/);assert.match(payload.plain,/b\. Q:/);assert.match(payload.plain,/c\. A:/);assert.doesNotMatch(payload.plain,/\(127\)|\(205\)/);
 assert.equal(payload.summary.sentences,4);assert.deepEqual(cells(payload.html,'form'),cells(payload.html,'gloss'));
});

test('partial and repeated group occurrences keep abc, roles and judgments while receiving consecutive Word numbers',()=>{
 const a=row(),b=row();a.key='first';b.key='second';a.group={key:'first-group',name:'',context:''};b.group={key:'second-group',name:'',context:''};a.label='c. Q:';b.label='b. A:';a.judgment={symbol:'*'};
 const out=core.numberSelection([a,b]);assert.equal(out[0].group.number,'(1)');assert.equal(out[1].group.number,'(2)');const payload=core.build(out);assert.match(payload.plain,/c\. Q: \*/);assert.match(payload.plain,/b\. A:/);
});

test('every table retains one form row and one gloss row, including all segments of long sentences',()=>{
 const result=core.build(fixtures.rows),tables=[...result.html.matchAll(/<table\b[\s\S]*?<\/table>/g)].map(m=>m[0]);
 assert.equal(tables.length,result.summary.tables.length);
 tables.forEach((table,i)=>{const columns=result.summary.tables[i].wordColumns+1+(result.summary.tables[i].trailingColumn?1:0);assert.deepEqual(cells(table,'form'),[columns]);assert.deepEqual(cells(table,'gloss'),[columns]);});
 assert.equal(result.summary.tables.filter(t=>t.key===fixtures.rows[6].key).reduce((n,t)=>n+t.wordColumns,0),24);
 assert.match(tables[6],/white-space:nowrap/);assert.doesNotMatch(tables[6],/<br>/);
});
test('font families, variants and scripts remain editable HTML',()=>{
 const r=core.build(fixtures.rows.slice(1,3));
 assert.match(r.html,/IPAPANNEW/);assert.match(r.html,/Junicode/);assert.match(r.html,/Microsoft YaHei/);
 assert.match(r.html,/<sup>55<\/sup>/);assert.match(r.html,/<sub>1<\/sub>/);assert.match(r.html,/font-style:italic/);
 assert.match(r.html,/font-variant:small-caps/);assert.doesNotMatch(r.html,/<(?:img|canvas|svg)\b/);
});
test('same source in different groups is copied twice, in selected display order',()=>{
 const selected=[fixtures.rows[1],fixtures.rows[5]],r=core.build(selected);
 assert.equal(selected[0].sourceId,selected[1].sourceId);assert.equal(r.summary.sentences,2);assert.equal(r.summary.groups,2);
 assert.match(r.plain,/a\. Q:/);assert.match(r.plain,/b\. Q:/);assert.equal((r.plain.match(/mĩra/g)||[]).length,2);
});
test('a single b member keeps b, A and its original group heading',()=>{
 const r=core.build([fixtures.rows[2]]);
 assert.match(r.plain,/\(18\).*问答/);assert.match(r.plain,/b\. A:/);assert.doesNotMatch(r.plain,/a\. A:/);
});
test('whole group has one title and context, each judgment is separate from its local note',()=>{
 const r=core.build(fixtures.rows.slice(1,5));
 assert.equal((r.plain.match(/问答与合法性对比/g)||[]).length,1);assert.equal((r.plain.match(/调查语境/g)||[]).length,1);
 assert.match(r.plain,/c\. A: \* na luma/);assert.match(r.plain,/d\. A: \? luma/);assert.match(r.plain,/本处判断：此语境/);
 assert.equal(new Set(r.summary.tables.map(t=>t.labelWidthPt)).size,1);
});
test('notes are opt in; selected examples and metadata are never mutated',()=>{
 const input=frozen(clone(fixtures.rows)),before=JSON.stringify(input);
 assert.doesNotMatch(core.build(input).plain,/默认不复制备注/);assert.match(core.build(input,{includeNotes:true}).plain,/默认不复制备注/);
 assert.equal(JSON.stringify(input),before);
});
test('CF_HTML offsets count UTF-8 bytes across Chinese, IPA combining marks and emoji',()=>{
 const x=row();x.body.ipa='中文 mĩra ɕː 👩🏽';const payload=core.build([x]),buffer=Buffer.from(payload.cfHtml);
 const header=buffer.toString('ascii',0,110),field=n=>Number(header.match(new RegExp(n+':(\\d+)'))[1]);
 assert.equal(buffer.subarray(field('StartHTML'),field('EndHTML')).toString('utf8'),payload.html);
 const fragment=buffer.subarray(field('StartFragment'),field('EndFragment')).toString('utf8');
 assert.ok(fragment.startsWith('<div'));assert.ok(fragment.endsWith('</div>'));assert.match(fragment,/中文 mĩra ɕː 👩🏽/);
 assert.equal(field('EndHTML'),buffer.length);assert.equal(new TextDecoder('utf-8',{fatal:true}).decode(buffer),buffer.toString('utf8'));
});
test('literal markup and boundary markers cannot introduce active HTML or extra CF_HTML fragments',()=>{
 const x=row();x.body.ipa='<img src=x onerror=alert(1)> <!--StartFragment-->';x.body.translation='<script>bad()</script> & "quote"';
 const r=core.build([x]);assert.doesNotMatch(r.html,/<img|<script/);assert.match(r.html,/&lt;img/);
 assert.equal((r.html.match(/<!--StartFragment-->/g)||[]).length,1);assert.match(r.plain,/<script>bad/);
});
test('empty gloss and punctuation cells stay in exactly the same column',()=>{
 const r=core.build([fixtures.rows[7]]);assert.deepEqual(cells(r.html,'form'),[5]);assert.deepEqual(cells(r.html,'gloss'),[5]);
 assert.equal(r.plain.split('\r\n')[1],'luma\t,\tna');assert.equal(r.plain.split('\r\n')[2],'\t\t来');
});
test('visible extra rows preserve column count and layer fonts; hidden rows are excluded',()=>{
 const x=row();x.layers=[{name:'orthography',font:'Charis SIL',size:120,values:['甲','乙','丙']},{visible:false,values:[]}];
 const r=core.build([x]);assert.deepEqual(cells(r.html,'layer'),[5]);assert.match(r.html,/Charis SIL/);assert.match(r.plain,/甲\t乙\t丙/);
 x.layers[0].values.pop();assert.throws(()=>core.build([x]),/一一对应/);
});
test('the Word column limit creates two or more tables without losing or reordering words or layers',()=>{
 const x=row();x.metadata={...x.metadata,morpheme_scale:.6,gloss_scale:.6};x.body.words=Array.from({length:125},(_,i)=>({form:'x',gloss:i===62?'':'y'}));x.layers=[{size:60,values:x.body.words.map((_,i)=>i===62?'':'z')}];
 const r=core.build([x]);assert.deepEqual(r.summary.tables.map(t=>t.wordColumns),[62,62,1]);assert.equal(r.summary.warnings[0].parts,3);assert.equal((r.html.match(/data-copy-word=/g)||[]).length,125*3);assert.match(r.html,/续/);
 assert.deepEqual(r.summary.tables.map(t=>[t.start,t.end]),[[0,62],[62,124],[124,125]]);
});
test('short examples have sentence-level space without stretching their word grid; no 64th column is added',()=>{
 const a=row(),r=core.build([a]);assert.equal(r.summary.tables[0].widthPt,468);assert.equal(r.summary.tables[0].trailingColumn,true);
 assert.equal((r.html.match(/data-copy-spacer="true"/g)||[]).length,2);
 a.metadata={...a.metadata,morpheme_scale:.6,gloss_scale:.6};a.body.words=Array.from({length:62},()=>({form:'a',gloss:'a'}));const wide=core.build([a],{referenceWidthPt:1200});
 assert.deepEqual(cells(wide.html,'form'),[63]);assert.equal(wide.summary.tables[0].trailingColumn,false);
});
test('word-internal line breaks and tabs are rejected rather than silently flattened',()=>{
 for(const marker of ['\n','\r','\t','\u2028']){const x=row();x.body.words[0].gloss='one'+marker+'two';assert.throws(()=>core.build([x]),/换行或Tab/);}
 const x=row();x.body.ipa='first\nsecond';assert.match(core.build([x]).html,/first<br>second/);
});
test('metadata is per sentence and independent of screen scale or theme',()=>{
 const a=row(),b=row();b.key='other';b.metadata={...b.metadata,ipa_font:'Charis SIL',ipa_scale:1.5};
 const r=core.build([a,b],{screenScale:1.5,theme:'night'});assert.match(r.html,/IPAPANNEW/);assert.match(r.html,/Charis SIL/);
 assert.equal(core.build([a]).html,core.build([a],{screenScale:1.5,theme:'night'}).html);
 assert.equal(core.typography({translation_font:'sans-serif'}).translation.font,'"Segoe UI"');
});
test('invalid font CSS, broken Unicode, duplicate positions and inconsistent groups fail explicitly',()=>{
 const x=row();x.metadata.ipa_font='x";background:url(x)';assert.throws(()=>core.build([x]),/字体名称/);
 x.metadata.ipa_font='IPAPANNEW';x.body.ipa='bad\uD800';assert.throws(()=>core.build([x]),/Unicode/);
 assert.throws(()=>core.build([row(),row()]),/展示位置不能重复/);
 const group=clone(fixtures.rows.slice(1,3));group[1].group.name='different';assert.throws(()=>core.build(group),/不一致/);
});
test('IPA-only examples remain available without inventing word or gloss rows',()=>{
 const x=row();x.body.words=[];const r=core.build([x]);assert.deepEqual(cells(r.html,'form'),[]);assert.match(r.plain,/soro55/);
});
test('selection follows page order, not click order; successful simulated copying exits mode',async()=>{
 const s=new core.Selection(fixtures.rows);s.enter();s.select(fixtures.rows[3].key,true);s.select(fixtures.rows[1].key,true);
 let written;await s.copy(async p=>{written=p;});assert.deepEqual(written.summary.tables.map(t=>t.key),[fixtures.rows[1].key,fixtures.rows[3].key]);
 assert.equal(s.active,false);assert.equal(s.chosen.size,0);
});
test('whole-group selection and mixed state do not affect another occurrence of the same source',()=>{
 const s=new core.Selection(fixtures.rows);s.enter();s.select(fixtures.rows[1].key,true);assert.equal(s.groupState('group-contrast'),'some');
 s.group('group-contrast',true);assert.equal(s.groupState('group-contrast'),'all');assert.equal(s.chosen.size,4);assert.equal(s.chosen.has(fixtures.rows[5].key),false);
 s.group('group-contrast',false);assert.equal(s.groupState('group-contrast'),'none');
});
test('a rejected simulated clipboard write preserves selection and permits retry',async()=>{
 const s=new core.Selection(fixtures.rows);s.enter();s.select(fixtures.rows[0].key,true);
 await assert.rejects(s.copy(async()=>{throw Error('write unavailable');}),/unavailable/);assert.equal(s.active,true);assert.equal(s.chosen.size,1);assert.equal(s.busy,false);
 await s.copy(async()=>{});assert.equal(s.active,false);
});
test('double copy is coalesced and neither cancel nor paging can change an in-flight selection',async()=>{
 const s=new core.Selection(fixtures.rows);s.enter();s.select(fixtures.rows[0].key,true);let complete,calls=0;
 const first=s.copy(()=>{calls++;return new Promise(resolve=>complete=resolve);});assert.equal(await s.copy(async()=>calls++),null);assert.equal(calls,1);
 assert.equal(s.cancel(),false);assert.throws(()=>s.changePage([]),/不能改变范围/);assert.throws(()=>s.select(fixtures.rows[1].key,true),/不能选择/);
 complete();await first;assert.equal(s.busy,false);
});
test('paging clears selections and oversized content never reaches the simulated writer',async()=>{
 const s=new core.Selection(fixtures.rows);s.enter();s.select(fixtures.rows[0].key,true);s.changePage([fixtures.rows[1]]);assert.equal(s.active,false);assert.equal(s.chosen.size,0);
 const x=row();x.body.words=[{form:'W'.repeat(300),gloss:''}];const t=new core.Selection([x]);t.enter();t.select(x.key,true);let writes=0;
 await assert.rejects(t.copy(async()=>writes++),/词格过宽/);assert.equal(writes,0);assert.equal(t.chosen.size,1);
});
test('wide tables split before Word can clamp columns; individual cells are never truncated',()=>{
 const x=row();x.body.words=Array.from({length:40},(_,i)=>({form:'morpheme'+i,gloss:'第'+i+'词'}));const r=core.build([x]);assert.ok(r.summary.warnings.length);assert.equal(r.summary.tables.reduce((n,t)=>n+t.wordColumns,0),40);assert.ok(r.summary.tables.every(t=>t.widthPt<=1000));
});
test('registered tag scripts remain normal caps and explicit nonitalic runs survive italic row preferences',()=>{
 const r=core.build([{...row(),body:{ipa:'',words:[{form:[{text:'na'},{text:'1',script:'sub',italic:false}],gloss:[{text:'neg',smallCaps:true,italic:false},{text:'POT',script:'sub',smallCaps:true,italic:false}]}],translation:''}}]);assert.doesNotMatch(r.html,/font-family:inherit/);assert.match(r.html,/font-style:normal.*<sub>POT/);assert.match(r.html,/font-variant:small-caps/);
});
test('zero selections and malformed controls cannot copy anything',async()=>{
 const s=new core.Selection(fixtures.rows);await assert.rejects(s.copy(async()=>{}),/先选择/);s.enter();await assert.rejects(s.copy(async()=>{}),/先选择/);
 assert.throws(()=>s.select('unknown',true),/不能选择/);assert.throws(()=>core.build([]),/请选择/);
});
test('sentence layers keep their own type and remain exactly once around split tables in HTML and plain text',()=>{
 const x=row();x.body.words=Array.from({length:70},()=>({form:'word',gloss:'tag'}));x.sentenceLayers=[{anchor:'ipa',value:'书写层甲',font:'Charis SIL',pt:14},{anchor:'translation',value:'翻译层乙',font:'Arial',pt:9}];
 const r=core.build([x]);assert.ok(r.summary.tables.length>1);for(const value of ['书写层甲','翻译层乙']){assert.equal(r.html.split(value).length,2);assert.equal(r.plain.split(value).length,2);}assert.match(r.html,/font-size:14pt/);assert.match(r.html,/font-size:9pt/);
});
test('uppercase registered tags retain their spelling and reduce only the visible capitals, matching all-small-caps',()=>{
 const x=row();x.body.words[0].gloss='PST';const r=core.build([x]);assert.match(r.html,/font-size:80%">PST<\/span>/);assert.match(r.plain,/PST/);assert.doesNotMatch(r.plain,/pst/);
});
