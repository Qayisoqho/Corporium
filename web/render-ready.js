/* Small, revision-scoped reads shared by preparation and sentence decorators.
   No timers, persistent project data, or cached failures. */
class CorporiumViewBatch {
 static generation=0;
 static invalidate(){this.generation++;}
 constructor(read,{size=200,limit=600,identity=()=>JSON.stringify([typeof desktopProjectStamp==='string'?desktopProjectStamp:'',activeLanguage,window.corporiumWorkspaceRevision,CorporiumViewBatch.generation])}={}){this.read=read;this.size=size;this.limit=limit;this.identity=identity;this.owner=null;this.values=new Map();}
 clear(){this.values.clear();this.owner=null;}
 async get(ids){
  const owner=this.identity();if(owner!==this.owner){this.values.clear();this.owner=owner;}
  ids=[...new Set(ids.filter(id=>id&&!String(id).startsWith('new:')))];
  const missing=ids.filter(id=>!this.values.has(id)),requests=new Map();
  for(let i=0;i<missing.length;i+=this.size){
   const group=missing.slice(i,i+this.size),pending=Promise.resolve().then(()=>this.read(group));
   for(const id of group){const value=pending.then(data=>data[id]);this.values.set(id,value);requests.set(id,value);value.catch(()=>{if(this.values.get(id)===value)this.values.delete(id);});}
  }
  for(const id of ids)if(!requests.has(id))requests.set(id,this.values.get(id));
  while(this.values.size>this.limit)this.values.delete(this.values.keys().next().value);
  return Object.fromEntries(await Promise.all([...requests].map(async([id,value])=>[id,await value])));
 }
}
async function corporiumPrepareSentences(records=[]){
 const corpus=[],independent=[],languages=new Set();
 for(const r of records){if(!r)continue;if(r.language_id)languages.add(r.language_id);(r.kind==='independent'?independent:corpus).push(r.id);}
 await Promise.allSettled([
  window.corporiumPrepareFonts?.([...languages]),
  window.CorporiumSentenceAudio?.prepare([...corpus,...independent.map(id=>'independent:'+id)]),
  window.CollaboratorLinks?.prepare(corpus,independent),
  window.CorporiumObjectMedia?.prepare('independent',independent)
 ]);
}
function corporiumPrepareEvidence(corpus,independent){
 return corporiumPrepareSentences([
  ...(corpus?.items||[]).filter(e=>e.entry).map(e=>({kind:'corpus',id:e.entry_id,language_id:e.entry.language_id||e.text_language})),
  ...(independent?.items||[]).map(e=>({kind:'independent',id:e.id,language_id:e.language_id}))
 ]);
}
if(typeof module!=='undefined')module.exports={CorporiumViewBatch};

if(typeof window!=='undefined'){
window.corporiumInvalidateSentenceReads=()=>CorporiumViewBatch.invalidate();
// Start the selected language's faces while its data is being read. A face
// already loaded is free; missing/unavailable fonts retain the normal fallback.
window.corporiumPrepareFonts=async function(ids=[activeLanguage]){
 if(!document.fonts)return;
 await window.corporiumFontsReady;
 const specs=new Set(),add=(font,variant)=>{
  const v=variantStyle(variant),stack=font==='@global'?fontStackCSS(savedFontStack(typography)):rowFontCSS(font).replace(/var\(--global-font-stack,var\(--default-ui-font\)\)/g,fontStackCSS(savedFontStack(typography)));
  specs.add(`${v.style} ${v.weight} 16px ${stack}`);
 };
 add('@global',typography.uiVariant);add('@global','bold');
 for(const id of new Set(ids.length?ids:[activeLanguage])){
  const language=languageList.find(l=>l.id===id);if(!language)continue;
  const settings=languageTypographySettings(JSON.parse(language.metadata||'{}'));
  for(const [row,font] of [['ipa','ipa'],['morpheme','annotation'],['gloss','gloss'],['translation','translation']])add(settings[font+'_font'],settings[row+'_variant']);
 }
 await Promise.allSettled([...specs].map(spec=>document.fonts.load(spec,'Aaŋəɐʰː́ 中文')));
};
const prepareLanguageFonts=()=>{void window.corporiumPrepareFonts().catch(()=>{});};
void initialLanguageReady.then(prepareLanguageFonts);
window.addEventListener('corporium-fonts-changed',prepareLanguageFonts);
const renderLanguageBeforeFontPreparation=renderLanguage;
renderLanguage=function(...args){const result=renderLanguageBeforeFontPreparation(...args);prepareLanguageFonts();return result;};
}
