"""Native first searches agree with the established complete matcher."""
import unittest
from unittest.mock import patch
import unicodedata
import dictionary_cold
import dictionary_own_index
import record_sources
import server
import test_shared_search_index as shared
import test_gloss_inheritance as inheritance


class ColdDictionaryTests(unittest.TestCase):
    for name in ('setUp','tearDown','call','seed','entries','undo','api','word','example','detail','link','fixture','change','mode'):
        locals()[name]=getattr(inheritance.GlossInheritanceTests,name)
    dictionary=shared.SharedSearchTests.dictionary

    def test_native_unicode_hidden_values_and_visible_extensions(self):
        sentence,example,target=self.fixture()
        with server.connect(audit=False) as db:
            self.assertTrue(dictionary_cold.available(db))
            for table,rid in (('entries',sentence['id']),('dictionary_examples',example['id'])):
                body=record_sources.read(db,table,rid)
                body.update(translation='Straße e\u0301 \\"quoted"',edited=False)
                body['words'][0].update(note='Cold extension Ω',features=[],secret_test={'visible':True,'id':'hidden-only-token'},gloss_frozen={'note':'frozen-hidden-token'})
                record_sources.write(db,table,rid,body)
        for term in ('STRASSE','é','e\u0301','quoted','Ω','extension','否','是','hidden-only-token','frozen-hidden-token','家','missing'):
            for case in (False,True):self.dictionary(term,case=case)
        with server.connect(audit=False) as db:
            self.assertEqual(db.execute('SELECT count(*) FROM dictionary_own_docs').fetchone()[0],0)
            self.assertEqual(db.execute('SELECT count(*) FROM material_search_literal_records').fetchone()[0],0)

    def test_source_value_queue_edit_undo_and_transaction_rollback(self):
        sentence,example,target=self.fixture()
        self.dictionary('not-present-cold-value')
        with server.connect(audit=False) as db:
            body=record_sources.read(db,'dictionary_examples',example['id'])
            revision=db.execute('SELECT revision FROM dictionary_examples WHERE id=?',(example['id'],)).fetchone()[0]
        body['words'].append(dict(form='queued-field-form',gloss='queued-field-gloss'))
        self.api('example-save',dict(id=example['id'],body=body,revision=revision))
        with patch.object(dictionary_cold,'distinct',side_effect=AssertionError('unchanged slots must use the value queue')):
            self.dictionary('queued-field-form')
            self.dictionary('queued-field-gloss')
        self.undo()
        with patch.object(dictionary_cold,'distinct',side_effect=AssertionError('undo must update the value queue')):
            self.dictionary('queued-field-form')
        with server.connect(audit=False) as db:
            db.execute('SAVEPOINT probe')
            db.execute("UPDATE sentence_word_rows SET gloss='rolled-back-token' WHERE kind='corpus' AND owner_id=? AND position=0",(sentence['id'],))
            self.assertIn('rolled-back-token',dictionary_cold.source_values(db)['gloss'])
            db.execute('ROLLBACK TO probe');db.execute('RELEASE probe')
        self.dictionary('rolled-back-token')
        with server.connect(audit=False) as db:
            db.execute("UPDATE sentence_word_rows SET gloss='different-after-rollback' WHERE kind='corpus' AND owner_id=? AND position=0",(sentence['id'],))
        self.dictionary('different-after-rollback')
        self.dictionary('external-header-update')
        with server.connect(audit=False) as db:
            db.execute("UPDATE sentence_text_rows SET translation='external-header-update' WHERE kind='corpus' AND owner_id=?",(sentence['id'],))
        self.dictionary('external-header-update')

    def test_reference_labels_composed_glosses_and_media(self):
        _,_,target=self.fixture()
        with server.connect(audit=False) as db:
            body=record_sources.read(db,'lexemes',target['id'])
            body['usages'][0]['senses'][0].update(short_gloss='meaning.3',gloss_addition='SG')
            body['usages'][0].update(pos='Noun',subclass='Countable')
            record_sources.write(db,'lexemes',target['id'],body)
        for term in ('meaning.3SG','meaning','Noun / Countable',target['headword'],'尚未指定'):
            self.dictionary(term)

    def test_unicode_negative_anchors_are_conservative(self):
        safe=set('bcdegmopqruvxz0123456789')
        if unicodedata.unidata_version not in ('14.0.0','15.0.0'):return
        for i in range(128,0x110000):
            self.assertFalse(safe.intersection(unicodedata.normalize('NFC',chr(i)).casefold()),hex(i))

    def test_cached_queries_update_only_changed_definitions_and_bound_their_scopes(self):
        _,_,target=self.fixture()
        for term in ('incremental-cold-needle','missing-other-query'):
            self.dictionary(term)
        edit=self.api('lexeme?id='+target['id'])
        edit['body']['usages'][0]['senses'][0]['definition']='incremental-cold-needle'
        self.api('lexeme-save',edit)
        original=dictionary_cold.Query.own
        seen=[]
        def limited(query,only=None):
            self.assertIsNotNone(only)
            seen.append(set(only))
            return original(query,only)
        with patch.object(dictionary_cold.Query,'own',limited):
            self.assertEqual(self.dictionary('incremental-cold-needle')['total'],1)
            self.undo()
            self.assertEqual(self.dictionary('incremental-cold-needle')['total'],0)
        self.assertTrue(seen)
        self.assertTrue(all(ids=={target['id']} for ids in seen))
        for i in range(10):self.dictionary('bounded-query-'+str(i))
        with server.connect(audit=False) as db:
            self.assertLessEqual(db.execute('SELECT count(*) FROM dictionary_cold_query_state').fetchone()[0],8)
            self.assertEqual(db.execute("SELECT count(*) FROM dictionary_own_scopes WHERE context LIKE 'cold:%'").fetchone()[0],8)
            self.assertEqual(db.execute("SELECT count(*) FROM sqlite_master WHERE type='trigger' AND name LIKE 'dictionary_cold_independent_%'").fetchone()[0],6)

    def test_repeated_queries_follow_manual_annotation_edits_and_undo(self):
        import annotations
        sentence,_,target=self.fixture()
        layer=self.api('layer-save',dict(name='Cold note',anchor='translation'))['id']
        self.dictionary('cold-manual-token')
        data=self.api('annotations?kind=corpus&id='+sentence['id'])
        self.api('annotation-save',dict(kind='corpus',id=sentence['id'],revision=data['revision'],before=data['cells'],layers=data['layers'],
            cells=[dict(unit_id=annotations.SENTENCE,layer_id=layer,value='cold-manual-token')]))
        self.assertEqual(self.dictionary('cold-manual-token')['total'],1)
        self.undo()
        self.assertEqual(self.dictionary('cold-manual-token')['total'],0)

    def test_cold_cancellation_leaves_source_and_cache_queues_consistent(self):
        import long_tasks,journal
        self.fixture()
        with server.connect(audit=False) as db:revision=journal.workspace_revision(db)
        original=dictionary_cold.source_values
        def cancel(db):
            original(db)
            raise long_tasks.Cancelled()
        with patch.object(dictionary_cold,'source_values',cancel):
            job=long_tasks.submit(server.DB,'dictionary',dict(language='ordos',q='missing cancellation token',summary='1'))
            long_tasks.JOBS[job]['future'].result(timeout=20)
        self.assertEqual(long_tasks.view(server.DB,job)['state'],'cancelled')
        with server.connect(audit=False) as db:self.assertEqual(journal.workspace_revision(db),revision)
        self.dictionary('家')
