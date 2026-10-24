import json
import sqlite3
import unittest
from contextlib import closing
from unittest.mock import patch
import server
import language_deletion
import test_server


class LanguageDeletionTests(unittest.TestCase):
    setUp=test_server.APITests.setUp
    tearDown=test_server.APITests.tearDown
    call=test_server.APITests.call

    def post(self,path,body):
        status,result=self.call('/api/'+path,body)
        self.assertEqual(status,200,result)
        return result

    def seed(self,lid='ordos'):
        return self.post('import',dict(title='材料',content='#pass([ipa], (([word],[NOM]),), [翻译])',_language=lid))['id']

    def preview(self,lid='ordos'):
        language=next(r for r in self.call('/api/languages')[1] if r['id']==lid)
        return self.post('language-delete-preview',dict(id=lid,revision=language['revision'],_language=lid))

    def delete(self,p,**kw):
        return self.call('/api/delete-language',dict(id=p['id'],revision=p['revision'],token=p['token'],_language=p['id'],confirmed=True,**kw))

    def test_nonempty_delete_backup_and_other_language_undo(self):
        other=self.post('save-language',dict(name='保留',metadata={}))['id']
        self.seed();self.seed(other)
        p=self.preview();self.assertEqual(p['counts']['entries'],1);self.assertEqual(p['blockers'],[])
        with server.connect(audit=False) as db:
            before={t:[tuple(r) for r in db.execute('SELECT * FROM '+t)] for t in ('languages','entries','texts','undo_steps')}
            kept=[tuple(r) for r in db.execute('SELECT * FROM texts WHERE language_id=?',(other,))]
            kept_units=[tuple(r) for r in db.execute('SELECT u.* FROM corpus_units u JOIN entries e ON e.id=u.entry_id JOIN texts t ON t.id=e.text_id WHERE t.language_id=?',(other,))]
        status,r=self.delete(p);self.assertEqual(status,200,r)
        with closing(sqlite3.connect(server.DB.parent/'backups'/r['backup'])) as db:
            for table,rows in before.items():self.assertEqual(list(db.execute('SELECT * FROM '+table)),rows)
        with server.connect(audit=False) as db:
            self.assertEqual([tuple(r) for r in db.execute('SELECT * FROM texts')],kept)
            self.assertFalse(db.execute("SELECT 1 FROM languages WHERE id='ordos'").fetchone())
            self.assertFalse(db.execute('PRAGMA foreign_key_check').fetchone())
            self.assertCountEqual([tuple(r) for r in db.execute('SELECT * FROM corpus_units')],kept_units)
        state=self.call('/api/undo-state?language='+other)[1]
        self.post('undo',dict(_language=other,generation=state['generation']))
        server.init()
        self.assertEqual([r['id'] for r in self.call('/api/languages')[1]],[other])

    def test_last_language_can_be_deleted_and_recreated_after_restart(self):
        p=self.preview();status,result=self.delete(p);self.assertEqual(status,200,result)
        self.assertEqual(result['next_language'],'all')
        server.init();self.assertEqual(self.call('/api/languages')[1],[])
        self.assertEqual(self.call('/api/entries?language=all')[1]['total'],0)
        new=self.post('save-language',dict(name='新语言',metadata={},_language='all'))['id']
        self.seed(new);server.init()
        self.assertEqual([r['id'] for r in self.call('/api/languages')[1]],[new])

    def test_confirm_scope_and_stale_preview_are_required(self):
        p=self.preview()
        for body in ({'confirmed':False},{'confirmed':1},{'token':''},{'_language':'all'}):
            b=dict(id=p['id'],revision=p['revision'],token=p['token'],_language=p['id'],confirmed=True);b.update(body)
            self.assertEqual(self.call('/api/delete-language',b)[0],400)
        self.seed();self.assertEqual(self.delete(p)[0],400)
        self.assertEqual(len(self.call('/api/languages')[1]),1)
        self.assertFalse((server.DB.parent/'backups').exists())

    def test_other_language_mixed_sentence_blocks_and_prose_does_not(self):
        other=self.post('save-language',dict(name='保留',metadata={}))['id'];self.seed(other)
        entry=self.call('/api/entries?language='+other)[1]['items'][0]
        self.post('save',{**entry,'language_id':'ordos','notes':'','_language':other})
        p=self.preview();self.assertTrue(p['blockers']);self.assertEqual(self.delete(p)[0],400)
        entry=self.call('/api/entries?language='+other)[1]['items'][0]
        self.post('save',{**entry,'language_id':'','translation':'ordos','notes':'ordos','_language':other})
        p=self.preview();self.assertFalse(p['blockers']);self.assertEqual(self.delete(p)[0],200)
        self.assertEqual(self.call('/api/entries?language='+other)[1]['items'][0]['translation'],'ordos')
        # A previous saved mixed-language version must not be resurrected by undo.
        with server.connect(audit=False) as db:
            for row in db.execute('SELECT changes FROM undo_steps'):
                for c in server.journal.decode_changes(row[0]):
                    for r in (c.get('before'),c.get('after')):
                        if r:self.assertFalse(language_deletion.references(r,set(),'ordos'))

    def test_backup_failure_and_sql_failure_roll_back(self):
        self.seed();p=self.preview()
        with patch('language_deletion.backup_policy.write',side_effect=OSError('备份失败')):
            self.assertEqual(self.delete(p)[0],400)
        with server.connect(audit=False) as db:
            db.execute("CREATE TRIGGER reject_language_delete BEFORE DELETE ON languages BEGIN SELECT RAISE(ABORT,'test rollback'); END")
        self.assertEqual(self.delete(p)[0],400)
        self.assertEqual(self.call('/api/entries?language=ordos')[1]['total'],1)
        self.assertEqual(len(self.call('/api/languages')[1]),1)

    def test_reference_predicate_parses_nested_history_and_ignores_prose(self):
        self.assertTrue(language_deletion.references({'body':json.dumps({'targets':[{'lexeme_id':'x'}]})},{'x'},'ordos'))
        self.assertFalse(language_deletion.references({'body':json.dumps({'translation':'ordos','notes':'x'})},{'x'},'ordos'))
        self.assertTrue(language_deletion.references({'metadata':json.dumps({'workspace_language_id':'ordos'})},set(),'ordos'))
        self.assertTrue(language_deletion.references({'features':json.dumps(['tag-id'])},{'tag-id'},'ordos'))
        self.assertFalse(language_deletion.references({'body':json.dumps({'forms':[{'features':['other-tag']}]})},{'tag-id'},'ordos'))

    def test_linked_dictionary_examples_gloss_and_annotations_are_removed(self):
        from test_gloss_inheritance import GlossInheritanceTests
        helper=GlossInheritanceTests();e,ex,x=helper.fixture()
        from test_annotations import AnnotationTests
        annotator=AnnotationTests();layer=annotator.layer()
        annotator.annotate('corpus',e,layer);annotator.annotate('independent',ex,layer)
        self.post('morpheme-save',dict(form='-s',body={}))
        p=self.preview()
        self.assertGreater(p['counts']['gloss_bindings'],0);self.assertGreater(p['counts']['gloss_meanings'],0)
        self.assertEqual(p['blockers'],[])
        status,result=self.delete(p);self.assertEqual(status,200,result)
        with server.connect(audit=False) as db:
            for table in language_deletion.PREDICATES:
                self.assertEqual(db.execute('SELECT count(*) FROM '+table).fetchone()[0],0,table)

    def test_global_catalogue_is_preserved_and_workspace_mapping_blocks(self):
        with server.connect(audit=False) as db:
            db.execute("INSERT INTO timeline_codes(id,name,metadata) VALUES('shared','共用标记',?)",(json.dumps({'workspace_language_id':'ordos'}),))
            db.execute("INSERT INTO timeline_speakers(id,name,metadata) VALUES('person','共用合作者','{}')")
        p=self.preview();self.assertTrue(p['blockers']);self.assertEqual(self.delete(p)[0],400)
        with server.connect(audit=False) as db:db.execute("UPDATE timeline_codes SET metadata='{}'")
        self.assertEqual(self.delete(self.preview())[0],200)
        with server.connect(audit=False) as db:
            self.assertEqual(db.execute('SELECT name FROM timeline_codes').fetchone()[0],'共用标记')
            self.assertEqual(db.execute('SELECT name FROM timeline_speakers').fetchone()[0],'共用合作者')

    def test_old_orphaned_units_and_links_do_not_prevent_language_deletion(self):
        from test_gloss_inheritance import GlossInheritanceTests
        helper=GlossInheritanceTests();e,ex,x=helper.fixture()
        with server.connect(audit=False) as db:
            db.execute('DELETE FROM gloss_bindings WHERE owner_id=?',(e['id'],))
            db.execute('DELETE FROM entries WHERE id=?',(e['id'],))
            db.execute('UPDATE corpus_units SET active=0 WHERE entry_id=?',(e['id'],))
        p=self.preview();self.assertEqual(p['blockers'],[])
        status,result=self.delete(p);self.assertEqual(status,200,result)
        with server.connect(audit=False) as db:
            self.assertFalse(db.execute('SELECT 1 FROM lexical_links').fetchone())
            self.assertFalse(db.execute('SELECT 1 FROM corpus_units').fetchone())


if __name__=='__main__':unittest.main()
