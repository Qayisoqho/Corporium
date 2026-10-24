/* A non-modal top-layer tool, reparented into the active modal to escape inert. */
(()=>{
 const host=document.createElement('section');host.id='ipa-keyboard';host.setAttribute('popover','manual');host.setAttribute('aria-label','IPA悬浮键盘');
 host.innerHTML='<button id="ipa-toggle" type="button" title="展开IPA键盘" aria-label="展开IPA键盘" aria-expanded="false">IPA⌨</button><section id="ipa-board" hidden><header id="ipa-drag"><strong>IPA</strong><span id="ipa-target">请先选择输入位置</span><button id="ipa-home" type="button" aria-label="移回右下角" title="移回右下角"><svg viewBox="0 0 24 24" aria-hidden="true"><circle cx="12" cy="12" r="6"></circle><path d="M12 2v5m0 10v5M2 12h5m10 0h5"></path></svg></button><button id="ipa-collapse" type="button" aria-label="收起IPA键盘" title="收起IPA键盘"><svg viewBox="0 0 24 24" aria-hidden="true"><path d="m4 8 8 8 8-8"></path></svg></button></header><div id="ipa-filter"><input id="ipa-search" type="search" placeholder="搜索符号或中英文名称" aria-label="搜索IPA符号"><select id="ipa-category" aria-label="IPA分类"><option value="">全部分类</option><option value="favorites">收藏</option><option value="recent">最近使用</option>'+Object.entries(CorporiumIPA.categories).map(([id,name])=>'<option value="'+id+'">'+name+'</option>').join('')+'</select></div><div id="ipa-keys"></div><footer><span id="ipa-message">☆ 按语言收藏 · 收藏把手可拖动排序</span><span id="ipa-size" role="separator" tabindex="0" aria-label="调整IPA键盘宽高" title="拖动调整宽高；方向键微调"></span></footer></section>';
 document.body.append(host);const el=id=>host.querySelector('#'+id),known=new Map(CorporiumIPA.symbols.map(s=>[s.text,s]));
 let state={open:false,width:510,height:310,x:null,y:null},target=null,selection=null,owner=null,favorites=[],recent=[],frame=0,forceTop=false,drag=null;
 const composing=new WeakSet();
 try{const saved=JSON.parse(localStorage.getItem('corporium-ipa-layout')||'{}');for(const k of ['open','width','height','x','y'])if(k in saved)state[k]=saved[k];}catch{}
 const language=()=>typeof activeLanguage==='string'?activeLanguage:'all';
 const storage=(kind)=>typeof projectStorageKey==='function'?projectStorageKey('ipa-'+kind+':'+language()):'corporium-ipa-'+kind+':'+language();
 function read(kind){try{const data=JSON.parse(localStorage.getItem(storage(kind))||'[]');return Array.isArray(data)?[...new Set(data.filter(s=>known.has(s)))].slice(0,kind==='recent'?24:200):[];}catch{return [];}}
 function save(kind,value){try{localStorage.setItem(storage(kind),JSON.stringify(value));}catch{}}
 function saveLayout(){try{localStorage.setItem('corporium-ipa-layout',JSON.stringify(state));}catch{}}
 function modal(){return [...document.querySelectorAll('dialog[open]')].filter(d=>d.matches(':modal')).at(-1)||null;}
 function editable(node){const field=node?.closest?.('input,textarea,[contenteditable="true"]');if(!field||host.contains(field)||field.disabled||field.readOnly||field.closest('[inert]'))return null;if(field.tagName==='INPUT'&&!['text','search','url','tel',''].includes(field.type))return null;return field;}
 function valid(){const m=modal();return target?.isConnected&&target.getClientRects().length&&editable(target)===target&&(!m||m.contains(target));}
 function label(){if(!valid())return '请先选择输入位置';return target.getAttribute('aria-label')||target.labels?.[0]?.textContent.trim()||target.closest('label')?.textContent.trim()||target.closest('.survey-rich-box')?.querySelector('label')?.textContent||target.placeholder||'当前输入框';}
 // Keystrokes only capture the caret. Visibility checks and header writes belong
 // to opening/focusing the tool, not to each input/keyup or IME composition.
 function remember(){if(!target?.isConnected||editable(target)!==target)return;if(target.isContentEditable){const s=getSelection();if(s.rangeCount&&target.contains(s.anchorNode)&&target.contains(s.focusNode))selection=s.getRangeAt(0).cloneRange();}else selection={start:target.selectionStart,end:target.selectionEnd,direction:target.selectionDirection};}
 document.addEventListener('focusin',e=>{const field=editable(e.target);if(field){if(target!==field)selection=null;target=field;remember();}schedule();});
 document.addEventListener('compositionstart',e=>{const field=editable(e.target);if(field)composing.add(field);});
 document.addEventListener('compositionend',e=>{composing.delete(e.target);if(e.target===target)remember();});
 for(const event of ['select','keyup','pointerup','input'])document.addEventListener(event,e=>{if(e.target===target)remember();});
 document.addEventListener('selectionchange',()=>{if(target?.isContentEditable&&!host.contains(document.activeElement))remember();});
 host.addEventListener('pointerdown',e=>{if(e.target.closest('.ipa-insert,.ipa-star,#ipa-toggle,#ipa-collapse,#ipa-home'))e.preventDefault();});
 function message(text){el('ipa-message').textContent=text;}
 function insert(text){
  if(!valid()){message('请先点击要输入的文字位置');return;}
  if(composing.has(target)){message('请先完成正在输入的文字');return;}
  // Focusing contenteditable can move its caret to the start and fires focusin.
  // Keep the captured range separate until focus has finished.
  const savedSelection=target.isContentEditable?selection?.cloneRange?.():selection;
  target.focus({preventScroll:true});
  if(target.isContentEditable){const s=getSelection();if(!savedSelection||!target.contains(savedSelection.commonAncestorContainer)){message('输入位置已变化，请重新选择');return;}s.removeAllRanges();s.addRange(savedSelection);}
  else target.setSelectionRange(savedSelection?.start??target.value.length,savedSelection?.end??target.value.length,savedSelection?.direction||'none');
  const before=new InputEvent('beforeinput',{bubbles:true,cancelable:true,inputType:'insertText',data:text});if(!target.dispatchEvent(before))return;
  const previous=target.isContentEditable?target.innerHTML:target.value;let notified=false;
  const capture=()=>{notified=true;};target.addEventListener('input',capture,{once:true});
  // Chromium's editing command preserves the field's native undo stack.
  const inserted=document.execCommand('insertText',false,text);target.removeEventListener('input',capture);
  if(!inserted){message('此输入框暂不支持插入，请重新选择输入位置');return;}
  if(!notified&&(target.isContentEditable?target.innerHTML:target.value)!==previous)target.dispatchEvent(new InputEvent('input',{bubbles:true,inputType:'insertText',data:text}));
  remember();recent=[text,...recent.filter(v=>v!==text)].slice(0,24);save('recent',recent);message('已插入 '+known.get(text).display+' · '+label());render();
 }
 function keys(rows,favorite=false){return '<div class="ipa-key-grid">'+rows.map(s=>'<div class="ipa-key-cell"'+(favorite?' data-favorite="'+esc(s.text)+'"':'')+'><button type="button" class="ipa-insert" data-insert="'+esc(s.text)+'" title="'+esc(s.name+' · '+[...s.text].map(c=>'U+'+c.codePointAt(0).toString(16).toUpperCase().padStart(4,'0')).join(' '))+'" aria-label="插入'+esc(s.name)+'">'+esc(s.display)+'</button><button type="button" class="ipa-star" data-favorite-toggle="'+esc(s.text)+'" aria-pressed="'+favorites.includes(s.text)+'" aria-label="'+(favorites.includes(s.text)?'取消收藏':'收藏')+esc(s.name)+'" title="'+(favorites.includes(s.text)?'取消收藏':'按当前语言收藏')+'">'+(favorites.includes(s.text)?'★':'☆')+'</button>'+(favorite?'<button class="ipa-fav-grip" type="button" draggable="true" data-fav-grip="'+esc(s.text)+'" aria-label="调整收藏顺序：'+esc(s.name)+'" title="拖动排序；左右方向键移动">⠿</button>':'')+'</div>').join('')+'</div>';}
 function render(){const category=el('ipa-category').value,q=el('ipa-search').value,found=CorporiumIPA.find(q),match=new Set(found.map(s=>s.text));let html='';
  const section=(name,list,fav=false)=>{const rows=list.map(s=>known.get(s)).filter(s=>s&&match.has(s.text));if(rows.length)html+='<h3>'+name+'</h3>'+keys(rows,fav);};
  if(!category||category==='favorites')section('收藏',favorites,true);
  if(!category||category==='recent')section('最近使用',recent);
  if(category!=='favorites'&&category!=='recent')for(const [id,name] of Object.entries(CorporiumIPA.categories))if(!category||category===id){const rows=found.filter(s=>s.category===id);if(rows.length)html+='<h3>'+name+'</h3>'+keys(rows);}
  const scroll=el('ipa-keys').scrollTop;el('ipa-keys').innerHTML=html||'<p>没有匹配的符号'+(category==='favorites'?'，可点击符号旁的☆收藏':'')+'。</p>';el('ipa-keys').scrollTop=scroll;
 }
 function floatingButtons(){const activeModal=modal();return [...document.querySelectorAll('#add,#new-lexeme,#morpheme-new,#library-new,dialog[open]:not([hidden]) .dialog-bottom')].filter(b=>(!activeModal||activeModal.contains(b))&&b.getClientRects().length&&getComputedStyle(b).visibility!=='hidden'&&(b.matches('.dialog-bottom')||getComputedStyle(b).position==='fixed')).map(b=>b.getBoundingClientRect());}
 function position(){const margin=10,w=state.open?Math.min(Math.max(300,Number(state.width)||510),innerWidth-2*margin):64,h=state.open?Math.min(Math.max(190,Number(state.height)||310),innerHeight-2*margin):36;
  let x=state.open&&Number.isFinite(state.x)?state.x:innerWidth-w-margin,y=state.open&&Number.isFinite(state.y)?state.y:innerHeight-h-margin;
  x=Math.max(margin,Math.min(x,innerWidth-w-margin));y=Math.max(margin,Math.min(y,innerHeight-h-margin));
  for(const r of floatingButtons())if(x<r.right+8&&x+w>r.left-8&&y<r.bottom+8&&y+h>r.top-8){if(r.left-w-8>=margin)x=r.left-w-8;else y=Math.max(margin,r.top-h-8);}
  host.style.left=x+'px';host.style.top=y+'px';host.style.width=w+'px';host.style.height=h+'px';
 }
 function sync(){frame=0;const home=document.documentElement.dataset.home!=='false';if(home){if(host.matches(':popover-open'))host.hidePopover();return;}
  const parent=modal()||document.body;if(host.parentElement!==parent){if(host.matches(':popover-open'))host.hidePopover();parent.append(host);}
  if(forceTop&&host.matches(':popover-open'))host.hidePopover();forceTop=false;
  if(!host.matches(':popover-open'))host.showPopover();
  if(owner!==language()){owner=language();favorites=read('favorites');recent=read('recent');render();}
  if(el('ipa-board').hidden!==!state.open)el('ipa-board').hidden=!state.open;
  if(el('ipa-toggle').hidden!==!!state.open)el('ipa-toggle').hidden=!!state.open;
  const expanded=String(!!state.open);if(el('ipa-toggle').getAttribute('aria-expanded')!==expanded)el('ipa-toggle').setAttribute('aria-expanded',expanded);
  if(state.open){const text=label();if(el('ipa-target').textContent!==text)el('ipa-target').textContent=text;}position();
 }
 function schedule(top=false){forceTop ||= top;if(!frame)frame=requestAnimationFrame(sync);}
 function immediate(top=false){if(frame)cancelAnimationFrame(frame);frame=0;forceTop ||= top;sync();}
 el('ipa-toggle').onclick=()=>{state.open=true;saveLayout();immediate(true);};el('ipa-collapse').onclick=()=>{state.open=false;saveLayout();immediate();};el('ipa-home').onclick=()=>{state.x=state.y=null;saveLayout();immediate();};
 el('ipa-search').oninput=render;el('ipa-category').onchange=()=>{el('ipa-keys').scrollTop=0;render();};
 host.addEventListener('click',e=>{const b=e.target.closest('[data-insert],[data-favorite-toggle]');if(!b)return;if(b.dataset.insert!==undefined)insert(b.dataset.insert);else{if(language()==='all'){message('请先选择一种语言再收藏');return;}const s=b.dataset.favoriteToggle;favorites=favorites.includes(s)?favorites.filter(v=>v!==s):[...favorites,s];save('favorites',favorites);render();}});
 function start(e,mode){if(e.button!==0||e.target.closest('button,input,select'))return;e.preventDefault();const r=host.getBoundingClientRect();drag={mode,id:e.pointerId,x:e.clientX,y:e.clientY,left:r.left,top:r.top,width:r.width,height:r.height};e.currentTarget.setPointerCapture(e.pointerId);}
 el('ipa-drag').onpointerdown=e=>start(e,'move');el('ipa-size').onpointerdown=e=>start(e,'size');
 host.addEventListener('pointermove',e=>{if(!drag||e.pointerId!==drag.id)return;const dx=e.clientX-drag.x,dy=e.clientY-drag.y;if(drag.mode==='move'){state.x=drag.left+dx;state.y=drag.top+dy;}else{state.width=Math.max(300,Math.min(innerWidth-20,drag.width+dx));state.height=Math.max(190,Math.min(innerHeight-20,drag.height+dy));state.x=drag.left;state.y=drag.top;}position();});
 for(const event of ['pointerup','pointercancel','lostpointercapture'])host.addEventListener(event,()=>{if(drag){drag=null;saveLayout();}});
 el('ipa-size').onkeydown=e=>{const changes={ArrowLeft:[-10,0],ArrowRight:[10,0],ArrowUp:[0,-10],ArrowDown:[0,10]};if(changes[e.key]){e.preventDefault();state.width+=changes[e.key][0];state.height+=changes[e.key][1];position();saveLayout();}};
 let moving=null;host.addEventListener('dragstart',e=>{const grip=e.target.closest('[data-fav-grip]');if(grip){moving=grip.dataset.favGrip;e.dataTransfer.setData('text/plain',moving);e.dataTransfer.effectAllowed='move';}});
 host.addEventListener('dragover',e=>{const cell=e.target.closest('[data-favorite]');if(moving&&cell){e.preventDefault();for(const n of host.querySelectorAll('[data-ipa-drop]'))delete n.dataset.ipaDrop;cell.dataset.ipaDrop='true';}});
 host.addEventListener('drop',e=>{const cell=e.target.closest('[data-favorite]');if(moving&&cell){e.preventDefault();const order=CorporiumOrder.move(favorites,[moving],cell.dataset.favorite,e.clientX>cell.getBoundingClientRect().left+cell.getBoundingClientRect().width/2);favorites=order;save('favorites',favorites);moving=null;render();}});
 host.addEventListener('dragend',()=>{moving=null;for(const n of host.querySelectorAll('[data-ipa-drop]'))delete n.dataset.ipaDrop;});
 host.addEventListener('keydown',e=>{const grip=e.target.closest('[data-fav-grip]');if(!grip||!['ArrowLeft','ArrowRight'].includes(e.key))return;e.preventDefault();const i=favorites.indexOf(grip.dataset.favGrip),j=i+(e.key==='ArrowLeft'?-1:1);if(j<0||j>=favorites.length)return;[favorites[i],favorites[j]]=[favorites[j],favorites[i]];save('favorites',favorites);render();host.querySelector('[data-fav-grip="'+CSS.escape(grip.dataset.favGrip)+'"]')?.focus();});
 function layoutChanged(records){return records.some(r=>{
  if(host.contains(r.target))return false;
  if(r.type==='attributes')return true;
  const relevant='dialog,#add,#new-lexeme,#morpheme-new,#library-new';
  return [...r.addedNodes,...r.removedNodes].some(n=>n.nodeType===1&&(n.matches(relevant)||n.querySelector(relevant)||target&&n.contains(target)));
 });}
 new MutationObserver(records=>{if(layoutChanged(records))schedule(records.some(r=>r.type==='attributes'&&r.attributeName==='open'));}).observe(document.body,{childList:true,subtree:true,attributes:true,attributeFilter:['open','hidden']});
 new MutationObserver(()=>schedule()).observe(document.documentElement,{attributes:true,attributeFilter:['data-home','data-theme','style']});
 document.addEventListener('toggle',e=>{if(e.target!==host&&e.newState==='open')schedule(true);},true);
 window.addEventListener('resize',()=>schedule());document.addEventListener('corporium-sidebar-layout',()=>schedule());window.addEventListener('storage',()=>{owner=null;schedule();});render();schedule();
})();
