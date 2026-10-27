import undo_codec
import json
import sqlite3
import unittest
from contextlib import closing
from pathlib import Path

import server
import timeline
import test_server
from restore_backup import restore


class TimelineOrderTests(unittest.TestCase):
    setUp=test_server.APITests.setUp
    tearDown=test_server.APITests.tearDown
    call=test_server.APITests.call

    def create(self,name,lid='ordos'):
        code,result=self.call('/api/timeline-create',{'name':name,'_language':lid})
        self.assertEqual(code,200,result)
        return result['id']

    def rows(self,lid='ordos'):
        return self.call('/api/timeline-list?language='+lid)[1]

    def reorder(self,order,snapshot=None):
        return self.call('/api/timeline-reorder',{'order':order,'snapshot':snapshot if snapshot is not None else [dict(id=r['id'],revision=r['revision']) for r in self.rows()]})

    def undo(self,kind='undo'):
        return self.call('/api/'+kind,{'generation':self.call('/api/undo-state')[1]['generation']})

    def test_order_undo_redo_reload_and_noop(self):
        ids=[self.create(n) for n in ('甲','乙','丙')]
        self.assertEqual([r['id'] for r in self.rows()],ids[::-1])
        self.assertEqual(self.reorder(ids)[0],200)
        self.assertEqual(self.call('/api/undo-state')[1]['undo']['label'],'调整时间轴顺序')
        self.assertEqual([r['id'] for r in self.rows()],ids)
        server.init()
        self.assertEqual([r['id'] for r in self.rows()],ids)
        state=self.call('/api/undo-state')[1]
        self.assertEqual(self.reorder(ids)[0],200)
        self.assertEqual(self.call('/api/undo-state')[1],state)
        self.assertEqual(self.undo()[0],200)
        self.assertEqual([r['id'] for r in self.rows()],ids[::-1])
        self.assertEqual(self.undo('redo')[0],200)
        self.assertEqual([r['id'] for r in self.rows()],ids)
        new=self.create('新增')
        self.assertEqual([r['id'] for r in self.rows()],[new,*ids])

    def test_invalid_stale_and_cross_language_reorder_are_atomic(self):
        ids=[self.create(n) for n in ('甲','乙','丙')]
        lid=self.call('/api/save-language',{'name':'其他语言','metadata':{}})[1]['id']
        foreign=self.create('另一语言',lid)
        before=self.rows();undo_before=self.call('/api/undo-state')[1]
        for bad in (None,{},ids[:2],[ids[0],ids[0],ids[2]],[foreign,*ids[:2]],[1,*ids[:2]]):
            self.assertEqual(self.reorder(bad)[0],400)
            self.assertEqual(self.rows(),before)
            self.assertEqual(self.call('/api/undo-state')[1],undo_before)
        stale=[dict(id=r['id'],revision=r['revision']) for r in before]
        row=before[0]
        self.call('/api/timeline-rename',dict(id=row['id'],revision=row['revision'],name='新名称'))
        self.assertEqual(self.reorder(ids,stale)[0],400)
        self.assertEqual(self.reorder(ids)[0],200)
        after_reorder=self.rows()
        self.assertEqual(self.reorder(ids[::-1],stale)[0],400)
        self.assertEqual(self.rows(),after_reorder)
        self.assertEqual([r['id'] for r in self.rows(lid)],[foreign])

    def test_exchange_and_both_backup_formats_keep_order(self):
        ids=[self.create(n) for n in ('甲','乙','丙')]
        self.assertEqual(self.reorder([ids[1],ids[0],ids[2]])[0],200)
        expected=[r['name'] for r in self.rows()]
        bundle=self.call('/api/export-language?language=ordos')[1]
        target=self.call('/api/save-language',{'name':'交换','metadata':{}})[1]['id']
        code,result=self.call('/api/import-language',{'bundle':bundle,'_language':target})
        self.assertEqual(code,200,result)
        self.assertEqual([r['name'] for r in self.rows(target)],expected)
        # Legacy language packages already list sessions in their intended order.
        for row in bundle['timeline_sessions']:row.pop('position')
        legacy_target=self.call('/api/save-language',{'name':'旧交换','metadata':{}})[1]['id']
        self.assertEqual(self.call('/api/import-language',{'bundle':bundle,'_language':legacy_target})[0],200)
        self.assertEqual([r['name'] for r in self.rows(legacy_target)],expected)
        path=Path(self.temp.name)/'backup.json';path.write_text(json.dumps(self.call('/api/backup')[1]),encoding='utf-8')
        restored=Path(self.temp.name)/'restored.sqlite3';restore(path,restored)
        with closing(sqlite3.connect(restored)) as db:
            self.assertEqual([r[0] for r in db.execute('SELECT name FROM timeline_sessions WHERE language_id=? ORDER BY position',('ordos',))],expected)
        import project_backup,language_exchange
        with server.connect(audit=False) as db:package=project_backup.prepare(db,server.DB)
        archive=language_exchange.staged(server.DB,package['token'],'project-backup')
        snapshot=Path(self.temp.name)/'snapshot.sqlite3';project_backup.restore(archive,snapshot)
        with closing(sqlite3.connect(snapshot)) as db:
            self.assertEqual([r[0] for r in db.execute('SELECT name FROM timeline_sessions WHERE language_id=? ORDER BY position',('ordos',))],expected)

    def test_migration_backs_up_and_legacy_undo_preserves_saved_position(self):
        ids=[self.create(n) for n in ('甲','乙','丙')]
        old_order=[r['id'] for r in self.rows()]
        with server.connect(audit=False) as db:
            db.execute('DROP INDEX timeline_session_order')
            db.execute('ALTER TABLE timeline_sessions DROP COLUMN position')
            for step in db.execute('SELECT id,changes FROM undo_steps').fetchall():
                changes=undo_codec.decode(step['changes'])
                for c in changes:
                    if c['table']=='timeline_sessions':
                        for side in ('before','after'):
                            if c[side]:c[side].pop('position',None)
                db.execute('UPDATE undo_steps SET changes=? WHERE id=?',(json.dumps(changes),step['id']))
        server.init()
        self.assertEqual([r['id'] for r in self.rows()],old_order)
        backups=list((server.DB.parent/'backups').glob('*.sqlite3'));self.assertTrue(backups)
        with closing(sqlite3.connect(backups[-1])) as db:
            self.assertNotIn('position',{r[1] for r in db.execute('PRAGMA table_info(timeline_sessions)')})
        # Rename history from before this schema must keep a later saved order.
        row=self.rows()[0]
        self.call('/api/timeline-rename',dict(id=row['id'],revision=row['revision'],name='改名'))
        with server.connect(audit=False) as db:
            step=db.execute('SELECT id,changes FROM undo_steps ORDER BY id DESC LIMIT 1').fetchone()
            changes=undo_codec.decode(step['changes'])
            for c in changes:
                if c['table']=='timeline_sessions':
                    for side in ('before','after'):
                        if c[side]:c[side].pop('position',None)
            db.execute('UPDATE undo_steps SET changes=? WHERE id=?',(json.dumps(changes),step['id']))
            db.execute('UPDATE timeline_sessions SET position=90 WHERE id=?',(row['id'],))
        before=[r['id'] for r in self.rows()]
        self.assertEqual(self.undo()[0],200)
        self.assertEqual([r['id'] for r in self.rows()],before)
        self.assertEqual(self.undo('redo')[0],200)
        self.assertEqual([r['id'] for r in self.rows()],before)


if __name__=='__main__':unittest.main()
