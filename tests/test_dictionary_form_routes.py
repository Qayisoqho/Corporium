"""Exercise real dictionary save/replacement routes with explicit form identities."""
import copy
import unittest

import test_dictionary_form_sync


class FormRouteTests(unittest.TestCase):
    for name in ('setUp', 'tearDown', 'call', 'api', 'detail', 'example', 'bind', 'undo'):
        locals()[name] = getattr(test_dictionary_form_sync.FormSyncTests, name)

    def fixture(self, kind):
        # Two homographic variants deliberately have different stable IDs.
        body = dict(variants=[dict(form='-ne', notes='first'),
                              dict(form='-ne', notes='second')])
        if kind == 'lexeme':
            body['usages'] = [dict(senses=[dict(short_gloss='GEN')])]
            x = self.api('lexeme-save', dict(headword='-n', body=body))
        else:
            body.update(gloss='GEN', entry_type='affix')
            x = self.api('morpheme-save', dict(form='-n', body=body))
        variants = x['body']['variants']
        pairs = [('root-n', '根-GEN'), ('root-ne', '根-GEN'),
                 ('root-ne', '根-GEN'), ('root-n', '根-GEN'),
                 ('root-ne', '根-GEN'), ('root-ne', '根-GEN'),
                 ('n', 'GEN'), ('ne', 'GEN'), ('ne', 'GEN')]
        text = self.api('import', dict(title=kind, content='#pass([unchanged IPA ' + kind + '], (' +
                        ','.join('([%s],[%s])' % p for p in pairs) + '), [keep translation])'))
        e = self.api('entries?text=' + text['id'])['items'][0]
        ex = self.example(pairs)
        records = [('corpus', e), ('independent', ex)]
        for owner, r in records:
            for i, form in [(0, None), (1, variants[0]['id']), (2, variants[1]['id']),
                            (6, None), (7, variants[0]['id']), (8, variants[1]['id'])]:
                self.bind(r, x, '1:host' if i < 3 else '@word', owner, i, form)
        return x, records

    def current(self, kind, x):
        return self.api(kind + '?id=' + x['id'])

    def snapshot(self, kind, x, records):
        current = self.current(kind, x)
        bodies = [self.detail(r, owner)['body'] for owner, r in records]
        self.assertEqual([b['warnings'] for b in bodies], [[], []])
        self.assertTrue(all(not t['segmentation_review'] and
                            not t['segmentation_ref'].get('detached')
                            for t in bodies[1]['targets']))
        # Versions advance on undo/redo; identities and actual content must match.
        return dict(
            base=current['headword' if kind == 'lexeme' else 'form'],
            variants=[(v['id'], v['form'], v['notes']) for v in current['body']['variants']],
            forms=[[w['form'] for w in b['words']] for b in bodies],
            glosses=[[w['gloss'] for w in b['words']] for b in bodies],
            corpus_ids=[(w['unit_id'], [m['unit_id'] for m in w['morphemes']])
                        for w in bodies[0]['words']],
            independent_ids=[w['annotation_id'] for w in bodies[1]['words']],
            refs=[(t['lexeme_id'], t.get('form_id'), t['usage_id'], t['sense_id'],
                   t['segmentation_ref']['word'], t['segmentation_ref']['key'])
                  for t in bodies[1]['targets']],
            metadata=[(b.get('ipa'), b.get('translation'), b.get('notes', '')) for b in bodies])

    def replace(self, kind, x, records, field, find, replacement, path=None, expected=1):
        args = dict(kind=kind, scope='current', field=field, find=find,
                    replacement=replacement, mode='exact', case=True,
                    **{kind + '_id': x['id']})
        before = self.snapshot(kind, x, records)
        history = self.api('undo-state')
        preview = self.api('dictionary-replace-preview', args)
        self.assertEqual(preview['blocked'], [])
        self.assertEqual(len(preview['changes']), expected)
        self.assertEqual(self.snapshot(kind, x, records), before)
        self.assertEqual(self.api('undo-state'), history, 'preview must not write or add history')
        keys = [c['key'] for c in preview['changes'] if path is None or c['path'] == path]
        self.assertEqual(len(keys), 1)
        result = self.api('dictionary-replace-apply', dict(
            **args, token=preview['token'], keys=keys, confirm_conflicts=True))
        self.assertEqual((result['records'], result['replacements']), (1, 1))
        self.assertEqual(self.api('undo-state')['generation'], history['generation'] + 1)

    def assert_forms(self, state, linked):
        # Positions 3..5 are unlinked homographs, including both variant spellings.
        expected = ['root-' + s for s in linked] + ['root-n', 'root-ne', 'root-ne'] + linked
        self.assertEqual(state['forms'], [expected, expected])

    def test_selected_replace_base_and_homographic_variants_are_independent_with_full_undo_redo(self):
        for kind in ('lexeme', 'morpheme'):
            with self.subTest(kind=kind):
                x, records = self.fixture(kind)
                states = [self.snapshot(kind, x, records)]
                operations = [('headword' if kind == 'lexeme' else 'form', '-n', '-na', None, 1,
                               ['na', 'ne', 'ne']),
                              ('variant', '-ne', '-nea', ['body', 'variants', 0, 'form'], 2,
                               ['na', 'nea', 'ne']),
                              ('variant', '-ne', '-nei', ['body', 'variants', 1, 'form'], 1,
                               ['na', 'nea', 'nei'])]
                for field, old, new, path, count, forms in operations:
                    self.replace(kind, x, records, field, old, new, path, count)
                    state = self.snapshot(kind, x, records)
                    self.assert_forms(state, forms)
                    for key in ('corpus_ids', 'independent_ids', 'refs', 'metadata', 'glosses'):
                        self.assertEqual(state[key], states[0][key])
                    states.append(state)
                for expected in reversed(states[:-1]):
                    self.assertEqual(self.undo()[0], 200)
                    self.assertEqual(self.snapshot(kind, x, records), expected)
                for expected in states[1:]:
                    self.assertEqual(self.undo('redo')[0], 200)
                    self.assertEqual(self.snapshot(kind, x, records), expected)

    def test_combined_base_variant_and_gloss_save_restores_every_change_in_one_step(self):
        for kind in ('lexeme', 'morpheme'):
            with self.subTest(kind=kind):
                x, records = self.fixture(kind)
                before = self.snapshot(kind, x, records)
                current = copy.deepcopy(x)
                current['headword' if kind == 'lexeme' else 'form'] = '-na'
                for variant, form in zip(current['body']['variants'], ['-nea', '-nei']):
                    variant['form'] = form
                if kind == 'lexeme':
                    current['body']['usages'][0]['senses'][0]['short_gloss'] = 'POSS'
                else:
                    current['body']['gloss'] = 'POSS'
                history = self.api('undo-state')
                self.api(kind + '-save', current)
                after = self.snapshot(kind, x, records)
                self.assert_forms(after, ['na', 'nea', 'nei'])
                self.assertEqual(after['glosses'], [
                    ['根-POSS'] * 3 + ['根-GEN'] * 3 + ['POSS'] * 3] * 2)
                for key in ('corpus_ids', 'independent_ids', 'refs', 'metadata'):
                    self.assertEqual(after[key], before[key])
                self.assertEqual(self.api('undo-state')['generation'], history['generation'] + 1)
                self.assertEqual(self.undo()[0], 200)
                self.assertEqual(self.snapshot(kind, x, records), before)
                self.assertEqual(self.undo('redo')[0], 200)
                self.assertEqual(self.snapshot(kind, x, records), after)

    def test_replace_all_three_forms_in_one_transaction(self):
        for kind in ('lexeme', 'morpheme'):
            with self.subTest(kind=kind):
                x, records = self.fixture(kind)
                before = self.snapshot(kind, x, records)
                args = dict(kind=kind, scope='current', field='all', find='-n',
                            replacement='-k', mode='prefix', case=True,
                            **{kind + '_id': x['id']})
                preview = self.api('dictionary-replace-preview', args)
                self.assertEqual(len(preview['changes']), 3)
                self.assertEqual(preview['blocked'], [])
                self.assertEqual(self.snapshot(kind, x, records), before)
                self.api('dictionary-replace-apply', dict(**args, token=preview['token'],
                         keys=[c['key'] for c in preview['changes']], confirm_conflicts=True))
                after = self.snapshot(kind, x, records)
                self.assert_forms(after, ['k', 'ke', 'ke'])
                self.assertEqual(self.undo()[0], 200)
                self.assertEqual(self.snapshot(kind, x, records), before)
                self.assertEqual(self.undo('redo')[0], 200)
                self.assertEqual(self.snapshot(kind, x, records), after)
