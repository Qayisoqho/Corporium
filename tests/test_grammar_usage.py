import source_fixtures
import json,unittest
from unittest.mock import patch
import grammar,grammar_usage,long_tasks,material_search_index,read_views,server
import test_grammar_candidates


class GrammarUsageTests(unittest.TestCase):
    for name in ('setUp','tearDown','call','sources','seed','entries','tag','undo'):
        locals()[name]=getattr(test_grammar_candidates.CandidateTests,name)

    def registry(self):
        code,data=self.call('/api/grammar-audit?view=registry&language=ordos')
        self.assertEqual(code,200,data);return data

    def test_ready_across_connections_and_reinitialization_never_prepares_or_writes(self):
        self.sources();self.tag('PL');expected=self.registry();server.init()
        with server.connect(audit=False) as db:
            self.assertEqual(grammar_usage.pending(db),0)
            with patch.object(grammar_usage,'prepare',side_effect=AssertionError('prepared registry rescanned')):
                self.assertEqual(grammar_usage.library(db,{'language':'ordos'}),expected)
            self.assertEqual(db.total_changes,0)

    def test_restart_reuses_persistent_counts_but_reads_current_description(self):
        self.sources();tag=self.tag('PL');expected=self.registry()
        with server.connect(audit=False) as db:
            db.execute("UPDATE grammar_tags SET description='new description' WHERE id=?",(tag['id'],))
        with patch.object(grammar_usage,'REGISTRIES',read_views.Cache(6*1024**2)),patch.object(grammar_usage,'WEIGHTS',read_views.Cache(16*1024**2)):
            with patch.object(grammar,'tokens',side_effect=AssertionError('unchanged sources reclassified')):
                actual=self.registry()
        expected['tags'][0]['description']='new description'
        self.assertEqual(actual,expected)

    def test_transactional_recipe_output_and_rollback_invalidate_process_weights(self):
        self.sources();old=self.registry()
        with server.connect(audit=False) as db:
            token=read_views.token(db,'grammar_usage');db.execute('SAVEPOINT changed')
            db.execute("UPDATE gloss_search_recipes SET output=json_set(output,'$.gloss','DU'),revision='test' WHERE id=(SELECT min(id) FROM gloss_search_recipes)")
            self.assertEqual(read_views.token(db,'grammar_usage'),token)
            changed=grammar_usage.library(db,{'language':'ordos'})
            self.assertIn('DU',{r['symbol'] for r in changed['unknown']})
            db.execute('ROLLBACK TO changed');db.execute('RELEASE changed')
            self.assertEqual(grammar_usage.library(db,{'language':'ordos'}),old)

    def test_external_source_update_prepares_only_changed_recipes_and_matches_full_audit(self):
        self.sources();self.tag('PL');self.registry()
        with server.connect(audit=False) as db:
            source_fixtures.patch_values(db,'entries',None,((('words', 0, 'gloss'), 'house-DU'),))
        actual=self.registry()
        self.assertEqual(next(t['uses'] for t in actual['tags'] if t['symbol']=='PL'),1)
        code,full=self.call('/api/grammar-audit?language=ordos');self.assertEqual(code,200,full)
        self.assertEqual(actual,{k:full[k] for k in actual})

    def test_deleted_label_projection_and_cancelled_preparation_are_recoverable(self):
        self.sources();expected=self.registry()
        with server.connect(audit=False) as db:
            db.execute('DELETE FROM grammar_usage_labels')
            pending=grammar_usage.pending(db);self.assertGreater(pending,0)
            with patch.object(grammar_usage.long_tasks,'steps',side_effect=RuntimeError('cancelled')):
                with self.assertRaisesRegex(RuntimeError,'cancelled'):
                    with material_search_index.preparing(db):grammar_usage.prepare(db)
            self.assertEqual(grammar_usage.pending(db),pending)
            self.assertEqual(grammar_usage.library(db,{'language':'ordos'}),expected)
            self.assertEqual(grammar_usage.pending(db),0)

    def test_orphan_recipe_labels_are_removed_by_identity_and_reused_ids_are_reparsed(self):
        self.sources();expected=self.registry()
        with server.connect(audit=False) as db:
            row=db.execute('SELECT body,output,revision FROM gloss_search_recipes LIMIT 1').fetchone()
            db.execute('INSERT INTO gloss_search_recipes(id,identity,body,output,revision,dirty) VALUES(999999,?,?,?,?,0)',('temporary',*row))
            grammar_usage.prepare(db)
            self.assertIsNotNone(db.execute('SELECT 1 FROM grammar_usage_labels WHERE recipe=999999').fetchone())
            db.execute('DELETE FROM gloss_search_recipes WHERE id=999999');grammar_usage.prepare(db)
            self.assertIsNone(db.execute('SELECT 1 FROM grammar_usage_labels WHERE recipe=999999').fetchone())
            self.assertEqual(grammar_usage.library(db,{'language':'ordos'}),expected)

    def test_portable_projection_drop_rebuilds_from_sources(self):
        self.sources();self.tag('PL');expected=self.registry()
        with server.connect(audit=False) as db:
            grammar_usage.drop(db);grammar_usage.initialize(db)
            self.assertEqual(grammar_usage.library(db,{'language':'ordos'}),expected)

    def test_background_registry_preparation_commits_projections_and_drains_queues(self):
        self.sources();self.tag('PL')
        generation=self.call('/api/undo-state')[1]['generation']
        with server.connect(audit=False) as db:
            bodies=[tuple(r) for r in db.execute('SELECT id,body FROM entries_documents')]
            self.assertGreater(grammar_usage.pending(db),0)
        jid=long_tasks.submit(server.DB,'grammar-audit',dict(language='ordos',view='registry'))
        long_tasks.JOBS[jid]['future'].result(timeout=20)
        state=long_tasks.view(server.DB,jid);self.assertEqual(state['state'],'done',state)
        self.assertEqual(state['result'],self.registry())
        with server.connect(audit=False) as db:
            self.assertEqual(grammar_usage.pending(db),0)
            self.assertEqual([tuple(r) for r in db.execute('SELECT id,body FROM entries_documents')],bodies)
        self.assertEqual(self.call('/api/undo-state')[1]['generation'],generation)

    def test_large_cold_registry_counts_only_requested_source_then_updates_changed_words(self):
        self.sources();self.tag('PL')
        with patch.object(grammar_usage,'COLD_OWNER_LIMIT',0):
            code,corpus=self.call('/api/grammar-audit?view=registry&language=ordos&source=corpus')
            self.assertEqual(code,200,corpus)
        with server.connect(audit=False) as db:
            self.assertIsNotNone(grammar_usage.direct_state(db))
            self.assertIsNone(db.execute('SELECT 1 FROM gloss_search_words').fetchone())
            self.assertEqual({r[0] for r in db.execute('SELECT kind FROM grammar_usage_source_dirty')},{'independent'})
        before=self.registry()
        code,full=self.call('/api/grammar-audit?language=ordos')
        self.assertEqual(code,200,full)
        self.assertEqual(before,{k:full[k] for k in before})
        with server.connect(audit=False) as db:
            source_fixtures.patch_values(db,'entries',None,((('words',0,'gloss'),'house-DU'),))
            self.assertEqual({r[0] for r in db.execute('SELECT kind FROM grammar_usage_source_dirty')},{'corpus'})
        after=self.registry()
        code,full=self.call('/api/grammar-audit?language=ordos')
        self.assertEqual(code,200,full)
        self.assertEqual(after,{k:full[k] for k in after})
        self.assertNotEqual(after,before)
    def test_cancel_before_registry_commit_restores_pending_work_and_source_rows(self):
        self.sources();before=long_tasks.committing
        def cancel(db):
            long_tasks.CURRENT.get()['cancel'].set();before(db)
        with patch.object(long_tasks,'committing',side_effect=cancel):
            jid=long_tasks.submit(server.DB,'grammar-audit',dict(language='ordos',view='registry'))
            long_tasks.JOBS[jid]['future'].result(timeout=20)
        state=long_tasks.view(server.DB,jid);self.assertEqual(state['state'],'cancelled',state)
        with server.connect(audit=False) as db:self.assertGreater(grammar_usage.pending(db),0)
        self.registry()
        with server.connect(audit=False) as db:self.assertEqual(grammar_usage.pending(db),0)
