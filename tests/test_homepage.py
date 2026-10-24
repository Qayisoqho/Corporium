import unittest
import test_server

class HomeTests(unittest.TestCase):
    setUp=test_server.APITests.setUp
    tearDown=test_server.APITests.tearDown
    call=test_server.APITests.call

    def test_empty(self):
        code,r=self.call('/api/home');self.assertEqual(code,200)
        self.assertEqual(r['counts']['sentences'],0);self.assertEqual(r['samples'],[])

    def test_global_counts_dedup_and_sources(self):
        self.call('/api/import',dict(title='Text',content='#pass([ipa], (([a],[A]),), [translation])'))
        x=self.call('/api/lexeme-save',dict(headword='a',body={}))[1]
        self.call('/api/example-save',dict(body=dict(ipa='ipa',translation='translation',targets=[dict(lexeme_id=x['id'])])))
        self.call('/api/example-save',dict(body=dict(original='Independent',translation='other',targets=[dict(lexeme_id=x['id'])])))
        other=self.call('/api/save-language',dict(name='Other',metadata={}))[1]['id']
        self.call('/api/import',dict(_language=other,title='Other text',content='#pass([ipa], (([a],[A]),), [translation])'))
        r=self.call('/api/home?language=ordos')[1]
        self.assertEqual(r['counts'],dict(texts=2,corpus_sentences=2,independent_sentences=2,lexemes=1,sentences=4))
        self.assertEqual(len(r['samples']),3)
        self.assertEqual({s['kind'] for s in r['samples']},{'corpus','independent'})
        self.assertEqual({s['language_id'] for s in r['samples']},{'ordos',other})
        independent=next(s for s in r['samples'] if s['kind']=='independent')
        self.assertEqual(independent['lexeme_id'],x['id'])

    def test_bounded_sample_and_blank_entries(self):
        self.call('/api/new-text',dict(title='Blank'))
        self.call('/api/import',dict(title='Many',content='\n'.join('#pass([ipa'+str(i)+'], (([a],[A]),), [translation])' for i in range(40))))
        r=self.call('/api/home')[1]
        self.assertEqual(len(r['samples']),24)
        self.assertEqual(len({s['id'] for s in r['samples']}),24)

    def test_library_only_unlinked_examples_and_word_forms(self):
        first=self.call('/api/example-save',dict(body=dict(ipa='tʰa',translation='独立例句，无词条关联')))[1]
        second=self.call('/api/example-save',dict(body=dict(words=[dict(form='a',gloss='A'),dict(form='b',gloss='B')],translation='仅词格')))[1]
        r=self.call('/api/home')[1]
        self.assertEqual(r['counts']['texts'],0)
        self.assertEqual(r['counts']['sentences'],2)
        self.assertEqual(r['counts']['independent_sentences'],2)
        self.assertEqual({s['id'] for s in r['samples']},{first['id'],second['id']})
        self.assertTrue(all(s['kind']=='independent' and s['lexeme_id'] is None for s in r['samples']))
        self.assertEqual(next(s['original'] for s in r['samples'] if s['id']==second['id']),'a b')

    def test_shared_library_example_counts_once_and_refreshes_after_delete(self):
        words=[self.call('/api/lexeme-save',dict(headword=w,body={}))[1]['id'] for w in ['a','b']]
        example=self.call('/api/example-save',dict(body=dict(ipa='one',targets=[dict(lexeme_id=w) for w in words])))[1]
        r=self.call('/api/home')[1]
        self.assertEqual(r['counts']['sentences'],1)
        self.assertEqual(len(r['samples']),1)
        code,deleted=self.call('/api/example-delete',dict(id=example['id'],revision=example['revision'],confirmed=True))
        self.assertEqual(code,200,deleted)
        r=self.call('/api/home')[1]
        self.assertEqual(r['counts']['sentences'],0)
        self.assertEqual(r['samples'],[])
