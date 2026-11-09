import json
import hashlib
from pathlib import Path
import sqlite3
import tempfile
import threading
import unittest
from types import SimpleNamespace
from unittest.mock import patch
import urllib.request
import urllib.error
from http.cookiejar import CookieJar
import desktop
import server
import test_server

class DesktopTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.root=Path(self.temp.name)
        self.old_db=server.DB;self.old_font=server.font_catalog.ROOT
        self.projects=desktop.Projects(self.root/'settings')
    def tearDown(self):
        server.DB=self.old_db;server.font_catalog.ROOT=self.old_font;server.font_catalog._catalog=None
        self.temp.cleanup()

    def test_project_creation_reopen_and_preservation(self):
        path=self.root/'项目';self.projects.create(path)
        server.import_text('Text','','#pass([ipa], (([word],[N]),), [translation])')
        self.projects.open(path)
        self.assertEqual(server.DB,path/'data'/'corpus.sqlite3')
        self.assertTrue(list((path/'data'/'backups').glob('before-desktop-*.sqlite3')))
        with server.connect() as db:
            self.assertEqual(db.execute('SELECT COUNT(*) FROM entries').fetchone()[0],1)
            self.assertEqual(db.execute('SELECT name FROM languages WHERE id=?',('ordos',)).fetchone()[0],'Ordos / 鄂尔多斯')
        with self.assertRaises(ValueError):self.projects.create(path)
        with self.assertRaises(ValueError):self.projects.open(self.root/'missing')
        self.assertEqual(self.projects.current,path)
        self.assertEqual(desktop.Projects(self.root/'settings').status()['recent'],[str(path)])

    def test_bundled_example_is_a_separate_project_and_opens_in_telira(self):
        import journal
        import language_exchange
        source=desktop.ASSETS/'packaging'/'examples'/'Telira.corporium'
        original=hashlib.sha256(source.read_bytes()).hexdigest()
        bundle=language_exchange.read(source)
        try:
            expected=language_exchange.info(bundle)
            catalogs={(r['kind'],r['name']) for r in bundle.get('category_classes',[]) if r['kind']!='_seed'}
        finally:bundle.close()
        scope=journal.scope.get();action=journal.action.get();path=self.root/'Tëlira example';path.mkdir()
        result=self.projects.create_example(path)
        self.assertEqual(result['project'],str(path))
        self.assertEqual(self.projects.current,path)
        self.assertEqual(journal.scope.get(),scope)
        self.assertEqual(journal.action.get(),action)
        self.assertTrue((path/'font'/'Junicode').is_dir())
        with server.connect(audit=False) as db:
            languages=list(db.execute('SELECT id,name FROM languages'))
            self.assertEqual(len(languages),1)
            self.assertEqual(languages[0]['name'],'Tëlira')
            self.assertNotEqual(languages[0]['id'],'ordos')
            self.assertEqual(db.execute('SELECT COUNT(*) FROM lexemes').fetchone()[0],expected['lexemes'])
            self.assertEqual(db.execute('SELECT COUNT(*) FROM texts').fetchone()[0],expected['texts'])
            self.assertEqual(db.execute('SELECT COUNT(*) FROM entries').fetchone()[0],expected['sentences'])
            self.assertEqual({(r['kind'],r['name']) for r in db.execute("SELECT kind,name FROM category_classes WHERE kind!='_seed'")},catalogs)
            self.assertEqual(db.execute('SELECT COUNT(*) FROM gloss_bindings').fetchone()[0],db.execute('SELECT COUNT(*) FROM lexical_links WHERE sense_id IS NOT NULL').fetchone()[0])
            self.assertGreater(db.execute('SELECT COUNT(*) FROM gloss_bindings').fetchone()[0],0)
            self.assertEqual(db.execute('PRAGMA integrity_check').fetchone()[0],'ok')
            self.assertEqual(db.execute('PRAGMA foreign_key_check').fetchall(),[])
        self.assertEqual(hashlib.sha256(source.read_bytes()).hexdigest(),original)
        reopened=desktop.Projects(self.root/'settings');self.assertTrue(reopened.restore_last())
        self.assertEqual(reopened.current,path)
        with server.connect(audit=False) as db:self.assertEqual(db.execute('SELECT name FROM languages').fetchone()[0],'Tëlira')

    def test_example_failure_preserves_selected_folder_and_active_project(self):
        import journal
        self.projects.create(self.root/'first')
        old_db=server.DB;generation=self.projects.generation;settings=dict(self.projects.settings);scope=journal.scope.get()
        target=self.root/'example';target.mkdir()
        def fail(db,*args):
            db.execute("INSERT INTO languages VALUES('partial','partial','{}',1)")
            journal.scope.set('partial')
            raise ValueError('import failed')
        with patch('language_exchange.import_new',side_effect=fail):
            with self.assertRaisesRegex(ValueError,'import failed'):self.projects.create_example(target)
        self.assertEqual(list(target.iterdir()),[])
        self.assertEqual(list(self.root.glob('.corporium-example-*')),[])
        self.assertEqual(server.DB,old_db);self.assertEqual(journal.scope.get(),scope)
        self.assertEqual(self.projects.current,self.root/'first');self.assertEqual(self.projects.generation,generation)
        self.assertEqual(self.projects.settings,settings)
        (target/'keep.txt').write_text('keep',encoding='utf-8')
        with self.assertRaises(ValueError):self.projects.create_example(target)
        self.assertEqual((target/'keep.txt').read_text(encoding='utf-8'),'keep')
        with patch.object(desktop,'ASSETS',self.root):
            with self.assertRaisesRegex(ValueError,'Tëlira'):self.projects.create_example(self.root/'missing-example')
        self.assertFalse((self.root/'missing-example').exists())

    def test_example_bridge_uses_native_folder_selection_and_handles_cancel(self):
        bridge=desktop.Bridge(self.projects);bridge._origin='http://127.0.0.1:8980'
        dialog=SimpleNamespace(FOLDER='folder',OPEN='open')
        native=SimpleNamespace(FileDialog=dialog)
        window=SimpleNamespace(get_current_url=lambda:bridge._origin+'/',create_file_dialog=lambda kind:None)
        bridge._window=window
        with patch.dict('sys.modules',{'webview':native}),patch.object(self.projects,'create_example') as create:
            self.assertEqual(bridge.project_action('example'),{'cancelled':True});create.assert_not_called()
            chosen=str(self.root/'chosen')
            window.create_file_dialog=lambda kind:([chosen] if kind==dialog.FOLDER else self.fail('expected a folder chooser'))
            self.assertEqual(bridge.project_action('example','ignored'),{'ok':True})
            create.assert_called_once_with(chosen)

    def test_restore_new_project(self):
        self.projects.create(self.root/'original')
        data=test_server.APITests().call('/api/backup')[1]
        backup=self.root/'backup.json';backup.write_text(json.dumps(data),encoding='utf-8')
        self.projects.create(self.root/'restored',backup)
        self.assertTrue((self.root/'restored'/'data'/'corpus.sqlite3').exists())

    def test_failed_switch_keeps_active_project(self):
        self.projects.create(self.root/'first');original=server.DB;generation=self.projects.generation
        with patch.object(self.projects,'remember',side_effect=OSError('settings read-only')):
            with self.assertRaises(OSError):self.projects.create(self.root/'second')
        self.assertEqual(server.DB,original);self.assertEqual(self.projects.current,self.root/'first')
        self.assertEqual(self.projects.generation,generation)

    def test_session_authentication_and_empty_project(self):
        http=server.ThreadingHTTPServer(('127.0.0.1',0),desktop.make_handler(self.projects,'secret'))
        thread=threading.Thread(target=http.serve_forever,daemon=True);thread.start()
        base='http://127.0.0.1:'+str(http.server_port)
        opener=urllib.request.build_opener(urllib.request.ProxyHandler({}),urllib.request.HTTPCookieProcessor(CookieJar()))
        try:
            with self.assertRaises(urllib.error.HTTPError) as e:opener.open(base+'/api/backup')
            self.assertEqual(e.exception.code,403)
            with opener.open(base+'/desktop-bootstrap?token=secret') as r:
                html=r.read().decode()
                self.assertIn('data-project-action="new"',html)
                self.assertIn('data-project-action="example"',html)
            for page in ('/licenses','/license-notices.js','/license-notices.css','/style.css','/workbench.css','/ui-standards.css','/i18n-settings.js','/licenses/catalog','/licenses/developer-font',
                         '/font/Junicode/Junicode.ttf','/font/Junicode/Junicode-Italic.ttf','/font/Junicode/Junicode-Bold.ttf','/font/Junicode/Junicode-BoldItalic.ttf'):
                with opener.open(base+page) as r:self.assertEqual(r.status,200)
            with opener.open(base+'/licenses/document?id=Microsoft-WebView2-Runtime-LICENSE.txt') as r:
                self.assertIn('DISTRIBUTABLE CODE',json.load(r)['text'])
            with self.assertRaises(urllib.error.HTTPError) as e:opener.open(base+'/api/backup')
            self.assertEqual(e.exception.code,409)
            with desktop.LOCK:self.projects.create(self.root/'project')
            opener.addheaders=[('X-Corporium-Project',self.projects.generation)]
            with opener.open(base+'/api/languages') as r:self.assertTrue(json.load(r))
            with opener.open(base+'/api/languages?language=old-project-language') as r:self.assertTrue(json.load(r))
            with opener.open(base+'/') as r:
                html=r.read().decode()
                self.assertIn('const desktopProjectKey=',html)
                first_key=html.split('const desktopProjectKey=',1)[1].split(';',1)[0]
            request=urllib.request.Request(base+'/api/new-text',data=b'{"title":"bad"}',headers={'Content-Type':'application/json','Origin':'https://example.com'})
            with self.assertRaises(urllib.error.HTTPError) as e:opener.open(request)
            self.assertEqual(e.exception.code,403)
            with desktop.LOCK:self.projects.create(self.root/'other')
            with self.assertRaises(urllib.error.HTTPError) as e:opener.open(base+'/api/languages')
            self.assertEqual(e.exception.code,409)
            opener.addheaders=[('X-Corporium-Project',self.projects.generation)]
            with opener.open(base+'/') as r:
                other_key=r.read().decode().split('const desktopProjectKey=',1)[1].split(';',1)[0]
            self.assertNotEqual(first_key,other_key)
            with desktop.LOCK:self.projects.open(self.root/'project')
            with opener.open(base+'/') as r:
                reopened_key=r.read().decode().split('const desktopProjectKey=',1)[1].split(';',1)[0]
            self.assertEqual(first_key,reopened_key)
        finally:http.shutdown();http.server_close();thread.join()
