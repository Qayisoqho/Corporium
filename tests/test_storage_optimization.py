import base64
import copy
import hashlib
import json
import sqlite3
import unittest
from pathlib import Path
from contextlib import closing
from unittest.mock import patch
import server
import journal
import storage_optimization as storage
import undo_codec as codec
import test_gloss_inheritance as inheritance


class UndoCodecTests(unittest.TestCase):
    def test_legacy_small_large_and_unicode_roundtrip(self):
        for count in (0,1,2000):
            delta=[dict(table='entries',before=None,after=dict(body='汉字 e\u0301 𝒙🙂\n"'*10,id=str(i))) for i in range(count)]
            plain=journal.encode_changes(delta);encoded=codec.encode(delta)
            self.assertEqual(codec.decode(plain),delta);self.assertEqual(codec.decode(encoded),delta)
            migrated=codec.compress_legacy(plain)
            self.assertEqual(codec.decode(migrated),delta);self.assertEqual(codec.compress_legacy(migrated),migrated)
            if len(plain)>codec.THRESHOLD:
                envelope=json.loads(migrated);self.assertEqual(envelope['sha256'],hashlib.sha256(plain).hexdigest());self.assertLess(len(encoded.encode()),len(plain)//4)
            else:self.assertIsInstance(json.loads(encoded),list)

    def test_damaged_unknown_truncated_and_length_mismatch_are_rejected(self):
        good=json.loads(codec.encode([{'body':'中'*10000}]))
        for field,value in [('sha256','0'*64),('length',1),('length',-1),('format','future'),('data','!')]:
            bad={**good,field:value}
            with self.subTest(field=field,value=value),self.assertRaises(ValueError):codec.decode(json.dumps(bad))
        raw=base64.b64decode(good['data']);bad={**good,'data':base64.b64encode(raw[:-1]).decode()}
        with self.assertRaises(ValueError):codec.decode(json.dumps(bad))

    def test_large_encoding_and_decoding_can_be_cancelled(self):
        large=[{'body':'测试'*10000} for _ in range(100)]
        encoded=codec.encode(large)
        with patch('long_tasks.checkpoint',side_effect=ValueError('cancel')):
            with self.assertRaisesRegex(ValueError,'cancel'):codec.encode(large)
            with self.assertRaisesRegex(ValueError,'cancel'):codec.decode(encoded)


class StorageMigrationTests(unittest.TestCase):
    for name in ('setUp','tearDown','call','seed','entries','undo','api','word','example','detail','link','fixture','labels','change'):
        locals()[name]=getattr(inheritance.GlossInheritanceTests,name)

    def legacy_schema(self):
        with server.connect(audit=False) as db:
            db.execute("ALTER TABLE lexical_links ADD COLUMN status TEXT DEFAULT 'confirmed'")
            db.execute("ALTER TABLE morpheme_components ADD COLUMN status TEXT DEFAULT 'confirmed'")
            db.execute("ALTER TABLE gloss_bindings ADD COLUMN form TEXT DEFAULT 'legacy duplicate'")
            db.execute('CREATE INDEX entries_text_position ON entries(text_id,position)')
            db.execute('DELETE FROM storage_migrations')

    def test_migration_keeps_bindings_bodies_ids_history_and_preupgrade_snapshot(self):
        e,ex,x=self.fixture();self.change(x,'住所')
        self.legacy_schema()
        with server.connect(audit=False) as db:
            before={t:[tuple(r) for r in db.execute('SELECT rowid,* FROM '+t+' ORDER BY rowid')] for t in ('entries','dictionary_examples','gloss_meanings')}
            history=[(r['id'],codec.decode(r['changes'])) for r in db.execute('SELECT * FROM undo_steps ORDER BY id')]
        server.init()
        with server.connect(audit=False) as db:
            for t,cols in storage.RETIRED.items():self.assertFalse(cols&{r[1] for r in db.execute('PRAGMA table_info('+t+')')})
            indexes={r[1] for r in db.execute('PRAGMA index_list(entries)')};self.assertIn('entries_text',indexes);self.assertNotIn('entries_text_position',indexes)
            for t,rows in before.items():self.assertEqual(rows,[tuple(r) for r in db.execute('SELECT rowid,* FROM '+t+' ORDER BY rowid')])
            self.assertEqual(history,[(r['id'],codec.decode(r['changes'])) for r in db.execute('SELECT * FROM undo_steps ORDER BY id')])
            self.assertFalse(storage.needed(db));self.assertEqual(db.execute('PRAGMA integrity_check').fetchone()[0],'ok')
        snapshots=list((server.DB.parent/'backups').glob('before-*.sqlite3'));self.assertTrue(snapshots)
        with closing(sqlite3.connect(snapshots[-1])) as db:self.assertIn('form',{r[1] for r in db.execute('PRAGMA table_info(gloss_bindings)')})
        self.assertEqual(self.labels(e,ex),['住所.SG','住所.SG']);self.assertEqual(self.undo()[0],200);self.assertEqual(self.labels(e,ex),['家.SG','家.SG']);self.assertEqual(self.undo('redo')[0],200)
        count=len(snapshots);server.init();self.assertEqual(len(list((server.DB.parent/'backups').glob('before-*.sqlite3'))),count)

    def test_old_row_images_with_removed_columns_undo_redo_and_json_restore(self):
        from restore_backup import restore
        e,ex,x=self.fixture();step=None
        with server.connect(audit=False) as db:
            for record in db.execute('SELECT id,changes FROM undo_steps').fetchall():
                changes=codec.decode(record['changes'])
                for c in changes:
                    for side in ('before','after'):
                        if c[side]:
                            for col in storage.RETIRED.get(c['table'],()):c[side][col]='old form' if col=='form' else 'confirmed'
                db.execute('UPDATE undo_steps SET changes=? WHERE id=?',(json.dumps(changes,ensure_ascii=False),record['id']))
        self.assertEqual(self.undo()[0],200);self.assertEqual(self.undo('redo')[0],200);self.assertEqual(self.labels(e,ex),['家.SG','家.SG'])
        backup=self.api('backup')
        for table in storage.RETIRED:
            for row in backup.get(table,[]):
                for col in storage.RETIRED[table]:row[col]='old form' if col=='form' else 'disputed'
        source=Path(self.temp.name)/'legacy.json';source.write_text(json.dumps(backup),encoding='utf8');dest=Path(self.temp.name)/'restored.sqlite3';restore(source,dest)
        server.DB=dest
        self.assertEqual(self.labels(e,ex),['家.SG','家.SG']);self.assertEqual(self.undo()[0],200);self.assertEqual(self.undo('redo')[0],200)
        with server.connect(audit=False) as db:
            import manual_status
            self.assertTrue(all(manual_status.DISPUTED_NOTE in r[0] for r in db.execute('SELECT notes FROM lexical_links')))

    def test_large_compressed_save_undo_redo_and_corrupt_history_rolls_back(self):
        e=self.seed();before=copy.deepcopy(e);value='保留全部研究笔记 e\u0301🙂\n'*10000
        self.api('save',{**e,'notes':value})
        with server.connect(audit=False) as db:
            row=db.execute('SELECT id,changes FROM undo_steps ORDER BY id DESC LIMIT 1').fetchone();stored=row['changes'];self.assertEqual(json.loads(stored)['format'],codec.FORMAT)
            bad=json.loads(stored);bad['sha256']='0'*64;db.execute('UPDATE undo_steps SET changes=? WHERE id=?',(json.dumps(bad),row['id']))
        self.assertEqual(self.undo()[0],400);self.assertEqual(self.entries()[0]['notes'],value)
        with server.connect(audit=False) as db:db.execute('UPDATE undo_steps SET changes=? WHERE id=?',(stored,row['id']))
        self.assertEqual(self.undo()[0],200);self.assertEqual(self.entries()[0].get('notes',''),before.get('notes',''));self.assertEqual(self.undo('redo')[0],200);self.assertEqual(self.entries()[0]['notes'],value)

    def test_note_coalescing_supports_compressed_history(self):
        # Exercise the actual merge path independently of note editor validation.
        with server.connect(audit=False) as db:
            first=dict(id='note',body='中'*10000);second={**first,'body':'文'*10000};third={**first,'body':'字'*10000}
            journal.record(db,{('fieldwork_notes',1):(first,second)},'编辑调查笔记')
            journal.record(db,{('fieldwork_notes',1):(second,third)},'编辑调查笔记')
            rows=list(db.execute('SELECT * FROM undo_steps'));self.assertEqual(len(rows),1)
            self.assertEqual(codec.decode(rows[0]['changes']),[dict(table='fieldwork_notes',before=first,after=third)])

    def test_malformed_legacy_payload_rolls_back_schema_and_history(self):
        self.fixture();self.legacy_schema()
        with server.connect(audit=False) as db:db.execute("UPDATE undo_steps SET changes='malformed' WHERE id=(SELECT max(id) FROM undo_steps)")
        with self.assertRaises(ValueError):
            with server.connect(audit=False) as db:storage.migrate(db)
        with server.connect(audit=False) as db:
            self.assertIn('form',{r[1] for r in db.execute('PRAGMA table_info(gloss_bindings)')});self.assertTrue(storage.needed(db))

    def test_disputed_legacy_link_is_kept_as_a_note_even_with_old_marker(self):
        self.fixture();self.legacy_schema()
        with server.connect(audit=False) as db:db.execute("UPDATE lexical_links SET status='disputed'")
        server.init()
        with server.connect(audit=False) as db:
            import manual_status
            self.assertTrue(all(manual_status.DISPUTED_NOTE in r[0] for r in db.execute('SELECT notes FROM lexical_links')))


class CompressedMediaHistoryTests(unittest.TestCase):
    import test_object_media as fixture
    for name in ('setUp','tearDown','call','word','undo','audio','add'):
        locals()[name]=getattr(fixture.ObjectMediaTests,name)

    def test_json_and_sqlite_backups_restore_media_referenced_only_by_compressed_redo(self):
        import project_backup,language_exchange,media_engine
        from restore_backup import restore
        x=self.word();caption='完整录音说明 e\u0301🙂'*400
        self.assertEqual(self.add(x,self.audio(),dict(caption=caption))[0],200)
        with server.connect(audit=False) as db:self.assertEqual(json.loads(db.execute('SELECT changes FROM undo_steps ORDER BY id DESC LIMIT 1').fetchone()[0])['format'],codec.FORMAT)
        self.assertEqual(self.undo()[0],200)
        original=server.DB
        backup=self.call('/api/backup')[1];self.assertEqual(len(backup['object_media_files']),1)
        source=Path(self.temp.name)/'compressed-media.json';source.write_text(json.dumps(backup),encoding='utf8')
        with server.connect(audit=False) as db:package=project_backup.prepare(db,server.DB)
        archive=language_exchange.staged(server.DB,package['token'],'project-backup')
        for name,file in [('json',source),('sqlite',archive)]:
            dest=Path(self.temp.name)/name/'corpus.sqlite3';dest.parent.mkdir()
            try:
                restore(file,dest);server.DB=dest;server.init();self.assertEqual(self.undo('redo')[0],200)
                item=self.call('/api/object-media?kind=lexeme&id='+x['id'])[1]['items'][0]
                path=media_engine.resolve(dest,item['asset']);self.assertTrue(path.is_relative_to(dest.parent));self.assertEqual(path.read_bytes(),self.audio().read_bytes());self.assertEqual(item['body']['caption'],caption)
            finally:server.DB=original

