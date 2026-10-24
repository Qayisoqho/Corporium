import json
import unittest
import test_server
import server
from pathlib import Path
from restore_backup import restore


class MetadataTests(unittest.TestCase):
    setUp=test_server.APITests.setUp
    tearDown=test_server.APITests.tearDown
    call=test_server.APITests.call

    def folder(self,name):
        status,r=self.call('/api/save-folder',{'name':name,'metadata':{'place':'调查地点','notes':'备注'}})
        self.assertEqual(status,200)
        return r['id']

    def test_edit_move_delete_and_conflict(self):
        tid=self.call('/api/new-text',{'title':'文本'})[1]['id']
        a=self.folder('调查A');b=self.folder('调查B')
        payload={'id':tid,'revision':0,'title':'新标题','source':'来源','folder_id':a,'metadata':{'speakers':'甲、乙','date':'约2020年','custom':[{'name':'设备','value':'录音机'}]}}
        self.assertEqual(self.call('/api/save-text-info',payload)[0],200)
        self.assertEqual(self.call('/api/save-text-info',payload)[0],400)
        self.assertEqual(self.call('/api/save-text-info',{**payload,'revision':1,'folder_id':b})[0],200)
        self.call('/api/order-folder',{'id':b,'direction':-1})
        self.assertEqual(self.call('/api/folders')[1][0]['id'],b)
        self.call('/api/save-folder',{'id':b,'revision':1,'name':'改名','metadata':{'notes':'新备注'}})
        self.assertEqual(self.call('/api/delete-folder',{'id':b,'revision':2,'confirmed':True})[0],200)
        t=self.call('/api/texts')[1][0]
        self.assertIsNone(t['folder_id'])
        self.assertEqual(json.loads(t['metadata'])['speakers'],'甲、乙')
        self.assertEqual(self.call('/api/entries')[1]['total'],1)

    def test_backup_restore_new_and_old(self):
        fid=self.folder('调查')
        tid=self.call('/api/new-text',{'title':'文本'})[1]['id']
        self.call('/api/save-text-info',{'id':tid,'revision':0,'title':'文本','folder_id':fid,'metadata':{'notes':'保留'}})
        backup=self.call('/api/backup')[1]
        path=Path(self.temp.name)/'backup.json';path.write_text(json.dumps(backup),encoding='utf-8')
        target=Path(self.temp.name)/'restored.db';restore(path,target)
        server.DB=target
        self.assertEqual(self.call('/api/texts')[1][0]['folder_id'],fid)
        self.assertEqual(self.call('/api/folders')[1][0]['name'],'调查')
        backup.pop('folders');backup.pop('text_info');path.write_text(json.dumps(backup),encoding='utf-8')
        old_target=Path(self.temp.name)/'old.db';restore(path,old_target);server.DB=old_target
        self.assertIsNone(self.call('/api/texts')[1][0]['folder_id'])

    def test_merge_preserves_both_metadata(self):
        ids=[self.call('/api/new-text',{'title':name})[1]['id'] for name in ('A','B')]
        folder=self.folder('调查')
        for tid,name in zip(ids,('A','B')):
            self.call('/api/save-text-info',{'id':tid,'revision':0,'title':name,'folder_id':folder,'metadata':{'speakers':name}})
        self.assertEqual(self.call('/api/merge',{'first_id':ids[0],'second_id':ids[1],'title':'合并','counts':[1,1]})[0],200)
        t=self.call('/api/texts')[1][0];m=json.loads(t['metadata'])
        self.assertEqual(t['folder_id'],folder)
        self.assertEqual(m['speakers'],'A')
        self.assertEqual(m['merged_sources'][0]['metadata']['speakers'],'B')
