/* New sentences are local instances of the shared annotation editor until saved. */
function sentenceDraftEmpty(d){
 return !['ipa','translation','notes','original','source','language_notes','grammaticality'].some(k=>String(d.body[k]||'').trim())&&!d.body.words.some(w=>w.form.trim()||w.gloss.trim())&&!d.cells.some(c=>c.value.trim());
}
function discardEmptySentenceDrafts(){
 for(const [key,d] of inlineDrafts)if(d.isNew&&!d.saving&&sentenceDraftEmpty(d)){inlineDrafts.delete(key);d.host?.remove();d.onDiscard?.();}
}
async function leaveSentenceDrafts(){
 discardEmptySentenceDrafts();
 if([...inlineDrafts.values()].some(d=>d.isNew))throw Error('请先保存或取消正在新建的句子。');
}
async function beginSentenceDraft(options={}){
 await leaveSentenceDrafts();
 if(inlineDrafts.size)throw Error('请先保存或取消正在编辑的句子。');
 const kind=options.kind||'independent',lid=options.language_id||activeLanguage;
 if(lid==='all')throw Error('请先选择一种语言。');
 const originWorkspace=workspace,originLanguage=activeLanguage;
 const layers=await api('layers?lexical_language='+encodeURIComponent(lid));
 if(workspace!==originWorkspace||activeLanguage!==originLanguage)return;
 if(inlineDrafts.size)throw Error('请先保存或取消正在编辑的句子。');
 const id='draft:'+crypto.randomUUID(),key=inlineKey(kind,id),host=document.createElement('article');host.className='entry new-sentence-draft';
 const d={kind,id,isNew:true,workspace,language_id:lid,owner_language:lid,body:{ipa:'',translation:'',notes:'',original:'',words:[]},words:[],cells:[],before:[],layers,orphaned:[],dirty:false,...options,host};
 const slot='new:'+crypto.randomUUID();d.words.push({id:slot,protected:false});d.body.words.push({form:'',gloss:''});
 inlineDrafts.set(key,d);
 host.innerHTML='<div class="entry-head"><strong>新建句子</strong><small>保存后建立记录，可保存空句</small></div>'+renderEditableExample(d.body,kind,id);
 const target=options.host||({'corpus':$('results'),'library':$('library-results'),'dictionary':$('standalone-examples'),'survey':$('survey-content'),'timeline':$('tl-editor')}[workspace])||main;
 if(options.host||workspace==='timeline')target.prepend(host);else target.before(host);host.querySelector('[data-inline-field="ipa"]')?.focus({preventScroll:true});host.scrollIntoView({block:'nearest'});
 return d;
}
(()=>{
 const oldStandalone=openStandalone;
 openStandalone=async function(x,e=null){if(e)return oldStandalone(x,e);return beginSentenceDraft({kind:'independent',language_id:x.language_id,targets:x.id?[{lexeme_id:x.id}]:[]});};
 $('add').textContent='＋ 添加句子';
 $('add').onclick=safe(()=>beginSentenceDraft({kind:'corpus',text_id:selected,onSaved:async r=>{clearFilters();page=Math.ceil(r.position/pageSize());}}));
 const previousHome=showHome;showHome=async function(...args){try{await leaveSentenceDrafts();return previousHome(...args);}catch(e){await corporiumAlert(e.message);}};
 const previousWorkspace=setWorkspace;setWorkspace=async function(name){if(name!==workspace)await leaveSentenceDrafts();return previousWorkspace(name);};
 const previousLanguage=switchLanguage;switchLanguage=async function(id){if(id!==activeLanguage)await leaveSentenceDrafts();return previousLanguage(id);};
 const previousText=selectText;selectText=async function(id,...options){await leaveSentenceDrafts();return previousText(id,...options);};
 const previousLexeme=showLexeme;showLexeme=async function(...args){await leaveSentenceDrafts();return previousLexeme(...args);};
 // Add Tab editing to every shared sentence's More menu, including timeline cards.
 document.addEventListener('click',safe(async e=>{const b=e.target.closest('[data-tab-edit]');if(!b)return;const card=b.closest('.editable-example'),kind=card.dataset.exampleKind,id=card.dataset.exampleId;
  if(inlineDrafts.has(inlineKey(kind,id)))throw Error('请先保存或取消标注编辑。');
  if(kind==='independent'){const record=await api('independent-example?id='+encodeURIComponent(id));await oldStandalone({language_id:record.language_id},record);}
  else{const d=await api('annotations?'+new URLSearchParams({kind,id}));await edit({...d.body,id,revision:d.revision,text_language_id:d.owner_language,title:'Tab 编辑',position:''});}
 }));
 const previousRender=renderEditableExample;renderEditableExample=function(e,kind,id){let html=previousRender(e,kind,id);if(!briefMode&&!inlineDrafts.has(inlineKey(kind,id)))html=html.replace('<div class="inline-tools">','<div class="inline-tools"><button type="button" data-tab-edit>Tab 编辑</button>');return html;};
 // Use the same compact search structure as the text workspace.
 $('library-source').value='independent';$('library-source').closest('label').hidden=true;
 const searchBox=document.createElement('section');searchBox.className='search';
 const row=libraryPanel.querySelector('.search-row'),filters=libraryPanel.querySelector('.filters');row.before(searchBox);searchBox.append(row);
 row.prepend($('library-field'));$('library-search').classList.add('primary');
 const options=document.createElement('details');options.className='workbench-search-options';options.innerHTML='<summary>检索选项</summary>';options.append(filters);searchBox.append(options);
 const libraryActions=document.createElement('div');libraryActions.className='actions';libraryActions.append($('library-survey-back'),$('library-add'));libraryPanel.querySelector('.workbench-heading').append(libraryActions);
 const clear=$('library-clear');clear.onclick=()=>{$('library-query').value='';$('library-field').value='all';$('library-mode').value='contains';$('library-case').checked=false;$('library-search').click();};filters.append(clear);
 const batch=document.createElement('details');batch.className='workbench-batch';batch.innerHTML='<summary>批量操作</summary><div class="organize-bar"></div>';searchBox.after(batch);
 for(const b of [...row.querySelectorAll('button')])if(b!==$('library-search'))batch.lastElementChild.append(b);
 const resultsBar=document.createElement('div');resultsBar.className='workbench-result-tools';$('library-count').before(resultsBar);resultsBar.append($('library-count'),$('library-top'));
 // Independent examples have a peer workspace tab, immediately after the dictionary.
 libraryButton.hidden=false;libraryButton.textContent='独立例句';$('workspace-dictionary').after(libraryButton);
 $('library-survey-back').hidden=true;
})();
