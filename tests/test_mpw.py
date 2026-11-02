import json
import unittest
from urllib.parse import urlencode
from unittest.mock import patch
import corpus_statistics
import mpw_statistics
import test_lexicon
import server


class MPWTests(unittest.TestCase):
    setUp=test_lexicon.LexiconTests.setUp
    tearDown=test_lexicon.LexiconTests.tearDown
    call=test_lexicon.LexiconTests.call
    seed=test_lexicon.LexiconTests.seed
    word=test_lexicon.LexiconTests.word
    link=test_lexicon.LexiconTests.link
    entries=test_lexicon.LexiconTests.entries

    def count(self,separate=False,**scope):
        code,run=self.call('/api/analysis-run',dict(query=dict(kind='counts',separate_clitics=separate,scope=dict(mode='language',**scope))))
        self.assertEqual(code,200,run)
        code,data=self.call('/api/analysis-result?'+urlencode(dict(id=run['id'],language='ordos')))
        self.assertEqual(code,200,data)
        return run,data['statistics']

    def test_form_cells_scripts_groups_empty_parts_and_clitic_groups(self):
        for source,expected in [('a-b=ke',(3,1)),('ke=a-b=ki',(4,2)),('a＝ke',(2,1)),('=ke',(1,0)),('a==ke',(2,1)),('a--b',(2,0)),('a~a+b',(3,0)),('a<in-fix>b-c',(2,0)),('a#sub[x-y]-b#sup[=k]',(2,0)),('∅-a',(2,0)),('a.b',(1,0))]:
            with self.subTest(source=source):self.assertEqual(mpw_statistics.cells(source),expected)

    def test_ratio_counts_unlinked_cells_and_only_changes_mpw_denominator(self):
        self.seed('#pass([], (([a-b=ke],[A-B=CL]),([c],[C]),([。],[]),([#],[#]),([],[])), [])')
        _,joined=self.count();_,separate=self.count(True)
        self.assertEqual(joined['words'],2);self.assertEqual(separate['words'],2)
        self.assertEqual(joined['mpw'],dict(morphemes=4,word_slots=2,clitic_words=1,words=2,value=2,separate_clitics=False))
        self.assertEqual(separate['mpw']['morphemes'],4)
        self.assertEqual(separate['mpw']['words'],3);self.assertAlmostEqual(separate['mpw']['value'],4/3)
        self.assertEqual(separate['rows'][0]['mpw'],separate['mpw'])

    def test_union_is_weighted_and_dictionary_references_are_not_duplicated(self):
        e=self.seed('#pass([], (([a-b-c],[A-B-C]),), [])');x=self.word()
        x['body']['usages'][0]['senses'][0]['short_gloss']='A-B-C'
        code,x=self.call('/api/lexeme-save',x);self.assertEqual(code,200,x)
        self.link(e['words'][0]['unit_id'],x)
        self.assertEqual(self.call('/api/import',dict(title='Second',content='#pass([], (([d],[D]),([e],[E]),([f],[F])), [])'))[0],200)
        _,stats=self.count()
        self.assertEqual((stats['mpw']['morphemes'],stats['mpw']['words'],stats['mpw']['value']),(6,4,1.5))
        self.assertEqual(sorted(r['mpw']['value'] for r in stats['rows'] if r['mpw']['value'] is not None),[1,3])

    def test_options_cache_snapshot_and_invalid_values(self):
        self.seed('#pass([], (([a=ke],[A=CL]),), [])')
        first,stats=self.count(True);cached,_=self.count(True);joined,_=self.count(False)
        self.assertTrue(cached['cached']);self.assertFalse(joined['cached'])
        code,saved=self.call('/api/analysis-save',dict(kind='snapshot',name='MPW',run_id=first['id']));self.assertEqual(code,200,saved)
        code,data=self.call('/api/analysis-export?'+urlencode(dict(id=saved['id'],snapshot='true',language='ordos')))
        self.assertEqual(code,200,data);self.assertEqual(data['statistics']['mpw'],stats['mpw']);self.assertTrue(data['query']['separate_clitics'])
        for value in ('true',1,None,[]):
            code,data=self.call('/api/analysis-run',dict(query=dict(kind='counts',scope=dict(mode='language'),separate_clitics=value)))
            self.assertEqual(code,400,data)

    def test_empty_scope_is_undefined_and_independent_examples_use_same_rule(self):
        _,stats=self.count();self.assertIsNone(stats['mpw']['value'])
        self.assertEqual(self.call('/api/example-save',dict(body=dict(ipa='',translation='',words=[dict(form='ke=a-b',gloss='CL=A-B')])))[0],200)
        _,stats=self.count(True)
        self.assertEqual((stats['mpw']['morphemes'],stats['mpw']['words'],stats['mpw']['value']),(3,2,1.5))

    def test_repeated_forms_share_counting_without_research_writes(self):
        counter=mpw_statistics.Counter(corpus_statistics.WordCounter(),True)
        with patch.object(mpw_statistics,'cells',wraps=mpw_statistics.cells) as parse:
            counter.record([dict(form='a-b=ke')]*2000)
        self.assertEqual(parse.call_count,1);self.assertEqual(counter.finish()['value'],1.5)
