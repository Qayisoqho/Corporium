/* The free gloss and optional tags are edited independently. */
function joinGlossAtoms(parts){let value='';for(const atom of parts)value+=(!value||/[0-9]$/.test(value)?'':'.')+atom;return value;}
function glossAtoms(value){const seen=new Set(value.split('.').map(p=>p.toLowerCase()));for(const part of value.split('.')){const person=part.match(/^([0-9]+)([A-Za-z][A-Za-z0-9_]*)$/);if(person){seen.add(person[1].toLowerCase());seen.add(person[2].toLowerCase());}}return seen;}
function senseGloss(s={},field='short_gloss'){
 const base=s[field]||'',extra=s.show_gloss_addition===false?'':s.gloss_addition||'';
 if(!extra)return base;
 const parts=base.trim()?base.trim().split('.'):[],seen=glossAtoms(base.trim());
 for(const atom of extra.split('.'))if(atom&&!seen.has(atom.toLowerCase())){parts.push(atom);seen.add(atom.toLowerCase());}
 return joinGlossAtoms(parts);
}
function readGlossAddition(host){
 if(host?.classList?.contains('sense-editor')&&!host.querySelector('.sense-addition-controls'))host=document.querySelector('[data-addition-for="'+host.dataset.id+'"]')||host;
 return {gloss_addition:host?.querySelector('.sense-gloss-addition')?.value||'',show_gloss_addition:host?.querySelector('.sense-show-addition')?.checked??true};
}
const senseAdditionBindings=new WeakMap();
function mountGlossAddition(input,s={},tags=[],onchange=()=>{}){
 senseAdditionBindings.get(input)?.();
 input.parentElement.parentElement.querySelector(':scope > .sense-addition-controls')?.remove();
 const box=document.createElement('div');box.className='sense-addition-controls';
 const t=v=>globalThis.CorporiumI18n?.phrase(v)??v;
 box.innerHTML=`<label>${esc(t('附加标签'))}<input class="sense-gloss-addition" value="${esc(s.gloss_addition||'')}" placeholder="${esc(t('点号分隔，如 LOC.PL'))}"></label><label>${esc(t('已登记的语法标签'))}<select class="sense-addition-picker"><option value="">${esc(t('选择标签以附加'))}</option>${tags.map(tag=>`<option value="${esc(tag.symbol)}">${esc(tag.symbol+(tag.description?' · '+tag.description:''))}</option>`).join('')}</select></label><label class="sense-addition-toggle"><input type="checkbox" class="sense-show-addition" ${s.show_gloss_addition===false?'':'checked'}>${esc(t('显示附加标签'))}</label><output class="sense-addition-preview"></output>`;
 input.closest('label').after(box);const extra=box.querySelector('input'),picker=box.querySelector('select'),show=box.querySelector('input[type=checkbox]');
 const refresh=()=>{box.querySelector('output').textContent='→ '+senseGloss({short_gloss:input.value,gloss_addition:extra.value,show_gloss_addition:show.checked});};
 picker.onchange=()=>{if(!picker.value)return;const parts=extra.value.split('.').map(p=>p.trim()).filter(Boolean);if(!parts.some(p=>p.toLowerCase()===picker.value.toLowerCase()))parts.push(picker.value);extra.value=parts.join('.');picker.value='';extra.dispatchEvent(new Event('input',{bubbles:true}));};
 box.addEventListener('input',()=>{refresh();onchange();});input.addEventListener('input',refresh);senseAdditionBindings.set(input,()=>{input.removeEventListener?.('input',refresh);box.remove();});refresh();return box;
}
