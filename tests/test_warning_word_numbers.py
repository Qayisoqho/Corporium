"""Diagnostic word numbers exclude punctuation without moving source cells."""
import copy
import json
import re
import unittest

import corpus
import corpus_statistics
import grammar
import languages
import server
import test_server
import test_lexicon
import ui_localization as ui


def example():
    words=[dict(form='«',gloss=''),dict(form=' ',gloss='')]
    for n in range(12):
        words.extend([dict(form='w'+str(n),gloss='meaning'),dict(form='，',gloss='')])
    words.extend([dict(form=r'\#',gloss=''),dict(form='—',gloss=''),
                  dict(form='bad-form',gloss='ROOT'),dict(form='。',gloss='',punctuation=True,punctuation_form='。')])
    return dict(ipa='',translation='材料不变',notes='第 99 词：这是研究笔记',words=words)


class WarningWordNumberTests(unittest.TestCase):
    def test_thirteenth_word_and_all_analysis_caches_skip_nonwords(self):
        source=example();original=copy.deepcopy(source)
        for cache in (None,corpus.WordAnalysisCache(),grammar.AuditAnalysisCache()):
            with self.subTest(cache=type(cache).__name__):
                for _ in range(2):
                    body=corpus.analyze(copy.deepcopy(source),cache=cache)
                    issues=[w for w in body['warnings'] if '语素数量' in w]
                    self.assertEqual(issues,['第 13 词：语素数量或边界不一致，保留整词配对'])
                    self.assertEqual(corpus.word_numbers(body['words'])[-2],13)
                    self.assertEqual(sum(map(corpus_statistics.is_word,body['words'])),13)
                    self.assertEqual([(w['form'],w['gloss']) for w in body['words']],[(w['form'],w['gloss']) for w in source['words']])
                    self.assertEqual(body['notes'],source['notes'])
        self.assertEqual(source,original)

    def test_word_internal_punctuation_counts_and_pure_punctuation_uses_cell(self):
        words=[dict(form='?!',gloss='X-Y'),dict(form='t!',gloss='T'),dict(form='ǃa',gloss='A'),
               dict(form='a-b',gloss='A'),dict(form='',gloss=''),dict(form='x#bad',gloss='')]
        body=corpus.analyze(dict(ipa='',translation='',words=words))
        self.assertEqual(corpus.word_numbers(words),[None,1,2,3,None,4])
        self.assertIn('第 1 格：语素数量或边界不一致，保留整词配对',body['warnings'])
        self.assertIn('第 3 词：语素数量或边界不一致，保留整词配对',body['warnings'])
        self.assertIn('第 4 词：含未支持的 Typst 命令，保留源码显示',body['warnings'])

    def test_fixed_cell_reanalysis_can_change_the_ordinal_of_untouched_words(self):
        source=dict(ipa='#source',translation='',words=[dict(form='a-b',gloss='A'),
                    dict(form='。',gloss=''),dict(form='#',gloss=''),dict(form='c-d',gloss='C')])
        previous=corpus.analyze(copy.deepcopy(source))
        for cache in (None,corpus.WordAnalysisCache()):
            for index,replacement in [(1,dict(form='extra',gloss='meaning')),
                                      (0,dict(form='!',gloss='',punctuation=True,punctuation_form='!'))]:
                with self.subTest(cache=type(cache).__name__,index=index):
                    changed=copy.deepcopy(previous);changed['words'][index]=replacement
                    expected=corpus.analyze(copy.deepcopy(changed))
                    self.assertEqual(corpus.reanalyze(changed,previous,{index},cache=cache),expected)

    def test_unknown_labels_use_the_same_word_numbers(self):
        source=example();source['words'][-2]=dict(form='bad',gloss='PL')
        catalogue={'test':dict(name='测试',metadata=json.dumps(dict(check_glossary=True)))}
        body=languages.annotate(source,'test',catalogue)
        self.assertEqual([w for w in body['warnings'] if '尚未登记' in w],
                         ['第 13 词：疑似语法标签尚未登记（请确认） PL'])

    def test_localized_warning_wrappers_preserve_authored_text_and_indices(self):
        body=corpus.analyze(example());warning='第 13 词：语素数量或边界不一致，保留整词配对'
        body['warnings'].append('第 13 词：疑似语法标签尚未登记（请确认） ZZZ')
        shapes={
            '/api/entries':dict(items=[copy.deepcopy(body)]),
            '/api/example-library':dict(items=[dict(body=copy.deepcopy(body))]),
            '/api/example-groups-library':dict(items=[dict(body=dict(members=[dict(record=dict(body=copy.deepcopy(body)))]))]),
            '/api/example-group':dict(members=[dict(record=dict(body=copy.deepcopy(body)))]),
            '/api/survey-detail':dict(items=[dict(record=dict(body=copy.deepcopy(body)))]),
            '/api/lexeme-examples':dict(items=[dict(entry=copy.deepcopy(body),word_position=28)]),
            '/api/grammar-audit':dict(items=[dict(body=copy.deepcopy(body),word=29,word_number=13)]),
            '/api/segmentation':dict(body=copy.deepcopy(body)),
            '/api/independent-example':dict(body=copy.deepcopy(body)),
        }
        for path,original in shapes.items():
            with self.subTest(path=path):
                before=json.dumps(original,ensure_ascii=False)
                self.assertIs(ui.present(original,path,'zh-CN'),original)
                result=ui.present(original,path,'en');text=json.dumps(result,ensure_ascii=False)
                self.assertIn('Word 13: Morpheme counts or boundaries differ; whole-word pairing retained',text)
                self.assertIn('Word 13: Possible unregistered grammatical labels (please confirm): ZZZ',text)
                self.assertIn(body['notes'],text);self.assertIn(body['translation'],text)
                self.assertNotIn(warning,text)
                self.assertEqual(json.dumps(original,ensure_ascii=False),before)


