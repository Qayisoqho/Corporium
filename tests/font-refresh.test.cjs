const test=require('node:test'),assert=require('node:assert/strict'),vm=require('node:vm'),fs=require('node:fs');
const source=fs.readFileSync('web/fonts.js','utf8');
function setup(){
 const elements=new Map(),selected={value:'localfont-aaaaaaaaaaaaaaaaaaaaaaaa',options:[],classList:{contains:()=>true}};
 const element=id=>{if(!elements.has(id))elements.set(id,{id,textContent:'',append(){}});return elements.get(id);};
 const events=new Map();const c={window:{addEventListener(name,fn){events.set(name,fn);}},document:{head:{append(e){elements.set(e.id,e);}},createElement:()=>({}),querySelector:()=>({append(){}}),querySelectorAll:()=>[selected]},$:id=>elements.get(id)||(['font-scan-status','font-scan-errors','font-scan-list','scan-fonts'].includes(id)?element(id):null),esc:s=>String(s),Option:function(label,value){this.value=value;},renderLanguage(){c.renders++;},renders:0};
 vm.createContext(c);vm.runInContext(source,c);c.selectFont=(select,value)=>{select.value=value;};
 return {c,elements,selected,events};
}
function catalog(version){return {families:[{id:'localfont-aaaaaaaaaaaaaaaaaaaaaaaa',name:'Probe',faces:[{url:'/api/font-file?id=one&v='+version,style:'normal',weight:'400'}]}],builtins:[{family:'Junicode',url:'/font/Junicode/Junicode.ttf?v='+version,style:'normal',weight:'400'},{family:'Junicode',url:'/font/Junicode/Junicode-BoldItalic.ttf?v='+version,style:'italic',weight:'700'}],file_count:1,errors:[]};}
test('immutable bundled UI faces keep their initial CSS URLs after a project font scan',()=>{
 const {c}=setup(),data=catalog('latest');
 data.builtins.push({family:'Noto Sans',url:'/font/NotoSans/NotoSans-VF.ttf?v=latest',style:'normal',weight:'100 900',bundled_ui:true});
 assert.doesNotMatch(c.fontFaceCSS(data),/NotoSans/);assert.match(c.fontFaceCSS(data),/Junicode/);
});
test('font face rules update both stable custom IDs and builtin style aliases',()=>{
 const {c}=setup(),old=c.fontFaceCSS(catalog('before')),fresh=c.fontFaceCSS(catalog('after'));
 assert.notEqual(old,fresh);assert.match(fresh,/font-family:"localfont-aaaaaaaaaaaaaaaaaaaaaaaa"/);assert.match(fresh,/font-family:"Junicode"/);assert.match(fresh,/font-style:italic;font-weight:700/);assert.doesNotMatch(fresh,/before/);
});
test('rescan replaces font URLs while preserving the current selection and avoids rebuilding unchanged controls',async()=>{
 const {c,elements,selected}=setup();let version='old';c.api=async()=>catalog(version);
 await c.scanFonts();const chosen=selected.value;version='new';await c.scanFonts(true);
 assert.equal(selected.value,chosen);assert.match(elements.get('local-font-styles').textContent,/v=new/);assert.equal(c.renders,2);
 await c.scanFonts();assert.equal(c.renders,2);
});
test('a late older scan cannot restore the previous font definitions',async()=>{
 const {c,elements}=setup();let finish;c.api=()=>new Promise(resolve=>finish=resolve);const older=c.scanFonts();
 c.api=async()=>catalog('latest');await c.scanFonts(true);finish(catalog('old'));await older;
 assert.match(elements.get('local-font-styles').textContent,/v=latest/);assert.equal(c.renders,1);
});
test('returning to the window checks for updated fonts without changing the selected family',async()=>{
 const {c,elements,selected,events}=setup();let version='initial';c.api=async()=>catalog(version);
 events.get('DOMContentLoaded')();await c.window.corporiumFontsReady;const chosen=selected.value;
 version='updated';events.get('focus')();await new Promise(resolve=>setImmediate(resolve));
 assert.match(elements.get('local-font-styles').textContent,/v=updated/);assert.equal(selected.value,chosen);
});
