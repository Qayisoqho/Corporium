// Empty is grammatical. Catalogs belong to languages; marks never enter IPA.
(()=>{
 const defaults=[{id:'ungrammatical',name:'不合语法',symbol:'*',enabled:true},{id:'questionable',name:'合法性存疑',symbol:'?',enabled:true}];
 const legal={id:'',name:'合法',symbol:'',description:'',enabled:true};
 function types(lid){return JSON.parse(languageList.find(l=>l.id===lid)?.metadata||'{}').grammaticality_types||defaults;}
 function item(body,lid){if(body.grammaticality_display)return body.grammaticality_display;return body.grammaticality?types(lid).find(r=>r.id===body.grammaticality)||{name:'类型已变化',symbol:'!',id:body.grammaticality}:legal;}
 function choices(lid,value=''){const rows=[legal,...types(lid)].filter(t=>t.enabled!==false||t.id===value);if(value&&!rows.some(t=>t.id===value))rows.push({id:value,name:'类型不属于此语言，请重新选择',symbol:'!'});return rows.map(t=>`<option value="${esc(t.id)}" ${t.id===value?'selected':''}>${esc(t.symbol?t.symbol+' · '+t.name:'合法（无符号）')}${t.enabled===false?'（已停用）':''}</option>`).join('');}
 function mark(body,lid,interactive=false){const r=item(body,lid),tag=interactive?'button':'span';return `<${tag} class="judgment-mark ${r.id?'':'is-legal'}" ${interactive?'type="button" data-judgment-edit':''} title="${esc(r.name+(r.description?'：'+r.description:''))}${interactive?' · 点击修改':''}" aria-label="${esc('合法性：'+r.name)}">${esc(r.symbol||'·')}</${tag}>`;}
 function editor(d){if(d.kind!=='independent')return '';return `<label class="judgment-inline">合法性<select data-inline-field="grammaticality" aria-label="本句合法性">${choices(d.language_id,d.body.grammaticality||'')}</select></label>`;}
 window.CorporiumGrammaticality={types,item,choices,mark,editor};
 const previousBody=renderBody;renderBody=function(body,kind='corpus'){
  if(kind!=='independent')return previousBody(body);
  const lid=body.language_id||body.text_language_id||current?.text_language_id||activeLanguage;
  let html=previousBody(body);html=html.replace('class="language-body"','class="language-body judgment-area"');
  if(!html.includes('judgment-area'))html='<div class="judgment-area">'+html+'</div>';
  // Keep the words container's child positions unchanged for dictionary linking.
  const anchor=body.ipa?'ipa':body.words?.length?'word':'translation';
  const pattern=new RegExp('(<div class="'+anchor+'(?: [^"\\n]*)?)("[^>]*>)');
  return html.replace(pattern,(_,a,b)=>a+' judgment-anchor'+b+mark(body,lid,true));
 };
 // New and existing inline drafts use the same compact selector.
 document.addEventListener('change',e=>{if(e.target.dataset.inlineField!=='grammaticality')return;const card=e.target.closest('.editable-example'),d=inlineDrafts.get(card?.dataset.exampleKey);if(d){d.body.grammaticality=e.target.value;d.dirty=true;}});
 // Only the independent example editor offers a sentence judgment.
 const label=document.createElement('label');label.className='judgment-editor-row';label.innerHTML='合法性<select id="standalone-grammaticality" aria-label="例句合法性"></select>';$('standalone-ipa').closest('label').before(label);
 const previousStandalone=openStandalone;openStandalone=async function(x,e){$('standalone-grammaticality').innerHTML=choices(x.language_id,e?.body?.grammaticality||'');return previousStandalone(x,e);};
 makeDialog('judgment-picker','<h2>本句合法性</h2><p><small>修改原句，所有引用处共同显示。语法调查的本处判断单独保留。</small></p><form id="judgment-picker-form"><select id="judgment-picker-value" aria-label="合法性"></select><button class="primary" type="submit">保存</button></form><p id="judgment-picker-error" role="alert"></p>');
 let picked=null,pickerBusy=false;
 document.addEventListener('click',safe(async e=>{const b=e.target.closest('[data-judgment-edit]');if(!b)return;const card=b.closest('.editable-example');if(!card||card.dataset.exampleKind!=='independent')return;
  if(inlineDrafts.has(inlineKey(card.dataset.exampleKind,card.dataset.exampleId)))throw Error('请在当前标注编辑中的合法性选项修改。');
  picked=await api('annotations?'+new URLSearchParams({kind:card.dataset.exampleKind,id:card.dataset.exampleId}));
  $('judgment-picker-value').innerHTML=choices(picked.language_id,picked.body.grammaticality||'');$('judgment-picker-error').textContent='';$('judgment-picker').showModal();
 }));
 $('judgment-picker-form').onsubmit=async e=>{e.preventDefault();if(pickerBusy)return;pickerBusy=true;const button=e.submitter;button.disabled=true;try{await api('grammaticality-save',{kind:picked.kind,id:picked.id,revision:picked.revision,grammaticality:$('judgment-picker-value').value,_language:picked.owner_language});$('judgment-picker').close();await window.corporiumRefreshVisibleWorkspace?.();}catch(e){$('judgment-picker-error').textContent=e.message;}finally{pickerBusy=false;button.disabled=false;}};
 $('judgment-picker').addEventListener('cancel',e=>{if(pickerBusy)e.preventDefault();});
 // Management catalog: one short row per type, advanced text in the edit form.
 const manage=document.createElement('button');manage.id='judgment-manage-open';manage.textContent='合法性类型';$('management-entries').append(manage);
 makeDialog('judgment-manager','<h2>合法性类型</h2><label>语言<select id="judgment-language"></select></label><p><small>仅用于独立例句。空值表示合法、不显示符号。停用保留已有记录；使用中的类型不能删除。</small></p><div id="judgment-type-list"></div><button id="judgment-type-new" type="button">＋ 添加类型</button><form id="judgment-type-form"><div class="judgment-type-fields"><label>名称<input id="judgment-type-name" required maxlength="80"></label><label>符号<input id="judgment-type-symbol" required maxlength="12"></label><label>顺序<input id="judgment-type-position" type="number" min="1" max="200" required></label><label><input id="judgment-type-enabled" type="checkbox" checked>启用</label></div><label>说明<input id="judgment-type-description" maxlength="2000"></label><button type="submit" class="primary">保存类型</button></form><p id="judgment-type-error" role="alert"></p>');
 let catalog=null,editing=null,typeBusy=false,managerRequest=0,typeDirty=false;
 function fillType(r=null){editing=r;for(const key of ['name','symbol','description'])$('judgment-type-'+key).value=r?.[key]||'';$('judgment-type-position').value=r?catalog.items.findIndex(t=>t.id===r.id)+1:(catalog?.items.length||2)+1;$('judgment-type-enabled').checked=r?.enabled!==false;typeDirty=false;}
 async function loadManager(){const seq=++managerRequest,lid=$('judgment-language').value;const data=await api('grammaticality-types?lexical_language='+encodeURIComponent(lid));if(seq!==managerRequest)return;catalog=data;if(!editing&&!typeDirty)fillType();
  $('judgment-type-list').innerHTML='<div class="judgment-type-row"><span>无符号</span><strong>合法</strong><small>默认</small></div>'+data.items.map((r,i)=>`<div class="judgment-type-row"><strong class="judgment-type-symbol">${esc(r.symbol)}</strong><span>${esc(r.name)}${r.enabled?'':' · 已停用'}</span><button type="button" data-type-edit="${i}">编辑</button><button type="button" data-type-delete="${i}">删除</button></div>`).join('');
  $('judgment-type-list').querySelectorAll('[data-type-edit]').forEach(b=>b.onclick=safe(async()=>{if(typeDirty&&!await corporiumConfirm('放弃尚未保存的类型修改？'))return;fillType(data.items[+b.dataset.typeEdit]);}));
  $('judgment-type-list').querySelectorAll('[data-type-delete]').forEach(b=>b.onclick=safe(async()=>{if(typeBusy)return;const r=data.items[+b.dataset.typeDelete];if(!await corporiumConfirm((typeDirty?'放弃未保存的修改，并删除':'删除')+'合法性类型「'+r.name+'」？可撤销；使用中的类型请停用。'))return;typeBusy=true;try{await api('grammaticality-type-delete',{id:r.id,revision:data.revision,confirmed:true,_language:lid});await loadManager();fillType();await window.corporiumRefreshVisibleWorkspace?.();}finally{typeBusy=false;}}));
 }
 manage.onclick=safe(async()=>{$('management-dialog').close();$('judgment-language').innerHTML=languageOptions();$('judgment-language').value=activeLanguage==='all'?languageList[0]?.id:activeLanguage;fillType();await loadManager();$('judgment-manager').showModal();});
 $('judgment-language').onchange=safe(async()=>{if(typeDirty&&!await corporiumConfirm('放弃尚未保存的类型修改？')){$('judgment-language').value=catalog.language_id;return;}fillType();await loadManager();});
 $('judgment-type-new').onclick=safe(async()=>{if(!typeDirty||await corporiumConfirm('放弃尚未保存的类型修改？'))fillType();});
 $('judgment-type-form').oninput=()=>typeDirty=true;
 function closeManager(e){if(typeBusy){e.preventDefault();return;}guardDialogDiscard(e,typeDirty,'放弃尚未保存的类型修改？');}
 $('judgment-manager').addEventListener('cancel',closeManager);
 $('judgment-manager').querySelector('form[method="dialog"]').addEventListener('submit',closeManager);
 window.addEventListener('beforeunload',e=>{if(typeDirty){e.preventDefault();e.returnValue='';}});
 $('judgment-type-form').onsubmit=async e=>{e.preventDefault();if(typeBusy)return;typeBusy=true;const controls=[...$('judgment-manager').querySelectorAll('input,select,button')];controls.forEach(n=>n.disabled=true);try{await api('grammaticality-type-save',{id:editing?.id,revision:catalog.revision,name:$('judgment-type-name').value,symbol:$('judgment-type-symbol').value,description:$('judgment-type-description').value,enabled:$('judgment-type-enabled').checked,position:Number($('judgment-type-position').value),_language:catalog.language_id});fillType();await loadManager();await window.corporiumRefreshVisibleWorkspace?.();}catch(e){$('judgment-type-error').textContent=e.message;}finally{typeBusy=false;controls.forEach(n=>n.disabled=false);}};
 // Text corpus has no judgment attribute or filter.
 const filterLabel=document.createElement('label');filterLabel.innerHTML='合法性<select id="library-grammaticality" aria-label="筛选合法性"></select>';$('library-mode').closest('label').after(filterLabel);$('library-grammaticality').onchange=()=>$('library-search').click();
 function filters(){const select=$('library-grammaticality'),old=select.value,lid=activeLanguage;select.innerHTML='<option value="">不限</option><option value="legal">合法（无符号）</option>'+languageList.filter(l=>lid==='all'||l.id===lid).map(l=>types(l.id).map(r=>`<option value="${esc(l.id+'/'+r.id)}">${esc(r.symbol+' · '+r.name+(lid==='all'?' · '+l.name:''))}</option>`).join('')).join('');if([...select.options].some(o=>o.value===old))select.value=old;}
 const previousLanguages=loadLanguages;loadLanguages=async function(){await previousLanguages();filters();};
 $('library-clear').addEventListener('click',()=>{$('library-grammaticality').value='';$('library-search').click();});
 void corpusReady.then(filters);
})();
