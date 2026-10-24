import json,os,sqlite3,tempfile,unittest
from pathlib import Path
import backup_policy as policy
import server,test_server

class PolicyTests(unittest.TestCase):
    def setUp(self):self.temp=tempfile.TemporaryDirectory();self.folder=Path(self.temp.name)/'data'/'backups';self.folder.mkdir(parents=True)
    def tearDown(self):self.temp.cleanup()
    def seed(self,n):
        for i in range(n):
            p=self.folder/f'20261013T010000-{i:08x}.json';p.write_text('{}');os.utime(p,(100+i,100+i))
    def test_default_mixed_formats_and_manual_protection(self):
        self.seed(22)
        manual=self.folder/'ordos-backup-2026-10-13.json';manual.write_text('manual')
        unknown=self.folder/'keep.sqlite3';unknown.write_text('manual')
        partial=self.folder/'.automatic.tmp';partial.write_text('pending')
        nested=self.folder/'manual';nested.mkdir();(nested/'20261013T010000-12345678.json').write_text('nested')
        source=sqlite3.connect(':memory:');source.execute('CREATE TABLE test(x)');source.commit()
        try:name=policy.sqlite_snapshot(self.folder,source,'desktop')
        finally:source.close()
        self.assertEqual(policy.status(self.folder)['count'],20)
        self.assertTrue((self.folder/name).exists());self.assertEqual(manual.read_text(),'manual');self.assertTrue(unknown.exists());self.assertTrue(partial.exists());self.assertEqual(len(list(nested.iterdir())),1)
        self.assertFalse((self.folder/'20261013T010000-00000000.json').exists())
    def test_policy_persistence_and_failed_write_preserves_backups(self):
        self.seed(25);r=policy.save_policy(self.folder,10);self.assertEqual(r['count'],10);self.assertEqual(policy.limit(self.folder),10)
        names={p.name for p in policy.candidates(self.folder)}
        def fail(p):p.write_text('partial');raise OSError('disk full')
        with self.assertRaises(OSError):policy.write(self.folder,'20261013T020000-12345678.json',fail)
        self.assertEqual(names,{p.name for p in policy.candidates(self.folder)})
        self.assertFalse(list(self.folder.glob('*.tmp')))
        for bad in (0,-1,True,'20',1000):
            with self.assertRaises(ValueError):policy.save_policy(self.folder,bad)
        name=policy.write_json(self.folder,{'format':'ordos-corpus-v1','entries':[]})
        self.assertEqual(json.loads((self.folder/name).read_text())['format'],'ordos-corpus-v1');self.assertEqual(policy.status(self.folder)['count'],10)

    def test_five_backups_and_legacy_upper_bound(self):
        self.seed(35)
        (self.folder.parent/'backup-policy.json').write_text('{"limit":100}')
        self.assertEqual(policy.limit(self.folder),30)
        self.assertEqual(policy.save_policy(self.folder,5)['count'],5)
        self.assertEqual(policy.limit(self.folder),5)
        for value in (40,50,100):
            with self.assertRaises(ValueError):policy.save_policy(self.folder,value)

class PolicyAPITests(unittest.TestCase):
    setUp=test_server.APITests.setUp
    tearDown=test_server.APITests.tearDown
    call=test_server.APITests.call
    def test_api_and_manual_download_independence(self):
        self.assertEqual(self.call('/api/backup-policy')[1]['limit'],20)
        self.assertEqual(self.call('/api/backup-policy',{'limit':10})[0],200)
        self.assertEqual(self.call('/api/backup-policy',{'limit':2})[0],400)
        for _ in range(3):self.assertEqual(self.call('/api/backup')[0],200)
        self.assertEqual(self.call('/api/backup-policy')[1]['count'],0)
        server.init();self.assertEqual(self.call('/api/backup-policy')[1]['limit'],10)
