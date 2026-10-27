"""Whole-library matching: citation boundaries cannot hide eligible targets."""
import unittest
from urllib.parse import urlencode

import server
import test_sentence_dictionary as sd
import test_paradigms


class AutoBoundaryTests(unittest.TestCase):
    for name in ('setUp', 'tearDown', 'call', 'api', 'source', 'detail', 'args', 'entry', 'undo'):
        locals()[name] = getattr(sd.SentenceDictionaryTests, name)

    def target(self, kind, form, gloss='G'):
        return self.entry(form, gloss) if kind == 'lexeme' else self.api('morpheme-save', dict(form=form, body=dict(gloss=gloss)))

    def scope(self, src):
        if src['kind'] == 'independent':return '@independent'
        with server.connect(audit=False) as db:
            return db.execute('SELECT text_id FROM entries WHERE id=?', (src['id'],)).fetchone()[0]

    def plan(self, src, **options):
        return self.api('lexeme-auto-preview?'+urlencode(dict(language='ordos', text_id=self.scope(src), **options)))

    def rows(self, plan, src, group='suggestions'):
        return [r for r in plan[group] if r['entry_id'] == src['id']]

    def apply(self, plan, selected=None, **options):
        b = dict(token=plan['token'], text_id=plan['text_id'], ignore_symbols=plan['ignore_symbols'], ignore_position=plan['ignore_position'])
        if selected is not None:b.update(mode='candidates', selected=selected)
        return self.api('lexeme-auto-link', {**b, **options})

    def test_each_apply_mode_leaves_the_other_matches_available_with_fresh_token(self):
        for kind in ('corpus','independent'):
            for first in ('strict','candidates'):
                with self.subTest(kind=kind,first=first):
                    prefix=kind+first
                    self.entry(prefix+'exact','G');self.entry(prefix+'relaxed-','G');self.entry(prefix+'later-','G')
                    src=self.source(kind,[(prefix+'exact','G'),(prefix+'relaxed','G'),(prefix+'later','G')])
                    p=self.plan(src);self.assertEqual(len(p['matches']),1);self.assertEqual(len(p['suggestions']),2)
                    selected=[p['suggestions'][0]['candidate_id']]
                    self.assertEqual(self.apply(p,selected if first=='candidates' else None)['count'],1)
                    fresh=self.plan(src);self.assertNotEqual(fresh['token'],p['token'])
                    self.assertEqual(len(fresh['matches']),0 if first=='strict' else 1)
                    self.assertEqual(len(fresh['suggestions']),2 if first=='strict' else 1)
                    if first=='strict':self.assertEqual({c['candidate_id'] for c in p['suggestions']},{c['candidate_id'] for c in fresh['suggestions']})
                    self.assertEqual(self.apply(fresh,[fresh['suggestions'][0]['candidate_id']] if first=='strict' else None)['count'],1)
                    final=self.plan(src);self.assertEqual(len(final['matches']),0);self.assertEqual(len(final['suggestions']),1)
                    self.undo();restored=self.plan(src);self.assertEqual(len(restored['matches']),len(fresh['matches']));self.assertEqual(len(restored['suggestions']),len(fresh['suggestions']))
                    self.undo(True);left=self.plan(src);self.apply(left,[c['candidate_id'] for c in left['suggestions']])

    def test_exact_and_edge_targets_are_all_selectable_both_sources_and_kinds(self):
        for source in ('corpus', 'independent'):
            for kind in ('lexeme', 'morpheme'):
                for n, (left, right) in enumerate((('-', ''), ('', '-'), ('=', ''), ('', '='), ('.', ''), ('', '.'))):
                    with self.subTest(source=source, target=kind, left=left, right=right):
                        form = f'word{source}{kind}{n}'
                        exact = self.target(kind, form)
                        marked = self.target(kind, left+form+right)
                        src = self.source(source, [(form, 'G')])
                        before = self.detail(src)
                        history = self.api('undo-state')
                        p = self.plan(src)
                        self.assertEqual(history, self.api('undo-state'))
                        self.assertEqual(self.rows(p, src, 'matches'), [])
                        rows = self.rows(p, src)
                        self.assertEqual([r['lexeme_id'] for r in rows], [exact['id'], marked['id']])
                        self.assertTrue(all(not r['default_selected'] for r in rows))
                        self.assertEqual(len({r['candidate_id'] for r in rows}), 2)
                        self.assertEqual(self.apply(p)['count'], 0)
                        self.assertEqual(self.detail(src), before)
                        self.assertEqual(self.apply(p, [rows[1]['candidate_id']])['count'], 1)
                        self.assertEqual(self.detail(src)['body']['words'][0]['gloss'], 'G')
                        self.undo()
                        self.assertEqual(len(self.rows(self.plan(src), src)), 2)
                        self.undo(True)
                        self.assertEqual(self.rows(self.plan(src), src), [])

    def test_unique_edge_and_internal_options_prefill_without_automatic_writes(self):
        for source in ('corpus', 'independent'):
            for kind in ('lexeme', 'morpheme'):
                for n, marker in enumerate(('-', '=', '.')):
                    with self.subTest(source=source, target=kind, marker=marker):
                        form = f'uniques{source}{kind}{n}'
                        target = self.target(kind, marker+form+marker)
                        src = self.source(source, [(form, 'G')])
                        p = self.plan(src)
                        rows = self.rows(p, src)
                        self.assertEqual(len(rows), 1)
                        self.assertTrue(rows[0]['default_selected'])
                        self.assertEqual(self.apply(p)['count'], 0)
                        self.assertEqual(self.rows(self.plan(src, ignore_symbols=''), src), [])
                        self.assertEqual(self.apply(p, [rows[0]['candidate_id']])['count'], 1)
                        self.assertEqual(rows[0]['lexeme_id'], target['id'])
                for n, marker in enumerate(('-', '=', '.')):
                    form = f'internal{source}{kind}{n}'
                    self.target(kind, form[:3]+marker+form[3:])
                    src = self.source(source, [(form, 'G')])
                    self.assertEqual(self.rows(self.plan(src), src), [])
                    p = self.plan(src, ignore_position='all')
                    rows = self.rows(p, src)
                    self.assertEqual(len(rows), 1)
                    self.assertTrue(rows[0]['default_selected'])
                    self.assertEqual(self.rows(self.plan(src, ignore_position='all', ignore_symbols=''), src), [])

    def test_different_complete_glosses_do_not_create_false_ambiguity(self):
        noun = self.entry('kele', '舌头')
        verb = self.entry('kele-', '说')
        for source in ('corpus', 'independent'):
            src = self.source(source, [('kele', '说'), ('kele', '舌头'), ('kele', '讲'), ('kelex', '说'), ('Kele', '说')])
            p = self.plan(src)
            strict, relaxed = self.rows(p, src, 'matches'), self.rows(p, src)
            self.assertEqual([r['lexeme_id'] for r in strict], [noun['id']])
            self.assertEqual([r['lexeme_id'] for r in relaxed], [verb['id']])
            self.assertTrue(relaxed[0]['default_selected'])
            self.assertEqual(self.rows(p, src, 'ambiguous'), [])

    def test_punctuated_unsplit_examples_have_one_whole_word_candidate(self):
        for kind in ('lexeme', 'morpheme'):
            form = 'punct'+kind
            x = self.target(kind, form+'=')
            for source in ('corpus', 'independent'):
                for punct in ('!', ',', '。'):
                    src = self.source(source, [(form+punct, 'G')])
                    p = self.plan(src)
                    rows = self.rows(p, src)
                    self.assertEqual(len(rows), 1)
                    c = rows[0]
                    self.assertEqual((c['kind'], c['lexeme_id'], c['normalized_form']), ('word', x['id'], form))
                    if source == 'independent':self.assertEqual(c['segmentation_ref']['key'], '@word')
                    self.apply(p, [c['candidate_id']])
                    self.assertEqual(self.detail(src)['body']['words'][0]['form'], form+punct)
                    self.assertEqual(self.rows(self.plan(src), src), [])

    def test_paradigm_and_variant_candidates_survive_an_exact_homograph(self):
        body = test_paradigms.body()
        body['variants'][0]['form'] = 'we-nt'
        inflection = self.api('lexeme-save', dict(headword='go', body=body))
        exact = self.entry('went', '去.PST')
        for source in ('corpus', 'independent'):
            src = self.source(source, [('went', '去.PST')])
            p = self.plan(src, ignore_position='all')
            rows = self.rows(p, src)
            self.assertEqual([r['lexeme_id'] for r in rows], [exact['id'], inflection['id']])
            self.assertEqual((rows[1]['form_id'], rows[1]['sense_id']), ('went', 'went-meaning'))
            self.apply(p, [rows[1]['candidate_id']])
            d = self.detail(src)
            link = d['body']['targets'][0] if source == 'independent' else self.api('unit-dictionary?id='+d['body']['words'][0]['unit_id'])['link']
            self.assertEqual((link['lexeme_id'], link['form_id'], link['sense_id']), (inflection['id'], 'went', 'went-meaning'))

    def test_same_sense_exact_aliases_are_not_duplicated_by_relaxed_index(self):
        x = self.entry('root', 'G', variants=[dict(form='root'), dict(form='root-')])
        for source in ('corpus', 'independent'):
            src = self.source(source, [('root', 'G')])
            p = self.plan(src)
            rows = self.rows(p, src)
            self.assertEqual(len(rows), 3)
            self.assertEqual({r['lexeme_id'] for r in rows}, {x['id']})
            self.assertEqual(len({r['candidate_id'] for r in rows}), 3)
            self.assertTrue(all(not r['default_selected'] for r in rows))
            p = self.plan(src, ignore_symbols='')
            self.assertEqual(len(self.rows(p, src, 'matches')), 1)
            self.assertIsNone(self.rows(p, src, 'matches')[0]['form_id'])

    def test_new_marked_target_invalidates_strict_preview_and_conflicts_roll_back(self):
        for source in ('corpus', 'independent'):
            form = 'stale'+source
            self.entry(form, 'G')
            src = self.source(source, [(form, 'G')])
            p = self.plan(src)
            self.assertEqual(len(self.rows(p, src, 'matches')), 1)
            self.entry(form+'-', 'G')
            history = self.api('undo-state')
            status, value = self.call('/api/lexeme-auto-link', dict(token=p['token'], text_id=p['text_id']))
            self.assertEqual(status, 400, value)
            fresh = self.plan(src)
            rows = self.rows(fresh, src)
            self.assertEqual(len(rows), 2)
            status, value = self.call('/api/lexeme-auto-link', dict(token=fresh['token'], text_id=fresh['text_id'],
                mode='candidates', selected=[r['candidate_id'] for r in rows]))
            self.assertEqual(status, 400, value)
            self.assertEqual(history, self.api('undo-state'))
            self.apply(fresh, [rows[1]['candidate_id']])
            self.assertEqual(self.rows(self.plan(src), src), [])

    def test_existing_single_morpheme_link_blocks_a_duplicate_whole_word_link(self):
        for source in ('corpus', 'independent'):
            for n, punctuation in enumerate(('', '!')):
                form = f'linked{source}{n}'
                x = self.entry(form+'-', 'G')
                u = x['body']['usages'][0]
                src = self.source(source, [(form+punctuation, 'G')])
                self.api('segmentation-link', dict(**self.args(src), word=0, key='0:host',
                    lexeme_id=x['id'], lexeme_revision=x['revision'], usage_id=u['id'], sense_id=u['senses'][0]['id']))
                before = self.detail(src)
                p = self.plan(src)
                self.assertEqual(self.rows(p, src), [])
                self.assertEqual(self.rows(p, src, 'matches'), [])
                self.assertGreaterEqual(p['already_linked'], 1)
                self.assertEqual(self.detail(src), before)

    def test_words_and_morphemes_compete_without_cross_kind_preference(self):
        for source in ('corpus', 'independent'):
            for n, kinds in enumerate((('lexeme', 'morpheme'), ('morpheme', 'lexeme'))):
                form = f'cross{source}{n}'
                x = self.target(kinds[0], form)
                y = self.target(kinds[1], '='+form)
                src = self.source(source, [(form, 'G')])
                p = self.plan(src)
                self.assertEqual(self.rows(p, src, 'matches'), [])
                rows = self.rows(p, src)
                self.assertEqual([r['lexeme_id'] for r in rows], [x['id'], y['id']])
                self.assertTrue(all(not r['default_selected'] for r in rows))

    def test_boundary_matching_still_requires_all_inherent_features_and_aliases(self):
        tag = self.api('grammar-save', dict(symbol='PL', aliases=['plu']))['id']
        self.api('grammar-save', dict(symbol='NOM'))
        for source in ('corpus', 'independent'):
            for kind in ('lexeme', 'morpheme'):
                form = f'feature{source}{kind}'
                exact = self.entry(form, 'G')
                if kind == 'lexeme':x = self.entry('='+form, 'G', features=[tag])
                else:x = self.api('morpheme-save', dict(form='='+form, body=dict(gloss='G', features=[tag])))
                src = self.source(source, [(form, 'G.PL'), (form, 'G.plu'), (form, 'G'), (form, 'G.PL.NOM')])
                p = self.plan(src)
                self.assertEqual([r['lexeme_id'] for r in self.rows(p, src)], [x['id'], x['id']])
                self.assertEqual([r['lexeme_id'] for r in self.rows(p, src, 'matches')], [exact['id']])
                self.assertEqual(self.rows(p, src, 'ambiguous'), [])


if __name__ == '__main__':unittest.main()
