import copy
import json
import unittest
import server
import manual_status
import component_links
import link_review
import test_morpheme_registry


class RetiredStatusTests(unittest.TestCase):
    setUp=test_morpheme_registry.MorphemeRegistryTests.setUp
    tearDown=test_morpheme_registry.MorphemeRegistryTests.tearDown
    call=test_morpheme_registry.MorphemeRegistryTests.call
    seed=test_morpheme_registry.MorphemeRegistryTests.seed
    entries=test_morpheme_registry.MorphemeRegistryTests.entries
    fixture=test_morpheme_registry.MorphemeRegistryTests.fixture
    link=test_morpheme_registry.MorphemeRegistryTests.link
    undo=test_morpheme_registry.MorphemeRegistryTests.undo

    def test_old_data_and_undo_migrate_without_touching_phonology(self):
        m=self.call('/api/morpheme-save',{'form':'a','body':{'notes':'田野笔记'}})[1]
        with server.connect(audit=False) as db:
            row=dict(db.execute('SELECT rowid,* FROM morphemes WHERE id=?',(m['id'],)).fetchone())
            old=json.loads(row['body']);old['status']='disputed';row['body']=json.dumps(old)
            db.execute('UPDATE morphemes SET body=? WHERE id=?',(row['body'],m['id']))
            db.execute('UPDATE undo_steps SET changes=? WHERE id=(SELECT max(id) FROM undo_steps)',(json.dumps([dict(table='morphemes',before=None,after=row)]),))
            metadata=json.loads(db.execute("SELECT metadata FROM languages WHERE id='ordos'").fetchone()[0])
            metadata['phonology_test']={'status':'pending','assignments':{'a':'confirmed'}}
            db.execute("UPDATE languages SET metadata=? WHERE id='ordos'",(json.dumps(metadata),))
            db.execute('DELETE FROM editorial_migrations')
        server.init()
        current=self.call('/api/morpheme?id='+m['id'])[1]
        self.assertNotIn('status',current['body'])
        self.assertIn('田野笔记',current['body']['notes'])
        self.assertEqual(current['body']['notes'].count(manual_status.DISPUTED_NOTE),1)
        self.assertEqual(self.undo()[0],200)
        self.assertEqual(self.undo('redo')[0],200)
        self.assertEqual(self.call('/api/morpheme?id='+m['id'])[1]['body'],current['body'])
        server.init()
        with server.connect() as db:
            self.assertEqual(json.loads(db.execute("SELECT metadata FROM languages WHERE id='ordos'").fetchone()[0])['phonology_test'],metadata['phonology_test'])

    def test_status_only_change_not_stale_but_component_edit_is(self):
        _,x=self.fixture();body=x['body']
        ref=component_links.choose(body,dict(analysis_id='a',component_id='c'))
        changed=copy.deepcopy(body)
        changed['word_structure']['analyses'][0]['status']='disputed'
        changed['word_structure']['analyses'][0]['components'][0]['status']='pending'
        self.assertFalse(component_links.review(changed,ref))
        changed=manual_status.clean(changed)
        self.assertFalse(component_links.review(changed,ref))
        changed['word_structure']['analyses'][0]['components'][0]['gloss']='修改'
        self.assertTrue(component_links.review(changed,ref))

    def test_valid_pending_link_is_used_and_concrete_review_survives_undo(self):
        e,x=self.fixture();self.assertEqual(self.link(e,x)[0],200)
        uid=e['words'][0]['morphemes'][0]['unit_id']
        self.assertEqual(self.call('/api/grammar-audit?issue=pending')[1]['total'],0)
        with server.connect() as db:
            link_review.mark(db,'unit_id=?',(uid,),'原词格形式已修改，请核对关联')
        data=self.call('/api/grammar-audit?issue=pending')[1]
        self.assertTrue(any('原词格形式已修改' in i['message'] for i in data['items']))
        self.assertEqual(self.link(e,x)[0],200)
        self.assertEqual(self.call('/api/grammar-audit?issue=pending')[1]['total'],0)
        self.assertEqual(self.undo()[0],200)
        self.assertTrue(self.call('/api/unit-dictionary?id='+uid)[1]['link']['review_reason'])

    def test_review_reasons_survive_language_exchange_and_full_backup(self):
        from pathlib import Path
        from restore_backup import restore
        from contextlib import closing
        import sqlite3
        e,x=self.fixture();self.link(e,x)
        with server.connect() as db:
            link_review.mark(db,'lexeme_id=?',(x['id'],),'原词格已修改，请核对关联')
        bundle=self.call('/api/export-language?language=ordos')[1]
        self.assertEqual(len(bundle['lexical_reviews']),1)
        lid=self.call('/api/save-language',{'name':'副本','metadata':{}})[1]['id']
        self.assertEqual(self.call('/api/import-language',{'_language':lid,'bundle':bundle})[0],200)
        source=Path(self.temp.name)/'review-backup.json'
        source.write_text(json.dumps(self.call('/api/backup')[1]),encoding='utf-8')
        destination=Path(self.temp.name)/'review-restored.sqlite3'
        restore(source,destination)
        with closing(sqlite3.connect(destination)) as db:
            self.assertEqual(db.execute('SELECT count(*) FROM lexical_reviews').fetchone()[0],2)


if __name__=='__main__':unittest.main()
