/* The selected analysis supplies the shared morpheme table and basic headword. */
(() => {
  'use strict';
  const ui = (zh, en) => globalThis.CorporiumI18n?.ui(zh, en) ?? zh;
  const setting = document.createElement('section');
  setting.innerHTML = '<label class="ui-label"><input type="checkbox" id="language-chinese-mode"></label><p class="ui-help"></p>';
  setting.querySelector('label').append(document.createTextNode(ui('汉语模式：新词条默认按语素录入','Chinese mode: enter new headwords as morphemes')));
  setting.querySelector('p').textContent = ui('现有词条可在词形来源中选择分析或独立词形。','Existing entries can select an analysis or an independent headword in Headword source.');
  $('quick-edit-settings-form').prepend(setting);
  const editor = $('lexeme-editor');
  const form = $('lexeme-form');
  const headword = $('lexeme-headword');
  const host = (globalThis.CorporiumMultipart.get(headword) ||
    globalThis.CorporiumMultipart.mount(headword, {}, {title:ui('词形','Headword')})).host;
  const panel = document.createElement('section');
  panel.id = 'chinese-headword-editor';
  panel.innerHTML = '<div class="chinese-source-controls ui-controls ui-controls--compact"><div class="chinese-source-field"><label class="ui-label" for="chinese-form-source"></label><select id="chinese-form-source"></select></div><div class="chinese-source-field"><label class="ui-label" for="chinese-form-joiner"></label><input id="chinese-form-joiner" maxlength="32"></div></div><div id="chinese-morpheme-cells" class="chinese-table-host"></div><div class="chinese-form-actions ui-controls ui-controls--compact"><button type="button" id="chinese-component-details"></button></div>';
  host.append(panel);
  const choice = $('chinese-form-source');
  const joiner = $('chinese-form-joiner');
  const tableHost = $('chinese-morpheme-cells');
  const analysisList = $('ws-analyses');
  const actions = panel.querySelector('.chinese-form-actions');
  const detailsButton = actions.querySelector('button');
  actions.classList.remove('ui-controls--compact');
  panel.querySelector('[for="chinese-form-source"]').textContent = ui('词形来源', 'Headword source');
  panel.querySelector('[for="chinese-form-joiner"]').textContent = ui('连接文字', 'Join with');
  joiner.setAttribute('aria-label', ui('语素间的连接文字，留空直接拼合', 'Text between morphemes; blank joins directly'));
  let source = null;
  let frame = 0;
  let tableUpdate = false;
  let openSequence = 0;
  let entrySequence = 0;
  let opening = null;
  let detailsMode = false;
  let quickPreparing = false;
  let analysisHome = null;
  let settingsPending = null;
  let settingsReady = false;
  const hiddenAnalyses = new Map();
  const enabled = () => JSON.parse(languageList.find(l => l.id === $('lexeme-language').value)?.metadata || '{}').chinese_mode === true;
  const analyses = () => [...analysisList.children];
  const selected = () => analyses().find(a => a.dataset.id === source?.analysis_id);
  const quickOpen = () => !!$('lexeme-quick-editor')?.open;
  const tableActive = () => editor.open && !!source && !!selected() && !detailsMode && !quickPreparing && !quickOpen() && settingsReady;
  function hide(node, value) {
    if (node.hidden !== value) node.hidden = value;
  }
  function leaves() {
    const rows = [...(selected()?.querySelector('.ws-components').children || [])];
    const parents = new Set(rows.map(r => r.querySelector('.ws-parent').value).filter(Boolean));
    return rows.filter(r => !parents.has(r.dataset.id));
  }
  function updateHeadword() {
    if (headword.readOnly !== !!source) headword.readOnly = !!source;
    if (!source) return;
    source.joiner = joiner.value;
    const rows = leaves();
    if (selected() && rows.length && rows.every(r => wsVal(r,'form').trim())) {
      headword.value = rows.map(r => wsVal(r,'form')).join(source.joiner).trim();
    }
  }
  function restoreAnalyses() {
    for (const [analysis,hidden] of hiddenAnalyses) hide(analysis,hidden);
    hiddenAnalyses.clear();
  }
  function releaseTable() {
    if (!analysisHome) return;
    panel.append(actions);
    window.CorporiumQuickEdit.clear();
    restoreAnalyses();
    analysisHome.replaceWith(analysisList);
    analysisHome = null;
  }
  function showSelectedAnalysis() {
    for (const analysis of analyses()) {
      if (!hiddenAnalyses.has(analysis)) hiddenAnalyses.set(analysis,analysis.hidden);
      hide(analysis,analysis !== selected());
    }
  }
  function borrowTable() {
    if (!analysisHome) {
      const list = analysisList;
      analysisHome = document.createComment('full word-formation analyses');
      list.before(analysisHome);
      tableHost.append(list);
    }
    showSelectedAnalysis();
    window.CorporiumQuickEdit.refresh();
    const toolbar=selected()?.querySelector('.quick-analysis-tools');
    if (toolbar && actions.parentElement !== toolbar) toolbar.append(actions);
  }
  function ensureSettings() {
    if (settingsReady) return Promise.resolve();
    if (settingsPending) return settingsPending;
    const sequence = openSequence;
    const lid = $('lexeme-language').value;
    const pending = window.CorporiumQuickEdit.settings(lid).then(() => {
      if (sequence === openSequence && $('lexeme-language').value === lid && editor.open) {
        settingsReady = true;
        queue();
      }
    });
    settingsPending = pending;
    pending.then(() => {if(settingsPending === pending)settingsPending=null;},
      error => {if(settingsPending === pending){settingsPending=null;$('lexeme-error').textContent=error.message;}});
    return pending;
  }
  function placePanel() {
    const info = form.querySelector('.lx-formhead .lx-meta');
    const navigation = info?.querySelector('.lx-index');
    const place = info && !quickPreparing && !quickOpen() ? info : host;
    if (panel.parentElement !== place) {
      if (place === info) navigation.before(panel);
      else place.append(panel);
    }
  }
  function refresh(updateTable=true) {
    updateHeadword();
    if (!updateTable) return;
    placePanel();
    hide(panel,!enabled() && !source);
    const multipart = host.querySelector('.multipart-toggle');
    if (multipart) hide(multipart,!!source);
    if (panel.hidden || !source || !selected() || detailsMode || quickPreparing) {
      releaseTable();
      if (!source || !quickOpen()) restoreAnalyses();
    }
    if (panel.hidden) return;
    const choices = [new Option(ui('独立词形','Independent headword'),'')];
    for (const [index,analysis] of analyses().entries()) choices.push(new Option(wsVal(analysis,'title') || ui('分析 ','Analysis ') + (index+1),analysis.dataset.id));
    if (!analyses().length) choices.push(new Option(ui('由语素生成','Generate from morphemes'),'@new'));
    if (source && !selected()) choices.push(new Option(ui('来源分析已删除，请重新选择','Source analysis removed; choose another'),source.analysis_id));
    const key = JSON.stringify(choices.map(option => [option.value,option.textContent]));
    if (choice.dataset.options !== key) {choice.replaceChildren(...choices);choice.dataset.options=key;}
    choice.value = source?.analysis_id || '';
    hide(joiner,!source);
    hide(panel.querySelector('[for="chinese-form-joiner"]'),!source);
    hide(tableHost,!source || quickOpen() || detailsMode);
    hide(actions,!source || quickOpen());
    detailsButton.textContent = detailsMode ? ui('返回语素表格','Back to morpheme table') : ui('构词分析详情','Analysis details');
    if (!source || !selected() || detailsMode || quickPreparing) return;
    if (quickOpen()) {
      showSelectedAnalysis();
      window.CorporiumQuickEdit.refresh();
    } else if (settingsReady) borrowTable();
    else ensureSettings().catch(() => {});
  }
  function queue(updateTable=true) {
    tableUpdate ||= updateTable;
    if (!frame && editor.open) frame=requestAnimationFrame(() => {
      frame=0;
      const update=tableUpdate;
      tableUpdate=false;
      refresh(update);
    });
  }
  function createSource() {
    let row = analyses().find(a => a.querySelector('.ws-default').checked) || analyses()[0];
    if (!row) {
      wsAnalysis({default:true,title:ui('基本词形','Basic headword'),components:[{form:headword.value}]});
      row=analyses().at(-1);
    }
    source={analysis_id:row.dataset.id,joiner:''};
    joiner.value='';
  }
  choice.addEventListener('change', () => {
    if (choice.value && host.querySelector('.multipart-toggle input')?.checked) {
      choice.value=source?.analysis_id || '';
      $('lexeme-error').textContent=ui('请先在独立词形中关闭不连续多部分形式，再选择语素生成。','First turn off discontinuous parts in the independent headword, then select an analysis.');
      return;
    }
    if (choice.value === '@new') createSource();
    else source=choice.value ? {analysis_id:choice.value,joiner:joiner.value} : null;
    detailsMode=false;
    lexemeDirty=true;
    refresh();
    if (quickOpen()) window.CorporiumQuickEdit.refresh();
  });
  joiner.addEventListener('input', () => {updateHeadword();lexemeDirty=true;});
  detailsButton.addEventListener('click', () => {
    detailsMode=!detailsMode;
    if (detailsMode) {
      releaseTable();
      restoreAnalyses();
      form.querySelector('[data-lx-open="analysis"]')?.click();
    } else form.querySelector('[data-lx-close]')?.click();
    refresh();
  });
  form.addEventListener('click', event => {
    if (event.target.closest?.('[data-lx-open="analysis"],[data-lx-add="analysis"]')) {
      detailsMode=true;releaseTable();restoreAnalyses();queue();
    } else if (event.target.closest?.('[data-lx-close],[data-lx-index]')) {
      detailsMode=false;queue();
    } else if (event.target.closest?.('#ws-analyses button')) queue();
  },true);
  for (const type of ['input','change','ws-rows-change']) form.addEventListener(type, event => {
    if (event.target.closest?.('#ws-analyses')) queue(type !== 'input' || event.target.matches('[data-ws="title"]'));
  });
  $('lexeme-language').addEventListener('change', () => {
    settingsReady=false;settingsPending=null;
    if (!editingLexeme && enabled() && !source) createSource();
    if (!editingLexeme && !enabled()) source=null;
    queue();
  });
  editor.addEventListener('corporium-quick-edit', event => {
    const phase=event.detail.phase;
    if (phase === 'prepare') {
      quickPreparing=true;detailsMode=false;releaseTable();restoreAnalyses();placePanel();
    } else if (phase === 'opened' || phase === 'restored' || phase === 'settled') {
      quickPreparing=false;queue();
    }
  });
  editor.addEventListener('close', () => {releaseTable();restoreAnalyses();detailsMode=false;});
  for (const name of ['wsFill','wsSetRegistryRecord','wsReleaseRegistry']) {
    const original=name === 'wsFill' ? wsFill : name === 'wsSetRegistryRecord' ? wsSetRegistryRecord : wsReleaseRegistry;
    const wrapped=function(...args) {const value=original(...args);queue();return value;};
    if (name === 'wsFill') wsFill=wrapped;
    else if (name === 'wsSetRegistryRecord') wsSetRegistryRecord=wrapped;
    else wsReleaseRegistry=wrapped;
  }
  const originalAnalysis=wsAnalysis;
  wsAnalysis=function(...args) {const value=originalAnalysis(...args);queue();return value;};
  editor.addEventListener('corporium-lexeme-opened', event => {
    entrySequence++;
    releaseTable();restoreAnalyses();
    source=event.detail.entry?.body?.headword_source ? {...event.detail.entry.body.headword_source} : null;
    joiner.value=source?.joiner || '';
    settingsReady=false;settingsPending=null;detailsMode=false;
    hide(panel,true);
  });
  const originalOpen=openLexemeEditor;
  openLexemeEditor=async function(entry=null,...args) {
    const sequence=++openSequence,before=entrySequence;
    const pending=(async () => {
      await originalOpen(entry,...args);
      if (sequence !== openSequence || before === entrySequence || !editor.open || editingLexeme?.id !== entry?.id) return;
      if (!entry && enabled() && !source) createSource();
      if (source) await ensureSettings();
      if (sequence === openSequence && editor.open) refresh();
    })();
    opening=pending;
    try {return await pending;}
    finally {if(opening === pending)opening=null;}
  };
  const originalRead=readMorphEntry;
  readMorphEntry=function() {
    updateHeadword();
    const body=originalRead();
    if (source) body.headword_source={...source};
    else if (Object.hasOwn(editingLexeme?.body || {},'headword_source')) body.headword_source=null;
    return body;
  };
  window.CorporiumChineseMode={
    refresh,tableActive,
    generated:()=>!!source,
    tableAnalyses:()=>source && !detailsMode ? (selected() ? [selected()] : []) : null,
    async prepare() {
      await opening;
      await Promise.all([...$('ws-analyses').querySelectorAll('.ws-component')].map(row => row.registryPending));
      refresh();
      if (source && (!selected() || !leaves().length || leaves().some(row => !wsVal(row,'form').trim()))) {
        throw Error(ui('请填写生成基本词形的全部组分，或选择独立词形。','Fill every source component, or choose an independent headword.'));
      }
    }
  };
})();

