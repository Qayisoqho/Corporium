const inlineDrafts=new Map();
const inlineOpening=new Map();
// A hidden draft belongs to the workspace where the user last edited it.
for(const event of ['pointerdown','focusin'])document.addEventListener(event,e=>{const card=e.target.closest('.editable-example'),d=inlineDrafts.get(card?.dataset.exampleKey);if(d)d.workspace=workspace;},true);
let inlineDrag=null;
// Pointer sorting also works on read-only input surfaces and in embedded WebViews.
let inlinePointer=null,inlinePointerMoved=false;
document.addEventListener('pointerdown',e=>{
 const slot=e.target.closest('[data-inline-slot]'),card=slot?.closest('.editable-example'),d=inlineDrafts.get(card?.dataset.exampleKey);
 if(!d?.dragEnabled||d.saving||e.button!==0)return;
 inlinePointer={key:card.dataset.exampleKey,id:slot.dataset.inlineSlot,x:e.clientX,y:e.clientY,pointer:e.pointerId,slot};inlinePointerMoved=false;
 e.preventDefault();slot.setPointerCapture(e.pointerId);
});
document.addEventListener('pointermove',e=>{
 const p=inlinePointer;if(!p||e.pointerId!==p.pointer)return;
 if(Math.hypot(e.clientX-p.x,e.clientY-p.y)<5&&!inlinePointerMoved)return;
 inlinePointerMoved=true;const d=inlineDrafts.get(p.key);if(!d)return;
 if(!d.selectedSlots?.has(p.id))d.selectedSlots=new Set([p.id]);
 const slot=document.elementFromPoint(e.clientX,e.clientY)?.closest('[data-inline-slot]');
 for(const n of document.querySelectorAll('[data-slot-drop]'))delete n.dataset.slotDrop;
 if(slot?.closest('.editable-example')?.dataset.exampleKey!==p.key){p.target=null;return;}
 const box=slot.getBoundingClientRect();p.target=slot.dataset.inlineSlot;p.after=e.clientX>box.left+box.width/2;slot.dataset.slotDrop=p.after?'after':'before';
});
document.addEventListener('pointerup',e=>{
 const p=inlinePointer;if(!p||e.pointerId!==p.pointer)return;inlinePointer=null;
 if(p.slot.hasPointerCapture(e.pointerId))p.slot.releasePointerCapture(e.pointerId);
 const d=inlineDrafts.get(p.key);
 if(inlinePointerMoved&&p.target&&d&&!d.saving){const before=d.words.map(w=>w.id),after=CorporiumOrder.move(before,[...d.selectedSlots],p.target,p.after);if(after.some((id,i)=>id!==before[i])){const indices=new Map(before.map((id,i)=>[id,i]));d.words=after.map(id=>d.words[indices.get(id)]);d.body.words=after.map(id=>d.body.words[indices.get(id)]);d.dirty=true;repaintInline(p.key);}}
 for(const n of document.querySelectorAll('[data-slot-drop]'))delete n.dataset.slotDrop;
 setTimeout(()=>inlinePointerMoved=false,0);
});
document.addEventListener('pointercancel',()=>{inlinePointer=null;inlinePointerMoved=false;for(const n of document.querySelectorAll('[data-slot-drop]'))delete n.dataset.slotDrop;});
document.addEventListener('change',e=>{if(!e.target.matches('[data-slot-drag]'))return;const card=e.target.closest('.editable-example'),d=inlineDrafts.get(card.dataset.exampleKey);if(!d||d.saving)return;d.dragEnabled=e.target.checked;d.selectedSlots=new Set(d.selectedSlot?[d.selectedSlot]:[]);inlineSelection(card,d);});
document.addEventListener('click',e=>{
 const slot=e.target.closest('[data-inline-slot]'),card=slot?.closest('.editable-example'),d=inlineDrafts.get(card?.dataset.exampleKey);if(!d?.dragEnabled||d.saving)return;
 e.preventDefault();e.stopImmediatePropagation();if(inlinePointerMoved)return;const id=slot.dataset.inlineSlot;d.selectedSlots??=new Set();
 if(e.shiftKey&&d.selectedSlot){const ids=d.words.map(w=>w.id),a=ids.indexOf(d.selectedSlot),b=ids.indexOf(id);d.selectedSlots=new Set(ids.slice(Math.min(a,b),Math.max(a,b)+1));}
 else if(e.ctrlKey||e.metaKey){d.selectedSlots.has(id)?d.selectedSlots.delete(id):d.selectedSlots.add(id);d.selectedSlot=id;}
 else{d.selectedSlots=new Set([id]);d.selectedSlot=id;}
 inlineSelection(card,d);
},true);
document.addEventListener('dragstart',e=>{const slot=e.target.closest('[data-inline-slot]'),card=slot?.closest('.editable-example'),d=inlineDrafts.get(card?.dataset.exampleKey);if(!d?.dragEnabled||d.saving)return;const id=slot.dataset.inlineSlot;if(!d.selectedSlots?.has(id))d.selectedSlots=new Set([id]);d.selectedSlot=id;inlineSelection(card,d);inlineDrag={key:card.dataset.exampleKey,ids:[...d.selectedSlots]};e.dataTransfer.effectAllowed='move';e.dataTransfer.setData('text/plain',inlineDrag.ids.join(','));});
document.addEventListener('dragover',e=>{const slot=e.target.closest('[data-inline-slot]'),card=slot?.closest('.editable-example');if(!inlineDrag||card?.dataset.exampleKey!==inlineDrag.key)return;e.preventDefault();e.dataTransfer.dropEffect='move';for(const n of card.querySelectorAll('[data-slot-drop]'))delete n.dataset.slotDrop;const box=slot.getBoundingClientRect();slot.dataset.slotDrop=e.clientX>box.left+box.width/2?'after':'before';});
document.addEventListener('drop',e=>{
 const slot=e.target.closest('[data-inline-slot]'),card=slot?.closest('.editable-example');if(!inlineDrag||card?.dataset.exampleKey!==inlineDrag.key)return;e.preventDefault();const d=inlineDrafts.get(inlineDrag.key);if(!d||d.saving)return;
 const before=d.words.map(w=>w.id),box=slot.getBoundingClientRect(),after=CorporiumOrder.move(before,inlineDrag.ids,slot.dataset.inlineSlot,e.clientX>box.left+box.width/2);
 if(after.some((id,i)=>id!==before[i])){const positions=new Map(before.map((id,i)=>[id,i]));d.words=after.map(id=>d.words[positions.get(id)]);d.body.words=after.map(id=>d.body.words[positions.get(id)]);d.dirty=true;repaintInline(inlineDrag.key);}
 inlineDrag=null;for(const n of document.querySelectorAll('[data-slot-drop]'))delete n.dataset.slotDrop;
});
document.addEventListener('dragend',()=>{inlineDrag=null;for(const n of document.querySelectorAll('[data-slot-drop]'))delete n.dataset.slotDrop;});
function fitInlineTextareas(fields){
 const visible=[...fields].filter(field=>field.isConnected&&field.getClientRects().length);
 for(const field of visible)field.style.height='auto';
 const heights=visible.map(field=>field.scrollHeight+2);
 visible.forEach((field,i)=>{field.style.height=heights[i]+'px';});
}
function fitInlineTextarea(field){fitInlineTextareas([field]);}
document.addEventListener('input',e=>{if(e.target.matches('.editable-example textarea'))fitInlineTextarea(e.target);});
document.addEventListener('toggle',e=>{if(e.target.matches('.example-notes')&&e.target.open)fitInlineTextareas(e.target.querySelectorAll('textarea'));},true);
new MutationObserver(records=>{const fields=new Set();for(const record of records)for(const node of record.addedNodes){if(node.nodeType===1){if(node.matches('.editable-example textarea'))fields.add(node);node.querySelectorAll('.editable-example textarea').forEach(el=>fields.add(el));if(node.closest('.editable-example'))node.querySelectorAll('textarea').forEach(el=>fields.add(el));}}fitInlineTextareas(fields);}).observe(document.body,{subtree:true,childList:true});
const inlineKey=(kind,id)=>kind+':'+id;
const inlineWidth=(value,compact=false)=>Math.max(compact?1:3,Math.min(40,[...value].reduce((n,c)=>n+(c.codePointAt(0)>255?2:1),compact?0:1)));
const compactWord=w=>phonologicalBoundary(w.form)||!!(w.punctuation&&w.punctuation_form===w.form);
function inlineWordParts(w,key){return compactWord(w)?[w[key]]:glossEditParts(w[key],key==='gloss');}
function inlineWordLayout(w){
 const rows={form:inlineWordParts(w,'form'),gloss:inlineWordParts(w,'gloss')};
 function chunks(parts){const out=[[]];parts.forEach((value,i)=>{if(i%2&&'-＝=+~'.includes(value)){out.push(i,[]);}else out[out.length-1].push(i);});return out;}
 const f=chunks(rows.form),g=chunks(rows.gloss),layout={form:[],gloss:[],columns:0};
 const aligned=f.length===g.length&&f.every((part,i)=>Array.isArray(part)||rows.form[part]===rows.gloss[g[i]]);
 if(!aligned){for(const key of ['form','gloss'])layout[key]=rows[key].map((_,i)=>({column:i+1,span:1}));layout.columns=Math.max(rows.form.length,rows.gloss.length);return layout;}
 let column=1;
 f.forEach((part,i)=>{const width=Array.isArray(part)?Math.max(part.length,g[i].length):1;
  for(const [key,indices] of [['form',part],['gloss',g[i]]])if(Array.isArray(indices))indices.forEach((index,j)=>{layout[key][index]={column:column+j,span:j===indices.length-1?width-j:1};});else layout[key][indices]={column,span:1};
  column+=width;
 });layout.columns=column-1;return layout;
}
function renderEditableExample(e,kind,id){
  const libraryNumber=kind==='independent'&&Number.isSafeInteger(e.library_number)?` data-library-number="${e.library_number}"`:'';
  if(briefMode&&!inlineDrafts.has(inlineKey(kind,id)))return `<section class="editable-example"${libraryNumber} data-example-kind="${esc(kind)}" data-example-id="${esc(id)}">${briefBody(e,kind)}<div class="inline-tools">${window.CorporiumCodes?.tools(e)||''}</div></section>`;
  const key=inlineKey(kind,id),d=inlineDrafts.get(key);
  return `<section class="editable-example"${libraryNumber} data-example-key="${esc(key)}" data-example-kind="${esc(kind)}" data-example-id="${esc(id)}">${d?inlineStyledFields(d):(globalThis.CorporiumI18n?.f("3407024b6efc16",()=>[renderBody(e,kind),window.CorporiumCodes?.tools(e)||'',e.notes?(globalThis.CorporiumI18n?.f("e63dee05bdeb2f",()=>[])??' · 已填写'):'',esc(e.notes||(globalThis.CorporiumI18n?.f("087910b2197bcc",()=>[])??'暂无备注'))])??`${renderBody(e,kind)}<div class="inline-tools"><button type="button" data-inline-start>编辑标注</button><button type="button" data-punctuation-single>应用自动识别标点</button>${window.CorporiumCodes?.tools(e)||''}</div><details class="example-notes"><summary>备注${e.notes?' · 已填写':''}</summary><div class="preserve-lines">${esc(e.notes||'暂无备注')}</div><button type="button" data-inline-start="notes">编辑备注</button></details>`)}</section>`;
}
function inlineFields(d){
 const b=d.body,values=new Map(d.cells.map(c=>[c.unit_id+'|'+c.layer_id,c.value]));
 function parts(w,i,key){const layout=inlineWordLayout(w);return inlineWordParts(w,key).map((v,j)=>{const p=layout[key][j],style=`grid-column:${p.column} / span ${p.span}`;return j%2?`<span style="${style}">${esc(v)}</span>`:((globalThis.CorporiumI18n?.f("5f467cabdd4021",()=>[key,i,key,j,esc(v),i+1,key==='form'?(globalThis.CorporiumI18n?.f("c12f3d5ac78da5",()=>[])??'语素'):(globalThis.CorporiumI18n?.f("a22e2bf278f503",()=>[])??'标注'),Math.floor(j/2)+1,inlineWidth(v,compactWord(w))])??`<input class="inline-piece ${key}" data-word="${i}" data-field="${key}" data-part="${j}" value="${esc(v)}" aria-label="第 ${i+1} 词 ${key==='form'?'语素':'标注'} ${Math.floor(j/2)+1}" size="${inlineWidth(v,compactWord(w))}">`).replace('<input ',`<input style="${style}" `));}).join('');}
 return (globalThis.CorporiumI18n?.f("4044150baed104",()=>[window.CorporiumGrammaticality?.editor(d)||'',d.saving?'disabled':'',d.saving?'disabled':'',esc(b.ipa),inlineSentenceLayers(d,"ipa"),inlineSlotTools(d),b.words.map((w,i)=>`<div class="word ${compactWord(w)?'compact-symbol':''}" style="--inline-columns:${inlineWordLayout(w).columns};--symbol-columns:${Math.max(inlineWidth(w.form,true),inlineWidth(w.gloss,true))}" data-inline-slot="${esc(d.words[i].id)}"><div class="inline-parts">${parts(w,i,'form')}</div><div class="inline-parts">${parts(w,i,'gloss')}</div>${d.layers.filter(l=>(l.anchor||'word')==='word').map(l=>(globalThis.CorporiumI18n?.f("e349012e00379c",()=>[esc(validFont(l.font)?l.font:'Junicode'),(l.size||100)/100,['bold','bolditalic'].includes(l.style)?700:400,['italic','bolditalic'].includes(l.style)?'italic':'normal',l.style==='small-caps'?'small-caps':'normal',esc(l.name),l.visible?'':(globalThis.CorporiumI18n?.f("485c7a885c224f",()=>[])??'（隐藏层）'),esc(l.id),esc(d.words[i].id),i+1,esc(l.name),esc(values.get(d.words[i].id+'|'+l.id)||'')])??`<label class="extra-layer" style="font-family:'${esc(validFont(l.font)?l.font:'Junicode')}';--layer-scale:${(l.size||100)/100};font-size:calc(.9375rem * var(--layer-scale));font-weight:${['bold','bolditalic'].includes(l.style)?700:400};font-style:${['italic','bolditalic'].includes(l.style)?'italic':'normal'};font-variant-caps:${l.style==='small-caps'?'small-caps':'normal'}"><small>${esc(l.name)}${l.visible?'':'（隐藏层）'}</small><input data-inline-layer="${esc(l.id)}" data-inline-unit="${esc(d.words[i].id)}" aria-label="第 ${i+1} 词 ${esc(l.name)}" value="${esc(values.get(d.words[i].id+'|'+l.id)||'')}"></label>`)).join('')}</div>`).join(''),esc(b.translation),inlineSentenceLayers(d,"translation"),d.notesOpen?'open':'',esc(b.notes||''),d.orphaned.length?(globalThis.CorporiumI18n?.f("bbff40d9d02cac",()=>[])??'<p class="warning">另有旧标注待核对，请保存后打开“附加标注”处理。</p>'):'',esc(d.error===d.errorShown?'':d.error||'')])??`<div class="inline-tools"><strong>编辑标注</strong>${window.CorporiumGrammaticality?.editor(d)||''}<button type="button" data-inline-save ${d.saving?'disabled':''}>保存</button><button type="button" data-inline-cancel ${d.saving?'disabled':''}>取消</button><small>已关联标注的手动修改仅用于本句，可在“标注来源”恢复跟随。末尾按 Tab 新增词格；无标注、无分析或关联的明确标点在保存时自动识别，疑似项可保存后预览确认。</small></div><label>IPA<textarea rows="1" class="ipa" data-inline-field="ipa">${esc(b.ipa)}</textarea></label>${inlineSentenceLayers(d,"ipa")}${inlineSlotTools(d)}<div class="words inline-words">${b.words.map((w,i)=>`<div class="word ${compactWord(w)?'compact-symbol':''}" style="--inline-columns:${inlineWordLayout(w).columns};--symbol-columns:${Math.max(inlineWidth(w.form,true),inlineWidth(w.gloss,true))}" data-inline-slot="${esc(d.words[i].id)}"><div class="inline-parts">${parts(w,i,'form')}</div><div class="inline-parts">${parts(w,i,'gloss')}</div>${d.layers.filter(l=>(l.anchor||'word')==='word').map(l=>`<label class="extra-layer" style="font-family:'${esc(validFont(l.font)?l.font:'Junicode')}';--layer-scale:${(l.size||100)/100};font-size:calc(.9375rem * var(--layer-scale));font-weight:${['bold','bolditalic'].includes(l.style)?700:400};font-style:${['italic','bolditalic'].includes(l.style)?'italic':'normal'};font-variant-caps:${l.style==='small-caps'?'small-caps':'normal'}"><small>${esc(l.name)}${l.visible?'':'（隐藏层）'}</small><input data-inline-layer="${esc(l.id)}" data-inline-unit="${esc(d.words[i].id)}" aria-label="第 ${i+1} 词 ${esc(l.name)}" value="${esc(values.get(d.words[i].id+'|'+l.id)||'')}"></label>`).join('')}</div>`).join('')}</div><label>翻译<textarea rows="1" data-inline-field="translation">${esc(b.translation)}</textarea></label>${inlineSentenceLayers(d,"translation")}<details class="example-notes" ${d.notesOpen?'open':''}><summary>备注</summary><textarea rows="1" data-inline-field="notes" aria-label="例句备注" placeholder="填写研究备注、疑问或待核对事项">${esc(b.notes||'')}</textarea></details>${d.orphaned.length?'<p class="warning">另有旧标注待核对，请保存后打开“附加标注”处理。</p>':''}<p class="inline-error" role="alert">${esc(d.error===d.errorShown?'':d.error||'')}</p>`);
}
function repaintInline(key,except=null,visibleOnly=false){const d=inlineDrafts.get(key);if(!d)return;let painted=false;for(const card of document.querySelectorAll('.editable-example'))if(card!==except&&card.dataset.exampleKey===key&&(!visibleOnly||card.getClientRects().length)){delete card.dataset.inlineRefresh;card.innerHTML=inlineStyledFields(d);inlineSelection(card,d);painted=true;}if(painted)d.errorShown=d.error;}
function clearInlineEditView(card){
 if(!card.querySelector('[data-inline-save]'))return false;
 card.dataset.inlineRefresh='true';
 card.innerHTML=(globalThis.CorporiumI18n?.f("3e27a10e05d3bd",()=>[])??'<p class="muted" role="status">正在更新例句显示…</p>');
 return true;
}
function finishInlineDraft(key){
 inlineOpening.delete(key);inlineDrafts.delete(key);
 // Hidden pages retain DOM as well as data. Retire every old editor before an
 // asynchronous history/read request gives navigation a chance to reveal it.
 for(const card of document.querySelectorAll('.editable-example'))if(card.dataset.exampleKey===key)clearInlineEditView(card);
 window.corporiumInvalidateViews?.();
}
// Cached panels can contain an older rendering of the same shared draft.
window.corporiumSyncInlineDrafts=()=>{let stale=false;for(const card of document.querySelectorAll('.editable-example'))if(card.getClientRects().length&&!inlineDrafts.has(card.dataset.exampleKey))stale=clearInlineEditView(card)||stale;if(stale)window.corporiumInvalidateViews?.();for(const key of inlineDrafts.keys())repaintInline(key,null,true);};
async function refreshExampleViews(options={}){
 if(options.invalidate!==false)window.corporiumInvalidateViews?.();
 if(workspace==='corpus'){await loadTexts();await search();}
 if(workspace==='grammar')await loadGrammar();
 if(workspace==='library')await loadLibrary();
 if(workspace==='dictionary')await loadDictionary();
 if(['survey','timeline','analysis'].includes(workspace))await window.corporiumRefreshVisibleWorkspace?.();
}
document.addEventListener('input',e=>{
 const card=e.target.closest('.editable-example');if(!card)return;const d=inlineDrafts.get(card.dataset.exampleKey);if(!d)return;const t=e.target;if(t.matches('[data-slot-drag]'))return;d.dirty=true;if(t.classList.contains('inline-piece'))t.size=inlineWidth(t.value,t.closest('.word').classList.contains('compact-symbol'));

 d.workspace=workspace;d.error='';
 if(t.dataset.inlineField)d.body[t.dataset.inlineField]=t.value;
 if(t.dataset.word!==undefined){const i=Number(t.dataset.word),field=t.dataset.field;d.body.words[i][field]=[...t.parentElement.children].map(x=>x.tagName==='INPUT'?x.value:x.textContent).join('');const slot=t.closest('.word'),w=d.body.words[i];if(slot.classList.contains('compact-symbol')){slot.classList.toggle('compact-symbol',compactWord(w));slot.style.setProperty('--symbol-columns',Math.max(inlineWidth(w.form,true),inlineWidth(w.gloss,true)));}}
 if(t.dataset.inlineLayer){let c=d.cells.find(c=>c.unit_id===t.dataset.inlineUnit&&c.layer_id===t.dataset.inlineLayer);if(!c){c={unit_id:t.dataset.inlineUnit,layer_id:t.dataset.inlineLayer,value:''};d.cells.push(c);}c.value=t.value;}
 // Keep other visible references current without replacing the focused input
 // or rebuilding hidden pages on every keystroke.
 repaintInline(card.dataset.exampleKey,card,true);
});
document.addEventListener('click',async e=>{
 const button=e.target.closest('[data-inline-start],[data-inline-save],[data-inline-cancel]');if(!button)return;
 e.preventDefault();const card=button.closest('.editable-example'),key=card.dataset.exampleKey;
 const run=async()=>{try{
  if(button.hasAttribute('data-inline-start')){
   await window.corporiumSentenceInspector?.prepareExampleEdit?.();
   if(await window.corporiumLeaveCodes?.()===false)return;
   if(inlineDrafts.has(key)){repaintInline(key);return;}
   const owner=activeLanguage,origin=workspace,opening={};inlineOpening.set(key,opening);button.disabled=true;
   try{
    const data=await api('annotations?'+new URLSearchParams({kind:card.dataset.exampleKind,id:card.dataset.exampleId}));
    if(inlineOpening.get(key)!==opening||owner!==activeLanguage||workspace!==origin||!card.isConnected)return;
    if(inlineDrafts.has(key)){repaintInline(key);return;}
    const d={...data,workspace,body:structuredClone(data.body),before:structuredClone(data.cells),cells:structuredClone(data.cells),dirty:false,notesOpen:button.dataset.inlineStart==='notes'};inlineDrafts.set(key,d);repaintInline(key);
   }catch(error){if(inlineOpening.get(key)===opening&&owner===activeLanguage&&workspace===origin&&card.isConnected)throw error;}
   finally{if(inlineOpening.get(key)===opening)inlineOpening.delete(key);button.disabled=false;}
   return;
  }
  const d=inlineDrafts.get(key);if(!d||d.saving)return;
  if(button.hasAttribute('data-inline-cancel')){if(d.dirty&&!(d.isNew&&sentenceDraftEmpty(d))&&!await corporiumConfirm((globalThis.CorporiumI18n?.f("ec0a7463fb2ec1",()=>[])??'放弃这条例句尚未保存的修改？')))return;finishInlineDraft(key);d.host?.remove();await d.onCancel?.();await refreshExampleViews({invalidate:false});return;}
  if(d.splitSpaces)inlineSplitSpaces(d);
  // Send cleared existing slots as well: the server removes empty pairs atomically,
  // preserving their old identities and references for undo.
  d.saving=true;d.error='';repaintInline(key);
  let saved;
  try{saved=await originalApi(d.isNew?'sentence-create':'inline-save',{kind:d.kind,id:d.id,text_id:d.text_id,targets:d.targets,survey_node:d.survey_node,survey_version:d.survey_version,example_group:d.example_group,example_group_token:d.example_group_token,revision:d.revision,before:d.before,layers:d.layers,body:d.body,slot_ids:d.words.map(w=>w.id),delete_confirmed:!!d.deleteConfirmed,cells:d.cells.filter(c=>(c.unit_id==='@sentence'||d.words.some(w=>w.id===c.unit_id))&&d.layers.some(l=>l.id===c.layer_id)),_language:d.owner_language});}
  catch(error){d.error=error.message;d.saving=false;repaintInline(key);return;}
  finishInlineDraft(key);
  try{const inPlace=await d.onSaved?.(saved,d);d.host?.remove();await window.corporiumRefreshUndoState();if(!inPlace)await refreshExampleViews({invalidate:false});await window.corporiumSentenceInspector?.afterExampleSave?.({kind:d.kind,id:d.id});}
  catch(error){d.host?.remove();window.corporiumInvalidateViews?.();$('notice').textContent=(globalThis.CorporiumI18n?.f("a5f2790f965cdc",()=>[error.message])??'例句已保存，但界面刷新失败：'+error.message+'。请刷新页面查看已保存内容。');}
 }catch(error){button.disabled=false;const msg=document.createElement('p');msg.className='inline-error';msg.textContent=error.message;card.append(msg);}};
 if(window.corporiumPreserveExampleLocation)await window.corporiumPreserveExampleLocation({kind:card.dataset.exampleKind,id:card.dataset.exampleId,card},run);else await run();
});
window.addEventListener('beforeunload',e=>{if([...inlineDrafts.values()].some(d=>d.saving||(d.dirty&&!(d.isNew&&sentenceDraftEmpty(d))))){e.preventDefault();e.returnValue='';}});


