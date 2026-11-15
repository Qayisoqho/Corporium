"""Retire a native project's word mirror without changing its journal or exchange."""
from pathlib import Path
import json
import sqlite3
import unittest
from contextlib import closing
from unittest.mock import patch

import independent_links
import independent_annotations
import language_exchange
import project_backup
import server
import sentence_rows
import test_gloss_inheritance


class IndependentWordSourceTests(unittest.TestCase):
    for name in ('setUp','tearDown','api','call','example','word','link','detail','change','mode','undo'):
        locals()[name]=getattr(test_gloss_inheritance.GlossInheritanceTests,name)

    def add_old_column(self,*,damaged=False):
        # Recreate the prior native schema using the already saved source slots.
        # Reverse object key order to exercise value comparison during migration.
        with server.connect(audit=False) as db:
            db.execute("ALTER TABLE independent_words ADD COLUMN source TEXT NOT NULL DEFAULT '{}'")
            words=db.execute("""SELECT owner_id,position,form,gloss,extra
                              FROM sentence_word_rows WHERE kind='independent'""")
            copies=[(json.dumps(dict(reversed(list(sentence_rows.decode_word(row).items()))),ensure_ascii=False),
                     row['owner_id'],row['position']) for row in words]
            db.executemany('UPDATE independent_words SET source=? WHERE example_id=? AND position=?',copies)
            if damaged:
                db.execute("UPDATE independent_words SET source=json_set(source,'$.gloss','冲突') WHERE position=0")

    def journal(self,db):
        return [tuple(r) for r in db.execute('SELECT id,changes,applied FROM undo_steps ORDER BY id')]

    def research_values(self,value):
        if isinstance(value,dict):
            return {k:self.research_values(v) for k,v in value.items() if k not in ('revision','gloss_revision')}
        if isinstance(value,list):
            return [self.research_values(v) for v in value]
        return value

    def frozen_example(self):
        example=self.example([('home-n','家-GEN'),('free','')])
        whole=self.word('home-n',['家-GEN'])
        child=self.word('n',['POSS'])
        self.link(example,whole,'@word',kind='independent')
        self.link(example,child,'1:host',kind='independent')
        state=self.detail(example,'independent')
        index=next(i for i,target in enumerate(state['body']['targets']) if target['segmentation_ref']['key']=='1:host')
        self.api('segmentation-link',dict(kind='independent',id=example['id'],revision=state['revision'],remove_target=index))
        return example

    def test_existing_frozen_annotation_survives_cutover_and_history_replay(self):
        ex=self.frozen_example()
        before=self.detail(ex,'independent')
        self.add_old_column()
        with server.connect(audit=False) as db:
            history=self.journal(db)
            overlay=[tuple(r) for r in db.execute('SELECT * FROM independent_word_overrides')]
            self.assertTrue(overlay)
        server.init()
        with server.connect(audit=False) as db:
            self.assertFalse(independent_links.has_word_source(db))
            self.assertEqual(self.journal(db),history)
            self.assertEqual([tuple(r) for r in db.execute('SELECT * FROM independent_word_overrides')],overlay)
        self.assertEqual(self.detail(ex,'independent')['body'],before['body'])
        self.assertEqual(self.undo()[0],200)
        self.assertEqual(len(self.detail(ex,'independent')['body']['targets']),2)
        self.assertEqual(self.undo('redo')[0],200)
        self.assertEqual(self.research_values(self.detail(ex,'independent')['body']),self.research_values(before['body']))
        snapshots=list((server.DB.parent/'backups').glob('before-lexicon-*.sqlite3'))
        self.assertTrue(snapshots)
        with closing(sqlite3.connect(snapshots[-1])) as db:
            self.assertTrue(independent_links.has_word_source(db))

    def test_editing_another_slot_preserves_frozen_annotation(self):
        ex=self.frozen_example()
        rid=ex['id']
        before=self.detail(ex,'independent')
        self.assertEqual(before['body']['words'][0]['gloss'],'家-POSS')
        draft=self.api('annotations?kind=independent&id='+rid)
        draft['body']['words'][1]['gloss']='自由'
        self.api('inline-save',dict(**draft,before=draft['cells'],slot_ids=[w['id'] for w in draft['words']]))
        words=self.detail(ex,'independent')['body']['words']
        self.assertEqual([word['gloss'] for word in words],['家-POSS','自由'])
        self.assertEqual(words[0]['gloss_frozen'],before['body']['words'][0]['gloss_frozen'])
        self.assertEqual(words[0]['annotation_id'],before['body']['words'][0]['annotation_id'])
        with server.connect(audit=False) as db:
            self.assertFalse(db.execute("SELECT 1 FROM sentence_word_rows WHERE kind='independent' AND extra->'$.gloss_frozen' IS NOT NULL").fetchone())
            self.assertTrue(db.execute('SELECT 1 FROM independent_frozen_values WHERE owner_id=?',(rid,)).fetchone())
        self.assertEqual(self.undo()[0],200)
        self.assertEqual(self.research_values(self.detail(ex,'independent')['body']),self.research_values(before['body']))

    def test_typed_snapshot_backup_preserves_fragments_and_old_undo_images(self):
        from restore_backup import restore
        example=self.example([('h<o>me-n','家<IN>-GEN'),('free','')])
        whole=self.word('hme',['家'])
        self.link(example,whole,'0:host',kind='independent')
        before=self.detail(example,'independent')['body']
        ref=before['targets'][0]['segmentation_ref']
        self.assertEqual([fragment['text'] for fragment in ref['fragments']],['h','me'])
        with server.connect(audit=False) as db:
            self.assertFalse(db.execute("SELECT 1 FROM independent_links WHERE payload->'$.segmentation_ref' IS NOT NULL").fetchone())
            stored=db.execute('SELECT start,end,text FROM independent_link_fragments ORDER BY ordinal')
            self.assertEqual([dict(row) for row in stored],ref['fragments'])
        frozen=self.frozen_example()
        frozen_body=self.detail(frozen,'independent')['body']
        payload=self.api('backup')
        self.assertEqual(json.loads(payload['independent_links'][0]['payload'])['segmentation_ref'],ref)
        self.assertTrue(payload['independent_word_overrides'])
        source=Path(self.temp.name)/'portable-snapshots.json'
        source.write_text(json.dumps(payload,ensure_ascii=False),encoding='utf8')
        dest=Path(self.temp.name)/'portable-snapshots.sqlite3'
        restore(source,dest)
        server.DB=dest
        self.assertEqual(self.detail(example,'independent')['body'],before)
        self.assertEqual(self.detail(frozen,'independent')['body'],frozen_body)
        self.assertEqual(self.undo()[0],200)
        self.assertEqual(len(self.detail(frozen,'independent')['body']['targets']),2)
        self.assertEqual(self.undo('redo')[0],200)
        self.assertEqual(self.research_values(self.detail(frozen,'independent')['body']),self.research_values(frozen_body))

    def test_snapshot_migration_rolls_back_after_replacing_legacy_columns(self):
        server.DB=Path(self.temp.name)/'before-typed-snapshots.sqlite3'
        with patch.object(independent_annotations,'migrate',return_value=False):
            server.init()
        ex=self.frozen_example()
        before=self.detail(ex,'independent')['body']
        with server.connect(audit=False) as db:
            legacy=[tuple(row) for row in db.execute('SELECT * FROM independent_word_overrides')]
            history=self.journal(db)
            self.assertTrue(legacy)
            with patch.object(independent_annotations,'install_cleanup',side_effect=RuntimeError('test rollback')):
                with self.assertRaisesRegex(RuntimeError,'test rollback'):
                    independent_annotations.migrate(db)
            self.assertFalse(independent_annotations.enabled(db))
            self.assertEqual([tuple(row) for row in db.execute('SELECT * FROM independent_word_overrides')],legacy)
            self.assertEqual(self.journal(db),history)
        self.assertEqual(self.detail(ex,'independent')['body'],before)
        server.init()
        self.assertEqual(self.detail(ex,'independent')['body'],before)

    def test_inconsistent_copy_keeps_source_and_history(self):
        ex=self.example([('home','家')])
        self.add_old_column(damaged=True)
        with server.connect(audit=False) as db:
            original=db.execute('SELECT source FROM independent_words').fetchone()[0]
            history=self.journal(db)
        with self.assertRaisesRegex(ValueError,'独立例句词格迁移校验失败'):
            server.init()
        with server.connect(audit=False) as db:
            self.assertEqual(db.execute('SELECT source FROM independent_words').fetchone()[0],original)
            self.assertEqual(self.journal(db),history)
        self.assertEqual(self.detail(ex,'independent')['body']['words'][0]['gloss'],'家')

    def test_install_error_rolls_back_schema_and_data(self):
        self.example([('home','家')])
        self.add_old_column()
        with server.connect(audit=False) as db:
            before=[tuple(r) for r in db.execute('SELECT * FROM independent_words')]
            with patch.object(independent_links,'_install_triggers',side_effect=RuntimeError('test rollback')):
                with self.assertRaisesRegex(RuntimeError,'test rollback'):
                    independent_links.migrate_word_source(db)
            self.assertTrue(independent_links.has_word_source(db))
            self.assertEqual([tuple(r) for r in db.execute('SELECT * FROM independent_words')],before)
            self.assertFalse(db.execute("SELECT 1 FROM sqlite_master WHERE name='independent_words_new'").fetchone())

    def test_legacy_body_and_word_trigger_upgrade_together(self):
        server.DB=Path(self.temp.name)/'legacy-word-source.sqlite3'
        server.init(source_mode='legacy')
        ex=self.frozen_example()
        body=self.detail(ex,'independent')['body']
        self.add_old_column()
        with server.connect(audit=False) as db:
            db.execute('DROP TRIGGER independent_words_update')
            db.execute("""CREATE TRIGGER independent_words_update AFTER UPDATE OF body ON dictionary_examples BEGIN
                UPDATE independent_words SET source=NEW.body->('$.words['||position||']')
                WHERE example_id=NEW.id;
            END""")
        server.init()
        with server.connect(audit=False) as db:
            self.assertFalse(independent_links.has_word_source(db))
            self.assertFalse(db.execute("SELECT 1 FROM pragma_table_info('dictionary_examples') WHERE name='body'").fetchone())
        self.assertEqual(self.detail(ex,'independent')['body'],body)

    def test_old_sqlite_package_and_new_language_exchange(self):
        ex=self.frozen_example()
        before=self.detail(ex,'independent')['body']
        bundle_before=self.api('export-language?language=ordos')
        self.add_old_column()
        with server.connect(audit=False) as db:
            archive=project_backup.prepare(db,server.DB)
        path=language_exchange.staged(server.DB,archive['token'],'project-backup')
        target=Path(self.temp.name)/'restored-word-source.sqlite3'
        project_backup.restore(path,target)
        server.DB=target
        server.init()
        with server.connect(audit=False) as db:
            self.assertFalse(independent_links.has_word_source(db))
        self.assertEqual(self.detail(ex,'independent')['body'],before)
        bundle=self.api('export-language?language=ordos')
        self.assertEqual(bundle,bundle_before)
        self.assertEqual(self.undo()[0],200)
        self.assertEqual(len(self.detail(ex,'independent')['body']['targets']),2)
        self.assertEqual(self.undo('redo')[0],200)
        lid=self.api('save-language',dict(name='Imported',metadata={}))['id']
        self.api('import-language',dict(_language=lid,bundle=bundle))
        results=self.api('example-library?source=independent&language='+lid)
        self.assertEqual(results['total'],1)
        imported=self.api('segmentation?kind=independent&id='+results['items'][0]['id']+'&language='+lid)
        self.assertEqual(imported['body']['words'][0]['gloss'],'家-POSS')
