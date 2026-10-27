import json
import unittest
import server
import analysis_workspace
import test_analysis_workspace
import test_classes
import test_annotations


class CustomFieldTests(unittest.TestCase):
    setUp=test_analysis_workspace.AnalysisTests.setUp
    tearDown=test_analysis_workspace.AnalysisTests.tearDown
    call=test_analysis_workspace.AnalysisTests.call
    seed=test_analysis_workspace.AnalysisTests.seed
    entries=test_analysis_workspace.AnalysisTests.entries
    word=test_analysis_workspace.AnalysisTests.word
    link=test_analysis_workspace.AnalysisTests.link
    execute=test_analysis_workspace.AnalysisTests.execute
    page=test_analysis_workspace.AnalysisTests.page
    create=test_classes.ClassTests.create
    layer=test_annotations.AnnotationTests.layer
    annotate=test_annotations.AnnotationTests.annotate

    def hits(self,field,value='',**kw):return self.execute(conditions=[dict(field=field,value=value)],**kw)['summary']['hits']

    def test_hidden_layers_explicit_search_orphans_and_snapshot(self):
        e=self.seed();layer=self.layer();self.annotate('corpus',e,layer)
        self.assertEqual(self.call('/api/layer-save',{**layer,'visible':False,'searchable':False})[0],200)
        field='layer_word:'+layer['id']
        self.assertEqual(self.hits(field,'NOUN'),1)
        self.assertEqual(self.hits(field,'noun'),1)
        self.assertEqual(self.hits(field,'noun',case=True),0)
        run=self.execute(field,'NOUN')
        snap=self.call('/api/analysis-save',dict(kind='snapshot',name='fixed',run_id=run['id']))[1]
        e['words']=e['words'][1:];e['notes']='';self.assertEqual(self.call('/api/save',e)[0],200)
        self.assertEqual(self.hits(field,'NOUN'),0)
        self.assertEqual(self.page(snap,snapshot='true')['items'][0]['record']['body']['words'][0]['extra_layers'][0]['value'],'NOUN')

    def test_sentence_layer_combination_and_wrong_anchor(self):
        e=self.seed();code,l=self.call('/api/layer-save',dict(name='译注',font='Junicode',style='normal',anchor='translation'))
        self.assertEqual(code,200,l)
        a=self.call('/api/annotations?kind=corpus&id='+e['id'])[1]
        code,r=self.call('/api/annotation-save',dict(kind='corpus',id=e['id'],revision=a['revision'],before=a['cells'],layers=a['layers'],cells=[dict(unit_id='@sentence',layer_id=l['id'],value='疑问句')]))
        self.assertEqual(code,200,r)
        field='layer_sentence:'+l['id'];self.assertEqual(self.hits(field,'疑问句'),1)
        q=[dict(field=field,value='疑问句'),dict(field='form',value='go',relation='sentence')]
        self.assertEqual(self.execute(conditions=q)['summary']['hits'],1)
        q[1]['relation']='same_word';self.assertEqual(self.call('/api/analysis-run',{'query':{'conditions':q}})[0],400)
        self.assertEqual(self.call('/api/analysis-run',{'query':{'conditions':[{'field':'layer_word:'+l['id']}]}})[0],400)

    def test_class_identity_hierarchy_rename_and_selected_usage(self):
        e=self.seed();x=self.word();root=next(c for c in self.call('/api/classes')[1] if c['kind']=='pos' and c['name']=='名词');child=self.create('具体名词',parent_id=root['id'])
        x['body']['usages'][0]['subclass']=child['name'];code,x=self.call('/api/lexeme-save',x);self.assertEqual(code,200,x)
        self.link(e['words'][0]['unit_id'],x)
        verb=next(c for c in self.call('/api/classes')[1] if c['kind']=='pos' and c['name']=='动词')
        self.assertEqual(self.hits('class:'+root['id']),1)
        self.assertEqual(self.execute(conditions=[dict(field='class:'+root['id'],include_children=False)])['summary']['hits'],0)
        self.assertEqual(self.hits('class:'+verb['id']),0)
        self.assertEqual(self.execute(conditions=[dict(field='class:'+verb['id'],mode='not_belongs')])['summary']['hits'],1)
        # The unlinked second word is unknown, never a negative-classification hit.
        run=self.execute(conditions=[dict(field='class:'+child['id'])])
        self.assertEqual(self.call('/api/analysis-save',dict(kind='query',name='stable',query=run['query']))[0],200)
        self.assertEqual(self.call('/api/class-save',{**child,'name':'实体名词'})[0],200)
        fresh=self.execute(conditions=run['query']['conditions']);self.assertEqual(self.page(fresh)['items'][0]['value'],'实体名词')
        self.assertIn('实体名词',fresh['query']['conditions'][0]['label'])

    def test_writing_usage_tags_valid_links_and_language(self):
        e=self.seed();x=self.word();code,w=self.call('/api/writing-save',dict(name='汉字',font='Junicode'));self.assertEqual(code,200,w)
        x['body']['orthographies']=[dict(type_id=w['id'],label='汉字',text='家',font='Junicode')]
        code,x=self.call('/api/lexeme-save',x);self.assertEqual(code,200,x)
        self.assertEqual(self.hits('writing:'+w['id'],'家'),0)
        self.link(e['words'][0]['unit_id'],x)
        self.assertEqual(self.hits('writing:'+w['id'],'家'),1)
        cls=next(c for c in self.call('/api/classes')[1] if c['kind']=='usage_tag' and c['name']=='语域')
        self.assertEqual(self.hits('usage_tag:'+cls['id'],'文语'),1)
        with server.connect() as db:
            self.assertNotIn("status",{r[1] for r in db.execute("PRAGMA table_info(lexical_links)")});analysis_workspace.invalidate(db)
        self.assertEqual(self.hits('writing:'+w['id'],'家'),1)
        self.assertEqual(self.hits('writing:'+w['id'],'家',confirmed_only=False),1)
        with server.connect() as db:
            db.execute("UPDATE corpus_units SET active=0 WHERE id=?",(e['words'][0]['unit_id'],));analysis_workspace.invalidate(db)
        self.assertEqual(self.hits('writing:'+w['id'],'家',confirmed_only=False),0)

    def test_grammar_class_without_link_and_missing_field(self):
        self.seed();root=self.create('格','grammar');child=self.create('属格','grammar',parent_id=root['id'])
        self.assertEqual(self.call('/api/grammar-save',dict(symbol='GEN',category='属格'))[0],200)
        self.assertEqual(self.hits('class:'+root['id']),1)
        fields=self.call('/api/analysis-fields?language=ordos')[1];self.assertTrue(any(f['field']=='class:'+root['id'] for f in fields))
        for field in ('class:missing','writing:missing','layer_word:missing'):
            self.assertEqual(self.call('/api/analysis-run',{'query':{'conditions':[{'field':field}]}})[0],400)

    def test_custom_combination_and_changed_sentence_language(self):
        e=self.seed();x=self.word();self.link(e['words'][0]['unit_id'],x)
        layer=self.layer();self.annotate('corpus',e,layer)
        c=next(c for c in self.call('/api/classes')[1] if c['kind']=='pos' and c['name']=='名词')
        query=[dict(field='layer_word:'+layer['id'],value='NOUN'),dict(field='class:'+c['id'],relation='same_word'),dict(field='form',value='go',relation='right',min=1,max=1)]
        self.assertEqual(self.execute(conditions=query)['summary']['hits'],1)
        other=self.call('/api/save-language',dict(name='Other',metadata={}))[1]['id']
        with server.connect() as db:
            row=db.execute('SELECT body FROM entries WHERE id=?',(e['id'],)).fetchone();body=json.loads(row[0]);body['language_id']=other
            db.execute('UPDATE entries SET body=? WHERE id=?',(json.dumps(body),e['id']));analysis_workspace.invalidate(db)
        self.assertEqual(self.hits('class:'+c['id']),0)
        self.assertEqual(self.hits('layer_word:'+layer['id'],'NOUN'),0)
        self.assertTrue(all(r['language_id']==other for r in self.call('/api/analysis-fields?language='+other)[1]))
        self.assertEqual(self.call('/api/analysis-run',{'query':{'conditions':[{'field':None}]}})[0],400)

    def test_form_and_morph_classes_respect_selected_analysis(self):
        e=self.seed();x=self.word();m=self.create('第一变格','morph');other=self.create('动词形态','morph')
        x['body']['word_structure']={'memberships':[dict(class_id=m['id'],usage_id=x['body']['usages'][0]['id']),dict(class_id=other['id'],usage_id=x['body']['usages'][1]['id'])]}
        code,x=self.call('/api/lexeme-save',x);self.assertEqual(code,200,x);self.link(e['words'][0]['unit_id'],x)
        self.assertEqual(self.hits('class:'+m['id']),1);self.assertEqual(self.hits('class:'+other['id']),0)
        form=next(c for c in self.call('/api/classes')[1] if c['kind']=='form' and c['name']==x['body']['variants'][0]['kind'])
        self.assertEqual(self.hits('class:'+form['id']),0)
        with server.connect() as db:
            link=db.execute('SELECT id FROM lexical_links').fetchone()[0]
            db.execute('INSERT OR REPLACE INTO morphology_analyses VALUES(?,?,?)',(link,x['body']['variants'][0]['id'],'[]'));analysis_workspace.invalidate(db)
        self.assertEqual(self.hits('class:'+form['id']),1)
