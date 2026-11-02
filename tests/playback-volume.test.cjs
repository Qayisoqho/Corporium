const test=require('node:test'),assert=require('node:assert/strict');
const {percent,sentence,recording,timelineContext,createStore}=require('../web/playback-volume.js');
function storage(){const values=new Map();return {values,getItem:key=>values.get(key)??null,setItem:(key,value)=>values.set(key,value)};}
test('new playback settings default to full volume; corrupt and out-of-range values are bounded',()=>{
 const data=storage(),s=createStore(data,'p:');assert.equal(s.effective(sentence('a','t')),1);
 for(const value of [undefined,null,'','bad',NaN,Infinity])assert.equal(percent(value),100);
 assert.equal(percent(-3),0);assert.equal(percent(120),100);assert.equal(percent('27.4'),27);
 data.values.set('p:sentence:a','broken');assert.equal(s.effective(sentence('a')),1);
 data.values.set('p:sentence:a','{"percent":300}');assert.equal(s.effective(sentence('a')),1);
});
test('text and sentence factors are multiplied afresh without cumulative attenuation',()=>{
 const s=createStore(storage(),'p:');s.set('text:t',{percent:60});s.set('sentence:a',{percent:50});
 for(let i=0;i<10;i++)assert.equal(s.effective(sentence('a','t')),.3);
 assert.equal(s.effective(sentence('b','t')),.6);assert.equal(s.effective(sentence('a','other')),.5);
 s.set('text:t',{percent:80});assert.equal(s.effective(sentence('a','t')),.4);
});
test('mute and reset preserve local level and do not reset the parent or siblings',()=>{
 const s=createStore(storage(),'p:');s.set('text:t',{percent:60});s.set('sentence:a',{percent:40});
 s.toggle('sentence:a');assert.equal(s.effective(sentence('a','t')),0);s.toggle('sentence:a');assert.equal(s.get('sentence:a').percent,40);
 s.toggle('text:t');assert.equal(s.effective(sentence('a','t')),0);s.reset('sentence:a');assert.equal(s.effective(sentence('a','t')),0);
 s.toggle('text:t');assert.equal(s.effective(sentence('a','t')),.6);
 s.set('sentence:a',{percent:0});s.toggle('sentence:a');assert.equal(s.get('sentence:a').percent,100);
});
test('preferences survive store recreation and isolate projects, sentences and entry recordings',()=>{
 const data=storage(),s=createStore(data,'projectA:');s.set(recording('lexeme','same','one').key,{percent:12});s.set(sentence('same').key,{percent:25});
 const reopened=createStore(data,'projectA:');assert.equal(reopened.effective(recording('lexeme','same','one')),.12);
 assert.equal(reopened.effective(recording('lexeme','same','two')),1);assert.equal(reopened.effective(recording('morpheme','same','one')),1);
 assert.equal(createStore(data,'projectB:').effective(sentence('same')),1);assert.equal(reopened.effective(sentence('same')),.25);
});
test('independent audio attachments and aligned clips use the same sentence preference',()=>{
 const context=recording('independent','example','file'),s=createStore(storage(),'p:');s.set(context.key,{percent:37});
 assert.equal(s.effective(sentence('independent:example')), .37);assert.equal(s.effective(recording('independent','example','other')), .37);
 assert.equal(sentence('independent:example','@independent').parent,null);
});
test('timeline sentence playback shares sentence/text factors; arbitrary ranges use the session',()=>{
 const i={entry_id:'a',text_id:'t',start_ms:100,end_ms:300},s=createStore(storage(),'p:');s.set('text:t',{percent:50});s.set('sentence:a',{percent:40});
 assert.equal(s.effective(timelineContext(i,[100,300],'session')),.2);
 assert.equal(s.effective(timelineContext(i,[100,350],'session')),1);
 assert.equal(timelineContext(null,[100,300],'session').key,'timeline:session');
});
test('volume updates notify live controls and handle storage denied or quota exceeded',()=>{
 const s=createStore({getItem:()=>'{"percent":20}',setItem(){throw Error('quota');}},'p:');let seen=[];const off=s.subscribe(()=>seen.push(s.effective(sentence('a'))));
 s.set('sentence:a',{percent:70});s.toggle('sentence:a');assert.deepEqual(seen,[.7,0]);off();s.reset('sentence:a');assert.equal(seen.length,2);
 const denied=createStore({getItem(){throw Error('denied');},setItem(){throw Error('denied');}},'p:');denied.set('sentence:a',{percent:30});assert.equal(denied.effective(sentence('a')),.3);
});
test('another tab can refresh stored preferences without retaining stale in-memory levels',()=>{
 const data=storage(),a=createStore(data,'p:'),b=createStore(data,'p:');a.set('sentence:a',{percent:20});b.set('sentence:a',{percent:80});a.reload();assert.equal(a.effective(sentence('a')),.8);
});

test('shared player binding updates the actual media volume immediately, releases stopped players and resets mute',()=>{
 const vm=require('node:vm'),fs=require('node:fs');const data=storage();
 data.setItem('corporium-media-volume','.3'); // The retired global setting must not affect a new object.
 const context={localStorage:data,projectStorageKey:key=>key+':project:A',document:{body:{},addEventListener(){}},MutationObserver:class{observe(){}},addEventListener(){}};
 context.window=context;vm.runInNewContext(fs.readFileSync(require.resolve('../web/playback-volume.js'),'utf8'),context);
 const v=context.CorporiumVolume,media={muted:true,volume:.3};v.bind(media,v.sentence('a','t'));assert.equal(media.volume,1);assert.equal(media.muted,false);
 v.set('text:t',{percent:60});v.set('sentence:a',{percent:50});assert.equal(media.volume,.3);
 v.toggle('text:t');assert.equal(media.volume,0);v.toggle('text:t');assert.equal(media.volume,.3);
 v.bind(media,v.sentence('b','t'));assert.equal(media.volume,.6);v.set('sentence:a',{percent:20});assert.equal(media.volume,.6);
 v.unbind(media);v.set('text:t',{percent:30});assert.equal(media.volume,.6);
});
