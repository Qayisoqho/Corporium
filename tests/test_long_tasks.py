import gc
import io
import json
import sqlite3
import threading
import time
import unittest
import zipfile
from contextlib import closing
from pathlib import Path
from unittest.mock import patch
import test_server
import server
import streaming_json
import language_exchange
import project_backup
import long_tasks


class StreamingTests(unittest.TestCase):
    def test_table_encoding_preserves_unicode_nulls_ints_and_exact_real_values(self):
        import random
        with sqlite3.connect(':memory:') as db:
            db.row_factory=sqlite3.Row
            db.execute('CREATE TABLE "quoted table"("odd\""name" TEXT,value,number INTEGER)')
            values=[None,'汉字𐀀 e\u0301\n\t"\\\x00',2**63-1,-2**63,1.2345678901234567,1e-307,float('inf')]
            generator=random.Random(74);values.extend(generator.uniform(-1e30,1e30) for _ in range(20))
            db.executemany('INSERT INTO "quoted table" VALUES(?,?,?)',[(str(i),v,i) for i,v in enumerate(values)])
            data=streaming_json.TableRows(db,'quoted table');out=io.BytesIO()
            expected=list(streaming_json.Rows(db,'SELECT rowid AS rowid,* FROM "quoted table"'))
            streaming_json.write({'rows':data},out)
            self.assertEqual(json.loads(out.getvalue())['rows'],expected)
            self.assertEqual(list(data),expected)
            self.assertEqual(data[2],expected[2])

    def test_table_encoding_still_checks_cancel_and_abandons_partial_backup(self):
        import tempfile,backup_policy
        with tempfile.TemporaryDirectory() as directory,sqlite3.connect(':memory:') as db:
            db.row_factory=sqlite3.Row;db.execute('CREATE TABLE records(id INTEGER,body TEXT)')
            db.executemany('INSERT INTO records VALUES(?,?)',[(i,'大'*50000) for i in range(3)])
            def stop(*args):raise long_tasks.Cancelled()
            with patch.object(long_tasks,'checkpoint',stop),self.assertRaises(long_tasks.Cancelled):
                backup_policy.write_json(directory,{'records':streaming_json.TableRows(db,'records')},stream=True)
            self.assertEqual(list(Path(directory).iterdir()),[])

    def test_cursor_rows_nested_with_empty_tables_and_unicode_stay_streamed(self):
        with sqlite3.connect(':memory:') as db:
            db.row_factory=sqlite3.Row
            db.execute('CREATE TABLE records(id INTEGER,body TEXT)')
            db.executemany('INSERT INTO records VALUES(?,?)',[(i,'组合e\u0301、𐀀\n"'+str(i)) for i in range(200)])
            rows=streaming_json.Rows(db,'SELECT * FROM records ORDER BY id')
            value={'nested':[{'rows':rows,'empty':streaming_json.Rows(db,'SELECT * FROM records WHERE id<0')}],True:'boolean key'}
            out=io.BytesIO();updates=[]
            streaming_json.write(value,out,lambda *a:updates.append(a))
            expected={'nested':[{'rows':[dict(r) for r in db.execute('SELECT * FROM records ORDER BY id')],'empty':[]}],'true':'boolean key'}
            self.assertEqual(json.loads(out.getvalue()),expected)

    def test_chunk_boundaries_and_cleanup(self):
        class Tiny(io.StringIO):
            def read(self,n=-1):return super().read(min(n,1))
        expected={'unicode':'中文𐀀', 'numbers':[1.234e-15,-2e30,True,None,0], 'nested':[{'a':[1,2,3]},[],['a'*70000]]}
        doc=streaming_json.read(Tiny(json.dumps(expected,ensure_ascii=False)))
        directory=Path(doc.store.directory)
        out=io.BytesIO();streaming_json.write(doc,out)
        self.assertEqual(json.loads(out.getvalue()),expected)
        doc.close();self.assertFalse(directory.exists())
        doc=streaming_json.read(io.StringIO('{"a":[1]}'));directory=Path(doc.store.directory)
        del doc;gc.collect();self.assertFalse(directory.exists())

    def test_invalid_json(self):
        for text in ('{"a":[1,]}','{"a":1e}','{"a":"unfinished','[]','{"a":1} garbage','{"a":01}'):
            with self.subTest(text=text),self.assertRaises(ValueError):streaming_json.read(io.StringIO(text))

    def test_cancel_while_reading_one_large_scalar(self):
        updates=[]
        def stop(*args):
            updates.append(args)
            if len(updates)==3:raise long_tasks.Cancelled()
        with self.assertRaises(long_tasks.Cancelled):streaming_json.read(io.StringIO('{"large":"'+'x'*300000+'"}'),stop)
        self.assertEqual(len(updates),3)


