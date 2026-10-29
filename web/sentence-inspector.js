/* A shared, nonmodal inspector. Existing forms and save handlers stay intact. */
function createSentenceInspector(main){
 const dialogs={dictionary:$('word-link-dialog'),morphology:$('segmentation-dialog')};
 const nativeClose=Object.fromEntries(Object.entries(dialogs).map(([key,d])=>[key,d.close.bind(d)]));
 const openDictionary=openWordLink,openMorphology=openSegmentation;
 let context=null,loaded={},activeTab='dictionary',linkDirty=false,linkBusy=false,originButton=null,originCard=null,queue=Promise.resolve(),sourceRefresh=0;
 const wordIdentity=word=>word?.unit_id||word?.annotation_id||null;
 function releaseContent(){for(const d of Object.values(dialogs)){const content=d.querySelector('.dialog-content');if(content)content.inert=false;}}
 const same=(a,b)=>a&&b&&a.kind===b.kind&&a.id===b.id&&a.word===b.word;
 const isOpen=()=>Object.values(dialogs).some(d=>d.open);
 async function canDiscard(){
  if(segmentBusy||linkBusy)throw Error((globalThis.CorporiumI18n?.f("08b118e049e62c",()=>[])??'正在保存词格关联或形态分析，请稍后再操作。'));
  return !(linkDirty||segmentDirty)||await corporiumConfirm((globalThis.CorporiumI18n?.f("b845839f7011f2",()=>[])??'放弃尚未保存的词典关联或形态组合修改？'));
 }
 const keepLocation=(source,work,card=originCard)=>window.corporiumPreserveExampleLocation?window.corporiumPreserveExampleLocation({...source,card},work):work();
 function closeAll(focus=true){return keepLocation(context,()=>{
  for(const [key,d] of Object.entries(dialogs)){if(d.open)nativeClose[key]();d.hidden=false;}
  document.documentElement.classList.remove('workbench-inspecting');context=null;sourceRefresh++;releaseContent();loaded={};linkDirty=false;segmentDirty=false;markOrigin();
  if(focus&&originButton?.isConnected)originButton.focus({preventScroll:true});
 });}
 function markOrigin(){
  for(const e of main.querySelectorAll('.inspection-origin'))e.classList.remove('inspection-origin');
  if(!context||!isOpen())return;
  for(const card of main.querySelectorAll('.editable-example')){
   if(card.dataset.exampleKind===context.kind&&card.dataset.exampleId===context.id)card.querySelectorAll('.words:not(.inline-words)>.word')[context.word]?.classList.add('inspection-origin');
  }
 }
 function present(tab){
  activeTab=tab;document.documentElement.classList.add('workbench-inspecting');
  for(const [key,d] of Object.entries(dialogs)){
   d.hidden=key!==tab;if(key===tab&&!d.open)d.show();if(!d.open)continue;dockDialog(d);
   if(!d.querySelector('.sentence-inspector-tabs')){
    const header=d.querySelector('.dialog-top'),title=d.querySelector('h2');header.prepend(title);header.classList.add('dialog-title-row');
    const tabs=document.createElement('nav');tabs.className='sentence-inspector-tabs';tabs.setAttribute('role','tablist');tabs.setAttribute('aria-label',(globalThis.CorporiumI18n?.f("4c6bf2d3681a3c",()=>[])??'例句词格工具'));
    tabs.innerHTML=(globalThis.CorporiumI18n?.f("61244f56169ebf",()=>[])??'<button type="button" role="tab" data-inspector-tab="dictionary">词典关联</button><button type="button" role="tab" data-inspector-tab="morphology">形态分析</button>');
    header.append(tabs);tabs.onclick=safe(async e=>{const b=e.target.closest('[data-inspector-tab]');if(b&&context)await open(context,b.dataset.inspectorTab);});
   }
   for(const b of d.querySelectorAll('[data-inspector-tab]'))b.setAttribute('aria-selected',String(b.dataset.inspectorTab===tab));
  }
  markOrigin();
 }
 async function showTab(tab,provided,options){
  const owner=context,ticket=sourceRefresh,current=()=>context===owner&&sourceRefresh===ticket;
  if(!loaded[tab]){
   if(tab==='morphology'){await openMorphology(context.kind,context.id,context.word);if(!current())return;if(typeof segmentDraft!=='undefined')context.wordId=wordIdentity(segmentDraft?.body.words[context.word])||context.wordId;}
   else{
    const d=provided||await api('segmentation?'+new URLSearchParams({kind:context.kind,id:context.id}));if(!current())return;const w=d.body.words[context.word];
    if(!w)throw Error((globalThis.CorporiumI18n?.f("7656825f751d34",()=>[])??'原词已变化，请重新选择词格。'));
    context.wordId=wordIdentity(w)||context.wordId;
    const record=context.kind==='corpus'?items.find(e=>e.id===context.id):null;
    const entry={...d.body,id:context.id,title:record?.title||(context.kind==='independent'?(globalThis.CorporiumI18n?.f("a985ab74fe677d",()=>[])??'独立例句'):(globalThis.CorporiumI18n?.f("00ce3cff7c44da",()=>[])??'文本句子')),position:record?.position||'',text_language_id:d.language_id};
    if(context.kind==='independent')entry.independentLink={id:context.id,word:context.word};
    await openDictionary(entry,w,options);
    if(!current())return;
    if(context.pendingLinkDraft){const pending=context.pendingLinkDraft;delete context.pendingLinkDraft;if(typeof restoreWordLinkDraft==='function')await restoreWordLinkDraft(pending.value,current);if(!current())return;linkDirty=pending.dirty;}
   }
   loaded[tab]=true;
   if(tab==='morphology'&&context.pendingMorphDraft){restoreMorphDraft(context.pendingMorphDraft);delete context.pendingMorphDraft;}
  }
  present(tab);
 }
 function open(next,tab=activeTab,provided,card){
  const task=keepLocation(next,()=>queue.then(async()=>{
   if(segmentBusy||linkBusy)throw Error((globalThis.CorporiumI18n?.f("164144f578448c",()=>[])??'正在保存词格关联或形态分析，请稍后再操作。'));
   if(!same(context,next)){
    if(isOpen()&&!await canDiscard())return;
    // Keep the dock and open dialogs in place between words. Closing them
    // briefly widens every preceding sentence and triggers native focus scroll.
    context={...next};sourceRefresh++;releaseContent();loaded={};linkDirty=false;segmentDirty=false;originButton=document.activeElement;if(card)originCard=card;
   }
   try{await showTab(tab,provided);}catch(error){await closeAll(false);throw error;}
  }),card||originCard);queue=task.catch(()=>{});return task;
 }
 for(const [key,d] of Object.entries(dialogs)){
  d.classList.add('workbench-inspector');d.setAttribute('aria-label',key==='dictionary'?(globalThis.CorporiumI18n?.f("f5d9e4ed3b041f",()=>[])??'词典关联侧面板'):(globalThis.CorporiumI18n?.f("12a474442acb38",()=>[])??'形态分析侧面板'));
  d.showModal=()=>present(key);d.close=()=>closeAll();
  const form=d.querySelector('form[method="dialog"]');
  if(key==='morphology'){d.removeEventListener('cancel',segmentClose);form.removeEventListener('submit',segmentClose);}
  form.addEventListener('submit',e=>{e.preventDefault();void safe(async()=>{if(await canDiscard())closeAll();})();});
 }
 const dirtyLink=e=>{if(!e?.target?.matches?.('#link-query'))linkDirty=true;};dialogs.dictionary.addEventListener('input',dirtyLink);dialogs.dictionary.addEventListener('change',dirtyLink);
 for(const id of ['save-link','unlink-unit']){const button=$(id);if(!button)continue;const handler=button.onclick;button.onclick=async(...args)=>{if(linkBusy)return;linkBusy=true;const content=dialogs.dictionary.querySelector('.dialog-content');if(content)content.inert=true;try{return await keepLocation(context,()=>handler(...args));}finally{linkBusy=false;if(content)content.inert=false;}};}
 const previousLoad=loadLinkUnit;loadLinkUnit=async function(...args){await previousLoad(...args);linkDirty=false;if(!segmentDirty)loaded.morphology=false;markOrigin();};
 $('link-unit').onchange=linkSafe(async()=>{const next=$('link-unit').value,previous=linkUnit?.id;if(linkDirty&&!await corporiumConfirm((globalThis.CorporiumI18n?.f("4fcb53ae135591",()=>[])??'放弃尚未保存的词典关联选择或备注？'))){$('link-unit').value=previous;return;}$('link-unit').value=next;await loadLinkUnit();});
 const previousSegmentRefresh=refreshSegmentation;refreshSegmentation=async function(){return keepLocation(context,async()=>{await previousSegmentRefresh();if(typeof segmentDraft!=='undefined'&&segmentDraft)await afterExampleSave({kind:segmentDraft.kind,id:segmentDraft.id});markOrigin();});};
 const previousWordChange=$('segment-word').onchange;$('segment-word').onchange=async()=>{
  const old=context?.word;if(linkDirty&&!await corporiumConfirm((globalThis.CorporiumI18n?.f("3cc90e88e1c976",()=>[])??'切换词格前放弃尚未保存的词典关联选择或备注？'))){$('segment-word').value=String(old);return;}
  await previousWordChange();if(context&&Number($('segment-word').value)!==old){context.word=Number($('segment-word').value);context.wordId=typeof segmentDraft==='undefined'?null:wordIdentity(segmentDraft?.body.words[context.word]);loaded.dictionary=false;linkDirty=false;markOrigin();}
 };
 openSegmentation=(kind,id,word)=>open({kind,id,word:word??(context?.kind===kind&&context?.id===id?context.word:0)},'morphology');
 openWordLink=async(entry,word)=>{
  const kind=entry.independentLink?'independent':'corpus',id=entry.independentLink?.id||entry.id,index=entry.independentLink?.word??entry.words.findIndex(w=>w.unit_id===word.unit_id);
  return open({kind,id,word:Math.max(0,index)},'dictionary',{body:entry,language_id:word.language_id||entry.text_language_id||entry.language_id||activeLanguage});
 };
 document.addEventListener('click',e=>{
  const word=e.target.closest('.editable-example .words:not(.inline-words)>.word');
  if(!word||word.matches('.punctuation-unit,.phonological-boundary')||e.target.closest('a,input,select,textarea,[data-judgment-edit]'))return;
  const card=word.closest('.editable-example'),index=[...word.parentElement.children].indexOf(word);if(!card.dataset.exampleId)return;
  e.preventDefault();e.stopImmediatePropagation();void safe(()=>open({kind:card.dataset.exampleKind,id:card.dataset.exampleId,word:index},activeTab,undefined,card))();
 },true);
 document.addEventListener('keydown',e=>{if(e.key==='Escape'&&isOpen()&&!document.querySelector('dialog:modal')){e.preventDefault();void safe(async()=>{if(await canDiscard())closeAll();})();}});
 function prepareWords(){
  for(const word of main.querySelectorAll('.editable-example .words:not(.inline-words)>.word')){
   if(word.matches('.punctuation-unit,.phonological-boundary'))continue;
   const form=word.querySelector('.form');if(!form||form.matches('button'))continue;
   const button=document.createElement('button');button.type='button';button.className=form.className+' word-dictionary';button.title=(globalThis.CorporiumI18n?.f("fbab1a5c9d6540",()=>[])??'查看词典关联与形态分析');button.innerHTML=form.innerHTML;form.replaceWith(button);
  }markOrigin();
 }
 let scheduled=false;new MutationObserver(records=>{if(scheduled||!records.some(r=>[...r.addedNodes].some(n=>n.nodeType===1&&(n.matches('.editable-example,.words,.word,.form')||n.querySelector('.editable-example,.words>.word')))))return;scheduled=true;queueMicrotask(()=>{scheduled=false;prepareWords();});}).observe(main,{childList:true,subtree:true});prepareWords();
 function captureMorphDraft(){
  if(!segmentDirty||typeof segmentCurrent!=='function'||!$('segment-members'))return null;
  const w=segmentCurrent();return {signature:JSON.stringify(w?.segments||[]),editing:segmentEditing,members:[...$('segment-members').querySelectorAll('input:checked')].map(i=>i.value),type:$('segment-type').value,gloss:$('segment-gloss').value,notes:$('segment-notes').value,open:$('segment-manual').open};
 }
 function restoreMorphDraft(draft){
  if(typeof segmentCurrent!=='function')return;
  const w=segmentCurrent();let compatible=JSON.stringify(w?.segments||[])===draft.signature&&(!draft.editing||w.morph_groups?.some(g=>g.id===draft.editing));
  if(compatible&&typeof drawSegmentMembers==='function')drawSegmentMembers(w,draft.editing);
  const inputs=[...$('segment-members').querySelectorAll('input')];compatible=compatible&&draft.members.every(id=>inputs.some(i=>i.value===id));
  segmentEditing=compatible?draft.editing:'';for(const input of inputs)input.checked=compatible&&draft.members.includes(input.value);$('segment-type').value=draft.type;$('segment-gloss').value=draft.gloss;$('segment-notes').value=draft.notes;$('segment-manual').open=draft.open;segmentDirty=true;
  if(!compatible){$('segment-save').disabled=true;globalThis.corporiumStatus?.(globalThis.CorporiumI18n?.ui('例句切分已变化，已保留输入；请重新选择组合成员。','Segmentation changed. Your text is retained; select the group members again.')??'例句切分已变化，已保留输入；请重新选择组合成员。','sentence-inspector');}
 }
 async function refresh(source,provided){return keepLocation(context,async()=>{linkDirty=false;segmentDirty=false;loaded={};if(context&&isOpen())await showTab(activeTab,provided,same(context,source)?{unitKey:source.key,linkedOnly:true}:undefined);});}
 async function afterExampleSave(source){
  if(context?.kind!==source.kind||context.id!==source.id||!isOpen())return;
  const before=context,lid=activeLanguage,ticket=++sourceRefresh,selected=loaded.dictionary&&typeof linkedSentenceSource==='function'?linkedSentenceSource():{...(context.pendingSelection||context),key:context.pendingSelection?.key||'@word'},word=typeof linkColorWord==='undefined'?null:linkColorWord,identity=context.wordId||wordIdentity(word),draft=loaded.dictionary&&typeof readWordLinkDraft==='function'?{value:readWordLinkDraft(),dirty:linkDirty}:context.pendingLinkDraft,morphDraft=captureMorphDraft()||context.pendingMorphDraft;
  const oldUnit=loaded.dictionary&&typeof linkUnit!=='undefined'?linkUnit.id:context.pendingUnitId,oldPart=loaded.dictionary?word?.morphemes?.find(m=>m.key===selected?.key):context.pendingPart;
  context.pendingSelection=selected;context.pendingUnitId=oldUnit;context.pendingPart=oldPart;context.pendingLinkDraft=draft;context.pendingMorphDraft=morphDraft;
  const content=dialogs.dictionary.querySelector('.dialog-content');if(content)content.inert=true;for(const id of ['save-link','unlink-unit'])if($(id))$(id).disabled=true;
  try{
   const data=await api('segmentation?'+new URLSearchParams({kind:source.kind,id:source.id}));
   if(context!==before||lid!==activeLanguage||ticket!==sourceRefresh)return;
   const index=identity?data.body.words.findIndex(w=>wordIdentity(w)===identity):context.word;
   if(index<0||!data.body.words[index]){await closeAll(false);return;}
   const currentWord=data.body.words[index];
   if(selected?.key&&selected.key!=='@word'){
    const part=currentWord.morphemes?.find(m=>source.kind==='corpus'?m.unit_id===oldUnit:m.key===selected.key&&m.form===oldPart?.form);
    if(!part){await closeAll(false);globalThis.corporiumStatus?.(globalThis.CorporiumI18n?.ui('原语素已变化，已关闭旧关联面板；请重新选择。','The source morpheme changed. Select it again to reopen the link panel.')??'原语素已变化，已关闭旧关联面板；请重新选择。','sentence-inspector');return;}
    selected.key=part.key;
    context.pendingUnitId=source.kind==='corpus'?part.unit_id:part.key;context.pendingPart=part;
   }
   context.word=index;context.wordId=wordIdentity(currentWord);selected.word=index;
   context.pendingLinkDraft=draft;context.pendingMorphDraft=morphDraft;
   await refresh(selected,data);if(context===before&&ticket===sourceRefresh&&context.pendingLinkDraft?.dirty)linkDirty=true;
  }catch(error){if(context===before&&ticket===sourceRefresh){loaded={};for(const id of ['save-link','unlink-unit'])if($(id))$(id).disabled=true;}throw error;}
  finally{if(context===before&&ticket===sourceRefresh&&content)content.inert=false;}
 }
 return {markOrigin,current:()=>context?{...context}:null,
  async prepare(){await queue;return !isOpen()||await canDiscard();},
  refresh,
  afterExampleSave,
  prepareExampleEdit(){if(segmentBusy||linkBusy)throw Error((globalThis.CorporiumI18n?.f("08b118e049e62c",()=>[])??'正在保存词格关联或形态分析，请稍后再操作。'));},
  async leave(){await queue;if(isOpen()){if(!await canDiscard())throw Error((globalThis.CorporiumI18n?.f("f2a7f9457269a9",()=>[])??'已保留尚未保存的词格关联或形态分析。'));await closeAll(false);}}};
}