function inlineStyledFields(d){const m=JSON.parse(languageList.find(l=>l.id===d.language_id)?.metadata||'{}');const ipa=validFont(m.ipa_font)?m.ipa_font:'IPAPANNEW',annotation=validFont(m.annotation_font)?m.annotation_font:'Junicode';return `<div class="language-body" ${d.saving?'inert':''} style="${languageTypography(m)}">${inlineFields(d)}</div>`;}

function inlineSentenceLayers(d,anchor){return d.layers.filter(l=>l.anchor===anchor).map(l=>`<label>${esc(l.name)}${l.visible?'':(globalThis.CorporiumI18n?.f("a324d7c89aa886",()=>[])??'（隐藏层）')}<textarea rows="1" data-inline-layer="${esc(l.id)}" data-inline-unit="@sentence" style="${layerStyle(l)}">${esc(d.cells.find(c=>c.unit_id==='@sentence'&&c.layer_id===l.id)?.value||'')}</textarea></label>`).join('');}

function inlineSlotTools(d){const i=d.words.findIndex(w=>w.id===d.selectedSlot);return (globalThis.CorporiumI18n?.f("dea3c16ceda7cc",()=>[d.dragEnabled?'checked':'',d.splitSpaces?'checked':'',i<0?(globalThis.CorporiumI18n?.f("6e0bf08ede7ffe",()=>[])??'请选择词格'):(globalThis.CorporiumI18n?.f("14e68406dd6c09",()=>[i+1])??`已选第 ${i+1} 个词格`),d.isNew||i<0?'disabled':'',i<0?'disabled':'',i<0||i===d.words.length-1?'disabled':'',i<0?'disabled':''])??`<div class="slot-tools" role="group" aria-label="本句词格操作"><label class="slot-drag-toggle"><input type="checkbox" data-slot-drag ${d.dragEnabled?'checked':''}> 拖动排序</label><label class="slot-drag-toggle"><input type="checkbox" data-slot-split ${d.splitSpaces?'checked':''}> 保存时按语素行空格分词（仅本次编辑）</label><span data-slot-selection>${i<0?'请选择词格':`已选第 ${i+1} 个词格`}</span><button type="button" data-slot-transfer ${d.isNew||i<0?'disabled':''}>跨句转移</button><button type="button" data-slot-add>末尾添加</button><button type="button" data-slot-action="insert" ${i<0?'disabled':''}>后方插入</button><button type="button" data-slot-action="merge" title="与后一个词格直接拼接词形和标注；附加层用空格连接，保存后可撤销" ${i<0||i===d.words.length-1?'disabled':''}>向后合并词格</button><button type="button" data-slot-action="delete" ${i<0?'disabled':''}>删除词格</button></div>`);}
function inlineSelection(card,d){const i=d.words.findIndex(w=>w.id===d.selectedSlot);for(const el of card.querySelectorAll('[data-inline-slot]')){el.classList.toggle('slot-selected',d.dragEnabled?d.selectedSlots?.has(el.dataset.inlineSlot):el.dataset.inlineSlot===d.selectedSlot);el.draggable=!!d.dragEnabled;for(const input of el.querySelectorAll('input'))input.readOnly=!!d.dragEnabled;};const transfer=card.querySelector('[data-slot-transfer]');if(transfer)transfer.disabled=d.isNew|| (d.dragEnabled?!d.selectedSlots?.size:i<0);const label=card.querySelector('[data-slot-selection]');if(label)label.textContent=d.dragEnabled&&d.selectedSlots?.size>1?(globalThis.CorporiumI18n?.f("cb18c1555e2435",()=>[d.selectedSlots.size])??`已选 ${d.selectedSlots.size} 个词格`):i<0?(globalThis.CorporiumI18n?.f("ad0e68e9164b01",()=>[])??'请选择词格'):(globalThis.CorporiumI18n?.f("a6def35721262a",()=>[i+1])??`已选第 ${i+1} 个词格`);for(const button of card.querySelectorAll('[data-slot-action]'))button.disabled=(d.dragEnabled&&d.selectedSlots?.size>1)||i<0||(button.dataset.slotAction==='merge'&&i===d.words.length-1);}
for(const event of ['focusin','click'])document.addEventListener(event,e=>{const slot=e.target.closest('[data-inline-slot]'),card=slot?.closest('.editable-example'),d=inlineDrafts.get(card?.dataset.exampleKey);if(!d||d.saving||d.dragEnabled)return;d.selectedSlot=slot.dataset.inlineSlot;inlineSelection(card,d);});
function inlineSlotEmpty(d,i){const w=d.body.words[i],id=d.words[i]?.id;return !!w&&!w.form.trim()&&!w.gloss.trim()&&!d.words[i].protected&&!w.redup_id&&!w.morph_groups?.length&&!w.infix_confirmation&&!d.cells.some(c=>c.unit_id===id&&c.value.trim());}
function inlineFocus(card,i){const el=card.querySelectorAll('[data-inline-slot]')[i]?.querySelector('.inline-piece.form');el?.focus();}
function inlineInsert(card,d,i){d.words.splice(i,0,{id:'new:'+crypto.randomUUID(),protected:false});d.body.words.splice(i,0,{form:'',gloss:''});d.dirty=true;repaintInline(card.dataset.exampleKey);inlineFocus(card,i);}
function inlineRemove(d,i){const id=d.words[i].id;d.words.splice(i,1);d.body.words.splice(i,1);d.cells=d.cells.filter(c=>c.unit_id!==id);d.dirty=true;}
function inlineMerge(d,i){
 if(i<0||i>=d.words.length-1)return false;
 const left=d.words[i],right=d.words[i+1],word=d.body.words[i],next=d.body.words[i+1];
 word.form+=next.form;word.gloss+=next.gloss;
 for(const c of d.cells.filter(c=>c.unit_id===right.id)){
  const existing=d.cells.find(v=>v.unit_id===left.id&&v.layer_id===c.layer_id);
  if(existing)existing.value=[existing.value,c.value].filter(Boolean).join(' ');
  else d.cells.push({...c,unit_id:left.id});
 }
 left.protected||=right.protected;
 inlineRemove(d,i+1);d.deleteConfirmed=true;d.selectedSlot=left.id;d.selectedSlots=new Set([left.id]);return true;
}
document.addEventListener('click',async e=>{
 const button=e.target.closest('[data-slot-add],[data-slot-action]');if(!button)return;
 const card=button.closest('.editable-example'),d=inlineDrafts.get(card?.dataset.exampleKey);if(!d||d.saving)return;e.preventDefault();
 if(button.hasAttribute('data-slot-add')){const last=d.words.length-1;if(last>=0&&inlineSlotEmpty(d,last))inlineFocus(card,last);else inlineInsert(card,d,d.words.length);return;}
 const id=d.selectedSlot,i=d.words.findIndex(w=>w.id===id),action=button.dataset.slotAction;if(i<0)return;
 if(action==='insert')return inlineInsert(card,d,i+1);
 if(action==='merge'){if(inlineMerge(d,i)){repaintInline(card.dataset.exampleKey);inlineFocus(card,i);}return;}
 if(action==='delete'){if(!inlineSlotEmpty(d,i)){if(!await corporiumConfirm((globalThis.CorporiumI18n?.f("6e4c6609d433c7",()=>[])??'删除这个词格及其附加标注？已有引用将保留为待核对记录，保存后可撤销。')))return;d.deleteConfirmed=true;}inlineRemove(d,i);repaintInline(card.dataset.exampleKey);return;}

});
document.addEventListener('keydown',e=>{
 if(e.key!=='Tab'||e.isComposing||e.keyCode===229||!e.target.matches('.inline-piece'))return;
 const card=e.target.closest('.editable-example'),d=inlineDrafts.get(card.dataset.exampleKey);if(!d||d.saving)return;
 const fields=[...card.querySelectorAll('.inline-piece')],i=fields.indexOf(e.target),next=fields[i+(e.shiftKey?-1:1)];
 const slot=e.target.closest('[data-inline-slot]');
 if(!e.shiftKey&&slot?.dataset.inlineSlot===d.words.at(-1)?.id&&!inlineSlotEmpty(d,d.words.length-1)&&e.target===slot.querySelectorAll('.inline-piece.'+e.target.dataset.field)[slot.querySelectorAll('.inline-piece.'+e.target.dataset.field).length-1]){e.preventDefault();inlineInsert(card,d,d.words.length);return;}
 if(next){e.preventDefault();next.focus();return;}
 if(!e.shiftKey&&!inlineSlotEmpty(d,d.words.length-1)){e.preventDefault();inlineInsert(card,d,d.words.length);}
});
document.addEventListener('focusout',e=>{
 const card=e.target.closest('.editable-example'),slot=e.target.closest('[data-inline-slot]');if(!card||!slot)return;
 setTimeout(()=>{const d=inlineDrafts.get(card.dataset.exampleKey);if(!d||d.saving||d.dragEnabled)return;
 // Only trim the trailing slot after focus actually leaves it; never rebuild the focused editor.
 let last=d.words.length-1;
 while(last>=0&&inlineSlotEmpty(d,last)){
  const id=d.words[last].id,els=[...document.querySelectorAll('[data-inline-slot]')].filter(el=>el.closest('.editable-example')?.dataset.exampleKey===card.dataset.exampleKey&&el.dataset.inlineSlot===id);
  if(!id.startsWith('new:'))break;
  if(els.some(el=>el.contains(document.activeElement))||(card.querySelector('.slot-tools')?.contains(document.activeElement)&&d.selectedSlot===id)||document.querySelector('dialog[open]'))break;
  inlineRemove(d,last);for(const el of els)el.remove();last--;inlineSelection(card,d);
 }
 },0);
});

