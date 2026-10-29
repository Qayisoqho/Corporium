// Additional headword representations and conservative bulk linking.
const orthographyFonts=availableFonts;
function orthographyFont(value){return validFont(value)?value:'serif';}
function orthographyStyle(value){const font=orthographyFont(value);return ['serif','sans-serif'].includes(font)?font:`&quot;${font}&quot;,serif`;}
function addOrthography(value={}){
  const row=document.createElement('section');row.className='orthography-editor';row.dataset.id=value.id||'';
  row.innerHTML=(globalThis.CorporiumI18n?.f("0fb9a5d043c77f",()=>[esc(value.label||''),esc(value.text||''),fontChoices()])??`<label>名称<input class="orthography-label" placeholder="IPA、汉字或其他转写" value="${esc(value.label||'')}"></label><label>内容<input class="orthography-text" value="${esc(value.text||'')}"></label><label>字体<select class="orthography-font">${fontChoices()}</select></label><button type="button" class="remove-orthography">移除</button>`);
  const font=row.querySelector('select'),content=row.querySelector('.orthography-text');selectFont(font,orthographyFont(value.font||'Junicode'));
  const preview=()=>content.style.fontFamily=['serif','sans-serif'].includes(font.value)?font.value:`"${font.value}", serif`;font.addEventListener('change',preview);preview();
  row.querySelector('button').onclick=()=>{row.remove();lexemeDirty=true;};$('lexeme-orthographies').append(row);
}

