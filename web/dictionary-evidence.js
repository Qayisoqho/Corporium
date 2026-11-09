/* Reading controls reuse the original filters, callbacks and evidence nodes. */
(()=>{
 const ui=(zh,en)=>globalThis.CorporiumI18n?.ui(zh,en)??zh;
 const node=(tag,cls,text)=>{const n=document.createElement(tag);if(cls)n.className=cls;if(text!==undefined)n.textContent=text;return n;};
 const setText=(n,text)=>{if(n.textContent!==text)n.textContent=text;};
 const move=(parent,child)=>{if(child&&child.parentElement!==parent)parent.append(child);};
 function preparePage(bar){
  if(bar.querySelector(':scope>.example-paging-controls'))return;
  const paging=node('div','example-paging-controls');paging.append(...bar.childNodes);bar.append(paging);bar.classList.add('evidence-page-actions');
 }
 function pageState(bar,selected,busy){
  const paging=bar.querySelector(':scope>.example-paging-controls');if(!paging)return;
  paging.hidden=Number(bar.dataset.examplePages||1)<=1;
  const active=selected>0||busy;
  for(const control of bar.querySelectorAll(':scope>.example-select-all,:scope>[data-example-unlink-selected]'))control.hidden=!active;
  bar.hidden=paging.hidden&&!active;
 }
 function releaseFilter(root,id){
  const control=root?.querySelector('.dictionary-evidence-filters #'+id);control?.closest('label')?.remove();
 }
 function setup(controls){
  if(controls.classList.contains('compact-evidence-controls'))return;
  controls.classList.add('compact-evidence-controls');
  const title=controls.querySelector(':scope>h3')||node('h3','');setText(title,ui('例证','Examples'));
  const heading=node('div','dictionary-evidence-heading'),actions=node('div','dictionary-evidence-actions');
  const more=node('details','workbench-menu dictionary-evidence-more');
  const summary=node('summary','', '⋯');summary.setAttribute('aria-label',ui('更多例证操作','More example actions'));summary.title=ui('更多例证操作','More example actions');
  const menu=node('div','workbench-menu-items');more.append(summary,menu);actions.append(more);heading.append(title,actions);
  const row=node('div','dictionary-evidence-navigation'),sources=node('div','dictionary-evidence-sources');sources.setAttribute('role','group');sources.setAttribute('aria-label',ui('例证来源','Example source'));
  for(const source of ['all','corpus','independent']){const b=node('button','');b.type='button';b.dataset.evidenceSource=source;sources.append(b);}
  const filters=node('details','dictionary-evidence-filters'),filterSummary=node('summary','',ui('筛选','Filters')),fields=node('div','dictionary-evidence-fields');
  filters.append(filterSummary,fields);row.append(sources,filters);controls.append(heading,row);
  menu.addEventListener('click',e=>{if(e.target.closest('button'))more.open=false;});
 }
 function label(control,caption,title){
  if(!control)return null;const host=control.closest('label');if(!host)return null;
  if(!host.dataset.evidenceLabel){for(const child of [...host.childNodes])if(child.nodeType===3)child.remove();host.prepend(node('span','',caption));host.dataset.evidenceLabel='true';host.dataset.evidenceControl=control.id;control.setAttribute('aria-label',caption);if(title)host.title=title;}
  return host;
 }
 function refresh(root=document.getElementById('dictionary-detail')){
  if(!root)return;
  const native=root.hasAttribute('data-live-morpheme-evidence');
  const controls=native?root.querySelector('.morpheme-evidence-heading'):root.querySelector('#dictionary-example-controls');
  const select=native?null:root.querySelector('#example-source');if(!controls||!native&&!select)return;
  setup(controls);controls.classList.remove('brief-empty');
  const heading=controls.querySelector('.dictionary-evidence-heading'),actions=heading.querySelector('.dictionary-evidence-actions'),menu=actions.querySelector('.workbench-menu-items');
  const add=controls.querySelector('#new-standalone,[data-new-evidence]');if(add&&add.parentElement!==actions)actions.prepend(add);
  for(const button of controls.querySelectorAll('[data-unlink-all]'))move(menu,button);
  actions.querySelector('.dictionary-evidence-more').hidden=!menu.children.length;
  for(const old of [...controls.querySelectorAll(':scope>.dictionary-evidence-actions')])if(!old.children.length)old.remove();
  const fields=controls.querySelector('.dictionary-evidence-fields'),sources=controls.querySelector('.dictionary-evidence-sources');
  if(select){const old=select.closest('label');old.hidden=true;old.classList.add('dictionary-evidence-source-select');}
  const form=root.querySelector('#example-form'),kind=root.querySelector('#example-kind');
  move(fields,label(form,ui('形式','Form'),ui('同时筛选语料引用和独立例句','Filters both corpus references and independent examples')));
  move(fields,label(kind,ui('关联单位','Linked unit'),ui('仅筛选语料引用的关联单位','Only filters linked units in corpus references')));
  const clear=root.querySelector('#examples-clear');if(clear)move(fields,clear);
  const corpus=native?root.querySelector('[data-corpus-evidence]'):root.querySelector('#corpus-examples-section');
  const independent=native?root.querySelector('[data-independent-evidence]'):root.querySelector('#standalone-examples');
  const corpusCount=Number((native?root:corpus)?.dataset.corpusCount||0),independentCount=Number((native?root:independent)?.dataset.independentCount||0);
  const value=native?(root.dataset.evidenceSource||'all'):select.value;
  const filtered=!!((form&&form.value!=='all')||(kind&&kind.value!=='all')||value!=='all');
  if(clear)clear.hidden=!filtered;
  const filterBox=controls.querySelector('.dictionary-evidence-filters');filterBox.hidden=!form&&!kind;
  const owner=root.dataset.referenceId||root.dataset.evidenceOwner||'';
  if(root.dataset.evidenceFilterOwner!==owner){root.dataset.evidenceFilterOwner=owner;root.dataset.evidenceFiltersOpen='false';}
  if(!filterBox.dataset.remembered){filterBox.dataset.remembered='true';filterBox.open=root.dataset.evidenceFiltersOpen==='true';filterBox.addEventListener('toggle',()=>{if(controls.isConnected)root.dataset.evidenceFiltersOpen=String(filterBox.open);});}
  const activeFilters=Number(!!form&&form.value!=='all')+Number(!!kind&&kind.value!=='all');
  setText(filterBox.querySelector('summary'),ui('筛选','Filters')+(activeFilters?' · '+activeFilters:''));
  const captions={all:ui('全部','All'),corpus:ui('语料引用 '+corpusCount+'次','Corpus '+corpusCount+(corpusCount===1?' occurrence':' occurrences')),independent:ui('独立例句 '+independentCount+'句','Independent '+independentCount+(independentCount===1?' sentence':' sentences'))};
  for(const button of sources.children){const source=button.dataset.evidenceSource;setText(button,captions[source]);button.setAttribute('aria-pressed',String(source===value));button.onclick=dictSafe(async()=>{
   if(source===value)return;await leaveSentenceDrafts();if(!root.isConnected||!button.isConnected||owner!==(root.dataset.referenceId||root.dataset.evidenceOwner||''))return;
   if(native){root.dataset.evidenceSource=source;refresh(root);}else{select.value=source;select.dispatchEvent(new Event('change',{bubbles:true}));}
  });}
  // Keep an active corpus-only filter visible even when viewing the other source.
  if(kind)kind.closest('label').classList.toggle('inactive-source-filter',value==='independent');
  const hasCorpus=!!(corpusCount||corpus?.querySelector('.lex-example'));
  const hasIndependent=!!(independentCount||independent?.querySelector('.new-sentence-draft'));
  if(native){
   for(const host of [corpus,root.querySelector('[data-corpus-pager]')])if(host)host.hidden=value==='independent'||!hasCorpus||(host!==corpus&&Number(host.dataset.evidencePages||1)<=1);
   for(const host of [independent,root.querySelector('[data-independent-pager]')])if(host){if(host===independent)host.hidden=value==='corpus'||!hasIndependent;else host.hidden=value==='corpus'||Number(host.dataset.evidencePages||1)<=1;}
  }else{
   if(corpus)corpus.hidden=value==='independent'||!corpusCount&&!corpus.querySelector('.lex-example');
   if(independent)independent.hidden=value==='corpus'||!independentCount&&!independent.querySelector('.new-sentence-draft');
  }
  // The source tabs own counts; empty subsection headings add no information.
  if(corpus)for(const h of corpus.querySelectorAll(':scope>h3'))h.hidden=value!=='all'||!independentCount||!corpusCount;
  if(independent&&!native)for(const h of independent.querySelectorAll(':scope>h3'))h.hidden=value!=='all'||!independentCount||!corpusCount;
  if(native)for(const h of root.querySelectorAll(':scope>h4'))h.hidden=true;
  let empty=controls.querySelector('.dictionary-evidence-empty');if(!empty){empty=node('p','dictionary-evidence-empty');empty.setAttribute('role','status');controls.append(empty);}
  empty.hidden=!!root.querySelector('.new-sentence-draft')||(value==='corpus'?hasCorpus:value==='independent'?hasIndependent:hasCorpus||hasIndependent);
  setText(empty,activeFilters?ui('没有符合当前条件的例证，可清除筛选。','No examples match these filters. Clear filters to show more.'):(value==='independent'?ui('暂无独立例句，可从上方添加。','No independent examples yet. Add one above.'):ui('暂无例证，可添加独立例句。','No examples yet. Add an independent example above.')));
 }
 globalThis.CorporiumDictionaryEvidence={preparePage,pageState,releaseFilter,refresh};
})();
