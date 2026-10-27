/* A shared, nonmodal inspector. Existing forms and save handlers stay intact. */
function createSentenceInspector(main){
 const dialogs={dictionary:$('word-link-dialog'),morphology:$('segmentation-dialog')};
 const nativeClose=Object.fromEntries(Object.entries(dialogs).map(([key,d])=>[key,d.close.bind(d)]));
 const openDictionary=openWordLink,openMorphology=openSegmentation;
 let context=null,loaded={},activeTab='dictionary',linkDirty=false,linkBusy=false,originButton=null,queue=Promise.resolve();
 const same=(a,b)=>a&&b&&a.kind===b.kind&&a.id===b.id&&a.word===b.word;
 const isOpen=()=>Object.values(dialogs).some(d=>d.open);
 async function canDiscard(){
  if(segmentBusy||linkBusy)throw Error((globalThis.CorporiumI18n?.f("08b118e049e62c",()=>[])??'正在保存词格关联或形态分析，请稍后再操作。'));
  return !(linkDirty||segmentDirty)||await corporiumConfirm((globalThis.CorporiumI18n?.f("b845839f7011f2",()=>[])??'放弃尚未保存的词典关联或形态组合修改？'));
 }
 function closeAll(focus=true){
  for(const [key,d] of Object.entries(dialogs)){if(d.open)nativeClose[key]();d.hidden=false;}
  document.documentElement.classList.remove('workbench-inspecting');context=null;loaded={};linkDirty=false;segmentDirty=false;markOrigin();
  if(focus&&originButton?.isConnected)originButton.focus({preventScroll:true});
 }
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
  if(!loaded[tab]){
   if(tab==='morphology')await openMorphology(context.kind,context.id,context.word);
   else{
    const d=provided||await api('segmentation?'+new URLSearchParams({kind:context.kind,id:context.id})),w=d.body.words[context.word];
    if(!w)throw Error((globalThis.CorporiumI18n?.f("7656825f751d34",()=>[])??'原词已变化，请重新选择词格。'));
    const record=context.kind==='corpus'?items.find(e=>e.id===context.id):null;
    const entry={...d.body,id:context.id,title:record?.title||(context.kind==='independent'?(globalThis.CorporiumI18n?.f("a985ab74fe677d",()=>[])??'独立例句'):(globalThis.CorporiumI18n?.f("00ce3cff7c44da",()=>[])??'文本句子')),position:record?.position||'',text_language_id:d.language_id};
    if(context.kind==='independent')entry.independentLink={id:context.id,word:context.word};
    await openDictionary(entry,w,options);
   }
   loaded[tab]=true;
  }
  present(tab);
 }
 function open(next,tab=activeTab,provided){
  const task=queue.then(async()=>{
   if(segmentBusy||linkBusy)throw Error((globalThis.CorporiumI18n?.f("164144f578448c",()=>[])??'正在保存词格关联或形态分析，请稍后再操作。'));
   if(!same(context,next)){
    if(isOpen()&&!await canDiscard())return;
    closeAll(false);context={...next};originButton=document.activeElement;
   }
   try{await showTab(tab,provided);}catch(error){if(!isOpen())closeAll(false);throw error;}
  });queue=task.catch(()=>{});return task;
 }
 for(const [key,d] of Object.entries(dialogs)){
  d.classList.add('workbench-inspector');d.setAttribute('aria-label',key==='dictionary'?(globalThis.CorporiumI18n?.f("f5d9e4ed3b041f",()=>[])??'词典关联侧面板'):(globalThis.CorporiumI18n?.f("12a474442acb38",()=>[])??'形态分析侧面板'));
  d.showModal=()=>present(key);d.close=()=>closeAll();
  const form=d.querySelector('form[method="dialog"]');
  if(key==='morphology'){d.removeEventListener('cancel',segmentClose);form.removeEventListener('submit',segmentClose);}
  form.addEventListener('submit',e=>{e.preventDefault();void safe(async()=>{if(await canDiscard())closeAll();})();});
 }
 dialogs.dictionary.addEventListener('input',()=>linkDirty=true);dialogs.dictionary.addEventListener('change',()=>linkDirty=true);
 for(const id of ['save-link','unlink-unit']){const button=$(id);if(!button)continue;const handler=button.onclick;button.onclick=async(...args)=>{if(linkBusy)return;linkBusy=true;const content=dialogs.dictionary.querySelector('.dialog-content');if(content)content.inert=true;try{return await handler(...args);}finally{linkBusy=false;if(content)content.inert=false;}};}
 const previousLoad=loadLinkUnit;loadLinkUnit=async function(...args){await previousLoad(...args);linkDirty=false;if(!segmentDirty)loaded.morphology=false;markOrigin();};
 $('link-unit').onchange=linkSafe(async()=>{const next=$('link-unit').value,previous=linkUnit?.id;if(linkDirty&&!await corporiumConfirm((globalThis.CorporiumI18n?.f("4fcb53ae135591",()=>[])??'放弃尚未保存的词典关联选择或备注？'))){$('link-unit').value=previous;return;}$('link-unit').value=next;await loadLinkUnit();});
 const previousSegmentRefresh=refreshSegmentation;refreshSegmentation=async function(){await previousSegmentRefresh();if(!linkDirty)loaded.dictionary=false;markOrigin();};
 const previousWordChange=$('segment-word').onchange;$('segment-word').onchange=async()=>{
  const old=context?.word;if(linkDirty&&!await corporiumConfirm((globalThis.CorporiumI18n?.f("3cc90e88e1c976",()=>[])??'切换词格前放弃尚未保存的词典关联选择或备注？'))){$('segment-word').value=String(old);return;}
  await previousWordChange();if(context&&Number($('segment-word').value)!==old){context.word=Number($('segment-word').value);loaded.dictionary=false;linkDirty=false;markOrigin();}
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
  e.preventDefault();e.stopImmediatePropagation();void safe(()=>open({kind:card.dataset.exampleKind,id:card.dataset.exampleId,word:index}))();
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
 return {markOrigin,current:()=>context?{...context}:null,
  async prepare(){await queue;return !isOpen()||await canDiscard();},
  async refresh(source){linkDirty=false;segmentDirty=false;loaded={};if(context&&isOpen())await showTab(activeTab,undefined,same(context,source)?{unitKey:source.key,linkedOnly:true}:undefined);},
  async leave(){await queue;if(isOpen()){if(!await canDiscard())throw Error((globalThis.CorporiumI18n?.f("f2a7f9457269a9",()=>[])??'已保留尚未保存的词格关联或形态分析。'));closeAll(false);}}};
}
