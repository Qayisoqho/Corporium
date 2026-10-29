const test=require('node:test'),assert=require('node:assert/strict'),vm=require('node:vm'),fs=require('node:fs');
const source=fs.readFileSync(require.resolve('../web/vocabulary-statistics.js'),'utf8');
function setup(){
 const nodes=new Map();let next=0;
 function make(){const n={children:[],innerHTML:'',attributes:{},append(...v){this.children.push(...v);},before(v){this.beforeNode=v;},setAttribute(k,v){this.attributes[k]=v;},querySelector:q=>node(q),querySelectorAll:()=>[]};Object.defineProperty(n,'id',{set:id=>nodes.set(id,n)});return n;}
 function node(id){if(!nodes.has(id))nodes.set(id,make());return nodes.get(id);}
 const esc=s=>String(s??'').replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
 const s={window:{},document:{createElement:()=>make(),createTextNode:s=>({textContent:s})},$:node,esc,rich:esc,languageList:[{id:'one',name:'Language',metadata:'{}'}],languageTypography:()=>'',topPagination(){},CorporiumI18n:{phrase:s=>({'涉及词次':'Containing word tokens','独立例句库':'Examples library'}[s]||s)}};
 vm.createContext(s);vm.runInContext(source,s);return {api:s.window.CorporiumVocabulary,node};
}
const data=()=>({id:'run',statistics:{words:7,types:4,sentences:3,morpheme_words:5,root_words:5,rows:[{title:'A',words:4,types:3,sentences:1,excluded:0},{title:'B',words:2,types:2,sentences:1,excluded:0}]},vocabulary:{view:'overview',rows:[],page:1,pages:1,total:4,order:'frequency',items:[]}});
test('overview shows union type count and per-text types without summing them',()=>{
 const {api,node}=setup(),d=data();d.statistics.rows.push({kind:'independent',title:'独立例句库',words:1,types:1,sentences:1,excluded:0});api.render(d,{reload(){},card(){},source(){}});
 assert.match(node('analysis-summary').innerHTML,/>4<\/button>/);
 assert.ok(node('analysis-results').children[1].innerHTML.includes('<td>3</td>'));
 assert.equal(node('analysis-counts-case').checked,true);
 assert.match(node('analysis-results').children[1].innerHTML,/Examples library/);
});
test('morpheme rows keep occurrence counts distinct from containing word tokens and escape source text',()=>{
 const {api,node}=setup(),d=data();d.vocabulary={...d.vocabulary,view:'roots',denominator:4,rows:[{key:'root',form:'<script>',gloss:'<unsafe>',kind:'root',language_id:'one',count:4,words:2,sentences:2,texts:1,types:2}]};
 api.render(d,{reload(){},card(){},source(){}});
 const body=node('analysis-results').children[1].children.at(-1).innerHTML;
 assert.match(body,/Containing word tokens/);assert.match(body,/&lt;script&gt;/);assert.match(body,/&lt;unsafe&gt;/);assert.doesNotMatch(body,/<script>|<unsafe>/);assert.match(body,/>4<\/button>/);assert.match(body,/<td>2<\/td>/);
});
test('profile selection restores within its run and resets when another run is selected',()=>{
 const {api}=setup();api.restore({id:'one',view:'roots',order:'form',page:2,item:'root',sourcePage:1});
 assert.equal(api.params('one').vocabulary_item,'root');assert.equal(api.params('one').vocabulary_page,2);
 assert.equal(api.params('two').vocabulary_view,'overview');assert.equal(api.params('two').vocabulary_item,undefined);
 assert.equal(api.render({statistics:{}},{}),false);
});
test('configured runs can open custom groups and preserve overlapping occurrence percentages',()=>{
 const {api,node}=setup(),d=data();api.params(d.id,'custom');
 d.vocabulary={...d.vocabulary,view:'custom',denominator:2,selection:{target:'morpheme',group_by:'class:semantic',label:'语义类',eligible_entries:1,entries:1,words:1},rows:[{key:'a',form:'<user class>',language_id:'one',count:2,words:1,sentences:1,texts:1,types:1,entries:1},{key:'b',form:'second',language_id:'one',count:2,words:1,sentences:1,texts:1,types:1,entries:1}]};
 api.render(d,{reload(){},card(){},source(){}});
 const body=node('analysis-results').children[1].children.at(-1).innerHTML;
 assert.match(body,/&lt;user class&gt;/);assert.equal((body.match(/100.00%/g)||[]).length,2);
 assert.equal(node('analysis-results').children[0].children.length,3);
 assert.equal(api.params(d.id).vocabulary_view,'custom');
});
test('entry statistics show meanings to distinguish separate homographic identities',()=>{
 const {api,node}=setup(),d=data();d.vocabulary={...d.vocabulary,view:'custom',denominator:1,selection:{target:'lexeme',group_by:'entry',label:'按条目分别统计',eligible_entries:2,entries:1,words:1},rows:[{key:'id',form:'same',gloss:'<meaning>',language_id:'one',count:1,words:1,sentences:1,texts:1,types:1,entries:1}]};
 api.render(d,{reload(){},card(){},source(){}});
 const body=node('analysis-results').children[1].children.at(-1).innerHTML;
 assert.match(body,/&lt;meaning&gt;/);assert.doesNotMatch(body,/<meaning>/);
});
