let homeVisible=false,homeData=null,homeIndex=0,homeTimer=null,homeRemaining=10000,homeStartedAt=null,homeAudioPlaying=false,homeAudioHolder=null,homePaused=false,homeHovered=false,homeFocused=false,homeInitialized=false,homeRestoring=false,homeFetch=0;
const home=document.createElement('section');home.id='homepage';home.hidden=true;
home.innerHTML=(globalThis.CorporiumI18n?.f("cf30846c1a0fae",()=>[])??'<div class="home-shell"><div class="home-heading"><div class="home-ornament" aria-hidden="true">✧</div><h1>Corporium</h1><div id="home-stats" class="home-stats" aria-label="全部语言统计"></div></div><section class="home-example" id="home-example"><div id="home-example-language"></div><div id="home-example-body"><button id="home-example-open" class="home-example-link" aria-label="查看例句来源"><span id="home-example-original"></span><span id="home-example-translation"></span></button></div><div id="home-example-source"></div><div class="home-example-footer"><div class="home-example-tools"><button id="home-pause" aria-pressed="false">暂停轮换</button><button id="home-next">换一句</button></div><div id="home-example-audio"></div></div></section><div id="home-empty" hidden><p>暂无可展示的例句。</p><button id="home-add-language">添加语言</button><button id="home-import">导入文本</button></div><div class="home-bottom"><button id="home-enter" class="home-enter" disabled>进入 <span class="home-wordmark">Corporium</span> <span class="home-enter-arrow" aria-hidden="true">→</span></button><label class="home-skip"><input type="checkbox" id="home-skip"> 下次直接进入工作区</label><p id="home-error" role="status"></p></div></div>');
document.body.append(home);
// Measure rendered text, including the language's font, rather than estimating by character count.
let homeFitFrame=null;
function fitHomeExample(){
  if(!homeVisible||$('home-example').hidden)return;
  const box=$('home-example-body'),content=$('home-example-open');
  if(!box.clientWidth||!box.clientHeight)return;
  const fits=scale=>{content.style.setProperty('--home-example-scale',scale);return content.getBoundingClientRect().height<=box.clientHeight-2&&content.scrollWidth<=box.clientWidth;};
  if(fits(1))return;
  let low=0,high=1;
  for(let i=0;i<14;i++){const mid=(low+high)/2;if(fits(mid))low=mid;else high=mid;}
  fits(low);
}
function scheduleHomeFit(){if(homeFitFrame!==null)return;homeFitFrame=requestAnimationFrame(()=>{homeFitFrame=null;fitHomeExample();});}
new ResizeObserver(scheduleHomeFit).observe($('home-example-body'));
new MutationObserver(scheduleHomeFit).observe(document.documentElement,{attributes:true,attributeFilter:['style','class','data-theme']});
window.addEventListener('resize',scheduleHomeFit);
document.fonts.ready.then(scheduleHomeFit);document.fonts.addEventListener('loadingdone',scheduleHomeFit);
function saveHomePlace(){if(!homeInitialized||homeRestoring)return;try{localStorage.setItem(projectStorageKey('corporium-last-place'),JSON.stringify({language:activeLanguage,workspace,text:selected,lexeme:dictionarySelection}));}catch{}}
const homeSetWorkspace=setWorkspace;setWorkspace=async function(name){await homeSetWorkspace(name);saveHomePlace();};
const homeSelectText=selectText;selectText=async function(id,...options){await homeSelectText(id,...options);saveHomePlace();};
const homeShowLexeme=showLexeme;showLexeme=async function(id,p=1){await homeShowLexeme(id,p);saveHomePlace();};
const homeRenderLanguage=renderLanguage;renderLanguage=function(){homeRenderLanguage();if(homeVisible)document.title='Corporium';};
function stopHomeTimer(){
  if(homeStartedAt!==null)homeRemaining=Math.max(0,homeRemaining-(performance.now()-homeStartedAt));
  clearTimeout(homeTimer);homeTimer=null;homeStartedAt=null;
}
function nextHomeExample(){if(!homeData?.samples.length)return;if(homeIndex+1>=homeData.samples.length){showHome();return;}homeIndex++;drawHomeExample();scheduleHome();}
function scheduleHome(){
  stopHomeTimer();
  if(!homeVisible||homePaused||homeHovered||homeFocused||homeAudioPlaying||document.hidden||(homeData?.samples.length||0)<2)return;
  homeStartedAt=performance.now();
  homeTimer=setTimeout(()=>{homeTimer=null;homeStartedAt=null;homeRemaining=0;nextHomeExample();},homeRemaining);
}
function homeAudioState(event){
  const {holder,active}=event.detail||{};
  if(active&&$('home-example-audio').contains(holder)){homeAudioHolder=holder;homeAudioPlaying=true;}
  else if(!active&&holder&&holder===homeAudioHolder){homeAudioHolder=null;homeAudioPlaying=false;}
  else return;
  scheduleHome();
}
document.addEventListener('corporium-sentence-audio-state',homeAudioState);
function drawHomeExample(){
  const e=homeData?.samples[homeIndex];$('home-example').hidden=!e;$('home-empty').hidden=!!e;
  stopHomeTimer();homeAudioHolder=null;homeAudioPlaying=false;
  window.stopSentenceAudio?.();homeRemaining=10000;
  if(!e)return;
  $('home-example-language').textContent=e.language_name;$('home-example-language').title=e.language_name;
  $('home-example-audio').innerHTML=sentenceAudioMarkup((e.kind==='independent'?'independent:':'')+e.id,{compact:true});
  const original=$('home-example-original');original.textContent=e.ipa||e.original;original.classList.toggle('home-ipa',!!e.ipa);
  applyLanguageTypography($('home-example'),JSON.parse(languageList.find(l=>l.id===e.language_id)?.metadata||'{}'));
  const font=(e.ipa?e.ipa_font:e.annotation_font)||'Junicode';original.style.fontFamily=validFont(font)?(['serif','sans-serif'].includes(font)?font:`"${font}", serif`):'Junicode, serif';
  $('home-example-translation').textContent=e.translation;
  $('home-example-source').textContent=(e.kind==='corpus'?(globalThis.CorporiumI18n?.f("3feffcaac44b55",()=>[e.source,e.position])??'语料引用 · '+e.source+' · 第 '+e.position+' 句'):(globalThis.CorporiumI18n?.f("11b273517bae20",()=>[e.source])??'独立例句 · '+e.source));
  $('home-example-source').title=$('home-example-source').textContent;
  $('home-next').disabled=homeData.samples.length<2;$('home-pause').disabled=homeData.samples.length<2;
  scheduleHomeFit();
  if(!matchMedia('(prefers-reduced-motion: reduce)').matches)$('home-example-open').animate([{opacity:0},{opacity:1}],{duration:450});
}
async function showHome(){
  if(document.querySelector('dialog[open]'))return;
  if(infoDirty){$('notice').textContent=(globalThis.CorporiumI18n?.f("dd8b5d599fbdb1",()=>[])??'请先保存或取消正在编辑的文本信息，再返回首页。');return;}
  try{await window.corporiumFlushSurvey?.();window.corporiumLeaveSurvey?.();}catch(error){corporiumStatus(error.message);return;}
  const entering=!homeVisible;
  saveHomePlace();homeVisible=true;home.hidden=false;document.documentElement.dataset.home='true';document.title='Corporium';
  if(entering&&!matchMedia('(prefers-reduced-motion: reduce)').matches){
    home.querySelectorAll('.home-ornament,h1,.home-stats,.home-example,#home-empty,.home-enter,.home-skip').forEach((element,i)=>{
      element.getAnimations().forEach(animation=>animation.cancel());
      element.animate([{opacity:0,transform:'translateY(9px)'},{opacity:1,transform:'translateY(0)'}],{duration:480,delay:i*70,easing:'ease-out',fill:'backwards'});
    });
  }
  const seq=++homeFetch;$('home-error').textContent='';
  try{const data=await api('home');if(seq!==homeFetch||!homeVisible)return;homeData=data;homeIndex=0;
    const c=data.counts;$('home-stats').innerHTML=(globalThis.CorporiumI18n?.f("52342ffe7db4b8",()=>[c.texts.toLocaleString(),c.corpus_sentences,c.independent_sentences,c.sentences.toLocaleString(),c.lexemes.toLocaleString()])??`<span><b>${c.texts.toLocaleString()}</b> 文本</span><i>·</i><span title="文本句子 ${c.corpus_sentences} ＋ 独立例句 ${c.independent_sentences}"><b>${c.sentences.toLocaleString()}</b> 句</span><i>·</i><span title="词典词条数量"><b>${c.lexemes.toLocaleString()}</b> 词条</span>`);
    drawHomeExample();scheduleHome();
  }catch(e){$('home-error').textContent=(globalThis.CorporiumI18n?.f("f7e68ee74b08b6",()=>[e.message])??'首页数据暂时无法加载：'+e.message);}
}
async function enterHomeWorkspace(){await homeRestored;homeVisible=false;homeFetch++;stopHomeTimer();home.hidden=true;document.documentElement.dataset.home='false';renderLanguage();}
$('home-enter').onclick=()=>enterHomeWorkspace().catch(e=>$('home-error').textContent=e.message);
$('home-pause').onclick=()=>{homePaused=!homePaused;$('home-pause').textContent=homePaused?(globalThis.CorporiumI18n?.f("b5d198f0b1eccd",()=>[])??'继续轮换'):(globalThis.CorporiumI18n?.f("4c28bb89e5fdf4",()=>[])??'暂停轮换');$('home-pause').setAttribute('aria-pressed',String(homePaused));scheduleHome();};
$('home-next').onclick=nextHomeExample;
$('home-example').onmouseenter=()=>{homeHovered=true;scheduleHome();};$('home-example').onmouseleave=()=>{homeHovered=false;scheduleHome();};
$('home-example').onfocusin=()=>{homeFocused=true;scheduleHome();};$('home-example').onfocusout=e=>{if(!$('home-example').contains(e.relatedTarget)){homeFocused=false;scheduleHome();}};
document.addEventListener('visibilitychange',scheduleHome);
try{$('home-skip').checked=localStorage.getItem('corporium-skip-home')==='true';}catch{}
$('home-skip').onchange=()=>{try{localStorage.setItem('corporium-skip-home',String($('home-skip').checked));}catch{}};
$('brand-home').onclick=e=>{e.preventDefault();showHome();};
$('home-add-language').onclick=async()=>{await enterHomeWorkspace();$('add-language').click();};$('home-import').onclick=async()=>{await enterHomeWorkspace();$('import').click();};
$('home-example-open').onclick=async()=>{
  const e=homeData?.samples[homeIndex];if(!e)return;
  try{await enterHomeWorkspace();await switchLanguage(e.owner_language);
    if(e.kind==='corpus'){await setWorkspace('corpus');clearFilters();await loadTexts();window.CorporiumDialogue?.showOriginal(e.text_id);await selectText(e.text_id);page=Math.ceil(e.position/pageSize());await search();$('entry-'+e.id)?.scrollIntoView({block:'center'});}
    else{if(!e.lexeme_id){await window.CorporiumSurvey.openExample(e.id);return;}exampleSource='independent';await setWorkspace('dictionary');await showLexeme(e.lexeme_id);focusStandaloneExample(e.id);}
  }catch(error){$('notice').textContent=(globalThis.CorporiumI18n?.f("0f953080443689",()=>[error.message])??'例句可能已变化，请刷新后重试：'+error.message);}
};
async function restoreHomePlace(){
  await corpusReady;homeRestoring=true;
  try{let place;try{place=JSON.parse(localStorage.getItem(projectStorageKey('corporium-last-place'))||'null');}catch{}
    if(place&&(languageList.some(l=>l.id===place.language)||place.language==='all')){
      if(activeLanguage!==place.language)await switchLanguage(place.language);
      if(place.text&&texts.some(t=>t.id===place.text))await selectText(place.text);
      if(['survey','library','grammar','analysis','timeline'].includes(place.workspace)){await setWorkspace(place.workspace);}
      else if(place.workspace==='dictionary'){dictionarySelection=place.lexeme||null;await setWorkspace('dictionary');}
    }
  }finally{homeRestoring=false;homeInitialized=true;}
}
const homeRestored=restoreHomePlace().catch(e=>$('home-error').textContent=e.message);
homeRestored.then(()=>window.corporiumFontsReady).then(()=>document.fonts?.ready).finally(()=>{
 document.documentElement.dataset.appLoading='false';$('home-enter').disabled=false;
});
if(!$('home-skip').checked)showHome();else{document.documentElement.dataset.home='false';}
