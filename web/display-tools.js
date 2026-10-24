// Display-only preferences and registered grammatical tag typography.
function grammarLabel(s,lid=activeLanguage){const description=grammarDefinitions(lid).get(String(s).toLowerCase());return `<span class="grammar-label"${description?` title="${esc(description)}"`:''}>${esc(s).replace(/#sub\[([^\[\]]*)\]/g,'<sub>$1</sub>').replace(/#(?:super|sup)\[([^\[\]]*)\]/g,'<sup>$1</sup>')}</span>`;}
function phonologicalBoundary(form){return /^(#+)$/.test(String(form).trim().replace(/\\#/g,'#'));}
function boundaryName(form,lid){const hashes=String(form).trim().replace(/\\#/g,'#'),m=JSON.parse(languageList.find(l=>l.id===lid)?.metadata||'{}');return m.phonological_boundaries?.[hashes]||`音系单位边界（${hashes.length} 个 #）`;}
function boundaryGloss(w,lid){return '';}
const grammarDisplayCache=new Map();
function registeredTags(lid){
 const metadata=languageList.find(l=>l.id===lid)?.metadata||'{}',cached=grammarDisplayCache.get(lid);
 if(cached?.metadata===metadata)return cached.names;
 const definitions=new Map(Object.entries(JSON.parse(metadata).glossary||{}).map(([name,description])=>[name.toLowerCase(),description]));
 const names=new Set(definitions.keys()),spellings=new Set(Object.keys(JSON.parse(metadata).glossary||{}));grammarDisplayCache.set(lid,{metadata,names,definitions,spellings});return names;
}
function grammarDefinitions(lid){registeredTags(lid);return grammarDisplayCache.get(lid).definitions;}
function hasRegisteredTag(s,lid,explicit=false){const names=registeredTags(lid);return names.has(s.toLowerCase())&&(explicit||!['a','all','art','pass'].includes(s.toLowerCase())||s===s.toUpperCase()||grammarDisplayCache.get(lid).spellings.has(s));}
function isRegisteredTag(s,lid){const m=s.match(/^([123])([A-Za-z]+)$/);return hasRegisteredTag(s,lid)||!!(m&&hasRegisteredTag(m[2],lid));}
function richGloss(s,lid=activeLanguage,grammatical=false){
 const known=registeredTags(lid);
 function token(t,bracketed){if(!t)return '';if(hasRegisteredTag(t,lid,bracketed))return grammarLabel(t,lid);const m=t.match(/^([123])([A-Za-z]+)$/);return m&&hasRegisteredTag(m[2],lid,bracketed)?m.slice(1).map(p=>hasRegisteredTag(p,lid,bracketed)?grammarLabel(p,lid):esc(p)).join(''):esc(t);}
 const plain=(t,bracketed=false)=>t.split(/([\s.\-=:+~/;_\\,!?，。；：！？\[\](){}<>«»“”"']+)/).map((p,i)=>i%2?p.split('>').map(esc).join('<span class="gloss-relation" title="语义与论元关系：左侧 → 右侧">&gt;</span>'):token(p,bracketed)).join('');
 function fragment(t,bracketed=false){
  return t.split(/([A-Za-z0-9]+(?:#(?:sub|super|sup)\[[^\[\]]*\])+|#(?:sub|super|sup)\[[^\[\]]*\])/g).map(p=>{
   if(!/#(?:sub|super|sup)\[/.test(p))return plain(p,bracketed);
   if(known.has(p.toLowerCase()))return grammarLabel(p,lid);
   return p.split(/(#(?:sub|super|sup)\[[^\[\]]*\])/g).map(v=>/^#(?:sub|super|sup)\[/.test(v)?(v.startsWith('#sub[')?'<sub>':'<sup>')+plain(v.slice(v.indexOf('[')+1,-1))+(v.startsWith('#sub[')?'</sub>':'</sup>'):plain(v)).join('');
  }).join('');
 }
 // Identify grammatical brackets before rendering script runs. Splitting a
 // decorated tag first would detach it from <...> and lose the infix context.
 const text=String(s||'').replace(/\\([~?\[\]#])/g,'$1');let out='',buffer='',at=0;
 for(const m of text.matchAll(/#(?:sub|super|sup)\[[^\[\]]*\]|<[^<]*>|\[(?:#(?:sub|super|sup)\[[^\[\]]*\]|[^\[\]])*\]/g)){
  buffer+=text.slice(at,m.index);at=m.index+m[0].length;
  if(m[0].startsWith('#')){buffer+=m[0];continue;}
  out+=fragment(buffer,grammatical);buffer='';const infix=m[0].startsWith('<');
  out+='<span class="'+(infix?'gloss-infix':'gloss-bracket')+'">'+(infix?'&lt;':'[')+fragment(m[0].slice(1,-1),true)+(infix?'&gt;':']')+'</span>';
 }
 return out+fragment(buffer+text.slice(at),grammatical);
}
function glossEditParts(text,gloss=true){
 const parts=[],ranges=[...text.matchAll(/<[^<]*>/g)].map(m=>[m.index,m.index+m[0].length]);let start=0,depth=0;
 for(let i=0;i<text.length;i++){const c=text[i];if(c==='[')depth++;else if(c===']')depth=Math.max(0,depth-1);else if(!depth&&!ranges.some(([a,b])=>a<=i&&i<b)&&(gloss?'~-.＝=:+/>;_\\':'~-＝=+').includes(c)){parts.push(text.slice(start,i),c);start=i+1;}}
 parts.push(text.slice(start));return parts;
}

function lexemeLabel(x){return esc(x.headword)+(x.body?.homonym_number?'<sub>'+esc(x.body.homonym_number)+'</sub>':'');}
function lexemePlainLabel(x){return x.headword+(x.body?.homonym_number?String(x.body.homonym_number).replace(/[0-9]/g,n=>'₀₁₂₃₄₅₆₇₈₉'[+n]):'');}
// Shared by text titles and dictionary headwords; only clipped text pans on hover/focus.
function setupSidebarTitlePan(host,{row,mask,text}){
 function measure(el){const title=el.querySelector(text);if(!title)return;const overflow=Math.max(0,title.scrollWidth-el.clientWidth);el.style.setProperty('--title-travel',(-overflow)+'px');el.style.setProperty('--title-duration',Math.max(6,overflow/28*2+2)+'s');el.classList.toggle('title-overflows',overflow>1);}
 // Offscreen titles only need measurement when hovered or focused. Measuring every
 // title after each row mutation forces layout thousands of times in large lists.
 let frame=0;function refresh(){if(!frame)frame=requestAnimationFrame(()=>{frame=0;host.querySelectorAll(row+':hover '+mask+','+row+':focus-within '+mask).forEach(measure);});}
 host.addEventListener('pointerover',e=>{const el=e.target.closest(mask);if(el&&!el.contains(e.relatedTarget))measure(el);});
 host.addEventListener('focusin',e=>e.target.closest(row)?.querySelectorAll(mask).forEach(measure));
 new ResizeObserver(refresh).observe(host);
 new MutationObserver(refresh).observe(host,{childList:true,subtree:true});
 document.fonts?.ready.then(refresh);document.fonts?.addEventListener('loadingdone',refresh);
 refresh();
}
let briefMode=false;
try{briefMode=localStorage.getItem('corporium-brief')==='true';}catch{}
document.documentElement.classList.toggle('brief-mode',briefMode);
function briefBody(e,kind='corpus'){return renderBody({...e,words:e.words.map(w=>({...w,unit_id:null,extra_layers:[]})),annotation_review_count:0,sentence_layers:[]},kind);}

function usageLabel(u){return (u.pos||'词类待定')+(u.subclass?' · '+u.subclass:'');}
function dictionaryTargetDescription(x){return x.target_kind==='morpheme'?[...new Set((x.body?.usages||[]).flatMap(u=>u.senses||[]).map(s=>s.short_gloss||s.definition||'').filter(Boolean))].join(' / '):(x.body?.usages||[]).map(usageLabel).join(' / ');}
function dictionaryCandidateLabel(x){const form=lexemePlainLabel({headword:x.headword,body:{homonym_number:x.homonym_number}});return x.target_kind==='morpheme'?'语素 · '+form:form+' / '+(x.pos||'词类未定');}

function uiIcon(name){const paths={copy:'M9 8h11v13H9z M5 16H3V3h12v2',delete:'M4 6h16 M9 6V3h6v3 M6 6l1 15h10l1-15 M10 10v7 M14 10v7',import:'M4 15v5h16v-5 M12 3v12 M7 10l5 5 5-5',export:'M4 15v5h16v-5 M12 15V3 M7 8l5-5 5 5',intervalDelete:'M3 6h18v12H3z M9 9l6 6 M15 9l-6 6',merge:'M2 6h7v12H2z M15 6h7v12h-7z M5 12h14 M10 9l3 3-3 3',context:'M4 4h16 M4 8h16 M4 16h16 M4 20h16 M3 11h18v2H3z'};return `<svg class="ui-icon" viewBox="0 0 24 24" width="18" height="18" fill="none" stroke="currentColor" stroke-width="1.6" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><path d="${paths[name]||''}"/></svg>`;}
