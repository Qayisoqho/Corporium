import unittest
import test_morpheme_registry

class HomophoneTests(unittest.TestCase):
    for helper in ('setUp','tearDown','call','seed','entries','undo','fixture','link','assign'):
        locals()[helper]=getattr(test_morpheme_registry.MorphemeRegistryTests,helper)
    def test_reading_identity_dedup_and_component_override(self):
        _,x=self.fixture()
        m=self.call('/api/morpheme-save',{'form':'abstract','body':{'readings':['ma55'],'gloss':'麻','status':'confirmed'}})[1]
        self.assertEqual(self.assign(x,create=None,morpheme_id=m['id'],morpheme_revision=m['revision'],components=[{'analysis_id':'a','component_id':'c'},{'analysis_id':'b','component_id':'d'}])[0],200)
        result=self.call('/api/homophones?language=ordos')[1]
        self.assertEqual(len(result['groups']),1,result)
        self.assertEqual(len(result['groups'][0]['items']),1)
        self.assertEqual(len(result['groups'][0]['items'][0]['sources']),2)
        x['body']['word_structure']['analyses'][1]['components'][0]['readings']=['ma21']
        self.assertEqual(self.call('/api/lexeme-save',x)[0],200)
        result=self.call('/api/homophones?language=ordos')[1]
        self.assertEqual({g['reading'] for g in result['groups']},{'ma55','ma21'})
        self.assertFalse(any('待核对' in r['reason'] for r in result['review']))

    def test_missing_fallback_unorganized_and_language_scope(self):
        _,x=self.fixture()
        result=self.call('/api/homophones?language=ordos')[1]
        self.assertEqual(result['total'],0)
        self.assertEqual(result['review_total'],2)
        result=self.call('/api/homophones?language=ordos&fallback=true&only_multiple=true')[1]
        self.assertEqual(result['total'],1)
        self.assertEqual(len(result['groups'][0]['items']),2)
        self.assertTrue(all(r['provisional'] for r in result['groups'][0]['items']))
        self.assertEqual(self.call('/api/homophones?language=all')[0],400)
        other=self.call('/api/save-language',{'name':'另一语言','metadata':{}})[1]['id']
        self.assertEqual(self.call('/api/homophones?language='+other)[1]['total'],0)
        self.assertNotIn('readings',self.call('/api/lexeme?id='+x['id'])[1]['body']['word_structure']['analyses'][0]['components'][0])

    def test_unicode_multiple_writings_and_reading_preservation(self):
        t=self.call('/api/writing-save',{'name':'汉字','font':'Junicode'})[1]
        m=self.call('/api/morpheme-save',{'form':'a','body':{'readings':['a\u0301','á','a21'],'writings':[{'type_id':t['id'],'text':'阿'}]}})[1]
        n=self.call('/api/morpheme-save',{'form':'b','body':{'readings':['á'],'gloss':'另一语素'}})[1]
        result=self.call('/api/homophones?language=ordos&writing='+t['id'])[1]
        self.assertEqual(result['total'],2)
        group=next(g for g in result['groups'] if g['reading']=='á')
        self.assertEqual(len(group['items']),2)
        self.assertEqual(next(r for r in group['items'] if r['identity']==m['id'])['writings'][0]['text'],'阿')
        self.assertEqual(self.call('/api/morpheme?id='+m['id'])[1]['body']['readings'],['a\u0301','á','a21'])
        self.assertEqual(self.call('/api/writing-delete',{'id':t['id'],'revision':t['revision'],'confirmed':True})[0],400)
        self.assertEqual(self.call('/api/morpheme-save',{'form':'bad','body':{'readings':'not a list'}})[0],400)

    def test_readings_and_writings_survive_language_exchange(self):
        _,x=self.fixture();t=self.call('/api/writing-save',{'name':'汉字','font':'Junicode'})[1]
        c=x['body']['word_structure']['analyses'][0]['components'][0]
        c.update(readings=['ma55'],writings=[{'type_id':t['id'],'text':'麻'}])
        x=self.call('/api/lexeme-save',x)[1]
        m=self.call('/api/morpheme-save',{'form':'ma','body':{'readings':['ma55'],'writings':c['writings']}})[1]
        self.assertEqual(self.assign(x,create=None,morpheme_id=m['id'],morpheme_revision=m['revision'])[0],200)
        bundle=self.call('/api/export-language?language=ordos')[1]
        other=self.call('/api/save-language',{'name':'副本','metadata':{}})[1]['id']
        code,result=self.call('/api/import-language',{'_language':other,'bundle':bundle});self.assertEqual(code,200,result)
        data=self.call('/api/homophones?language='+other)[1]
        self.assertEqual(data['groups'][0]['reading'],'ma55')
        row=data['groups'][0]['items'][0]
        self.assertNotEqual(row['identity'],m['id'])
        self.assertEqual(row['writings'][0]['text'],'麻')
        self.assertNotEqual(row['writings'][0]['type_id'],t['id'])

    def test_empty_readings_do_not_invalidate_legacy_snapshot(self):
        e,x=self.fixture();self.assertEqual(self.link(e,x)[0],200)
        x['body']['word_structure']['analyses'][0]['components'][0]['readings']=[]
        self.assertEqual(self.call('/api/lexeme-save',x)[0],200)
        uid=e['words'][0]['morphemes'][0]['unit_id']
        self.assertFalse(self.call('/api/unit-dictionary?id='+uid)[1]['link']['component_review'])

    def test_pagination_and_reading_search_include_review(self):
        import json,server
        with server.connect(audit=False) as db:
            for i in range(45):db.execute('INSERT INTO morphemes VALUES(?,?,?,?,?,1)',(str(i),'ordos','form'+str(i),1,json.dumps({'readings':['r%02d'%i],'status':'pending'})))
        result=self.call('/api/homophones?language=ordos&page=2&review_page=2')[1]
        self.assertEqual((result['total'],len(result['groups']),result['review_total'],len(result['review'])),(45,5,0,0))
        result=self.call('/api/homophones?language=ordos&q=r04')[1]
        self.assertEqual((result['total'],result['review_total']),(1,0))

    def test_review_count_keeps_record_missing_selected_writing_without_inventing_text(self):
        han=self.call('/api/writing-save',dict(name='汉字',font='Junicode'))[1]
        roman=self.call('/api/writing-save',dict(name='转写',font='Junicode'))[1]
        m=self.call('/api/morpheme-save',dict(form='ma',body=dict(gloss='麻',writings=[dict(type_id=roman['id'],text='ma')])))[1]
        before=self.call('/api/morpheme?id='+m['id'])[1]
        result=self.call('/api/homophones?language=ordos&writing='+han['id'])[1]
        self.assertEqual((result['review_total'],len(result['review'])),(1,1))
        row=result['review'][0]
        self.assertEqual(row['identity'],m['id'])
        self.assertEqual(row['writings'],[])
        self.assertIn('缺少读音',row['reason'])
        self.assertEqual(self.call('/api/morpheme?id='+m['id'])[1],before)

