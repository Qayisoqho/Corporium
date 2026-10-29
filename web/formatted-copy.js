/* Occurrence-based selection: source records stay untouched. */
(()=>{
 'use strict';
 const core=window.CorporiumFormattedCopyFormat,records=new Map(),groupKeys=new WeakMap(),boxes=new WeakMap(),borrowed=new Map();
 let sequence=0,active=false,busy=false,selected=new Set(),pageKeys='',owner=null,frame=0,controls=[];
 function stamp(html,body,kind,id,label=''){
  if(!['corpus','independent'].includes(kind)||String(id).startsWith('new:'))return html;
  const key='formatted-'+(++sequence);records.set(key,{body,kind,id,label});
  return html.replace(/<(section|article)\b/,'<$1 data-formatted-source="'+key+'"');
 }
 window.CorporiumFormattedCopy={stamp};
 const previous=renderEditableExample;
 renderEditableExample=function(body,kind,id){return stamp(previous(body,kind,id),body,kind,id,kind==='corpus'&&Number.isInteger(body.position)?'('+body.position+')':'');};
 const visible=el=>!!el?.getClientRects().length&&getComputedStyle(el).visibility!=='hidden';
 function scope(){return [...document.querySelectorAll('dialog[open]')].filter(visible).at(-1)||null;}
 function cards(root=scope(),firstOnly=false){
  const result=[];
  // Reject hidden workspaces before asking the browser for layout. Inactive
  // controls only need one available example, not every example on the page.
  for(const el of (root||document).querySelectorAll('[data-formatted-source]')){
   if(!records.has(el.dataset.formattedSource)||el.dataset.inlineRefresh||el.closest('dialog')!==root||el.closest('[hidden],[inert]')||!visible(el))continue;
   result.push(el);if(firstOnly)break;
  }
  return result;
 }
 function idForGroup(g){if(!groupKeys.has(g))groupKeys.set(g,'copy-group-'+(++sequence));return groupKeys.get(g);}
 function plain(el){return el?.textContent.trim()||'';}
 function groupFor(card){return card.closest('.example-group');}
 function sourceMark(card){const group=groupFor(card);return group?card.closest('.example-group-example')?.querySelector(':scope>.example-group-mark'):card.closest('.entry,.lex-example')?.querySelector(':scope>.sentence-number,:scope>.dialogue-row-head>.dialogue-original');}
 function labelFor(card,index){const mark=sourceMark(card);return mark?plain(mark):records.get(card.dataset.formattedSource).label||'('+(index+1)+')';}
 function readRuns(html){
  const holder=document.createElement('div');holder.innerHTML=html;const result=[];
  function visit(node,state={}){
   if(node.nodeType===3){if(node.nodeValue)result.push({...state,text:node.nodeValue});return;}
   if(node.nodeType!==1)return;
   const tag=node.tagName,next={...state};if(tag==='SUB')next.script='sub';if(tag==='SUP')next.script='sup';
   if(node.classList.contains('grammar-label')){next.smallCaps=true;next.italic=false;}
   if(tag==='SUB'||tag==='SUP'){next.smallCaps=false;next.italic=false;}
   if(tag==='B'||tag==='STRONG')next.bold=true;if(tag==='I'||tag==='EM')next.italic=true;
   if(tag==='BR'){result.push({...state,text:'\n'});return;}
   for(const child of node.childNodes)visit(child,next);
  }
  for(const child of holder.childNodes)visit(child);return result;
 }
 function itemFor(card,index){
  const source=records.get(card.dataset.formattedSource),body=source.body,lid=body.language_id||body.text_language_id||activeLanguage;
  const metadata=JSON.parse(languageList.find(l=>l.id===lid)?.metadata||'{}');Object.assign(metadata,languageTypographySettings(metadata));
  const forms=v=>core.runs(String(v||''),{}).map(r=>r.script?{...r,italic:false}:r),gloss=v=>readRuns(richGloss(v||'',lid));
  const layers=new Map();
  for(const w of body.words||[])for(const l of w.extra_layers||[])if(l.visible)layers.set(l.id||l.name,l);
  const group=groupFor(card);let groupInfo=null;
  if(group){const heading=group.querySelector('.example-group-fold>summary,.entry-head>strong');const name=heading?[...heading.childNodes].filter(n=>n.nodeType===3).map(n=>n.textContent).join('').trim():'';groupInfo={key:idForGroup(group),number:'',name,context:plain(group.querySelector(':scope>.example-group-context,:scope>.example-group-body>.example-group-context'))};}
  const local=card.closest('.example-group-member')?.querySelector('.example-group-local');
  const judgment=source.kind==='independent'?window.CorporiumGrammaticality?.item(body,lid):null;
  return {key:card.dataset.formattedSource,sourceId:source.kind+':'+source.id,label:labelFor(card,index),metadata,group:groupInfo,judgment:{symbol:judgment?.symbol||''},
   body:{ipa:forms(body.ipa),translation:forms(body.translation),notes:body.notes||'',words:(body.words||[]).map(w=>({form:forms(w.form),gloss:phonologicalBoundary(w.form)?[]:gloss(w.gloss)}))},
   layers:[...layers].map(([key,l])=>({name:l.name,font:l.font||'Junicode',size:l.size||100,variant:l.style||'regular',values:(body.words||[]).map(w=>{const value=(w.extra_layers||[]).find(x=>(x.id||x.name)===key)?.value||'';return l.style==='small-caps'?[{text:value,smallCaps:true}]:forms(value);})})),
   sentenceLayers:(body.sentence_layers||[]).filter(l=>l.visible&&l.value).map(l=>({anchor:l.anchor,font:l.font||'Junicode',pt:11*(l.size||100)/100,bold:['bold','bolditalic'].includes(l.style),italic:['italic','bolditalic'].includes(l.style),value:forms(l.value)})),
   localJudgment:local?(local.innerText||'').trim().replace(/^(?:本处判断|Local judgment)[:：]\s*/,''):''};
 }
 function updateControls(){
  const label=active?(globalThis.CorporiumI18n?.f("15d9149dc26434",()=>[])??'复制'):(globalThis.CorporiumI18n?.f("8bbbd48ab2688e",()=>[])??'带格式复制');
  const count=(globalThis.CorporiumI18n?.f("e683e085d27e56",()=>[selected.size])??'已选 '+selected.size+' 句');
  // Complete all visibility reads before changing any button or caption.
  const states=controls.map(c=>({c,disabled:busy||(!active&&!cards(c.root,true).length)}));
  for(const {c,disabled} of states){
   if(c.copy.textContent!==label)c.copy.textContent=label;
   c.copy.classList.toggle('is-copying',active);
   if(c.copy.getAttribute('aria-pressed')!==String(active))c.copy.setAttribute('aria-pressed',String(active));
   if(c.copy.disabled!==disabled)c.copy.disabled=disabled;
   if(c.cancel.hidden!==!active)c.cancel.hidden=!active;
   if(c.cancel.disabled!==busy)c.cancel.disabled=busy;
   if(c.count.hidden!==!active)c.count.hidden=!active;
   if(c.count.textContent!==count)c.count.textContent=count;
  }
 }
 function finish(){
  active=false;selected.clear();pageKeys='';owner=null;document.documentElement.classList.remove('formatted-copy-mode');
  for(const [box,{card,listener}] of borrowed){box.removeEventListener('change',listener);box.classList.remove('formatted-copy-pick');delete box.dataset.copyOwner;boxes.delete(card);}
  borrowed.clear();window.CorporiumSentenceSelection?.lock(false);
  document.querySelectorAll('.formatted-copy-choice,.formatted-copy-pick,.formatted-copy-group-pick').forEach(el=>el.remove());updateControls();
 }
 function syncShared(){if(!active)return;for(const [box,{card}] of borrowed){box.checked?selected.add(card.dataset.formattedSource):selected.delete(card.dataset.formattedSource);}updateControls();}
 document.addEventListener('corporium-sentence-selection',syncShared);
 function addBox(card,index){
  if(boxes.get(card)?.isConnected)return;
  const entry=card.closest('.example-group-member,.entry,.lex-example'),shared=entry?.querySelector(':scope>.entry-head [data-pick]');
  if(shared){const listener=()=>{syncShared();};borrowed.set(shared,{card,listener});shared.addEventListener('change',listener);shared.classList.add('formatted-copy-pick');shared.dataset.copyOwner=card.dataset.formattedSource;boxes.set(card,shared);if(shared.checked)selected.add(card.dataset.formattedSource);return;}
  const box=document.createElement('input');box.type='checkbox';box.className='formatted-copy-pick';box.setAttribute('aria-label',(globalThis.CorporiumI18n?.f("0d3a04f4c383d0",()=>[labelFor(card,index)])??'复制例句 '+labelFor(card,index)));box.title=(globalThis.CorporiumI18n?.f("d578cda27a1f32",()=>[])??'选择带格式复制');box.checked=selected.has(card.dataset.formattedSource);
  box.onchange=()=>{if(busy)return;box.checked?selected.add(card.dataset.formattedSource):selected.delete(card.dataset.formattedSource);paint();};
  boxes.set(card,box);box.dataset.copyOwner=card.dataset.formattedSource;
  const label=document.createElement('label');label.className='formatted-copy-choice';label.append(box);
  const head=entry?.querySelector(':scope>.entry-head,:scope>.dialogue-row-head');
  (head||card.querySelector('.inline-tools')||card).prepend(label);
 }
 function paint(list=cards(owner)){
  list.forEach(addBox);
  window.CorporiumSentenceSelection?.lock(busy);
  document.querySelectorAll('.formatted-copy-pick').forEach(box=>{const key=box.dataset.copyOwner||box.closest('[data-formatted-source]')?.dataset.formattedSource;box.checked=selected.has(key);box.disabled=busy;});
  const groups=new Set(list.map(groupFor).filter(Boolean));
  for(const group of groups){let box=group.querySelector(':scope>.entry-head .formatted-copy-group-pick');if(!box){box=document.createElement('input');box.type='checkbox';box.className='formatted-copy-group-pick';box.setAttribute('aria-label',(globalThis.CorporiumI18n?.f("fa1b9f88fbe90d",()=>[])??'复制整组例句'));box.title=(globalThis.CorporiumI18n?.f("03a49d88b809b7",()=>[])??'选择整组');const head=group.querySelector(':scope>.entry-head'),heading=head?.querySelector('summary,strong')||head?.firstElementChild;if(heading)heading.prepend(box);else continue;box.onchange=()=>{if(busy)return;for(const card of cards(owner).filter(c=>groupFor(c)===group)){box.checked?selected.add(card.dataset.formattedSource):selected.delete(card.dataset.formattedSource);}paint();};}
   const members=list.filter(c=>groupFor(c)===group),n=members.filter(c=>selected.has(c.dataset.formattedSource)).length;box.checked=n===members.length;box.indeterminate=n>0&&n<members.length;box.setAttribute('aria-checked',box.indeterminate?'mixed':String(box.checked));box.disabled=busy;
  }
  updateControls();
 }
 async function clickCopy(root){
  if(busy)return;
  if(!active){if(inlineDrafts.size)throw Error((globalThis.CorporiumI18n?.f("d94bc4f1fcb435",()=>[])??'请先保存或取消正在编辑的例句。'));if($('example-group-select')?.getAttribute('aria-pressed')==='true')throw Error((globalThis.CorporiumI18n?.f("80ff85dc1ae823",()=>[])??'请先结束“选择成组”，再使用带格式复制。'));if(!cards(root).length)throw Error((globalThis.CorporiumI18n?.f("47cc37e0ab1e68",()=>[])??'本页暂无可复制的例句。'));active=true;owner=root;selected.clear();pageKeys=cards(root).map(c=>c.dataset.formattedSource).join('|');document.documentElement.classList.add('formatted-copy-mode');paint();return;}
  if(root!==owner)throw Error((globalThis.CorporiumI18n?.f("534f46cd990b3d",()=>[])??'请先结束当前页面的复制选择。'));
  const list=cards(owner);if(list.map(c=>c.dataset.formattedSource).join('|')!==pageKeys){finish();throw Error((globalThis.CorporiumI18n?.f("5692cfbdeadcdc",()=>[])??'页面内容已变化，请重新选择例句。'));}
  if(inlineDrafts.size)throw Error((globalThis.CorporiumI18n?.f("28fcad63c3c001",()=>[])??'请先保存或取消正在编辑的例句，再复制。'));
  if(!selected.size)throw Error((globalThis.CorporiumI18n?.f("91068f10ae58cb",()=>[])??'请先勾选需要复制的例句。'));
  const payload=core.build(core.numberSelection(list.map((c,i)=>selected.has(c.dataset.formattedSource)?itemFor(c,i):null).filter(Boolean)));
  if(!navigator.clipboard?.write||typeof ClipboardItem==='undefined')throw Error((globalThis.CorporiumI18n?.f("1c4b7e86aa3f46",()=>[])??'当前窗口不支持带格式剪贴板，请在桌面版或本机浏览器中使用。'));
  busy=true;paint();
  try{
   await navigator.clipboard.write([new ClipboardItem({'text/html':new Blob([payload.html],{type:'text/html'}),'text/plain':new Blob([payload.plain],{type:'text/plain'})})]);
   finish();const message=(globalThis.CorporiumI18n?.f("aab43a28cfbf4f",()=>[payload.summary.sentences,payload.summary.warnings.length?'\n'+payload.summary.warnings.map(w=>w.message).join('\n'):''])??'已带格式复制 '+payload.summary.sentences+' 句。'+(payload.summary.warnings.length?'\n'+payload.summary.warnings.map(w=>w.message).join('\n'):'')+'\n在 Word 中请选择“保留源格式”，以保留字体；宽表可在 Word 中手动分行。');
   corporiumStatus(message,'formatted-copy');if(payload.summary.warnings.length)await corporiumAlert(message);
  }catch(error){throw Error((globalThis.CorporiumI18n?.f("c3f1dd16974c29",()=>[error.message])??'带格式复制失败，已保留勾选：'+error.message));}
  finally{busy=false;if(active)paint();else updateControls();}
 }
 function controlsFor(root,host){const wrap=document.createElement('span');wrap.className='formatted-copy-controls';const copy=document.createElement('button');copy.type='button';copy.textContent=(globalThis.CorporiumI18n?.f("09873850bdb9ae",()=>[])??'带格式复制');copy.title=(globalThis.CorporiumI18n?.f("29de53a9eed80e",()=>[])??'勾选本页例句，按显示顺序复制到 Word');const cancel=document.createElement('button');cancel.type='button';cancel.textContent=(globalThis.CorporiumI18n?.f("109c2e7553d6c5",()=>[])??'取消');cancel.hidden=true;const count=document.createElement('span');count.className='formatted-copy-count';count.setAttribute('role','status');count.hidden=true;copy.onclick=async()=>{try{await clickCopy(root);}catch(error){corporiumStatus(error.message,'formatted-copy');}};cancel.onclick=()=>{if(!busy)finish();};wrap.append(copy,cancel,count);host(wrap);const c={root,copy,cancel,count,wrap};controls.push(c);return c;}
 function refresh(){
  frame=0;const present=new Set([...document.querySelectorAll('[data-formatted-source]')].map(c=>c.dataset.formattedSource));for(const key of records.keys())if(!present.has(key))records.delete(key);
  controls=controls.filter(c=>c.wrap.isConnected);
  if(active){const list=cards(owner),keys=list.map(c=>c.dataset.formattedSource).join('|');if(owner!==scope()||keys!==pageKeys){finish();return;}paint(list);}
  else updateControls();
 }
 function schedule(){if(!frame)frame=requestAnimationFrame(refresh);}
 function relevant(change){
  const target=change.target.nodeType===1?change.target:change.target.parentElement;
  if(!target||target.closest('.formatted-copy-controls,.formatted-copy-gutter,.formatted-copy-pick,#ipa-keyboard'))return false;
  if(active)return true;
  if(change.type==='attributes')return target.matches('dialog')||target.matches('[data-formatted-source]')||!!target.querySelector('[data-formatted-source]');
  return [...change.addedNodes,...change.removedNodes].some(node=>node.nodeType===1&&(node.matches('[data-formatted-source]')||node.querySelector('[data-formatted-source]')));
 }
 function init(){const after=$('toolbar-replace-open');if(after){const c=controlsFor(null,wrap=>after.after(wrap));c.copy.id='formatted-copy-open';}new MutationObserver(changes=>{if(changes.some(relevant))schedule();}).observe(document.body,{childList:true,subtree:true,attributes:true,attributeFilter:['hidden','open']});new MutationObserver(()=>{if(active)finish();schedule();}).observe(document.documentElement,{attributes:true,attributeFilter:['data-workbench']});document.addEventListener('keydown',e=>{if(e.key==='Escape'&&active&&!busy){finish();e.preventDefault();e.stopPropagation();}},true);schedule();}
 window.addEventListener('resize',schedule);document.fonts?.ready.then(schedule);document.fonts?.addEventListener('loadingdone',schedule);
 if(document.readyState==='loading')document.addEventListener('DOMContentLoaded',()=>{init();new ResizeObserver(schedule).observe(document.querySelector('main'));},{once:true});else{init();new ResizeObserver(schedule).observe(document.querySelector('main'));}
})();
