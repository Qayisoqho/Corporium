"""Statistics caches must follow semantic edits, rollback and immutable snapshots."""
import source_fixtures
import copy
import json
import unittest
from unittest.mock import patch

import analysis_counts
import analysis_payload
import analysis_workspace
import corpus_statistics
import example_groups
import read_views
import server
import statistics_facts
import vocabulary_statistics
import test_vocabulary_statistics


class IncrementalStatisticsTests(unittest.TestCase):
    for name in ('setUp','tearDown','call','api','source','detail','args','entry','undo','m','bind','run_stats','page'):
        locals()[name] = getattr(test_vocabulary_statistics.VocabularyTests, name)

    def fixture(self):
        morpheme = self.m('na')
        corpus = self.source('corpus', [('na','ROOT'),('Na','N'),('é','E')])
        independent = self.source('independent', [('na','ROOT'),('e\u0301','E')])
        self.bind(corpus, morpheme)
        self.bind(independent, morpheme)
        return corpus, independent

    def test_prepared_facts_and_every_indexed_view_match_original_results(self):
        self.fixture()
        for case in (True, False):
            with server.connect(audit=False) as db:
                scope = corpus_statistics.normalize({})
                with patch.object(statistics_facts,'ready',return_value=False):
                    expected = corpus_statistics.calculate(db,'ordos',scope,case=case)
                actual = corpus_statistics.calculate(db,'ordos',scope,case=case)
                self.assertEqual(actual, expected)
                self.assertEqual(db.execute('SELECT count(*) FROM statistics_fact_dirty').fetchone()[0],0)
            run = self.run_stats(case=case)
            with server.connect(audit=False) as db:
                row = db.execute('SELECT * FROM analysis_runs WHERE id=?',(run['id'],)).fetchone()
                self.assertEqual(analysis_workspace.unpack(row['payload']),dict(hits=actual['_hits'],vocabulary=actual['_vocabulary'],statistics={k:v for k,v in actual.items() if not k.startswith('_')}))
                data = dict(statistics=actual,vocabulary=actual['_vocabulary'])
                for view in ('overview','forms','morphemes','roots','stems','affixes'):
                    for order in ('frequency','form'):
                        for query in ('','é','missing'):
                            request = dict(vocabulary_view=view,vocabulary_order=order,vocabulary_query=query,vocabulary_page=999)
                            profile, indices = vocabulary_statistics.page(data,request)
                            statistics, indexed, hits = analysis_counts.page(db,'run',row,request)
                            self.assertEqual(indexed,profile)
                            self.assertEqual(hits,[{**actual['_hits'][i],'index':i} for i in indices])
                item = actual['_vocabulary']['forms'][0]['key']
                request = dict(vocabulary_view='forms',vocabulary_item=item)
                profile, indices = vocabulary_statistics.page(data,request)
                _, indexed, hits = analysis_counts.page(db,'run',row,request)
                self.assertEqual(indexed,profile)
                self.assertEqual(hits,[{**actual['_hits'][i],'index':i} for i in indices])

    def test_translation_and_notes_keep_cache_across_restart_but_words_invalidate(self):
        corpus, independent = self.fixture()
        entry=self.entry('ordinary','old')
        before = self.run_stats()
        with server.connect(audit=False) as db:
            token = read_views.token(db,'statistics')
            source_fixtures.patch_values(db,'entries',corpus['id'],((('notes',), 'note'),))
            source_fixtures.patch_values(db,'dictionary_examples',independent['id'],((('translation',), 'new'),))
            source_fixtures.patch_values(db,'lexemes',entry['id'],((('usages', 0, 'senses', 0, 'short_gloss'), 'new'),))
            db.execute("UPDATE languages SET metadata=json_set(metadata,'$.homophone_phonology.assignments',json('{}')) WHERE id='ordos'")
            self.assertEqual(read_views.token(db,'statistics'), token)
            self.assertEqual(db.execute('SELECT count(*) FROM statistics_fact_dirty').fetchone()[0],0)
        self.assertTrue(self.run_stats()['cached'])
        server.init()
        self.assertTrue(self.run_stats()['cached'])
        with server.connect(audit=False) as db:
            untouched = db.execute("SELECT data FROM statistics_record_facts WHERE kind='independent' AND id=?",(independent['id'],)).fetchone()[0]
            source_fixtures.patch_values(db,'entries',corpus['id'],((('words', 1, 'form'), 'changed'),))
            self.assertEqual([tuple(r) for r in db.execute('SELECT * FROM statistics_fact_dirty')],[('corpus',corpus['id'])])
        fresh = self.run_stats()
        self.assertFalse(fresh['cached'])
        self.assertEqual(fresh['summary']['words'],before['summary']['words'])
        with server.connect(audit=False) as db:
            self.assertEqual(db.execute("SELECT data FROM statistics_record_facts WHERE kind='independent' AND id=?",(independent['id'],)).fetchone()[0],untouched)

    def test_rolled_back_preparation_and_native_type_changes_keep_exact_counts(self):
        corpus, independent = self.fixture()
        with server.connect(audit=False) as db:
            scope = corpus_statistics.normalize({})
            original = corpus_statistics.calculate(db,'ordos',scope)
        with server.connect(audit=False) as db:
            db.execute('SAVEPOINT facts_test')
            source_fixtures.patch_values(db,'morphemes',None,((('entry_type',), 'affix'), (('gloss',), 'NEW')))
            prepared = corpus_statistics.calculate(db,'ordos',scope)
            with patch.object(statistics_facts,'ready',return_value=False):
                self.assertEqual(prepared,corpus_statistics.calculate(db,'ordos',scope))
            self.assertEqual(prepared['root_words'],0)
            db.execute('ROLLBACK TO facts_test');db.execute('RELEASE facts_test')
            self.assertEqual(corpus_statistics.calculate(db,'ordos',scope),original)

    def test_changed_payload_and_deleted_runs_cannot_reuse_stale_metadata(self):
        self.fixture()
        run = self.run_stats()
        with server.connect(audit=False) as db:
            row = db.execute('SELECT * FROM analysis_runs WHERE id=?',(run['id'],)).fetchone()
            result = analysis_workspace.unpack(row['payload'])
            result['statistics']['words'] = 999
            payload = analysis_workspace.pack(result)
            db.execute('UPDATE analysis_runs SET payload=? WHERE id=?',(payload,run['id']))
            changed = db.execute('SELECT * FROM analysis_runs WHERE id=?',(run['id'],)).fetchone()
            self.assertIsNone(analysis_counts.page(db,'run',changed,{}))
            self.assertEqual(analysis_workspace.result_page(db,'ordos',dict(id=run['id']))['statistics']['words'],999)
            self.assertEqual(db.execute('SELECT count(*) FROM analysis_count_garbage').fetchone()[0],1)
            analysis_counts.reclaim(db,budget_ms=100)
            self.assertEqual(db.execute('SELECT count(*) FROM analysis_count_cache').fetchone()[0],0)

    def test_cached_runs_share_a_durable_payload_and_portable_backup_expands_it(self):
        self.fixture()
        original=self.run_stats();first=self.run_stats();second=self.run_stats()
        self.assertTrue(first['cached'] and second['cached'])
        self.assertEqual(len({original['id'],first['id'],second['id']}),3)
        expected=self.page(second)['statistics']
        with server.connect(audit=False) as db:
            self.assertEqual(db.execute('SELECT count(*) FROM analysis_run_payloads').fetchone()[0],1)
            self.assertEqual(db.execute('SELECT count(*) FROM analysis_run_references').fetchone()[0],2)
            db.execute('DELETE FROM analysis_runs WHERE id IN (?,?)',(original['id'],first['id']))
            analysis_counts.drop(db)
        self.assertEqual(self.page(second)['statistics'],expected)
        exported=self.api('backup')['analysis_runs']
        self.assertEqual([row['id'] for row in exported],[second['id']])
        self.assertEqual(analysis_workspace.unpack(exported[0]['payload'])['statistics'],expected)
        import language_exchange,project_backup,sqlite3
        from contextlib import closing
        from pathlib import Path
        with server.connect(audit=False) as db:
            package=project_backup.prepare(db,server.DB)
        source=language_exchange.staged(server.DB,package['token'],'project-backup')
        restored=Path(self.temp.name)/'statistics-restored.sqlite3'
        project_backup.restore(source,restored)
        with closing(sqlite3.connect(restored)) as db:
            payload=db.execute('SELECT payload FROM analysis_run_documents WHERE id=?',(second['id'],)).fetchone()[0]
            self.assertEqual(analysis_workspace.unpack(payload)['statistics'],expected)
        with server.connect(audit=False) as db:
            db.execute('DELETE FROM analysis_runs WHERE id=?',(second['id'],))
            self.assertEqual(db.execute('SELECT count(*) FROM analysis_run_payloads').fetchone()[0],0)

    def test_group_proof_notices_newly_resolved_members_and_external_damage(self):
        self.source('independent',[('na','N')])
        with server.connect(audit=False) as db:
            example_groups.validate_changes(db)
            with patch.object(example_groups,'validate',side_effect=AssertionError('unchanged groups rescanned')):
                example_groups.validate_changes(db)
            db.execute("INSERT INTO example_groups VALUES('bad','missing','{}',1)")
            with self.assertRaises(ValueError):
                example_groups.validate_changes(db)

    def test_external_replace_and_renamed_identity_drop_derived_snapshot_index(self):
        self.fixture()
        run=self.run_stats()
        with server.connect(audit=False) as db:
            row=dict(db.execute('SELECT * FROM analysis_runs WHERE id=?',(run['id'],)).fetchone())
            db.execute('INSERT OR REPLACE INTO analysis_runs ('+','.join(row)+') VALUES ('+','.join('?' for _ in row)+')',list(row.values()))
            self.assertIsNone(analysis_counts.indexed_row(db,'run',run['id'],'ordos'))
            result=analysis_workspace.unpack(row['payload'])
            analysis_counts.store(db,'run',row['id'],row['payload'],result)
            db.execute('UPDATE analysis_runs SET id=? WHERE id=?',('changed-id',run['id']))
            self.assertIsNone(analysis_counts.indexed_row(db,'run','changed-id','ordos'))
            self.assertEqual(db.execute('SELECT count(*) FROM analysis_count_garbage').fetchone()[0],1)
            analysis_counts.reclaim(db,budget_ms=100)
            self.assertEqual(db.execute('SELECT count(*) FROM analysis_count_cache').fetchone()[0],0)

    def test_save_list_rerun_and_page_keep_statistics_but_reject_word_changes(self):
        corpus,independent=self.fixture()
        # Existing inheritance fixtures contain legacy persisted display fields.
        # Their first normal save cleans those fields and legitimately invalidates
        # statistics; establish the ordinary, already-normalized edit path first.
        detail=self.detail(independent)
        self.api('example-save',dict(id=independent['id'],body=detail['body'],revision=detail['revision']))
        run=self.run_stats()
        before=self.page(run,vocabulary_view='forms')['vocabulary']
        with server.connect(audit=False) as db:
            original=db.execute('SELECT body,revision FROM dictionary_examples_documents WHERE id=?',(independent['id'],)).fetchone()
            data=json.loads(original['body']);revision=original['revision']
        data['translation']='changed translation'
        code,result=self.call('/api/example-save',dict(id=independent['id'],body=data,revision=revision))
        self.assertEqual(code,200,result)
        records=self.api('analysis-records?language=ordos')
        self.assertIn(run['id'],[r['id'] for r in records['recent']])
        with patch.object(corpus_statistics,'calculate',side_effect=AssertionError('valid counts recomputed')):
            fresh=self.run_stats()
        self.assertTrue(fresh['cached'])
        self.assertEqual(self.page(fresh,vocabulary_view='forms')['vocabulary'],before)
        self.assertFalse(self.page(run)['stale'])
        exported=self.api('analysis-export?language=ordos&id='+run['id'])
        self.assertEqual(exported['records']['independent:'+independent['id']]['body']['translation'],'changed translation')
        self.api('analysis-save',dict(kind='snapshot',name='valid counts',run_id=run['id']))
        self.undo()
        self.api('analysis-records?language=ordos')
        self.assertTrue(self.run_stats()['cached'])
        with server.connect(audit=False) as db:
            source_fixtures.patch_values(db,'entries',corpus['id'],((('words', 0, 'form'), 'other'),))
        self.assertNotIn(run['id'],[r['id'] for r in self.api('analysis-records?language=ordos')['recent']])
        self.assertTrue(self.page(run)['stale'])

    def test_reclamation_keeps_shared_snapshots_and_rebuilds_interrupted_index(self):
        self.fixture();run=self.run_stats()
        with server.connect(audit=False) as db:
            row=db.execute('SELECT * FROM analysis_runs WHERE id=?',(run['id'],)).fetchone()
            payload=row['payload'];result=analysis_workspace.unpack(payload);key=analysis_counts.signature(payload)
            db.execute("INSERT INTO analysis_saved VALUES('fixed','ordos','snapshot','keep','','now',? ,?)",
                       (json.dumps(dict(query=run['query'],summary=run['summary'],version=run['version'])),payload))
            analysis_counts.store(db,'saved','fixed',payload,result)
            db.execute('DELETE FROM analysis_runs WHERE id=?',(run['id'],))
            analysis_counts.reclaim(db,budget_ms=100)
            self.assertIsNotNone(analysis_counts.indexed_row(db,'saved','fixed','ordos'))
            db.execute("DELETE FROM analysis_saved WHERE id='fixed'")
            # One tiny budget leaves an unavailable header and resumable rows.
            with patch.object(analysis_counts.time,'monotonic',side_effect=[0,0,1]):
                collected=analysis_counts.reclaim(db,budget_ms=10,batch=1)
            self.assertTrue(collected['pending'])
            self.assertIsNone(db.execute('SELECT 1 FROM analysis_count_cache WHERE key=?',(key,)).fetchone())
            db.execute('INSERT INTO analysis_runs VALUES(?,?,?,?,?,?,?)',tuple(row))
            analysis_counts.store(db,'run',run['id'],payload,result,version='rebuilt')
            self.assertFalse(db.execute('SELECT 1 FROM analysis_count_garbage').fetchone())
            rebuilt=analysis_counts.indexed_row(db,'run',run['id'],'ordos')
            self.assertEqual(analysis_counts.page(db,'run',rebuilt,{})[0],result['statistics'])
            self.assertEqual(db.execute('SELECT count(*) FROM analysis_count_items WHERE key=?',(key,)).fetchone()[0],
                             sum(len(result['vocabulary'][kind]) for kind in ('forms','morphemes')))

    def test_entry_filtered_counts_reuse_sentence_metadata_but_notice_entry_notes(self):
        corpus,independent=self.fixture()
        query=dict(kind='counts',scope={},vocabulary=dict(target='morpheme',group_by='entry',
            search=dict(conditions=[dict(field='notes',op='contains',value='eligible')])) )
        original=self.api('analysis-run',dict(query=query))
        with server.connect(audit=False) as db:
            source_fixtures.patch_values(db,'dictionary_examples',independent['id'],((('translation',), 'changed'),))
        with patch.object(corpus_statistics,'calculate',side_effect=AssertionError('sentence metadata invalidated entry-only counts')):
            self.assertTrue(self.api('analysis-run',dict(query=query))['cached'])
        with server.connect(audit=False) as db:
            before=read_views.token(db,'statistics')
            source_fixtures.patch_values(db,'morphemes',None,((('notes',), 'eligible'),))
            self.assertEqual(read_views.token(db,'statistics'),before)
        fresh=self.api('analysis-run',dict(query=query));self.assertFalse(fresh['cached'])
        self.assertTrue(self.page(original)['stale'])
        self.assertGreater(self.page(fresh)['vocabulary']['total'],0)

    def test_idle_cleanup_rollback_and_engine_upgrade_do_not_publish_partial_results(self):
        self.fixture();run=self.run_stats()
        with server.connect(audit=False) as db:
            row=db.execute('SELECT * FROM analysis_runs WHERE id=?',(run['id'],)).fetchone()
            db.execute('SAVEPOINT cleanup_test')
            db.execute('DELETE FROM analysis_runs WHERE id=?',(run['id'],))
            analysis_counts.reclaim(db,budget_ms=100)
            db.execute('ROLLBACK TO cleanup_test');db.execute('RELEASE cleanup_test')
            self.assertIsNotNone(analysis_counts.indexed_row(db,'run',run['id'],'ordos'))
            self.assertTrue(analysis_workspace.current_run(db,row))
            q=json.loads(row['query']);q['engine']=-1
            self.assertFalse(analysis_workspace.current_run(db,row,q))
