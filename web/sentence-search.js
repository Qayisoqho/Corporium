/* One compact drawer below the command row; each sentence workspace remembers it. */
(()=>{
 const dock=document.createElement('section');dock.id='sentence-search-dock';
 const grip=document.createElement('button');grip.id='sentence-search-grip';grip.type='button';grip.innerHTML='<svg viewBox="0 0 24 12" aria-hidden="true"><path d="m7 4 5 4 5-4"/></svg>';
 const panels={corpus:corpusWorkspace.querySelector(':scope>.search'),library:libraryPanel.querySelector(':scope>.search')},opened={};
 for(const [scope,panel] of Object.entries(panels)){if(scope==='library')for(const label of panel.querySelectorAll('.filters label'))if(!label.querySelector('input,select')&&label.textContent.trim()===(globalThis.CorporiumI18n?.f("01580cb198ead2",()=>[])??'层次'))label.remove();panel.id=scope+'-search-panel';dock.append(panel);try{opened[scope]=localStorage.getItem(projectStorageKey('corporium-sentence-search-open:'+scope))==='true';}catch{opened[scope]=false;}}
 dock.append(grip);toolbarRow.after(dock);
 function render(){
  const scope=workspace==='library'?'library':'corpus',valid=['corpus','library'].includes(workspace);
  dock.hidden=!valid||(scope==='corpus'&&corpusWorkspace.classList.contains('dialogue-active'));
  for(const [name,panel] of Object.entries(panels))panel.hidden=!valid||name!==scope||!opened[scope];
  const title=(globalThis.CorporiumI18n?.f("b14c3fa185b187",()=>[(opened[scope]?(globalThis.CorporiumI18n?.f("0613362baa1b0b",()=>[])??'收起'):(globalThis.CorporiumI18n?.f("b431f3c01b8667",()=>[])??'展开'))+(scope==='library'?(globalThis.CorporiumI18n?.f("9e32c567593d37",()=>[])??'独立例句'):(globalThis.CorporiumI18n?.f("0b11fbc446a4c1",()=>[])??'文本语料'))])??(opened[scope]?'收起':'展开')+(scope==='library'?'独立例句':'文本语料')+'检索');grip.title=title;grip.setAttribute('aria-label',title);grip.setAttribute('aria-expanded',String(opened[scope]));grip.setAttribute('aria-controls',panels[scope].id);dock.classList.toggle('search-open',opened[scope]);
 }
 grip.onclick=()=>{const scope=workspace==='library'?'library':'corpus';opened[scope]=!opened[scope];try{localStorage.setItem(projectStorageKey('corporium-sentence-search-open:'+scope),String(opened[scope]));}catch{}render();};
 new MutationObserver(render).observe(document.documentElement,{attributes:true,attributeFilter:['data-workbench']});
 new MutationObserver(render).observe(corpusWorkspace,{attributes:true,attributeFilter:['class']});
 render();
})();

/* Shared custom-field choices; names remain user data in either UI language. */
(()=>{
 let sequence=0,owner=null,signature='';
 const selectors=()=>[$('field'),$('library-field'),$('survey-search-scope')].filter(Boolean);
 async function refresh(){
  const lid=activeLanguage,ticket=++sequence,data=await api('sentence-search-fields?language='+encodeURIComponent(lid));
  if(ticket!==sequence||lid!==activeLanguage)return;
  const next=JSON.stringify(data);if(owner===lid&&signature===next)return;
  for(const select of selectors()){
   const previous=owner===lid?select.value:'all';
   select.querySelectorAll('[data-custom-search-fields]').forEach(node=>node.remove());
   for(const [id,zh,en] of [['layers','附加标注层','Extra tiers'],['writings','自定义书写形式','Written forms']])if(![...select.options].some(o=>o.value===id))select.add(new Option(globalThis.CorporiumI18n?.ui(zh,en)??zh,id));
   for(const [kind,zh,en] of [['layer','附加标注层','Extra tiers'],['writing','自定义书写形式','Written forms']]){
    const group=document.createElement('optgroup');group.dataset.customSearchFields='';group.label=globalThis.CorporiumI18n?.ui(zh,en)??zh;
    for(const f of data.fields.filter(f=>f.group===kind))group.append(new Option(f.name,f.id));
    if(group.children.length)select.append(group);
   }
   if(![...select.options].some(o=>o.value===previous)){const missing=new Option(globalThis.CorporiumI18n?.ui('原字段已删除，请重新选择','Field removed; choose another field')??'原字段已删除，请重新选择',previous);missing.dataset.customSearchFields='';select.add(missing);}
   select.value=previous;
  }
  owner=lid;signature=next;
 }
 window.corporiumRefreshSentenceSearchFields=refresh;
 const previous=loadTexts;loadTexts=async function(...args){const result=await previous(...args);await refresh();return result;};
 for(const select of selectors())select.addEventListener('focus',()=>refresh().catch(e=>corporiumAlert(e.message)));
 refresh().catch(e=>corporiumAlert(e.message));
})();
