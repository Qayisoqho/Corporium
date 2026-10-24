import unittest
import json
from urllib.parse import urlencode
import server
import corpus_statistics
import test_lexicon


class StatisticsTests(unittest.TestCase):
    setUp=test_lexicon.LexiconTests.setUp
    tearDown=test_lexicon.LexiconTests.tearDown
    call=test_lexicon.LexiconTests.call
    seed=test_lexicon.LexiconTests.seed
    entries=test_lexicon.LexiconTests.entries
    word=test_lexicon.LexiconTests.word
    link=test_lexicon.LexiconTests.link

    def run_count(self,mode='language',**scope):
        code,r=self.call('/api/analysis-run',dict(query=dict(kind='counts',scope=dict(mode=mode,**scope))))
        self.assertEqual(code,200,r)
        code,p=self.call('/api/analysis-result?'+urlencode(dict(id=r['id'],language='ordos')))
        self.assertEqual(code,200,p)
        return r,p['statistics']

    def test_unmarked_punctuation_empty_boundaries_and_real_forms(self):
        for form in ('','  ','。','?!','……','«»','（），','—',' # ','###',r'\#',' # ， # '):
            with self.subTest(form=form):self.assertFalse(corpus_statistics.is_word(dict(form=form,gloss='TAG')))
        for form in ('a-b','t!','a#b','ʔ','ŋ','#sub[n]','123','ǃa'):
            with self.subTest(form=form):self.assertTrue(corpus_statistics.is_word(dict(form=form,gloss='')))
        e=self.seed('#pass([], (([a-b],[A-B]),([,],[]),([#],[#]),([?!],[Q]),([],[]),([t!],[T])), [])')
        _,st=self.run_count('texts',text_ids=[e['text_id']]);self.assertEqual((st['words'],st['sentences'],st['excluded']),(2,1,4))
        r=self.call('/api/analysis-run',dict(query=dict(conditions=[dict(field='form',value='')])))[1]
        self.assertEqual(r['summary']['scope_words'],2);self.assertEqual(r['summary']['hits'],2)

    def test_multiple_texts_deduplicated_and_no_empty_scope_expansion(self):
        first=self.seed()
        self.call('/api/import',dict(title='Second',content='#pass([two], (([c],[C]),), [])'))
        ids=[t['id'] for t in self.call('/api/texts')[1]]
        _,st=self.run_count('texts',text_ids=ids+[ids[0]])
        self.assertEqual((st['words'],st['sentences'],st['texts']),(3,2,2))
        _,one=self.run_count('texts',text_ids=[first['text_id']]);self.assertEqual(one['words'],2)
        for ids in ([],['missing']):
            code,r=self.call('/api/analysis-run',dict(query=dict(kind='counts',scope=dict(mode='texts',text_ids=ids))))
            self.assertEqual(code,400,r)

    def test_dictionary_union_counts_examples_once_and_lexemes_separately(self):
        e=self.seed();x=self.word();self.link(e['words'][0]['unit_id'],x);self.link(e['words'][1]['unit_id'],x)
        code,r=self.call('/api/example-save',dict(body=dict(ipa='x',translation='example',words=[dict(form='x',gloss='X'),dict(form='。',gloss='')],targets=[dict(lexeme_id=x['id'])])))
        self.assertEqual(code,200,r)
        _,dictionary=self.run_count('dictionary');self.assertEqual((dictionary['lexemes'],dictionary['sentences'],dictionary['words']),(1,2,3))
        _,whole=self.run_count();self.assertEqual((whole['sentences'],whole['words'],whole['overlap_sentences']),(2,3,1))
        _,custom=self.run_count('texts',text_ids=[e['text_id']],include_dictionary=True);self.assertEqual(custom,whole)
        _,texts=self.run_count('texts',text_ids=[e['text_id']]);self.assertEqual((texts['sentences'],texts['words']),(1,2))

    def test_count_history_snapshot_export_and_cache_invalidation(self):
        e=self.seed();r,st=self.run_count();cached,_=self.run_count();self.assertTrue(cached['cached'])
        code,snap=self.call('/api/analysis-save',dict(kind='snapshot',name='counts',run_id=r['id']));self.assertEqual(code,200,snap)
        e.update(notes='',words=[dict(form='new',gloss='N')]);self.assertEqual(self.call('/api/save',e)[0],200)
        old=self.call('/api/analysis-result?'+urlencode(dict(id=r['id'],language='ordos')))[1];self.assertTrue(old['stale'])
        exported=self.call('/api/analysis-export?'+urlencode(dict(id=snap['id'],snapshot='true',language='ordos')))[1]
        self.assertEqual(exported['statistics']['words'],2)
        fresh,st=self.run_count();self.assertFalse(fresh['cached']);self.assertEqual(st['words'],1)
        for _ in range(29):self.run_count()
        with server.connect() as db:
            self.assertEqual(db.execute('SELECT COUNT(*) FROM analysis_runs').fetchone()[0],30)
            self.assertIsNone(db.execute('SELECT id FROM analysis_runs WHERE id=?',(r['id'],)).fetchone())

    def test_independent_library_includes_unlinked_and_empty_sentences(self):
        e=self.seed();x=self.word();self.link(e['words'][0]['unit_id'],x)
        for body in ({},{'words':[{'form':'a','gloss':''},{'form':'#','gloss':''},{'form':'。','gloss':''}]},{'words':[{'form':'b','gloss':'B'}],'targets':[{'lexeme_id':x['id']}]}):
            code,r=self.call('/api/example-save',dict(body=body));self.assertEqual(code,200,r)
        _,library=self.run_count('independent')
        self.assertEqual((library['sentences'],library['words'],library['corpus_sentences']),(3,2,0))
        self.assertEqual(library['excluded'],2)
        _,combined=self.run_count('texts',text_ids=[e['text_id']],include_independent=True)
        self.assertEqual((combined['sentences'],combined['words']),(4,4))

    def test_count_language_scope_rejects_foreign_text(self):
        e=self.seed();other=self.call('/api/save-language',dict(name='Other',metadata={}))[1]['id']
        code,r=self.call('/api/analysis-run',dict(_language=other,query=dict(kind='counts',scope=dict(mode='texts',text_ids=[e['text_id']]))));self.assertEqual(code,400,r)
        code,r=self.call('/api/analysis-run',dict(_language=other,query=dict(kind='counts',scope=dict(mode='language'))));self.assertEqual(code,200,r);self.assertEqual(r['summary']['words'],0)
