import json
import unittest
from contextlib import nullcontext
from unittest.mock import patch
from urllib.parse import urlencode

import source_fixtures
import server
import lexicon
import test_server


class CreatedRecordLocationTests(unittest.TestCase):
    setUp = test_server.APITests.setUp
    tearDown = test_server.APITests.tearDown
    call = test_server.APITests.call

    def get(self, endpoint, **query):
        code, data = self.call('/api/' + endpoint + '?' + urlencode(query))
        self.assertEqual(code, 200, data)
        return data

    def seed_dictionary(self):
        with server.connect() as db:
            source_fixtures.seed_many(db, 'lexemes', ('id','language_id','headword','body','revision'),
                [(f'x{i}', 'ordos', f'word-{i:03}', json.dumps(lexicon.normalize({})), 1) for i in range(37)])
            source_fixtures.seed_many(db, 'morphemes', ('id','language_id','form','number','body','revision'),
                [(f'm{i}', 'ordos', f'part-{i:03}', 1, json.dumps({'gloss':'match' if i % 2 else 'other'}), 1) for i in range(37)])

    def test_dictionary_focus_respects_sort_filter_size_and_cache(self):
        self.seed_dictionary()
        foreign = self.call('/api/save-language', {'name':'Other','metadata':{}})[1]['id']
        for endpoint in ('lexemes','morphemes'):
            for order in ('', '@added-asc', '@added-desc'):
                all_rows = self.get(endpoint, page_size='all', sort_order=order)['items']
                self.get(endpoint, page_size=10, sort_order=order, page=1)
                for index in (0, 10, 36):
                    target = all_rows[index]['id']
                    result = self.get(endpoint, page_size=10, sort_order=order, focus=target)
                    self.assertTrue(result['focus_found'])
                    self.assertEqual(result['page'], index // 10 + 1)
                    self.assertIn(target, [r['id'] for r in result['items']])
                self.assertEqual(self.get(endpoint, page_size=10, sort_order=order)['page'], 1)
            target = all_rows[-1]['id']
            self.assertEqual(self.get(endpoint, page_size='all', focus=target)['page'], 1)
            self.assertFalse(self.get(endpoint, q='absent', focus=target)['focus_found'])
            self.assertFalse(self.get(endpoint, focus='deleted')['focus_found'])
            self.assertFalse(self.get(endpoint, language=foreign, focus=target)['focus_found'])
        filtered = self.get('morphemes', q='match', page_size='all')['items']
        target = filtered[-1]['id']
        self.assertEqual(self.get('morphemes', q='match', page_size=10, focus=target)['page'], 2)

    def test_corpus_focus_counts_rows_and_checks_language(self):
        code, text = self.call('/api/import', {'title':'Pages', 'content':'\n'.join(
            '#pass([ipa], (([word],[gloss]),), [translation])' for _ in range(20))})
        self.assertEqual(code, 200, text)
        code, saved = self.call('/api/sentence-create', {'kind':'corpus','text_id':text['id'],
            'body':{'ipa':'new','words':[]},'layers':[],'cells':[],'slot_ids':[]})
        self.assertEqual(code, 200, saved)
        target = saved['id']
        self.assertEqual(self.get('entry-page', id=target, page_size=20)['page'], 2)
        # Imported numbering can have gaps: position is not a page offset.
        with server.connect() as db:
            db.execute('UPDATE entries SET position=position*10 WHERE text_id=?', (text['id'],))
        self.assertEqual(self.get('entry-page', id=target, page_size=10)['page'], 3)
        self.assertEqual(self.get('entry-page', id=target, page_size=50)['page'], 1)
        for query in ({'id':target,'page_size':0},{'id':'missing'}, {'id':target,'language':'foreign'}):
            self.assertEqual(self.call('/api/entry-page?'+urlencode(query))[0], 400)

    def test_library_focus_cached_and_windowed_plans(self):
        ids = []
        for i in range(23):
            code, row = self.call('/api/example-save', {'body':{'ipa':str(i),'words':[]}})
            self.assertEqual(code, 200, row)
            ids.append(row['id'])
        for cached in (True, False):
            # A missing view token exercises the large/windowed query path too.
            with patch('read_views.token', return_value=None) if not cached else nullcontext():
                for order, expected in (('added-asc',2), ('added-desc',1)):
                    query = {'sort_order':order}
                    self.get('example-groups-library', **query)
                    result = self.get('example-groups-library', focus=ids[-1], **query)
                    self.assertTrue(result['focus_found'])
                    self.assertEqual(result['page'], expected)
                    self.assertIn(ids[-1], [r['id'] for r in result['items']])
                    self.assertEqual(self.get('example-groups-library', **query)['page'], 1)
                self.assertFalse(self.get('example-groups-library', focus=ids[-1], q='absent')['focus_found'])
                self.assertFalse(self.get('example-groups-library', focus=ids[-1], group_filter='groups')['focus_found'])
