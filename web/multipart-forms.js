/* One compact editor for a base realization and each of its registered forms. */
(()=>{
 'use strict';
 const text=p=>typeof p==='string'?p:(p.left||'')+p.text+(p.right||'');
 const format=parts=>parts.map(text).join('…');
 const infer=(value,body={})=>body.form_parts?.length?body.form_parts.map(text):
  (body.entry_type==='circumfix'||body.entry_type==='affix'&&body.affix_position==='circumfix')&&value.includes('…')?value.split('…'):[];
 function reconcile(value,parts){
  if(value===format(parts))return parts;
  const next=value.split('…');
  if(next.length!==parts.length||next.some(p=>!p.trim()))throw Error((globalThis.CorporiumI18n?.f("14a2783178744b",()=>[])??'修改多部分形式须保留各部分；请返回形式编辑栏核对。'));
  return next;
 }
 if(typeof module!=='undefined'&&module.exports){module.exports={text,format,infer,reconcile};return;}
 const widgets=new WeakMap();
 function mount(input,body={},options={}){
  let widget=widgets.get(input);
  if(widget){widget.load(body,options);return widget;}
  const oldLabel=input.parentElement,host=document.createElement('div');host.className='multipart-form-editor';
  const title=document.createElement('div');title.className='multipart-heading';
  const caption=document.createElement('label');caption.htmlFor=input.id;caption.textContent=options.title||oldLabel.firstChild?.textContent?.trim()||(globalThis.CorporiumI18n?.f("a9fb08c3edb94e",()=>[])??'形式');
  const choice=document.createElement('label');choice.className='multipart-toggle';
  const toggle=document.createElement('input');toggle.type='checkbox';toggle.setAttribute('aria-label',(globalThis.CorporiumI18n?.f("dfdd3b5dc9f123",()=>[options.title||caption.textContent])??(options.title||caption.textContent)+'：不连续多部分形式'));
  choice.append(toggle,document.createTextNode((globalThis.CorporiumI18n?.f("b580029845ce6e",()=>[])??'不连续多部分形式')));title.append(caption,choice);
  const rows=document.createElement('div');rows.className='multipart-parts';
  const hint=document.createElement('small');hint.className='multipart-hint';hint.hidden=true;
  oldLabel.replaceWith(host);host.append(title,input,rows,hint);
  const required=input.required;let draft=[],forced=0;
  const changed=()=>input.dispatchEvent(new Event('input',{bubbles:true}));
  function values(){return [...rows.querySelectorAll('input')].map(e=>e.value);}
  function sync(){if(toggle.checked)input.value=format(values());}
  function draw(){
   rows.replaceChildren();input.hidden=toggle.checked;input.required=required&&!toggle.checked;
   rows.hidden=!toggle.checked;toggle.disabled=!!forced;
   hint.hidden=!toggle.checked;hint.textContent=forced?(draft.length>2?(globalThis.CorporiumI18n?.f("8c5edfa0a6113f",()=>[])??'环缀须为两个部分，请先移除多余部分；现有内容已保留。'):(globalThis.CorporiumI18n?.f("a5dc5b89ab7ab4",()=>[])??'前部- … -后部；两个部分都须填写。')):(globalThis.CorporiumI18n?.f("b5b5ebd410c7e3",()=>[])??'按出现顺序填写；首尾 -、=、+ 表示与相邻成分的连接位置。');
   if(!toggle.checked)return;
   draft.forEach((value,i)=>{
    const row=document.createElement('div');row.className='multipart-part';
    const field=document.createElement('input');field.value=value;field.required=true;field.className='dictionary-wordform';
    field.setAttribute('aria-label',forced&&draft.length===2?(i?(globalThis.CorporiumI18n?.f("70bca252abf12f",()=>[])??'环缀后部'):(globalThis.CorporiumI18n?.f("9fe5729217b7a3",()=>[])??'环缀前部')):(globalThis.CorporiumI18n?.f("63fed7cc5dd6f3",()=>[i+1])??'形式第 '+(i+1)+' 部分'));
    field.placeholder=forced&&draft.length===2?(i?(globalThis.CorporiumI18n?.f("b3d42c0ba00022",()=>[])??'-后部'):(globalThis.CorporiumI18n?.f("6091c944836829",()=>[])??'前部-')):(globalThis.CorporiumI18n?.f("eacd7e6581ea34",()=>[i+1])??'第 '+(i+1)+' 部分');
    field.oninput=()=>{draft=values();sync();changed();};row.append(field);
    if(!forced||draft.length>2)for(const [label,action] of [['−','remove'],['＋','add']]){
     const button=document.createElement('button');button.type='button';button.textContent=label;
     button.setAttribute('aria-label',action==='add'?(globalThis.CorporiumI18n?.f("bce141ba886ddf",()=>[])??'在此后添加形式部分'):(globalThis.CorporiumI18n?.f("c203aeb184810c",()=>[])??'移除此形式部分'));
     button.disabled=action==='add'?!!forced||draft.length>=12:draft.length<=2;
     button.onclick=()=>{draft=values();if(action==='add')draft.splice(i+1,0,'');else draft.splice(i,1);draw();sync();changed();rows.querySelectorAll('input')[Math.min(i+(action==='add'?1:0),draft.length-1)]?.focus();};
     row.append(button);
    }
    rows.append(row);
   });sync();
  }
  toggle.onchange=()=>{
   if(toggle.checked){if(!draft.length)draft=input.value.includes('…')?input.value.split('…'):[input.value,''];}
   else{draft=values();input.value=format(draft);hint.hidden=false;hint.textContent=(globalThis.CorporiumI18n?.f("8e6ce1a944c198",()=>[])??'各部分已保留，请将词形编辑为一个连续形式后保存。');}
   draw();changed();
  };
  widget={
   load(body={},options={}){
    forced=options.forced||0;draft=infer(input.value,body);toggle.checked=!!draft.length||!!forced;
    if(forced&&!draft.length)draft=[input.value,''];
    if(toggle.checked&&draft.length<2)draft.push('');draw();
   },
   force(count){const current=toggle.checked?values():[];forced=count;toggle.checked=!!count||toggle.checked;draft=current.length?current:(count?[input.value,'']:draft);draw();},
   read(){
    if(!toggle.checked){if(draft.length&&input.value.includes('…'))throw Error((globalThis.CorporiumI18n?.f("9bafd9769ea2ab",()=>[])??'请先将词形合并为一个连续形式，或重新勾选不连续多部分形式。'));return [];}
    const current=values(),updated=reconcile(input.value,current);
    if(updated!==current){draft=updated;draw();}
    const parts=values().map(s=>s.trim());
    if(parts.length<2||parts.length>12||parts.some(s=>!s||!s.replace(/^[-=+]|[-=+]$/g,'').trim()))throw Error((globalThis.CorporiumI18n?.f("2a82739586b75c",()=>[])??'请填写全部形式部分，或移除空白部分。'));
    if(forced&&parts.length!==2)throw Error((globalThis.CorporiumI18n?.f("afa51a1e9f973d",()=>[])??'环缀须保留前、后两个形式部分。'));
    sync();return parts;
   },host
  };
  widgets.set(input,widget);widget.load(body,options);return widget;
 }
 const get=input=>widgets.get(input);
 window.CorporiumMultipart={mount,get,format,infer};
 const oldOpen=openLexemeEditor;
 openLexemeEditor=async function(x=null,...args){await oldOpen(x,...args);mount($('lexeme-headword'),x?.body||{},{title:(globalThis.CorporiumI18n?.f("f55b97eed43dac",()=>[])??'词形')});};
 const oldFill=fillMorphEntry;
 fillMorphEntry=function(body){oldFill(body);mount($('lexeme-headword'),body,{title:(globalThis.CorporiumI18n?.f("e17cf1403e9faf",()=>[])??'词形')});};
 const oldRead=readMorphEntry;
 readMorphEntry=function(){return {...oldRead(),form_parts:get($('lexeme-headword'))?.read()||[]};};
 const oldAdd=addVariant;
 addVariant=function(v={}){oldAdd(v);mount($('lexeme-variants').lastElementChild.querySelector('.variant-form'),v,{title:(globalThis.CorporiumI18n?.f("c78af3cb818638",()=>[])??'形式')});};
 const oldForm=readMorphForm;
 readMorphForm=function(row){return {...oldForm(row),form_parts:get(row.querySelector('.variant-form'))?.read()||[]};};
})();
