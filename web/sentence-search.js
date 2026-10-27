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