class LongTaskTests(unittest.TestCase):
    setUp=test_server.APITests.setUp
    tearDown=test_server.APITests.tearDown
    call=test_server.APITests.call

    def seed(self):
        code,result=self.call('/api/import',dict(title='Example',content='#gloss([a], (([a-b],[N-pl]),), [translation])'))
        self.assertEqual(code,200,result)

    def wait(self,jid):
        deadline=time.monotonic()+20
        while time.monotonic()<deadline:
            state=long_tasks.view(server.DB,jid)
            if state['state'] not in ('queued','running'):return state
            time.sleep(.01)
        self.fail('Task timed out')

    def test_stream_matches_legacy(self):
        self.seed()
        with server.connect(audit=False) as db:
            expected=language_exchange.export_bundle(db,'ordos')
            result=language_exchange.prepare(db,server.DB,'ordos',json_only=True)
            path=language_exchange.staged(server.DB,result['token'],'language-json')
            self.assertEqual(json.loads(path.read_text(encoding='utf8')),expected)

    def test_picker_search_task_can_skip_unused_counts(self):
        self.seed()
        code,x=self.call('/api/lexeme-save',dict(headword='picker',body=dict(usages=[dict(senses=[dict(short_gloss='meaning')])])));self.assertEqual(code,200,x)
        with patch('lexicon.occurrence_count',side_effect=AssertionError('picker counts are unused')):
            jid=long_tasks.submit(server.DB,'dictionary',dict(language='ordos',q='picker',counts='0'))
            long_tasks.JOBS[jid]['future'].result(timeout=20)
            state=long_tasks.view(server.DB,jid)
            self.assertEqual(state['state'],'done',state)
            self.assertEqual(state['result']['items'][0]['body']['usages'][0]['senses'][0]['short_gloss'],'meaning')
            self.assertNotIn('example_count',state['result']['items'][0])

    def test_snapshot_restore_and_checksum(self):
        self.seed()
        with server.connect(audit=False) as db:
            result=project_backup.prepare(db,server.DB)
            expected={r[0]:db.execute('SELECT COUNT(*) FROM "'+r[0]+'"').fetchone()[0] for r in db.execute("SELECT name FROM sqlite_master WHERE type='table'")}
        path=language_exchange.staged(server.DB,result['token'],'project-backup')
        target=Path(self.temp.name)/'restored.sqlite3'
        from restore_backup import restore
        restore(path,target)
        with closing(sqlite3.connect(target)) as db:
            actual={r[0]:db.execute('SELECT COUNT(*) FROM "'+r[0]+'"').fetchone()[0] for r in db.execute("SELECT name FROM sqlite_master WHERE type='table'")}
            self.assertEqual(actual,expected)
            self.assertEqual(db.execute('PRAGMA quick_check').fetchone()[0],'ok')
            with closing(sqlite3.connect(server.DB)) as original:
                for table in expected:self.assertEqual(db.execute('SELECT * FROM "'+table+'"').fetchall(),original.execute('SELECT * FROM "'+table+'"').fetchall(),table)
        with self.assertRaises(ValueError):restore(path,target)
        corrupt=Path(self.temp.name)/'corrupt.zip'
        with zipfile.ZipFile(path) as src,zipfile.ZipFile(corrupt,'w') as dst:
            for name in src.namelist():
                data=src.read(name)
                if name=='manifest.json':
                    manifest=json.loads(data);manifest['database_sha256']='bad';data=json.dumps(manifest)
                dst.writestr(name,data)
        invalid=Path(self.temp.name)/'invalid.sqlite3'
        with self.assertRaisesRegex(ValueError,'校验'):restore(corrupt,invalid)
        self.assertFalse(invalid.exists())

    def test_queue_cancel_write_guard_and_scope(self):
        self.seed();entered=threading.Event();release=threading.Event()
        def slow(*a,**kw):
            entered.set()
            while not release.wait(.01):long_tasks.checkpoint(None,'Working')
            return {'ok':True}
        with patch('lexicon.list_lexemes',slow):
            first=long_tasks.submit(server.DB,'dictionary',{'language':'ordos'})
            self.assertTrue(entered.wait(5))
            second=long_tasks.submit(server.DB,'dictionary',{'language':'ordos'})
            try:
                self.assertEqual(self.call('/api/new-text',{'title':'Blocked'})[0],409)
                with self.assertRaises(ValueError):long_tasks.view(Path(self.temp.name)/'other.sqlite3',first)
                self.assertEqual(long_tasks.cancel(server.DB,second)['state'],'cancelled')
                long_tasks.cancel(server.DB,first)
                self.assertEqual(self.wait(first)['state'],'cancelled')
                self.assertEqual(self.wait(second)['state'],'cancelled')
                self.assertFalse(long_tasks.active(server.DB))
            finally:release.set()
        self.assertEqual(self.call('/api/new-text',{'title':'Allowed'})[0],200)

    def test_worker_export_and_failure_cleanup(self):
        self.seed()
        for kind in ('backup','language-json','language-package'):
            state=self.wait(long_tasks.submit(server.DB,kind,{'language':'ordos'}))
            self.assertEqual(state['state'],'done',state)
        before=set(Path(language_exchange.STAGING.name).iterdir())
        def stop(*args):raise long_tasks.Cancelled()
        with server.connect(audit=False) as db:
            with self.assertRaises(long_tasks.Cancelled):project_backup.prepare(db,server.DB,update=stop)
            original=streaming_json.write
            def abort(value,stream,update):stream.write(b'{');raise long_tasks.Cancelled()
            with patch('streaming_json.write',abort),self.assertRaises(long_tasks.Cancelled):language_exchange.prepare(db,server.DB,'ordos',json_only=True)
        self.assertEqual(set(Path(language_exchange.STAGING.name).iterdir()),before)

    def test_memory_protection_and_preview(self):
        self.seed()
        def slow(*args,**kw):
            while True:time.sleep(.01);long_tasks.checkpoint()
        with patch('long_tasks.working_set',return_value=long_tasks.MEMORY_LIMIT+1),patch('lexicon.list_lexemes',slow):
            state=self.wait(long_tasks.submit(server.DB,'dictionary',{'language':'ordos'}))
            self.assertEqual(state['state'],'error');self.assertIn('保护上限',state['message'])
        with server.connect(audit=False) as db:result=language_exchange.prepare(db,server.DB,'ordos',json_only=True)
        path=language_exchange.staged(server.DB,result['token'],'language-json')
        token=language_exchange.stage(server.DB,path,'import')
        state=self.wait(long_tasks.submit(server.DB,'language-preview',{'language':'ordos','token':token}))
        self.assertEqual(state['state'],'done',state);self.assertEqual(state['result']['sentences'],1)

    def test_snapshot_link_policy_and_attachment_restore(self):
        import wave,timeline,media_engine
        self.seed()
        path=Path(self.temp.name)/'tiny.wav'
        with wave.open(str(path),'wb') as f:f.setnchannels(1);f.setsampwidth(2);f.setframerate(8000);f.writeframes(b'\0\0'*80)
        with server.connect(audit=False) as db:
            timeline.mutate(db,'ordos','create',{'name':'linked'},dict(name=path.name,path=str(path),storage='link',metadata=dict(fingerprint=media_engine.fingerprint(path),duration_ms=10)))
        for include in (False,True):
            with server.connect(audit=False) as db:result=project_backup.prepare(db,server.DB,include_media=include)
            self.assertEqual(result['media'],int(include));self.assertEqual(result['external_links'],int(not include))
            archive=language_exchange.staged(server.DB,result['token'],'project-backup')
            target=Path(self.temp.name)/('copy'+str(include)+'.sqlite3')
            project_backup.restore(archive,target)
            with closing(sqlite3.connect(target)) as db:
                db.row_factory=sqlite3.Row;asset=dict(db.execute('SELECT * FROM timeline_media').fetchone())
                self.assertEqual(asset['storage'],'copy' if include else 'link')
                self.assertEqual(media_engine.resolve(target,asset).read_bytes(),path.read_bytes())

    def test_new_desktop_save_dialog_and_cancel(self):
        import desktop,types
        from unittest.mock import Mock
        self.seed()
        with server.connect(audit=False) as db:r=project_backup.prepare(db,server.DB)
        bridge=desktop.Bridge(None);bridge._origin='http://127.0.0.1:123';bridge._window=Mock();bridge._window.get_current_url.return_value=bridge._origin+'/'
        destination=Path(self.temp.name)/'Chosen.corporium-backup'
        bridge._window.create_file_dialog.return_value=[str(destination)]
        with patch.dict('sys.modules',webview=types.SimpleNamespace(FileDialog=types.SimpleNamespace(SAVE=1))):
            self.assertTrue(bridge.save_task_export(r['token'],destination.name,'project-backup').get('ok'))
            bridge._window.create_file_dialog.return_value=None
            self.assertTrue(bridge.save_task_export(r['token'],destination.name,'project-backup').get('cancelled'))
        self.assertEqual(destination.read_bytes(),language_exchange.staged(server.DB,r['token'],'project-backup').read_bytes())
        from webview.util import parse_file_type
        for file_type in bridge._window.create_file_dialog.call_args.kwargs['file_types']:parse_file_type(file_type)

    def test_attachment_undo_redo_survives_sqlite_restore(self):
        from test_object_media import ObjectMediaTests
        from test_lexicon import LexiconTests
        self.word=LexiconTests.word.__get__(self)
        self.undo=LexiconTests.undo.__get__(self)
        self.audio=ObjectMediaTests.audio.__get__(self)
        self.add=ObjectMediaTests.add.__get__(self)
        import object_media,media_engine
        word=self.word();self.assertEqual(self.add(word,self.audio())[0],200)
        self.assertEqual(self.undo()[0],200)
        with server.connect(audit=False) as db:backup=project_backup.prepare(db,server.DB)
        self.assertEqual(backup['media'],1)
        target=Path(self.temp.name)/'attachment-restored'/'corpus.sqlite3'
        project_backup.restore(language_exchange.staged(server.DB,backup['token'],'project-backup'),target)
        original=server.DB
        try:
            server.DB=target
            self.assertEqual(self.undo('redo')[0],200)
            with server.connect(audit=False) as db:
                item=object_media.listing(db,'lexeme',word['id'])['items'][0]
                path=media_engine.resolve(target,item['asset'])
                self.assertTrue(path.is_relative_to(target.parent))
                self.assertEqual(path.read_bytes(),self.audio().read_bytes())
        finally:server.DB=original

    def test_cancel_partial_snapshot_and_sqlite_query(self):
        self.seed();before=set(Path(language_exchange.STAGING.name).iterdir())
        def stop(progress,message):
            if progress is not None and progress>0:raise long_tasks.Cancelled()
        with server.connect(audit=False) as db,self.assertRaises(long_tasks.Cancelled):project_backup.prepare(db,server.DB,update=stop)
        self.assertEqual(set(Path(language_exchange.STAGING.name).iterdir()),before)
        entered=threading.Event()
        def query(db,*args,**kw):
            entered.set()
            return db.execute('WITH RECURSIVE n(x) AS (VALUES(1) UNION ALL SELECT x+1 FROM n WHERE x<100000000) SELECT sum(x) FROM n').fetchone()
        with patch('lexicon.list_lexemes',query):
            jid=long_tasks.submit(server.DB,'dictionary',{'language':'ordos'})
            self.assertTrue(entered.wait(5));long_tasks.cancel_all()
            self.assertEqual(self.wait(jid)['state'],'cancelled')

    def test_staged_retention_expiry_and_project_scope(self):
        tokens=[];files=[]
        for i in range(4):
            path=Path(language_exchange.STAGING.name)/('retention-'+str(i)+'.json');path.write_text('{}')
            files.append(path);tokens.append(language_exchange.stage(server.DB,path,'language-json'))
        self.assertFalse(files[0].exists());self.assertTrue(all(p.exists() for p in files[1:]))
        with self.assertRaises(ValueError):language_exchange.staged(Path(self.temp.name)/'other.sqlite3',tokens[-1],'language-json')
        with patch('language_exchange.time.time',return_value=time.time()+3601):language_exchange.prune()
        self.assertTrue(all(not p.exists() for p in files))

    def test_worker_queries_match_existing_apis(self):
        from test_lexicon import LexiconTests
        self.seed();LexiconTests.word(self)
        for kind,request,path in (
            ('dictionary',{'q':'test'},'/api/lexemes?q=test&language=ordos'),
            ('auto-match',{},'/api/lexeme-auto-preview?language=ordos')):
            expected=self.call(path)[1]
            response=self.call('/api/task-start',{'kind':kind,'request':{'language':'ordos',**request}})
            self.assertEqual(response[0],200,response)
            state=self.wait(response[1]['id']);self.assertEqual(state['state'],'done',state)
            self.assertEqual(state['result'],expected)


if __name__=='__main__':unittest.main()
