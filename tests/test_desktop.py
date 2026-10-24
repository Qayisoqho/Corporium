import json
from pathlib import Path
import sqlite3
import tempfile
import threading
import unittest
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
        with server.connect() as db:self.assertEqual(db.execute('SELECT COUNT(*) FROM entries').fetchone()[0],1)
        with self.assertRaises(ValueError):self.projects.create(path)
        with self.assertRaises(ValueError):self.projects.open(self.root/'missing')
        self.assertEqual(self.projects.current,path)
        self.assertEqual(desktop.Projects(self.root/'settings').status()['recent'],[str(path)])

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
            with opener.open(base+'/desktop-bootstrap?token=secret') as r:self.assertIn('data-project-action="new"',r.read().decode())
            for page in ('/licenses','/license-notices.js','/license-notices.css','/style.css','/licenses/catalog','/licenses/developer-font'):
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
