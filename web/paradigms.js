// Optional tables share stable form records with variants and principal parts.
function paradigmAddition(value=''){
 const atoms=value.trim()?value.split('.').map(v=>v.trim()):[];
 for(const atom of atoms){const plain=atom.replace(/#(?:sub|super|sup)\[[A-Za-z0-9]+\]/g,'');if(!plain||/[\s.\-=:+/;_\\,!?，。；：！？\[\](){}<>#]/.test(plain))throw Error((globalThis.CorporiumI18n?.f("7a135fd47b6c70",()=>[])??'附加标签请用点号分隔；复杂结构请使用独立标注'));}
 return [...new Set(atoms)].join('.');
}
function paradigmCompose(base='',extra=''){
 base=base.trim();extra=paradigmAddition(extra);if(!base)throw Error((globalThis.CorporiumI18n?.f("e042510716e891",()=>[])??'请选择已填写简短释义的基本义项'));if(!extra)return base;
 if(/[\s\-=+<>\[\](){}:;/_\\#]/.test(base.replace(/#(?:sub|super|sup)\[[A-Za-z0-9]+\]/g,'')))throw Error((globalThis.CorporiumI18n?.f("c67c2698d241a0",()=>[])??'基本标注含复杂结构，请使用独立标注'));
 const parts=base.split('.');if(parts.some(p=>!p))throw Error((globalThis.CorporiumI18n?.f("6e6144acd86e08",()=>[])??'基本标注含空片段'));const seen=new Set(parts.map(p=>p.toLowerCase()));
 for(const p of extra.split('.'))if(!seen.has(p.toLowerCase())){parts.push(p);seen.add(p.toLowerCase());}return parts.join('.');
}
function paradigmGloss(body,table,m){return m.gloss_mode==='inherit'?paradigmCompose((body.usages||[]).find(u=>u.id===table.usage_id)?.senses.find(s=>s.id===m.base_sense_id)?.short_gloss||'',m.gloss_addition||''):m.short_gloss||'';}
function paradigmUsages(body={},formId=null){
 const added=new Map();
 for(const t of body.paradigms||[])for(const r of t.rows||[])if(r.state==='filled')for(const f of r.realizations||[])if(formId===null||f.form_id===formId)for(const m of f.meanings||[]){
  if(!added.has(t.usage_id))added.set(t.usage_id,[]);
  added.get(t.usage_id).push({...m,short_gloss:paradigmGloss(body,t,m),paradigm_form_id:f.form_id,paradigm_label:t.title+' / '+r.labels.join(' · ')});
 }
 return (body.usages||[]).map(u=>({...u,senses:[...u.senses,...added.get(u.id)||[]]}));
}
function paradigmLayout(table){return {id:crypto.randomUUID(),title:table.title,dimensions:[...table.dimensions],rows:table.rows.map(r=>({id:crypto.randomUUID(),labels:[...r.labels],state:'unfilled',...(r.gloss_addition?{gloss_addition:r.gloss_addition}:{})}))};}
function paradigmFromTemplate(t){const p=paradigmLayout(t);return {...p,template_id:t.id,usage_id:'',notes:'',rows:p.rows.map(r=>({...r,realizations:[]}))};}
function paradigmPendingForm(value,selected,forms,detached=null){
 const form=value.trim();
 // A table retains the form it is using even if its shared variant row was removed.
 // Restore that identity, rather than merging homographs or breaking corpus links.
 if(selected&&!forms.some(f=>f.id===selected)&&detached?.id===selected&&detached.form.trim()&&(!form||form===detached.form.trim()))return {...detached};
 if(!form)return null;
 const current=forms.find(f=>f.id===selected);if(current?.form===form)return current;
 const peers=forms.filter(f=>f.form===form);
 if(peers.length>1)throw Error((globalThis.CorporiumI18n?.f("74a7e51b59a7e8",()=>[])??'同形形式有多个，请先在完整编辑中选择对应的共用形式。'));
 return peers[0]||{id:crypto.randomUUID(),form,kind:'inflected'};
}
function paradigmDetachSense(meaning,sense){
 if(meaning.base_sense_id!==sense.id)return meaning;
 const value={...meaning,base_sense_id:''};
 if(value.gloss_mode==='inherit'){value.short_gloss=paradigmCompose(sense.short_gloss,value.gloss_addition);delete value.gloss_mode;delete value.gloss_addition;}
 return value;
}
function validateParadigmForms(body){
 const forms=new Map((body.variants||[]).map(f=>[f.id,f]));
 for(const table of body.paradigms||[])for(const row of table.rows)for(const form of row.realizations){
  if(!forms.has(form.form_id))throw Error((globalThis.CorporiumI18n?.f("eda9f2c7f6f817",()=>[table.title,row.labels.join(' · ')||(globalThis.CorporiumI18n?.f("2d872b7ee5a4df",()=>[])??'未命名行')])??'变形表「'+table.title+'」的「'+(row.labels.join(' · ')||'未命名行')+'」找不到引用的词形，请重新选择或填写该行词形。'));
  if(!forms.get(form.form_id).form.trim())throw Error((globalThis.CorporiumI18n?.f("3271945e6b6996",()=>[table.title,row.labels.join(' · ')||(globalThis.CorporiumI18n?.f("49d552f712fc7c",()=>[])??'未命名行')])??'变形表「'+table.title+'」的「'+(row.labels.join(' · ')||'未命名行')+'」词形已被清空。请补填词形，或先从表格中移除此形式。'));
 }
}
function paradigmView(x){
 const forms=new Map((x.body.variants||[]).map(f=>[f.id,f]));
 return (x.body.paradigms||[]).map(t=>(globalThis.CorporiumI18n?.f("75ec0df036b752",()=>[esc(t.title),esc(usageLabel(x.body.usages.find(u=>u.id===t.usage_id)||{})),t.notes?`<p class="preserve-lines">${esc(t.notes)}</p>`:'',t.dimensions.map(d=>`<th>${esc(d)}</th>`).join(''),t.rows.map(r=>{
  const values=r.realizations.flatMap(f=>f.meanings.length?f.meanings.map(m=>({f,m})):[{f,m:{}}]);
  return (values.length?values:[{f:null,m:{}}]).map(({f,m},i)=>`<tr>${i?'':r.labels.map(l=>`<th scope="row" rowspan="${Math.max(1,values.length)}">${esc(l)}</th>`).join('')}<td>${f?`<button type="button" class="dictionary-wordform" data-morph-form="${esc(f.form_id)}">${esc(forms.get(f.form_id)?.form||(globalThis.CorporiumI18n?.f("e29e0e938316cc",()=>[])??'形式已不存在'))}</button>`:r.state==='missing'?(globalThis.CorporiumI18n?.f("62fd4575aba217",()=>[])??'无此形式'):(globalThis.CorporiumI18n?.f("03521d239d4c4e",()=>[])??'未填写')}</td><td class="gloss"><span class="paradigm-gloss-line"><span>${richGloss(paradigmGloss(x.body,t,m),x.language_id)}</span>${m.gloss_mode==='inherit'?(globalThis.CorporiumI18n?.f("6447c7f20a1231",()=>[esc(m.gloss_addition||(globalThis.CorporiumI18n?.f("1999cf85a96f7b",()=>[])??'无附加标签'))])??'<small class="paradigm-inheritance">继承＋'+esc(m.gloss_addition||'无附加标签')+'</small>'):''}</span></td><td class="preserve-lines">${esc(m.definition||'')}${m.notes?`<small>${esc(m.notes)}</small>`:''}</td></tr>`).join('');
 }).join('')])??`<section class="paradigm-view"><h3>${esc(t.title)}</h3><small>${esc(usageLabel(x.body.usages.find(u=>u.id===t.usage_id)||{}))}</small>${t.notes?`<p class="preserve-lines">${esc(t.notes)}</p>`:''}<div class="paradigm-scroll"><table><thead><tr>${t.dimensions.map(d=>`<th>${esc(d)}</th>`).join('')}<th>形式</th><th>简短标注</th><th>释义</th></tr></thead><tbody>${t.rows.map(r=>{
  const values=r.realizations.flatMap(f=>f.meanings.length?f.meanings.map(m=>({f,m})):[{f,m:{}}]);
  return (values.length?values:[{f:null,m:{}}]).map(({f,m},i)=>`<tr>${i?'':r.labels.map(l=>`<th scope="row" rowspan="${Math.max(1,values.length)}">${esc(l)}</th>`).join('')}<td>${f?`<button type="button" class="dictionary-wordform" data-morph-form="${esc(f.form_id)}">${esc(forms.get(f.form_id)?.form||'形式已不存在')}</button>`:r.state==='missing'?'无此形式':'未填写'}</td><td class="gloss"><span class="paradigm-gloss-line"><span>${richGloss(paradigmGloss(x.body,t,m),x.language_id)}</span>${m.gloss_mode==='inherit'?'<small class="paradigm-inheritance">继承＋'+esc(m.gloss_addition||'无附加标签')+'</small>':''}</span></td><td class="preserve-lines">${esc(m.definition||'')}${m.notes?`<small>${esc(m.notes)}</small>`:''}</td></tr>`).join('');
 }).join('')}</tbody></table></div></section>`)).join('');
}
(()=>{
 const editor=document.createElement('section');editor.id='paradigm-editor';
 editor.innerHTML=(globalThis.CorporiumI18n?.f("8a656c7c79d93f",()=>[])??'<h3>变形表 · Paradigm</h3><p><small>可选。简短标注可独立填写，或继承基本义项并附加标签。表格使用的词形在保存时自动登记为变体；要彻底移除形式，请从表格中一并移除。未填写与无此形式分别保留。</small></p><p id="paradigm-status" role="status"></p><div id="paradigm-tables"></div><div class="paradigm-toolbar"><select id="paradigm-template" aria-label="选择变形表模板"></select><button type="button" id="paradigm-add">＋ 添加变形表</button><button type="button" id="paradigm-manage">管理本语言模板</button></div>');
 morphologyEditorBlock.before(editor);
 let quick=false;const detachedForms=new Map();
 const quickHost=document.createElement('div');quickHost.id='paradigm-quick-tables';quickHost.hidden=true;$('paradigm-tables').after(quickHost);
 const addToolbar=editor.querySelector(':scope>.paradigm-toolbar'),quickAdd=document.createElement('details');quickAdd.className='paradigm-quick-add';quickAdd.hidden=true;quickAdd.innerHTML=(globalThis.CorporiumI18n?.f("b08a3493e10143",()=>[])??'<summary>＋ 添加变形表／模板</summary>');editor.querySelector('h3').after(quickAdd);
 const id=()=>crypto.randomUUID(),field=(key,label,value='',area=false)=>`<label>${esc(label)}${area?`<textarea data-p="${key}" rows="2">${esc(value)}</textarea>`:`<input data-p="${key}" value="${esc(value)}">`}</label>`;
 const val=(el,key)=>el.querySelector(`[data-p="${key}"]`).value;
 const options=(values,value,empty)=>wsOptions(values,value,empty);
 function templates(){return JSON.parse(languageList.find(l=>l.id===$('lexeme-language').value)?.metadata||'{}').paradigm_templates||[];}
 function templateChoices(){const s=$('paradigm-template'),v=s.value,values=templates();s.innerHTML=(globalThis.CorporiumI18n?.f("c7621088e4f6ce",()=>[quick?' hidden':'',values.map(t=>`<option value="${esc(t.id)}">${esc(t.title)}</option>`).join('')])??'<option value=""'+(quick?' hidden':'')+'>空白表格</option>'+values.map(t=>`<option value="${esc(t.id)}">${esc(t.title)}</option>`).join(''));s.value=v;if(quick&&!s.value&&values.length)s.value=values[0].id;}
 function move(row){const tools=document.createElement('div');tools.className='paradigm-toolbar';tools.innerHTML=(globalThis.CorporiumI18n?.f("9d3f6e45020c5f",()=>[])??'<button type="button" data-p-up>上移</button><button type="button" data-p-down>下移</button><button type="button" data-p-remove>移除</button>');row.append(tools);tools.onclick=e=>{
  const b=e.target.closest('button');if(!b)return;
  if(b.hasAttribute('data-p-up')&&row.previousElementSibling)row.before(row.previousElementSibling);
  if(b.hasAttribute('data-p-down')&&row.nextElementSibling)row.nextElementSibling.after(row);
  if(b.hasAttribute('data-p-remove'))row.remove();lexemeDirty=true;
 };}
 function baseSenses(uid){const u=[...$('lexeme-usages').children].find(u=>u.dataset.id===uid);return [...u?.querySelector('.sense-editors').children||[]].map((s,i)=>{if(!s.dataset.id)s.dataset.id=id();return {id:s.dataset.id,short_gloss:s.querySelector('.sense-short').value,label:(i+1)+'. '+(s.querySelector('.sense-short').value||s.querySelector('.sense-definition').value||(globalThis.CorporiumI18n?.f("4264618e63f941",()=>[])??'未填写'))};});}
 function tagSelect(select,tags){select.innerHTML=(globalThis.CorporiumI18n?.f("312db3735bbf16",()=>[tags.map(t=>`<option value="${esc(t.symbol)}">${esc(t.symbol+(t.description?' · '+t.description:''))}</option>`).join('')])??'<option value="">＋ 已有标签</option>'+tags.map(t=>`<option value="${esc(t.symbol)}">${esc(t.symbol+(t.description?' · '+t.description:''))}</option>`).join(''));}
 function glossControl(host,m,uid,onchange=()=>{}){
  const box=document.createElement('div');box.className='paradigm-gloss-controls';
  box.innerHTML=(globalThis.CorporiumI18n?.f("95c9cddd0077ed",()=>[])??'<select class="paradigm-mode" aria-label="变形标注模式"><option value="independent">独立标注</option><option value="inherit">继承＋附加标签</option></select><select class="paradigm-base" aria-label="对应基本义项"></select><input data-p="short_gloss" aria-label="变形简短标注" placeholder="完整简短标注"><div class="paradigm-addition-row"><input data-p="gloss_addition" aria-label="附加标签" placeholder="如 NOM 或 ACC.SG"><select class="paradigm-tag-select" aria-label="选择已有语法标签"></select></div><output class="paradigm-gloss-preview" aria-live="polite"></output>');
  host.append(box);const mode=box.querySelector('.paradigm-mode'),base=box.querySelector('.paradigm-base'),full=box.querySelector('[data-p="short_gloss"]'),extra=box.querySelector('[data-p="gloss_addition"]'),picker=box.querySelector('.paradigm-tag-select'),preview=box.querySelector('output');let previousMode='independent';
  function bases(value=base.value){const values=baseSenses(uid());base.innerHTML=options(values,value,(globalThis.CorporiumI18n?.f("25f911b75fb971",()=>[])??'选择基本义项'));if(value&&!values.some(s=>s.id===value))base.add(new Option((globalThis.CorporiumI18n?.f("6238dedea75247",()=>[])??'原基本义项已不存在，请调整'),value));base.value=value;}
  function read(){return {base_sense_id:base.value,short_gloss:mode.value==='inherit'?'':full.value,...(mode.value==='inherit'?{gloss_mode:'inherit',gloss_addition:extra.value}:{})};}
  function refresh(){bases();const inherited=mode.value==='inherit';full.hidden=inherited;box.querySelector('.paradigm-addition-row').hidden=!inherited;preview.hidden=!inherited;box.classList.toggle('is-inherited',inherited);try{preview.textContent=inherited?'→ '+paradigmCompose(baseSenses(uid()).find(s=>s.id===base.value)?.short_gloss||'',extra.value):'';preview.classList.remove('invalid');}catch(e){preview.textContent=e.message;preview.classList.add('invalid');}}
  function set(value){mode.value=value.gloss_mode||'independent';previousMode=mode.value;bases(value.base_sense_id||'');full.value=value.short_gloss||'';extra.value=value.gloss_addition||'';refresh();}
  const tagChoices=()=>morphEditorData.tags.filter(t=>t.language_id===$('lexeme-language').value);tagSelect(picker,tagChoices());picker.onfocus=()=>tagSelect(picker,tagChoices());picker.onchange=()=>{if(!picker.value)return;extra.value=[extra.value,picker.value].filter(Boolean).join('.');picker.value='';refresh();onchange(read());lexemeDirty=true;};
  base.onfocus=()=>bases();base.onchange=()=>{refresh();onchange(read());lexemeDirty=true;};
  mode.onchange=()=>{try{if(mode.value==='independent'&&previousMode==='inherit')full.value=paradigmCompose(baseSenses(uid()).find(s=>s.id===base.value)?.short_gloss||'',extra.value);else if(mode.value==='inherit'&&full.value.trim()){const label=baseSenses(uid()).find(s=>s.id===base.value)?.short_gloss?.trim()||'';if(label&&full.value.trim()===label)extra.value='';else if(label&&full.value.trim().startsWith(label+'.'))extra.value=paradigmAddition(full.value.trim().slice(label.length+1));else throw Error((globalThis.CorporiumI18n?.f("70a4e492400529",()=>[])??'现有完整标注不能直接拆分，请先选择对应义项并调整标注。'));}previousMode=mode.value;refresh();onchange(read());lexemeDirty=true;}catch(e){mode.value=previousMode;refresh();$('lexeme-error').textContent=e.message;}};
  for(const input of [full,extra])input.oninput=()=>{refresh();onchange(read());lexemeDirty=true;};
  const control={read,set,refresh};box.control=control;set(m);return control;
 }
 function readMeaning(row){return {id:row.dataset.id,...row.glossControl.read(),definition:val(row,'definition'),notes:val(row,'notes')};}
 function meaning(list,m={},uid){
  if(!m.id&&!m.short_gloss&&!m.base_sense_id)m={...uid.defaults?.(),...m};
  const row=document.createElement('section');row.className='paradigm-meaning';row.dataset.id=m.id||id();
  list.append(row);row.glossControl=glossControl(row,m,uid);row.insertAdjacentHTML('beforeend',(globalThis.CorporiumI18n?.f("2bd8e1640c69fa",()=>[field('definition',(globalThis.CorporiumI18n?.f("1bc310c9b8d392",()=>[])??'释义'),m.definition,true),field('notes',(globalThis.CorporiumI18n?.f("f108ff28943caf",()=>[])??'备注'),m.notes,true)])??`<button type="button" class="paradigm-copy-meaning">从基本义项复制</button>${field('definition','释义',m.definition,true)}<details><summary>意义备注</summary>${field('notes','备注',m.notes,true)}</details>`));
  row.querySelector('.paradigm-copy-meaning').onclick=()=>{const value=row.glossControl.read(),u=[...$('lexeme-usages').children].find(u=>u.dataset.id===uid()),sense=[...u?.querySelector('.sense-editors').children||[]].find(s=>s.dataset.id===value.base_sense_id);if(!sense)return;if(value.gloss_mode!=='inherit'&&value.short_gloss||val(row,'definition')){$('lexeme-error').textContent=(globalThis.CorporiumI18n?.f("354f1712e573db",()=>[])??'请先清空本形式的释义，再从基本义项复制。');return;}if(value.gloss_mode!=='inherit')row.glossControl.set({...value,short_gloss:sense.querySelector('.sense-short').value});row.querySelector('[data-p="definition"]').value=sense.querySelector('.sense-definition').value;lexemeDirty=true;};move(row);
 }
 function realization(list,f={},uid){
  const row=document.createElement('section');row.className='paradigm-realization';row.dataset.id=f.id||id();
  row.innerHTML=(globalThis.CorporiumI18n?.f("ace8fae58f32b5",()=>[options(wsVariants(),f.form_id,(globalThis.CorporiumI18n?.f("02b9ec576202bd",()=>[])??'选择已有形式'))])??`<label>共用形式<select class="paradigm-form">${options(wsVariants(),f.form_id,'选择已有形式')}</select></label><div class="paradigm-new-form"><input aria-label="新变形形式" placeholder="或在此登记新形式"><button type="button" class="paradigm-register">登记新形式</button></div><div class="paradigm-meanings"></div><button type="button" class="paradigm-add-meaning">＋ 添加意义</button>`);
  list.append(row);const select=row.querySelector('select');select.onfocus=()=>{const forms=wsVariants(),saved=detachedForms.get(select.value);if(saved&&!forms.some(f=>f.id===saved.id))forms.push({id:saved.id,label:(globalThis.CorporiumI18n?.f("f3b35619335a5d",()=>[saved.form])??saved.form+'（保存时自动登记）')});select.innerHTML=options(forms,select.value,(globalThis.CorporiumI18n?.f("ef578e78146e53",()=>[])??'选择已有形式'));};
  row.querySelector('.paradigm-register').onclick=()=>{try{registerPending(row);lexemeDirty=true;}catch(e){$('lexeme-error').textContent=e.message;}};
  const meanings=row.querySelector('.paradigm-meanings');for(const m of f.meanings||[])meaning(meanings,m,uid);
  row.querySelector('.paradigm-add-meaning').onclick=()=>{meaning(meanings,{},uid);lexemeDirty=true;};move(row);
 }
 function registerPending(row){
  const input=row.querySelector('.paradigm-new-form input'),select=row.querySelector('.paradigm-form');
  const forms=[...$('lexeme-variants').children].map(r=>({id:r.dataset.id,form:r.querySelector('.variant-form').value.trim()}));
  const choice=paradigmPendingForm(input.value,select.value,forms,detachedForms.get(select.value));if(!choice)return;
  if(!forms.some(f=>f.id===choice.id))addVariant(choice);
  detachedForms.delete(choice.id);
  select.innerHTML=options(wsVariants(),choice.id,(globalThis.CorporiumI18n?.f("df8c29629a8eaf",()=>[])??'选择已有形式'));input.value='';
 }
 function flushPending(){for(const row of $('paradigm-tables').querySelectorAll('.paradigm-realization')){
  registerPending(row);
  if(!row.querySelector('.paradigm-form').value&&[...row.querySelectorAll('.paradigm-meanings input,.paradigm-meanings textarea,.paradigm-base')].some(e=>e.value.trim()))throw Error((globalThis.CorporiumI18n?.f("42e93804d551e0",()=>[])??'已填写变形意义，请同时填写或选择该行的形式。'));
 }}
 function tableRow(list,r={},table){
  const row=document.createElement('details');row.className='paradigm-row';row.dataset.id=r.id||id();row.open=!r.id;
  const dims=readDimensions(table);row.innerHTML=(globalThis.CorporiumI18n?.f("2fd751319209ab",()=>[dims.map((d,i)=>field('label-'+i,d,r.labels?.[i])).join('')])??`<summary></summary><div class="paradigm-labels">${dims.map((d,i)=>field('label-'+i,d,r.labels?.[i])).join('')}</div><label>此行状态<select class="paradigm-state"><option value="unfilled">未填写</option><option value="filled">已填写</option><option value="missing">无此形式</option></select></label><div class="paradigm-realizations"></div><button type="button" class="paradigm-add-form">＋ 添加形式</button>`);
  list.append(row);const state=row.querySelector('.paradigm-state'),forms=row.querySelector('.paradigm-realizations');state.value=r.state||'unfilled';
  row.insertAdjacentHTML('beforeend',(globalThis.CorporiumI18n?.f("a9d0ac958a740f",()=>[esc(r.gloss_addition||'')])??`<label class="paradigm-row-preset">新形式预设附加标签<input data-p="gloss_addition" value="${esc(r.gloss_addition||'')}" placeholder="可留空，如 NOM"></label>`));
  const uid=()=>table.querySelector('.paradigm-usage').value;uid.defaults=()=>{const base=table.querySelector('.paradigm-default-base').value;return base?{base_sense_id:base,gloss_mode:'inherit',gloss_addition:val(row,'gloss_addition')}:{}};row.paradigmUID=uid;for(const f of r.realizations||[])realization(forms,f,uid);
  state.onchange=()=>{if(state.value!=='filled'&&forms.children.length){state.value='filled';$('lexeme-error').textContent=(globalThis.CorporiumI18n?.f("4d6f95f0fa587b",()=>[])??'请先移除本行的形式，再设为未填写或无此形式。');}};
  row.querySelector('.paradigm-add-form').onclick=()=>{state.value='filled';realization(forms,{meanings:[{}]},uid);refreshSummary();lexemeDirty=true;};move(row);
  function refreshSummary(){const labels=[...row.querySelectorAll('.paradigm-labels input')].map(i=>i.value).filter(Boolean).join(' · ')||(globalThis.CorporiumI18n?.f("e9a1a4101b4b6e",()=>[])??'新行'),names=[...row.querySelectorAll('.paradigm-form')].map(s=>s.selectedOptions[0]?.textContent||(globalThis.CorporiumI18n?.f("97f603c9f030bd",()=>[])??'未选形式'));row.querySelector('summary').textContent=labels+' — '+(state.value==='missing'?(globalThis.CorporiumI18n?.f("e34d93560b3f31",()=>[])??'无此形式'):names.join(' / ')||(globalThis.CorporiumI18n?.f("66754272a77800",()=>[])??'未填写'));}
  row.refreshParadigmSummary=refreshSummary;row.addEventListener('input',refreshSummary);row.addEventListener('change',refreshSummary);row.addEventListener('click',()=>queueMicrotask(refreshSummary));refreshSummary();
 }
 function readDimensions(t){return val(t,'dimensions').split('|').map(s=>s.trim());}
 function readTable(t){return {id:t.dataset.id,template_id:t.dataset.templateId||'',title:val(t,'title'),notes:val(t,'notes'),usage_id:t.querySelector('.paradigm-usage').value,default_base_sense_id:t.querySelector('.paradigm-default-base').value,dimensions:readDimensions(t),rows:[...t.querySelector('.paradigm-rows').children].map(r=>({id:r.dataset.id,labels:[...r.querySelector('.paradigm-labels').querySelectorAll('input')].map(i=>i.value),state:r.querySelector('.paradigm-state').value,gloss_addition:val(r,'gloss_addition'),realizations:[...r.querySelector('.paradigm-realizations').children].map(f=>({id:f.dataset.id,form_id:f.querySelector('.paradigm-form').value,meanings:[...f.querySelector('.paradigm-meanings').children].map(readMeaning)})).filter(f=>f.form_id)}))};}
 function addTable(t={title:(globalThis.CorporiumI18n?.f("8fc1c3f6a096be",()=>[])??'变形表'),dimensions:[(globalThis.CorporiumI18n?.phrase('数')??'数'),(globalThis.CorporiumI18n?.f("a098f6a717f543",()=>[])??'格')],rows:[]}){
  const el=document.createElement('section');el.className='paradigm-table-editor';el.dataset.id=t.id||id();el.dataset.templateId=t.template_id||'';
  el.innerHTML=(globalThis.CorporiumI18n?.f("a355d4f29365d7",()=>[field('title',(globalThis.CorporiumI18n?.f("35ceaf2f0f54ab",()=>[])??'表名'),t.title),options(wsUsages(),t.usage_id,(globalThis.CorporiumI18n?.f("0c56306c41d36f",()=>[])??'请选择词类用法')),field('dimensions',(globalThis.CorporiumI18n?.f("8334ab25343792",()=>[])??'分类栏目（用 | 分开，例如：数 | 格 | 有生性）'),t.dimensions.join(' | ')),field('notes',(globalThis.CorporiumI18n?.f("1b663056995ac5",()=>[])??'表格备注'),t.notes,true)])??`<div class="metadata-grid">${field('title','表名',t.title)}<label>词类用法<select class="paradigm-usage">${options(wsUsages(),t.usage_id,'请选择词类用法')}</select></label></div>${field('dimensions','分类栏目（用 | 分开，例如：数 | 格 | 有生性）',t.dimensions.join(' | '))}<button type="button" class="paradigm-columns">应用栏目</button>${field('notes','表格备注',t.notes,true)}<div class="paradigm-rows"></div><div class="paradigm-toolbar"><button type="button" class="paradigm-add-row">＋ 添加一行</button><button type="button" class="paradigm-save-template">存为本语言模板</button></div>`);
  $('paradigm-tables').append(el);const usage=el.querySelector('.paradigm-usage');if(!t.usage_id&&wsUsages().length===1)usage.value=wsUsages()[0].id;usage.onfocus=()=>usage.innerHTML=options(wsUsages(),usage.value,(globalThis.CorporiumI18n?.f("37ea90355e9d81",()=>[])??'请选择词类用法'));
  usage.parentElement.insertAdjacentHTML('afterend',(globalThis.CorporiumI18n?.f("e3dfa4c6581b17",()=>[])??'<label>新形式默认继承义项<select class="paradigm-default-base" aria-label="新形式默认继承义项"></select></label>'));
  const defaultBase=el.querySelector('.paradigm-default-base'),refreshBase=()=>{const value=defaultBase.value;defaultBase.innerHTML=options(baseSenses(usage.value),value,(globalThis.CorporiumI18n?.f("ccd866537cade0",()=>[])??'新形式使用独立标注'));if(value&&!baseSenses(usage.value).some(s=>s.id===value))defaultBase.add(new Option((globalThis.CorporiumI18n?.f("5bc5e49b6c4510",()=>[])??'原默认义项已不存在，请调整'),value));defaultBase.value=value;};refreshBase();defaultBase.value=t.default_base_sense_id||'';defaultBase.onfocus=refreshBase;
  usage.onchange=()=>{refreshBase();for(const controls of el.querySelectorAll('.paradigm-gloss-controls'))controls.control.refresh();};
  const list=el.querySelector('.paradigm-rows');for(const r of t.rows)tableRow(list,r,el);
  el.querySelector('.paradigm-add-row').onclick=()=>{tableRow(list,{},el);lexemeDirty=true;};
  el.querySelector('.paradigm-columns').onclick=()=>{try{flushPending();const dims=readDimensions(el);if(!dims.length||dims.length>12||dims.some(d=>!d))throw Error((globalThis.CorporiumI18n?.f("c53697505dc40e",()=>[])??'请填写 1–12 个非空栏目名称。'));const rows=readTable(el).rows;if(rows.some(r=>r.labels.slice(dims.length).some(v=>v.trim())))throw Error((globalThis.CorporiumI18n?.f("b74bc9f102de84",()=>[])??'缩减栏目之前，请先清空将移除栏目中的内容。'));list.replaceChildren();for(const r of rows)tableRow(list,{...r,labels:dims.map((d,i)=>r.labels[i]||'')},el);lexemeDirty=true;}catch(e){$('lexeme-error').textContent=e.message;}};
  el.querySelector('.paradigm-save-template').onclick=async()=>{try{const t=readTable(el),entry=languageList.find(l=>l.id===$('lexeme-language').value),metadata=JSON.parse(entry.metadata);metadata.paradigm_templates=[...metadata.paradigm_templates||[],paradigmLayout(t)];await api('save-language',{id:entry.id,revision:entry.revision,name:entry.name,metadata,_language:entry.id});await loadLanguages();templateChoices();$('paradigm-status').textContent=(globalThis.CorporiumI18n?.f("40ecdd72770c2a",()=>[])??'模板已保存，包含栏目、行类别和预设附加标签。');}catch(e){$('lexeme-error').textContent=e.message;}};move(el);if(quick)renderQuick();
 }
 function renderQuick(){
  if(!quick)return;quickHost.replaceChildren();
  // Only two entry fields per visible row. Advanced controls mount on demand.
  for(const source of $('paradigm-tables').children){
   const box=document.createElement('section');box.className='paradigm-quick-table';
   const dims=readDimensions(source);
   box.innerHTML=(globalThis.CorporiumI18n?.f("28c998a9233fda",()=>[esc(dims.length===1?dims[0]:(globalThis.CorporiumI18n?.f("f97fc3067cdee7",()=>[])??'类别'))])??'<div class="paradigm-quick-heading"><strong class="paradigm-quick-title"></strong><label class="paradigm-quick-default">新增形式沿用<select aria-label="新形式默认继承义项" title="为新添加的形式选择基本义项；已有形式可在各行设置中修改。"></select></label><button type="button" class="paradigm-table-settings-toggle" aria-expanded="false">表设置</button></div><div class="paradigm-quick-table-settings" hidden><label>表名<input aria-label="变形表名称"></label><label>词类用法<select aria-label="变形表所属用法"></select></label><button type="button" class="paradigm-remove-table danger">移除表格</button></div><div class="paradigm-scroll"><table><colgroup><col class="pq-category-col"><col class="pq-form-col"><col class="pq-gloss-col"><col class="pq-preview-col"><col class="pq-tools-col"></colgroup><thead><tr><th>'+esc(dims.length===1?dims[0]:'类别')+'</th><th>词形</th><th title="沿用基本义项时只填附加标签；也可在行设置中改为独立标注。">标注</th><th>最终标注</th><th aria-label="行设置"></th></tr></thead><tbody></tbody></table></div>');
   quickHost.append(box);
   const title=box.querySelector((globalThis.CorporiumI18n?.f("b32eb678577be1",()=>[])??'[aria-label="变形表名称"]')),usage=box.querySelector((globalThis.CorporiumI18n?.f("a636b7258bac92",()=>[])??'[aria-label="变形表所属用法"]')),sourceUsage=source.querySelector('.paradigm-usage'),baseDefault=box.querySelector((globalThis.CorporiumI18n?.f("cb3be87993c0a8",()=>[])??'[aria-label="新形式默认继承义项"]')),sourceDefault=source.querySelector('.paradigm-default-base'),tbody=box.querySelector('tbody');
   title.value=val(source,'title');box.querySelector('.paradigm-quick-title').textContent=title.value;
   title.oninput=()=>{source.querySelector('[data-p="title"]').value=title.value;box.querySelector('.paradigm-quick-title').textContent=title.value;lexemeDirty=true;};
   usage.innerHTML=options(wsUsages(),sourceUsage.value,(globalThis.CorporiumI18n?.f("010191ec5d7a18",()=>[])??'选择用法'));usage.onchange=()=>{sourceUsage.innerHTML=options(wsUsages(),usage.value,(globalThis.CorporiumI18n?.f("f1b4da72273632",()=>[])??'请选择词类用法'));sourceUsage.onchange();lexemeDirty=true;renderQuick();};
   baseDefault.onfocus=()=>{sourceDefault.onfocus();baseDefault.innerHTML=sourceDefault.innerHTML;baseDefault.options[0].textContent=(globalThis.CorporiumI18n?.f("5edafcfc33e8b7",()=>[])??'独立标注');baseDefault.value=sourceDefault.value;};baseDefault.onfocus();
   baseDefault.onchange=()=>{sourceDefault.value=baseDefault.value;lexemeDirty=true;renderQuick();};
   box.querySelector('.paradigm-table-settings-toggle').onclick=e=>{const panel=box.querySelector('.paradigm-quick-table-settings');panel.hidden=!panel.hidden;e.currentTarget.setAttribute('aria-expanded',String(!panel.hidden));};
   box.querySelector('.paradigm-remove-table').onclick=()=>{source.remove();lexemeDirty=true;renderQuick();};
   function focusRow(identity,field){const row=[...quickHost.querySelectorAll('.paradigm-quick-row')].find(r=>r.dataset.meaning===identity||r.dataset.realization===identity);row?.querySelector(field)?.focus();}
   tbody.addEventListener('keydown',e=>{
    if(e.isComposing||e.ctrlKey||e.altKey||e.metaKey||!e.target.matches('.paradigm-quick-row input')||!['Tab','Enter'].includes(e.key))return;
    const rows=[...tbody.querySelectorAll('.paradigm-quick-row')].map(r=>[...r.querySelectorAll('input')].filter(i=>!i.disabled));
    const flat=rows.flat(),at=flat.indexOf(e.target);let target;
    if(e.key==='Tab')target=flat[at+(e.shiftKey?-1:1)];
    else{const row=rows.findIndex(r=>r.includes(e.target)),column=rows[row]?.indexOf(e.target),step=e.shiftKey?-1:1;for(let i=row+step;i>=0&&i<rows.length;i+=step)if(rows[i][column]){target=rows[i][column];break;}}
    // Enter edits the next row, never submits the complete dictionary form.
    if(e.key==='Enter'||target)e.preventDefault();if(target){target.focus();target.select();}
   });
   for(const category of source.querySelector('.paradigm-rows').children){
    const forms=category.querySelector('.paradigm-realizations'),state=category.querySelector('.paradigm-state'),uid=category.paradigmUID;
    const labels=[...category.querySelectorAll('.paradigm-labels input')].map(i=>i.value),categoryLabel=labels.join(' · ');
    const items=[...forms.children].flatMap(f=>{const meanings=[...f.querySelector('.paradigm-meanings').children];return (meanings.length?meanings:[null]).map(m=>({f,m}));});if(!items.length)items.push({f:null,m:null});
    for(const item of items){
     const tr=document.createElement('tr');tr.className='paradigm-quick-row';tr.dataset.realization=item.f?.dataset.id||'';tr.dataset.meaning=item.m?.dataset.id||'';
     tr.innerHTML=(globalThis.CorporiumI18n?.f("1276e07d31830d",()=>[esc(categoryLabel),esc((globalThis.CorporiumI18n?.f("cd75fbbaece4fb",()=>[categoryLabel])??categoryLabel+'：行设置'))])??'<th scope="row">'+esc(categoryLabel)+'</th><td><input class="paradigm-quick-form" aria-label="变形形式"></td><td><input class="paradigm-quick-label" aria-label="变形标注"></td><td class="paradigm-quick-result"></td><td class="paradigm-quick-tools"><button type="button" class="paradigm-row-settings" aria-label="'+esc(categoryLabel+'：行设置')+'" aria-expanded="false" title="选择标签、独立标注、释义及更多操作">⋯</button></td>');
     const detail=document.createElement('tr');detail.className='paradigm-quick-detail';detail.hidden=true;detail.innerHTML='<td colspan="5"><div class="paradigm-row-settings-panel"></div></td>';
     tbody.append(tr,detail);
     const form=tr.querySelector('.paradigm-quick-form'),label=tr.querySelector('.paradigm-quick-label'),preview=tr.querySelector('.paradigm-quick-result'),more=tr.querySelector('button');
     const selected=item.f?.querySelector('.paradigm-form').value||'',variant=[...$('lexeme-variants').children].find(v=>v.dataset.id===selected);
     form.value=item.f?.querySelector('.paradigm-new-form input').value||variant?.querySelector('.variant-form').value||detachedForms.get(selected)?.form||'';form.paradigmSource=item.f;
     const current=()=>item.m?readMeaning(item.m):uid.defaults();
     const ensure=()=>{if(!item.f){realization(forms,{meanings:[{}]},uid);item.f=forms.lastElementChild;item.m=item.f.querySelector('.paradigm-meanings').firstElementChild;form.paradigmSource=item.f;}if(!item.m){const list=item.f.querySelector('.paradigm-meanings');meaning(list,{},uid);item.m=list.lastElementChild;}tr.dataset.realization=item.f.dataset.id;tr.dataset.meaning=item.m.dataset.id;state.value='filled';lexemeDirty=true;};
     let advanced;
     function refresh(){
      const value=current(),inherited=value.gloss_mode==='inherit',text=inherited?value.gloss_addition||'':value.short_gloss||'';
      if(label.value!==text)label.value=text;label.placeholder=inherited?(globalThis.CorporiumI18n?.f("60cdcfafebec1b",()=>[])??'附加标签'):(globalThis.CorporiumI18n?.f("1a6785aff36c5b",()=>[])??'完整标注');label.setAttribute('aria-label',inherited?(globalThis.CorporiumI18n?.f("2a6e4332e54b2b",()=>[])??'附加标签'):(globalThis.CorporiumI18n?.f("3e9635a2c9c244",()=>[])??'独立标注'));label.title=inherited?(globalThis.CorporiumI18n?.f("b6e6f3b12e527d",()=>[])??'只填这一形式新增的标签，例如 ACC。'):(globalThis.CorporiumI18n?.f("a6df296717c29f",()=>[])??'此形式独立填写的完整标注。');
      form.disabled=label.disabled=state.value==='missing';form.placeholder=state.value==='missing'?(globalThis.CorporiumI18n?.f("df99c1af39cf0d",()=>[])??'无此形式'):(globalThis.CorporiumI18n?.f("a2afc432d962a9",()=>[])??'词形');preview.classList.remove('invalid');
      try{const result=inherited?paradigmCompose(baseSenses(uid()).find(s=>s.id===value.base_sense_id)?.short_gloss||'',value.gloss_addition||''):value.short_gloss||'';preview.innerHTML=state.value==='missing'?(globalThis.CorporiumI18n?.f("e1336ed749e761",()=>[])??'<small>无此形式</small>'):(inherited?'':(globalThis.CorporiumI18n?.f("a67c875a06719a",()=>[])??'<small class="paradigm-independent-badge">独立</small>'))+'<span>'+esc(result||'—')+'</span>';preview.title=result;}catch(e){preview.textContent=e.message;preview.title=e.message;preview.classList.add('invalid');}
      if(advanced)advanced.set(value);
     }
     tr.refreshQuickGloss=refresh;refresh();
     form.oninput=()=>{ensure();const select=item.f.querySelector('.paradigm-form'),pending=item.f.querySelector('.paradigm-new-form input');let v=[...$('lexeme-variants').children].find(v=>v.dataset.id===select.value);if(!v&&!pending.value&&detachedForms.has(select.value)){registerPending(item.f);v=[...$('lexeme-variants').children].find(v=>v.dataset.id===select.value);}if(v&&!pending.value){v.querySelector('.variant-form').value=form.value;for(const peer of quickHost.querySelectorAll('.paradigm-quick-form'))if(peer!==form&&peer.paradigmSource?.querySelector('.paradigm-form').value===select.value)peer.value=form.value;}else{pending.value=form.value;for(const peer of quickHost.querySelectorAll('.paradigm-quick-form'))if(peer!==form&&peer.paradigmSource===item.f)peer.value=form.value;}refresh();};
     label.oninput=()=>{ensure();const value=current();if(value.gloss_mode==='inherit')value.gloss_addition=label.value;else value.short_gloss=label.value;item.m.glossControl.set(value);refresh();};
     more.onclick=()=>{
      const opening=detail.hidden;
      for(const row of tbody.querySelectorAll('.paradigm-quick-detail'))row.hidden=true;
      for(const button of tbody.querySelectorAll('.paradigm-row-settings'))button.setAttribute('aria-expanded','false');
      detail.hidden=!opening;more.setAttribute('aria-expanded',String(opening));if(!opening)return;
      const panel=detail.querySelector('.paradigm-row-settings-panel');panel.replaceChildren();
      advanced=glossControl(panel,current(),uid,value=>{ensure();item.m.glossControl.set(value);refresh();});
      panel.insertAdjacentHTML('beforeend',(globalThis.CorporiumI18n?.f("5589e78ba52919",()=>[])??'<div class="paradigm-quick-meaning-notes"><label>详细释义<textarea rows="1" class="pq-definition"></textarea></label><label>意义备注<textarea rows="1" class="pq-notes"></textarea></label></div><div class="paradigm-quick-row-actions"><label>本行状态<select class="paradigm-quick-state"><option value="unfilled">未填写</option><option value="filled">已填写</option><option value="missing">无此形式</option></select></label><button type="button" data-pq-form>＋ 另一形式</button><button type="button" data-pq-meaning>＋ 另一意义</button><button type="button" data-pq-remove>移除此形式／意义</button></div>'));
      for(const [selector,key] of [['.pq-definition','definition'],['.pq-notes','notes']]){const input=panel.querySelector(selector);input.value=item.m?val(item.m,key):'';input.oninput=()=>{ensure();item.m.querySelector('[data-p="'+key+'"]').value=input.value;};}
      for(const control of panel.querySelectorAll('.paradigm-gloss-controls input,.paradigm-gloss-controls select,textarea'))control.disabled=state.value==='missing';
      const statePicker=panel.querySelector('.paradigm-quick-state');statePicker.value=state.value;statePicker.onchange=()=>{if(statePicker.value!=='filled'&&forms.children.length){statePicker.value=state.value;$('paradigm-status').textContent=(globalThis.CorporiumI18n?.f("1b4de2d06da3da",()=>[])??'请先移除本行的形式，再更改填写状态。');return;}state.value=statePicker.value;lexemeDirty=true;renderQuick();};
      panel.querySelector('[data-pq-form]').onclick=()=>{realization(forms,{meanings:[{}]},uid);state.value='filled';const identity=forms.lastElementChild.dataset.id;lexemeDirty=true;renderQuick();focusRow(identity,'.paradigm-quick-form');};
      panel.querySelector('[data-pq-meaning]').onclick=()=>{if(item.f){const list=item.f.querySelector('.paradigm-meanings');meaning(list,{},uid);item.m=list.lastElementChild;}else ensure();const identity=item.m.dataset.id;lexemeDirty=true;renderQuick();focusRow(identity,'.paradigm-quick-label');};
      const remove=panel.querySelector('[data-pq-remove]');remove.disabled=!item.f;remove.onclick=()=>{if(item.m&&item.f.querySelector('.paradigm-meanings').children.length>1)item.m.remove();else item.f?.remove();if(!forms.children.length)state.value='unfilled';lexemeDirty=true;renderQuick();};
     };
    }
   }
  }
  if(!quickHost.children.length)quickHost.innerHTML=(globalThis.CorporiumI18n?.f("037b2ac6dd649a",()=>[])??'<p class="paradigm-quick-empty">选择模板后添加，直接填写词形和标签。Tab 移至下一格，Enter 移至下一行。</p>');
 }
 window.CorporiumParadigms={setQuick(value){quick=value;editor.classList.toggle('paradigm-quick',quick);editor.querySelector('h3').textContent=quick?(globalThis.CorporiumI18n?.f("87784113a305ce",()=>[])??'词形变化'):(globalThis.CorporiumI18n?.f("144309ad6ace7b",()=>[])??'变形表 · Paradigm');$('paradigm-tables').hidden=quick;quickHost.hidden=!quick;quickAdd.hidden=!quick;if(quick){quickAdd.append(addToolbar);quickAdd.open=!$('paradigm-tables').children.length;}else{quickHost.after(addToolbar);quickAdd.open=false;}$('paradigm-manage').textContent=quick?(globalThis.CorporiumI18n?.f("0ebb729643728a",()=>[])??'模板管理'):(globalThis.CorporiumI18n?.f("8d2562aee8e233",()=>[])??'管理本语言模板');$('paradigm-template').options[0].hidden=quick;if(quick){if(!$('paradigm-template').value&&templates().length)$('paradigm-template').value=templates()[0].id;renderQuick();}else{quickHost.replaceChildren();for(const row of $('paradigm-tables').querySelectorAll('.paradigm-row'))row.refreshParadigmSummary?.();}}};
 const originalOpen=openLexemeEditor;openLexemeEditor=async function(...args){await originalOpen(...args);if(!$('lexeme-editor').open)return;detachedForms.clear();$('paradigm-status').textContent='';$('paradigm-tables').replaceChildren();for(const t of args[0]?.body.paradigms||[])addTable(t);templateChoices();};
 const originalRead=readMorphEntry;readMorphEntry=function(){flushPending();return {...originalRead(),paradigms:[...$('paradigm-tables').children].map(readTable)};};
 const prune=pruneNewLexemeRows;pruneNewLexemeRows=function(body,previous){const kept=new Set((body.paradigms||[]).map(t=>t.usage_id)),saved={...previous,usages:[...previous?.usages||[],...(body.usages||[]).filter(u=>kept.has(u.id))]};const result=prune(body,saved);validateParadigmForms(result);return result;};
 // Keep a detached draft until save, so a table can register its form automatically.
 const addForm=addVariant;addVariant=function(...args){
  addForm(...args);const row=$('lexeme-variants').lastElementChild,remove=row.querySelector('.remove-variant'),original=remove.onclick;
  remove.onclick=e=>{try{detachedForms.set(row.dataset.id,{...readMorphForm(row),id:row.dataset.id,form:row.querySelector('.variant-form').value,notes:row.querySelector('.variant-notes').value,tags:readTags(row.querySelector('.variant-tags'))});}catch{detachedForms.delete(row.dataset.id);}return original.call(remove,e);};
 };

 $('paradigm-add').onclick=()=>{const t=templates().find(t=>t.id===$('paradigm-template').value);if(quick&&!t){$('paradigm-status').textContent=(globalThis.CorporiumI18n?.f("6b29189acc1b7d",()=>[])??'请选择模板；可在“模板管理”中先定义栏目和行类别。');return;}addTable(t?paradigmFromTemplate(t):undefined);if(quick)quickAdd.open=false;lexemeDirty=true;};
 $('lexeme-language').addEventListener('change',templateChoices);
 $('lexeme-usages').addEventListener('corporium-before-sense-remove',event=>{
  const row=event.detail.row,sense={id:row.dataset.id,short_gloss:row.querySelector('.sense-short').value},updates=[];
  try{for(const box of editor.querySelectorAll('.paradigm-gloss-controls')){const before=box.control.read(),after=paradigmDetachSense(before,sense);if(before!==after)updates.push([box.control,after]);}}
  catch(error){event.preventDefault();$('lexeme-error').textContent=(globalThis.CorporiumI18n?.f("05b4df0dd69db7",()=>[error.message])??'请先调整依赖此义项的变形标注：'+error.message);return;}
  for(const [control,value] of updates)control.set(value);
  for(const select of editor.querySelectorAll('.paradigm-default-base'))if(select.value===sense.id)select.value='';
  if(updates.length){$('paradigm-status').textContent=(globalThis.CorporiumI18n?.f("5c783e8feb04db",()=>[])??'已移除基本义项引用；相关变形保留当前完整标注，改为独立标注。');if(quick)renderQuick();}
 });
 $('lexeme-usages').addEventListener('corporium-before-usage-remove',event=>{
  if([...editor.querySelectorAll('.paradigm-usage')].some(s=>s.value===event.detail.row.dataset.id)){event.preventDefault();$('lexeme-error').textContent=(globalThis.CorporiumI18n?.f("7d86ca7d367c29",()=>[])??'此词类仍有变形表，请先调整表格所属词类或移除表格，再删除词类用法。');}
 });
 $('lexeme-usages').addEventListener('input',()=>{for(const select of editor.querySelectorAll('.paradigm-usage'))select.onfocus?.();for(const select of editor.querySelectorAll((globalThis.CorporiumI18n?.f("d6eeea71e81140",()=>[])??'[aria-label="新形式默认继承义项"]')))select.onfocus?.();for(const box of editor.querySelectorAll('.paradigm-gloss-controls'))box.control.refresh();for(const row of quickHost.querySelectorAll('.paradigm-quick-row'))row.refreshQuickGloss?.();});
 // The shared association dialog covers both text sentences and independent ones.
 const originalChoose=chooseLinkLexeme;chooseLinkLexeme=async function(){await originalChoose();chooseLinkUsage();};$('link-lexeme').onchange=linkSafe(chooseLinkLexeme);
 const originalShow=showMorphLinkForm;showMorphLinkForm=function(){originalShow();chooseLinkUsage();};$('link-form').onchange=showMorphLinkForm;
 // Templates can also be managed without opening an entry. Rows use | to separate categories.
 makeDialog('paradigm-template-manager',(globalThis.CorporiumI18n?.f("242d4f9d98810b",()=>[])??'<h2>变形表模板</h2><p>模板保存栏目、行类别与预设附加标签；修改或删除模板不改变词条中已加入的表格。</p><label>语言<select id="paradigm-template-language"></select></label><label>模板<select id="paradigm-template-choice"></select></label><form id="paradigm-template-form"><label>名称<input id="paradigm-template-title" required></label><label>栏目（用 | 分开）<input id="paradigm-template-dimensions" placeholder="数 | 格"></label><label>每行的类别（每行一组，用 | 分开）<textarea id="paradigm-template-rows" rows="8" placeholder="单数 | 主格&#10;单数 | 属格&#10;复数 | 主格"></textarea></label><p id="paradigm-template-error" role="alert"></p><button type="submit" class="primary">保存模板</button><button type="button" id="paradigm-template-delete">删除模板</button></form>'));
 let templateLanguage=null,templateDirty=false,templateBusy=false,templateChoice='',templateRows=[],templateTags=[];
 const presetHost=document.createElement('div');presetHost.id='paradigm-template-presets';$('paradigm-template-rows').parentElement.after(presetHost);
 function templatePresets(){
  const old=new Map();for(const row of templateRows){const key=JSON.stringify(row.labels);if(!old.has(key))old.set(key,[]);old.get(key).push(row);}
  templateRows=$('paradigm-template-rows').value.split('\n').filter(v=>v.trim()).map(v=>{const labels=v.split('|').map(v=>v.trim()),prior=old.get(JSON.stringify(labels))?.shift();return {id:prior?.id||id(),labels,state:'unfilled',gloss_addition:prior?.gloss_addition||''};});
  presetHost.innerHTML=templateRows.length?(globalThis.CorporiumI18n?.f("b1ecc274d1e5c8",()=>[])??'<small>每行预设附加标签（可留空；加入词条后独立保存）</small>'):'';
  for(const row of templateRows){const item=document.createElement('div');item.className='paradigm-template-preset';item.innerHTML=(globalThis.CorporiumI18n?.f("6b428b1fe50634",()=>[esc(row.labels.join(' · '))])??'<span>'+esc(row.labels.join(' · '))+'</span><input aria-label="模板预设附加标签" placeholder="如 NOM"><select aria-label="选择已有语法标签"></select>');presetHost.append(item);const input=item.querySelector('input'),select=item.querySelector('select');input.value=row.gloss_addition;input.oninput=()=>{row.gloss_addition=input.value;templateDirty=true;};tagSelect(select,templateTags);select.onchange=()=>{if(select.value){input.value=[input.value,select.value].filter(Boolean).join('.');row.gloss_addition=input.value;select.value='';templateDirty=true;}};}
 }
 $('paradigm-template-rows').addEventListener('input',templatePresets);
 function fillTemplate(){templateDirty=false;templateChoice=$('paradigm-template-choice').value;const t=(JSON.parse(templateLanguage?.metadata||'{}').paradigm_templates||[]).find(t=>t.id===$('paradigm-template-choice').value);$('paradigm-template-title').value=t?.title||'';$('paradigm-template-dimensions').value=t?.dimensions.join(' | ')||(globalThis.CorporiumI18n?.f("1402a953dca9c7",()=>[])??'数 | 格');$('paradigm-template-rows').value=t?.rows.map(r=>r.labels.join(' | ')).join('\n')||'';templateRows=structuredClone(t?.rows||[]);templatePresets();$('paradigm-template-delete').disabled=!t;$('paradigm-template-error').textContent='';}
 async function loadTemplateManager(){await loadLanguages();templateLanguage=languageList.find(l=>l.id===$('paradigm-template-language').value);templateTags=await api('grammar-tags?language='+encodeURIComponent(templateLanguage.id));$('paradigm-template-choice').innerHTML=(globalThis.CorporiumI18n?.f("df992523958582",()=>[(JSON.parse(templateLanguage.metadata).paradigm_templates||[]).map(t=>`<option value="${esc(t.id)}">${esc(t.title)}</option>`).join('')])??'<option value="">＋ 新建模板</option>'+(JSON.parse(templateLanguage.metadata).paradigm_templates||[]).map(t=>`<option value="${esc(t.id)}">${esc(t.title)}</option>`).join(''));fillTemplate();}
 async function openTemplates(lid){$('paradigm-template-language').innerHTML=languageOptions();$('paradigm-template-language').value=lid==='all'?'ordos':lid;$('paradigm-template-manager').showModal();try{await loadTemplateManager();}catch(e){$('paradigm-template-error').textContent=e.message;}}
 $('paradigm-manage').onclick=()=>openTemplates($('lexeme-language').value);
 const manage=document.createElement('button');manage.id='paradigm-template-open';manage.textContent=(globalThis.CorporiumI18n?.f("2dbaee5d990bd6",()=>[])??'变形表模板');manage.onclick=()=>{$('management-dialog').close();openTemplates(activeLanguage);};$('management-entries').append(manage);
 $('paradigm-template-language').onchange=async()=>{if(templateBusy)return;if(templateDirty&&!await corporiumConfirm((globalThis.CorporiumI18n?.f("eb9954c232d9a1",()=>[])??'放弃尚未保存的模板修改？'))){$('paradigm-template-language').value=templateLanguage.id;return;}await loadTemplateManager();};$('paradigm-template-choice').onchange=async()=>{if(templateBusy)return;if(templateDirty&&!await corporiumConfirm((globalThis.CorporiumI18n?.f("4ba25d4a74a5fe",()=>[])??'放弃尚未保存的模板修改？'))){$('paradigm-template-choice').value=templateChoice;return;}fillTemplate();};
 $('paradigm-template-form').addEventListener('input',()=>templateDirty=true);
 const templateDialog=$('paradigm-template-manager');templateDialog.addEventListener('cancel',e=>{if(templateBusy)e.preventDefault();else guardDialogDiscard(e,templateDirty,(globalThis.CorporiumI18n?.f("16450a13021e40",()=>[])??'放弃尚未保存的模板修改？'));});
 templateDialog.querySelector('form[method="dialog"]').addEventListener('submit',e=>{if(templateBusy)e.preventDefault();else guardDialogDiscard(e,templateDirty,(globalThis.CorporiumI18n?.f("7186c3492fa4d4",()=>[])??'放弃尚未保存的模板修改？'));});
 window.addEventListener('beforeunload',e=>{if(templateDialog.open&&templateDirty){e.preventDefault();e.returnValue='';}});
 async function saveTemplates(values,selected=''){templateBusy=true;$('paradigm-template-language').disabled=$('paradigm-template-choice').disabled=true;try{const l=templateLanguage;await api('save-language',{id:l.id,revision:l.revision,name:l.name,metadata:{...JSON.parse(l.metadata),paradigm_templates:values},_language:l.id});await loadTemplateManager();$('paradigm-template-choice').value=selected;fillTemplate();templateChoices();}finally{templateBusy=false;$('paradigm-template-language').disabled=$('paradigm-template-choice').disabled=false;}}
 $('paradigm-template-form').onsubmit=async e=>{e.preventDefault();const button=e.submitter;button.disabled=true;try{const dims=$('paradigm-template-dimensions').value.split('|').map(v=>v.trim()),tid=$('paradigm-template-choice').value||id(),value={id:tid,title:$('paradigm-template-title').value,dimensions:dims,rows:templateRows.map(r=>({...r,gloss_addition:paradigmAddition(r.gloss_addition)}))},values=JSON.parse(templateLanguage.metadata).paradigm_templates||[];await saveTemplates([...values.filter(t=>t.id!==tid),value],tid);}catch(e){$('paradigm-template-error').textContent=e.message;}finally{button.disabled=false;}};
 $('paradigm-template-delete').onclick=async()=>{const button=$('paradigm-template-delete');button.disabled=true;try{await saveTemplates((JSON.parse(templateLanguage.metadata).paradigm_templates||[]).filter(t=>t.id!==$('paradigm-template-choice').value));}catch(e){$('paradigm-template-error').textContent=e.message;button.disabled=false;}};
})();
