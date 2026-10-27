/* Reuse unchanged views and revision-keyed small catalogs. Detail reads only
   share one render, so entry drafts never survive edits or project switches. */
class CorporiumWorkspaceViews{
 constructor(identity){this.identity=identity;this.records=new Map();this.generations=new Map();this.running=new Map();this.handlers=new Map();}
 stamp(){const [owner,revision]=this.identity();return revision?JSON.stringify([owner,revision]):null;}
 current(name){const key=this.stamp();return !!key&&this.records.get(name)===key;}
 invalidate(name){this.records.delete(name);this.generations.set(name,(this.generations.get(name)||0)+1);}
 invalidateAll(){for(const name of new Set([...this.records.keys(),...this.generations.keys()]))this.invalidate(name);}
 mark(name){const key=this.stamp();if(key)this.records.set(name,key);}
 async run(name,fn){
  this.invalidate(name);const generation=this.generations.get(name),key=this.stamp();this.running.set(name,generation);
  try{const value=await fn();if(generation===this.generations.get(name)&&key&&key===this.stamp()&&value!==false)this.records.set(name,key);return value;}
  finally{if(this.running.get(name)===generation)this.running.delete(name);}
 }
 register(name,active,refresh){this.handlers.set(name,{active,refresh});}
 async refreshVisible(){for(const [name,h] of this.handlers)if(h.active()&&!this.current(name)&&!this.running.has(name))await h.refresh();}
}
(()=>{
 const views=window.CorporiumViews=new CorporiumWorkspaceViews(()=>[activeLanguage,window.corporiumWorkspaceRevision]);
 let rendered=null,loadSequence=0,readers=0,failures=0,reads=new Map();
 const stamp=()=>JSON.stringify([activeLanguage,window.dictionaryEntryKind?.()||'lexeme',window.corporiumWorkspaceRevision]);
 const catalogs=new Map(),catalogNames=new Set(['dictionary-search-options','morpheme-search-options','dictionary-organization','dictionary-counts','writing-types','grammar-tags']);
 window.corporiumInvalidateViews=()=>{rendered=null;reads.clear();catalogs.clear();views.invalidateAll();};
 const shared=new Set(['lexeme','morphology-options','dictionary-organization','dictionary-examples','grammar-tags','morpheme-components','synonyms','object-media','collaborators']);
 const previousApi=api;
 api=async function(path,body){
  if(body){if(!['docx-inspect','docx-preview','docx-export','docx-template'].includes(path)){rendered=null;reads.clear();catalogs.clear();views.invalidateAll();}return previousApi(path,body);}
  const url=new URL(path,'http://corporium.local/');
  if(window.corporiumWorkspaceRevision&&catalogNames.has(url.pathname.slice(1))){
   url.searchParams.sort();const key=stamp()+'\0'+url.pathname+'?'+url.searchParams;
   if(!catalogs.has(key)){
    if(catalogs.size>=16)catalogs.delete(catalogs.keys().next().value);
    const pending=previousApi(path,body);catalogs.set(key,pending);
    pending.catch(()=>{if(catalogs.get(key)===pending)catalogs.delete(key);});
   }
   return structuredClone(await catalogs.get(key));
  }
  if(!readers||!shared.has(url.pathname.slice(1)))return previousApi(path,body);
  url.searchParams.sort();const key=stamp()+'\0'+url.pathname+'?'+url.searchParams;
  if(!reads.has(key)){
   // The bound applies to one render; large result lists are not retained afterwards.
   if(reads.size>=64)return previousApi(path,body);
   const pending=previousApi(path,body);reads.set(key,pending);
   pending.catch(()=>{failures++;if(reads.get(key)===pending)reads.delete(key);});
  }
  return structuredClone(await reads.get(key));
 };
 async function render(fn){
  readers++;
  try{return await fn();}finally{if(!--readers)reads.clear();}
 }
 const previousLoad=loadDictionary;
 loadDictionary=async function(...args){
  const sequence=++loadSequence,before=stamp(),failed=failures;rendered=null;
  return render(async()=>{
   // Start independent small catalogs together. Their normal consumers below
   // await the same promises, including normal error handling and invalidation.
   if(window.corporiumWorkspaceRevision){
    const paths=(window.dictionaryEntryKind?.()||'lexeme')==='morpheme'
     ?['morpheme-search-options']:['dictionary-search-options','dictionary-organization','dictionary-counts'];
    for(const path of paths)void api(path).catch(()=>{});
   }
   const result=await previousLoad(...args);
   if(sequence===loadSequence&&before===stamp()&&failed===failures&&window.corporiumWorkspaceRevision)rendered=before;
   return result;
  });
 };
 window.corporiumReuseDictionary=()=>!!rendered&&rendered===stamp();
 // Check before changing panels: a background window may have saved this project.
 window.corporiumCheckDictionary=async()=>{
  if(!window.corporiumReuseDictionary())return;
  const owner=activeLanguage,state=await originalApi('undo-state');
  if(owner!==activeLanguage)return;
  if(!state.workspace_revision||state.workspace_revision!==window.corporiumWorkspaceRevision)await window.corporiumRefreshUndoState();
 };
 window.corporiumCheckWorkspace=async name=>{
  if(name==='dictionary')return window.corporiumCheckDictionary();
  const key=name==='analysis'&&window.corporiumHomophonesSelected?.()?'homophones':name;
  if(views.current(key)){
   const owner=activeLanguage,state=await originalApi('undo-state');
   if(owner!==activeLanguage)return;
   if(!state.workspace_revision||state.workspace_revision!==window.corporiumWorkspaceRevision)await window.corporiumRefreshUndoState();
  }
  if(name==='analysis')await window.corporiumRefreshAnalysisCatalog?.();
 };
 if(typeof search==='function'){const previous=search;search=async function(...args){return views.run('corpus',()=>previous(...args));};}
 if(typeof selectText==='function'){const previous=selectText;selectText=async function(...args){views.invalidate('corpus');return previous(...args);};}
 if(typeof loadLibrary==='function'){const previous=loadLibrary;loadLibrary=async function(...args){return views.run('library',()=>previous(...args));};}
 views.register('corpus',()=>workspace==='corpus',async()=>{await loadTexts();await search();});
 views.register('library',()=>workspace==='library',()=>loadLibrary());
 views.register('survey',()=>workspace==='survey',()=>window.corporiumReloadSurvey());
 views.register('timeline',()=>workspace==='timeline',()=>window.corporiumReloadTimeline());
 views.register('homophones',()=>workspace==='analysis'&&window.corporiumHomophonesSelected?.()&&window.corporiumHomophonesReady?.(),()=>window.corporiumReloadHomophones());
 views.register('analysis',()=>workspace==='analysis'&&!window.corporiumHomophonesSelected?.(),()=>window.corporiumReloadAnalysis());
 window.corporiumRefreshVisibleWorkspace=()=>views.refreshVisible();
 if(typeof undoCommand==='function'){
  const previousUndo=undoCommand;
  undoCommand=async function(...args){
   // Check before autosave/navigation wrappers can mutate or hide another draft.
   if(typeof inlineDrafts!=='undefined'&&inlineDrafts.size){$('notice').textContent=(globalThis.CorporiumI18n?.f("e45b5e8e1892dd",()=>[])??'请先保存或取消正在编辑的句子，再撤销或重做。');return;}
   const run=async()=>{
    const before=window.corporiumWorkspaceRevision;
    const result=await previousUndo(...args);
    if(before!==window.corporiumWorkspaceRevision)await views.refreshVisible();
    return result;
   };
   return window.corporiumPreserveLocation?window.corporiumPreserveLocation(run):run();
  };
 }
 if(typeof corpusReady!=='undefined')void corpusReady.then(()=>{if(workspace==='corpus')views.mark('corpus');});
 const previousShow=showLexeme;
 showLexeme=async function(...args){return render(()=>previousShow(...args));};
 // Gather sections before replacing the old detail, so the next paint is complete.
 window.corporiumPrepareLexeme=async x=>{
  await Promise.all([
   api('dictionary-examples?id='+encodeURIComponent(x.id)),
   api('grammar-tags?language='+encodeURIComponent(x.language_id)),
   api('dictionary-organization?lexical_language='+encodeURIComponent(x.language_id)),
   api('morpheme-components?id='+encodeURIComponent(x.id)),
   api('synonyms?'+new URLSearchParams({kind:'lexeme',id:x.id,language:activeLanguage})),
   api('object-media?'+new URLSearchParams({kind:'lexeme',id:x.id})),
   api('collaborators')
  ]);
 };
})();
