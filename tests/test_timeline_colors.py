import undo_codec
import json
import sqlite3
import unittest
from contextlib import closing
from pathlib import Path

import server
import timeline
import timeline_colors
import test_timeline as base
from restore_backup import restore


class TimelineColorTests(unittest.TestCase):
    setUp=base.TimelineTests.setUp
    tearDown=base.TimelineTests.tearDown
    call=base.TimelineTests.call
    detail=base.TimelineTests.detail
    mutation=base.TimelineTests.mutation
    undo=base.TimelineTests.undo

    def test_saved_colors_survive_add_delete_reorder_and_legacy_rename(self):
        root=self.detail()['tracks'][0]
        self.assertEqual(root['color'],timeline_colors.PALETTE[0])
        self.assertEqual(self.mutation('track',track_id=root['id'],name='自选',color='#F012AB')[0],200)
        self.assertEqual(self.mutation('track',name='另一轨道',kind='event')[0],200)
        other=next(t for t in self.detail()['tracks'] if t['id']!=root['id'])
        self.assertEqual(self.mutation('track',track_id=root['id'],name='只改名称')[0],200)
        self.assertEqual(self.detail()['tracks'][0]['color'],'#f012ab')
        with server.connect(audit=False) as db:db.execute('UPDATE timeline_tracks SET position=100-position WHERE session_id=?',(self.sid,))
        self.assertEqual(self.mutation('delete-track',track_id=other['id'],confirmed=True)[0],200)
        self.assertEqual(self.mutation('track',name='后加轨道',kind='event')[0],200)
        self.assertEqual(next(t for t in self.detail()['tracks'] if t['id']==root['id'])['color'],'#f012ab')

    def test_child_inheritance_custom_override_undo_and_invalid_color_rollback(self):
        root=self.detail()['tracks'][0]
        self.assertEqual(self.mutation('track',name='子层',kind='event',parent_id=root['id'])[0],200)
        child=next(t for t in self.detail()['tracks'] if t['parent_id'])
        self.assertIsNone(child['color'])
        self.assertEqual(self.mutation('track',track_id=child['id'],name=child['name'],kind='event',color='#ffffff')[0],200)
        self.assertEqual(next(t for t in self.detail()['tracks'] if t['id']==child['id'])['color'],'#ffffff')
        self.assertEqual(self.undo()[0],200)
        self.assertIsNone(next(t for t in self.detail()['tracks'] if t['id']==child['id'])['color'])
        before=self.detail()
        for bad in ('red','#123','#1234567','url(javascript:alert(1))',123,{},''):
            code,result=self.mutation('track',track_id=root['id'],name='不应保存',color=bad)
            self.assertEqual(code,400,result)
            self.assertEqual(self.detail(),before)
        self.assertEqual(self.mutation('track',track_id=root['id'],name=root['name'],color='#000000')[0],200)

    def test_duplicate_language_exchange_and_legacy_import_preserve_colors(self):
        root=self.detail()['tracks'][0]
        self.assertEqual(self.mutation('track',track_id=root['id'],name='根',color='#120abc')[0],200)
        self.assertEqual(self.mutation('track',name='继承',kind='event',parent_id=root['id'])[0],200)
        self.assertEqual(self.mutation('track',name='独立颜色',kind='event',parent_id=root['id'],color='#fab012')[0],200)
        code,result=self.mutation('duplicate');self.assertEqual(code,200,result)
        self.sid=result['id'];expected={t['name']:t['color'] for t in self.detail()['tracks']}
        self.assertEqual(expected,{'根':'#120abc','继承':None,'独立颜色':'#fab012'})
        bundle=self.call('/api/export-language?language=ordos')[1]
        target=self.call('/api/save-language',{'name':'颜色交换','metadata':{}})[1]['id']
        code,result=self.call('/api/import-language',{'bundle':bundle,'_language':target});self.assertEqual(code,200,result)
        with server.connect(audit=False) as db:
            imported=[dict(r) for r in db.execute('SELECT t.name,t.color FROM timeline_tracks t JOIN timeline_sessions s ON s.id=t.session_id WHERE s.language_id=?',(target,))]
            self.assertEqual({t['name']:t['color'] for t in imported},expected)
            legacy=timeline.export_bundle(db,'ordos')
            for t in legacy['timeline_tracks']:t.pop('color')
            timeline.import_bundle(db,legacy,'ordos',{})
            self.assertFalse(db.execute('SELECT 1 FROM timeline_tracks WHERE parent_id IS NULL AND color IS NULL').fetchone())

    def test_backup_restore_and_pre_color_undo_history(self):
        root=self.detail()['tracks'][0]
        self.assertEqual(self.mutation('track',track_id=root['id'],name='旧记录')[0],200)
        # Simulate a pre-colour database and its undo payload without touching production.
        with server.connect(audit=False) as db:
            db.execute('ALTER TABLE timeline_tracks DROP COLUMN color')
            for step in db.execute('SELECT id,changes FROM undo_steps').fetchall():
                changes=undo_codec.decode(step['changes'])
                for change in changes:
                    if change['table']=='timeline_tracks':
                        for side in ('before','after'):
                            if change[side]:change[side].pop('color',None)
                db.execute('UPDATE undo_steps SET changes=? WHERE id=?',(json.dumps(changes),step['id']))
        server.init()
        files=list((server.DB.parent/'backups').glob('*.sqlite3'));self.assertTrue(files)
        with closing(sqlite3.connect(files[-1])) as db:self.assertNotIn('color',{r[1] for r in db.execute('PRAGMA table_info(timeline_tracks)')})
        color=self.detail()['tracks'][0]['color'];self.assertEqual(color,timeline_colors.PALETTE[0])
        server.init();self.assertEqual(self.detail()['tracks'][0]['color'],color)
        self.assertEqual(self.undo()[0],200)
        self.assertEqual(self.detail()['tracks'][0]['color'],color)
        self.assertEqual(self.detail()['tracks'][0]['name'],root['name'])
        self.assertEqual(self.undo('redo')[0],200)
        self.assertEqual(self.detail()['tracks'][0]['color'],color)
        self.assertEqual(self.mutation('track',track_id=root['id'],name=root['name'],color='#33aa77')[0],200)
        backup=self.call('/api/backup')[1];path=Path(self.temp.name)/'colors.json';path.write_text(json.dumps(backup),encoding='utf-8')
        destination=Path(self.temp.name)/'restored.sqlite3';restore(path,destination)
        with closing(sqlite3.connect(destination)) as db:
            self.assertEqual(db.execute('SELECT color FROM timeline_tracks WHERE id=?',(root['id'],)).fetchone()[0],'#33aa77')
        import project_backup,language_exchange
        with server.connect(audit=False) as db:package=project_backup.prepare(db,server.DB)
        archive=language_exchange.staged(server.DB,package['token'],'project-backup')
        target=Path(self.temp.name)/'snapshot.sqlite3';project_backup.restore(archive,target)
        with closing(sqlite3.connect(target)) as db:self.assertEqual(db.execute('SELECT color FROM timeline_tracks WHERE id=?',(root['id'],)).fetchone()[0],'#33aa77')
        # Invalid incoming colours must fail the whole language import.
        bundle=self.call('/api/export-language?language=ordos')[1];bundle['timeline_tracks'][0]['color']='bad'
        tables=('languages','texts','entries','timeline_sessions','timeline_tracks','timeline_intervals')
        with server.connect(audit=False) as db:before={t:db.execute('SELECT COUNT(*) FROM '+t).fetchone()[0] for t in tables}
        self.assertEqual(self.call('/api/import-language',{'bundle':bundle,'name':'不应创建'})[0],400)
        with server.connect(audit=False) as db:self.assertEqual({t:db.execute('SELECT COUNT(*) FROM '+t).fetchone()[0] for t in tables},before)
