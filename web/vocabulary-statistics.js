/* Read-only vocabulary profiles share analysis runs, snapshots and source cards. */
(()=>{
'use strict';
const t=s=>globalThis.CorporiumI18n?.phrase(s)??s;
let state={id:null,view:'overview',order:'frequency',page:1,item:'',query:'',sourcePage:1};
const kinds={root:'词根',stem:'词干',affix:'词缀',clitic:'附着词',connector:'连接成分',multipart:'多部分语素',unspecified:'类型未定'};
const views={overview:'统计概况',forms:'词形频率',morphemes:'语素频率',roots:'词根频率',stems:'词干频率',affixes:'词缀频率',custom:'自定义条目统计'};
const panel=$('analysis-counts-panel');if(!panel)return;
panel.querySelector('summary').textContent=t('词次、词形与语素统计');
$('analysis-counts-run').textContent=t('运行统计');
panel.querySelector('.analysis-help').textContent=t('以词格计词次，完整词形去重。保留声调、附加符号和词素边界，仅统一 Unicode 等价写法。同一记录的多处引用只计一次；自然文本与诱导材料请按来源分别选择。');
const label=document.createElement('label'),checkbox=document.createElement('input');checkbox.type='checkbox';checkbox.id='analysis-counts-case';checkbox.checked=true;
label.append(checkbox,document.createTextNode(' '+t('区分词形大小写')));$('analysis-counts-run').before(label);
function params(id,initial='overview'){if(state.id!==id)state={id,view:initial,order:'frequency',page:1,item:'',query:'',sourcePage:1};return {vocabulary_view:state.view,vocabulary_order:state.order,vocabulary_page:state.page,vocabulary_query:state.query||'',...(state.item?{vocabulary_item:state.item}:{})};}
function render(data,{reload,card,source}){
 if(!data.vocabulary)return false;
 const st=data.statistics,v=data.vocabulary;params(data.id);
 const host=$('analysis-results'),count=$('analysis-result-count');
 const change=patch=>{Object.assign(state,{page:1,item:''},patch);return reload();};
 $('analysis-summary').innerHTML=`<strong>${st.words.toLocaleString()} <small>${t(v.view==='custom'?'范围词次':'总词次')}</small></strong><strong><button type="button" id="vocabulary-types" class="text-button">${st.types.toLocaleString()}</button> <small>${t(v.view==='custom'?'范围词形数':'不同词形数')}</small></strong><strong>${st.sentences.toLocaleString()} <small>${t(v.view==='custom'?'范围句数':'句子记录')}</small></strong>`;
 $('vocabulary-types').onclick=()=>change({view:'forms'});
 const nav=document.createElement('div');nav.className='analysis-result-tools';nav.setAttribute('role','group');nav.setAttribute('aria-label',t('词汇统计视图'));
 const shown=v.selection?{overview:views.overview,forms:views.forms,custom:views.custom}:Object.fromEntries(Object.entries(views).filter(([key])=>key!=='custom'));
 for(const [key,name] of Object.entries(shown)){const b=document.createElement('button');b.type='button';b.textContent=t(name);b.setAttribute('aria-pressed',String(v.view===key));b.onclick=()=>change({view:key});nav.append(b);}
 host.append(nav);
 const content=document.createElement('div');content.className='vocabulary-content';host.append(content);
 if(v.view==='overview'){
  count.textContent=t('不同词形总数按整个范围去重，不能把各篇的不同词形数直接相加。');
  const rows=st.rows||[],pages=Math.max(1,Math.ceil(rows.length/20));state.sourcePage=Math.max(1,Math.min(pages,state.sourcePage));
  content.innerHTML=`<div class="vocabulary-table"><table class="analysis-table"><thead><tr>${['来源','句数','词次','不同词形数','排除格数'].map(s=>'<th>'+t(s)+'</th>').join('')}</tr></thead><tbody>${rows.slice((state.sourcePage-1)*20,state.sourcePage*20).map(r=>`<tr><td>${esc(r.kind==='independent'?t('独立例句库'):r.title)}</td><td>${r.sentences}</td><td>${r.words}</td><td>${r.types}</td><td>${r.excluded}</td></tr>`).join('')}</tbody></table></div><p>${t('有有效语素关联的词次')}：${st.morpheme_words} / ${st.words} · ${t('有已确认词根的词次')}：${st.root_words} / ${st.words}</p>`;
  topPagination($('analysis-pagination'),state.sourcePage,pages,async p=>{state.sourcePage=p;await reload();});
  return true;
 }
 const tools=document.createElement('div');tools.className='analysis-result-tools';
 const order=document.createElement('select');order.setAttribute('aria-label',t('词频排序'));
 for(const [value,text] of [['frequency','按次数从多到少'],['form','按形式排序']]){const o=document.createElement('option');o.value=value;o.textContent=t(text);order.append(o);}order.value=v.order;order.onchange=()=>change({order:order.value});tools.append(order);content.append(tools);
 const query=document.createElement('input');query.value=state.query||'';query.placeholder=t('筛选词形、语素或释义');query.setAttribute('aria-label',t('筛选词频'));
 const find=document.createElement('button');find.type='button';find.textContent=t('筛选词频');find.onclick=()=>change({query:query.value});query.onkeydown=e=>{if(e.key==='Enter'){e.preventDefault();find.click();}};tools.append(query,find);
 const custom=v.view==='custom',selection=v.selection;
 const help=document.createElement('p');help.className='analysis-help';help.textContent=custom?t('只计入符合条目条件的有效关联；整词与相同单语素关联去重。占比以筛选后的关联出现次数为分母；同一条目属于多个组时可重复归组，各组不能直接相加。统计概况和词形频率仍展示整个语料范围。'):v.view==='forms'?t('完整词形分别计数；点击形式或次数查看原句。导出 JSON 包含本次全部词频和例证位置。'):t('仅计入当前有效关联的语素条目，按已指定类型筛选，不自动删除词缀。语素出现次数与涉及词次分别计算；同一词中的重复语素可出现多次，例句按词格展示。类型未定项保留在全部语素中。');content.append(help);
 const coverage=document.createElement('p');coverage.textContent=custom?[t(selection.target==='morpheme'?'语素条目':'词典词条'),t('分类标准')+'：'+(window.CorporiumVocabularyControls?.groupLabel(selection)||t(selection.label)),t('符合条件条目')+' '+selection.eligible_entries,t('语料中条目')+' '+selection.entries,t('涉及词次')+' '+selection.words+' / '+st.words].join(' · '):t('有有效语素关联的词次')+'：'+st.morpheme_words+' / '+st.words+' · '+t('有已确认词根的词次')+'：'+st.root_words+' / '+st.words;content.append(coverage);
 const body=document.createElement('div');body.className='vocabulary-table';content.append(body);
 if(v.selected){
  count.textContent=(v.selected.system_label?t(v.selected.form):v.selected.form)+' · '+t('出现次数')+' '+v.selected.count+' · '+t('涉及词次')+' '+v.selected.words;
  const back=document.createElement('button');back.type='button';back.textContent=t('返回词频表');back.onclick=()=>change({});tools.append(back);
  body.innerHTML=v.items.map((h,i)=>card(h,`<button type="button" data-vocabulary-source="${i}">${t('原句与前后文')}</button>`)).join('')||'<p>'+t('没有符合条件的例证。')+'</p>';
  body.querySelectorAll('[data-vocabulary-source]').forEach(b=>b.onclick=()=>source(v.items[+b.dataset.vocabularySource].record));
 }else{
  count.textContent=t(views[v.view])+' · '+v.total+' · '+t('出现次数')+' '+v.denominator;
  const morph=v.view!=='forms',head=custom?['分组／条目',...(selection.group_by==='entry'?['释义']:[]),'出现次数','占比','涉及词次','句数','文本数','不同词形数','条目数']:morph?['形式','释义','类型','出现次数','占比','涉及词次','句数','文本数','不同词形数']:['词形','出现次数','占比','句数','文本数'];
  body.innerHTML='<table class="analysis-table"><thead><tr>'+[t('语言'),...head.map(t)].map(s=>'<th>'+s+'</th>').join('')+'</tr></thead><tbody>'+v.rows.map((r,i)=>{
   const language=languageList.find(l=>l.id===r.language_id),style=languageTypography(JSON.parse(language?.metadata||'{}'));
   const form=`<button type="button" class="text-button" data-vocabulary-item="${i}"><span style="${esc(custom&&selection.group_by!=='entry'?'':style)}">${custom&&selection.group_by!=='entry'?esc(r.system_label?t(r.form):r.form):rich(r.form)}</span></button>`,frequency=`<button type="button" class="text-button" data-vocabulary-item="${i}">${r.count}</button>`,ratio=v.denominator?(r.count/v.denominator*100).toFixed(2)+'%':'0%';
   const cells=[esc(language?.name||r.language_id),form,...(custom&&selection.group_by==='entry'?[esc(r.gloss||'')]:[]),...(morph&&!custom?[esc(r.gloss||''),t(kinds[r.kind]||'类型未定')]:[]),frequency,ratio,...(morph?[r.words]:[]),r.sentences,r.texts,...(morph?[r.types]:[]),...(custom?[r.entries]:[])];
   return '<tr>'+cells.map(s=>'<td>'+s+'</td>').join('')+'</tr>';
  }).join('')+'</tbody></table>';
  body.querySelectorAll('[data-vocabulary-item]').forEach(b=>b.onclick=()=>change({item:v.rows[+b.dataset.vocabularyItem].key}));
 }
 topPagination($('analysis-pagination'),v.page,v.pages,async p=>{state.page=p;await reload();});
 return true;
}
window.CorporiumVocabulary={params,render,capture:()=>({...state}),restore:value=>{if(value)state={...value};}};
})();
