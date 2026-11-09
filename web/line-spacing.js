/* Per-definition outer spacing and optional multiline tier spacing. */
(()=>{
 'use strict';
 const fields=['space_before','space_after'];
 const valid=v=>typeof v==='number'&&Number.isFinite(v)&&v>=-300&&v<=300;
 const text=(zh,en)=>globalThis.CorporiumI18n?.ui(zh,en)??zh;
 const formFields=prefix=>prefix==='layer'?[...fields,'line_spacing']:fields;
 function internalStyle(def={}){return valid(def.line_spacing)?`line-height:${Math.max(0,1.35+def.line_spacing/100)};`:'';}
 // Block rows reserve space inside their own box: adjoining block margins can
 // collapse to the larger value and swallow small changes (including zero).
 function style(def={},mode='margin'){return fields.map((key,i)=>{const side=i?'bottom':'top';return valid(def?.[key])?(mode==='block'?`margin-${side}:0;padding-${side}:${Math.max(0,def[key])/100}em;${def[key]<0?`--line-${side}-tighten:${def[key]/100}em;`:''}`:`margin-${side}:${def[key]/100}em;`):'';}).join('')+internalStyle(def);}
 function blockAttrs(def={}){return 'data-line-block'+(valid(def?.space_before)?' data-line-before':'')+(valid(def?.space_after)?' data-line-after':'');}
 // Keep attached IPA tiers beside the reading text when media/actions wrap.
 // Move the existing nodes, retaining typography, controls and annotations.
 function readingLines(ipa){
  const layers=[];let next=ipa.nextElementSibling;
  while(next?.matches('.sentence-layer')){layers.push(next);next=next.nextElementSibling;}
  if(!layers.length)return ipa;
  const column=document.createElement('div');column.className='sentence-reading-lines';ipa.before(column);column.append(ipa,...layers);return column;
 }
 function applyInternal(node,def){if(valid(def.line_spacing))node.style.setProperty('line-height',String(Math.max(0,1.35+def.line_spacing/100)));else node.style.removeProperty('line-height');}
 function apply(node,def={}){const block=node.hasAttribute?.('data-line-block');fields.forEach((key,i)=>{const side=i?'bottom':'top',set=valid(def?.[key]);if(block){node.toggleAttribute(i?'data-line-after':'data-line-before',set);if(set){node.style.setProperty('margin-'+side,'0');node.style.setProperty('padding-'+side,`${Math.max(0,def[key])/100}em`);if(def[key]<0)node.style.setProperty('--line-'+side+'-tighten',`${def[key]/100}em`);else node.style.removeProperty('--line-'+side+'-tighten');}else{node.style.removeProperty('margin-'+side);node.style.removeProperty('padding-'+side);node.style.removeProperty('--line-'+side+'-tighten');}}else if(set)node.style.setProperty('margin-'+side,`${def[key]/100}em`);else node.style.removeProperty('margin-'+side);});if('line_spacing' in def||node.hasAttribute?.('data-line-layer')||node.id==='layer-spacing-sample'){applyInternal(node,def);for(const child of node.querySelectorAll?.(':scope > textarea')||[])applyInternal(child,def);}}
 function read(prefix){return Object.fromEntries(formFields(prefix).map(key=>{const s=document.getElementById(prefix+'-'+key).value.trim();return [key,s===''?null:Number(s)];}));}
 function preview(prefix){
  const sample=document.getElementById(prefix+'-spacing-sample');apply(sample,read(prefix));
  const font=document.getElementById(prefix+'-font')?.value;
  if(typeof rowFontCSS==='function'&&(font==='@global'||validFont(font)))sample.style.fontFamily=rowFontCSS(font)+',serif';
  if(prefix==='layer'){
   const size=Number(document.getElementById('layer-size').value)||100,variant=document.getElementById('layer-style').value;
   sample.style.fontSize=`calc(.9375rem * ${Math.max(50,Math.min(200,size))/100})`;
   sample.style.fontWeight=variant.includes('bold')?'700':'400';sample.style.fontStyle=variant.includes('italic')?'italic':'normal';sample.style.fontVariantCaps=variant==='small-caps'?'small-caps':'normal';
  }
 }
 function mount(prefix,form){
  const details=document.createElement('details');details.className='line-spacing-settings';details.id=prefix+'-spacing-settings';
  const summary=document.createElement('summary');summary.textContent=text('显示设置','Display settings');details.append(summary);
  const row=document.createElement('div');row.className='line-spacing-fields';
  fields.forEach((key,i)=>{const label=document.createElement('label');label.textContent=i?text('行后间距（%）','Space after (%)'):text('行前间距（%）','Space before (%)');const input=document.createElement('input');input.id=prefix+'-'+key;input.type='number';input.min='-300';input.max='300';input.step='any';input.placeholder=text('默认','Default');input.addEventListener('input',()=>preview(prefix));label.append(input);row.append(label);});
  if(prefix==='layer'){const label=document.createElement('label');label.textContent=text('内部行距（%）','Internal line spacing (%)');const input=document.createElement('input');input.id='layer-line_spacing';input.type='number';input.min='-300';input.max='300';input.step='any';input.placeholder=text('默认','Default');input.addEventListener('input',()=>preview(prefix));label.append(input);row.append(label);}
  const reset=document.createElement('button');reset.type='button';reset.textContent=text('恢复默认','Reset to default');reset.onclick=()=>{formFields(prefix).forEach(key=>document.getElementById(prefix+'-'+key).value='');preview(prefix);};row.append(reset);details.append(row);
  const help=document.createElement('small');help.className='compact-help';help.textContent=text('留空沿用默认间距；0 表示不留空，负值进一步收紧。100% 等于本行一个字号的高度。仅作用于此层或书写类型，不压缩字符本身。','Leave blank for default spacing; 0 removes the space; negative values tighten it further. 100% equals this line’s font size. Applies only to this tier or writing type and does not compress characters.');details.append(help);
  if(prefix==='layer'){const hint=document.createElement('small');hint.className='compact-help';hint.textContent=text('内部行距调整同一层的多行文字：正值拉开，负值收紧，0 为标准行高。百分比以本层字号为基准；留空沿用原显示。','Internal spacing adjusts lines within the same tier: positive values spread them apart, negative values tighten them, and 0 uses the standard line height. Percentages are relative to this tier’s font size; leave blank to keep the existing layout.');details.append(hint);}
  const box=document.createElement('div');box.className='line-spacing-preview';const sample=document.createElement('span');sample.id=prefix+'-spacing-sample';sample.textContent=prefix==='layer'?'a̋ŋɡə̃ · Aa\nŋa · Bb\ntə · Cc':'a̋ŋɡə̃ · Aa';sample.style.whiteSpace='pre-wrap';box.append(sample);details.append(box);
  form.querySelector('button[type=submit]').before(details);
  details.addEventListener('toggle',()=>preview(prefix));
  for(const id of [prefix+'-font',...(prefix==='layer'?['layer-style','layer-size']:[])])document.getElementById(id)?.addEventListener('change',()=>preview(prefix));
 }
 function fill(prefix,def){formFields(prefix).forEach(key=>document.getElementById(prefix+'-'+key).value=def?.[key]??'');document.getElementById(prefix+'-spacing-settings').open=false;preview(prefix);}
 function update(kind,rows){
  const defs=new Map(rows.map(r=>[r.id,r]));
  for(const node of document.querySelectorAll(`[data-line-${kind}]`)){const def=defs.get(node.getAttribute('data-line-'+kind));if(def){apply(node,def);if(kind==='writing'){for(const [property,value] of [['display','inline-block'],['vertical-align','baseline'],['max-width','100%']]){if(fields.some(key=>valid(def[key])))node.style.setProperty(property,value);else node.style.removeProperty(property);}}}}
  // Keep active annotation drafts and their definition revisions current without
  // replacing the user's words, annotation cells, selection or cursor.
  if(kind==='layer'&&typeof inlineDrafts!=='undefined')for(const draft of inlineDrafts.values())for(const layer of draft.layers||[]){const def=defs.get(layer.id);if(def)Object.assign(layer,def);}
 }
 const api={style,internalStyle,blockAttrs,readingLines,apply,mount,fill,read,update};
 globalThis.CorporiumLineSpacing=api;
 if(typeof module!=='undefined')module.exports=api;
})();
