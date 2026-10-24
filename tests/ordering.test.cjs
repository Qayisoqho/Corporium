const {test}=require('node:test'),assert=require('node:assert/strict'),order=require('../web/ordering.js');
test('outline numbers recompute after reparenting without changing titles',()=>{
 const nodes=[{id:'a',parent_id:null,title:'1 原题'},{id:'b',parent_id:'a'},{id:'c',parent_id:'b'},{id:'d',parent_id:'a'}];
 assert.equal(order.numbers(nodes).get('c'),'1.1.1');nodes[2].parent_id='a';
 assert.equal(order.numbers(nodes).get('c'),'1.2');assert.equal(order.numbers(nodes).get('d'),'1.3');assert.equal(nodes[0].title,'1 原题');
 assert.equal(order.numbers([nodes[0],nodes[3],nodes[1],nodes[2]]).get('d'),'1.1');
});
test('multi-drag preserves selected order and stable IDs in either direction',()=>{
 const ids=['a','b','c','d','e'];assert.deepEqual(order.move(ids,['d','b'],'e',true),['a','c','e','b','d']);
 assert.deepEqual(order.move(ids,['c','e'],'a'),['c','e','a','b','d']);
 assert.deepEqual(order.move(ids,['b','d'],'b'),ids);assert.deepEqual(order.move(ids,['b'],'missing'),ids);assert.deepEqual(ids,['a','b','c','d','e']);
});
