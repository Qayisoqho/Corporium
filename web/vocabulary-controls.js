/* Statistics use the same entry conditions as the dictionary sidebar. */
(()=>{
'use strict';
const t=s=>globalThis.CorporiumI18n?.phrase(s)??s;
const defaults=()=>({target:'morpheme',group_by:'entry',query:'',search:{}});
let root,controls,owner='',ticket=0,draft=defaults(),problem='';const labels=new Map();
const el=id=>document.getElementById('vocabulary-'+id);
const enums={entry_type:['尚未指定','词条','普通语素','词根','词干','词缀','附着成分','中缀','环缀','连接成分','其他多部分语素','多词表达'],affix_position:['尚未指定','前缀','后缀','中缀','环缀'],affix_function:['尚未指定','屈折','派生','屈折与派生']};
function decorate(){
 if(!root)return;
 for(const row of root.querySelectorAll('.dictionary-condition')){
  const field=row.querySelector('.dictionary-condition-field').value,op=row.querySelector('.dictionary-condition-op').value,input=row.querySelector('input');
  let select=row.querySelector('.vocabulary-enum');
  if(!enums[field]||['empty','present'].includes(op)){if(select)select.remove();input.hidden=false;continue;}
  if(!select){select=document.createElement('select');select.className='vocabulary-enum';select.setAttribute('aria-label',t('分类值'));input.before(select);}
  const values=[...enums[field]];if(input.value&&!values.includes(input.value))values.unshift(input.value);
  select.replaceChildren(new Option(t('请选择分类值'),''),...values.map(v=>new Option(t(v),v)));select.value=input.value;
  select.onchange=()=>{input.value=select.value;};input.hidden=true;
 }
}
function mount(){
 if(root)return;
 root=document.createElement('section');root.id='vocabulary-configuration';root.className='vocabulary-configuration';
 root.innerHTML=`<div class="vocabulary-choice-row"><label>${t('统计对象')}<select id="vocabulary-target"><option value="morpheme">${t('语素条目')}</option><option value="lexeme">${t('词典词条')}</option></select></label><label>${t('分类标准')}<select id="vocabulary-group"></select></label></div><details id="vocabulary-filter"><summary>${t('筛选要统计的条目')}</summary><label>${t('条目包含内容')}<input id="vocabulary-query" aria-label="${t('条目包含内容')}"></label><div id="vocabulary-conditions"></div></details><p class="analysis-help" id="vocabulary-condition-status"></p>`;
 document.getElementById('analysis-counts-run').before(root);
 el('target').onchange=()=>{draft={...defaults(),target:el('target').value};configure(activeLanguage).catch(show);};
 el('conditions').addEventListener('change',decorate);el('conditions').addEventListener('click',decorate);
}
function show(error){problem=error.message;el('condition-status').textContent=problem;}
function read(){return {target:el('target').value,group_by:el('group').value,query:el('query').value,search:controls.get()};}
async function configure(language){
 mount();const seq=++ticket,wanted=draft||read(),target=wanted.target,key=language+':'+target;
 problem='';el('condition-status').textContent=t('正在读取统计分类…');el('target').value=target;
 try{
  const catalog=await api('vocabulary-options?target='+encodeURIComponent(target));if(seq!==ticket||language!==activeLanguage)return;
  labels.set(key,new Map(catalog.groups.map(g=>[g.id,g.name])));
  const value=draft||read();draft=null;
  const cid=value.search?.class_id;if(cid&&cid!=='@unclassified'&&!catalog.classes.some(c=>c.id===cid))catalog.classes.push({id:cid,kind:'semantic',language_id:language,name:t('原分类已不存在，请重新选择')});
  const previousOpen=el('filter').open;
  controls=window.createDictionaryConditions(el('conditions'),{prefix:'vocabulary',catalog,kind:'lexeme',value:value.search,onclear:()=>{el('query').value='';}});
  el('group').replaceChildren(...catalog.groups.map(g=>new Option(g.id.startsWith('class:')||g.id==='entry'?t(g.name):t('字段')+' · '+g.name,g.id)));
  if(!catalog.groups.some(g=>g.id===value.group_by))el('group').add(new Option(t('原分类已不存在，请重新选择'),value.group_by));
  el('group').value=value.group_by;el('query').value=value.query||'';owner=key;
  el('filter').open=previousOpen||!!value.query||!!value.search?.class_id||!!value.search?.conditions?.length;
  el('condition-status').textContent=t('条件只筛选条目自身资料，例句不参与条目筛选。分类未填写的项另列；一个条目属于多个组时，各组次数可能重叠。');decorate();
  if(document.getElementById('analysis-counts-run').disabled)root.querySelectorAll('input,select,button').forEach(node=>node.disabled=true);
 }catch(error){if(seq===ticket)show(error);throw error;}
}
function fill(value){draft=structuredClone(value||defaults());if(root){el('target').value=draft.target;configure(activeLanguage).catch(()=>{});}}
window.CorporiumVocabularyControls={configure,fill,groupLabel(value){return labels.get(activeLanguage+':'+value.target)?.get(value.group_by)||t(value.label);},query(){if(draft)return structuredClone(draft);if(problem)throw Error(problem);if(!controls||owner!==activeLanguage+':'+el('target').value)throw Error(t('统计分类尚未读取完成'));return read();},updateDisabled(){controls?.updateDisabled();}};
})();
