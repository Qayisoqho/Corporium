import json
import unittest
from urllib.parse import urlencode
import server
import analysis_workspace
import test_vocabulary_statistics as vs


class SelectionTests(unittest.TestCase):
    for name in ('setUp','tearDown','call','api','source','detail','args','entry','undo','m','bind','page'):
        locals()[name]=getattr(vs.VocabularyTests,name)

    def run_selection(self,target='morpheme',group_by='entry',query='',**search):
        return self.api('analysis-run',dict(query=dict(kind='counts',vocabulary=dict(target=target,group_by=group_by,query=query,search=search))))
    def profile(self,run,**extra):return self.page(run,vocabulary_view='custom',**extra)['vocabulary']
    def condition(self,field,value='',op='exact'):return dict(field=field,value=value,op=op)
    def class_(self,name,kind='morph',**extra):return self.api('class-save',dict(name=name,kind=kind,**extra))['id']
    def semantic(self,name,**extra):return self.api('dict-org-class-save',dict(name=name,**extra))['id']

    def test_affix_type_suffix_and_dormant_fields(self):
        suffix=self.m('s','affix',affix_position='suffix',affix_function='inflection')
        prefix=self.m('pre','affix',affix_position='prefix')
        root=self.m('na','root',affix_position='suffix')
        for m in (suffix,prefix,root):self.bind(self.source('corpus',[(m['form'],'ROOT')]),m)
        r=self.run_selection(conditions=[self.condition('entry_type','词缀'),self.condition('affix_position','后缀')]);p=self.profile(r)
        self.assertEqual((p['selection']['entries'],p['denominator'],p['rows'][0]['form']),(1,1,'s'))
        all_=self.profile(self.run_selection(group_by='affix_position'))
        self.assertEqual({r['form']:r['count'] for r in all_['rows']},{'后缀':1,'前缀':1,'未分类／未填写':1})
        self.assertTrue(all(r['system_label'] for r in all_['rows']))

    def test_custom_morph_class_filter_descendants_and_grouping(self):
        parent=self.class_('动词变化');child=self.class_('不规则',parent_id=parent)
        m=self.m('na',word_structure=dict(memberships=[dict(class_id=child,parts=[])]))
        self.bind(self.source('independent',[('na','ROOT')]),m)
        p=self.profile(self.run_selection(class_id=parent,group_by='class:morph'))
        self.assertEqual((p['selection']['entries'],p['rows'][0]['form']),(1,'动词变化 / 不规则'))
        self.api('class-save',dict(id=child,revision=1,name='第二类',kind='morph',parent_id=parent))
        fresh=self.profile(self.run_selection(class_id=parent,group_by='class:morph'))
        self.assertEqual(fresh['rows'][0]['form'],'动词变化 / 第二类')

    def test_semantic_multimembership_overlap_and_word_examples(self):
        a=self.semantic('活动');b=self.semantic('言说')
        m=self.m('na',semantic_classes=[a,b]);src=self.source('corpus',[('na-na','ROOT-ROOT')])
        for part in self.detail(src)['body']['words'][0]['morphemes']:self.bind(src,m,key=part['key'])
        run=self.run_selection(group_by='class:semantic');p=self.profile(run)
        self.assertEqual((p['denominator'],p['selection']['words'],len(p['rows'])),(2,1,2))
        self.assertEqual([r['count'] for r in p['rows']],[2,2])
        detail=self.profile(run,vocabulary_item=p['rows'][0]['key'])
        self.assertEqual((detail['example_total'],len(detail['items'])),(1,1))

    def test_lexeme_target_variants_and_native_morpheme_separate(self):
        x=self.entry('na','ROOT');m=self.m('na');src=self.source('independent',[('na','ROOT')])
        self.bind(src,m)
        src=self.source('corpus',[('na','ROOT')]);d=self.detail(src);u=x['body']['usages'][0]
        self.api('segmentation-link',dict(**self.args(src),word=0,key='@word',link_revision=0,lexeme_id=x['id'],lexeme_revision=x['revision'],usage_id=u['id'],sense_id=u['senses'][0]['id']))
        p=self.profile(self.run_selection(target='lexeme'))
        self.assertEqual((p['selection']['entries'],p['denominator'],p['rows'][0]['gloss']),(1,1,'ROOT'))
        self.assertEqual(self.profile(self.run_selection())['denominator'],1)

    def test_entry_fields_any_all_case_and_examples_excluded(self):
        m=self.m('Na',notes='own marker');self.bind(self.source('independent',[('Na','ROOT')]),m)
        self.source('independent',[('other','X')]);r=self.run_selection(query='own marker');self.assertEqual(self.profile(r)['denominator'],1)
        a=self.condition('headword','na');b=self.condition('notes','absent','contains')
        self.assertEqual(self.profile(self.run_selection(conditions=[a,b],combine='any'))['denominator'],1)
        self.assertEqual(self.profile(self.run_selection(conditions=[a,b],combine='all'))['denominator'],0)
        self.assertEqual(self.profile(self.run_selection(query='na',case=True))['denominator'],0)
        with server.connect() as db:
            body=json.loads(db.execute('SELECT body FROM morphemes WHERE id=?',(m['id'],)).fetchone()[0]);body['examples']=[dict(translation='example-only')]
            db.execute('UPDATE morphemes SET body=? WHERE id=?',(json.dumps(body),m['id']));analysis_workspace.invalidate(db)
        self.assertEqual(self.profile(self.run_selection(query='example-only'))['denominator'],0)
        catalog=self.api('vocabulary-options?target=morpheme')
        self.assertFalse(any(f['id'].startswith(('examples','media','layer:')) for f in catalog['fields']))
        self.assertIn('class:morph',{g['id'] for g in catalog['groups']})

    def test_unclassified_homographs_and_zero_frequency_entries(self):
        a=self.m('na');b=self.m('na');self.m('unused')
        for m in (a,b):self.bind(self.source('independent',[('na','ROOT')]),m)
        p=self.profile(self.run_selection());self.assertEqual((p['selection']['eligible_entries'],p['selection']['entries'],len(p['rows'])),(3,2,2))
        p=self.profile(self.run_selection(group_by='class:semantic',class_id='@unclassified'))
        self.assertEqual((p['rows'][0]['form'],p['rows'][0]['entries'],p['rows'][0]['count']),('未分类／未填写',2,2))

    def test_invalid_or_foreign_class_fields_and_targets_rejected(self):
        other=self.api('save-language',dict(name='Other',metadata={}))['id']
        c=self.api('class-save',dict(_language=other,name='foreign',kind='morph'))['id']
        values=[dict(target='bad'),dict(group_by='examples.translation'),dict(group_by='writing:missing'),dict(search=dict(class_id=c)),dict(search=dict(class_id='missing')),dict(search=dict(conditions=[self.condition('examples','x')])),dict(search=dict(conditions=[self.condition('notes','')])),dict(search=dict(case='yes'))]
        for value in values:
            status,result=self.call('/api/analysis-run',dict(query=dict(kind='counts',vocabulary=value)))
            self.assertEqual(status,400,(value,result))

    def test_snapshot_freezes_class_groups_and_original_source(self):
        c=self.semantic('言说');m=self.m('na',semantic_classes=[c]);src=self.source('independent',[('na','ROOT')]);self.bind(src,m)
        run=self.run_selection(group_by='class:semantic',class_id=c)
        snap=self.api('analysis-save',dict(kind='snapshot',name='classes',run_id=run['id']))
        d=self.detail(src);d['body']['words'][0]['form']='changed';self.api('example-save',dict(id=src['id'],revision=d['revision'],body=d['body']))
        frozen=self.profile(snap,snapshot='true');row=frozen['rows'][0]
        detail=self.profile(snap,snapshot='true',vocabulary_item=row['key'])
        self.assertEqual(detail['items'][0]['record']['body']['words'][0]['form'],'na')
        exported=self.api('analysis-export?'+urlencode(dict(id=snap['id'],snapshot='true',language='ordos')))
        self.assertEqual(exported['query']['vocabulary']['search']['class_id'],c)
        self.assertEqual(exported['vocabulary']['selection']['rows'][0]['form'],'言说')

    def test_cache_conditions_and_grouping_are_distinct(self):
        self.assertFalse(self.run_selection()['cached']);self.assertTrue(self.run_selection()['cached'])
        self.assertFalse(self.run_selection(group_by='entry_type')['cached'])
        self.assertFalse(self.run_selection(query='absent')['cached'])

    def test_custom_table_filter_retains_selection_denominator(self):
        for form in ('na','ti'):self.bind(self.source('corpus',[(form,'ROOT')]),self.m(form))
        p=self.profile(self.run_selection(),vocabulary_query='na')
        self.assertEqual((p['total'],p['denominator'],p['rows'][0]['count']),(1,2,1))

    def test_lexeme_review_and_sentence_only_citations_excluded(self):
        x=self.entry('na','ROOT');src=self.source('corpus',[('na','ROOT')]);u=x['body']['usages'][0]
        self.api('segmentation-link',dict(**self.args(src),word=0,key='@word',link_revision=0,lexeme_id=x['id'],lexeme_revision=x['revision'],usage_id=u['id'],sense_id=u['senses'][0]['id']))
        self.api('example-save',dict(body=dict(words=[dict(form='na',gloss='ROOT')],targets=[dict(lexeme_id=x['id'])])))
        self.assertEqual(self.profile(self.run_selection(target='lexeme'))['denominator'],1)
        with server.connect() as db:
            link=db.execute('SELECT id FROM lexical_links WHERE lexeme_id=?',(x['id'],)).fetchone()[0];db.execute('INSERT INTO lexical_reviews VALUES(?,?)',(link,'changed'));analysis_workspace.invalidate(db)
        self.assertEqual(self.profile(self.run_selection(target='lexeme'))['denominator'],0)

    def test_class_selection_does_not_cross_languages_in_all_scope(self):
        from vocabulary_selection import Selection,normalize
        c=self.class_('本语言类');a=self.m('na',word_structure=dict(memberships=[dict(class_id=c,parts=[])]))
        other=self.api('save-language',dict(name='Other',metadata={}))['id']
        foreign=self.api('class-save',dict(_language=other,name='本语言类',kind='morph'))['id']
        b=self.api('morpheme-save',dict(_language=other,form='ne',body=dict(gloss='R',word_structure=dict(memberships=[dict(class_id=foreign,parts=[])]))))
        with server.connect() as db:
            selection=Selection(db,'all',normalize(dict(search=dict(class_id=c))))
            self.assertEqual(set(selection.eligible),{a['id']});self.assertNotIn(b['id'],selection.eligible)

    def test_english_field_catalog_preserves_authored_class_names(self):
        import ui_localization as ui
        c=self.class_('保存');ui.catalog.cache_clear();ui.message.cache_clear()
        catalog=self.api('vocabulary-options?target=morpheme')
        english=ui.present(catalog,'/api/vocabulary-options','en')
        self.assertEqual(next(r['name'] for r in english['fields'] if r['id']=='affix_position'),'Affix position')
        self.assertEqual(next(r['name'] for r in english['classes'] if r['id']==c),'保存')
        self.assertEqual(next(r['name'] for r in english['groups'] if r['id']=='class:morph'),'Morphological class')