class WarningWordNumberRouteTests(unittest.TestCase):
    setUp=test_server.APITests.setUp
    tearDown=test_server.APITests.tearDown
    call=test_server.APITests.call
    seed=test_lexicon.LexiconTests.seed
    entries=test_lexicon.LexiconTests.entries
    word=test_lexicon.LexiconTests.word
    link=test_lexicon.LexiconTests.link

    def snapshot(self):
        with server.connect(audit=False) as db:
            return {table:[tuple(r) for r in db.execute('SELECT * FROM '+table+' ORDER BY id')]
                    for table in ('entries','dictionary_examples','corpus_units','lexical_links','survey_evidence','example_groups','example_group_members')}

    def test_sentence_sources_and_references_return_the_same_warning_number(self):
        source='#pass([], (([a],[meaning]),([,],[]),([#],[]),([bad-form],[ROOT])), [])'
        entry=self.seed(source)
        x=self.word();self.link(entry['words'][-1]['unit_id'],x)
        code,created=self.call('/api/example-save',dict(body=dict(words=[dict(form='a',gloss='meaning'),
                          dict(form=',',gloss=''),dict(form='#',gloss=''),dict(form='bad-form',gloss='ROOT')],targets=[])))
        self.assertEqual(code,200,created);rid=created['id']
        code,second=self.call('/api/example-save',dict(body=dict(words=[],targets=[])))
        self.assertEqual(code,200,second)
        code,group=self.call('/api/example-group-save',dict(body=dict(name='Numbering',numbering='letters'),members=[dict(example_id=rid),dict(example_id=second['id'])]))
        self.assertEqual(code,200,group)
        version=self.call('/api/survey?language=ordos')[1]['version']
        code,node=self.call('/api/survey-save',dict(title='Numbering',body={},version=version))
        self.assertEqual(code,200,node)
        version=self.call('/api/survey?language=ordos')[1]['version']
        code,result=self.call('/api/survey-evidence',dict(node_id=node['id'],kind='independent',record_id=rid,body={},version=version))
        self.assertEqual(code,200,result)
        # Existing projects may persist the old physical-cell wording. Display
        # readers must refresh it without rewriting those stored materials.
        with server.connect(audit=False) as db:
            for table,identity in [('entries',entry['id']),('dictionary_examples',rid)]:
                body=json.loads(db.execute('SELECT body FROM '+table+' WHERE id=?',(identity,)).fetchone()[0])
                body['warnings']=['第 4 词：语素数量或边界不一致，保留整词配对']
                db.execute('UPDATE '+table+' SET body=? WHERE id=?',(json.dumps(body,ensure_ascii=False),identity))
        before=self.snapshot()
        paths=[('/api/entries',lambda r:r['items'][0]),
               ('/api/example-library?source=independent',lambda r:next(e['body'] for e in r['items'] if e['id']==rid)),
               ('/api/lexeme-examples?id='+x['id'],lambda r:r['items'][0]['entry']),
               ('/api/segmentation?kind=corpus&id='+entry['id'],lambda r:r['body']),
               ('/api/segmentation?kind=independent&id='+rid,lambda r:r['body']),
               ('/api/survey-detail?language=ordos&id='+node['id'],lambda r:r['items'][0]['record']['body']),
               ('/api/example-group?language=ordos&id='+group['id'],lambda r:r['members'][0]['record']['body'])]
        for path,extract in paths:
            with self.subTest(path=path):
                code,value=self.call(path);self.assertEqual(code,200,value)
                body=extract(value)
                self.assertIn('第 2 词：语素数量或边界不一致，保留整词配对',body['warnings'])
                translated=extract(ui.present(value,path.partition('?')[0],'en'))
                self.assertIn('Word 2: Morpheme counts or boundaries differ; whole-word pairing retained',translated['warnings'])
        self.assertEqual(self.snapshot(),before)

    def test_audit_keeps_the_physical_cell_and_uses_a_separate_display_number(self):
        entry=self.seed('#pass([], (([a],[meaning]),([,],[]),([#],[]),([bad-form],[ROOT])), [])')
        before=self.snapshot()
        for source in ('corpus','all'):
            code,result=self.call('/api/grammar-audit?language=ordos&source='+source+'&issue=boundary')
            self.assertEqual(code,200,result)
            issue=next(i for i in result['items'] if i['id']==entry['id'])
            self.assertEqual((issue['word'],issue['word_number']),(4,2))
        self.assertEqual(self.snapshot(),before)


if __name__=='__main__':unittest.main()
