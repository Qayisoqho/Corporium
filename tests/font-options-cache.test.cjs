const test=require('node:test'),assert=require('node:assert/strict'),vm=require('node:vm'),fs=require('node:fs');
function setup(){
 const context=vm.createContext({esc:x=>x,CorporiumI18n:{ui:(zh,en)=>en,f:()=>undefined},Option:function(text,value){this.text=text;this.value=value;}});
 vm.runInContext(fs.readFileSync('web/fonts.js','utf8').split('function fontFaceCSS')[0],context);
 const dialog={open:false},options=['Junicode','STIX Two Text','@global'].map(value=>({value,selected:value==='STIX Two Text'}));
 const select={options:[...options],_value:'STIX Two Text',ownerDocument:{activeElement:null},closest:()=>dialog,replaceChildren(...nodes){this.options=nodes;},add(node){this.options.push(node);},get value(){return this._value;},set value(value){this._value=this.options.some(o=>o.value===value)?value:'';for(const o of this.options)o.selected=o.value===this._value;}};
 return {context,dialog,select,options};
}
test('unfocused font menus park nodes without changing selected value; focus restores exact order and identities',()=>{
 const {context:c,dialog,select,options}=setup();c.parkFontOptions(select);
 assert.deepEqual(select.options,[options[1]]);assert.equal(select.value,'STIX Two Text');
 select.ownerDocument.activeElement=select;dialog.open=true;c.restoreFontOptions(select);assert.deepEqual(select.options,options);assert.equal(select.value,'STIX Two Text');assert.equal(select.options[2],options[2]);
 c.parkFontOptions(select);assert.equal(select.options.length,3);
});
test('programmatic selection remains valid while closed, including follow-global and unavailable fonts',()=>{
 const {context:c,dialog,select}=setup();c.parkFontOptions(select);c.selectFont(select,'@global');assert.equal(select.value,'@global');assert.equal(select.options.length,1);
 c.selectFont(select,'localfont-aaaaaaaaaaaaaaaaaaaaaaaa');assert.equal(select.value,'localfont-aaaaaaaaaaaaaaaaaaaaaaaa');dialog.open=true;c.restoreFontOptions(select);
 assert.equal(select.options.length,4);assert.match(select.options[3].text,/Unavailable/);
});
test('a rescan replaces old parked options instead of restoring stale families',()=>{
 const {context:c,select}=setup();c.parkFontOptions(select);const fresh=[{value:'Junicode'},{value:'sans-serif'}];select.options=fresh;select.value='Junicode';c.restoreFontOptions(select);
 assert.equal(select.options,fresh);assert.equal(select.value,'Junicode');c.parkFontOptions(select);c.restoreFontOptions(select);assert.deepEqual(select.options,fresh);
});
