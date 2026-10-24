const test=require('node:test'),assert=require('node:assert/strict');
const geometry=require('../web/timeline-geometry.js');
test('pressing play after the media ends starts again from zero',async()=>{
 const vm=require('node:vm'),fs=require('node:fs'),source=fs.readFileSync(require.resolve('../web/timeline.js'),'utf8');
 const s={data:{media:{metadata:{duration_ms:20000}}},head:20000,timeSelection:null,loop:false,boundedPlayer:{start(a,z){assert.equal(a,0);assert.equal(z,20);}}};
 vm.createContext(s);vm.runInContext(source.match(/async function playTimeSelection[^\n]+/)[0],s);await vm.runInContext('playTimeSelection()',s);
});
test('zoom stops at the full extent and returns to its origin, including out-of-media annotations',()=>{
 let view=[5000,10000];for(let n=0;n<100;n++)view=geometry.zoom(...view,.5,100,[-2000,25000]);assert.deepEqual(view,[-2000,27000]);
 for(let n=0;n<100;n++)view=geometry.zoom(...view,.5,-100,[-2000,25000]);assert.equal(view[1],1);assert.ok(view[0]>=-2000&&view[0]+view[1]<=25000);
});
test('short clips, empty timelines and media longer than a day have finite usable bounds',()=>{
 assert.deepEqual(geometry.viewport(0,60000,[0,50]),[0,50]);assert.deepEqual(geometry.viewport(0,60000,[0,0]),[0,60000]);
 assert.deepEqual(geometry.zoom(0,170000000,.5,100,[0,180000000]),[0,180000000]);
});
test('playback waits for the right edge, returns after a loop and stops scrolling at the end',()=>{
 assert.equal(geometry.follow(0,1000,500,[0,10000]),0);
 assert.equal(geometry.follow(0,1000,999,[0,10000]),0);
 assert.equal(geometry.follow(0,1000,1000,[0,10000]),1000);
 assert.equal(geometry.follow(0,1000,1050,[0,10000]),1050);
 assert.equal(geometry.follow(9000,1000,10000,[0,10000]),9000);
 assert.equal(geometry.follow(9000,1000,100,[0,10000]),0);
});
