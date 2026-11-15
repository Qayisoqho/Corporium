"""Entry editing must hydrate only referenced/selected drafts and bounded choices."""
import json
import unittest
from unittest.mock import patch

import dictionary_read
import morphology
import server
import test_dictionary_performance
import test_dictionary_read
import test_lexicon
import test_word_structure


class EditorReadTests(unittest.TestCase):
    setUp=test_lexicon.LexiconTests.setUp
    tearDown=test_lexicon.LexiconTests.tearDown
    call=test_lexicon.LexiconTests.call
    seed=test_dictionary_performance.DictionaryPerformanceTests.seed
    edges=test_dictionary_read.DictionaryReadTests.edges
    save=test_word_structure.WordStructureTests.save
    setup_structure=test_word_structure.WordStructureTests.setup_structure

    def test_editor_catalog_has_direct_references_without_reverse_or_other_drafts(self):
        _,_,_,root,word=self.setup_structure()
        self.save('reverse',{'relation':{'base_id':word['id'],'type':'stem'}})
        self.save('unrelated',{'notes':'not needed by editor'})
        with server.connect(audit=False) as db:
            data=morphology.options(db,'ordos',word['id'],editor=True)
            self.assertTrue(data['remote_choices'])
            self.assertEqual([r['id'] for r in data['entries']],[root['id']])
            self.assertEqual(json.loads(data['entries'][0]['body'])['usages'],root['body']['usages'])
            self.assertEqual(morphology.options(db,'ordos',editor=True)['entries'],[])
            self.assertGreater(len(morphology.options(db,'ordos',word['id'])['entries']),1)
        self.assertEqual(self.call('/api/morphology-options?editor=1&entry_id=missing')[0],400)

    def test_choices_page_all_candidates_without_full_bodies_or_self_reference(self):
        self.seed()
        with server.connect(audit=False) as db:
            ids=[]
            with patch('dictionary_search.SearchIndex',side_effect=AssertionError('no full search documents')):
                for page in range(1,6):
                    result=morphology.choices(db,'ordos',page=page,exclude='x0')
                    self.assertEqual(result['total'],245)
                    self.assertLessEqual(len(result['items']),50)
                    ids.extend(r['id'] for r in result['items'])
                    self.assertTrue(all(set(r['body'])=={'homonym_number'} for r in result['items']))
            self.assertEqual(len(ids),len(set(ids)))
            self.assertNotIn('x0',ids)
            self.assertEqual(len(ids),245)
            self.assertEqual(morphology.choices(db,'ordos',page=999)['page'],5)

    def test_unicode_homonym_and_language_filters_match_complete_old_labels(self):
        self.seed();other=self.edges()
        with server.connect(audit=False) as db:
            source=[dict(r) for r in db.execute('SELECT id,language_id,headword,body FROM dictionary_targets')]
            for lid in ('ordos',other,'all'):
                for query in ('STRASSE','Straße','é','e\u0301','₁','₀','a','100%_x',' quoted ','missing'):
                    needle=query.strip().lower()
                    def matches(row):
                        b=json.loads(row['body']);number=b.get('homonym_number')
                        label=row['headword']+(str(number).translate(str.maketrans('0123456789','₀₁₂₃₄₅₆₇₈₉')) if number else '')
                        return (lid=='all' or row['language_id']==lid) and needle in label.lower()
                    expected={r['id'] for r in source if matches(r)}
                    first=morphology.choices(db,lid,query)
                    actual={r['id'] for r in first['items']}
                    for page in range(2,first['pages']+1):
                        actual.update(r['id'] for r in morphology.choices(db,lid,query,page)['items'])
                    self.assertEqual(actual,expected,(lid,query))
                    self.assertEqual(first['total'],len(expected))
            with patch.object(dictionary_read,'predicate',return_value=None):
                self.assertEqual(morphology.choices(db,'ordos','form-122')['items'][0]['id'],'x122')

    def test_changed_and_rolled_back_headwords_are_visible_to_choices(self):
        self.seed()
        with server.connect(audit=False) as db:
            self.assertEqual(morphology.choices(db,'ordos','changed')['total'],0)
            db.execute('SAVEPOINT editor_change')
            db.execute("UPDATE lexemes SET headword='changed' WHERE id='x0'")
            self.assertEqual(morphology.choices(db,'ordos','changed')['items'][0]['id'],'x0')
            db.execute('ROLLBACK TO editor_change');db.execute('RELEASE editor_change')
            self.assertEqual(morphology.choices(db,'ordos','changed')['total'],0)