function inlineSplitSpaces(d){
 const plans=[];
 for(let i=0;i<d.words.length;i++){
  const w=d.body.words[i],parts=w.form.trim().split(/\s+/u);if(parts.length<2)continue;
  if(d.words[i].protected||w.redup_id||w.morph_groups?.length||w.infix_confirmation||d.cells.some(c=>c.unit_id===d.words[i].id&&c.value.trim()))throw Error((globalThis.CorporiumI18n?.f("d39f265727bd31",()=>[i+1])??'第 '+(i+1)+' 个词格含关联、分析或附加标注，请先处理这些内容再按空格拆分。'));
  const gloss=w.gloss.trim()?w.gloss.trim().split(/\s+/u):[];
  if(gloss.length>1&&gloss.length!==parts.length)throw Error((globalThis.CorporiumI18n?.f("d765818eaf89ae",()=>[i+1])??'第 '+(i+1)+' 个词格的语素与标注分词数量不一致，请调整标注中的空格后再保存。'));
  plans.push({i,words:parts.map((form,n)=>({form,gloss:gloss[n]||''}))});
 }
 for(const p of plans.reverse()){d.body.words.splice(p.i,1,...p.words);d.words.splice(p.i+1,0,...p.words.slice(1).map(()=>({id:'new:'+crypto.randomUUID(),protected:false})));d.dirty=true;}
}
document.addEventListener('change',e=>{if(!e.target.matches('[data-slot-split]'))return;const card=e.target.closest('.editable-example'),d=inlineDrafts.get(card.dataset.exampleKey);if(d)d.splitSpaces=e.target.checked;});
