(()=>{
 const button=document.createElement('button');button.id='dictionary-replace-open';button.textContent='查找替换';$('dictionary-search').after(button);
 const fields={all:'全部可替换文字',headword:'词形',variant:'变体形式',writing:'书写形式',short_gloss:'简短释义',definition:'详细释义',notes:'备注',tag_value:'使用标签值'};
 const morphFields={all:'全部可替换文字',form:'语素形式',variant:'变体形式',writing:'书写形式',short_gloss:'简短释义',definition:'详细释义',readings:'读音',conditions:'变体出现条件',notes:'备注',tag_value:'使用标签值'};
 makeDialog('dictionary-replace-dialog',`<h2>词典查找替换</h2><p class="dr-help">先查找、预览，再逐处或全部替换；每次应用可一步撤销。</p><div class="replace-options"><label>范围<select id="dr-scope"></select></label><label>字段<select id="dr-field"></select></label></div><details id="dr-conditions"><summary>搜索条件<span id="dr-condition-count"></span></summary><label class="dr-query-label">范围检索<input id="dr-query" placeholder="进一步限制条目范围…"></label><div id="dr-condition-controls"></div></details><div class="replace-options"><label>查找<textarea id="dr-find" rows="1"></textarea></label><label>替换为<textarea id="dr-value" rows="1" placeholder="留空表示删除匹配文字"></textarea></label><label>匹配方式<select id="dr-mode"><option value="contains">包含（逐处匹配）</option><option value="exact">整个字段相同</option><option value="prefix">开头</option><option value="suffix">结尾</option></select></label><label><input id="dr-case" type="checkbox"> 区分大小写</label></div><div class="dr-actions"><button id="dr-find-search" aria-label="查找匹配"></button><button id="dr-preview">预览替换</button></div><p id="dr-status" role="status"></p><p id="dr-error" role="alert"></p><div id="dr-results"></div><div class="replace-pagination"><button id="dr-prev">上一页</button><span id="dr-page"></span><button id="dr-next">下一页</button></div><button id="dr-all" class="primary" disabled>替换全部匹配</button>`);
 let plan=null,request=null,language=null,selectedId='',kind='lexeme',controls=null,page=0,busy=false;
 const noun=()=>kind==='morpheme'?'语素':'词条';
 $('dictionary-replace-dialog').addEventListener('cancel',e=>{if(busy)e.preventDefault();});
 function reset(){plan=request=null;page=0;$('dr-results').replaceChildren();$('dr-status').textContent=$('dr-error').textContent=$('dr-page').textContent='';$('dr-all').disabled=$('dr-prev').disabled=$('dr-next').disabled=true;}
 function payload(findOnly=false){return {_language:language,kind,scope:$('dr-scope').value,lexeme_id:kind==='lexeme'?selectedId:'',morpheme_id:kind==='morpheme'?selectedId:'',query:$('dr-query').value,search:controls.get(),field:$('dr-field').value,find:$('dr-find').value,replacement:$('dr-value').value,mode:$('dr-mode').value,case:$('dr-case').checked,find_only:findOnly};}
 function draw(){
  if(!plan)return;const pages=Math.max(1,Math.ceil(plan.changes.length/50));page=Math.max(0,Math.min(page,pages-1));
  $('dr-status').textContent=`范围内 ${plan.records} 个${noun()}，${plan.changes.length} 处匹配。${plan.find_only?'尚未替换；填写替换内容后点击“预览替换”。':plan.conflicts.length?'应用前有 '+plan.conflicts.length+' 项需要确认。':''}${plan.blocked.length?'存在无效结果，请调整或逐处处理。':''}`;
  $('dr-results').innerHTML=plan.blocked.filter(b=>!b.id).map(b=>'<p class="warning">'+esc(b.reason)+'</p>').join('')+plan.changes.slice(page*50,page*50+50).map(c=>{
   const warning=plan.blocked.find(b=>b.id===c.id)||plan.conflicts.find(b=>b.id===c.id),chars=[...c.before],before=`<pre>${esc(chars.slice(0,c.start).join(''))}<mark>${esc(chars.slice(c.start,c.end).join(''))}</mark>${esc(chars.slice(c.end).join(''))}</pre>`;
   return `<article class="replace-row"><strong>${esc(c.title)}</strong><small> · ${esc(c.label)}</small>${plan.find_only?before:`<div class="replace-comparison">${before}<span>→</span><pre>${esc(c.after)}</pre></div>`}${c.read_only?'<small class="dr-readonly">此字段仅供检索，请在原条目或对应管理界面中修改。</small>':''}${warning?'<p class="warning">'+esc(warning.reason)+'</p>':''}${plan.find_only?'':`<button data-dr-one="${esc(c.key)}">替换此处</button>`}</article>`;
  }).join('')||'<p class="empty">没有找到匹配内容。</p>';
  $('dr-page').textContent=(page+1)+' / '+pages;$('dr-prev').disabled=page===0;$('dr-next').disabled=page+1>=pages;$('dr-all').disabled=!!plan.find_only||!plan.changes.length||!!plan.blocked.length;
 }
 function lock(value){busy=value;$('dictionary-replace-dialog').querySelectorAll('button,input,textarea,select').forEach(e=>e.disabled=value);if(!value){controls?.updateDisabled?.();if(plan)draw();else $('dr-all').disabled=$('dr-prev').disabled=$('dr-next').disabled=true;}}
 async function preview(keepScope=false,findOnly=false){const ids=keepScope?request?.scope_ids:null;request=payload(findOnly);if(ids)request.scope_ids=ids;plan=await api('dictionary-replace-preview',request);if(plan.scope_ids)request.scope_ids=plan.scope_ids;page=0;draw();}
 async function run(findOnly){if(busy)return;reset();lock(true);$('dr-status').textContent='正在查找并核对…';try{await preview(false,findOnly);}catch(e){$('dr-status').textContent='';$('dr-error').textContent=e.message;}finally{lock(false);}}
 button.onclick=dictSafe(async()=>{
  if(activeLanguage==='all')throw Error('请先选择一个语言工作区');if(inlineDrafts.size||infoDirty||($('lexeme-editor').open&&lexemeDirty)||window.corporiumMorphemeDirty?.())throw Error('请先保存或取消正在编辑的内容');
  const scope=window.dictionarySearchScope();language=activeLanguage;kind=scope.kind;selectedId=(kind==='morpheme'?window.dictionaryMorphemeSelection?.():dictionarySelection)||'';reset();
  $('dr-field').innerHTML=Object.entries(kind==='morpheme'?morphFields:fields).map(([v,n])=>`<option value="${v}">${n}</option>`).join('');const field={ 'variants.form':'variant','orthographies.text':'writing','writings.text':'writing',gloss:'short_gloss','usages.senses.short_gloss':'short_gloss','senses.gloss':'short_gloss','senses.definition':'definition','usages.senses.definition':'definition'}[scope.search.field]||scope.search.field;$('dr-field').value=(kind==='morpheme'?morphFields:fields)[field]?field:'all';
  $('dr-query').value=scope.query;$('dr-find').value=scope.query;$('dr-value').value='';$('dr-case').checked=!!scope.search.case;$('dr-mode').value='contains';$('dr-scope').innerHTML='<option value="search">当前条件下的所有'+noun()+'（所有页面）</option>'+(selectedId?'<option value="current">当前'+noun()+'</option>':'')+'<option value="language">当前语言'+noun()+'</option>';
  const count=()=>{$('dr-condition-count').textContent=controls?.count()?'（'+controls.count()+'）':'';reset();};controls=window.createDictionaryConditions($('dr-condition-controls'),{prefix:'dr-filter',catalog:scope.catalog,kind,value:scope.search,onchange:count,onclear:()=>{$('dr-query').value='';}});$('dr-condition-count').textContent=controls.count()?'（'+controls.count()+'）':'';$('dr-conditions').open=false;
  $('dr-find-search').innerHTML=window.dictionarySearchIcon;$('dictionary-replace-dialog').showModal();if(scope.query.trim())await run(true);
 });
 for(const id of ['dr-scope','dr-field','dr-query','dr-find','dr-value','dr-mode','dr-case'])$(id).addEventListener('input',reset);
 $('dr-preview').onclick=()=>run(false);$('dr-find-search').onclick=()=>run(true);
 $('dictionary-replace-dialog').addEventListener('keydown',e=>{if(e.key==='Enter'&&e.target.matches('input')){e.preventDefault();run(true);}});
 async function apply(keys){
  if(busy||!plan||plan.find_only)return;const args={...request,token:plan.token,keys,pending_keys:plan.changes.map(c=>c.key)};lock(true);$('dr-error').textContent='';let applied=null,message='';
  try{
   let result=await api('dictionary-replace-apply',args);if(result.needs_confirmation){if(!await corporiumConfirm(result.conflicts.slice(0,10).map(c=>c.title+'：'+c.reason).join('\n')+'\n\n继续替换并保留独立记录？'))return;result=await api('dictionary-replace-apply',{...args,confirm_conflicts:true});}applied=result;
   await refreshUndo();await loadDictionary();
   if(result.remaining_keys.length){await preview(true);const remain=new Set(result.remaining_keys);plan.changes=plan.changes.filter(c=>remain.has(c.key));draw();}else{plan.changes=[];draw();}
   message=`已替换 ${result.replacements} 处，涉及 ${result.records??result.lexemes} 个${noun()}，可撤销。剩余 ${plan.changes.length} 处。`;
  }catch(e){plan=null;$('dr-results').replaceChildren();$('dr-error').textContent=(applied?'替换已保存，但刷新失败：':'')+e.message+'；请重新预览。';}
  finally{lock(false);if(message)$('dr-status').textContent=message;}
 }
 $('dr-results').onclick=e=>{const b=e.target.closest('[data-dr-one]');if(b)apply([b.dataset.drOne]);};
 $('dr-all').onclick=async()=>{if(plan&&!plan.find_only&&await corporiumConfirm(`替换预览中的全部 ${plan.changes.length} 处匹配？`))apply(plan.changes.map(c=>c.key));};
 $('dr-prev').onclick=()=>{page--;draw();};$('dr-next').onclick=()=>{page++;draw();};
})();