const autoButton=document.createElement('button');autoButton.id='auto-link-open';autoButton.textContent=(globalThis.CorporiumI18n?.f("32ef47c39ccaf9",()=>[])??'自动关联词典');workspaceTabs.append(autoButton);
makeDialog('auto-link-dialog',(globalThis.CorporiumI18n?.f("7681b55489796b",()=>[])??'<h2>自动关联词典</h2><p>词形须完全一致；标注须完整匹配义项简短释义与条目、词类用法、具体形式的固有特征。普通尾部标签按标签库识别（含别名），允许调整顺序，不能缺少或多出特征。匹配整词和切分后的语素；不重复关联未切分的单个语素。</p><p>已登记的形式变体参与匹配；自定义书写形式不参与。复杂关系、括号和语素边界保留结构，不推断其与固有特征的组合。已有的关联会保留；多个条目或意义同时匹配时，留待手动选择。</p><label>搜索范围<select id="auto-link-scope"></select></label><fieldset id="auto-mark-options"><legend>忽略词形标记的候选（需勾选确认）</legend><label><input type="checkbox" value="-" checked> -</label> <label><input type="checkbox" value="=" checked> =</label> <label><input type="checkbox" value="." checked> .</label><label>忽略位置<select id="auto-mark-position"><option value="edges">仅首尾</option><option value="all">包含内部</option></select></label><small>比较去掉所选标记后的完整单位，不查找任意子串。完全匹配排前；同标注的忽略标记候选仍会列出，多目标需选择。</small></fieldset><button id="auto-link-preview">预览匹配</button><p id="auto-link-summary" role="status"></p><div id="auto-link-results"></div><p id="auto-link-error" role="alert"></p><button id="auto-link-apply" class="primary" disabled>关联全部唯一匹配</button><span id="auto-candidate-actions" hidden><label><input type="checkbox" id="auto-candidate-all"> 选择全部无歧义项</label><button id="auto-candidate-apply" disabled>确认关联所选候选</button><small id="auto-candidate-selection" role="status"></small></span>'));
let autoPlan=null,autoLanguage=null,autoSequence=0,autoCandidateSelection=null,autoBusy=false,autoShown=0;
function resetAutoPlan(){autoSequence++;autoPlan=null;autoCandidateSelection=null;$('auto-candidate-actions').hidden=true;$('auto-candidate-all').checked=false;$('auto-candidate-all').indeterminate=false;$('auto-candidate-selection').textContent='';$('auto-link-apply').disabled=true;$('auto-candidate-apply').disabled=true;$('auto-link-results').replaceChildren();$('auto-link-summary').textContent='';$('auto-link-error').textContent='';}
autoButton.onclick=()=>{
  if(autoBusy)return;
  if(activeLanguage==='all'){$('notice').textContent=(globalThis.CorporiumI18n?.f("eb4ff1c1c1de7f",()=>[])??'请先选择一个语言，再自动关联词典。');return;}
  autoLanguage=activeLanguage;resetAutoPlan();
  $('auto-link-scope').innerHTML=(globalThis.CorporiumI18n?.f("28dd07d7e933f4",()=>[texts.filter(t=>t.language_id===activeLanguage).map(t=>`<option value="${esc(t.id)}">${esc(t.title)}</option>`).join('')])??'<option value="">本语言全部文本（含独立例句）</option><option value="@independent">独立例句库</option>'+texts.filter(t=>t.language_id===activeLanguage).map(t=>`<option value="${esc(t.id)}">${esc(t.title)}</option>`).join(''));
  $('auto-link-scope').value=workspace==='library'?'@independent':workspace==='corpus'&&selected?selected:'';$('auto-link-dialog').showModal();
};
$('auto-link-scope').onchange=resetAutoPlan;
$('auto-mark-options').onchange=resetAutoPlan;
function autoMarkOptions(){return {ignore_symbols:[...$('auto-mark-options').querySelectorAll('input:checked')].map(e=>e.value).join(''),ignore_position:$('auto-mark-position').value};}
function autoMatchPair(row){
 const lid=row.effective_language_id||autoLanguage,metadata=JSON.parse(languageList.find(l=>l.id===lid)?.metadata||'{}');
 return `<span class="language-body auto-match-pair" style="${languageTypography(metadata)}"><span class="form">${rich(row.form)}</span> — <span class="gloss">${richGloss(row.gloss,lid)}</span></span>`;
}
function drawAutoPlan(plan,previous=null,shown=0){
 autoPlan=plan;autoCandidateSelection=null;autoShown=0;
 $('auto-candidate-actions').hidden=true;$('auto-candidate-apply').disabled=true;
 $('auto-candidate-all').checked=false;$('auto-candidate-all').indeterminate=false;
 $('auto-candidate-selection').textContent='';
 $('auto-link-summary').textContent=(globalThis.CorporiumI18n?.f("661ddb1591a884",()=>[plan.matches.length,plan.ambiguous.length,plan.already_linked,plan.suggestions.length])??`可关联 ${plan.matches.length} 处；有歧义 ${plan.ambiguous.length} 处；已有匹配关联 ${plan.already_linked} 处；需确认候选 ${plan.suggestions.length} 项。`);
 const cards=(rows,ambiguous)=>rows.slice(0,100).map(r=>(globalThis.CorporiumI18n?.f("372a030b558f08",()=>[autoMatchPair(r),esc(r.title),r.sentence_position,r.kind==='word'?(globalThis.CorporiumI18n?.f("e466908867c352",()=>[])??'整词'):(globalThis.CorporiumI18n?.f("9116310b3dd568",()=>[])??'语素'),ambiguous?(globalThis.CorporiumI18n?.f("ae786fca591034",()=>[r.candidates.map(c=>esc(dictionaryCandidateLabel(c))).join('；')])??'待手动选择：'+r.candidates.map(c=>esc(dictionaryCandidateLabel(c))).join('；')):esc(dictionaryCandidateLabel(r)),!ambiguous?'<p class="auto-match-reason">'+esc(r.match_reason)+'</p>':''])??`<div class="auto-match">${autoMatchPair(r)}<br><small>${esc(r.title)} · 第 ${r.sentence_position} 句 · ${r.kind==='word'?'整词':'语素'}</small><p>${ambiguous?'待手动选择：'+r.candidates.map(c=>esc(dictionaryCandidateLabel(c))).join('；'):esc(dictionaryCandidateLabel(r))}</p>${!ambiguous?'<p class="auto-match-reason">'+esc(r.match_reason)+'</p>':''}</div>`)).join('');
 $('auto-link-results').innerHTML=(globalThis.CorporiumI18n?.f("c2c528973de897",()=>[cards(plan.matches,false),plan.matches.length>100?(globalThis.CorporiumI18n?.f("45d46d79664e2c",()=>[])??'<p>仅展示前 100 处，执行时关联全部唯一匹配。</p>'):'',plan.ambiguous.length?(globalThis.CorporiumI18n?.f("06adead58e0af5",()=>[cards(plan.ambiguous,true),plan.ambiguous.length>100?(globalThis.CorporiumI18n?.f("ec1feef9ec2be4",()=>[])??'<p>仅展示前 100 处歧义匹配。</p>'):''])??'<h3>歧义匹配（跳过）</h3>'+cards(plan.ambiguous,true)+(plan.ambiguous.length>100?'<p>仅展示前 100 处歧义匹配。</p>':'')):''])??'<h3>唯一匹配</h3>'+cards(plan.matches,false)+(plan.matches.length>100?'<p>仅展示前 100 处，执行时关联全部唯一匹配。</p>':'')+(plan.ambiguous.length?'<h3>歧义匹配（跳过）</h3>'+cards(plan.ambiguous,true)+(plan.ambiguous.length>100?'<p>仅展示前 100 处歧义匹配。</p>':''):''));
 renderAutoSuggestions(plan,previous,shown);
 $('auto-link-apply').disabled=!plan.matches.length;
}
function autoPreviewRequest(plan=null){return 'lexeme-auto-preview?'+new URLSearchParams({language:autoLanguage,text_id:plan?plan.text_id:$('auto-link-scope').value,...(plan?{ignore_symbols:plan.ignore_symbols,ignore_position:plan.ignore_position}:autoMarkOptions())});}
$('auto-link-preview').onclick=async()=>{
 if(autoBusy)return;resetAutoPlan();const seq=autoSequence;$('auto-link-preview').disabled=true;
 try{const plan=await api(autoPreviewRequest());if(seq===autoSequence)drawAutoPlan(plan);}
 catch(e){if(seq===autoSequence)$('auto-link-error').textContent=e.message;}
 finally{$('auto-link-preview').disabled=false;}
};
// Bulk selection never chooses between competing targets for the same occurrence.
function createAutoCandidateSelection(rows,previous=null){
 const byId=new Map(rows.map(r=>[r.candidate_id,r])),groups=new Map(),selected=new Set();
 for(const r of rows){if(!groups.has(r.unit_id))groups.set(r.unit_id,[]);groups.get(r.unit_id).push(r.candidate_id);}
 const unique=[...groups.values()].filter(ids=>ids.length===1&&!byId.get(ids[0]).conflicts?.length).map(ids=>ids[0]);
 for(const id of unique)if(previous===null&&byId.get(id).default_selected)selected.add(id);
 if(previous!==null)for(const id of previous)if(byId.has(id))selected.add(id);
 return {selected,describe(id){const row=byId.get(id);if(!row)return null;const peers=groups.get(row.unit_id);return {total:peers.length,index:peers.indexOf(id)+1,overlap:(row.conflicts||[]).some(peer=>byId.get(peer)?.unit_id!==row.unit_id)};},toggle(id,checked){const row=byId.get(id);if(!row)return;if(checked){for(const peer of [...groups.get(row.unit_id),...(row.conflicts||[])])selected.delete(peer);selected.add(id);}else selected.delete(id);},toggleAll(checked){if(!checked)selected.clear();else for(const id of unique)selected.add(id);},state(){const checked=unique.length>0&&selected.size>0&&unique.every(id=>selected.has(id));return {checked,indeterminate:selected.size>0&&!checked,count:selected.size,ambiguous:[...groups.values()].filter(ids=>ids.length>1&&!ids.some(id=>selected.has(id))).length};}};
}
function autoCandidateNotice(selection,id){
 const choice=selection.describe(id);if(!choice)return '';
 const notes=[];
 if(choice.total>1)notes.push(globalThis.CorporiumI18n?.ui(`同一用例 · 候选 ${choice.index} / ${choice.total} · 请选一项`,`Same occurrence · option ${choice.index} / ${choice.total} · choose one`)??`同一用例 · 候选 ${choice.index} / ${choice.total} · 请选一项`);
 if(choice.overlap)notes.push(globalThis.CorporiumI18n?.ui('与其他候选共用语素片段，需手动选择','Shares morpheme segments with another candidate; choose manually')??'与其他候选共用语素片段，需手动选择');
 return notes.join('；');
}
function renderAutoSuggestions(plan,previous=null,shownBefore=0){
 for(const w of (plan.multipart_warnings||[]).slice(0,20)){const p=document.createElement('p');p.className='warning';p.textContent=(globalThis.CorporiumI18n?.f("4d758605140eca",()=>[w.word+1,w.reason])??'第 '+(w.word+1)+' 词：'+w.reason);$('auto-link-results').append(p);}
 if(!plan.suggestions.length)return;
 const selection=autoCandidateSelection=createAutoCandidateSelection(plan.suggestions,previous);$('auto-candidate-actions').hidden=false;
 const section=document.createElement('section');section.innerHTML=(globalThis.CorporiumI18n?.f("3d4815dfe058ad",()=>[])??'<h3>需确认的关联候选</h3><p>含多部分组合及忽略词形标记的匹配。唯一且无冲突的候选可默认勾选；共用片段或多个目标需手动选择，确认后才保存组合和关联。</p><div class="candidate-list"></div><button type="button">显示更多候选</button>');$('auto-link-results').append(section);
 const list=section.querySelector('.candidate-list'),more=section.querySelector('button');let shown=0;
 const sync=()=>{for(const c of list.querySelectorAll('[data-auto-candidate]'))c.checked=selection.selected.has(c.dataset.autoCandidate);const state=selection.state();$('auto-candidate-all').checked=state.checked;$('auto-candidate-all').indeterminate=state.indeterminate;$('auto-candidate-apply').disabled=!state.count;$('auto-candidate-selection').textContent=(globalThis.CorporiumI18n?.f("828831a8bf9cb0",()=>[state.count,state.ambiguous?(globalThis.CorporiumI18n?.f("16726a9a47c593",()=>[state.ambiguous])??' · '+state.ambiguous+' 处有多个目标，未自动勾选；请选一项'):''])??'已选 '+state.count+' 项'+(state.ambiguous?' · '+state.ambiguous+' 处有多个目标，未自动勾选；请选一项':''));};
 $('auto-candidate-all').title=(globalThis.CorporiumI18n?.f("7141b4bb62fc3e",()=>[])??'勾选全部无歧义且无冲突的候选，包括尚未展开项；多目标或共用片段须手选，取消勾选会清空选择');
 $('auto-candidate-all').onchange=e=>{selection.toggleAll(e.target.checked);sync();};
 const add=()=>{const end=Math.min(shown+Math.max(50,shownBefore),plan.suggestions.length);shownBefore=0;for(;shown<end;shown++){const r=plan.suggestions[shown];const row=document.createElement('label');row.className='auto-match candidate-choice';row.innerHTML=(globalThis.CorporiumI18n?.f("29468538b235ff",()=>[esc(r.candidate_id),esc(r.unit_id),autoMatchPair(r),esc(r.title),r.sentence_position,r.kind==='word'?(globalThis.CorporiumI18n?.f("2f535e1061fe54",()=>[])??'整词'):(globalThis.CorporiumI18n?.f("66c838a5dc04b7",()=>[])??'语素'),esc(dictionaryCandidateLabel(r)),r.target_kind==='morpheme'?(globalThis.CorporiumI18n?.f("c05362a83bfd13",()=>[])??'意义／功能'):(globalThis.CorporiumI18n?.f("23416f8e7f5d68",()=>[esc(r.sense_label)])??'义项 '+esc(r.sense_label)),esc(r.short_gloss),r.definition?'（'+esc(r.definition)+'）':'',r.form_id?(globalThis.CorporiumI18n?.f("4eaffd4c808510",()=>[esc(r.matched_form)])??' / 形式：'+esc(r.matched_form)):'',esc(r.match_reason)])??`<input type="checkbox" data-auto-candidate="${esc(r.candidate_id)}" data-unit="${esc(r.unit_id)}"><span>${autoMatchPair(r)}<br><small>${esc(r.title)} · 第 ${r.sentence_position} 句 · ${r.kind==='word'?'整词':'语素'}</small><p>目标：${esc(dictionaryCandidateLabel(r))} / ${r.target_kind==='morpheme'?'意义／功能':'义项 '+esc(r.sense_label)}：${esc(r.short_gloss)}${r.definition?'（'+esc(r.definition)+'）':''}${r.form_id?' / 形式：'+esc(r.matched_form):''}</p><p>${esc(r.match_reason)}</p></span>`);const notice=autoCandidateNotice(selection,r.candidate_id);if(notice){const note=document.createElement('small');note.className='auto-candidate-note';note.textContent=notice;row.querySelector(':scope > span').prepend(note);}list.append(row);}autoShown=shown;more.hidden=shown===plan.suggestions.length;more.textContent=(globalThis.CorporiumI18n?.f("bc4fa2306b246c",()=>[shown,plan.suggestions.length])??`显示更多候选（${shown} / ${plan.suggestions.length}）`);sync();};more.onclick=add;add();
 list.onchange=e=>{if(!e.target.matches('[data-auto-candidate]'))return;selection.toggle(e.target.dataset.autoCandidate,e.target.checked);sync();};
}
function lockAutoLinks(busy){
 autoBusy=busy;
 for(const id of ['auto-link-apply','auto-candidate-apply','auto-candidate-all','auto-link-preview','auto-link-clear','auto-link-scope','auto-mark-options'])$(id).disabled=busy;
 for(const input of $('auto-link-results').querySelectorAll('[data-auto-candidate],button'))input.disabled=busy;
 if(!busy){$('auto-link-apply').disabled=!autoPlan?.matches.length;$('auto-candidate-apply').disabled=!autoCandidateSelection?.selected.size;}
}
async function applyAutoLinks(mode){
 if(autoBusy||!autoPlan)return;
 const plan=autoPlan,selected=[...(autoCandidateSelection?.selected||[])],shown=autoShown,seq=autoSequence;
 const content=$('auto-link-dialog').querySelector('.dialog-content')||$('auto-link-dialog');
 const scroll=$('auto-link-results').scrollTop,dialogScroll=content.scrollTop;
 let applied=null;lockAutoLinks(true);$('auto-link-error').textContent='';
 try{
  const update=async()=>{
   applied=await api('lexeme-auto-link',{_language:autoLanguage,text_id:plan.text_id,token:plan.token,ignore_symbols:plan.ignore_symbols,ignore_position:plan.ignore_position,mode,selected});
   return api(autoPreviewRequest(plan));
  };
  const remaining=await (globalThis.window?.corporiumWithTaskProgress?window.corporiumWithTaskProgress(update):update());
  if(seq!==autoSequence)return;
  drawAutoPlan(remaining,new Set(selected),shown);
  $('auto-link-results').scrollTop=scroll;content.scrollTop=dialogScroll;
  const message=globalThis.CorporiumI18n?.ui(`已关联 ${applied.count} 处，可一步撤销。剩余唯一匹配 ${remaining.matches.length} 处，需确认候选 ${remaining.suggestions.length} 项，可继续关联。`,`Linked ${applied.count}. You can undo this step. Remaining: ${remaining.matches.length} unique matches and ${remaining.suggestions.length} candidates to confirm.`)??`已关联 ${applied.count} 处，可一步撤销。剩余唯一匹配 ${remaining.matches.length} 处，需确认候选 ${remaining.suggestions.length} 项，可继续关联。`;
  $('auto-link-summary').textContent=message;
  try{await (globalThis.window?.corporiumRefreshUndoState||refreshUndo)();await refreshExampleViews();}
  catch(e){$('auto-link-error').textContent=(globalThis.CorporiumI18n?.ui('关联已保存；页面刷新失败：','Links saved; page refresh failed: ')??'关联已保存；页面刷新失败：')+e.message;}
 }catch(e){
  if(seq!==autoSequence)return;
  resetAutoPlan();$('auto-link-error').textContent=(applied?(globalThis.CorporiumI18n?.ui(`已关联 ${applied.count} 处，但剩余候选更新失败，请重新预览：`,`Linked ${applied.count}, but remaining candidates could not be refreshed. Preview again: `)??`已关联 ${applied.count} 处，但剩余候选更新失败，请重新预览：`):'')+e.message;
 }finally{lockAutoLinks(false);}
}
$('auto-link-apply').onclick=()=>applyAutoLinks('strict');
$('auto-candidate-apply').onclick=()=>applyAutoLinks('candidates');
