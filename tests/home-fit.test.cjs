const test=require('node:test'),assert=require('node:assert/strict'),vm=require('node:vm'),fs=require('node:fs');
function setup(){
 const box={clientWidth:800,clientHeight:180},example={hidden:false};let scale=1;
 const content={style:{setProperty(k,v){scale=v;}},get scrollWidth(){return box.clientWidth;},getBoundingClientRect(){return {height:Math.ceil(2400*scale/box.clientWidth)*32*scale+Math.ceil(1200*scale/box.clientWidth)*28*scale+16*scale};}};
 const context={homeVisible:true,$:id=>({'home-example':example,'home-example-body':box,'home-example-open':content}[id])};
 const source=fs.readFileSync(require.resolve('../web/home.js'),'utf8');
 vm.runInNewContext(source.slice(source.indexOf('function fitHomeExample()'),source.indexOf('function scheduleHomeFit()')),context);
 return {box,example,context,content,scale:()=>scale,fit:()=>context.fitHomeExample()};
}
test('ordinary sentences retain their original size',()=>{const s=setup();s.fit();assert.equal(s.scale(),1);});
test('long sentences fit within available height and recover after expanding the window',()=>{const s=setup();s.box.clientWidth=220;s.box.clientHeight=80;s.fit();assert.ok(s.scale()>0&&s.scale()<1);assert.ok(s.content.getBoundingClientRect().height<=78);s.box.clientWidth=800;s.box.clientHeight=300;s.fit();assert.equal(s.scale(),1);});
test('every narrower viewport is measured again; hidden and unmeasurable examples are skipped',()=>{const s=setup();s.box.clientWidth=400;s.box.clientHeight=80;s.fit();const before=s.scale();s.box.clientWidth=180;s.fit();assert.ok(s.scale()<before);const fitted=s.scale();s.example.hidden=true;s.fit();assert.equal(s.scale(),fitted);s.example.hidden=false;s.box.clientHeight=0;s.fit();assert.equal(s.scale(),fitted);});
