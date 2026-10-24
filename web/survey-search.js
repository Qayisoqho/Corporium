/* Search highlights are temporary reading decorations, never editor content. */
function surveyTextRanges(text,query,limit=Infinity){
 const normalize=s=>s.normalize('NFC').toLowerCase().replaceAll('ς','σ').replace(/\s+/g,' '),needle=normalize(query);if(!needle)return [];
 const segments=typeof Intl.Segmenter==='function'?[...new Intl.Segmenter(undefined,{granularity:'grapheme'}).segment(text)].map(s=>[s.segment,s.index]):Array.from(text.matchAll(/\P{M}\p{M}*|\p{M}+/gu),m=>[m[0],m.index]);
 let value='',offsets=[];for(const [part,start] of segments){const n=normalize(part);if(n===' '&&value.endsWith(' ')){offsets.at(-1)[1]=start+part.length;continue;}value+=n;for(let i=0;i<n.length;i++)offsets.push([start,start+part.length]);}
 const result=[];let at=0;while(result.length<limit&&(at=value.indexOf(needle,at))>=0){result.push([offsets[at][0],offsets[at+needle.length-1][1]]);at+=needle.length;}return result;
}
function surveySnippet(text,query){let out='',at=0;for(const [a,b] of surveyTextRanges(text,query)){out+=esc(text.slice(at,a))+'<mark>'+esc(text.slice(a,b))+'</mark>';at=b;}return out+esc(text.slice(at));}
function createSurveySearch(adapter){
 const navigation=$('survey-navigation'),outline=$('survey-tree');let language=activeLanguage,session=null,original=null,generation=0,busy=false;
 const form=document.createElement('form');form.id='survey-search';form.setAttribute('role','search');form.setAttribute('aria-label','检索语法调查');
 form.innerHTML='<div class="survey-search-input"><input id="survey-search-query" aria-label="检索调查内容" placeholder="检索调查内容…" maxlength="200"><button type="submit" aria-label="检索语法调查" title="检索（Enter）"><svg viewBox="0 0 20 20" aria-hidden="true"><circle cx="8" cy="8" r="5.5"/><path d="m12 12 5 5"/></svg></button><button type="button" id="survey-search-clear" aria-label="清空调查检索" title="清空并恢复提纲">×</button></div><select id="survey-search-scope" aria-label="调查检索范围"><option value="all">全部内容</option><option value="survey">调查文字</option><option value="examples">引用例句</option></select>';
 const results=document.createElement('section');results.id='survey-search-results';results.hidden=true;results.setAttribute('aria-label','调查检索结果');
 const status=document.createElement('p');status.id='survey-search-status';status.setAttribute('role','status');status.hidden=true;
 navigation.prepend(form,status,results);
 new ResizeObserver(()=>navigation.style.setProperty('--survey-search-height',form.getBoundingClientRect().height+'px')).observe(form);
 function scrollRoot(){return navigation.closest('#workbench-module-nav')||navigation;}
 function clearHighlight(){
  window.CSS?.highlights?.delete('survey-search');
  for(const mark of document.querySelectorAll('mark.survey-search-match'))mark.replaceWith(document.createTextNode(mark.textContent));
  for(const el of document.querySelectorAll('.survey-search-focus'))el.classList.remove('survey-search-focus');
  for(const el of document.querySelectorAll('[data-survey-search-extra]'))el.remove();
 }
 function message(text,error=false){status.textContent=text;status.hidden=!text;status.classList.toggle('is-error',error);}
 function lock(value){busy=value;form.querySelectorAll('button,select').forEach(e=>e.disabled=value||activeLanguage==='all');$('survey-search-query').disabled=activeLanguage==='all';results.inert=value;}
 function refresh(){
  if(language!==activeLanguage){language=activeLanguage;generation++;session=original=null;$('survey-search-query').value='';$('survey-search-scope').value='all';clearHighlight();message('');}
  outline.hidden=!!session;results.hidden=!session;lock(busy);
 }
 function render(){
  refresh();if(!session)return;
  const d=session.data;message(`${d.nodes} 个条目 · ${d.total} 组匹配内容`);
  let previous=null;
  results.innerHTML=d.items.map((item,index)=>{const path=previous!==item.node_id?`<div class="survey-search-path">${item.path.map(esc).join(' › ')}</div>`:'';previous=item.node_id;
   const row=f=>`<button type="button" data-survey-hit="${index}" data-hit-field="${esc(f.field)}"><strong>${esc(f.label)}</strong><span>${surveySnippet(f.snippet,session.query)}</span></button>`;
   return `<div class="survey-search-result">${path}${item.evidence_id?`<small>${item.kind==='corpus'?'文本引用':'独立例句'} · 本处例证</small>`:''}${item.fields.slice(0,2).map(row).join('')}${item.fields.length>2?`<details><summary>另有 ${item.fields.length-2} 个命中字段</summary>${item.fields.slice(2).map(row).join('')}</details>`:''}</div>`;
  }).join('')||'<p class="survey-search-empty">没有匹配内容。</p>';
  if(d.pages>1)results.insertAdjacentHTML('beforeend',`<nav class="survey-search-pages" aria-label="调查检索分页"><button type="button" data-survey-search-page="${d.page-1}" ${d.page===1?'disabled':''} aria-label="上一页检索结果">‹</button><span>${d.page} / ${d.pages}</span><button type="button" data-survey-search-page="${d.page+1}" ${d.page===d.pages?'disabled':''} aria-label="下一页检索结果">›</button></nav>`);
 }
 async function run(page=1){
  if(busy)return;refresh();const query=$('survey-search-query').value.trim(),scope=$('survey-search-scope').value;if(!query)return clear();
  const seq=++generation,lid=activeLanguage;lock(true);
  try{
   await adapter.prepare();if(seq!==generation||lid!==activeLanguage)return;
   const place=original||adapter.capture(),data=await api('survey-search?'+new URLSearchParams({q:query,scope,page,language:lid}));
   if(seq!==generation||lid!==activeLanguage)return;
   original=place;session={query,scope,data};clearHighlight();render();scrollRoot().scrollTop=0;
  }catch(e){if(seq===generation)message(e.message,true);}finally{lock(false);}
 }
 function highlight(roots,query){
  let text='',pieces=[];for(const root of roots){if(text)text+=' ';const walker=document.createTreeWalker(root,NodeFilter.SHOW_TEXT);let node;
   while(node=walker.nextNode()){if(node.parentElement.closest('.code-word-label,.code-overview,[contenteditable],button:not(.word-dictionary),script,style'))continue;pieces.push({node,start:text.length,end:text.length+node.length});text+=node.textContent;}}
  const limit=Math.max(1,Math.min(500,Math.floor(1000/Math.max(1,query.length)))),matches=surveyTextRanges(text,query,limit+1),partial=matches.length>limit;
  if(partial)matches.length=limit;
  const ranges=[];let index=0;
  for(const p of pieces){while(index<matches.length&&matches[index][1]<=p.start)index++;for(let i=index;i<matches.length&&matches[i][0]<p.end;i++){
   const start=Math.max(matches[i][0],p.start)-p.start,end=Math.min(matches[i][1],p.end)-p.start;if(start>=end)continue;
   const range=document.createRange();range.setStart(p.node,start);range.setEnd(p.node,end);ranges.push(range);
  }}
  const firstMatch=ranges[0]?.startContainer.parentElement;
  if(window.Highlight&&window.CSS?.highlights)CSS.highlights.set('survey-search',new Highlight(...ranges));
  else for(const range of ranges.reverse()){const mark=document.createElement('mark');mark.className='survey-search-match';range.surroundContents(mark);}
  return {count:matches.length,first:firstMatch,partial,limit};
 }
 async function navigate(item,field){
  if(busy||!session)return;const seq=++generation,lid=activeLanguage,query=session.query;lock(true);
  const current=()=>seq===generation&&lid===activeLanguage;
  try{
   await adapter.prepare();if(!current())return;
   const target=await api('survey-locate?'+new URLSearchParams({node_id:item.node_id,evidence_id:item.evidence_id||'',field,q:query,scope:session.scope,language:lid}));if(!current())return;
   clearHighlight();const roots=await adapter.navigate(target,current);if(!current())return;
   if(!roots?.length)throw Error('该位置已改变，请重新检索。');
   for(const root of roots)for(let d=root.closest('details');d;d=d.parentElement?.closest('details'))d.open=true;
   const found=target.matched?highlight(roots,query):{count:0},count=found.count;
   const first=found.first||roots.find(r=>r.getClientRects().length)||roots[0];(roots.find(r=>r.contains(first))||first).classList.add('survey-search-focus');first.scrollIntoView({block:'center'});
   message(count?`${session.data.nodes} 个条目 · ${session.data.total} 组匹配内容${found.partial?' · 仅高亮前 '+found.limit+' 处':''}`:'内容已变化，已定位到原位置；可重新检索。',!count);
  }catch(e){if(current())message(e.message,true);}finally{lock(false);}
 }
 async function clear(){
  if(busy)return;const seq=++generation,lid=activeLanguage;lock(true);
  const previous=session,place=original,query=$('survey-search-query').value;
  try{
   if(session)await adapter.prepare();if(seq!==generation||lid!==activeLanguage)return;
   session=original=null;$('survey-search-query').value='';clearHighlight();message('');refresh();
   if(place)await adapter.restore(place,()=>seq===generation&&lid===activeLanguage);
  }catch(e){if(seq===generation){session=previous;original=place;$('survey-search-query').value=query;refresh();message(e.message,true);}}finally{lock(false);}
 }
 form.onsubmit=e=>{e.preventDefault();if(!e.isComposing)return run();};$('survey-search-clear').onclick=()=>clear();
 $('survey-search-query').onkeydown=e=>{if(e.isComposing&&e.key==='Enter')e.preventDefault();};
 $('survey-search-scope').onchange=()=>{if(session)void run();};
 results.onclick=e=>{const hit=e.target.closest('[data-survey-hit]'),page=e.target.closest('[data-survey-search-page]');if(hit)return navigate(session.data.items[+hit.dataset.surveyHit],hit.dataset.hitField);else if(page)return run(+page.dataset.surveySearchPage);};
 refresh();return {active:()=>!!session,refresh,clearHighlight};
}
