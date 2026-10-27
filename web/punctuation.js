let punctuationScope=null,punctuationPlan=null,punctuationLanguage=null,punctuationBusy=false;
const punctuationTextButton=document.createElement('button');punctuationTextButton.textContent=(globalThis.CorporiumI18n?.f("53830a66c9e6e2",()=>[])??'识别并拆分标点');punctuationTextButton.id='punctuation-text';document.querySelector('.actions').append(punctuationTextButton);
punctuationTextButton.onclick=safe(async()=>{if(!selected)throw Error((globalThis.CorporiumI18n?.f("a459be346634fe",()=>[])??'请先选择一个文本'));await openPunctuation({text_id:selected});});
makeDialog('punctuation-dialog',(globalThis.CorporiumI18n?.f("27dc0ba7b2daab",()=>[])??'<h2>识别并拆分标点</h2><p id="punctuation-scope"></p><p>只拆语素格，原标注和附加层保留在剩余词上。IPA、自由翻译不变。多个剩余词及复杂形态分析列为待处理。</p><label>识别的标点（每行一个；较长的标点优先）<textarea id="punctuation-symbols" rows="5"></textarea></label><label><input id="punctuation-internal" type="checkbox">同时识别格子内部标点（默认仅首尾）</label><p>不要加入有形态或音系用途的符号，除非确认当前材料将其用作标点。</p><button id="punctuation-preview">预览拆分</button><p id="punctuation-status" role="status"></p><div id="punctuation-results"></div><p id="punctuation-error" role="alert"></p><button id="punctuation-apply" class="primary" disabled>确认应用</button>'));
function resetPunctuation(){punctuationPlan=null;$('punctuation-apply').disabled=true;$('punctuation-results').replaceChildren();$('punctuation-status').textContent='';$('punctuation-error').textContent='';}
async function openPunctuation(scope){
 if(activeLanguage==='all')throw Error((globalThis.CorporiumI18n?.f("abc3aeeaad6b09",()=>[])??'请先选择一个语言'));
 if(inlineDrafts.size)throw Error((globalThis.CorporiumI18n?.f("927ad2da9df281",()=>[])??'请先保存或取消正在编辑的标注'));
 if(scope.records&&!scope.records.length)throw Error((globalThis.CorporiumI18n?.f("40c0f673488e99",()=>[])??'请先在例句库勾选独立例句'));
 punctuationLanguage=activeLanguage;punctuationScope=scope;resetPunctuation();
 const opts=await api('punctuation-settings?language='+encodeURIComponent(activeLanguage));$('punctuation-symbols').value=opts.symbols.join('\n');$('punctuation-internal').checked=opts.internal;
 $('punctuation-scope').textContent=scope.text_id?(globalThis.CorporiumI18n?.f("eb6bdf0e1e868a",()=>[])??'范围：当前整个文本（所有页面）'):(globalThis.CorporiumI18n?.f("d21cc3a70232dc",()=>[scope.records.length])??'范围：所选 '+scope.records.length+' 条例句');$('punctuation-dialog').showModal();
}
$('punctuation-symbols').oninput=$('punctuation-internal').onchange=resetPunctuation;
$('punctuation-preview').onclick=async()=>{
 if(punctuationBusy)return;punctuationBusy=true;resetPunctuation();$('punctuation-preview').disabled=true;$('punctuation-symbols').disabled=$('punctuation-internal').disabled=true;
 try{
  const request={...punctuationScope,_language:punctuationLanguage,symbols:$('punctuation-symbols').value.split('\n').map(s=>s.trim()).filter(Boolean),internal:$('punctuation-internal').checked};
  let plan=await api('punctuation-preview',request);
  if(plan.needs_bang_confirmation){if(!await corporiumConfirm((globalThis.CorporiumI18n?.f("2ce88f20ab0355",()=>[])??'请确认当前文本的感叹号 ! 不是搭嘴音符号')))return;request.bang_confirmed=true;plan=await api('punctuation-preview',request);}
  punctuationPlan={request,token:plan.token};
  $('punctuation-status').textContent=(globalThis.CorporiumI18n?.f("eb323de516c259",()=>[plan.record_count,plan.changes.length,plan.blocked.length])??`检查 ${plan.record_count} 条例句；可处理 ${plan.changes.length} 个格子；待人工处理 ${plan.blocked.length} 个。确认时同时保存本语言的标点设置。`);
  const rows=(items,blocked)=>items.slice(0,200).map(c=>(globalThis.CorporiumI18n?.f("037c61ecbfe790",()=>[esc(c.title),c.word+1,esc(c.before),c.pieces.map(p=>`<span class="punctuation-preview-cell ${p.punctuation?'is-punctuation':''}">${esc(p.form)}<small>${p.punctuation?(globalThis.CorporiumI18n?.f("d9e0808b2b5b48",()=>[])??'标点'):blocked?(globalThis.CorporiumI18n?.f("1441fd61a4ae3b",()=>[])??'标注待分配'):esc(c.gloss)}</small></span>`).join(' '),blocked?'<p>'+esc(c.reason)+'</p>':''])??`<article class="punctuation-preview-row"><small>${esc(c.title)} · 第 ${c.word+1} 格</small><p>${esc(c.before)} → ${c.pieces.map(p=>`<span class="punctuation-preview-cell ${p.punctuation?'is-punctuation':''}">${esc(p.form)}<small>${p.punctuation?'标点':blocked?'标注待分配':esc(c.gloss)}</small></span>`).join(' ')}</p>${blocked?'<p>'+esc(c.reason)+'</p>':''}</article>`)).join('');
  $('punctuation-results').innerHTML=(globalThis.CorporiumI18n?.f("bbdfc5ee94b5bb",()=>[rows(plan.changes,false),plan.changes.length>200?(globalThis.CorporiumI18n?.f("a922c1e03db8ca",()=>[])??'<p>预览仅展示前 200 个格子；确认处理全部可处理项。</p>'):'',plan.blocked.length?(globalThis.CorporiumI18n?.f("f5146755891792",()=>[rows(plan.blocked,true)])??'<h3>待处理（保持原样）</h3>'+rows(plan.blocked,true)):''])??'<h3>可处理</h3>'+rows(plan.changes,false)+(plan.changes.length>200?'<p>预览仅展示前 200 个格子；确认处理全部可处理项。</p>':'')+(plan.blocked.length?'<h3>待处理（保持原样）</h3>'+rows(plan.blocked,true):''));$('punctuation-apply').disabled=false;
 }catch(e){$('punctuation-error').textContent=e.message;}finally{punctuationBusy=false;$('punctuation-preview').disabled=false;$('punctuation-symbols').disabled=$('punctuation-internal').disabled=false;}
};
$('punctuation-apply').onclick=async()=>{
 if(!punctuationPlan||punctuationBusy)return;punctuationBusy=true;const plan=punctuationPlan;$('punctuation-apply').disabled=$('punctuation-preview').disabled=true;
 try{const result=await api('punctuation-apply',{...plan.request,token:plan.token});resetPunctuation();$('punctuation-status').textContent=(globalThis.CorporiumI18n?.f("46925085a252b5",()=>[result.sentences,result.cells,result.skipped])??`已处理 ${result.sentences} 条例句、${result.cells} 个格子；跳过 ${result.skipped} 个待处理格子。可一次撤销。`);await loadLanguages();await refreshExampleViews();}catch(e){resetPunctuation();$('punctuation-error').textContent=e.message;}finally{punctuationBusy=false;$('punctuation-preview').disabled=false;}
};
document.addEventListener('click',e=>{const b=e.target.closest('[data-punctuation-single]');if(!b)return;const card=b.closest('.editable-example');safe(()=>openPunctuation({records:[{kind:card.dataset.exampleKind,id:card.dataset.exampleId}]}))();});

