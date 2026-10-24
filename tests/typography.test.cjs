const test = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const vm = require('node:vm');

test('language fonts distinguish DOM CSS from HTML attribute encoding', () => {
  const context = vm.createContext({
    validFont: value => typeof value === 'string' && !!value,
    esc: text => text.replaceAll('&', '&amp;').replaceAll('"', '&quot;')
  });
  vm.runInContext(fs.readFileSync('web/typography.js', 'utf8').split('const variantOptions')[0], context);
  const settings = {annotation_font: 'Research & Serif', morpheme_variant: 'bolditalic'};
  const css = context.languageTypographyCSS(settings);
  assert.ok(css.includes('--annotation-font:"Research & Serif"'));
  assert.ok(css.includes('--form-style:italic;--form-weight:700'));
  assert.ok(!css.includes('&quot;'));
  assert.ok(context.languageTypography(settings).includes('&quot;Research &amp; Serif&quot;'));
  assert.ok(context.languageTypographyCSS({}).includes('--annotation-font:"Junicode"'));
});

test('all four row settings reset at language boundaries, including defaults', () => {
  const context = vm.createContext({validFont: value => typeof value === 'string' && !!value, esc: value => value});
  vm.runInContext(fs.readFileSync('web/typography.js', 'utf8').split('const variantOptions')[0], context);
  const a = {ipa_scale:.8, morpheme_scale:1.2, gloss_font:'KaiTi', gloss_variant:'bolditalic', gloss_scale:1.5, translation_font:'SimSun', translation_variant:'italic', translation_scale:2};
  const css = context.languageTypographyCSS(a);
  for (const text of ['--ipa-scale:0.8', '--form-scale:1.2', '--gloss-font:"KaiTi"', '--gloss-style:italic', '--gloss-weight:700', '--gloss-scale:1.5', '--translation-font:"SimSun"', '--translation-style:italic', '--translation-scale:2']) assert.ok(css.includes(text), text);
  const defaults = context.languageTypographyCSS({});
  for (const text of ['--ipa-scale:1', '--form-scale:1', '--gloss-font:"Junicode"', '--gloss-style:normal', '--gloss-scale:1', '--translation-font:sans-serif', '--translation-style:normal', '--translation-scale:1']) assert.ok(defaults.includes(text), text);
  assert.equal(context.languageTypographyCSS(a), css);
  assert.ok(context.languageTypographyCSS({gloss_scale:'2', translation_scale:99}).includes('--gloss-scale:1'));
});

test('legacy local preferences are immutable fallbacks; saved language rows take priority', () => {
  const legacy={ipaScale:.7,gloss:'KaiTi',glossBold:true};
  const c=vm.createContext({validFont:v=>typeof v==='string'&&!!v,esc:v=>v,localStorage:{getItem:()=>JSON.stringify(legacy)}});
  vm.runInContext(fs.readFileSync('web/typography.js','utf8').split('const variantOptions')[0],c);
  const initial=c.languageTypographyCSS({});assert.ok(initial.includes('--ipa-scale:0.7'));assert.ok(initial.includes('--gloss-font:"KaiTi"'));assert.ok(initial.includes('--gloss-weight:700'));
  const configured=c.languageTypographyCSS({ipa_scale:1.2,gloss_font:'Junicode',gloss_variant:'italic'});assert.ok(configured.includes('--ipa-scale:1.2'));assert.ok(configured.includes('--gloss-font:"Junicode"'));assert.ok(configured.includes('--gloss-weight:400'));
  legacy.ipaScale=2;assert.equal(c.languageTypographyCSS({}),initial);
});
