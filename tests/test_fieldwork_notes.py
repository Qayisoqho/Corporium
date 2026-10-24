import json
import sqlite3
import unittest
from contextlib import closing
from pathlib import Path

import server
import test_server
from restore_backup import restore


class FieldworkNotesTests(unittest.TestCase):
    setUp=test_server.APITests.setUp
    tearDown=test_server.APITests.tearDown
    call=test_server.APITests.call

    def rows(self,lid='ordos'):return self.call('/api/fieldwork-notes?language='+lid)[1]['items']
    def detail(self,nid,lid='ordos'):return self.call('/api/fieldwork-notes?language='+lid+'&id='+nid)[1]
    def create(self,title='',body=None,lid='ordos'):
        code,r=self.call('/api/fieldwork-note-create',dict(title=title,body=body or [],_language=lid));self.assertEqual(code,200,r);return r
    def mutate(self,action,row,**body):return self.call('/api/fieldwork-note-'+action,dict(id=row['id'],revision=row['revision'],_language=row['language_id'],**body))
    def save(self,row,**body):
        code,r=self.mutate('save',row,**body);self.assertEqual(code,200,r);return r
    def undo(self,kind='undo',lid='ordos'):return self.call('/api/'+kind,dict(generation=self.call('/api/undo-state?language='+lid)[1]['generation'],_language=lid))
    def reorder(self,order,snapshot=None):return self.call('/api/fieldwork-note-reorder',dict(order=order,snapshot=snapshot if snapshot is not None else [dict(id=r['id'],revision=r['revision']) for r in self.rows()]))

    def test_autosaves_coalesce_copy_delete_and_complete_undo_redo(self):
        row=self.create();nid=row['id']
        first=self.save(row,title='',body=[dict(text='现场记录',bold=True)])
        final=self.save(first,title='亲属称谓',body=[dict(text='父亲',italic=True),dict(text='\n追问母系称呼',highlight=True)])
        steps=self.call('/api/undo-state')[1]['steps'];self.assertEqual(len(steps),2)
        self.assertEqual(steps[0]['label'],'编辑调查笔记')
        state=self.call('/api/undo-state')[1];self.assertEqual(self.save(final,title=final['title'],body=final['body']),final)
        self.assertEqual(self.call('/api/undo-state')[1],state)
        code,copy=self.mutate('copy',final);self.assertEqual(code,200,copy);self.assertNotEqual(copy['id'],nid);self.assertEqual(copy['body'],final['body'])
        self.assertEqual(self.mutate('delete',final,confirmed=True)[0],200);self.assertNotIn(nid,[r['id'] for r in self.rows()])
        self.assertEqual(self.undo()[0],200);restored=self.detail(nid);self.assertEqual(restored['body'],final['body']);self.assertGreater(restored['revision'],final['revision'])
        self.assertEqual(self.undo('redo')[0],200);self.assertNotIn(nid,[r['id'] for r in self.rows()])
        self.undo();self.undo();self.undo();self.assertEqual(self.detail(nid)['body'],[])
        self.undo('redo');self.assertEqual(self.detail(nid)['body'],final['body'])

    def test_reorder_stale_and_invalid_requests_are_atomic(self):
        ids=[self.create(t)['id'] for t in ('第一','第二','第三')]
        stale=[dict(id=r['id'],revision=r['revision']) for r in self.rows()]
        self.assertEqual(self.reorder(ids[::-1])[0],200);self.assertEqual([r['id'] for r in self.rows()],ids[::-1])
        self.assertEqual(self.undo()[0],200);self.assertEqual([r['id'] for r in self.rows()],ids)
        self.assertEqual(self.undo('redo')[0],200);self.assertEqual([r['id'] for r in self.rows()],ids[::-1])
        before=self.rows();history=self.call('/api/undo-state')[1]
        for order in (None,{},ids[:2],[ids[0],ids[0],ids[2]],[1,*ids[:2]],['missing',*ids[:2]]):
            self.assertEqual(self.reorder(order)[0],400);self.assertEqual(self.rows(),before);self.assertEqual(self.call('/api/undo-state')[1],history)
        self.assertEqual(self.reorder(ids,stale)[0],400);self.assertEqual(self.rows(),before)
        self.assertEqual(self.reorder(ids[::-1])[0],200);self.assertEqual(self.call('/api/undo-state')[1],history)

    def test_language_isolation_revision_and_rich_validation(self):
        a=self.create('共享笔记',[dict(text='<script>文字</script>',bold=True,unknown='ignored')]);nid=a['id']
        other=self.call('/api/save-language',dict(name='另一语言',metadata={}))[1]['id'];foreign=self.create('外语笔记',lid=other)
        before=self.rows();history=self.call('/api/undo-state')[1]
        for action in ('save','copy','delete'):
            self.assertEqual(self.call('/api/fieldwork-note-'+action,dict(id=nid,revision=a['revision'],_language=other,confirmed=True))[0],400)
        self.assertEqual(self.call('/api/fieldwork-notes?language='+other+'&id='+nid)[0],400)
        self.assertEqual(self.call('/api/fieldwork-notes?language=all')[0],400)
        self.assertEqual(self.call('/api/fieldwork-note-create',dict(_language='all'))[0],400)
        self.assertEqual(self.mutate('delete',a)[0],400)
        for body in (None,{},[dict(text=2)],[dict(text='x',type_id='missing')],[dict(text='x'*200001)]):
            self.assertEqual(self.mutate('save',a,body=body)[0],400)
        self.assertEqual(self.mutate('save',a,title='x'*501)[0],400)
        self.assertEqual(self.rows(),before);self.assertEqual(self.call('/api/undo-state')[1],history)
        a=self.save(a,title='更新',body=a['body']);self.assertEqual(self.mutate('save',{**a,'revision':1},title='迟到内容')[0],400)
        self.assertEqual(self.detail(nid)['title'],'更新');self.assertEqual(self.detail(foreign['id'],other)['title'],'外语笔记')
        snapshot=[dict(id=r['id'],revision=r['revision']) for r in self.rows()]
        self.assertEqual(self.reorder([foreign['id']],snapshot)[0],400)

    def test_list_is_lightweight_and_preview_is_plain_text(self):
        row=self.create(body=[dict(text='\n长正文\n'+('汉字'*45000),bold=True)])
        listing=self.rows()[0];self.assertNotIn('body',listing);self.assertEqual(len(listing['preview']),180);self.assertTrue(listing['preview'].startswith('长正文'))
        self.assertEqual(self.detail(row['id'])['body'],row['body'])
        server.init();self.assertEqual(self.detail(row['id'])['body'],row['body'])

    def test_writing_type_replacement_and_language_exchange(self):
        t=self.call('/api/writing-save',dict(name='音标笔记',font='IPAPANNEW'))[1]
        row=self.create('录音现场',[dict(text='kʉrʰtʰe',type_id=t['id'],italic=True)])
        before=self.rows();self.assertEqual(self.call('/api/writing-delete',{**t,'confirmed':True})[0],400);self.assertEqual(self.rows(),before)
        replacement=self.call('/api/writing-save',dict(name='替代书写',font='Junicode'))[1]
        code,r=self.call('/api/writing-delete',{**t,'confirmed':True,'replacement_id':replacement['id']});self.assertEqual(code,200,r)
        self.assertEqual(self.detail(row['id'])['body'][0]['type_id'],replacement['id'])
        self.assertEqual(self.undo()[0],200);self.assertEqual(self.detail(row['id'])['body'][0]['type_id'],t['id'])
        bundle=self.call('/api/export-language?language=ordos')[1]
        import language_exchange
        with server.connect(audit=False) as db:export=language_exchange.prepare(db,server.DB,'ordos',json_only=True)
        streamed=json.loads(language_exchange.staged(server.DB,export['token'],'language-json').read_text(encoding='utf-8'))
        self.assertEqual(streamed['fieldwork_notes'],bundle['fieldwork_notes'])
        target=self.call('/api/save-language',dict(name='交换目标',metadata={}))[1]['id']
        code,result=self.call('/api/import-language',dict(bundle=bundle,_language=target));self.assertEqual(code,200,result)
        imported=self.rows(target)[0];self.assertNotEqual(imported['id'],row['id']);detail=self.detail(imported['id'],target)
        self.assertNotEqual(detail['body'][0]['type_id'],t['id'])
        self.assertIn(detail['body'][0]['type_id'],[r['id'] for r in self.call('/api/fieldwork-notes?language='+target)[1]['writing_types']])
        legacy=dict(bundle);legacy.pop('fieldwork_notes');target2=self.call('/api/save-language',dict(name='旧交换包',metadata={}))[1]['id']
        self.assertEqual(self.call('/api/import-language',dict(bundle=legacy,_language=target2))[0],200);self.assertEqual(self.rows(target2),[])

    def test_both_backup_formats_restore_notes_order_and_delete_history(self):
        a=self.create('A',[dict(text='正文',bold=True)]);b=self.create('B')
        self.reorder([b['id'],a['id']]);self.mutate('delete',self.detail(a['id']),confirmed=True)
        backup=Path(self.temp.name)/'backup.json';backup.write_text(json.dumps(self.call('/api/backup')[1]),encoding='utf-8')
        restored=Path(self.temp.name)/'restored.sqlite3';restore(backup,restored)
        import project_backup,language_exchange
        with server.connect(audit=False) as db:package=project_backup.prepare(db,server.DB)
        snapshot=Path(self.temp.name)/'snapshot.sqlite3';project_backup.restore(language_exchange.staged(server.DB,package['token'],'project-backup'),snapshot)
        original=server.DB
        for dest in (restored,snapshot):
            server.DB=dest;server.init();self.assertEqual([r['title'] for r in self.rows()],['B'])
            self.assertEqual(self.undo()[0],200);self.assertEqual([r['title'] for r in self.rows()],['B','A']);self.assertEqual(self.detail(a['id'])['body'],a['body'])
        server.DB=original

    def test_existing_database_migration_snapshots_before_creating_table(self):
        with server.connect(audit=False) as db:db.execute('DROP TABLE fieldwork_notes')
        existing=set((server.DB.parent/'backups').glob('*.sqlite3'));server.init()
        backups=set((server.DB.parent/'backups').glob('*.sqlite3'))-existing;self.assertEqual(len(backups),1)
        with closing(sqlite3.connect(backups.pop())) as db:self.assertFalse(db.execute("SELECT 1 FROM sqlite_master WHERE name='fieldwork_notes'").fetchone())
        self.assertEqual(self.rows(),[])


if __name__=='__main__':unittest.main()
