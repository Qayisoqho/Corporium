const test=require('node:test'),assert=require('node:assert/strict'),tree=require('../web/timeline-tree.js');
const tracks=[{id:'a',speaker_id:'p',name:'句子'},{id:'b',parent_id:'a',name:'语言'},{id:'c',speaker_id:'p',name:'动作'},{id:'d',name:'环境'}],speakers=[{id:'p',name:'甲'}];
test('one speaker groups multiple roots while children inherit their root',()=>{
 const rows=tree.rows(tracks,speakers);assert.equal(rows.filter(r=>r.group).length,2);assert.equal(rows[0].name,'甲');assert.equal(rows[2].depth,1);assert.equal(tree.root(tracks,'b').speaker_id,'p');assert.equal(rows.at(-2).name,'未指定说话人');
});
test('collapsing a parent hides children, collapsing a speaker hides all its roots',()=>{
 assert.deepEqual(tree.rows(tracks,speakers,new Set(['a'])).filter(r=>r.track).map(r=>r.track.id),['a','c','d']);
 assert.deepEqual(tree.rows(tracks,speakers,new Set(['speaker:p'])).filter(r=>r.track).map(r=>r.track.id),['d']);
});
test('renaming a participant updates the group without renaming tracks',()=>{
 const rows=tree.rows(tracks,[{id:'p',name:'匿名甲'}]);assert.equal(rows[0].name,'匿名甲');assert.equal(rows[1].track.name,'句子');
});

test('DAW track colours separate roots, inherit deeply and survive viewport order changes',()=>{
 const rows=Array.from({length:8},(_,i)=>({id:'root-'+i,position:i*3,color:tree.palette[i]}));
 rows.push({id:'child',parent_id:'root-2',position:7},{id:'grandchild',parent_id:'child',position:8});
 const colors=tree.colors(rows);
 assert.equal(new Set(rows.slice(0,8).map(t=>colors.get(t.id))).size,8);
 assert.equal(colors.get('child'),colors.get('root-2'));
 assert.equal(colors.get('grandchild'),colors.get('root-2'));
 const reversed=tree.colors([...rows].reverse());
 for(const [id,color] of colors){assert.equal(reversed.get(id),color);assert.match(color,/^#[0-9a-f]{6}$/);}
 const extended=tree.colors([...rows,{id:'new-root',position:30}]);
 for(const [id,color] of colors)assert.equal(extended.get(id),color);
 const changed=tree.colors(rows.filter(t=>t.id!=='root-0').map(t=>({...t,position:100-t.position})));
 for(const [id,color] of colors)if(id!=='root-0')assert.equal(changed.get(id),color);
});

test('custom child colours override inherited colours and grandchildren follow the nearest parent',()=>{
 const rows=[{id:'a',color:'#F012AB'},{id:'b',parent_id:'a',color:null},{id:'c',parent_id:'b',color:'#002233'},{id:'d',parent_id:'c'}];
 let colors=tree.colors(rows);assert.equal(colors.get('b'),'#f012ab');assert.equal(colors.get('d'),'#002233');
 rows[0].color='#ffffff';colors=tree.colors(rows);assert.equal(colors.get('b'),'#ffffff');assert.equal(colors.get('d'),'#002233');
 rows[2].color=null;colors=tree.colors(rows);assert.equal(colors.get('d'),'#ffffff');
 assert.equal(tree.nextColor([{id:'a',color:tree.palette[0]}]),tree.palette[1]);
 const legacy=[{id:'a'},{id:'b'}],before=tree.colors(legacy);assert.equal(tree.colors([legacy[1]]).get('b'),before.get('b'));
 assert.equal(tree.validColor('red;--surface:white'),false);
});

test('track palette uses bounded local state and tolerates missing parents or cycles',()=>{
 const broken=[{id:'a',parent_id:'b'},{id:'b',parent_id:'a'},{id:'orphan',parent_id:'deleted'}];
 const colors=tree.colors(broken);
 assert.equal(colors.get('a'),colors.get('b'));
 for(const color of colors.values())assert.match(color,/^#[0-9a-f]{6}$/);
 assert.equal(tree.colors([]).size,0);
 const many=Array.from({length:10000},(_,i)=>({id:'track-'+i,parent_id:i?'track-'+(i-1):null,position:i}));
 const deep=tree.colors(many);assert.equal(deep.size,many.length);assert.equal(new Set(deep.values()).size,1);
});
