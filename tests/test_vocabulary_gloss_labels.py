import json
import unittest
from unittest.mock import patch

import analysis_workspace
import server
import statistics_facts
import test_vocabulary_selection as selection_tests
import test_vocabulary_statistics as vocabulary_tests


class VocabularyGlossTests(unittest.TestCase):
    for name in ('setUp','tearDown','call','api','source','detail','args','entry','undo','bind','page','run_stats'):
        locals()[name] = getattr(vocabulary_tests.VocabularyTests, name)
    for name in ('run_selection','profile'):
        locals()[name] = getattr(selection_tests.SelectionTests, name)

    def marker(self, **extra):
        return self.api('morpheme-save', dict(form='ka', body=dict(gloss='', gloss_addition='PL', **extra)))

    def rows(self, run):
        return self.page(run, vocabulary_view='morphemes')['vocabulary']['rows']

    def test_label_only_gloss_in_facts_filter_export_snapshot_and_undo(self):
        m = self.marker()
        for kind in ('corpus','independent'):
            self.bind(self.source(kind, [('ka','PL')]), m)
        run = self.run_stats()
        self.assertEqual([(r['gloss'],r['count']) for r in self.rows(run)], [('PL',2)])
        filtered = self.page(run, vocabulary_view='morphemes', vocabulary_query='PL')['vocabulary']
        self.assertEqual(filtered['total'], 1)
        snapshot = self.api('analysis-save', dict(kind='snapshot', name='Labels', run_id=run['id']))
        m = self.api('morpheme?id='+m['id'])
        self.api('morpheme-save', dict(id=m['id'], revision=m['revision'], form=m['form'], body={**m['body'],'show_gloss_addition':False}))
        self.assertEqual(self.rows(self.run_stats())[0]['gloss'], '')
        self.assertEqual(self.page(snapshot, snapshot='true', vocabulary_view='morphemes')['vocabulary']['rows'][0]['gloss'], 'PL')
        self.undo()
        fresh = self.run_stats()
        self.assertEqual(self.rows(fresh)[0]['gloss'], 'PL')
        export = self.api('analysis-export?id='+fresh['id']+'&language=ordos')
        self.assertEqual(export['vocabulary']['morphemes'][0]['gloss'], 'PL')

    def test_custom_entry_meanings_include_labels_and_respect_display_switch(self):
        m = self.marker()
        self.bind(self.source('independent', [('ka','PL')]), m)
        self.assertEqual(self.profile(self.run_selection())['rows'][0]['gloss'], 'PL')
        x = self.api('lexeme-save', dict(headword='la', body=dict(usages=[dict(pos='', senses=[dict(short_gloss='',gloss_addition='SG'),dict(short_gloss='second')])])) )
        source = self.source('corpus', [('la','SG')])
        usage=x['body']['usages'][0]
        self.api('segmentation-link', dict(**self.args(source),word=0,key='@word',link_revision=0,lexeme_id=x['id'],lexeme_revision=x['revision'],usage_id=usage['id'],sense_id=usage['senses'][0]['id']))
        self.assertEqual(self.profile(self.run_selection(target='lexeme'))['rows'][0]['gloss'], 'SG')

    def test_free_gloss_and_labels_use_existing_join_and_deduplication_rules(self):
        m=self.api('morpheme-save',dict(form='pron',body=dict(gloss='3',gloss_addition='SG')))
        self.bind(self.source('corpus',[('pron','3SG')]),m)
        self.assertEqual(self.rows(self.run_stats())[0]['gloss'],'3SG')
        self.assertEqual(self.profile(self.run_selection())['rows'][0]['gloss'],'3SG')

    def test_old_derived_facts_rebuild_and_old_snapshots_remain_frozen(self):
        m=self.marker()
        self.bind(self.source('corpus',[('ka','PL')]),m)
        with patch.object(analysis_workspace,'VERSION',analysis_workspace.VERSION-1):
            old=self.run_stats()
            snap=self.api('analysis-save',dict(kind='snapshot',name='Old snapshot',run_id=old['id']))
        with server.connect(audit=False) as db:
            db.execute('UPDATE statistics_fact_state SET version=?',(statistics_facts.VERSION-1,))
            for row in db.execute('SELECT kind,id,data FROM statistics_record_facts').fetchall():
                data=json.loads(row['data'])
                for item in data['morphemes']:item['gloss']='obsolete'
                db.execute('UPDATE statistics_record_facts SET data=? WHERE kind=? AND id=?',(json.dumps(data),row['kind'],row['id']))
            statistics_facts.initialize(db)
        self.assertTrue(self.page(old)['stale'])
        self.assertFalse(self.page(snap,snapshot='true')['stale'])
        self.assertEqual(self.rows(self.run_stats())[0]['gloss'],'PL')
