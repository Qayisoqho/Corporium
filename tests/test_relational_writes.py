import json
import unittest
from pathlib import Path
from unittest.mock import patch

import dictionary_rows
import journal
import record_sources
import server
import source_schema
import test_server
from restore_backup import restore


class RelationalWriteTests(unittest.TestCase):
    setUp = test_server.APITests.setUp
    tearDown = test_server.APITests.tearDown
    call = test_server.APITests.call

    def api(self,route,payload=None):
        status,result=self.call('/api/'+route,payload)
        self.assertEqual(status,200,result)
        return result

    def undo(self,direction='undo'):
        self.api(direction,{'generation':self.api('undo-state')['generation']})

    def target(self):
        return self.api('lexeme-save',dict(headword='mala',body=dict(
            usages=[dict(id='u',pos='N',senses=[dict(id='s',short_gloss='石',definition='石头')])],
            variants=[dict(id='v',form='malaŋ',variation='unknown',kind='other')],
            word_structure=dict(analyses=[dict(id='a',title='切分',level='synchronic',
                components=[dict(id='c',form='mala',gloss='石')])]))))

    def read_source(self,table,owner):
        with server.connect(audit=False) as db:
            return record_sources.read(db,table,owner)

    def step(self,table):
        with server.connect(audit=False) as db:
            step=journal.state(db)['undo']
            changes=journal.decode_changes(db.execute('SELECT changes FROM undo_steps WHERE id=?',(step['id'],)).fetchone()[0])
        return next(c for c in changes if c['table']==table)

    def test_linked_corpus_undo_keeps_original_body_without_display_fields(self):
        target=self.target()
        text=self.api('import',dict(title='Corpus',content='#pass([mala], (([mala],[石]),([pa],[旧]),), [译文])'))
        owner=self.api('entries?text='+text['id'])['items'][0]['id']
        d=self.api('segmentation?kind=corpus&id='+owner)
        self.api('segmentation-link',dict(kind='corpus',id=owner,revision=d['revision'],word=0,key='@word',
            lexeme_id=target['id'],lexeme_revision=target['revision'],usage_id='u',sense_id='s',link_revision=0))
        with server.connect(audit=False) as db:
            old=record_sources.read(db,'entries',owner)
            old.pop('_gloss_active_bindings',None);old.pop('gloss_revision',None)
            old['words'][1]={k:v for k,v in old['words'][1].items() if k in ('form','gloss','form_kind','gloss_kind')}
            raw=json.dumps(old,ensure_ascii=False)
            record_sources.write(db,'entries',owner,old,bump=False)
        draft=self.api('annotations?kind=corpus&id='+owner)
        draft['body']['words'][0]['form']='malaj'
        draft.update(before=draft['cells'],slot_ids=[w['id'] for w in draft['words']])
        loads=json.loads
        def reject_complete_source(value,*args,**kwargs):
            self.assertNotEqual(value,raw)
            return loads(value,*args,**kwargs)
        with patch('json.loads',side_effect=reject_complete_source):
            self.api('inline-save',draft)
        self.assertEqual(self.step('entries')['before']['body'],old)
        self.assertEqual(self.read_source('entries',owner)['words'][0]['form'],'malaj')
        self.undo()
        self.assertEqual(self.read_source('entries',owner),old)
        with server.connect(audit=False) as db:
            self.assertNotIn('body',{r[1] for r in db.execute('PRAGMA table_info(entries)')})
        self.undo('redo')
        self.assertEqual(self.read_source('entries',owner)['words'][0]['form'],'malaj')

    def test_dictionary_definition_variant_and_construction_are_written_and_restored_as_values(self):
        target=self.target()
        owner=target['id']
        before=self.read_source('lexemes',owner)
        target['body']['usages'][0]['senses'][0]['definition']='新释义'
        target['body']['variants'][0]['notes']='变体证据'
        target['body']['word_structure']['analyses'][0]['components'][0]['gloss']='组分标注'
        self.api('lexeme-save',target)
        with server.connect(audit=False) as db:
            value=dictionary_rows.raw_bodies(db,'lexeme',[owner])[owner]
            self.assertEqual(value['usages'][0]['senses'][0]['definition'],'新释义')
            self.assertEqual(value['variants'][0]['notes'],'变体证据')
            self.assertEqual(value['word_structure']['analyses'][0]['components'][0]['gloss'],'组分标注')
            self.assertTrue(db.execute("SELECT 1 FROM independent_dictionary_keys WHERE target_id=? AND kind='form' AND key='v'",(owner,)).fetchone())
        self.assertEqual(self.step('lexemes')['before']['body'],before)
        self.undo()
        self.assertEqual(self.read_source('lexemes',owner),before)
        self.undo('redo')
        self.assertEqual(self.read_source('lexemes',owner),value)
        # A dependent example blocks deletion of the referenced sense.
        self.api('example-save',dict(body=dict(original='例句',words=[],
            targets=[dict(lexeme_id=owner,usage_id='u',sense_id='s',form_id='v')])))
        draft=self.api('lexeme?id='+owner)
        draft['body']['usages'][0]['senses']=[]
        status,_=self.call('/api/lexeme-save',draft)
        self.assertEqual(status,400)
        self.assertEqual(self.read_source('lexemes',owner),value)
        with server.connect(audit=False) as db:
            self.assertNotIn('body',{r[1] for r in db.execute('PRAGMA table_info(lexemes)')})
            self.assertEqual(db.execute('SELECT count(*) FROM record_source_writes').fetchone()[0],0)

    def test_existing_backup_format_restores_independent_body_and_undo(self):
        example=self.api('example-save',dict(body=dict(original='旧原文',words=[dict(form='ma',gloss='原注')])))
        owner=example['id']
        old=self.read_source('dictionary_examples',owner)
        draft=self.api('independent-example?id='+owner)
        draft['body']['words'][0]['gloss']='新注'
        self.api('example-save',draft)
        self.assertIsInstance(self.step('dictionary_examples')['after']['body'],dict)
        package=self.api('backup')
        step=journal.decode_changes(package['undo_steps'][-1]['changes'])
        self.assertIsInstance(next(c['after']['body'] for c in step if c['table']=='dictionary_examples'),str)
        path=Path(self.temp.name)/'old-format.json'
        path.write_text(json.dumps(package,ensure_ascii=False),encoding='utf-8')
        destination=Path(self.temp.name)/'restored.sqlite3'
        restore(path,destination)
        with patch.object(server,'DB',destination):
            self.assertEqual(self.read_source('dictionary_examples',owner)['words'][0]['gloss'],'新注')
            self.undo()
            self.assertEqual(self.read_source('dictionary_examples',owner),old)

    def test_old_project_cutover_keeps_undo_and_exchange_through_each_stage(self):
        import language_exchange
        import project_backup

        server.DB=Path(self.temp.name)/'legacy.sqlite3'
        server.init(source_mode='legacy')
        target=self.target()
        text=self.api('import',dict(title='Corpus',content='#pass([mala], (([mala],[石]),), [译文])'))
        eid=self.api('entries?text='+text['id'])['items'][0]['id']
        example=self.api('example-save',dict(body=dict(original='例句',words=[],
            targets=[dict(lexeme_id=target['id'],usage_id='u',sense_id='s',form_id='v')])))
        owner=target['id']
        old=self.read_source('lexemes',owner)
        target['body']['usages'][0]['senses'][0]['definition']='旧版编辑'
        self.api('lexeme-save',target)
        changed=self.read_source('lexemes',owner)
        with server.connect(audit=False) as db:
            step=db.execute('SELECT * FROM undo_steps ORDER BY id DESC LIMIT 1').fetchone()
            db.execute('UPDATE undo_steps SET changes=? WHERE id=?',(journal.portable_step(step)['changes'],step['id']))
            images={table:record_sources.backup_rows(db,table) for table in record_sources.KINDS}
        with server.connect(audit=False) as db:
            archived=project_backup.prepare(db,server.DB)
        archive=language_exchange.staged(server.DB,archived['token'],'project-backup')
        restored=Path(self.temp.name)/'restored-v1.sqlite3'
        restore(archive,restored)
        with patch.object(server,'DB',restored):
            server.init()
            self.assertEqual(self.read_source('lexemes',owner),changed)
            self.undo();self.assertEqual(self.read_source('lexemes',owner),old)
        server.init(source_mode='dual')
        with server.connect(audit=False) as db:
            self.assertEqual(images,{table:record_sources.backup_rows(db,table) for table in record_sources.KINDS})
        self.undo();self.assertEqual(self.read_source('lexemes',owner),old)
        self.undo('redo');self.assertEqual(self.read_source('lexemes',owner),changed)
        self.assertEqual(self.api('dictionary-examples?paged=1&id='+owner)['total'],1)
        bundle=self.api('export-language?language=ordos')
        self.assertEqual(json.loads(bundle['texts'][0]['entries'][0]['body'])['translation'],'译文')
        self.assertEqual(bundle['dictionary_examples'][0]['id'],example['id'])
        server.init(source_mode='single')
        with server.connect(audit=False) as db:
            mirror=db.execute('SELECT body FROM lexemes WHERE id=?',(owner,)).fetchone()[0]
        target=self.api('lexeme?id='+owner)
        target['body']['notes']='关系表备注'
        self.api('lexeme-save',target)
        with server.connect(audit=False) as db:
            self.assertEqual(db.execute('SELECT body FROM lexemes WHERE id=?',(owner,)).fetchone()[0],mirror)
        self.assertEqual(self.read_source('lexemes',owner)['notes'],'关系表备注')
        self.undo();self.assertEqual(self.read_source('lexemes',owner),changed)
        server.init()
        server.init()
        with server.connect(audit=False) as db:
            source_schema.validate_relations(db)
            for table in record_sources.KINDS:
                self.assertNotIn('body',{r[1] for r in db.execute('PRAGMA table_info('+table+')')})
        self.undo('redo')
        self.assertEqual(self.read_source('lexemes',owner)['notes'],'关系表备注')
        self.assertEqual(self.api('entries?q=mala&field=form')['items'][0]['id'],eid)
        self.assertTrue(list((server.DB.parent/'backups').glob('before-lexicon-*.sqlite3')))

    def test_mismatched_relational_rows_abort_before_removing_original_columns(self):
        server.DB=Path(self.temp.name)/'damaged-copy.sqlite3'
        server.init(source_mode='legacy')
        word=self.target()
        with server.connect(audit=False) as db:
            original=db.execute('SELECT body FROM lexemes WHERE id=?',(word['id'],)).fetchone()[0]
            db.execute("UPDATE dictionary_value_rows SET value='不一致的副本' WHERE target_id=? AND slot='definition'",(word['id'],))
        with self.assertRaisesRegex(ValueError,'正文迁移校验失败'):
            server.init()
        with server.connect(audit=False) as db:
            self.assertEqual(record_sources.mode(db),'legacy')
            self.assertEqual(db.execute('SELECT body FROM lexemes WHERE id=?',(word['id'],)).fetchone()[0],original)
            for table in record_sources.KINDS:
                self.assertIn('body',{r[1] for r in db.execute('PRAGMA table_info('+table+')')})
        self.assertTrue(list((server.DB.parent/'backups').glob('before-lexicon-*.sqlite3')))
