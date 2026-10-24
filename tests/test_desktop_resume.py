"""Remember a successful project and resume it without trapping startup."""
import json
from pathlib import Path
from unittest.mock import patch
import unittest

import desktop
import server
import test_desktop


class DesktopResumeTests(unittest.TestCase):
    setUp=test_desktop.DesktopTests.setUp
    tearDown=test_desktop.DesktopTests.tearDown

    def test_last_successful_project_reopens_with_home_resources(self):
        path=self.root/'上次项目'
        self.projects.create(path)
        server.import_text('Title','','#pass([ipa], (([a],[G]),), [translation])')
        saved=json.loads(self.projects.file.read_text(encoding='utf-8'))
        self.assertEqual(saved['last_project'],str(path))
        resumed=desktop.Projects(self.root/'settings')
        self.assertTrue(resumed.restore_last())
        self.assertEqual(resumed.current,path)
        self.assertTrue(resumed.generation)
        self.assertTrue(list((path/'data/backups').glob('before-desktop-*.sqlite3')))
        with server.connect(audit=False) as db:
            self.assertEqual(db.execute('SELECT count(*) FROM entries').fetchone()[0],1)
        handler=object.__new__(desktop.make_handler(resumed,'secret'))
        handler.path='/'
        handler.headers={'Cookie':'corporium=secret'}
        out=[]
        handler.send=lambda data,code=200,mime=None:out.append((code,data,mime))
        handler.do_GET()
        self.assertEqual(out[0][0],200)
        self.assertIn('/home.js',out[0][1])
        self.assertNotIn('id="desktop-recent"',out[0][1])

    def test_legacy_recent_list_restores_first_project(self):
        path=self.root/'legacy'
        self.projects.create(path)
        self.projects.file.write_text(json.dumps(dict(recent=[str(path)],other='keep')),encoding='utf-8')
        resumed=desktop.Projects(self.root/'settings')
        self.assertTrue(resumed.restore_last())
        self.assertEqual(resumed.current,path)
        self.assertEqual(resumed.settings['last_project'],str(path))
        self.assertEqual(resumed.settings['other'],'keep')

    def test_missing_last_project_does_not_open_a_different_recent_project(self):
        path=self.root/'valid'
        self.projects.create(path)
        missing=self.root/'moved'
        self.projects.file.write_text(json.dumps(dict(last_project=str(missing),recent=[str(path)])),encoding='utf-8')
        resumed=desktop.Projects(self.root/'settings')
        original=server.DB
        with self.assertLogs(level='ERROR'):self.assertFalse(resumed.restore_last())
        self.assertIsNone(resumed.current)
        self.assertEqual(server.DB,original)
        self.assertFalse(missing.exists())
        self.assertIn('无法打开上次的项目',resumed.status()['startup_error'])
        resumed.open(path)
        self.assertEqual(resumed.status()['startup_error'],'')

    def test_corrupt_database_falls_back_and_remains_unchanged(self):
        project=self.root/'corrupt'
        (project/'data').mkdir(parents=True)
        bad=project/'data/corpus.sqlite3'
        bad.write_bytes(b'corrupted database')
        self.projects.file.write_text(json.dumps(dict(last_project=str(project))),encoding='utf-8')
        resumed=desktop.Projects(self.root/'settings')
        with self.assertLogs(level='ERROR'):self.assertFalse(resumed.restore_last())
        self.assertIsNone(resumed.current)
        self.assertEqual(bad.read_bytes(),b'corrupted database')

    def test_invalid_or_missing_settings_do_not_block_project_selection(self):
        for value in ('[]','null','{broken','{"recent": "bad", "last_project": 2}',
                      '{"recent": [null, 1, "", "   "]}'):
            with self.subTest(value=value):
                self.projects.file.write_text(value,encoding='utf-8')
                resumed=desktop.Projects(self.root/'settings')
                self.assertFalse(resumed.restore_last())
                self.assertEqual(resumed.status()['recent'],[])
                self.assertEqual(resumed.status()['startup_error'],'')

    def test_failed_settings_write_preserves_last_successful_project(self):
        path=self.root/'first'
        self.projects.create(path)
        prior=dict(self.projects.settings)
        generation=self.projects.generation
        old_db=server.DB
        with patch.object(Path,'replace',side_effect=OSError('settings read-only')):
            with self.assertRaises(OSError):self.projects.create(self.root/'second')
        self.assertEqual(self.projects.settings,prior)
        self.assertEqual(server.DB,old_db)
        self.assertEqual(self.projects.current,path)
        self.assertEqual(self.projects.generation,generation)
        self.assertEqual(json.loads(self.projects.file.read_text(encoding='utf-8'))['last_project'],str(path))

    def test_successful_switch_is_the_next_launch_target(self):
        self.projects.create(self.root/'first')
        self.projects.create(self.root/'second')
        resumed=desktop.Projects(self.root/'settings')
        self.assertTrue(resumed.restore_last())
        self.assertEqual(resumed.current,self.root/'second')
        self.assertEqual(resumed.settings['recent'],[str(self.root/'second'),str(self.root/'first')])

    def test_main_uses_last_project_only_without_an_explicit_project(self):
        # Entry-point wiring is exercised up to the local HTTP service boundary;
        # neither a real window nor an unconfigured project may be opened.
        root=self.root/'launch'
        with patch.object(desktop.logging,'basicConfig'),patch.object(desktop.sys,'argv',['Corporium.exe']),patch.dict(desktop.os.environ,{'LOCALAPPDATA':str(root)}),\
             patch.object(desktop.ctypes,'WinDLL') as dll,patch.object(desktop.ctypes,'get_last_error',return_value=0),\
             patch.object(desktop.Projects,'restore_last') as restore,patch.object(server,'ThreadingHTTPServer',side_effect=RuntimeError('stop before server')):
            dll.return_value.CreateMutexW.return_value=None
            with self.assertRaisesRegex(RuntimeError,'stop before server'):desktop.main()
            restore.assert_called_once_with()
        with patch.object(desktop.logging,'basicConfig'),patch.object(desktop.sys,'argv',['Corporium.exe','--project','explicit']),patch.dict(desktop.os.environ,{'LOCALAPPDATA':str(root)}),\
             patch.object(desktop.ctypes,'WinDLL') as dll,patch.object(desktop.ctypes,'get_last_error',return_value=0),\
             patch.object(desktop.Projects,'restore_last') as restore,patch.object(desktop.Projects,'open') as opened,\
             patch.object(server,'ThreadingHTTPServer',side_effect=RuntimeError('stop before server')):
            dll.return_value.CreateMutexW.return_value=None
            with self.assertRaisesRegex(RuntimeError,'stop before server'):desktop.main()
            restore.assert_not_called()
            opened.assert_called_once_with('explicit')

    def test_smoke_restart_exercises_resume_without_recreating_the_project(self):
        with patch.object(desktop.logging,'basicConfig'),patch.object(desktop.sys,'argv',['Corporium.exe','--smoke-test',str(self.root/'smoke')]),\
             patch.object(desktop.Projects,'restore_last',return_value=True) as restore,patch.object(desktop.Projects,'create') as create,\
             patch.object(server,'ThreadingHTTPServer',side_effect=RuntimeError('stop before server')):
            with self.assertRaisesRegex(RuntimeError,'stop before server'):desktop.main()
            restore.assert_called_once_with()
            create.assert_not_called()


if __name__=='__main__':unittest.main()
