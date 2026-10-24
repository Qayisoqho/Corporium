/* Shared manual relations: inline changes remain in the sentence draft. */
(()=>{
 const kinds={partial:'部分重叠',full:'完全重叠',modified:'变形重叠',unspecified:'未细分'};
 let state=null,serial=0;
 makeDialog('redup-dialog','<h2>重叠与基底</h2><div id="redup-list"></div><form id="redup-form"><div class="redup-pair"><label>重叠部分<select id="redup-source" required></select></label><span aria-hidden="true">→</span><label>基底<select id="redup-base" required></select></label></div><div class="redup-actions"><label>类型<select id="redup-type"><option value="partial">部分重叠</option><option value="full">完全重叠</option><option value="modified">变形重叠</option><option value="unspecified">未细分</option></select></label><button type="button" id="redup-new">新建关系</button><button type="submit" id="redup-save" class="primary">保存关系</button></div><details><summary>备注</summary><textarea id="redup-notes" rows="2"></textarea></details><small id="redup-help"></small><p id="redup-error" role="alert"></p></form>');
 const optionKey=o=>JSON.stringify([o.word,o.key]);
 function selection(id){const [word,key]=JSON.parse($(id).value);return {word,key};}
 function render(){
  const s=state,opts=s.plan.options.map(o=>`<option value="${esc(optionKey(o))}">${esc(o.label)}</option>`).join('');
  $('redup-source').innerHTML=$('redup-base').innerHTML=opts;
  $('redup-list').innerHTML=s.plan.info.relations.map(r=>`<div class="redup-row"><span title="${esc(r.notes||'')}">${esc(r.source.form)} → ${esc(r.base.form)} <small>${esc(kinds[r.type])}${r.review?' · 待核对':''}</small></span><button type="button" data-redup-edit="${esc(r.id)}">${r.review?'核对':'编辑'}</button><button type="button" data-redup-delete="${esc(r.id)}">解除</button></div>`).join('');
  $('redup-help').textContent=(s.plan.info.candidates.length?'~ 仅提示候选，请确认方向与基底。':'')+(s.draft?'关系随本句“保存”一起生效。':'修改不会自动改写标注或登记词典变体。');
  $('redup-save').disabled=!s.plan.options.length;
  reset();
 }
 function reset(fresh=false){
  const s=state;s.editing='';$('redup-notes').value='';$('redup-type').value='partial';$('redup-save').textContent='保存关系';$('redup-error').textContent='';
  const candidate=s.plan.info.candidates.find(c=>c.word===s.word)||s.plan.info.candidates[0];
  const source=s.plan.options.find(o=>o.word===s.word&&o.key===s.key)||s.plan.options.find(o=>o.word===(candidate?.word??s.word)&&o.key===(candidate?.keys[0]||'@word'))||s.plan.options[0];
  const base=s.plan.options.find(o=>o.word===candidate?.word&&o.key===candidate?.keys[1])||s.plan.options.find(o=>o.word===source?.word&&o.key!==source?.key)||s.plan.options.find(o=>o.word!==source?.word);
  if(source)$('redup-source').value=optionKey(source);if(base)$('redup-base').value=optionKey(base);
  const existing=!fresh&&!candidate?s.plan.info.relations.find(r=>!r.review):null;
  if(existing){s.editing=existing.id;$('redup-source').value=optionKey({word:existing.source_word,key:existing.source.key});$('redup-base').value=optionKey({word:existing.base_word,key:existing.base.key});$('redup-type').value=existing.type;$('redup-notes').value=existing.notes;$('redup-save').textContent='更新关系';}
  else if(fresh&&!candidate){$('redup-source').value='';$('redup-base').value='';}
 }
 async function open(kind,id,word=0,draft=null,key=''){
  const ticket=++serial;let data=draft||await api('segmentation?'+new URLSearchParams({kind,id}));
  const plan=await originalApi('reduplication-preview',{body:data.body,_language:data.owner_language});
  if(ticket!==serial)return;
  state={kind,id,word,key,data,plan,draft,busy:false,editing:''};render();$('redup-dialog').showModal();
 }
 async function change(payload){
  const s=state;if(!s||s.busy)return;s.busy=true;$('redup-form').inert=true;$('redup-list').inert=true;$('redup-error').textContent='';
  try{
   const next=await originalApi('reduplication-preview',{body:s.plan.body,...payload,_language:s.data.owner_language});
   if(s.draft){
    // The modal is blocking; apply only relation fields, preserving other drafts.
    s.draft.body.reduplications=next.body.reduplications;
    next.body.words.forEach((w,i)=>{if(w.redup_id)s.draft.body.words[i].redup_id=w.redup_id;else delete s.draft.body.words[i].redup_id;});
    s.draft.dirty=true;s.plan=next;repaintInline(inlineKey(s.kind,s.id));
   }else{
    await api('segmentation-save',{kind:s.kind,id:s.id,revision:s.data.revision,...payload,_language:s.data.owner_language});
    s.data=await api('segmentation?'+new URLSearchParams({kind:s.kind,id:s.id}));
    s.plan=await originalApi('reduplication-preview',{body:s.data.body,_language:s.data.owner_language});
    if(segmentDraft?.kind===s.kind&&segmentDraft?.id===s.id)await refreshSegmentation();else{await refreshUndo();await refreshExampleViews();}
   }
   render();
  }catch(error){$('redup-error').textContent=error.message;}
  finally{s.busy=false;$('redup-form').inert=false;$('redup-list').inert=false;}
 }
 $('redup-form').onsubmit=e=>{e.preventDefault();if(!$('redup-source').value||!$('redup-base').value)return;void change({action:'redup-save',relation_id:state.editing||undefined,source:selection('redup-source'),base:selection('redup-base'),type:$('redup-type').value,notes:$('redup-notes').value});};
 $('redup-new').onclick=()=>reset(true);
 $('redup-list').onclick=e=>{
  const b=e.target.closest('button');if(!b||state.busy)return;
  if(b.dataset.redupDelete)return void change({action:'redup-delete',relation_id:b.dataset.redupDelete});
  const r=state.plan.info.relations.find(r=>r.id===b.dataset.redupEdit);if(!r)return;
  reset(true);state.editing=r.id;$('redup-type').value=r.type;$('redup-notes').value=r.notes;$('redup-save').textContent='更新关系';
  for(const name of ['source','base']){const o=state.plan.options.find(o=>o.word===r[name+'_word']&&o.key===r[name].key);$('redup-'+name).value=o?optionKey(o):'';}
  if(r.review)$('redup-error').textContent='原关系：'+r.source.form+' → '+r.base.form+'。请重新选择当前部分。';
 };
 function closing(e){if(state?.busy)e.preventDefault();}
 $('redup-dialog').addEventListener('cancel',closing);$('redup-dialog').querySelector('form[method="dialog"]').addEventListener('submit',closing);
 $('redup-dialog').addEventListener('close',()=>{serial++;state=null;});
 const originalTools=inlineSlotTools;
 inlineSlotTools=function(d){return originalTools(d).replace('</div>','<button type="button" data-redup-open>关联重叠基底</button></div>');};
 const originalFields=inlineFields;
 inlineFields=function(d){const html=originalFields(d),count=d.body.words.filter(w=>w.form.includes('~')).length;return html+(count?'<small class="redup-candidate">含 ~：可选中词格后关联重叠基底，候选不会自动生效。</small>':'');};
 function summary(e,editable=true){
  const info=e.reduplication_info;
  if(!info)return '';
  const rows=info.relations||[],candidates=info.candidates||[];if(!rows.length&&!candidates.length)return '';
  const title=rows.map(r=>r.source.form+' → '+r.base.form+' · '+kinds[r.type]+(r.review?' · 待核对':'')).join('\n');
  const hint=candidates.length?`~ 候选 ${candidates.length}`:'';
  return `<span class="redup-summary" title="${esc(title)}">${rows.length?`重叠关系 ${rows.length}${rows.some(r=>r.review)?' · 待核对':''}`:''}${hint?(editable?` <button type="button" data-redup-open>${hint}</button>`:' '+hint):''}</span>`;
 }
 window.CorporiumReduplication={summary};
 const originalBody=renderBody;
 renderBody=function(e,...args){return originalBody(e,...args)+summary(e);};
 const draw=drawSegmentation;
 drawSegmentation=function(){draw();$('segment-source').insertAdjacentHTML('beforeend','<button type="button" data-redup-panel>重叠与基底</button>');};
 document.addEventListener('focusin',e=>{const t=e.target;if(!t.matches('.inline-piece.form'))return;const card=t.closest('.editable-example'),d=inlineDrafts.get(card?.dataset.exampleKey);if(d){d.redupWord=+t.dataset.word;d.redupKey=(d.body.words[d.redupWord].form.includes('~')?'r:':'')+Math.floor(+t.dataset.part/2)+':host';}});
 document.addEventListener('click',async e=>{
  const b=e.target.closest('[data-redup-open],[data-redup-panel]');if(!b)return;e.preventDefault();
  try{
   if(b.hasAttribute('data-redup-panel'))return await open(segmentDraft.kind,segmentDraft.id,+$('segment-word').value);
   const card=b.closest('.editable-example');if(!card)return;
   const d=inlineDrafts.get(card.dataset.exampleKey),word=d?Math.max(0,d.words.findIndex(w=>w.id===d.selectedSlot)):0;
   await open(card.dataset.exampleKind,card.dataset.exampleId,word,d,d?.redupWord===word?d.redupKey:'');
  }catch(error){$('notice').textContent=error.message;}
 });
 for(const id of ['field','library-field']){const el=$(id);if(el)el.add(new Option('重叠基底','reduplication'));}
})();
