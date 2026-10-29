import json
import unittest
from urllib.parse import urlencode
import server
import test_replace_layers as layers


class CustomSearchTests(unittest.TestCase):
    for name in ('setUp','tearDown','call','api','source','detail','args','entry','undo','layer','data','annotate'):
        locals()[name]=getattr(layers.LayerReplaceTests,name)

    def results(self,kind,query,field='all',**extra):
        path='entries' if kind=='corpus' else 'example-library'
        return self.api(path+'?'+urlencode(dict(q=query,field=field,source='independent',language='ordos',**extra)))

    def test_live_word_sentence_hidden_layers_explicit_filter_and_modes(self):
        a=self.layer('逐词');b=self.layer('隐藏','ipa',visible=False,searchable=False)
        for kind in ('corpus','independent'):
            src=self.source(kind,[(kind,'ROOT')]);self.annotate(src,[(a,0,'École'),(b,None,'Hidden')])
            for field in ('all','layers','layer:'+a):
                result=self.results(kind,'e\u0301COLE',field);self.assertEqual(result['total'],1)
                if kind=='corpus':self.assertEqual(result['tokens'],1)
            self.assertEqual(self.results(kind,'Hidden')['total'],0)
            self.assertEqual(self.results(kind,'Hidden','layer:'+b)['total'],1)
            self.assertEqual(self.results(kind,'cole','layer:'+a,mode='exact')['total'],0)
            self.assertEqual(self.results(kind,'Éc','layer:'+a,mode='prefix')['total'],1)
            self.assertEqual(self.results(kind,'ÉCOLE','layer:'+a,case='true')['total'],0)
            with server.connect(audit=False) as db:db.execute('INSERT INTO annotation_cells VALUES(?,?,?,?,?,?,1)',('lost-'+kind,kind,src['id'],'missing',a,'ORPHAN'))
            self.assertEqual(self.results(kind,'ORPHAN','layer:'+a)['total'],0)

    def test_dictionary_writings_are_found_only_via_current_associations(self):
        t=self.api('writing-save',dict(name='汉字',font='Junicode'))['id']
        x=self.entry('home','HOUSE',orthographies=[dict(type_id=t,text='房屋',label='汉字',font='Junicode')],word_structure=dict(analyses=[dict(components=[dict(form='part',writings=[dict(type_id=t,text='部件')])])]))
        for kind in ('corpus','independent'):
            src=self.source(kind,[('home'+kind,'HOUSE')]);u=x['body']['usages'][0]
            self.api('segmentation-link',dict(**self.args(src),word=0,key='@word',link_revision=0,lexeme_id=x['id'],lexeme_revision=x['revision'],usage_id=u['id'],sense_id=u['senses'][0]['id']))
            for field in ('all','writings','writing:'+t):self.assertEqual(self.results(kind,'房屋',field)['total'],1)
            self.assertEqual(self.results(kind,'部件','writing:'+t)['total'],1)
            self.assertEqual(self.results(kind,'房屋','form')['total'],0)
        catalog=self.api('sentence-search-fields')['fields'];self.assertIn('writing:'+t,{f['id'] for f in catalog})
        other=self.api('save-language',dict(name='Other',metadata={}))['id']
        self.assertEqual(self.call('/api/entries?'+urlencode(dict(language=other,q='房屋',field='writing:'+t)))[0],400)

    def test_morpheme_search_includes_associated_sentence_layers(self):
        a=self.layer('田野笔记');m=self.api('morpheme-save',dict(form='home',body=dict(gloss='HOUSE')))
        src=self.source('independent',[('home','HOUSE')]);self.annotate(src,[(a,0,'稀有标记')])
        self.api('segmentation-link',dict(**self.args(src),word=0,key='@word',link_revision=0,lexeme_id=m['id'],lexeme_revision=m['revision'],usage_id='@morpheme',sense_id='@main'))
        for spec in ({},{'field':'layer:'+a}):
            result=self.api('morphemes?'+urlencode(dict(q='稀有标记',search=json.dumps(spec))))
            self.assertEqual([r['id'] for r in result['items']],[m['id']])
        self.assertIn('layer:'+a,{f['id'] for f in self.api('morpheme-search-options')['fields']})

    def test_survey_search_and_locate_include_hidden_layers_and_linked_spellings(self):
        a=self.layer('附注');src=self.source('independent',[('source','ROOT')]);self.annotate(src,[(a,0,'调查专用标记')])
        node=self.api('survey-save',dict(title='问题',kind='question',body={},version=self.api('survey?language=ordos')['version']))
        self.api('survey-evidence',dict(node_id=node['id'],kind='independent',record_id=src['id'],body={},version=self.api('survey?language=ordos')['version']))
        result=self.api('survey-search?'+urlencode(dict(q='专用标记',scope='examples',language='ordos')))
        self.assertEqual(result['total'],1);item=result['items'][0]
        self.assertIn('layers',{f['field'] for f in item['fields']})
        target=self.api('survey-locate?'+urlencode(dict(q='专用标记',scope='examples',language='ordos',evidence_id=item['evidence_id'],field='layers')))
        self.assertTrue(target['matched']);self.assertIn('专用标记',target['text'])
        specific=self.api('survey-search?'+urlencode(dict(q='专用标记',scope='layer:'+a,language='ordos')))
        self.assertEqual(specific['total'],1)

    def test_group_citation_search_uses_each_members_live_custom_cells(self):
        import uuid
        a=self.layer('组内层');one=self.source('independent',[('first','ROOT')]);two=self.source('independent',[('second','ROOT')])
        self.annotate(two,[(a,0,'组成员隐藏信息')])
        group=self.api('example-group-save',dict(body=dict(name='测试组',context='',numbering='letters'),members=[dict(example_id=s['id'],role='') for s in (one,two)]))
        node=self.api('survey-save',dict(title='整组问题',kind='question',body={},version=self.api('survey?language=ordos')['version']))
        with server.connect() as db:db.execute('INSERT INTO survey_evidence VALUES(?,?,?,?,?,?,?,1)',(str(uuid.uuid4()),'ordos',node['id'],'independent-group',group['id'],0,'{}'))
        result=self.api('survey-search?'+urlencode(dict(q='隐藏信息',scope='layer:'+a,language='ordos')))
        self.assertEqual(result['total'],1);self.assertEqual(result['items'][0]['kind'],'independent-group')

    def test_all_fields_uses_the_sentences_actual_language_inside_the_scoped_text(self):
        other=self.api('save-language',dict(name='Other',metadata={}))['id']
        layer=self.layer('他语言附注',_language=other)
        src=self.source('corpus',[('mixed','ROOT')])
        with server.connect() as db:
            row=db.execute('SELECT body FROM entries WHERE id=?',(src['id'],)).fetchone();body=json.loads(row[0]);body['language_id']=other
            db.execute('UPDATE entries SET body=?,revision=revision+1 WHERE id=?',(json.dumps(body),src['id']))
        self.annotate(src,[(layer,0,'实际语言附加值')])
        self.assertEqual(self.results('corpus','实际语言附加值')['total'],1)
        self.assertEqual(self.api('entries?'+urlencode(dict(q='实际语言附加值',language=other)))['total'],0)
