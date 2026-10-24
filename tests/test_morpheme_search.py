import json
import unittest
from urllib.parse import urlencode
import test_lexicon


class MorphemeSearchTests(unittest.TestCase):
    setUp = test_lexicon.LexiconTests.setUp
    tearDown = test_lexicon.LexiconTests.tearDown
    call = test_lexicon.LexiconTests.call

    def search(self, q='', **spec):
        code, data = self.call('/api/morphemes?' + urlencode({'q': q, 'search': json.dumps(spec)}))
        self.assertEqual(code, 200, data)
        return data

    def test_fields_custom_writings_features_and_language_scope(self):
        tag = self.call('/api/grammar-save', {'symbol': 'ANIM', 'description': '有生'})[1]
        writing = self.call('/api/writing-save', {'name': '汉字', 'font': 'Junicode'})[1]
        body = {'gloss': '植物', 'notes': 'évidence', 'readings': ['ma'],
                'features': [tag['id']], 'writings': [{'type_id': writing['id'], 'text': '麻'}],
                'senses': [{'id': 'sense2', 'gloss': '纤维', 'definition': '制作绳索'}]}
        code, item = self.call('/api/morpheme-save', {'form': 'ma', 'body': body})
        self.assertEqual(code, 200, item)
        for field, query in [('form', 'ma'), ('gloss', '植物'), ('readings', 'ma'),
                             ('writing:'+writing['id'], '麻'), ('features', '有生'),
                             ('senses.definition', '绳索'), ('notes', 'E\u0301VIDENCE')]:
            self.assertEqual([r['id'] for r in self.search(query, field=field)['items']], [item['id']])
        self.assertEqual(self.search('植物', field='form')['total'], 0)
        self.assertEqual(self.search(tag['id'])['total'], 0)
        self.assertEqual(self.search('ÉVIDENCE', case=True)['total'], 0)
        fields = self.call('/api/morpheme-search-options')[1]['fields']
        self.assertIn('writing:'+writing['id'], [f['id'] for f in fields])
        other = self.call('/api/save-language', {'name': 'Other', 'metadata': {}})[1]['id']
        self.assertEqual(self.call('/api/morphemes?language=' + other)[1]['total'], 0)

    def test_affix_metadata_stays_dormant_for_other_types(self):
        code,m=self.call('/api/morpheme-save',dict(form='n',body=dict(entry_type='affix',affix_function='inflection',affix_position='infix')))
        self.assertEqual(code,200,m)
        self.assertEqual(self.search('屈折',field='affix_function')['total'],1)
        m['body']['entry_type']='connector';code,m=self.call('/api/morpheme-save',m);self.assertEqual(code,200,m)
        self.assertEqual(m['body']['affix_position'],'infix')
        for query in ('屈折','中缀'):
            self.assertEqual(self.search(query)['total'],0)
        m['body']['entry_type']='affix';self.assertEqual(self.call('/api/morpheme-save',m)[0],200)
        self.assertEqual(self.search('中缀',field='affix_position')['total'],1)

    def test_conditions_apply_before_pagination(self):
        for n in range(32):
            self.call('/api/morpheme-save', {'form': f'm{n:02}', 'body': {'notes': 'target' if n < 31 else 'other'}})
        result = self.search(conditions=[{'field': 'notes', 'op': 'exact', 'value': 'target'}])
        self.assertEqual((result['total'], len(result['items']), result['pages']), (31, 30, 2))
        self.assertEqual(self.search(conditions=[{'field': 'senses', 'op': 'empty'}])['total'], 32)
        code, _ = self.call('/api/morphemes?' + urlencode({'search': json.dumps({'field': 'missing'})}))
        self.assertEqual(code, 400)
