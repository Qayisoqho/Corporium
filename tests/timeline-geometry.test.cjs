const test=require('node:test'),assert=require('node:assert/strict');
const g=require('../web/timeline-geometry.js');
test('moving stops at both neighbors and keeps duration',()=>{assert.deepEqual(g.clamp(100,200,1000,'move',50,250),[150,250]);assert.deepEqual(g.clamp(100,200,-1000,'move',50,250),[50,150]);});
test('resizing cannot cross another block or invert itself',()=>{assert.deepEqual(g.clamp(100,200,1000,'right',0,250),[100,250]);assert.deepEqual(g.clamp(100,200,1000,'left',0,250),[199,200]);});
test('negative and beyond-duration intervals remain valid',()=>{assert.deepEqual(g.clamp(100,200,-500,'move'),[-400,-300]);assert.deepEqual(g.clamp(100,200,500000,'move'),[500100,500200]);});
test('snap only within tolerance',()=>{assert.equal(g.snap(98,[0,100],3),100);assert.equal(g.snap(95,[0,100],3),95);});
test('horizontal zoom keeps cursor time fixed including negative origins',()=>{const [a,s]=g.zoom(-10000,60000,.35,-100);assert.ok(s<60000);assert.ok(Math.abs((a+.35*s)-11000)<1);});
test('zoom limits remain finite and do not change other axes',()=>{assert.deepEqual(g.zoom(12,500,0,-100),[12,500]);assert.deepEqual(g.zoom(12,86400000,0,100),[12,86400000]);});
