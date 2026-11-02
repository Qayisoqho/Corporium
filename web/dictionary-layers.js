/* Dictionary tiers contain projections, never user-editable annotation cells. */
function dictionaryLayerText(layer){
 const english=globalThis.CorporiumI18n?.locale==='en',labels=layer.entry_type_labels||{};
 return layer.derived?(layer.segments||[]).map((s,i)=>(i?' '+(s.boundary||'-')+' ':'')+(s.values.length?s.values.map(v=>labels[v]?.[english?1:0]??v).join(' / '):'—')).join(''):layer.value||'';
}
function renderDictionaryLayer(layer){
 const t=(zh,en)=>globalThis.CorporiumI18n?.ui(zh,en)??zh,english=globalThis.CorporiumI18n?.locale==='en',labels=layer.entry_type_labels||{};
 const reasons={unlinked:t('未关联词典','No dictionary link'),empty:t('词典中此字段未填写或不适用','The dictionary field is empty or not applicable'),stale:t('原有关联已变化，请核对词典关联','The original link has changed; review the dictionary link'),field_missing:t('所选词典字段已删除','The selected dictionary field has been deleted')};
 const segments=layer.segments?.length?layer.segments:[{values:[],refs:[],state:'unlinked'}];
 const content=segments.map((s,index)=>{
  const separator=index?'<span class="dictionary-layer-separator" aria-hidden="true"> '+esc(s.boundary||'-')+' </span>':'';
  if(!s.values.length)return separator+'<span title="'+esc(layer.name+' · '+(reasons[s.state]||reasons.empty))+'">—</span>';
  return separator+s.values.map(raw=>{
   const value=labels[raw]?.[english?1:0]??raw,refs=s.refs.filter(r=>!r.values||r.values.includes(raw)),sources=refs.map(r=>r.headword).join(' / '),title=layer.name+' · '+sources;
   const html=layer.dictionary_field==='short_gloss'&&typeof richGloss==='function'?richGloss(value,layer.language_id):rich(value);
   return refs.length?`<button type="button" class="dictionary-layer-value" data-layer-open="${esc(refs[0].id)}" title="${esc(title)}" aria-label="${esc(t('查看词典来源：','View dictionary source: ')+sources)}">${html}</button>`:html;
  }).join(' / ');
 }).join('');
 return `<span class="extra-layer dictionary-derived-layer" data-dictionary-layer="${esc(layer.id)}" data-dictionary-unit="${esc(layer.unit_id||'')}" data-line-layer="${esc(layer.id)}" aria-label="${esc(layer.name+' · '+t('来自词典，只读','From dictionary, read only'))}" style="${layerStyle(layer)}">${content}</span>`;
}
(()=>{
 if(typeof document==='undefined'){if(typeof module!=='undefined')module.exports={text:dictionaryLayerText};return;}
 const t=(zh,en)=>globalThis.CorporiumI18n?.ui(zh,en)??zh;
 let fields=[],sequence=0;
 const sourceLabel=document.createElement('label'),fieldLabel=document.createElement('label'),help=document.createElement('small');
 sourceLabel.textContent=t('内容来源','Content source');const source=document.createElement('select');source.id='layer-source';source.innerHTML=`<option value="manual">${t('手动填写','Manual annotation')}</option><option value="dictionary">${t('词典信息（只读）','Dictionary information (read only)')}</option>`;sourceLabel.append(source);
 fieldLabel.textContent=t('调用字段','Dictionary field');const field=document.createElement('select');field.id='layer-dictionary-field';fieldLabel.append(field);fieldLabel.hidden=true;
 help.className='compact-help dictionary-layer-help';help.textContent=t('按已确认的词格关联读取；在词典中修改后同步。书写形式跟随书写类型字体。','Reads confirmed word-cell links and updates after dictionary edits. Writings use their writing type’s font.');help.hidden=true;
 $('layer-anchor').closest('label').before(sourceLabel,fieldLabel,help);
 function controls(){const derived=source.value==='dictionary';fieldLabel.hidden=help.hidden=!derived;$('layer-anchor').disabled=derived;if(derived)$('layer-anchor').value='word';$('layer-font').disabled=derived&&field.value.startsWith('writing:');const definition=fields.find(f=>f.id===field.value);if(derived&&definition?.font)selectFont($('layer-font'),definition.font);}
 source.onchange=controls;field.onchange=controls;
 function options(selected=''){field.innerHTML='<option value="">'+esc(t('请选择字段','Choose a field'))+'</option>'+fields.map(f=>'<option value="'+esc(f.id)+'">'+esc(globalThis.CorporiumI18n?.locale==='en'?f.name_en:f.name)+'</option>').join('');if(selected&&!fields.some(f=>f.id===selected))field.insertAdjacentHTML('beforeend','<option value="'+esc(selected)+'">'+esc(t('字段已删除','Field removed'))+'</option>');field.value=selected;controls();}
 async function loadFields(lid){const data=await api('dictionary-layer-fields?lexical_language='+encodeURIComponent(lid));if($('layers-language').value!==lid)return;fields=data.fields;options(editingLayer?.dictionary_field||'');}
 const fill=fillLayer;fillLayer=function(def=null){fill(def);source.value=def?.source||'manual';options(def?.dictionary_field||'');};
 function annotationCell(d,w,l,values){if(l.source==='dictionary'){const derived=d.dictionary_layers?.[w.id]?.find(v=>v.id===l.id)||{...l,derived:true,segments:[],unit_id:w.id};return renderDictionaryLayer(derived);}return `<input data-unit="${esc(w.id)}" data-layer="${esc(l.id)}" data-line-layer="${esc(l.id)}" style="${layerStyle(l)}" aria-label="${esc(w.form+' · '+l.name)}" value="${esc(values.get(w.id+'|'+l.id)||'')}">`;}
 async function refresh(){
  const owners=new Map();
  for(const card of document.querySelectorAll('.editable-example')){const draft=typeof inlineDrafts==='undefined'?null:inlineDrafts.get(card.dataset.exampleKey);if(!card.getClientRects().length||!card.querySelector('[data-dictionary-layer]')&&!draft?.layers.some(l=>l.source==='dictionary'))continue;if(card.dataset.exampleId&&!card.dataset.exampleId.startsWith('new:'))owners.set(card.dataset.exampleKind+':'+card.dataset.exampleId,{kind:card.dataset.exampleKind,id:card.dataset.exampleId});}
  if(!owners.size)return;const ticket=++sequence;
  const requests=[...owners.values()],data={items:[]};
  for(let i=0;i<requests.length;i+=200){const batch=await api('dictionary-layer-values?owners='+encodeURIComponent(JSON.stringify(requests.slice(i,i+200))));if(ticket!==sequence)return;data.items.push(...batch.items);}
  for(const item of data.items){
   const selector=`.editable-example[data-example-kind="${CSS.escape(item.kind)}"][data-example-id="${CSS.escape(item.id)}"]`;
   for(const card of document.querySelectorAll(selector)){
    const draft=typeof inlineDrafts==='undefined'?null:inlineDrafts.get(card.dataset.exampleKey);
    if(draft){
     draft.dictionary_layers=item.values;draft.layers=item.layers||draft.layers;
     for(const [index,word] of draft.words.entries()){
      const saved=item.words.find(w=>w.id===word.id),root=card.querySelector('[data-inline-slot="'+CSS.escape(word.id)+'"]');if(!root)continue;
      if(saved&&draft.body.words[index].form!==saved.form)draft.dictionary_layers[word.id]=(item.values[word.id]||[]).map(l=>({...l,segments:[{values:[],refs:[],state:'stale'}]}));
      for(const def of draft.layers.filter(l=>(l.anchor||'word')==='word')){
       const old=root.querySelector('[data-line-layer="'+CSS.escape(def.id)+'"]');if(def.source!=='dictionary'&&!old?.hasAttribute('data-dictionary-layer'))continue;
       const template=document.createElement('template');template.innerHTML=inlineWordLayer(def,draft,index,new Map(draft.cells.map(c=>[c.unit_id+'|'+c.layer_id,c.value])));if(old)old.replaceWith(template.content.firstElementChild);else root.append(template.content.firstElementChild);
      }
      for(const old of root.querySelectorAll('[data-dictionary-layer]'))if(!draft.layers.some(l=>l.id===old.dataset.dictionaryLayer))old.remove();
     }
     continue;
    }
    const wordNodes=[...(card.querySelector('.words')?.children||[])].filter(n=>n.classList.contains('word'));
    item.words.forEach((unit,index)=>{const root=wordNodes[index];if(!root)return;const defs=item.values[unit.id]||[];
     for(const old of root.querySelectorAll('[data-dictionary-layer]'))if(!defs.some(l=>l.id===old.dataset.dictionaryLayer&&l.visible))old.remove();
     for(const def of defs){if(!def.visible)continue;const fresh=document.createElement('template');fresh.innerHTML=renderDictionaryLayer(def);const old=root.querySelector('[data-line-layer="'+CSS.escape(def.id)+'"]');if(old)old.replaceWith(fresh.content.firstElementChild);else root.append(fresh.content.firstElementChild);}
    });
   }
   window.CorporiumFormattedCopy?.updateDictionaryLayers?.(item);
  }
 }
 document.addEventListener('click',e=>{const button=e.target.closest('[data-layer-open]');if(!button)return;e.preventDefault();e.stopPropagation();dictSafe(()=>openDictionaryLexeme(button.dataset.layerOpen))();});
 function definitions(rows,lid){if(typeof inlineDrafts==='undefined')return;for(const draft of inlineDrafts.values())if(draft.language_id===lid)draft.layers=rows;}
 window.CorporiumDictionaryLayers={text:dictionaryLayerText,render:renderDictionaryLayer,loadFields,annotationCell,refresh,definitions};
})();
