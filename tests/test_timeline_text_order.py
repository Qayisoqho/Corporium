import json
import sqlite3
import unittest
from contextlib import closing
from pathlib import Path
from unittest.mock import patch

import server
import timeline_text_order
import test_server
import test_long_task_writes
from restore_backup import restore


class TimelineTextOrderTests(unittest.TestCase):
    setUp=test_server.APITests.setUp
    tearDown=test_server.APITests.tearDown
    call=test_server.APITests.call
    wait=test_long_task_writes.WriteTasks.wait
    submit=test_long_task_writes.WriteTasks.submit
    execute=test_long_task_writes.WriteTasks.execute
    snapshot=test_long_task_writes.WriteTasks.snapshot
    cancel_after_dispatch=test_long_task_writes.WriteTasks.cancel_after_dispatch

    def seed(self,letters='ABC'):
        code,r=self.call('/api/import',dict(title='时间顺序验证',content='\n'.join(f'#pass([{x}], (([{x}],[{x}]),), [{x}])' for x in letters)))
        self.assertEqual(code,200,r)
        self.tid=r['id'];self.ids=[r['id'] for r in self.entries()]
        self.sid=self.call('/api/timeline-create',dict(name='排序依据'))[1]['id']
        self.track=self.detail()['tracks'][0]['id']

    def entries(self):return self.call('/api/entries?text='+self.tid)[1]['items']
    def detail(self,sid=None):return self.call('/api/timeline-detail?id='+(sid or self.sid)+'&language=ordos&complete=1')[1]
    def payload(self,sid=None,**b):
        sid=sid or self.sid
        return dict(id=sid,revision=self.detail(sid)['session']['revision'],**b)
    def mutate(self,action,sid=None,**b):return self.call('/api/timeline-'+action,self.payload(sid,**b))
    def binding(self,sid=None):return self.call('/api/timeline-text-order?id='+(sid or self.sid)+'&language=ordos&text_id='+self.tid)[1]
    def order_body(self,enabled=True,sid=None):return self.payload(sid,text_id=self.tid,binding=self.binding(sid)['binding'],enabled=enabled)
    def enable(self,enabled=True,sid=None):
        code,r=self.call('/api/timeline-text-order',self.order_body(enabled,sid));self.assertEqual(code,200,r);return r
    def add(self,index,start,track=None,sid=None):
        code,r=self.mutate('interval',sid,track_id=track or self.track,entry_id=self.ids[index],start_ms=start,end_ms=start+5000)
        self.assertEqual(code,200,r)
        return next(i for i in self.detail(sid)['intervals'] if i['entry_id']==self.ids[index] and i['start_ms']==start)
    def undo(self,kind='undo'):return self.call('/api/'+kind,dict(generation=self.call('/api/undo-state')[1]['generation']))
    def assertOrder(self,letters):
        rows=self.entries();self.assertEqual(''.join(r['ipa'] for r in rows),letters)
        self.assertEqual([r['position'] for r in rows],list(range(1,len(rows)+1)))

    def test_new_sentence_alignment_persists_numbers_and_undo_is_atomic(self):
        self.seed('AB');self.add(0,1000);self.add(1,30000);self.enable()
        # A newly saved sentence appends until it receives its first alignment.
        code,c=self.call('/api/sentence-create',dict(kind='corpus',text_id=self.tid,slot_ids=[],body=dict(ipa='C',translation='C',words=[]),cells=[],layers=[]))
        self.assertEqual(code,200,c);self.ids.append(c['id']);self.assertOrder('ABC')
        before={r['id']:(r['revision'],r['words']) for r in self.entries()}
        self.add(2,10000);self.assertOrder('ACB')
        after={r['id']:(r['revision'],r['words']) for r in self.entries()}
        self.assertEqual(after,before)
        self.assertEqual(self.undo()[0],200);self.assertOrder('ABC')
        self.assertFalse(any(i['entry_id']==c['id'] for i in self.detail()['intervals']))
        self.assertEqual(self.undo('redo')[0],200);self.assertOrder('ACB')
        server.init();self.assertOrder('ACB');self.assertTrue(self.binding()['enabled'])
        interval=next(i for i in self.detail()['intervals'] if i['entry_id']==c['id'])
        code,r=self.mutate('interval',interval_id=interval['id'],track_id=self.track,entry_id=c['id'],start_ms=40000,end_ms=45000)
        self.assertEqual(code,200,r);self.assertOrder('ABC')
        self.assertEqual(self.undo()[0],200);self.assertOrder('ACB')
        self.assertEqual(next(i for i in self.detail()['intervals'] if i['id']==interval['id'])['start_ms'],10000)

    def test_enable_sorts_existing_and_disable_keeps_saved_order(self):
        self.seed();self.add(0,1000);self.add(1,30000);c=self.add(2,10000)
        self.assertOrder('ABC');self.enable();self.assertOrder('ACB')
        self.assertEqual(self.undo()[0],200);self.assertOrder('ABC');self.assertFalse(self.binding()['enabled'])
        self.undo('redo');self.assertOrder('ACB');self.enable(False);self.assertOrder('ACB')
        self.mutate('interval',interval_id=c['id'],track_id=self.track,entry_id=self.ids[2],start_ms=40000,end_ms=45000)
        self.assertOrder('ACB')

    def test_earliest_interval_ties_unaligned_and_delete_split_merge(self):
        self.seed('ABCDE');self.add(0,30000);b=self.add(1,10000)
        self.mutate('track',name='同时发言',kind='sentence');other=self.detail()['tracks'][-1]['id']
        self.add(2,10000,other);a=self.add(0,-5000);self.enable();self.assertOrder('ABCDE')
        self.assertEqual(self.mutate('split',interval_id=b['id'],at_ms=12000)[0],200);self.assertOrder('ABCDE')
        halves=[i for i in self.detail()['intervals'] if i['entry_id']==self.ids[1]]
        self.assertEqual(self.mutate('merge',interval_id=halves[0]['id'],other_id=halves[1]['id'])[0],200)
        self.assertEqual(self.mutate('delete-interval',interval_id=a['id'],confirmed=True)[0],200)
        self.assertOrder('BCADE')  # tied B,C retain order; D,E stay unaligned at the end.
        self.undo();self.assertOrder('ABCDE')

    def test_one_authority_per_text_switch_and_stale_cross_language_guards(self):
        self.seed();self.add(0,1000);self.add(1,30000);self.add(2,10000);self.enable()
        sid=self.call('/api/timeline-create',dict(name='另一录音'))[1]['id'];track=self.detail(sid)['tracks'][0]['id']
        self.add(1,1000,track,sid);self.add(2,10000,track,sid);self.add(0,30000,track,sid)
        self.assertOrder('ACB');stale=self.order_body()
        self.enable(sid=sid);self.assertOrder('BCA');self.assertFalse(self.binding()['enabled'])
        stale['revision']=self.detail()['session']['revision']
        before=self.snapshot();self.assertEqual(self.call('/api/timeline-text-order',stale)[0],400);self.assertEqual(self.snapshot(),before)
        self.assertEqual(self.call('/api/timeline-text-order',self.order_body(False))[0],400)
        self.undo();self.assertOrder('ACB');self.assertTrue(self.binding()['enabled'])
        foreign=self.call('/api/save-language',dict(name='其他语言',metadata={}))[1]['id']
        for bad in ('','@independent','missing'):
            self.assertEqual(self.call('/api/timeline-text-order',{**self.order_body(), 'text_id':bad})[0],400)
        self.assertEqual(self.call('/api/timeline-text-order',{**self.order_body(),'_language':foreign})[0],400)

    def test_export_import_and_both_backups_keep_binding_and_numbers(self):
        self.seed();self.add(0,1000);self.add(1,30000);self.add(2,10000);self.enable()
        bundle=self.call('/api/export-language?language=ordos')[1]
        target=self.call('/api/save-language',dict(name='交换目标',metadata={}))[1]['id']
        code,r=self.call('/api/import-language',dict(bundle=bundle,_language=target));self.assertEqual(code,200,r)
        with server.connect(audit=False) as db:
            binding=db.execute('SELECT o.*,t.language_id FROM timeline_text_orders o JOIN texts t ON t.id=o.id WHERE t.language_id=?',(target,)).fetchone()
            self.assertIsNotNone(binding);self.assertNotEqual(binding['id'],self.tid);self.assertNotEqual(binding['session_id'],self.sid)
            self.assertEqual(db.execute('SELECT language_id FROM timeline_sessions WHERE id=?',(binding['session_id'],)).fetchone()[0],target)
            copied=[json.loads(r[0])['ipa'] for r in db.execute('SELECT body FROM entries WHERE text_id=? ORDER BY position',(binding['id'],))]
            self.assertEqual(copied,list('ACB'))
        backup=Path(self.temp.name)/'backup.json';backup.write_text(json.dumps(self.call('/api/backup')[1]),encoding='utf-8')
        restored=Path(self.temp.name)/'restored.sqlite3';restore(backup,restored)
        import project_backup,language_exchange
        with server.connect(audit=False) as db:package=project_backup.prepare(db,server.DB)
        snapshot=Path(self.temp.name)/'snapshot.sqlite3';project_backup.restore(language_exchange.staged(server.DB,package['token'],'project-backup'),snapshot)
        for dest in (restored,snapshot):
            with closing(sqlite3.connect(dest)) as db:
                self.assertEqual(db.execute('SELECT session_id FROM timeline_text_orders WHERE id=?',(self.tid,)).fetchone()[0],self.sid)
                self.assertEqual([json.loads(r[0])['ipa'] for r in db.execute('SELECT body FROM entries WHERE text_id=? ORDER BY position',(self.tid,))],list('ACB'))
        bundle.pop('timeline_text_orders');target=self.call('/api/save-language',dict(name='旧交换包',metadata={}))[1]['id']
        self.assertEqual(self.call('/api/import-language',dict(bundle=bundle,_language=target))[0],200)

    def test_delete_cleanup_undo_and_migration_snapshot(self):
        self.seed();self.enable()
        self.assertEqual(self.mutate('delete',confirmed=True)[0],200)
        with server.connect(audit=False) as db:self.assertEqual(db.execute('SELECT COUNT(*) FROM timeline_text_orders').fetchone()[0],0)
        self.undo();self.assertTrue(self.binding()['enabled'])
        self.assertEqual(self.call('/api/delete-text',dict(id=self.tid,count=3,confirmed=True))[0],200)
        with server.connect(audit=False) as db:self.assertEqual(db.execute('SELECT COUNT(*) FROM timeline_text_orders').fetchone()[0],0)
        self.undo();self.assertTrue(self.binding()['enabled'])
        with server.connect(audit=False) as db:db.execute('DROP TABLE timeline_text_orders')
        existing=set((server.DB.parent/'backups').glob('*.sqlite3'));server.init()
        backups=set((server.DB.parent/'backups').glob('*.sqlite3'))-existing;self.assertEqual(len(backups),1)
        with closing(sqlite3.connect(backups.pop())) as db:self.assertFalse(db.execute("SELECT 1 FROM sqlite_master WHERE name='timeline_text_orders'").fetchone())
        self.assertFalse(self.binding()['enabled']);self.assertOrder('ABC')

    def test_background_cancel_rolls_back_binding_interval_numbers_and_history(self):
        self.seed();self.add(0,1000);self.add(1,30000);self.add(2,10000)
        self.cancel_after_dispatch('timeline-text-order',self.order_body());self.assertOrder('ABC')
        self.execute('timeline-text-order',self.order_body());self.assertOrder('ACB')
        interval=next(i for i in self.detail()['intervals'] if i['entry_id']==self.ids[2])
        body=self.payload(interval_id=interval['id'],track_id=self.track,entry_id=self.ids[2],start_ms=40000,end_ms=45000)
        self.cancel_after_dispatch('timeline-interval',body);self.assertOrder('ACB')
        before=self.snapshot();original=timeline_text_order.sync_text
        def abort(db,*args):
            import long_tasks
            changed=original(db,*args);self.assertGreater(changed,0)
            job=long_tasks.CURRENT.get();long_tasks.cancel(job['project'],job['id']);long_tasks.checkpoint()
        with patch('timeline_text_order.sync_text',abort):
            self.assertEqual(self.wait(self.submit('timeline-interval',body))['state'],'cancelled')
        self.assertEqual(self.snapshot(),before)
        self.execute('timeline-interval',body);self.assertOrder('ABC')
        self.undo();self.assertOrder('ACB')


if __name__=='__main__':unittest.main()
