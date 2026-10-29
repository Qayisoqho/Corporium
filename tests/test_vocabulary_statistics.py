import json,unittest
from urllib.parse import urlencode
import server,analysis_workspace
import test_sentence_dictionary as sd


class VocabularyTests(unittest.TestCase):
    for name in ('setUp','tearDown','call','api','source','detail','args','entry','undo'):
        locals()[name]=getattr(sd.SentenceDictionaryTests,name)

    def run_stats(self,mode='language',case=True,**scope):
        return self.api('analysis-run',dict(query=dict(kind='counts',case=case,scope=dict(mode=mode,**scope))))
    def page(self,run,**query):
        return self.api('analysis-result?'+urlencode(dict(id=run['id'],language='ordos',**query)))
    def m(self,form,kind='root',**body):
        return self.api('morpheme-save',dict(form=form,body=dict(entry_type=kind,gloss='ROOT',**body)))
    def bind(self,src,m,word=0,key='@word',**extra):
        return self.api('segmentation-link',dict(**self.args(src),word=word,key=key,link_revision=0,
            lexeme_id=m['id'],lexeme_revision=self.api('morpheme?id='+m['id'])['revision'],usage_id='@morpheme',sense_id='@main',**extra))

    def test_tokens_types_nfc_case_and_per_text_union(self):
        a=self.source('corpus',[('na','R'),('na','R'),('na-ti','R-PL'),('é','E')])
        b=self.source('corpus',[('na-ka','R-X'),('e\u0301','E'),('Na','R')])
        run=self.run_stats();page=self.page(run);st=page['statistics']
        self.assertEqual((st['words'],st['types']),(7,5));self.assertEqual([r['types'] for r in st['rows'] if r['kind']=='text'],[3,3])
        profile=self.page(run,vocabulary_view='forms')['vocabulary'];self.assertEqual(profile['total'],5)
        self.assertEqual({r['form']:r['count'] for r in profile['rows']},{'na':2,'na-ti':1,'na-ka':1,'é':2,'Na':1})
        folded=self.run_stats(case=False);self.assertEqual(folded['summary']['types'],4)
        self.assertFalse(folded['cached']);self.assertTrue(self.run_stats(case=False)['cached'])

    def test_language_identity_and_independent_records_are_separate(self):
        self.source('corpus',[('same','X')]);self.source('independent',[('same','X')])
        other=self.api('save-language',dict(name='Other',metadata={}))['id']
        self.api('import',dict(_language=other,title='Other text',content='#pass([], (([same],[X]),), [])'))
        run=self.api('analysis-run',dict(_language='all',query=dict(kind='counts',scope=dict(mode='language'))))
        result=self.api('analysis-result?'+urlencode(dict(language='all',id=run['id'],vocabulary_view='forms')))
        self.assertEqual(result['statistics']['types'],2)
        self.assertEqual({r['language_id']:r['count'] for r in result['vocabulary']['rows']},{'ordos':2,other:1})
        independent=self.run_stats('independent');self.assertEqual((independent['summary']['words'],independent['summary']['types']),(1,1))

    def test_root_affix_and_variants_use_valid_shared_identities(self):
        root=self.m('na',variants=[dict(id='variant',form='ne')]);affix=self.m('s','affix')
        for kind in ('corpus','independent'):
            src=self.source(kind,[('na-s','ROOT-ROOT'),('ne','ROOT')]);d=self.detail(src)
            keys=[m['key'] for m in d['body']['words'][0]['morphemes']]
            self.bind(src,root,key=keys[0]);self.bind(src,affix,key=keys[1]);self.bind(src,root,word=1,form_id='variant')
        run=self.run_stats();st=self.page(run)['statistics']
        self.assertEqual((st['words'],st['morpheme_words'],st['root_words']),(4,4,4))
        roots=self.page(run,vocabulary_view='roots')['vocabulary'];self.assertEqual(len(roots['rows']),1)
        row=roots['rows'][0];self.assertEqual((row['id'],row['count'],row['words'],row['types']),(root['id'],4,4,2))
        self.assertEqual(self.page(run,vocabulary_view='affixes')['vocabulary']['rows'][0]['count'],2)

    def test_repeated_roots_count_two_occurrences_in_one_word(self):
        root=self.m('na')
        for kind in ('corpus','independent'):
            src=self.source(kind,[('na-na','ROOT-ROOT')]);keys=[m['key'] for m in self.detail(src)['body']['words'][0]['morphemes']]
            for key in keys:self.bind(src,root,key=key)
        run=self.run_stats();row=self.page(run,vocabulary_view='roots')['vocabulary']['rows'][0]
        self.assertEqual((row['count'],row['words']),(4,2))
        examples=self.page(run,vocabulary_view='roots',vocabulary_item=row['key'])['vocabulary']
        self.assertEqual((examples['example_total'],len(examples['items'])),(2,2))

    def test_same_spelling_distinct_roots_and_untyped_items_are_not_guessed(self):
        a=self.m('na');b=self.m('na');untyped=self.m('s','unspecified')
        for m in (a,b,untyped):self.bind(self.source('independent',[(m['form'],'ROOT')]),m)
        self.source('independent',[('unlinked-s','X-ROOT')])
        run=self.run_stats();roots=self.page(run,vocabulary_view='roots')['vocabulary']['rows']
        self.assertEqual({r['id'] for r in roots},{a['id'],b['id']})
        all_rows=self.page(run,vocabulary_view='morphemes')['vocabulary']['rows'];self.assertEqual(len(all_rows),3)
        self.assertEqual(self.page(run)['statistics']['root_words'],2)

    def test_stale_links_and_sentence_only_citations_do_not_count_as_morphemes(self):
        root=self.m('na');src=self.source('corpus',[('na','ROOT')]);self.bind(src,root)
        self.api('example-save',dict(body=dict(words=[dict(form='na',gloss='ROOT')],targets=[dict(lexeme_id=root['id'])])))
        with server.connect() as db:
            link=db.execute('SELECT id FROM lexical_links').fetchone()[0];db.execute('INSERT INTO lexical_reviews VALUES(?,?)',(link,'changed'));analysis_workspace.invalidate(db)
        run=self.run_stats();self.assertEqual(run['summary']['morpheme_words'],0)
        self.assertEqual(self.page(run,vocabulary_view='roots')['vocabulary']['total'],0)

    def test_word_form_examples_freeze_with_snapshot_and_export_all_frequencies(self):
        src=self.source('independent',[('old','X')]);run=self.run_stats();row=self.page(run,vocabulary_view='forms')['vocabulary']['rows'][0]
        snap=self.api('analysis-save',dict(kind='snapshot',name='词频',run_id=run['id']))
        d=self.detail(src);body=d['body'];body['words'][0]['form']='new'
        self.api('example-save',dict(id=src['id'],revision=d['revision'],body=body))
        stale=self.page(run);self.assertTrue(stale['stale']);self.assertNotIn('vocabulary',stale)
        frozen=self.page(snap,snapshot='true',vocabulary_view='forms',vocabulary_item=row['key'])
        self.assertEqual(frozen['vocabulary']['items'][0]['record']['body']['words'][0]['form'],'old')
        exported=self.api('analysis-export?'+urlencode(dict(id=snap['id'],snapshot='true',language='ordos')))
        self.assertEqual(exported['vocabulary']['forms'][0]['count'],1)
        self.assertEqual(self.run_stats()['summary']['types'],1)

    def test_frequency_and_example_pagination_and_validation(self):
        self.source('independent',[(f'f{n:03}','X') for n in range(105)]+[('repeat','X')]*32)
        run=self.run_stats();p=self.page(run,vocabulary_view='forms',vocabulary_page=2)['vocabulary']
        self.assertEqual((p['total'],p['pages'],len(p['rows'])),(106,2,6))
        first=self.page(run,vocabulary_view='forms')['vocabulary']['rows'][0]
        examples=self.page(run,vocabulary_view='forms',vocabulary_item=first['key'],vocabulary_page=2)['vocabulary']
        self.assertEqual((examples['example_total'],examples['pages'],len(examples['items'])),(32,2,2))
        for fields in ({'vocabulary_view':'bad'},{'vocabulary_view':'forms','vocabulary_item':'bad'},{'vocabulary_order':'bad'}):
            self.assertEqual(self.call('/api/analysis-result?'+urlencode(dict(id=run['id'],language='ordos',**fields)))[0],400)

    def test_empty_results_and_complete_form_symbols(self):
        run=self.run_stats();self.assertEqual(run['summary']['types'],0)
        self.assertEqual(self.page(run,vocabulary_view='forms')['vocabulary']['rows'],[])
        self.source('independent',[('na¹','X'),('na1','X'),('na-ti','X-X'),('na=ti','X=X'),('。',''),('#','')])
        run=self.run_stats();self.assertEqual((run['summary']['words'],run['summary']['types']),(4,4))

    def test_adopted_component_maps_to_shared_root_but_unused_analysis_does_not_count(self):
        root=self.m('na','unspecified')
        x=self.entry('na-s','ROOT',word_structure=dict(analyses=[dict(id='a',components=[dict(id='c',form='na',gloss='ROOT',role='词根')])]))
        link=self.api('morpheme-components?id='+x['id'])['items'][0]['link']
        current=self.api('morpheme?id='+root['id']);x=self.api('lexeme?id='+x['id'])
        self.api('morpheme-assign',dict(morpheme_id=root['id'],morpheme_revision=current['revision'],lexeme_id=x['id'],lexeme_revision=x['revision'],components=[dict(analysis_id='a',component_id='c',revision=link['revision'] if link else 0)]))
        src=self.source('corpus',[('na-s','ROOT-PL')])
        self.assertEqual(self.run_stats()['summary']['morpheme_words'],0)
        key=self.detail(src)['body']['words'][0]['morphemes'][0]['key'];x=self.api('lexeme?id='+x['id']);u=x['body']['usages'][0]
        self.api('segmentation-link',dict(**self.args(src),word=0,key=key,link_revision=0,lexeme_id=x['id'],lexeme_revision=x['revision'],usage_id=u['id'],sense_id=u['senses'][0]['id'],component_selection=dict(analysis_id='a',component_id='c')))
        run=self.run_stats();self.assertEqual(run['summary']['root_words'],1)
        self.assertEqual(self.page(run,vocabulary_view='roots')['vocabulary']['rows'][0]['id'],root['id'])
        x=self.api('lexeme?id='+x['id']);x['body']['word_structure']['analyses'][0]['components'][0]['role']='词干';self.api('lexeme-save',x)
        self.assertEqual(self.run_stats()['summary']['morpheme_words'],0)

    def test_whole_word_and_single_morpheme_do_not_double_count(self):
        root=self.m('na');src=self.source('corpus',[('na','ROOT')]);key=self.detail(src)['body']['words'][0]['morphemes'][0]['key']
        self.bind(src,root);self.bind(src,root,key=key)
        row=self.page(self.run_stats(),vocabulary_view='roots')['vocabulary']['rows'][0]
        self.assertEqual((row['count'],row['words']),(1,1))

    def test_filter_uses_frequency_entries_not_examples_and_keeps_full_denominator(self):
        self.source('independent',[('Na','X'),('na','X'),('other','X')])
        run=self.run_stats(case=False)
        p=self.page(run,vocabulary_view='forms',vocabulary_query='NA')['vocabulary']
        self.assertEqual((p['total'],p['denominator'],p['rows'][0]['count']),(1,3,2))
        p=self.page(run,vocabulary_view='forms',vocabulary_query='translation')['vocabulary'];self.assertEqual(p['total'],0)

    def test_streamed_export_and_legacy_count_records(self):
        self.source('independent',[('a','X')]);run=self.run_stats()
        import language_exchange
        with server.connect(audit=False) as db:
            exported=analysis_workspace.export_file(db,server.DB,'ordos',dict(id=run['id']))
            path=language_exchange.staged(server.DB,exported['token'],'analysis-json');data=json.loads(path.read_text(encoding='utf-8'))
            self.assertEqual(data['vocabulary']['forms'][0]['count'],1)
            self.assertEqual(len(data['records']),1)
            legacy=dict(hits=[],statistics=dict(words=2,sentences=1,rows=[]))
            db.execute('UPDATE analysis_runs SET payload=? WHERE id=?',(analysis_workspace.pack(legacy),run['id']))
        page=self.page(run);self.assertNotIn('vocabulary',page);self.assertEqual(page['statistics']['words'],2)


if __name__=='__main__':unittest.main()
