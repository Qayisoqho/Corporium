import unittest
import unicodedata
import json
import uuid
import server
from urllib.parse import urlencode

import test_lexicon


class AutoUnicodeTests(unittest.TestCase):
    setUp = test_lexicon.LexiconTests.setUp
    tearDown = test_lexicon.LexiconTests.tearDown
    call = test_lexicon.LexiconTests.call
    seed = test_lexicon.LexiconTests.seed
    entries = test_lexicon.LexiconTests.entries
    undo = test_lexicon.LexiconTests.undo

    def ok(self, path, body=None):
        code, value = self.call('/api/' + path, body)
        self.assertEqual(code, 200, value)
        return value

    def plan(self, **query):
        return self.ok('lexeme-auto-preview?' + urlencode(dict(language='ordos', **query)))

    def morpheme(self, form, **fields):
        return self.ok('morpheme-save', dict(form=form, body=dict(gloss='c.cn', **fields)))

    def test_exact_native_and_independent_preserve_original_spellings_and_undo(self):
        e = self.seed('#pass([ǰi], (([ǰi],[c.cn]),), [t])')
        m = self.morpheme('j\u030ci')
        ex = self.ok('example-save', dict(body=dict(words=[dict(form='ǰi', gloss='c.cn')])))
        p = self.plan(ignore_symbols='')
        self.assertEqual(len(p['matches']), 2, p)
        self.assertEqual(p['suggestions'], [])
        self.assertEqual({c['lexeme_id'] for c in p['matches']}, {m['id']})
        self.assertEqual({c['matched_form'] for c in p['matches']}, {'j\u030ci'})
        self.assertEqual({c['form'] for c in p['matches']}, {'ǰi'})
        self.assertEqual(self.ok('lexeme-auto-link', dict(token=p['token'], ignore_symbols=''))['count'], 2)
        self.assertEqual(self.ok('morpheme?id=' + m['id'])['form'], 'j\u030ci')
        self.assertEqual(self.entries()[0]['words'][0]['form'], 'ǰi')
        self.assertEqual(self.ok('independent-example?id=' + ex['id'])['body']['words'][0]['form'], 'ǰi')
        self.assertEqual(self.plan()['already_linked'], 2)
        self.assertEqual(self.undo()[0], 200)
        self.assertEqual(len(self.plan()['matches']), 2)
        self.assertEqual(self.undo('redo')[0], 200)
        self.assertEqual(self.ok('lexeme-examples?id=' + m['id'])['total'], 1)

    def test_affix_marker_still_requires_explicit_confirmation_and_complete_gloss(self):
        e = self.seed('#pass([ipa], (([ge-ǰi],[quot-c.cn]),([ge-ǰi],[quot-pst.ide]),([ge-ǰike],[quot-c.cn]),([ge-J̌i],[quot-c.cn])), [t])')
        m = self.morpheme('-j\u030ci')
        p = self.plan(text_id=e['text_id'])
        self.assertEqual(p['matches'], [])
        self.assertEqual(len(p['suggestions']), 1, p)
        c = p['suggestions'][0]
        self.assertTrue(c['default_selected'])
        self.assertEqual((c['form'], c['gloss'], c['lexeme_id']), ('ǰi', 'c.cn', m['id']))
        self.assertEqual(self.plan(text_id=e['text_id'], ignore_symbols='')['suggestions'], [])
        self.assertEqual(self.ok('lexeme-auto-link', dict(token=p['token'], text_id=e['text_id']))['count'], 0)
        self.assertEqual(self.ok('lexeme-auto-link', dict(token=p['token'], text_id=e['text_id'], mode='candidates', selected=[c['candidate_id']]))['count'], 1)
        self.assertEqual(self.ok('lexeme-examples?id=' + m['id'])['total'], 1)
        self.assertEqual(self.entries()[0]['words'][0]['form'], 'ge-ǰi')
        self.assertEqual(self.entries()[0]['words'][1]['gloss'], 'quot-pst.ide')
        self.assertEqual(self.undo()[0], 200)
        self.assertEqual(len(self.plan(text_id=e['text_id'])['suggestions']), 1)

    def test_unique_marker_defaults_include_words_and_enabled_internal_markers(self):
        self.seed('#pass([], (([ka],[c.cn]),([ab],[c.cn]),([wo],[c.cn]),([ka],[other])), [])')
        self.morpheme('-ka');self.morpheme('a.b')
        self.ok('lexeme-save',dict(headword='-wo',body=dict(usages=[dict(senses=[dict(short_gloss='c.cn')])])))
        self.ok('example-save',dict(body=dict(words=[dict(form='ka',gloss='c.cn')])))
        p=self.plan(ignore_position='all');rows=p['suggestions']
        self.assertEqual([(r['form'],r['default_selected']) for r in rows].count(('ka',True)),2)
        self.assertTrue(all(r['default_selected'] for r in rows if r['form'] in ('ab','wo')))
        self.assertEqual(len(rows),4);self.assertEqual(p['matches'],[])
        self.assertEqual(self.ok('lexeme-auto-link',dict(token=p['token'],ignore_position='all'))['count'],0)

    def test_reverse_equivalence_and_registered_lexeme_variant(self):
        self.seed('#pass([ipa], (([ǰi],[c.cn]),), [t])')
        x = self.ok('lexeme-save', dict(headword='base', body=dict(usages=[dict(senses=[dict(short_gloss='c.cn')])], variants=[dict(form='ǰi')])))
        p = self.plan()
        self.assertEqual(len(p['matches']), 1, p)
        self.assertEqual(p['matches'][0]['form_id'], x['body']['variants'][0]['id'])
        self.assertEqual(p['matches'][0]['form'], 'j\u030ci')

    def test_equivalent_records_remain_ambiguous_and_duplicate_forms_do_not_guess(self):
        self.seed('#pass([ipa], (([ǰi],[c.cn]),), [t])')
        m = self.morpheme('j\u030ci', variants=[dict(form='ǰi')])
        p = self.plan()
        self.assertEqual(len(p['matches']), 1)
        self.assertIsNone(p['matches'][0]['form_id'])
        self.morpheme('ǰi')
        p = self.plan()
        self.assertEqual(p['matches'], [])
        self.assertEqual(len(p['ambiguous']), 1)
        self.assertEqual(len(p['ambiguous'][0]['candidates']), 2)

    def test_comparison_does_not_fold_compatibility_characters_or_other_diacritics(self):
        self.seed('#pass([ipa], (([ji],[c.cn]),([j́i],[c.cn]),([ǰI],[c.cn]),([ｊ̌i],[c.cn])), [t])')
        self.morpheme('j\u030ci')
        p = self.plan()
        self.assertEqual(p['matches'], [])
        self.assertEqual(p['suggestions'], [])
        self.assertEqual(p['ambiguous'], [])

    def test_all_canonically_decomposable_latin_letters_in_both_directions(self):
        letters=[]
        for code in range(0x110000):
            c=chr(code);decomposed=unicodedata.normalize('NFD',c)
            if 'LATIN' in unicodedata.name(c,'') and len(decomposed)>1 and 'LATIN' in unicodedata.name(decomposed[0],'') and all(unicodedata.combining(x) for x in decomposed[1:]):letters.append(c)
        self.assertTrue(set('ǰčšöüáñçǖ').issubset(letters))
        self.assertGreater(len(letters),400)
        template=self.ok('lexeme-save',dict(headword='template',body=dict(usages=[dict(senses=[dict(short_gloss='canonical')])])))
        with server.connect(audit=False) as db:
            db.execute('DELETE FROM lexemes WHERE id=?',(template['id'],))
            for i,c in enumerate(letters):
                spelling=c if i%2 else unicodedata.normalize('NFD',c)
                db.execute('INSERT INTO lexemes(id,language_id,headword,body) VALUES(?,?,?,?)',(str(uuid.uuid4()),'ordos',spelling,json.dumps(template['body'])))
        forms=[unicodedata.normalize('NFD',c) if i%2 else c for i,c in enumerate(letters)]
        self.seed('#pass([], ('+','.join('(['+f+'],[canonical])' for f in forms)+',), [])')
        p=self.plan(ignore_symbols='');self.assertEqual(len(p['matches']),len(letters));self.assertEqual(p['ambiguous'],[])

    def test_native_variants_auto_link_with_features_and_preserve_form_identity(self):
        tag=self.ok('grammar-save',dict(symbol='PL'))['id']
        m=self.morpheme('n',variants=[dict(form='čü',features=[tag])])
        e=self.seed('#pass([], (([čü],[c.cn.PL]),([čü],[c.cn]),([n],[c.cn])), [])')
        ex=self.ok('example-save',dict(body=dict(words=[dict(form='čü',gloss='c.cn.PL')])))
        p=self.plan();self.assertEqual(len(p['matches']),3,p)
        variant=[c for c in p['matches'] if c['form_id']]
        self.assertEqual(len(variant),2);self.assertTrue(all(c['form_id']==m['body']['variants'][0]['id'] for c in variant))
        self.assertEqual(self.ok('lexeme-auto-link',dict(token=p['token']))['count'],3)
        self.assertEqual(self.ok('dictionary-examples?id='+m['id'])[0]['body']['targets'][0]['form_id'],m['body']['variants'][0]['id'])
        self.assertEqual(self.undo()[0],200)


if __name__ == '__main__':
    unittest.main()
