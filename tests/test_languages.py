import json
import sqlite3
import unittest
from pathlib import Path
import server
import test_server
from restore_backup import restore


class LanguageTests(unittest.TestCase):
    setUp=test_server.APITests.setUp
    tearDown=test_server.APITests.tearDown
    call=test_server.APITests.call

    def language(self,name='Other'):
        code,result=self.call('/api/save-language',{'name':name,'metadata':{}})
        self.assertEqual(code,200,result)
        return result['id']

    def test_catalogue_recovers_from_previous_project_language(self):
        code,rows=self.call('/api/languages?language=previous-project-only-id')
        self.assertEqual(code,200,rows)
        self.assertTrue(any(r['id']=='ordos' for r in rows))
        # Actual scoped data still rejects unknown language IDs.
        self.assertEqual(self.call('/api/lexemes?language=previous-project-only-id')[0],400)

    def test_typography_variants(self):
        metadata={'ipa_font':'IPAPANNEW','annotation_font':'Junicode','ipa_variant':'regular','morpheme_variant':'bolditalic'}
        code,result=self.call('/api/save-language',{'name':'Typography','metadata':metadata})
        self.assertEqual(code,200,result)
        with server.connect() as db:
            saved=json.loads(db.execute('SELECT metadata FROM languages WHERE id=?',(result['id'],)).fetchone()[0])
        self.assertEqual(saved,metadata)
        for invalid in ('invalid',None,123,{}):
            code,_=self.call('/api/save-language',{'name':'Invalid','metadata':{**metadata,'ipa_variant':invalid}})
            self.assertEqual(code,400)

    def seed(self,lid='ordos'):
        code,result=self.call('/api/import',{'title':'Same title','content':'#pass([ipa], (([word],[GEN]),), [translation])','_language':lid})
        self.assertEqual(code,200,result)
        return result['id']

    def command(self,kind,lid):
        state=self.call('/api/undo-state?language='+lid)[1]
        code,result=self.call('/api/'+kind,{'generation':state['generation'],'_language':lid})
        self.assertEqual(code,200,result)
        return result

    def test_same_source_independent_filters_and_undo(self):
        other=self.language();a=self.seed();b=self.seed(other)
        self.assertNotEqual(a,b)
        self.assertEqual(self.call('/api/texts?language='+other)[1][0]['id'],b)
        self.assertEqual(self.call('/api/entries?language=ordos')[1]['total'],1)
        self.assertEqual(self.call('/api/entries?language=all')[1]['total'],2)
        self.command('undo','ordos')
        self.assertEqual(self.call('/api/entries?language='+other)[1]['total'],1)
        self.command('undo',other)
        self.command('redo','ordos')
        self.assertEqual(self.call('/api/entries?language=ordos')[1]['total'],1)
        self.assertEqual(self.call('/api/entries?language='+other)[1]['total'],0)
        self.command('redo',other)
        self.assertEqual(self.call('/api/entries?language=all')[1]['total'],2)

    def test_rowid_reuse_does_not_delete_other_language(self):
        a=self.seed();other=self.language()
        self.command('undo','ordos')
        b=self.seed(other)
        self.command('redo','ordos')
        self.assertEqual({t['id'] for t in self.call('/api/texts')[1]},{a,b})
        self.command('undo','ordos')
        self.assertEqual(self.call('/api/texts')[1][0]['id'],b)

    def test_cross_language_organization_is_rejected(self):
        other=self.language();a=self.seed();b=self.seed(other)
        entry=self.call('/api/entries?text='+a)[1]['items'][0]
        code,result=self.call('/api/move',{'source_id':a,'target_id':b,'ids':[entry['id']],'where':'end'})
        self.assertEqual(code,400)
        self.assertEqual(self.call('/api/merge',{'first_id':a,'second_id':b,'title':'bad','counts':[1,1]})[0],400)
        folder=self.call('/api/save-folder',{'name':'Other folder','metadata':{},'_language':other})[1]['id']
        self.assertEqual(self.call('/api/save-text-info',{'id':a,'title':'A','revision':0,'folder_id':folder,'metadata':{}})[0],400)
        self.assertEqual(self.call('/api/folders?language=ordos')[1],[])

    def test_mixed_sentence_rules_settings_and_export(self):
        other=self.language();a=self.seed()
        entry=self.call('/api/entries')[1]['items'][0]
        self.assertEqual(self.call('/api/save',{**entry,'notes':'','language_id':other,'language_notes':'quotation'})[0],200)
        code,result=self.call('/api/save-language',{'id':other,'revision':1,'name':'Other','metadata':{'glossary':{'DAT':'dative'},'check_glossary':True,'ipa_font':'Junicode'},'_language':other})
        self.assertEqual(code,200,result)
        e=self.call('/api/entries?language=all&sentence_language='+other)[1]['items'][0]
        self.assertEqual(e['effective_language_id'],other)
        self.assertEqual(e['language_fonts']['ipa'],'Junicode')
        self.assertTrue(any('GEN' in w for w in e['warnings']))
        bundle=self.call('/api/export-language?language=ordos')[1]
        self.assertEqual(bundle['referenced_languages'][0]['id'],other)
        dest=self.language('Third')
        code,result=self.call('/api/import-language',{'bundle':bundle,'_language':dest})
        self.assertEqual(code,200,result)
        copied=self.call('/api/entries?language='+dest)[1]['items'][0]
        self.assertEqual(copied['language_id'],other)
        self.assertEqual(copied['language_notes'],'quotation')
        self.command('undo',dest)
        self.assertEqual(self.call('/api/texts?language='+dest)[1],[])
        self.command('undo',other)
        self.assertFalse(self.call('/api/entries?language=ordos')[1]['items'][0]['warnings'])

    def test_multilingual_backup_restore(self):
        other=self.language();self.seed();self.seed(other)
        self.command('undo','ordos')
        path=Path(self.temp.name)/'backup.json'
        path.write_text(json.dumps(self.call('/api/backup')[1]),encoding='utf-8')
        dest=Path(self.temp.name)/'restored.db';restore(path,dest);server.DB=dest
        self.command('redo','ordos')
        self.assertEqual(len(self.call('/api/languages')[1]),2)
        self.assertEqual(self.call('/api/entries')[1]['total'],2)

    def test_legacy_migration_preserves_records_and_backup(self):
        # Simulate the pre-language database schema and an existing legacy digest.
        tid=self.seed()
        before=self.call('/api/entries')[1]['items'][0]['translation']
        with server.connect() as db:
            db.execute('DROP TABLE languages')
            db.execute('DROP TABLE undo_scopes')
            db.execute('DROP INDEX texts_language')
            db.execute('DROP INDEX folders_language')
            db.execute('DROP INDEX undo_language')
            for table in ('texts','folders','undo_steps'):
                db.execute('ALTER TABLE '+table+' DROP COLUMN language_id')
            db.execute('UPDATE undo_settings SET step_limit=10')
        self.assertTrue(server.DB.exists())
        server.init()
        self.assertEqual(self.call('/api/languages')[1][0]['id'],'ordos')
        self.assertEqual(self.call('/api/texts?language=ordos')[1][0]['id'],tid)
        self.assertEqual(self.call('/api/entries')[1]['items'][0]['translation'],before)
        self.assertEqual(self.call('/api/undo-state?language=ordos')[1]['step_limit'],10)
        self.command('undo','ordos')
        self.assertEqual(self.call('/api/entries')[1]['total'],0)
        self.assertTrue(list((server.DB.parent/'backups').glob('before-languages-*.sqlite3')))

    def test_scoped_limits_and_redo_branch(self):
        other=self.language();self.seed();self.seed(other)
        self.command('undo',other)
        entry=self.call('/api/entries?language=ordos')[1]['items'][0]
        self.call('/api/save',{**entry,'notes':'a new change','_language':'ordos'})
        self.assertIsNotNone(self.call('/api/undo-state?language='+other)[1]['redo'])
        state=self.call('/api/undo-state?language='+other)[1]
        self.call('/api/undo-limit',{'_language':other,'generation':state['generation'],'limit':10})
        self.assertEqual(self.call('/api/undo-state?language=ordos')[1]['step_limit'],20)
        self.assertEqual(self.call('/api/undo-state?language='+other)[1]['step_limit'],10)
