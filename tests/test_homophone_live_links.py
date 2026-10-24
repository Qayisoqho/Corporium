import json,unittest
import server
import test_homophones

class HomophoneLiveLinksTests(unittest.TestCase):
    for name in ('setUp','tearDown','call','seed','entries','fixture','assign','undo'):
        locals()[name]=getattr(test_homophones.HomophoneTests,name)

    def test_reassociation_and_deleted_component_do_not_create_review_tasks(self):
        _,x=self.fixture()
        first=self.call('/api/morpheme-save',{'form':'old','body':{'readings':['ma55'],'gloss':'旧'}})[1]
        second=self.call('/api/morpheme-save',{'form':'new','body':{'readings':['pa21'],'gloss':'新'}})[1]
        code,result=self.assign(x,create=None,morpheme_id=first['id'],morpheme_revision=first['revision']);self.assertEqual(code,200,result)
        x=self.call('/api/lexeme?id='+x['id'])[1];link=self.call('/api/morpheme-components?id='+x['id'])[1]['items'][0]['link']
        code,result=self.assign(x,create=None,morpheme_id=second['id'],morpheme_revision=second['revision'],components=[{'analysis_id':'a','component_id':'c','revision':link['revision']}]);self.assertEqual(code,200,result)
        code,data=self.call('/api/homophones?language=ordos');self.assertEqual(code,200,data)
        self.assertFalse(any('核对' in r['reason'] for r in data['review']))
        x=self.call('/api/lexeme?id='+x['id'])[1];x['body']['word_structure']['analyses']=x['body']['word_structure']['analyses'][1:]
        code,x=self.call('/api/lexeme-save',x);self.assertEqual(code,200,x)
        # The historical relation still exists for dictionary history and undo.
        with server.connect(audit=False) as db:self.assertEqual(db.execute('SELECT count(*) FROM morpheme_components WHERE morpheme_id=?',(second['id'],)).fetchone()[0],1)
        code,data=self.call('/api/homophones?language=ordos');self.assertEqual(code,200,data)
        self.assertFalse(any(r.get('origin')=='旧组分' or '核对' in r['reason'] or '已删除' in r['reason'] for r in data['review']))
        self.assertEqual(self.call('/api/homophone-words?language=ordos&identity='+second['id'])[1]['total'],0)
        self.assertEqual(self.undo()[0],200)
        self.assertEqual(self.call('/api/homophone-words?language=ordos&identity='+second['id'])[1]['total'],1)
        self.assertEqual(self.undo('redo')[0],200)
        self.assertEqual(self.call('/api/homophone-words?language=ordos&identity='+second['id'])[1]['total'],0)
