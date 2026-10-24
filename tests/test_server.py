import io
import json
import tempfile
import unittest
from pathlib import Path
import sys
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
import server
from restore_backup import restore


class APITests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory()
        self.old=server.DB
        server.DB=Path(self.temp.name)/'corpus.sqlite3'
        server.init()

    def tearDown(self):
        server.DB=self.old
        self.temp.cleanup()

    def call(self,path,body=None,origin=None):
        handler=object.__new__(server.Handler)
        handler.path=path
        payload=json.dumps(body).encode()
        handler.headers={'Content-Type':'application/json','Content-Length':str(len(payload)), 'Host':'127.0.0.1:8765'}
        if origin: handler.headers['Origin']=origin
        handler.rfile=io.BytesIO(payload)
        result=[]
        handler.send=lambda data,code=200,mime=None:result.append((code,data))
        if body is None:handler.do_GET()
        else:handler.do_POST()
        return result[0]

    def test_import_edit_history_conflict_export_backup_restore(self):
        source='#gloss([ipa], (("a-b", [名-dat]),), [翻译])'
        status,result=self.call('/api/import',{'title':'测试','content':source})
        self.assertEqual(status,200)
        self.assertEqual(self.call('/api/import',{'title':'测试','content':source})[1]['duplicate'],True)
        entry=self.call('/api/entries')[1]['items'][0]
        change={**entry,'translation':'修改后的译文','notes':'研究笔记'}
        self.assertEqual(self.call('/api/save',change)[0],200)
        self.assertEqual(self.call('/api/save',change)[0],409)
        history=self.call('/api/history?id='+entry['id'])[1]
        self.assertEqual(history[0]['body']['translation'],'翻译')
        exported=self.call('/api/export?id='+result['id'])[1]
        self.assertIn('修改后的译文',exported)
        self.assertEqual(self.call('/api/export?id='+result['id']+'&original=true')[1],source)
        backup=self.call('/api/backup')[1]
        backup_path=Path(self.temp.name)/'backup.json'
        backup_path.write_text(json.dumps(backup),encoding='utf-8')
        restored=Path(self.temp.name)/'restored.sqlite3'
        restore(backup_path,restored)
        server.DB=restored
        self.assertEqual(self.call('/api/entries')[1]['items'][0]['translation'],'修改后的译文')
        self.assertEqual(len(self.call('/api/history?id='+entry['id'])[1]),1)
        with self.assertRaises(ValueError):restore(backup_path,restored)

    def test_cross_origin_and_invalid_edit(self):
        self.assertEqual(self.call('/api/import',{'title':'x','content':'x'},'https://example.com')[0],403)
        self.call('/api/new-text',{'title':'New'})
        entry=self.call('/api/entries')[1]['items'][0]
        self.assertEqual(self.call('/api/save',{**entry,'ipa':'unclosed [','notes':''})[0],400)
        self.assertEqual(self.call('/api/entries')[1]['items'][0]['revision'],1)

    def test_page_sizes(self):
        self.call('/api/import',{'title':'Pages','content':'\n'.join('#pass([ipa], (([word],[tag]),), [translation])' for _ in range(23))})
        first=self.call('/api/entries?page_size=10')[1]
        second=self.call('/api/entries?page_size=10&page=2')[1]
        last=self.call('/api/entries?page_size=10&page=99')[1]
        self.assertEqual(len(first['items']),10)
        self.assertEqual(second['items'][0]['position'],11)
        self.assertEqual((last['page'],len(last['items'])),(3,3))
        self.assertEqual(len(self.call('/api/entries?page_size=50')[1]['items']),23)
        self.assertEqual(self.call('/api/entries?page_size=0')[0],400)
        self.assertEqual(self.call('/api/entries?mode=prefix&q=wo&field=form')[1]['total'],23)
        self.assertEqual(self.call('/api/entries?mode=suffix&q=wo&field=form')[1]['total'],0)

    def test_add_and_query(self):
        _,t=self.call('/api/new-text',{'title':'New'})
        self.call('/api/add',{'text_id':t['id']})
        self.assertEqual(self.call('/api/entries')[1]['total'],2)
        self.assertEqual(self.call('/api/entries?q=absent')[1]['total'],0)


if __name__=='__main__':unittest.main()
