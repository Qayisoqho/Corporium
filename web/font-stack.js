// Draft-only font ordering. The hidden input joins the settings form's normal
// save/discard snapshot; discovery and preview never apply the draft globally.
function moveFontInStack(stack,id,index){
  const next=[...stack],from=next.indexOf(id);if(from<0)return next;
  next.splice(from,1);next.splice(Math.max(0,Math.min(next.length,index)),0,id);return next;
}
function createFontStackEditor(host){
  const text=fontUI;
  host.innerHTML=`<p class="font-settings-intro">${text('字体按标签顺序回退：前面的字体缺字时，尝试后面的字体。全局设置保存在本机，各标注行也可单独指定字体。','Fonts fall back in tag order: when a character is missing, the next font is tried. Global settings stay on this computer; annotation rows can also use their own font.')}</p>
    <div class="font-stack-editor">
      <div class="font-stack-heading"><strong id="font-stack-label">${text('全局字体顺序','Global font order')}</strong><button type="button" id="font-stack-reset">${text('恢复默认顺序','Restore default order')}</button></div>
      <input type="hidden" id="global-ui-font"><ol id="global-font-stack" class="font-stack-tags" aria-labelledby="font-stack-label"></ol>
      <p class="font-stack-help">${text('点击下方字体添加；拖动把手排序，或聚焦把手后按方向键。最左侧优先，末尾始终保留系统通用回退。','Click a font below to add it. Drag a handle to reorder, or focus it and use the arrow keys. Leftmost comes first; a generic system fallback always remains at the end.')}</p>
      <div class="font-catalog-tools"><label>${text('查找字体','Find fonts')}<input id="font-catalog-search" type="search" data-settings-transient placeholder="${text('输入字体名称…','Search font names…')}"></label><label>${text('来源','Source')}<select id="font-source-filter" data-settings-transient><option value="">${text('全部来源','All sources')}</option>${['bundled','system','folder','generic','preset'].map(s=>`<option value="${s}">${fontSourceLabel(s)}</option>`).join('')}</select></label></div>
      <div id="font-catalog-results" class="font-catalog-results" role="group" aria-label="${text('可添加的字体','Available fonts')}"></div>
      <p id="font-stack-status" class="font-stack-status" role="status" aria-live="polite"></p>
      <div class="font-stack-preview" aria-label="${text('字体预览','Font preview')}"><small>${text('预览','Preview')}</small><div id="global-font-preview"><p>Corporium · 语料与词典</p><p>pʰatʰeːl · ɐ̃ ə̥ ʃ ʒ ŋ ɲ ʔ · ā́ e̯ o̤</p></div></div>
    </div><label>${text('界面字体变体','Interface font variant')}<select id="global-ui-variant">${variantOptions}</select></label>`;
  const input=$('global-ui-font'),tags=$('global-font-stack'),results=$('font-catalog-results'),status=$('font-stack-status');
  let names={},cancelDrag=null,catalogVersion=0,catalogKey='',catalogCache=null;
  const current=()=>{try{return normalizeFontStack(JSON.parse(input.value));}catch{return [...defaultFontStack];}};
  const label=id=>fontSources[id]?.name||names[id]||fontLabel(id);
  const announce=message=>status.textContent=message;
  function preview(){
    const sample=$('global-font-preview'),v=variantStyle($('global-ui-variant').value);
    Object.assign(sample.style,{fontFamily:fontStackCSS(current()),fontStyle:v.style,fontWeight:v.weight});
  }
  function syncCandidates(){const stack=new Set(current());for(const button of results.querySelectorAll('[data-font-add]')){
    const added=stack.has(button.dataset.fontAdd),pressed=String(added);if(button.getAttribute('aria-pressed')!==pressed)button.setAttribute('aria-pressed',pressed);
    const action=button.querySelector('.font-candidate-action'),text=added?'✓':'+';if(action.textContent!==text)action.textContent=text;
  }}
  function renderTags(focus){
    cancelDrag?.();
    const stack=current();tags.replaceChildren();
    for(const [i,id] of stack.entries()){
      const item=document.createElement('li');item.dataset.fontId=id;item.className='font-stack-tag';
      const known=fontSources[id],missing=!known;
      const handle=document.createElement('button');handle.type='button';handle.className='font-stack-handle';handle.textContent='⠿';
      const instruction=text('方向键调整顺序','Use arrow keys to reorder');
      handle.setAttribute('aria-label',text(`移动 ${label(id)}，优先级 ${i+1}`,`Move ${label(id)}, priority ${i+1}`));handle.title=instruction;
      const rank=document.createElement('span');rank.className='font-stack-rank';rank.textContent=String(i+1);rank.setAttribute('aria-hidden','true');
      const name=document.createElement('span');name.className='font-stack-name';name.textContent=label(id);name.title=name.textContent;
      const source=document.createElement('small');source.textContent=fontSourceLabel(known?.source);if(missing){item.classList.add('font-unavailable');source.title=text('保留设置；显示时继续尝试后面的字体。','Selection kept; display falls through to the following fonts.');}
      const remove=document.createElement('button');remove.type='button';remove.className='font-stack-remove';remove.textContent='×';remove.disabled=stack.length===1;
      remove.setAttribute('aria-label',text(`移除 ${label(id)}`,`Remove ${label(id)}`));remove.title=remove.getAttribute('aria-label');
      remove.onclick=()=>{const next=current().filter(v=>v!==id);if(!next.length)return;set(next,true,next[Math.min(i,next.length-1)]);announce(text(`已移除 ${label(id)}`,`Removed ${label(id)}`));};
      handle.onkeydown=event=>{
        if(event.key==='Escape'&&cancelDrag){event.preventDefault();cancelDrag();return;}
        const offset={ArrowLeft:-1,ArrowUp:-1,ArrowRight:1,ArrowDown:1}[event.key];
        if(offset==null&&!['Home','End'].includes(event.key))return;
        event.preventDefault();const index=event.key==='Home'?0:event.key==='End'?stack.length-1:i+offset;
        set(moveFontInStack(stack,id,index),true,id);announce(text(`${label(id)}：优先级 ${Math.max(1,Math.min(stack.length,index+1))}`,`${label(id)}: priority ${Math.max(1,Math.min(stack.length,index+1))}`));
      };
      handle.onpointerdown=event=>{
        if(event.button!==0)return;event.preventDefault();cancelDrag?.();handle.focus();
        const pointer=event.pointerId,startX=event.clientX,startY=event.clientY;let active=false,target=null;
        handle.setPointerCapture(pointer);
        const clear=()=>{for(const el of tags.children)el.classList.remove('font-drop-target','font-dragging');};
        const cleanup=()=>{
          cancelDrag=null;handle.removeEventListener('pointermove',move);handle.removeEventListener('pointerup',drop);handle.removeEventListener('pointercancel',cleanup);handle.removeEventListener('lostpointercapture',cleanup);window.removeEventListener('blur',cleanup);clear();
          if(handle.hasPointerCapture(pointer))handle.releasePointerCapture(pointer);
        };
        const move=e=>{
          if(e.pointerId!==pointer)return;
          if(!active&&Math.hypot(e.clientX-startX,e.clientY-startY)<5)return;
          active=true;clear();item.classList.add('font-dragging');
          const hit=document.elementFromPoint(e.clientX,e.clientY)?.closest('.font-stack-tag');
          target=hit?.parentElement===tags?hit:null;if(target&&target!==item)target.classList.add('font-drop-target');
        };
        const drop=e=>{
          if(e.pointerId!==pointer)return;const index=target?[...tags.children].indexOf(target):-1;cleanup();
          if(active&&index>=0&&index!==i){set(moveFontInStack(current(),id,index),true,id);announce(text(`已调整 ${label(id)} 的顺序`,`Reordered ${label(id)}`));}
        };
        cancelDrag=cleanup;handle.addEventListener('pointermove',move);handle.addEventListener('pointerup',drop);handle.addEventListener('pointercancel',cleanup);handle.addEventListener('lostpointercapture',cleanup);window.addEventListener('blur',cleanup);
      };
      const caption=document.createElement('span');caption.className='font-stack-caption';caption.append(rank,name,source);
      item.append(handle,caption,remove);tags.append(item);
    }
    syncCandidates();preview();
    if(focus)[...tags.children].find(el=>el.dataset.fontId===focus)?.querySelector('button').focus();
  }
  function set(stack,changed=false,focus){
    input.value=JSON.stringify(normalizeFontStack(stack));renderTags(focus);
    if(changed)input.dispatchEvent(new Event('input',{bubbles:true}));
  }
  function renderCatalog(opening=false){
    if(!opening&&(!host.closest('dialog[open]')||host.closest('[hidden],details:not([open])')))return;
    const query=$('font-catalog-search').value.trim().toLocaleLowerCase(),source=$('font-source-filter').value;
    const key=JSON.stringify([catalogVersion,query,source]);
    if(key===catalogKey){if(catalogCache){results.append(catalogCache);catalogCache=null;}syncCandidates();return;}
    catalogKey=key;catalogCache=null;
    const families=Object.values(fontSources).filter(f=>(!source||f.source===source)&&[f.name,...(f.aliases||[]),availableFonts[f.id]].join(' ').toLocaleLowerCase().includes(query));
    families.sort((a,b)=>a.name.localeCompare(b.name));const fragment=document.createDocumentFragment();
    for(const family of families){
      const button=document.createElement('button');button.type='button';button.dataset.fontAdd=family.id;button.className='font-candidate';
      const name=document.createElement('span');name.textContent=family.name;name.className='font-candidate-name';
      const source=document.createElement('small');source.textContent=fontSourceLabel(family.source);
      const action=document.createElement('span');action.className='font-candidate-action';action.setAttribute('aria-hidden','true');
      button.append(name,source,action);button.title=family.name+' · '+source.textContent;
      button.onclick=()=>{const stack=current();if(stack.includes(family.id))return;if(stack.length>=32){announce(text('最多选择 32 个字体。','Choose up to 32 fonts.'));return;}
        names[family.id]=family.name;
        // Generic families are terminal fallbacks. A newly added real family
        // must remain reachable when a legacy setting ended in a generic.
        const at=stack.findIndex(id=>['serif','sans-serif'].includes(id));stack.splice(at<0?stack.length:at,0,family.id);
        set(stack,true);announce(text(`已添加 ${family.name}`,`Added ${family.name}`));};
      fragment.append(button);
    }
    if(!families.length){const empty=document.createElement('p');empty.className='font-catalog-empty';empty.textContent=text('没有匹配的字体。可更换关键词或重新扫描。','No matching fonts. Try another search or rescan.');fragment.append(empty);}
    results.replaceChildren(fragment);
    syncCandidates();
  }
  $('font-catalog-search').oninput=()=>renderCatalog(true);
  $('font-catalog-search').onkeydown=event=>{if(event.key==='Enter')event.preventDefault();};
  $('font-source-filter').onchange=()=>renderCatalog(true);
  $('global-ui-variant').addEventListener('change',preview);
  $('font-stack-reset').onclick=()=>{set(defaultFontStack,true);announce(text('已恢复默认顺序，保存后生效。','Default order restored. Save to apply.'));};
  window.addEventListener('corporium-fonts-changed',()=>{catalogVersion++;renderTags();renderCatalog();});
  // Detached catalog buttons retain their handlers and draft selection, but do
  // not participate in unrelated workspace style matching while settings close.
  document.addEventListener('beforetoggle',event=>{
    if(!event.target.contains(host))return;
    if(event.newState==='open'&&!host.closest('[hidden],details:not([open])'))renderCatalog(true);
    else if(event.newState==='closed'&&results.firstChild){catalogCache=document.createDocumentFragment();catalogCache.append(...results.childNodes);}
  },true);
  // A collapsed font section need not construct the catalog either. Restore it
  // before the summary's default click action; toggle also covers script/AX
  // expansion through the native details API.
  document.addEventListener('click',event=>{const summary=event.target.closest('summary');if(summary&&!summary.parentElement.open&&summary.parentElement.contains(host))renderCatalog(true);},true);
  document.addEventListener('toggle',event=>{if(event.target.matches('details')&&event.target.open&&event.target.contains(host))renderCatalog();},true);
  return {
    load(settings){names={...(settings.uiFontNames||{})};$('global-ui-variant').value=settings.uiVariant||'regular';$('font-catalog-search').value='';$('font-source-filter').value='';set(savedFontStack(settings));renderCatalog();announce('');},
    settings(){const uiFonts=current();return {uiFonts,uiFontNames:Object.fromEntries(uiFonts.map(id=>[id,label(id)])),ui:uiFonts[0],uiVariant:$('global-ui-variant').value};}
  };
}
