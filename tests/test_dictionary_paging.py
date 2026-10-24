import json
import unittest
import server
import lexicon
import test_lexicon
from dictionary_paging import paginate


class DictionaryPagingTests(unittest.TestCase):
    setUp=test_lexicon.LexiconTests.setUp
    tearDown=test_lexicon.LexiconTests.tearDown
    call=test_lexicon.LexiconTests.call

    def seed(self):
        with server.connect() as db:
            body=json.dumps(lexicon.normalize({}))
            db.executemany('INSERT INTO lexemes VALUES(?,?,?,?,?)',[(f'x{i}','ordos',f'word-{i:04}',body,1) for i in range(1207)])
            db.executemany('INSERT INTO morphemes VALUES(?,?,?,?,?,?)',[(f'm{i}','ordos',f'part-{i:04}',1,json.dumps({'gloss':'选中' if i%2 else '其他','notes':''}),1) for i in range(1207)])

    def test_extended_sizes_and_all_in_both_lists(self):
        self.seed()
        for endpoint in ('lexemes','morphemes'):
            for size in (200,500,1000,'all'):
                code,data=self.call(f'/api/{endpoint}?page_size={size}&page=2')
                self.assertEqual(code,200,data)
                expected=1207 if size=='all' else min(size,1207-size)
                self.assertEqual(len(data['items']),expected)
                self.assertEqual(data['pages'],1 if size=='all' else (1207+size-1)//size)
                self.assertEqual(data['page'],1 if size=='all' else 2)
                self.assertEqual(data['total'],1207)

    def test_all_respects_language_and_search_before_paging(self):
        self.seed()
        for endpoint,query,expected in [('lexemes','word-00',100),('morphemes','选中',603)]:
            code,data=self.call(f'/api/{endpoint}?page_size=all&page=99&q={query}')
            self.assertEqual(code,200,data);self.assertEqual((data['total'],len(data['items']),data['page'],data['pages']),(expected,expected,1,1))
        other=self.call('/api/save-language',{'name':'Other','metadata':{}})[1]['id']
        for endpoint in ('lexemes','morphemes'):
            self.assertEqual(self.call(f'/api/{endpoint}?language={other}&page_size=all')[1]['total'],0)
            self.assertEqual(self.call(f'/api/{endpoint}?page_size=999')[0],400)

    def test_empty_all_and_invalid_sizes(self):
        self.assertEqual(paginate([],99,'all'),dict(items=[],total=0,page=1,pages=1))
        for size in (0,-1,999,'bad',None):
            with self.assertRaises(ValueError):paginate([],1,size)
