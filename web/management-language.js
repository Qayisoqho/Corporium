/* The settings center hosts the original editors, including their save handlers. */
function showSettingsEditor(id){
 const editor=$(id);
 if(window.CorporiumManagement?.owns(id))editor.show();
 else editor.showModal();
}

function runSettingsEditorAction(id,action){
 const management=window.CorporiumManagement;
 return management?.owns(id)?management.run(action):action();
}

document.addEventListener('DOMContentLoaded',()=>{
 const ui=(zh,en)=>globalThis.CorporiumI18n?.ui(zh,en)??zh;
 const management=$('management-dialog');
 const languagePage=$('management-language-page');
 const projectPage=$('management-project-page');
 const sharedEntries=$('management-entries');
 const pages=management.querySelector('.settings-pages');
 const closeButton=management.querySelector('.dialog-top .close');

 function element(tag,className='',text=''){
  const node=document.createElement(tag);
  node.className=className;
  node.textContent=text;
  return node;
 }

 function command(label,action){
  const button=element('button','',label);
  button.type='button';
  button.onclick=safe(action);
  return button;
 }

 const languageActions=element('div','management-language-actions ui-controls ui-controls--compact');
 const languageListView=element('div','management-language-list ui-list');
 const targetLabel=element('label','ui-label',ui('正在设置的语言','Language being configured'));
 const target=element('select');
 target.id='management-language-select';
 targetLabel.classList.add('management-language-target','ui-controls','ui-controls--compact');
 targetLabel.append(target);
 const languageTabs=element('nav','management-language-tabs ui-controls ui-controls--compact');
 languageTabs.setAttribute('aria-label',ui('语言设置分区','Language settings sections'));
 const languagePanel=element('div','management-editor-panel');
 const sharedPanel=element('div','management-editor-panel');
 const annotationEntries=element('div','management-annotation-entries');
 annotationEntries.setAttribute('role','list');
 languagePage.append(languageActions,targetLabel,languageListView,languageTabs,annotationEntries,languagePanel);
 projectPage.append(sharedPanel);
 for(const panel of [languagePanel,sharedPanel])panel.dataset.inlineMessage='';

 let currentPage='',languageId='',group='information',child='',sharedKind='';
 let editor=null,confirming=false,closeConfirmed=false,shortcut=null;
 const discardMessage=ui('放弃尚未保存的设置？','Discard unsaved settings?');
 const sectionLabels={
  information:ui('基本信息','Basic information'),
  input:ui('录入与显示','Entry and display'),
  annotation:ui('词典与标注','Lexicon and annotation'),
  sound:ui('音系与排序','Phonology and sorting')
 };

 function fieldsSnapshot(ids){
  const values=ids.flatMap(id=>Array.from($(id).elements)
   .filter(control=>control.matches('input,select,textarea')&&!['button','submit','reset'].includes(control.type))
   .map(control=>[control.value,control.checked]));
  return JSON.stringify(values);
 }

 const languageFieldsByGroup={
  information:['name',...languageFields.map(([key])=>key)].map(key=>$('language-'+key).closest('label')),
  display:[$('language-ipa-font').closest('.language-typography-grid')],
  annotation:[$('language-glossary').closest('label'),$('language-glossary').closest('label').nextElementSibling,
   ...checkFields.map(([key])=>$('language-'+key).closest('label'))],
  boundaries:[$('language-boundaries').closest('details')]
 };

 function hideField(state,node){
  if(!node)return;
  state.hiddenFields.set(node,node.hidden);
  node.hidden=true;
  node.classList.add('management-hidden-field');
 }

 function setLanguageFields(state,section){
  state.node.dataset.languageFields=section;
  for(const [key,nodes] of Object.entries(languageFieldsByGroup)){
   if(key!==section)for(const node of nodes)hideField(state,node);
  }
  if(section==='boundaries')$('language-boundaries').closest('details').open=true;
 }

 function releaseEditor(){
  if(!editor)return;
  const state=editor;
  editor=null;
  if(state.node.open)state.node.close();
  for(const message of state.node.querySelectorAll('[role="alert"],[id$="-error"]')){
   if(message.textContent)message.textContent='';
  }
  state.node.classList.remove('management-inline-editor');
  state.node.inert=false;
  state.node.removeAttribute('aria-busy');
  delete state.node.dataset.languageFields;
  for(const [node,wasHidden] of state.hiddenFields){
   node.hidden=wasHidden;
   node.classList.remove('management-hidden-field');
  }
  state.marker.replaceWith(state.node);
 }

 function dirty(){return !!editor?.read&&editor.baseline!==null&&editor.read()!==editor.baseline;}

 async function canLeave(){
  if(editor?.busy||confirming)return false;
  if(!dirty())return true;
  confirming=true;
  try{return await corporiumConfirm(discardMessage);}
  finally{confirming=false;}
 }

 function guardClose(event){
  if(closeConfirmed||!editor?.busy&&!dirty())return false;
  event.preventDefault();
  void canLeave().then(leave=>{
   if(!leave||!management.open)return;
   closeConfirmed=true;
   try{closeButton.click();}
   finally{closeConfirmed=false;}
  });
  return true;
 }

 async function run(action){
  const state=editor;
  if(state.busy)return;
  const focused=state.node.contains(document.activeElement)?document.activeElement:null;
  state.busy=true;
  state.node.inert=true;
  state.node.setAttribute('aria-busy','true');
  try{return await action();}
  finally{
   state.busy=false;
   if(editor===state){
    state.node.inert=false;
    state.node.removeAttribute('aria-busy');
    if(focused?.isConnected&&focused.getClientRects().length)focused.focus({preventScroll:true});
   }
  }
 }

 function clean(id){
  if(editor?.node.id===id&&editor.read)editor.baseline=editor.read();
 }

 function saved(id){
  clean(id);
  if(editor?.node.id===id)editor.status.textContent=ui('已保存。','Saved.');
 }

 async function mount(panel,spec){
  const node=$(spec.id);
  const marker=document.createComment('settings editor position');
  const status=element('p','ui-help management-editor-status',ui('正在读取设置…','Loading settings…'));
  status.setAttribute('role','status');
  const state={node,marker,status,hiddenFields:new Map(),baseline:null,busy:false,
   read:spec.read||(spec.forms?()=>fieldsSnapshot(spec.forms):null)};
  editor=state;
  node.before(marker);
  node.classList.add('management-inline-editor');
  if(spec.languageControl)hideField(state,$(spec.languageControl).closest('label'));
  if(spec.fields)setLanguageFields(state,spec.fields);
  panel.append(status,node);
  try{
   await run(spec.open);
   if(editor!==state)return;
   status.textContent='';
   if(spec.fields&&spec.fields!=='information')hideField(state,$('delete-language'));
   const title=node.querySelector('h2');
   if(spec.title)title.textContent=spec.title;
   if(!title.id)title.id=node.id+'-heading';
   node.setAttribute('aria-labelledby',title.id);
   title.tabIndex=-1;
   clean(node.id);
   if(management.open)title.focus({preventScroll:true});
  }catch(error){
   if(editor!==state)return;
   releaseEditor();
   status.textContent=error.message;
   status.setAttribute('role','alert');
  }
 }

 const languageEditor=(fields,title)=>({id:'language-dialog',fields,title,forms:['language-form'],
  open:()=>openLanguage(child==='new'?null:languageList.find(row=>row.id===languageId))});
 const childEditors={
  new:languageEditor('information',ui('新建语言','New language')),
  display:languageEditor('display',ui('语料行字体与字号','Corpus row fonts and sizes')),
  checks:languageEditor('annotation',ui('标注规则与缩写','Annotation rules and abbreviations')),
  boundaries:languageEditor('boundaries',ui('音系边界','Phonological boundaries')),
  writing:{id:'writing-manager',forms:['writing-form'],languageControl:'writing-language',open:()=>openWritingManager(languageId)},
  layers:{id:'layers-dialog',forms:['layer-form'],languageControl:'layers-language',open:()=>openLayerManager(languageId)},
  classes:{id:'classes-dialog',forms:['class-form','semantic-form'],languageControl:'class-language',open:()=>openClasses(languageId)},
  templates:{id:'paradigm-template-manager',forms:['paradigm-template-form'],languageControl:'paradigm-template-language',open:()=>window.CorporiumParadigms.openTemplates(languageId)},
  judgments:{id:'judgment-manager',forms:['judgment-type-form'],languageControl:'judgment-language',open:()=>window.CorporiumGrammaticality.openManager(languageId)},
  order:{id:'dictionary-order-manager',forms:['order-form'],open:()=>window.CorporiumDictionaryOrganization.openOrder(languageId)},
  import:{id:'language-exchange-import',open:()=>window.CorporiumLanguageExchange.openImport(),read:()=>JSON.stringify([$('exchange-file').value,$('exchange-name').value])},
  export:{id:'language-exchange-export',open:()=>window.CorporiumLanguageExchange.openExport(languageId)}
 };
 const groupEditors={
  information:languageEditor('information'),
  input:{id:'quick-edit-manager',forms:['quick-edit-settings-form'],languageControl:'quick-edit-language',open:()=>window.CorporiumQuickEdit.openSettings(languageId)},
  sound:{id:'hp-settings-dialog',open:()=>window.CorporiumHomophonePhonology.openSettings(languageId),read:()=>window.CorporiumHomophonePhonology.inventoryDraft()}
 };

 function updateLanguageHeader(){
  target.replaceChildren(new Option(ui('语言列表','Language list'),''),...languageList.map(row=>new Option(row.name,row.id)));
  target.value=languageId;
  targetLabel.hidden=!languageId;
  $('export-language').hidden=!languageId;
  languageTabs.hidden=!languageId;
  annotationEntries.hidden=!languageId||group!=='annotation'||!!child;
  for(const button of languageTabs.children){
   button.setAttribute('aria-current',String(button.dataset.languageSection===group));
  }
 }

 function drawLanguageList(){
  languageListView.hidden=!!languageId||!!child;
  if(languageListView.hidden)return;
  const rows=languageList.map(row=>{
   const button=command(row.name,()=>selectLanguage(row.id));
   button.classList.add('ui-list-item');
   button.dataset.managedLanguage=row.id;
   return button;
  });
  languageListView.replaceChildren(...rows);
  if(!rows.length)languageListView.append(element('p','ui-help',ui('项目还没有语言。可以新建语言或导入语言数据包。','This project has no languages. Create a language or import a language package.')));
 }

 function sectionCommands(panel,commands){
  const row=element('div','management-section-commands ui-controls ui-controls--compact');
  row.append(...commands);
  panel.append(row);
 }

 async function drawLanguage(){
  releaseEditor();
  languagePanel.replaceChildren();
  updateLanguageHeader();
  drawLanguageList();
  pages.scrollTop=0;
  if(child){
   const back=languageId?sectionLabels[group]:ui('语言列表','Language list');
   sectionCommands(languagePanel,[command('← '+back,()=>openChild(''))]);
   await mount(languagePanel,childEditors[child]);
  }else if(languageId&&group!=='annotation'){
   if(group==='input')sectionCommands(languagePanel,[command(childEditors.display.title,()=>openChild('display'))]);
   if(group==='sound')sectionCommands(languagePanel,[command(childEditors.boundaries.title,()=>openChild('boundaries')),
    command(ui('词条排序设置','Entry sorting'),()=>openChild('order'))]);
   await mount(languagePanel,groupEditors[group]);
  }else{
   languageListView.querySelector('button')?.focus({preventScroll:true});
  }
 }

 async function selectLanguage(id){
  if(id===languageId&&!child)return;
  if(!await canLeave()){target.value=languageId;return;}
  languageId=id;
  group='information';
  child='';
  await drawLanguage();
 }

 async function openChild(key){
  if(!await canLeave())return;
  child=key;
  await drawLanguage();
  if(!key&&languageId)languageTabs.querySelector('[aria-current="true"]')?.focus({preventScroll:true});
 }

 target.onchange=safe(()=>selectLanguage(target.value));
 for(const [key,label] of Object.entries(sectionLabels)){
  const button=command(label,async()=>{
   if(group===key&&!child&&(editor||key==='annotation'))return;
   if(!await canLeave())return;
   group=key;
   child='';
   await drawLanguage();
  });
  button.dataset.languageSection=key;
  languageTabs.append(button);
 }

 for(const [id,key,zh,en] of [
  ['add-language','new','新建语言','New language'],
  ['import-language-package','import','导入语言','Import language'],
  ['export-language','export','导出语言','Export language']
 ]){
  const button=$(id);
  button.classList.remove('language-icon');
  button.textContent=ui(zh,en);
  button.title=button.textContent;
  button.setAttribute('aria-label',button.textContent);
  button.onclick=safe(()=>openChild(key));
  languageActions.append(button);
 }

 const checks=command(childEditors.checks.title,()=>openChild('checks'));
 checks.id='management-annotation-rules';
 annotationEntries.append(checks);
 arrangeManagementEntries(annotationEntries,{
  [checks.id]:ui('标注缩写、语素边界核查及空缺提示。','Gloss abbreviations, morpheme boundary checks, and missing-field notices.')
 });
 for(const [buttonId,key] of [['writing-manager-open','writing'],['layers-open','layers'],['classes-open','classes'],
                             ['paradigm-template-open','templates'],['judgment-manage-open','judgments']]){
  const button=$(buttonId);
  annotationEntries.append(button.closest('.management-entry')||button);
  button.dataset.managementLanguageCommand='';
  button.onclick=safe(()=>management.open?openChild(key):openLanguagePage(key));
 }

 async function drawShared(){
  releaseEditor();
  sharedPanel.replaceChildren();
  sharedEntries.hidden=!!sharedKind;
  pages.scrollTop=0;
  if(!sharedKind)return;
  sectionCommands(sharedPanel,[command(ui('← 项目共用资料','← Shared project data'),async()=>{
   if(!await canLeave())return;
   const previous=sharedKind;
   sharedKind='';
   await drawShared();
   sharedEntries.querySelector(`[data-management-entry="${previous}"]`)?.focus({preventScroll:true});
  })]);
  await mount(sharedPanel,{id:'participants-dialog',forms:['participant-form'],open:()=>CorporiumPeople.open(sharedKind)});
 }

 for(const button of sharedEntries.querySelectorAll('[data-management-entry]')){
  button.onclick=safe(async()=>{
   if(!management.open)window.CorporiumSettingsCenter.openPage('project');
   sharedKind=button.dataset.managementEntry;
   await drawShared();
  });
 }

 function openLanguagePage(editorKey=''){
  shortcut={language:activeLanguage,editorKey};
  window.CorporiumSettingsCenter.openPage('language');
 }

 function showPage(id){
  if(id===currentPage&&!shortcut)return;
  releaseEditor();
  currentPage=id;
  if(id==='language'){
   const requested=shortcut?.language??activeLanguage;
   languageId=languageList.some(row=>row.id===requested)?requested:'';
   child=languageId?shortcut?.editorKey||'':'';
   group=child?'annotation':'information';
   shortcut=null;
   void drawLanguage();
  }
  if(id==='project'){
   sharedKind='';
   void drawShared();
  }
 }

 const shortcutButton=$('edit-language');
 const shortcutLabel=ui('语言设置…','Language settings…');
 shortcutButton.setAttribute('aria-label',shortcutLabel);
 shortcutButton.title=shortcutLabel;
 shortcutButton.setAttribute('role','menuitem');
 shortcutButton.setAttribute('aria-haspopup','dialog');
 shortcutButton.setAttribute('aria-controls',management.id);
 shortcutButton.tabIndex=-1;
 shortcutButton.onclick=()=>{
  closeBrandLanguageMenu(true);
  openLanguagePage();
 };

 management.addEventListener('keydown',event=>{
  if(event.key!=='Escape'||event.defaultPrevented||event.isComposing||!editor?.node.contains(event.target))return;
  event.preventDefault();
  closeButton.click();
 });
 management.addEventListener('close',()=>{
  if(management.open)return;
  releaseEditor();
  currentPage='';
  shortcut=null;
 });
 window.addEventListener('beforeunload',event=>{
  if(management.open&&(editor?.busy||dirty()))event.preventDefault();
 });

 window.CorporiumManagement={
  showPage,canLeave,guardClose,run,clean,saved,
  owns:id=>editor?.node.id===id,
  taskProgressHost:()=>management.open&&editor?.busy?editor.status.parentElement:null,
  async languageSaved(id){
   languageId=id;
   if(child==='new'){
    child='';
    await drawLanguage();
   }else updateLanguageHeader();
   saved('language-dialog');
  },
  async languageImported(id){
   languageId=id;
   group='information';
   child='';
   await drawLanguage();
   saved('language-dialog');
  }
 };
},{once:true});
