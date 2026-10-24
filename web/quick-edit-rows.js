// Compact views write through to the original draft controls; stable identities stay intact.
function createQuickEditRows(active,requiredTypes){
 const components=new Map(),tables=new Map(),usages=new Map(),extraTypes=new Set();let refreshing=false,drag=null;
 const changed=()=>{lexemeDirty=true;};
 function command(text,title,action){const b=document.createElement('button');b.type='button';b.textContent=text;b.title=title;b.setAttribute('aria-label',title);b.onclick=action;return b;}
 function field(label,cls=''){const input=document.createElement('input');input.className='quick-row-input '+cls;input.setAttribute('aria-label',label);input.title=label;return input;}
 function setValue(input,value){if(input.value!==value)input.value=value;}
 function write(source,value){source.value=value;source.dispatchEvent(new Event('input',{bubbles:true}));}
 function move(source,target,where){if(source===target||source.parentElement!==target.parentElement)return false;target[where](source);changed();return true;}
 function finishMove(row,source,done){const parent=row.parentElement;done();[...parent.children].find(r=>(r.quickSource||r)===source)?.querySelector('.quick-row-grip')?.focus({preventScroll:true});}
 function cancelDrag(){if(!drag)return;const d=drag;drag=null;d.row.classList.remove('quick-row-dragging');if(d.handle.hasPointerCapture?.(d.pointer))d.handle.releasePointerCapture(d.pointer);document.querySelectorAll('[data-quick-drop]').forEach(r=>delete r.dataset.quickDrop);}
 function grip(row,source,done,label){
  const b=command('⠿',label+'；拖动排序，方向键调整',()=>{});b.className='quick-row-grip';
  b.onkeydown=e=>{if(!['ArrowUp','ArrowDown'].includes(e.key))return;e.preventDefault();const target=e.key==='ArrowUp'?row.previousElementSibling:row.nextElementSibling;if(target&&move(source,target.quickSource||target,e.key==='ArrowUp'?'before':'after')){if(source!==row)target[e.key==='ArrowUp'?'before':'after'](row);finishMove(row,source,done);}};
  b.onpointerdown=e=>{if(e.button!==0)return;e.preventDefault();cancelDrag();document.querySelectorAll('#lexeme-quick-editor .ws-registry-results').forEach(r=>r.hidden=true);drag={row,source,done,handle:b,pointer:e.pointerId,x:e.clientX,y:e.clientY};b.setPointerCapture(e.pointerId);b.focus({preventScroll:true});};return b;
 }
 function pointerMove(e){
  if(!drag||e.pointerId!==drag.pointer)return;const d=drag;if(!d.moved&&Math.hypot(e.clientX-d.x,e.clientY-d.y)<5)return;d.moved=true;d.row.classList.add('quick-row-dragging');document.querySelectorAll('[data-quick-drop]').forEach(r=>delete r.dataset.quickDrop);
  const target=document.elementFromPoint(e.clientX,e.clientY)?.closest('.quick-sort-row');d.target=null;
  if(target&&target!==d.row&&target.parentElement===d.row.parentElement){d.target=target;d.where=e.clientY<target.getBoundingClientRect().top+target.getBoundingClientRect().height/2?'before':'after';target.dataset.quickDrop=d.where;}
  const area=d.row.closest('.dialog-content');if(area){const box=area.getBoundingClientRect();if(e.clientY<box.top+35)area.scrollTop-=14;else if(e.clientY>box.bottom-35)area.scrollTop+=14;}
 }
 function pointerUp(e){if(!drag||e.pointerId!==drag.pointer)return;const d=drag;if(d.moved&&d.target&&move(d.source,d.target.quickSource||d.target,d.where)){if(d.row!==d.source)d.target[d.where](d.row);finishMove(d.row,d.source,d.done);}cancelDrag();}
 document.addEventListener('pointermove',pointerMove);document.addEventListener('pointerup',pointerUp);document.addEventListener('pointercancel',cancelDrag);document.addEventListener('keydown',e=>{if(e.key==='Escape'&&drag){e.preventDefault();e.stopImmediatePropagation();cancelDrag();}},true);
 function mountControl(control,host,moved){const marker=document.createComment('full editor control');control.before(marker);moved.push({control,marker});host.append(control);}
 function removeComponentView(row,view){for(const {control,marker} of view.moved)if(marker.parentNode)marker.replaceWith(control);const result=row.querySelector('.ws-registry-results');if(result)row.querySelector('.ws-registry-picker').append(result);view.search.innerHTML=view.searchHTML;view.search.removeAttribute('title');row.classList.remove('quick-component-row','quick-sort-row');view.line.remove();components.delete(row);}
 function componentView(row){
  let v=components.get(row);if(v)return v;
  const line=document.createElement('div');line.className='quick-component-line';line.style.cssText=languageTypographyCSS(JSON.parse(languageList.find(l=>l.id===$('lexeme-language').value)?.metadata||'{}'));const searchCell=document.createElement('div');searchCell.className='quick-component-search';const moved=[];
  const query=row.querySelector('.ws-registry-query'),search=row.querySelector('.ws-registry-search'),target=row.querySelector('.ws-registry-target'),searchHTML=search.innerHTML;
  for(const el of [query,search,target,row.querySelector('.ws-registry-form')])mountControl(el,searchCell,moved);
  search.innerHTML='<svg viewBox="0 0 20 20" aria-hidden="true"><circle cx="8" cy="8" r="5.5"/><path d="m12 12 5 5"/></svg>';search.title='搜索已有语素';search.setAttribute('aria-label','搜索已有语素');
  const form=field('语素形式','quick-component-form'),readings=field('语素读音；多个读音用分号分隔','quick-component-readings'),gloss=field('语素释义','quick-component-gloss'),writings=document.createElement('div');writings.className='quick-component-writings';
  form.oninput=()=>{write(row.querySelector('[data-ws="form"]'),form.value);wsParents(row.parentElement);};
  readings.oninput=()=>write(row.querySelector('[data-ws="readings"]'),readings.value.split(/[;；\r\n]+/).map(s=>s.trim()).filter(Boolean).join('\n'));
  gloss.oninput=()=>write(row.querySelector('[data-ws="gloss"]'),gloss.value);
  const handle=grip(row,row,()=>wsParents(row.parentElement),'语素'),remove=command('×','移除此语素组分',()=>{row.querySelector(':scope > .ws-row-tools [data-ws-remove]').click();refresh();});remove.className='quick-row-remove';
  line.append(handle,searchCell,form,readings,writings,gloss,remove);row.append(line);row.classList.add('quick-component-row','quick-sort-row');
  v={line,search,searchHTML,target,moved,form,readings,gloss,writings,writingInputs:new Map()};components.set(row,v);return v;
 }
 function componentTable(analysis,types){
  let t=tables.get(analysis);if(!t){const list=analysis.querySelector('.ws-components'),marker=document.createComment('full editor component list'),wrap=document.createElement('div'),sheet=document.createElement('div'),head=document.createElement('div');wrap.className='quick-component-table';sheet.className='quick-component-sheet';head.className='quick-component-head';list.before(marker);marker.after(wrap);wrap.append(sheet);sheet.append(head,list);const add=document.createElement('select');add.className='quick-writing-add';add.setAttribute('aria-label','添加语素书写栏');add.title='添加本次快捷编辑的书写栏';add.onchange=()=>{if(add.value){extraTypes.add(add.value);refresh();}};analysis.querySelector('.ws-add-component').after(add);t={list,marker,wrap,sheet,head,add};tables.set(analysis,t);}
  t.add.innerHTML='<option value="">＋书写栏</option>'+writingTypes.filter(w=>!types.includes(w.id)).map(w=>`<option value="${esc(w.id)}">${esc(w.name)}</option>`).join('');t.add.hidden=types.length>=writingTypes.length;t.add.value='';
  t.sheet.style.setProperty('--quick-component-columns','24px minmax(260px,1.5fr) minmax(100px,1fr) minmax(105px,1fr) '+types.map(()=>'minmax(100px,1fr)').join(' ')+' minmax(110px,1fr) 26px');
  t.sheet.style.setProperty('--quick-component-width',(24+260+100+105+types.length*100+110+26+8*(5+types.length))+'px');
  t.head.replaceChildren(...['','关联语素','形式','读音',...types.map(id=>writingTypes.find(w=>w.id===id)?.name||'书写形式'),'释义',''].map(label=>{const s=document.createElement('span');s.textContent=s.title=label;return s;}));return t;
 }
 function refreshComponents(){
  for(const [row,v] of components)if(!row.isConnected)removeComponentView(row,v);
  for(const [analysis,t] of tables)if(!analysis.isConnected){if(t.marker.parentNode)t.marker.replaceWith(t.list);t.wrap.remove();t.add.remove();tables.delete(analysis);}
  const rows=[...$('ws-analyses').querySelectorAll('.ws-component')],types=[...new Set([...requiredTypes(),...extraTypes,...rows.flatMap(r=>[...wsReadWritings(r.querySelector('.ws-writings')),...(r.registryRecord?.body.writings||[])].map(w=>w.type_id))])];
  for(const analysis of $('ws-analyses').children)componentTable(analysis,types);
  for(const row of rows){
   const v=componentView(row),linked=!!row.registryRecord;setValue(v.form,wsVal(row,'form'));setValue(v.readings,wsVal(row,'readings').split('\n').join('；'));setValue(v.gloss,wsVal(row,'gloss')||(linked?wsRegistryGlosses(row.registryRecord).join(' / '):''));
   for(const input of [v.form,v.readings,v.gloss]){input.readOnly=linked;input.title=input.value||input.getAttribute('aria-label');}
   v.target.title=v.target.selectedOptions[0]?.textContent||'选择语素关联方式';
   const actual=wsReadWritings(row.querySelector('.ws-writings')),values=actual.length?actual:row.registryRecord?.body.writings||[];
   for(const [id,input] of v.writingInputs)if(!types.includes(id)){input.remove();v.writingInputs.delete(id);}
   for(const id of types){let input=v.writingInputs.get(id);if(!input){input=field(writingTypes.find(w=>w.id===id)?.name||'语素书写形式');input.oninput=()=>{const el=row.querySelector('.ws-writings'),current=wsReadWritings(el).filter(w=>w.type_id!==id);if(input.value.trim())current.push({type_id:id,text:input.value});wsWritings(el,current);changed();};v.writingInputs.set(id,input);}v.writings.append(input);input.style.fontFamily=cssFont(writingTypes.find(w=>w.id===id)?.font||'Junicode');setValue(input,values.find(w=>w.type_id===id)?.text||'');input.readOnly=linked;input.title=input.value||input.getAttribute('aria-label');}
   v.writings.style.setProperty('--quick-writing-columns',String(types.length));
   const results=row.querySelector('.ws-registry-results');if(results)v.line.append(results);
  }
 }
 function refreshUsages(){
  for(const [usage,list] of usages)if(!usage.isConnected){list.remove();usages.delete(usage);}
  for(const usage of $('lexeme-usages').children){
   let list=usages.get(usage);if(!list){list=document.createElement('div');list.className='quick-sense-list';usage.append(list);usages.set(usage,list);}usage.classList.add('quick-usage-row');
   const senses=[...usage.querySelector('.sense-editors').children],ui=[...$('lexeme-usages').children].indexOf(usage)+1,sourcePos=usage.querySelector('.usage-pos'),sources=senses.length?senses:[null];
   if(list.quickPos===sourcePos&&list.quickOptions===sourcePos.innerHTML&&list.quickPosition===ui&&list.children.length===sources.length&&sources.every((sense,i)=>list.children[i].quickSource===sense)){
    for(const r of list.children){setValue(r.querySelector('.quick-sense-pos'),sourcePos.value);if(r.quickSource)setValue(r.querySelector('.quick-sense-gloss'),r.quickSource.querySelector('.sense-short').value);}continue;
   }
   list.quickPos=sourcePos;list.quickOptions=sourcePos.innerHTML;list.quickPosition=ui;list.replaceChildren();
   for(const [i,sense] of (senses.length?senses:[null]).entries()){
    const row=document.createElement('div');row.className='quick-sense-row quick-sort-row';row.quickSource=sense;
    const label=document.createElement('span');label.className='quick-sense-number';label.textContent=ui+'.'+(i+1);
    const source=usage.querySelector('.usage-pos'),pos=source.cloneNode(true);pos.className='quick-sense-pos';pos.removeAttribute('id');pos.setAttribute('aria-label','词类用法 '+ui);pos.title='修改此词类用法下的全部义项';pos.value=source.value;pos.onchange=()=>{source.value=pos.value;source.dispatchEvent(new Event('change',{bubbles:true}));for(const select of list.querySelectorAll('.quick-sense-pos'))select.value=pos.value;};
    const gloss=field('义项 '+label.textContent+' 简短标注释义','quick-sense-gloss');gloss.placeholder='简短标注释义';gloss.value=sense?.querySelector('.sense-short').value||'';gloss.oninput=()=>{if(!sense)return;write(sense.querySelector('.sense-short'),gloss.value);};if(!sense)gloss.disabled=true;
    const tools=document.createElement('div');tools.className='quick-sense-tools';tools.append(command('+','添加本词类义项',()=>{usage.querySelector('.add-sense').click();refresh();}),command('×','移除义项 '+label.textContent,()=>{if(sense)sense.querySelector('.remove-sense').click();refresh();}));
    if(i===0)tools.append(command('类×','移除此词类用法',()=>{usage.querySelector('.remove-usage').click();refresh();}));
    row.append(sense?grip(row,sense,refreshUsages,'义项 '+label.textContent):document.createElement('span'),label,pos,gloss,tools);list.append(row);
   }
  }
 }
 function refresh(){if(!active()||refreshing)return;refreshing=true;try{refreshComponents();refreshUsages();}finally{refreshing=false;}}
 function clear(){cancelDrag();for(const [row,v] of components)removeComponentView(row,v);for(const t of tables.values()){if(t.marker.parentNode)t.marker.replaceWith(t.list);t.wrap.remove();t.add.remove();}tables.clear();extraTypes.clear();for(const [usage,list] of usages){usage.classList.remove('quick-usage-row');list.remove();}usages.clear();}
 const set=wsSetRegistryRecord,release=wsReleaseRegistry,search=wsSearchRegistry,fill=wsFill;
 wsSetRegistryRecord=function(...args){set(...args);refresh();};wsReleaseRegistry=function(...args){release(...args);refresh();};
 wsSearchRegistry=async function(...args){try{return await search(...args);}finally{refresh();}};
 wsFill=function(...args){fill(...args);refresh();};
 document.addEventListener('click',e=>{if(active()&&e.target.closest('.ws-row-tools'))refresh();});
 return {refresh,clear};
}
