"""SQL windows must agree with complete documents and follow source changes."""
import source_fixtures
from contextlib import closing
import json
import sqlite3
import unittest
from unittest.mock import patch

import dictionary_data
import dictionary_read
import dictionary_search
import lexicon
import morpheme_registry
import search_keys
import sentence_search_index
import server
import test_dictionary_performance
import test_lexicon


class DictionaryReadTests(unittest.TestCase):
    setUp = test_lexicon.LexiconTests.setUp
    tearDown = test_lexicon.LexiconTests.tearDown
    call = test_lexicon.LexiconTests.call
    undo = test_lexicon.LexiconTests.undo
    seed = test_dictionary_performance.DictionaryPerformanceTests.seed

    def test_literal_content_index_matches_complete_documents_and_rollback(self):
        import dictionary_own_index
        self.seed()
        self.edges()
        with server.connect(audit=False) as db:
            for target in (False,True):
                for scope in ('entry','all'):
                    for query in ('a','父','unmatched-needle'):
                        args=dict(query=query,search=dict(scope=scope),targets=target,summary=True)
                        with patch.object(dictionary_own_index,'predicate',return_value=None):
                            expected=lexicon._list_lexemes(db,'all',**args)
                        self.assertEqual(lexicon.list_lexemes(db,'all',**args),expected)
            db.execute('SAVEPOINT word_change')
            db.execute("UPDATE lexemes SET headword='rollback-needle' WHERE rowid=(SELECT min(rowid) FROM lexemes)")
            args=dict(query='rollback-needle',search=dict(scope='entry'),summary=True)
            self.assertEqual(lexicon.list_lexemes(db,'all',**args)['total'],1)
            db.execute('ROLLBACK TO word_change')
            self.assertEqual(lexicon.list_lexemes(db,'all',**args)['total'],0)
            db.execute('RELEASE word_change')

    def edges(self):
        other = self.call('/api/save-language', {'name': 'Other', 'metadata': {}})[1]['id']
        with server.connect(audit=False) as db:
            for i, word in enumerate(('Straße', 'STRASSE', 'é', 'e\u0301', ' quoted ', 'quoted', '100%_x', 'a', 'a', 'A', '', '   ')):
                for lid in ('ordos', other):
                    body = lexicon.normalize({'notes': 'long hidden content', 'usages': [{'pos': 'N', 'senses': [{'short_gloss': word}]}]})
                    if i % 3:
                        body['created_at'] = f'2026-01-{i+1:02}T00:00:00.000000+00:00'
                    source_fixtures.seed(db,'lexemes',('id', 'language_id', 'headword', 'body', 'revision'),(f'{lid}-x{i}', lid, word, json.dumps(body), 1))
                    source_fixtures.seed(db,'morphemes',('id', 'language_id', 'form', 'number', 'body', 'revision'),(f'{lid}-m{i}', lid, word, i+1, json.dumps({'gloss': word, 'created_at': body.get('created_at')}), 1))
        return other

    def compare(self, db, lid='ordos', spec=None, query='', **kw):
        with patch.object(dictionary_read, 'predicate', return_value=None):
            expected = lexicon.list_lexemes(db, lid, query, search=spec, **kw)
        actual = lexicon.list_lexemes(db, lid, query, search=spec, **kw)
        self.assertEqual(actual, expected, (lid, spec, query, kw))
        return actual

    def test_empty_entry_pickers_only_expand_the_visible_rows(self):
        self.seed()
        with server.connect(audit=False) as db, patch.object(dictionary_search, 'SearchIndex', side_effect=AssertionError('empty picker must not build documents')):
            with patch.object(dictionary_data, 'resolve', wraps=dictionary_data.resolve) as resolve:
                data = lexicon.list_lexemes(db, 'ordos', targets=True, counts=False, search={'scope': 'entry'}, page=2)
                self.assertEqual((data['total'], len(data['items'])), (246, 30))
                self.assertEqual(resolve.call_count, 30)
            data = morpheme_registry.listing(db, 'ordos', search={'scope': 'entry'}, page_size=20)
            self.assertEqual((data['total'], len(data['items'])), (123, 20))
            self.assertEqual(db.execute('SELECT count(*) FROM dictionary_form_search').fetchone()[0], 0)

    def test_association_choices_use_forms_and_restore_subscripts_on_undo(self):
        import morphology
        self.seed()
        code,other=self.call('/api/save-language',{'name':'Other','metadata':{}})
        self.assertEqual(code,200,other)
        targets=[]
        for form,language in (('Écho','ordos'),('Écho','ordos'),('Écho',other['id'])):
            code,row=self.call('/api/morpheme-save',dict(form=form,body={'gloss':'root'},_language=language))
            self.assertEqual(code,200,row)
            targets.append(row)

        def choices(query,page=1,exclude='',language='ordos'):
            with server.connect(audit=False) as db, patch('dictionary_rows.raw_bodies',
                    side_effect=AssertionError('association choices must not load definition bodies')):
                return morphology.choices(db,language,query,page,exclude)

        self.assertEqual((choices('FORM',3)['total'],len(choices('FORM',3)['items'])),(123,23))
        self.assertEqual([row['id'] for row in choices('éCHO₂',language='all')['items']],[targets[1]['id']])
        self.assertEqual(choices('écho₂',exclude=targets[1]['id'])['total'],0)
        self.assertEqual([row['body']['homonym_number'] for row in choices('écho')['items']],[1,2])
        code,row=self.call('/api/morpheme-save',{**targets[1],'form':'changed'})
        self.assertEqual(code,200,row)
        self.assertEqual(choices('écho₂')['total'],0)
        self.assertIsNone(choices('écho')['items'][0]['body']['homonym_number'])
        self.assertEqual(self.undo()[0],200)
        self.assertEqual([row['id'] for row in choices('écho₂')['items']],[targets[1]['id']])

        from urllib.parse import urlencode
        lexemes=[]
        for _ in range(2):
            token=self.call('/api/homonym-preview?'+urlencode(dict(form='Öl',language='ordos')))[1]['token']
            code,row=self.call('/api/lexeme-save',dict(headword='Öl',body={},homonym_confirmation=token))
            self.assertEqual(code,200,row)
            lexemes.append(row['id'])
        self.assertEqual([row['id'] for row in choices('öl')['items']],lexemes)
        self.assertEqual([row['id'] for row in choices('ÖL₂')['items']],lexemes[1:])
        self.assertEqual(self.undo()[0],200)
        self.assertEqual(choices('öl₂')['total'],0)
        self.assertEqual([row['id'] for row in choices('öl')['items']],lexemes[:1])

    def test_summary_does_not_decode_full_stored_drafts(self):
        self.seed()
        with server.connect(audit=False) as db:
            raw = {r[0] for r in db.execute('SELECT body FROM lexemes_documents')}
            loads = json.loads

            def decode(value, *args, **kw):
                self.assertNotIn(value, raw)
                return loads(value, *args, **kw)

            with patch.object(json, 'loads', side_effect=decode):
                data = lexicon.list_lexemes(db, 'ordos', summary=True)
            self.assertEqual(len(data['items']), 30)
            self.assertEqual(set(data['items'][0]['body']), {'homonym_number', 'homonym_note', 'usages'})

    def test_literal_form_modes_unicode_spaces_and_boolean_combinations(self):
        self.edges()
        cases = [('exact', 'STRASSE'), ('exact', 'é'), ('prefix', 'e\u0301'), ('suffix', 'x'),
                 ('contains', '%_'), ('not_contains', 'a'), ('empty', ''), ('present', ''), ('exact', ' quoted ')]
        with server.connect(audit=False) as db:
            for case in (True, False):
                for op, value in cases:
                    for targets in (False, True):
                        self.compare(db, spec={'scope': 'entry', 'case': case, 'conditions': [{'field': 'headword', 'op': op, 'value': value}]}, targets=targets, summary=True, page_size='all')
                for combine in ('all', 'any'):
                    spec = {'field': 'headword', 'case': case, 'combine': combine, 'scope': 'entry', 'conditions': [
                        {'field': 'headword', 'op': 'prefix', 'value': 'a'}, {'field': 'headword', 'op': 'suffix', 'value': 'x'}]}
                    self.compare(db, spec=spec, query='a', summary=True)

    def test_languages_pages_dates_homonyms_and_identity_only_reads(self):
        other = self.edges()
        with server.connect(audit=False) as db:
            for lid in ('ordos', other, 'all'):
                for order in ('', '@added-asc', '@added-desc'):
                    for targets in (False, True):
                        for size, page in ((10, 2), (10, 999), ('all', 99)):
                            spec = {'scope': 'entry', 'conditions': [{'field': 'headword', 'op': 'present'}]}
                            self.compare(db, lid, spec, targets=targets, counts=False, page=page, page_size=size, order=order)
                        self.compare(db, lid, {'scope': 'entry'}, targets=targets, ids_only=True, order=order)

    def test_morpheme_form_predicates_match_the_complete_reader(self):
        other = self.edges()
        with server.connect(audit=False) as db:
            for lid in ('ordos', other, 'all'):
                for case in (True, False):
                    for op, value in (('exact', 'STRASSE'), ('prefix', 'é'), ('suffix', 'x'), ('empty', ''), ('not_contains', 'a')):
                        spec = {'scope': 'entry', 'case': case, 'conditions': [{'field': 'form', 'op': op, 'value': value}]}
                        with patch.object(dictionary_read, 'predicate', return_value=None):
                            expected = morpheme_registry.listing(db, lid, search=spec, page_size=10, page=2)
                        self.assertEqual(morpheme_registry.listing(db, lid, search=spec, page_size=10, page=2), expected)

    def test_invalid_specs_still_reach_the_existing_validator(self):
        for spec in ({'scope': 'invalid'}, {'case': 1}, {'field': 'gone'}, {'combine': 'bad'},
                     {'class_id': None}, {'conditions': {}}, {'conditions': [{'field': 'headword', 'op': 'exact', 'value': ' '}]},
                     {'conditions': [{'field': 'headword', 'op': 'unknown', 'value': 'a'}]}):
            with server.connect(audit=False) as db:
                with self.assertRaises(ValueError, msg=str(spec)):
                    lexicon.list_lexemes(db, 'ordos', search=spec, summary=True)
                with self.assertRaises(ValueError, msg=str(spec)):
                    morpheme_registry.listing(db, 'ordos', search=spec)

    def test_key_invalidation_covers_external_writes_rollback_and_language_moves(self):
        other = self.edges()
        spec = {'conditions': [{'field': 'headword', 'op': 'exact', 'value': 'Straße'}]}
        with server.connect(audit=False) as db:
            self.assertEqual(lexicon.list_lexemes(db, 'ordos', search=spec, summary=True)['total'], 2)
        with server.connect(audit=False) as db:
            db.execute('SAVEPOINT change')
            db.execute("UPDATE lexemes SET headword='renamed' WHERE id='ordos-x0'")
            self.assertEqual(lexicon.list_lexemes(db, 'ordos', search=spec, summary=True)['total'], 1)
            db.execute('ROLLBACK TO change'); db.execute('RELEASE change')
            self.assertEqual(lexicon.list_lexemes(db, 'ordos', search=spec, summary=True)['total'], 2)
            db.execute("UPDATE lexemes SET language_id=? WHERE id='ordos-x0'", (other,))
            self.assertEqual(lexicon.list_lexemes(db, 'ordos', search=spec, summary=True)['total'], 1)
            self.assertEqual(lexicon.list_lexemes(db, other, search=spec, summary=True)['total'], 3)
            db.execute("DELETE FROM lexemes WHERE id='ordos-x0'")
            self.assertEqual(lexicon.list_lexemes(db, other, search=spec, summary=True)['total'], 2)

    def test_edit_undo_redo_and_shared_values_remain_current(self):
        status, item = self.call('/api/lexeme-save', {'headword': 'before', 'body': {}})
        self.assertEqual(status, 200)

        def total(word):
            with server.connect(audit=False) as db:
                return lexicon.list_lexemes(db, 'ordos', search={'conditions': [{'field': 'headword', 'op': 'exact', 'value': word}]}, summary=True)['total']

        self.assertEqual(total('before'), 1)
        item['headword'] = 'after'
        self.assertEqual(self.call('/api/lexeme-save', item)[0], 200)
        self.assertEqual((total('before'), total('after')), (0, 1))
        self.assertEqual(self.undo()[0], 200)
        self.assertEqual((total('before'), total('after')), (1, 0))
        self.assertEqual(self.undo('redo')[0], 200)
        self.assertEqual((total('before'), total('after')), (0, 1))
        with server.connect(audit=False) as db:
            vid = search_keys.Values(db).intern('after')
            search_keys.Values(db).release([vid])
            self.assertIsNotNone(db.execute('SELECT id FROM projection_search_values WHERE id=?', (vid,)).fetchone())

    def test_optional_fts_missing_keys_read_only_and_portable_rebuild(self):
        self.edges()
        spec = {'field': 'headword', 'scope': 'entry'}
        with server.connect(audit=False) as db:
            db.execute('DROP TABLE IF EXISTS projection_search_fts')
            self.compare(db, spec=spec, query='STRASSE', summary=True)
            with closing(sqlite3.connect(':memory:')) as copy:
                copy.row_factory = sqlite3.Row
                db.commit(); db.backup(copy)
                sentence_search_index.drop(copy)
                self.assertFalse(copy.execute("SELECT 1 FROM sqlite_master WHERE name GLOB 'dictionary_form_*'").fetchone())
                with patch.object(dictionary_read, 'predicate', return_value=None):
                    expected = lexicon.list_lexemes(copy, 'ordos', 'é', search=spec, summary=True)
                self.assertEqual(lexicon.list_lexemes(copy, 'ordos', 'é', search=spec, summary=True), expected)
                sentence_search_index.initialize(copy)
                self.assertEqual(lexicon.list_lexemes(copy, 'ordos', 'é', search=spec, summary=True), expected)
            db.execute("UPDATE lexemes SET headword='É' WHERE id='ordos-x2'")
        with closing(sqlite3.connect(server.DB.as_uri() + '?mode=ro', uri=True)) as db:
            db.row_factory = sqlite3.Row
            self.compare(db, spec=spec, query='é', summary=True)

    def test_default_order_uses_the_matching_index(self):
        self.seed()
        with server.connect(audit=False) as db:
            plans = list(db.execute("EXPLAIN QUERY PLAN SELECT id FROM lexemes WHERE language_id=? ORDER BY headword COLLATE NOCASE,homonym_number,rowid LIMIT 30", ('ordos',)))
            self.assertTrue(any('lexemes_list_language' in r[3] for r in plans))
            self.assertFalse(any('TEMP B-TREE' in r[3] for r in plans))


if __name__ == '__main__':
    unittest.main()
