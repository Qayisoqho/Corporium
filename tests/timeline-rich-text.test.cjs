const test=require('node:test'),assert=require('node:assert/strict'),vm=require('node:vm'),fs=require('node:fs');
const app=fs.readFileSync(require.resolve('../web/app.js'),'utf8'),timeline=fs.readFileSync(require.resolve('../web/timeline.js'),'utf8');
function setup(){
 const c={from:0,span:10000,selectedInterval:null,data:{tracks:[{id:'s',kind:'sentence'},{id:'e',kind:'event'},{id:'l',kind:'language'}]},time:String,ipaStyle:()=>'',sentenceBlockText:i=>i.text};
 vm.createContext(c);vm.runInContext(app.slice(app.indexOf('const esc='),app.indexOf('// A hidden desktop window')),c);
 vm.runInContext(timeline.slice(timeline.indexOf('function block('),timeline.indexOf('function sentenceBlockText(')),c);return c;
}
test('sentence blocks render escaped IPA and scripts like the original sentence, including tooltips',()=>{
 const c=setup(),i={entry_id:'source',track_id:'s',id:'one',start_ms:0,end_ms:1000,text:'qa(\\~ qa) #sup[ʰ] #sub[2]'};
 const html=c.block(i);assert.ok(html.includes('qa(~ qa) <sup>ʰ</sup> <sub>2</sub>'));assert.ok(html.includes('title="qa(~ qa) ʰ 2 ·'));assert.ok(html.includes('aria-label="qa(~ qa) ʰ 2 '));assert.ok(!html.includes('\\~'));assert.equal(i.text,'qa(\\~ qa) #sup[ʰ] #sub[2]');
});
test('literal backslashes and event labels remain literal and embedded markup stays escaped',()=>{
 const c=setup();assert.equal(c.plainRich('qa\\x'),'qa\\x');
 const i={id:'one',track_id:'s',start_ms:0,end_ms:1000,text:'\\~ <img src=x onerror=bad> #sup[x]'};
 assert.ok(c.block(i).includes('\\~ &lt;img src=x onerror=bad&gt; #sup[x]'));
 i.entry_id='source';const html=c.block(i);assert.ok(!html.includes('<img'));assert.ok(html.includes('&lt;img src=x onerror=bad&gt; <sup>x</sup>'));
 for(const track of ['e','l']){i.track_id=track;assert.ok(c.block(i).includes('\\~ &lt;img src=x onerror=bad&gt; #sup[x]'));}
});
