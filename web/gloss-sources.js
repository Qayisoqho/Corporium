(() => {
 const previous=renderEditableExample;
 renderEditableExample=function(entry,kind,id){
  const markup=previous(entry,kind,id);
  if(briefMode||inlineDrafts.has(inlineKey(kind,id))||!entry.words?.some(w=>w.gloss_sources?.length))return markup;
  return markup.replace('<div class="inline-tools">','<div class="inline-tools"><button type="button" data-gloss-source>标注来源</button>');
 };
 const dialog=document.createElement('dialog');dialog.id='gloss-source-dialog';dialog.className='gloss-source-dialog';dialog.setAttribute('aria-labelledby','gloss-source-title');
 dialog.innerHTML='<form method="dialog"><button class="close" aria-label="关闭标注来源">×</button></form><h2 id="gloss-source-title">本句标注来源</h2><label>选择词或语素<select data-source-unit></select></label><p data-source-default class="preserve-lines"></p><label>标注方式<select data-source-mode><option value="inherit">跟随词典释义</option><option value="override">本句单独标注</option></select></label><label>本句标注<textarea data-source-value rows="2" aria-label="本句单独标注，允许空白"></textarea></label><p data-source-hint></p><p data-source-error role="alert"></p><button type="button" data-source-save class="primary">保存</button>';
 document.body.append(dialog);
 const field=name=>dialog.querySelector('[data-source-'+name+']');let draft=null,units=[],busy=false,dirty=false;
 function choose(){
  const item=units[+field('unit').value];if(!item)return;
  field('mode').value=item.source.mode;field('value').value=item.gloss;
  field('default').textContent='词典简单释义：'+(item.source.meaning||'（空白）');
  field('hint').textContent='单独标注可以留空；恢复跟随后会显示词典的当前释义。整词单独标注时，以整词显示为准。';
  toggle();dirty=false;
 }
 function toggle(){field('value').disabled=field('mode').value==='inherit';}
 field('unit').onchange=()=>{if(dirty){field('error').textContent='请先保存当前标注方式，或关闭后重新打开。';field('unit').value=String(units.findIndex(i=>i.source.id===draft.selected));return;}draft.selected=units[+field('unit').value]?.source.id;choose();};
 field('mode').onchange=()=>{dirty=true;toggle();};field('value').oninput=()=>dirty=true;
 document.addEventListener('click',async event=>{
  const button=event.target.closest('[data-gloss-source]');if(!button)return;
  const host=button.closest('.editable-example');if(!host)return;button.disabled=true;
  try{
   draft=await api('segmentation?'+new URLSearchParams({kind:host.dataset.exampleKind,id:host.dataset.exampleId}));units=[];
   for(const [index,word] of draft.body.words.entries())for(const source of word.gloss_sources||[]){
    const unit=source.key==='@word'?word:word.morphemes?.find(m=>m.key===source.key);if(!unit)continue;
    units.push({source,gloss:unit.gloss,label:`${index+1}. ${source.key==='@word'?'整词':'语素'} · ${unit.form}`});
   }
   if(!units.length)throw Error('当前句子没有可继承的具体义项关联。');
   field('unit').innerHTML=units.map((u,i)=>`<option value="${i}">${esc(u.label)}</option>`).join('');
   draft.selected=units[0].source.id;field('error').textContent='';choose();dialog.showModal();
  }catch(error){corporiumStatus(error.message,'gloss-source');}finally{button.disabled=false;}
 });
 field('save').onclick=async()=>{
  const item=units[+field('unit').value];if(!item||busy)return;busy=true;field('save').disabled=true;
  try{
   await originalApi('gloss-source-save',{kind:draft.kind,id:draft.id,revision:draft.revision,binding_id:item.source.id,binding_revision:item.source.revision,gloss_revision:draft.body.gloss_revision,mode:field('mode').value,value:field('value').value,_language:draft.owner_language});
   dirty=false;dialog.close();await refreshUndo();await refreshExampleViews();
   if(typeof segmentDraft!=='undefined'&&$('segmentation-dialog')?.open)await refreshSegmentation();
  }catch(error){field('error').textContent=error.message;}finally{busy=false;field('save').disabled=false;}
 };
 dialog.addEventListener('cancel',event=>{if(busy){event.preventDefault();return;}guardDialogDiscard(event,dirty,'放弃尚未保存的本句标注？');});
 dialog.querySelector('form').addEventListener('submit',event=>{if(busy){event.preventDefault();return;}guardDialogDiscard(event,dirty,'放弃尚未保存的本句标注？');});
 dialog.addEventListener('close',()=>{dirty=false;draft=null;});
 window.addEventListener('beforeunload',event=>{if(dirty){event.preventDefault();event.returnValue='';}});
})();
