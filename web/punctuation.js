const punctuationSelection=new Set();let punctuationScope=null,punctuationPlan=null,punctuationLanguage=null,punctuationBusy=false;
const punctuationTextButton=document.createElement('button');punctuationTextButton.textContent='识别并拆分标点';punctuationTextButton.id='punctuation-text';document.querySelector('.actions').append(punctuationTextButton);
punctuationTextButton.onclick=safe(async()=>{if(!selected)throw Error('请先选择一个文本');await openPunctuation({text_id:selected});});
const punctuationBatch=document.createElement('button');punctuationBatch.id='punctuation-batch';punctuationBatch.textContent='拆分所选独立例句标点';punctuationBatch.disabled=true;$('library-search').after(punctuationBatch);
punctuationBatch.onclick=safe(()=>openPunctuation({records:[...punctuationSelection].map(id=>({kind:'independent',id}))}));
makeDialog('punctuation-dialog','<h2>识别并拆分标点</h2><p id="punctuation-scope"></p><p>只拆语素格，原标注和附加层保留在剩余词上。IPA、自由翻译不变。多个剩余词及复杂形态分析列为待处理。</p><label>识别的标点（每行一个；较长的标点优先）<textarea id="punctuation-symbols" rows="5"></textarea></label><label><input id="punctuation-internal" type="checkbox">同时识别格子内部标点（默认仅首尾）</label><p>不要加入有形态或音系用途的符号，除非确认当前材料将其用作标点。</p><button id="punctuation-preview">预览拆分</button><p id="punctuation-status" role="status"></p><div id="punctuation-results"></div><p id="punctuation-error" role="alert"></p><button id="punctuation-apply" class="primary" disabled>确认应用</button>');
function resetPunctuation(){punctuationPlan=null;$('punctuation-apply').disabled=true;$('punctuation-results').replaceChildren();$('punctuation-status').textContent='';$('punctuation-error').textContent='';}
async function openPunctuation(scope){
 if(activeLanguage==='all')throw Error('请先选择一个语言');
 if(inlineDrafts.size)throw Error('请先保存或取消正在编辑的标注');
 if(scope.records&&!scope.records.length)throw Error('请先在例句库勾选独立例句');
 punctuationLanguage=activeLanguage;punctuationScope=scope;resetPunctuation();
 const opts=await api('punctuation-settings?language='+encodeURIComponent(activeLanguage));$('punctuation-symbols').value=opts.symbols.join('\n');$('punctuation-internal').checked=opts.internal;
 $('punctuation-scope').textContent=scope.text_id?'范围：当前整个文本（所有页面）':'范围：所选 '+scope.records.length+' 条例句';$('punctuation-dialog').showModal();
}
$('punctuation-symbols').oninput=$('punctuation-internal').onchange=resetPunctuation;
$('punctuation-preview').onclick=async()=>{
 if(punctuationBusy)return;punctuationBusy=true;resetPunctuation();$('punctuation-preview').disabled=true;$('punctuation-symbols').disabled=$('punctuation-internal').disabled=true;
 try{
  const request={...punctuationScope,_language:punctuationLanguage,symbols:$('punctuation-symbols').value.split('\n').map(s=>s.trim()).filter(Boolean),internal:$('punctuation-internal').checked};
  let plan=await api('punctuation-preview',request);
  if(plan.needs_bang_confirmation){if(!await corporiumConfirm('请确认当前文本的感叹号 ! 不是搭嘴音符号'))return;request.bang_confirmed=true;plan=await api('punctuation-preview',request);}
  punctuationPlan={request,token:plan.token};
  $('punctuation-status').textContent=`检查 ${plan.record_count} 条例句；可处理 ${plan.changes.length} 个格子；待人工处理 ${plan.blocked.length} 个。确认时同时保存本语言的标点设置。`;
  const rows=(items,blocked)=>items.slice(0,200).map(c=>`<article class="punctuation-preview-row"><small>${esc(c.title)} · 第 ${c.word+1} 格</small><p>${esc(c.before)} → ${c.pieces.map(p=>`<span class="punctuation-preview-cell ${p.punctuation?'is-punctuation':''}">${esc(p.form)}<small>${p.punctuation?'标点':blocked?'标注待分配':esc(c.gloss)}</small></span>`).join(' ')}</p>${blocked?'<p>'+esc(c.reason)+'</p>':''}</article>`).join('');
  $('punctuation-results').innerHTML='<h3>可处理</h3>'+rows(plan.changes,false)+(plan.changes.length>200?'<p>预览仅展示前 200 个格子；确认处理全部可处理项。</p>':'')+(plan.blocked.length?'<h3>待处理（保持原样）</h3>'+rows(plan.blocked,true):'');$('punctuation-apply').disabled=false;
 }catch(e){$('punctuation-error').textContent=e.message;}finally{punctuationBusy=false;$('punctuation-preview').disabled=false;$('punctuation-symbols').disabled=$('punctuation-internal').disabled=false;}
};
$('punctuation-apply').onclick=async()=>{
 if(!punctuationPlan||punctuationBusy)return;punctuationBusy=true;const plan=punctuationPlan;$('punctuation-apply').disabled=$('punctuation-preview').disabled=true;
 try{const result=await api('punctuation-apply',{...plan.request,token:plan.token});resetPunctuation();$('punctuation-status').textContent=`已处理 ${result.sentences} 条例句、${result.cells} 个格子；跳过 ${result.skipped} 个待处理格子。可一次撤销。`;await loadLanguages();await refreshExampleViews();}catch(e){resetPunctuation();$('punctuation-error').textContent=e.message;}finally{punctuationBusy=false;$('punctuation-preview').disabled=false;}
};
document.addEventListener('click',e=>{const b=e.target.closest('[data-punctuation-single]');if(!b)return;const card=b.closest('.editable-example');safe(()=>openPunctuation({records:[{kind:card.dataset.exampleKind,id:card.dataset.exampleId}]}))();});
document.addEventListener('change',e=>{if(e.target.matches('[data-punctuation-select]')){const id=e.target.dataset.punctuationSelect;if(e.target.checked)punctuationSelection.add(id);else punctuationSelection.delete(id);punctuationBatch.textContent='拆分所选独立例句标点（'+punctuationSelection.size+'）';punctuationBatch.disabled=!punctuationSelection.size;}});
const punctuationLoadLibrary=loadLibrary;loadLibrary=async function(){await punctuationLoadLibrary();for(const c of $('library-results').querySelectorAll('[data-punctuation-select]'))c.checked=punctuationSelection.has(c.dataset.punctuationSelect);};
const punctuationSwitch=switchLanguage;switchLanguage=async function(...args){punctuationSelection.clear();punctuationBatch.disabled=true;punctuationBatch.textContent='拆分所选独立例句标点';return punctuationSwitch(...args);};

const punctuationClear=document.createElement('button');punctuationClear.textContent='取消标点拆分选择';punctuationBatch.after(punctuationClear);punctuationClear.onclick=()=>{punctuationSelection.clear();punctuationBatch.disabled=true;punctuationBatch.textContent='拆分所选独立例句标点';for(const c of $('library-results').querySelectorAll('[data-punctuation-select]'))c.checked=false;};
