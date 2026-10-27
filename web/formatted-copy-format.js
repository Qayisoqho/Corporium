/* Editable interlinear clipboard HTML. Real Word paste checked on 2026-10-24. */
(function (root, factory) {
  const api = factory();
  if (typeof module === 'object' && module.exports) module.exports = api;
  else root.CorporiumFormattedCopyFormat = api;
})(typeof globalThis !== 'undefined' ? globalThis : this, function () {
  'use strict';
  const VERSION = 1;
  const MAX_WORDS = 62; // Word's 63 columns minus one label column.
  const MAX_TABLE_PT = 1000; // Real Word clamps pasted HTML grids to 1080pt; leave room.
  const MAX_SELECTION = 200;
  const MAX_BYTES = 12 * 1024 * 1024;
  const fonts = {ipa: 'IPAPANNEW', form: 'Junicode', gloss: 'Junicode', translation: 'Times New Roman', label: 'Times New Roman'};
  const scales = {ipa: 1.1875, form: 1.125, gloss: 1, translation: .9375, label: 1};
  const esc = s => String(s ?? '').replace(/[&<>"']/g, c => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
  const bytes = s => new TextEncoder().encode(s);
  const text = value => {
    if (typeof value !== 'string') throw Error((globalThis.CorporiumI18n?.f("25132162c88856",()=>[])??'例句文字须为字符串'));
    if (value.length > 100000) throw Error((globalThis.CorporiumI18n?.f("0ec38f6f6b91e0",()=>[])??'单个文字字段过长'));
    if (/[\uD800-\uDFFF]/u.test(value)) throw Error((globalThis.CorporiumI18n?.f("0158ef2315c8e2",()=>[])??'文字包含不完整的Unicode字符'));
    if (/[\u0000-\u0008\u000b\u000c\u000e-\u001f]/u.test(value)) throw Error((globalThis.CorporiumI18n?.f("0e96f18c0504b7",()=>[])??'文字包含不支持的控制字符'));
    return value;
  };
  function family(value, fallback) {
    value = value || fallback;
    value = ({serif:'Times New Roman','sans-serif':'Segoe UI','system-ui':'Segoe UI'})[value] || value;
    if (typeof value !== 'string' || value.length > 120 || /[;{}<>\r\n\x00-\x1f]/u.test(value)) throw Error((globalThis.CorporiumI18n?.f("104f6330ac1962",()=>[])??'字体名称无效'));
    return '"' + value.replace(/\\/g, '\\\\').replace(/"/g, '\\"') + '"';
  }
  function finite(value, fallback, min, max, label) {
    if (value === undefined) return fallback;
    if (typeof value !== 'number' || !Number.isFinite(value) || value < min || value > max) throw Error((globalThis.CorporiumI18n?.f("e010c505db1460",()=>[label])??label + '无效'));
    return value;
  }
  function typography(metadata = {}, basePt = 11) {
    const result = {};
    const rows = [['ipa','ipa'],['form','annotation'],['gloss','gloss'],['translation','translation'],['label','label']];
    for (const [row, key] of rows) {
      const variant = metadata[(row === 'form' ? 'morpheme' : row) + '_variant'] || (row === 'form' ? 'italic' : 'regular');
      if (!['regular','normal','italic','bold','bolditalic'].includes(variant)) throw Error((globalThis.CorporiumI18n?.f("ed24ada7ae9b49",()=>[])??'字体变体无效'));
      const scale = finite(metadata[(row === 'form' ? 'morpheme' : row) + '_scale'], 1, .6, 2, (globalThis.CorporiumI18n?.f("bcaaeaa03d2b49",()=>[])??'字体比例'));
      result[row] = {
        font: family(metadata[key + '_font'], fonts[row]),
        pt: Math.round(basePt * scales[row] * scale * 100) / 100,
        bold: variant.includes('bold'), italic: variant.includes('italic')
      };
    }
    return result;
  }
  function scripts(value) {
    // Only Corporium's explicit sub/sup markers are interpreted; raw HTML is text.
    value = text(value);
    const out = []; let plain = '';
    const flush = () => {if (plain) {out.push({text: plain}); plain = '';}};
    for (let i = 0; i < value.length;) {
      if (value[i] === '\\' && /[~?\[\]#]/.test(value[i + 1] || '')) {plain += value[i + 1]; i += 2; continue;}
      const m = value.slice(i).match(/^#(sub|super|sup)\[([^\[\]]*)\]/);
      if (m) {flush(); out.push({text: m[2], script: m[1] === 'sub' ? 'sub' : 'sup'}); i += m[0].length;}
      else plain += value[i++];
    }
    flush(); return out;
  }
  function runs(value, glossary = {}, grammatical = false) {
    if (Array.isArray(value)) return value.map(r => {
      if (!r || typeof r !== 'object' || !['sub','sup',undefined].includes(r.script)) throw Error((globalThis.CorporiumI18n?.f("a48fd3916a86ad",()=>[])??'文字格式片段无效'));
      return {text: text(r.text), script: r.script, bold: r.bold===undefined?undefined:!!r.bold, italic: r.italic===undefined?undefined:!!r.italic, smallCaps: !!r.smallCaps};
    });
    if (!glossary || typeof glossary !== 'object' || Array.isArray(glossary)) throw Error((globalThis.CorporiumI18n?.f("44317ed4312364",()=>[])??'语法标签定义须为对象'));
    const known = new Set(Object.keys(glossary).map(k => k.toLowerCase()));
    const spelling = new Set(Object.keys(glossary));
    const registered = (s, explicit) => known.has(s.toLowerCase()) && (explicit || !['a','all','art','pass'].includes(s.toLowerCase()) || s === s.toUpperCase() || spelling.has(s));
    const out = []; let bracket = grammatical;
    for (const r of scripts(value)) {
      for (const token of r.text.split(/([\s.\-=:+~/;_\\,!?，。；：！？\[\](){}<>«»“”"']+)/)) {
        if (!token) continue;
        if (/^[\s.\-=:+~/;_\\,!?，。；：！？\[\](){}<>«»“”"']+$/u.test(token)) {
          for (const c of token) {if (c === '[' || c === '<') bracket = true; if (c === ']' || c === '>') bracket = grammatical;}
          out.push({...r, text: token}); continue;
        }
        const person = token.match(/^([123])([A-Za-z]+)$/);
        if (registered(token, bracket)) out.push({...r, text: token, smallCaps: true});
        else if (person && registered(person[2], bracket)) out.push({...r, text: person[1]}, {...r, text: person[2], smallCaps: true});
        else out.push({...r, text: token});
      }
    }
    return out;
  }
  function plainRuns(value) {return value.map(r => r.text).join('');}
  function markup(value) {
    return value.map(r => {
      let s = esc(r.text).replace(/\r\n?|\n/g, '<br>');
      if (r.script) s = '<' + r.script + '>' + s + '</' + r.script + '>';
      // Word's smallCaps only reduces lowercase letters. Match the app's
      // all-small-caps display while keeping the original uppercase spelling.
      if (r.smallCaps && !r.script) s = '<span style="font-variant:small-caps">' + s.replace(/\p{Lu}+/gu,c=>'<span style="font-size:80%">'+c+'</span>') + '</span>';
      if (r.bold) s = '<b>' + s + '</b>';
      if (r.italic) s = '<i>' + s + '</i>';
      if (r.italic===false) s = '<span style="font-style:normal">'+s+'</span>';
      return s;
    }).join('') || '&#160;';
  }
  function sizeHint(value, style) {
    // Width estimates are not Word font metrics; they must be checked in real Word.
    let units = 0;
    for (const c of plainRuns(value)) if (!/\p{Mark}/u.test(c)) units += /[\u2e80-\uffef]/u.test(c) ? 1 : /[MWmw@]/u.test(c) ? .85 : .55;
    return Math.max(12, Math.ceil(units * style.pt + 9));
  }
  function stringField(value, fallback = '') {return text(value === undefined ? fallback : value);}
  function normalize(item, index, options) {
    if (!item || typeof item !== 'object' || typeof item.key !== 'string' || !item.key) throw Error((globalThis.CorporiumI18n?.f("a0e73cf7b17812",()=>[])??'缺少例句展示位置'));
    if (!item.body || !Array.isArray(item.body.words)) throw Error((globalThis.CorporiumI18n?.f("70153f45c72ace",()=>[])??'例句词格格式无效'));
    if (item.body.words.length > 10000) throw Error((globalThis.CorporiumI18n?.f("ccedf5fbbf5c90",()=>[])??'单条例句超过10000词格，请分批复制'));
    const body = item.body, meta = item.metadata || {}, type = typography(meta, options.basePt);
    const glossary = meta.glossary || {};
    const words = body.words.map(w => {
      if (!w || typeof w !== 'object') throw Error((globalThis.CorporiumI18n?.f("5b32b1c6922ff9",()=>[])??'词格格式无效'));
      const form = runs(w.form, {}), gloss = runs(w.gloss, glossary);
      if (/[\r\n\t\u2028\u2029]/u.test(plainRuns(form) + plainRuns(gloss))) throw Error((globalThis.CorporiumI18n?.f("30f02f5b411e5e",()=>[])??'词格含手工换行或Tab，请先明确整理；不会静默展平'));
      return {form, gloss};
    });
    const label = stringField(item.label);
    const role = stringField(item.role);
    const judgment = stringField(item.judgment?.symbol);
    if (/[\r\n\t\u2028\u2029]/u.test(label + role + judgment)) throw Error((globalThis.CorporiumI18n?.f("90ee3a88034cd9",()=>[])??'标号、角色或合法性标记不能含换行'));
    const prefix = [label, role ? role + ':' : '', judgment].filter(Boolean).join(' ');
    const ipa = runs(body.ipa ?? '', {}), translation = runs(body.translation ?? '', {});
    const layers = (item.layers || []).filter(l => l.visible !== false).map(l => {
      if (!l || !Array.isArray(l.values) || l.values.length !== words.length) throw Error((globalThis.CorporiumI18n?.f("b34a4044edb020",()=>[])??'附加行须与词格一一对应'));
      const layerType = {...type.gloss, font: family(l.font, fonts.gloss), pt: type.gloss.pt * finite(l.size,100,50,200,(globalThis.CorporiumI18n?.f("bec7ba8cf917d8",()=>[])??'附加层字号')) / 100};
      layerType.pt=finite(l.pt,options.basePt*finite(l.size,100,50,200,(globalThis.CorporiumI18n?.f("f0de775e92862c",()=>[])??'附加层字号'))/100,3,96,(globalThis.CorporiumI18n?.f("342bc49971392a",()=>[])??'附加层字号'));
      if(l.variant){layerType.bold=l.variant.includes('bold');layerType.italic=l.variant.includes('italic');}
      return {name: stringField(l.name), type: layerType, values: l.values.map(v => {
        const r = runs(v, {}); if (/[\r\n\t\u2028\u2029]/u.test(plainRuns(r))) throw Error((globalThis.CorporiumI18n?.f("0b1bfcc4128be1",()=>[])??'附加行包含换行')); return r;
      })};
    });
    const sentenceLayers=(item.sentenceLayers||[]).filter(l=>l.visible!==false).map(l=>({anchor:l.anchor==='translation'?'translation':'ipa',value:runs(l.value||''),type:{font:family(l.font,fonts.gloss),pt:finite(l.pt,options.basePt,3,96,(globalThis.CorporiumI18n?.f("4f630805a851f6",()=>[])??'附加层字号')),bold:!!l.bold,italic:!!l.italic}}));
    let group = null;
    if (item.group) {
      if (typeof item.group.key !== 'string' || !item.group.key) throw Error((globalThis.CorporiumI18n?.f("b191722076d44c",()=>[])??'例句组缺少身份'));
      group = {key: item.group.key, number: stringField(item.group.number), name: stringField(item.group.name), context: stringField(item.group.context)};
    }
    return {key: item.key, sourceId: item.sourceId || '', prefix, type, words, ipa, translation, layers, sentenceLayers, group,
      localJudgment: stringField(item.localJudgment), notes: options.includeNotes ? stringField(body.notes) : ''};
  }
  function style(s) {
    return 'font-family:' + s.font + ';mso-ascii-font-family:' + s.font + ';mso-hansi-font-family:' + s.font + ';mso-fareast-font-family:' + s.font + ';font-size:' + s.pt + 'pt;font-weight:' + (s.bold ? '700' : '400') + ';font-style:' + (s.italic ? 'italic' : 'normal') + ';color:#000000';
  }
  function renderExample(x, number, sharedLabelWidth, referenceWidth) {
    const widths = x.words.map((w, i) => Math.max(sizeHint(w.form, x.type.form), sizeHint(w.gloss, x.type.gloss), ...x.layers.map(l => sizeHint(l.values[i], l.type))));
    if (!widths.length) widths.push(18);
    const labelWidth = sharedLabelWidth || Math.max(32, sizeHint([{text: x.prefix}], x.type.label));
    const wordWidth = labelWidth + widths.reduce((a, b) => a + b, 0);
    // A blank trailing column gives sentence-level IPA/translation normal line
    // width without stretching the actual aligned word columns of short examples.
    const trailingWidth = widths.length+1<63 ? Math.max(0,referenceWidth-wordWidth) : 0;
    const columnsWidth=[labelWidth,...widths,...(trailingWidth?[trailingWidth]:[])];
    const totalWidth = wordWidth+trailingWidth,span=widths.length+(trailingWidth?1:0);
    const common = 'border:none;vertical-align:top;padding:0pt 6pt 0pt 0pt;mso-padding-alt:0pt 6pt 0pt 0pt';
    const p = (content, s, nowrap = false) => '<p style="margin:0pt;mso-margin-top-alt:0pt;mso-margin-bottom-alt:0pt;page-break-after:avoid;line-height:normal;' + (nowrap ? 'white-space:nowrap;' : '') + esc(style(s)) + '">' + content + '</p>';
    const cell = (content, s, attr = '', nowrap = false, width) => '<td' + attr + (width ? ' width="'+Math.round(width*96/72)+'"' : '') + (nowrap ? ' nowrap="nowrap"' : '') + ' style="' + common + (width ? ';width:'+width+'pt' : '') + (nowrap ? ';white-space:nowrap;mso-wrap-style:none' : '') + '">' + p(content, s, nowrap) + '</td>';
    const blank = () => cell('&#160;', x.type.label, '', false, labelWidth);
    const full = (content, s, prefix = false) => '<tr style="page-break-inside:avoid">' + (prefix ? cell(esc(x.prefix) || '&#160;', x.type.label, '', true, labelWidth) : blank()) + cell(content, s, ' colspan="' + span + '"', false, totalWidth-labelWidth) + '</tr>';
    const gridRow = (key, s, values) => '<tr style="page-break-inside:avoid" data-copy-row="' + key + '">' + (x.continuation && key==='form' ? cell((globalThis.CorporiumI18n?.f("0c27d550728588",()=>[])??'续'),x.type.label,'',true,labelWidth) : blank()) + values.map((v, i) => cell(markup(v), s, ' data-copy-word="'+i+'"', true, widths[i])).join('') +(trailingWidth?cell('&#160;',s,' data-copy-spacer="true"',true,trailingWidth):'')+ '</tr>';
    let content = x.continuation ? '' : full(markup(x.ipa), x.type.ipa, true);
    if(!x.continuation)for(const l of x.sentenceLayers.filter(l=>l.anchor==='ipa'))content+=full(markup(l.value),l.type);
    if (x.words.length) {
      content += gridRow('form', x.type.form, x.words.map(w => w.form));
      content += gridRow('gloss', x.type.gloss, x.words.map(w => w.gloss));
      for (const layer of x.layers) content += gridRow('layer', layer.type, layer.values);
    }
    if (plainRuns(x.translation)) content += full(markup(x.translation), x.type.translation);
    for(const l of x.sentenceLayers.filter(l=>l.anchor==='translation'))content+=full(markup(l.value),l.type);
    if (x.localJudgment) content += full(esc((globalThis.CorporiumI18n?.f("da3d0920d385c0",()=>[x.localJudgment])??'本处判断：' + x.localJudgment)), x.type.translation);
    if (x.notes) content += full(markup(runs(x.notes)), x.type.translation);
    const columns = columnsWidth.map(w => '<col width="' + Math.round(w * 96 / 72) + '" style="width:' + w + 'pt">').join('');
    const html = '<table data-copy-example="' + number + '" border="0" cellspacing="0" cellpadding="0" width="' + Math.round(totalWidth * 96 / 72) + '" style="border:none;border-collapse:collapse;table-layout:fixed;mso-table-layout-alt:fixed;mso-table-lspace:0pt;mso-table-rspace:0pt;width:' + totalWidth + 'pt;margin:0pt"><colgroup>' + columns + '</colgroup><tbody>' + content + '</tbody></table><p style="margin:0pt;font-size:1pt;line-height:6pt;mso-line-height-rule:exactly">&#160;</p>';
    const plain = [x.prefix + (x.prefix && plainRuns(x.ipa) ? ' ' : '') + plainRuns(x.ipa), ...x.sentenceLayers.filter(l=>l.anchor==='ipa').map(l=>plainRuns(l.value)), ...(x.words.length ? [x.words.map(w => plainRuns(w.form)).join('\t'), x.words.map(w => plainRuns(w.gloss)).join('\t'), ...x.layers.map(l => l.values.map(plainRuns).join('\t'))] : []), plainRuns(x.translation), ...x.sentenceLayers.filter(l=>l.anchor==='translation').map(l=>plainRuns(l.value)), ...(x.localJudgment ? [(globalThis.CorporiumI18n?.f("33c8a6e078f587",()=>[x.localJudgment])??'本处判断：' + x.localJudgment)] : []), ...(x.notes ? [x.notes] : [])].filter(v => v !== '').join('\r\n');
    return {html, plain, widthPt: totalWidth, labelWidthPt:labelWidth, trailingColumn:!!trailingWidth, wordColumns: x.words.length};
  }
  function cfHtml(html) {
    const startMarker = '<!--StartFragment-->', endMarker = '<!--EndFragment-->';
    const start = html.indexOf(startMarker), end = html.indexOf(endMarker);
    if (start < 0 || end <= start || html.indexOf(startMarker, start + 1) !== -1 || html.indexOf(endMarker, end + 1) !== -1) throw Error((globalThis.CorporiumI18n?.f("02b8fb8e2e132d",()=>[])??'HTML片段边界无效'));
    const header = values => 'Version:1.0\r\n' + Object.entries(values).map(([key, value]) => key + ':' + String(value).padStart(10, '0') + '\r\n').join('');
    const empty = {StartHTML: 0, EndHTML: 0, StartFragment: 0, EndFragment: 0};
    const startHtml = bytes(header(empty)).length;
    const result = header({StartHTML: startHtml, EndHTML: startHtml + bytes(html).length, StartFragment: startHtml + bytes(html.slice(0, start + startMarker.length)).length, EndFragment: startHtml + bytes(html.slice(0, end)).length});
    return bytes(result + html);
  }
  function build(items, input = {}) {
    if (!Array.isArray(items) || !items.length || items.length > MAX_SELECTION) throw Error((globalThis.CorporiumI18n?.f("488e60bdc78a32",()=>[])??'请选择1至200条例句'));
    const options = {basePt: finite(input.basePt, 11, 8, 24, (globalThis.CorporiumI18n?.f("6e5800c851f85f",()=>[])??'基础字号')),referenceWidthPt:Math.min(MAX_TABLE_PT,finite(input.referenceWidthPt,468,180,1200,(globalThis.CorporiumI18n?.f("2e598b2a2d040f",()=>[])??'参考正文宽度'))), includeNotes: input.includeNotes === true};
    const seen = new Set(), groupHeaders = new Map();
    const html = [], plain = [], tables = [], warnings = [];
    const normalized=[],labelWidths=new Map();let inputBytes=0;
    for(const [i,item] of items.entries()) {
      const x=normalize(item,i,options);
      for(const value of [x.prefix,plainRuns(x.ipa),plainRuns(x.translation),x.notes,x.localJudgment,x.group?.name||'',x.group?.context||'',...x.words.flatMap(w=>[plainRuns(w.form),plainRuns(w.gloss)]),...x.layers.flatMap(l=>l.values.map(plainRuns))])inputBytes+=bytes(value).length;
      if(inputBytes>MAX_BYTES)throw Error((globalThis.CorporiumI18n?.f("c3e685ad6daef7",()=>[])??'复制内容超过12MB上限'));
      normalized.push(x);
      if(x.group)labelWidths.set(x.group.key,Math.max(labelWidths.get(x.group.key)||32,sizeHint([{text:x.prefix}],x.type.label)));
    }
    let lastGroup = null;
    let outputBytes = 0;
    for (const [i, x] of normalized.entries()) {
      if (seen.has(x.key)) throw Error((globalThis.CorporiumI18n?.f("d5fd4c34f174b3",()=>[])??'同一展示位置不能重复选择'));
      seen.add(x.key);
      if (x.group) {
        const signature = JSON.stringify(x.group);
        if (groupHeaders.has(x.group.key) && groupHeaders.get(x.group.key) !== signature) throw Error((globalThis.CorporiumI18n?.f("969785983f92cb",()=>[])??'同一组的标题或语境不一致'));
        groupHeaders.set(x.group.key, signature);
        if (lastGroup !== x.group.key) {
          const heading = [x.group.number, x.group.name].filter(Boolean).join(' ');
          if (heading) {html.push('<p style="margin:5pt 0pt 4pt 0pt;' + esc(style(x.type.label)) + '">' + esc(heading) + '</p>'); plain.push(heading);}
          if (x.group.context) {html.push('<p style="margin:0pt 0pt 4pt 0pt;' + esc(style(x.type.translation)) + '">' + esc(x.group.context).replace(/\r\n?|\n/g, '<br>') + '</p>'); plain.push(x.group.context);}
        }
        lastGroup = x.group.key;
      } else lastGroup = null;
      const labelWidth=x.group?labelWidths.get(x.group.key):Math.max(32,sizeHint([{text:x.prefix}],x.type.label));
      if(labelWidth>MAX_TABLE_PT-12)throw Error((globalThis.CorporiumI18n?.f("cd7adf7c822663",()=>[])??'例句标号或角色过长，请整理后重试；内容未截断'));
      const chunks=[];let start=0,width=labelWidth;
      for(let j=0;j<x.words.length;j++) {
        const w=x.words[j],next=Math.max(sizeHint(w.form,x.type.form),sizeHint(w.gloss,x.type.gloss),...x.layers.map(l=>sizeHint(l.values[j],l.type)));
        if(labelWidth+next>MAX_TABLE_PT)throw Error((globalThis.CorporiumI18n?.f("4534411e27e1a7",()=>[i+1,j+1])??'例句 '+(i+1)+' 的第 '+(j+1)+' 个词格过宽，请整理该词格后重试；内容未截断'));
        if(j>start&&(j-start>=MAX_WORDS||width+next>MAX_TABLE_PT)){chunks.push([start,j]);start=j;width=labelWidth;}
        width+=next;
      }
      chunks.push([start,x.words.length]);
      if(chunks.length>1)warnings.push({key:x.key,example:i+1,parts:chunks.length,words:x.words.length,message:(globalThis.CorporiumI18n?.f("89e0fe5a94f985",()=>[i+1,chunks.length,x.words.length])??'例句 '+(i+1)+' 超过单表上限，已按原顺序分为 '+chunks.length+' 段，保留全部 '+x.words.length+' 个词格及对应标注。')});
      for(const [part,[a,b]] of chunks.entries()) {
        const last=part===chunks.length-1;
        const chunk={...x,words:x.words.slice(a,b),layers:x.layers.map(l=>({...l,values:l.values.slice(a,b)})),sentenceLayers:x.sentenceLayers.filter(l=>l.anchor==='ipa'?part===0:last),continuation:part>0,ipa:part?[]:x.ipa,prefix:part?(globalThis.CorporiumI18n?.f("e94959b8a15cb5",()=>[])??'续'):x.prefix,translation:last?x.translation:[],localJudgment:last?x.localJudgment:'',notes:last?x.notes:''};
        const result=renderExample(chunk,i+1,labelWidth,options.referenceWidthPt);outputBytes+=bytes(result.html).length;
        if(outputBytes>MAX_BYTES)throw Error((globalThis.CorporiumI18n?.f("8570bb8ff7d4f8",()=>[])??'复制内容超过12MB上限'));
        tables.push({key:x.key,part:part+1,parts:chunks.length,start:a,end:b,widthPt:result.widthPt,labelWidthPt:result.labelWidthPt,wordColumns:result.wordColumns,trailingColumn:result.trailingColumn,widerThanReference:result.widthPt>options.referenceWidthPt});html.push(result.html);plain.push(result.plain);
      }
    }
    const fragment = '<div style="color:#000000;background:#ffffff">' + html.join('') + '</div>';
    const document = (globalThis.CorporiumI18n?.f("b2170ee5b78558",()=>[fragment])??'<!doctype html><html xmlns:o="urn:schemas-microsoft-com:office:office" xmlns:w="urn:schemas-microsoft-com:office:word"><head><meta charset="utf-8"><title>Corporium 例句</title></head><body><!--StartFragment-->' + fragment + '<!--EndFragment--></body></html>');
    if (bytes(document).length > MAX_BYTES) throw Error((globalThis.CorporiumI18n?.f("fdb69e38085aea",()=>[])??'复制内容超过12MB上限'));
    return {version: VERSION, html: document, plain: plain.join('\r\n\r\n'), cfHtml: cfHtml(document), summary: {sentences: items.length, groups: groupHeaders.size, tables, warnings}};
  }
  class Selection {
    constructor(items) {this.items = items; this.active = false; this.chosen = new Set(); this.busy = false;}
    enter() {if (this.busy) throw Error((globalThis.CorporiumI18n?.f("f4b8a992139956",()=>[])??'正在生成复制内容')); this.active = true; this.chosen.clear();}
    cancel() {if (this.busy) return false; this.active = false; this.chosen.clear(); return true;}
    select(key, yes) {if (!this.active || this.busy || !this.items.some(x => x.key === key)) throw Error((globalThis.CorporiumI18n?.f("546b445ff24788",()=>[])??'当前不能选择这条例句')); if (yes) this.chosen.add(key); else this.chosen.delete(key);}
    group(key, yes) {for (const item of this.items) if (item.group?.key === key) this.select(item.key, yes);}
    groupState(key) {const rows = this.items.filter(x => x.group?.key === key), n = rows.filter(x => this.chosen.has(x.key)).length; return n === 0 ? 'none' : n === rows.length ? 'all' : 'some';}
    changePage(items) {if (this.busy) throw Error((globalThis.CorporiumI18n?.f("f6411ff863632a",()=>[])??'复制过程中不能改变范围')); this.cancel(); this.items = items;}
    async copy(writer, options) {
      if (this.busy) return null;
      if (!this.active || !this.chosen.size) throw Error((globalThis.CorporiumI18n?.f("72440f16bd0ade",()=>[])??'请先选择例句'));
      this.busy = true;
      try {
        const payload = build(numberSelection(this.items.filter(x => this.chosen.has(x.key))), options);
        await writer(payload); this.active = false; this.chosen.clear(); return payload;
      } finally {this.busy = false;}
    }
  }
  function numberSelection(items) {
    let next=0;const groups=new Map();
    return items.map(item=>{
      if(!item.group)return {...item,label:'('+(++next)+')'};
      const key=item.group.key;if(!groups.has(key))groups.set(key,++next);
      return {...item,group:{...item.group,number:'('+groups.get(key)+')'}};
    });
  }
  return {VERSION, MAX_WORDS, MAX_TABLE_PT, MAX_SELECTION, build, cfHtml, typography, runs, markup, Selection, numberSelection};
});
