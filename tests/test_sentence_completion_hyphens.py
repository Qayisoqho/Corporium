"""Hyphenated citation forms remain candidates without changing segmentation."""
import copy
import unittest

import test_sentence_dictionary as sd
import test_paradigms
from sentence_dictionary import prepared_word


class CompletionHyphenTests(unittest.TestCase):
    for name in ('setUp', 'tearDown', 'call', 'api', 'source', 'detail', 'args', 'entry', 'undo'):
        locals()[name] = getattr(sd.SentenceDictionaryTests, name)

    def preview(self, src):
        return self.api('sentence-gloss-preview', self.args(src))

    def apply(self, src, plan, row, candidate):
        return self.api('sentence-gloss-apply', dict(**self.args(src), token=plan['token'],
            choices=[dict(word=row['word'], key=row['key'], candidate_id=candidate['id'])]))

    def test_internal_hyphens_offer_headword_and_variant_both_sources(self):
        head = self.entry('-nǐ-ha-o-', '你好')
        variant = self.entry('base', '自己', variants=[dict(form='zi-ǰi')])
        fid = variant['body']['variants'][0]['id']
        for kind in ('corpus', 'independent'):
            with self.subTest(kind=kind):
                src = self.source(kind, [('nǐhao', ''), ('ziǰi', ''), ('keep', '原标注')])
                before = self.detail(src)
                history = self.api('undo-state')
                plan = self.preview(src)
                self.assertEqual(self.api('undo-state'), history)
                self.assertEqual(self.detail(src), before)
                self.assertEqual([len(r['candidates']) for r in plan['rows']], [1, 1])
                for row, expected, form_id in zip(plan['rows'], (head, variant), (None, fid)):
                    c = row['candidates'][0]
                    self.assertEqual(c['lexeme_id'], expected['id'])
                    self.assertEqual(c['form_id'], form_id)
                    self.assertTrue(c['relaxed'])
                    self.assertTrue(row['automatic'])
                    self.assertIn('词形中的 -', c['reason'])
                choices = [dict(word=r['word'], key=r['key'], candidate_id=r['candidates'][0]['id']) for r in plan['rows']]
                self.api('sentence-gloss-apply', dict(**self.args(src), token=plan['token'], choices=choices))
                after = self.detail(src)
                self.assertEqual([w['form'] for w in after['body']['words']], ['nǐhao', 'ziǰi', 'keep'])
                self.assertEqual([w['gloss'] for w in after['body']['words']], ['你好', '自己', '原标注'])
                self.assertEqual([w['id'] for w in before['words']], [w['id'] for w in after['words']])
                if kind == 'independent':
                    link = next(t for t in after['body']['targets'] if t['lexeme_id'] == variant['id'])
                else:
                    link = self.api('unit-dictionary?id='+after['body']['words'][1]['unit_id'])['link']
                self.assertEqual(link['form_id'], fid)
                self.undo()
                self.assertEqual([w['gloss'] for w in self.detail(src)['body']['words']], ['', '', '原标注'])
                self.undo(True)
                self.assertEqual([w['gloss'] for w in self.detail(src)['body']['words']], ['你好', '自己', '原标注'])
        self.assertEqual(self.api('lexeme?id='+head['id']), head)
        self.assertEqual(self.api('lexeme?id='+variant['id']), variant)

    def test_exact_is_first_without_hiding_relaxed_ambiguity(self):
        exact = self.entry('abc', '精确')
        self.entry('a-bc', '甲')
        self.entry('ab-c', '乙')
        left = self.entry('x-yz', '同义')
        right = self.entry('xy-z', '同义')
        for kind in ('corpus', 'independent'):
            with self.subTest(kind=kind):
                src = self.source(kind, [('abc', ''), ('xyz', '')])
                plan = self.preview(src)
                first, second = plan['rows']
                self.assertEqual(len(first['candidates']), 3)
                self.assertEqual(first['candidates'][0]['lexeme_id'], exact['id'])
                self.assertFalse(first['automatic'])
                self.assertFalse(first['candidates'][0]['relaxed'])
                self.assertTrue(all(c['relaxed'] for c in first['candidates'][1:]))
                self.assertEqual(len({c['id'] for c in first['candidates']}), 3)
                self.assertEqual({c['lexeme_id'] for c in second['candidates']}, {left['id'], right['id']})
                self.assertFalse(second['automatic'])
                c = next(c for c in second['candidates'] if c['lexeme_id'] == right['id'])
                self.apply(src, plan, second, c)
                self.assertEqual([w['gloss'] for w in self.detail(src)['body']['words']], ['', '同义'])

    def test_hyphenated_paradigm_form_uses_its_own_meaning(self):
        body = copy.deepcopy(test_paradigms.body())
        body['variants'][0]['form'] = 'we-nt'
        x = self.api('lexeme-save', dict(headword='go', body=body))
        for kind in ('corpus', 'independent'):
            with self.subTest(kind=kind):
                src = self.source(kind, [('went', '')])
                plan = self.preview(src)
                row = plan['rows'][0]
                self.assertEqual(len(row['candidates']), 1)
                c = row['candidates'][0]
                self.assertEqual((c['lexeme_id'], c['form_id'], c['sense_id'], c['gloss']),
                    (x['id'], 'went', 'went-meaning', '去.PST'))
                self.apply(src, plan, row, c)
                self.assertEqual(self.detail(src)['body']['words'][0]['gloss'], '去.PST')

    def test_only_hyphens_inside_forms_are_ignored_and_split_keys_stay_stable(self):
        self.entry('x-y', 'XY')
        self.entry('a.b', 'DOT')
        self.entry('c=d', 'EQUAL')
        self.entry('e+f', 'PLUS')
        self.entry('ǰ-i', 'CARON')
        self.entry('q‐r', 'UNICODE HYPHEN')
        self.entry('pa-', 'PA')
        for kind in ('corpus', 'independent'):
            with self.subTest(kind=kind):
                src = self.source(kind, [('pa-xy', ''), ('ab', ''), ('cd', ''), ('ef', ''),
                    ('ji', ''), ('ǰI', ''), ('qr', '')])
                before = self.detail(src)
                plan = self.preview(src)
                row = next(r for r in plan['rows'] if r['word'] == 0 and r['key'] == '1:host')
                self.assertEqual(len(row['candidates']), 1)
                self.assertTrue(all(not r['candidates'] for r in plan['rows'] if r['word'] > 0))
                self.apply(src, plan, row, row['candidates'][0])
                after = self.detail(src)
                self.assertEqual(after['body']['words'][0]['gloss'], '-XY')
                self.assertEqual(after['body']['words'][0]['form'], 'pa-xy')
                # Entirely blank glosses mirror the existing explicit form
                # boundaries during preparation; they have no units beforehand.
                self.assertEqual([m['key'] for m in prepared_word(before['body']['words'][0])['morphemes']],
                    [m['key'] for m in after['body']['words'][0]['morphemes']])

    def test_unique_internal_hyphen_morpheme_prefills_and_stale_preview_is_rejected(self):
        m = self.api('morpheme-save', dict(form='x-y', body=dict(gloss='XY')))
        for kind in ('corpus', 'independent'):
            src = self.source(kind, [('xy', '')])
            plan = self.preview(src)
            row = plan['rows'][0]
            self.assertEqual(len(row['candidates']), 1)
            self.assertTrue(row['automatic'])
            self.assertFalse(row['candidates'][0]['citation_match'])
            m = self.api('morpheme?id='+m['id'])
            m['body']['notes'] = kind
            self.api('morpheme-save', m)
            status, error = self.call('/api/sentence-gloss-apply', dict(**self.args(src), token=plan['token'],
                choices=[dict(word=row['word'], key=row['key'], candidate_id=row['candidates'][0]['id'])]))
            self.assertEqual(status, 400, error)
            self.assertEqual(self.detail(src)['body']['words'][0]['gloss'], '')

    def test_unique_edge_markers_prefill_both_target_types_and_sources(self):
        for kind in ('corpus', 'independent'):
            for target_kind in ('lexeme', 'morpheme'):
                for prefix, suffix in (('-', ''), ('', '-'), ('=', ''), ('', '='), ('.', ''), ('', '.'), ('=-.', '.-=')):
                    with self.subTest(kind=kind, target=target_kind, prefix=prefix, suffix=suffix):
                        form = f'form{kind}{target_kind}{ord(prefix[0]) if prefix else 0}{ord(suffix[0]) if suffix else 0}{len(prefix)}'
                        spelling = prefix + form + suffix
                        if target_kind == 'lexeme':
                            self.entry(spelling, '标注')
                        else:
                            self.api('morpheme-save', dict(form=spelling, body=dict(gloss='标注')))
                        src = self.source(kind, [(form, '')])
                        before = self.detail(src)
                        plan = self.preview(src)
                        row = plan['rows'][0]
                        self.assertEqual(len(row['candidates']), 1)
                        self.assertTrue(row['automatic'])
                        self.assertEqual(self.detail(src), before)
                        self.apply(src, plan, row, row['candidates'][0])
                        self.assertEqual(self.detail(src)['body']['words'][0]['gloss'], '标注')

    def test_kele_noun_does_not_hide_hyphenated_verb_both_sources(self):
        verb = self.entry('kele-', '说')
        noun = self.entry('kele', '舌头')
        noun['body']['usages'][0]['senses'].append(dict(short_gloss='语言'))
        noun = self.api('lexeme-save', noun)
        for kind in ('corpus', 'independent'):
            src = self.source(kind, [('kele-ǰi', '')])
            plan = self.preview(src)
            row = next(r for r in plan['rows'] if r['key'] == '0:host')
            self.assertEqual(len(row['candidates']), 3)
            self.assertEqual([c['gloss'] for c in row['candidates']], ['舌头', '语言', '说'])
            self.assertFalse(row['automatic'])
            c = next(c for c in row['candidates'] if c['lexeme_id'] == verb['id'])
            self.apply(src, plan, row, c)
            self.assertEqual(self.detail(src)['body']['words'][0]['gloss'], '说-')

    def test_unsplit_punctuated_words_use_analyzed_lookup_without_editing_form(self):
        x = self.entry('say-', '说')
        for kind in ('corpus', 'independent'):
            for form in ('say!', 'say,', '“say”'):
                with self.subTest(kind=kind, form=form):
                    src = self.source(kind, [(form, '')])
                    plan = self.preview(src)
                    row = plan['rows'][0]
                    self.assertEqual(row['key'], '@word')
                    self.assertEqual(len(row['candidates']), 1)
                    self.assertEqual(row['candidates'][0]['lexeme_id'], x['id'])
                    self.assertTrue(row['automatic'])
                    self.assertEqual(self.detail(src)['body']['words'][0]['gloss'], '')
                    self.apply(src, plan, row, row['candidates'][0])
                    w = self.detail(src)['body']['words'][0]
                    self.assertEqual((w['form'], w['gloss']), (form, '说'))


if __name__ == '__main__':
    unittest.main()
