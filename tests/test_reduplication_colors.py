"""Source-only display overlays must never imply a dictionary association."""
import copy
import json
import unittest
import corpus
import morpheme_colors as colors
import reduplication as red
import server
import test_reduplication


class ReduplicationColorRanges(unittest.TestCase):
    def body(self,form='je~jepasu',gloss='RED~go',key='r:0:host',base='r:1:host'):
        b=corpus.analyze(dict(ipa='',translation='',words=[dict(form=form,gloss=gloss)]))
        red.apply(b,dict(source=dict(word=0,key=key),base=dict(word=0,key=base),type='partial'))
        corpus.analyze(b);colors.attach_reduplication(b)
        return b

    def test_candidates_are_not_colored_and_only_confirmed_source_gets_ranges(self):
        b=corpus.analyze(dict(ipa='',translation='',words=[dict(form='je~jepasu',gloss='RED~go')]))
        colors.attach_reduplication(b);self.assertNotIn('redup_colors',b['words'][0])
        b=self.body();c=b['words'][0]['redup_colors'][0]
        self.assertEqual(c['form'],[[0,2]]);self.assertEqual(c['gloss'],[[0,3]])
        suffix=self.body('go~go','go~RED',key='r:1:host',base='r:0:host')['words'][0]['redup_colors'][0]
        self.assertEqual(suffix['form'],[[3,5]]);self.assertEqual(suffix['gloss'],[[3,6]])

    def test_empty_or_unaligned_gloss_does_not_guess_a_gloss_range(self):
        for gloss in ('','go','RED-go'):
            c=self.body(gloss=gloss)['words'][0]['redup_colors'][0]
            self.assertEqual(c['form'],[[0,2]]);self.assertEqual(c['gloss'],[])

    def test_cross_word_sources_scripts_and_discontinuous_source(self):
        b=corpus.analyze(dict(ipa='',translation='',words=[dict(form='𐐀á#sub[2]',gloss='RED#sub[2]'),dict(form='base',gloss='go')]))
        red.apply(b,dict(source=dict(word=0,key='@word'),base=dict(word=1,key='@word'),type='modified'))
        corpus.analyze(b);colors.attach_reduplication(b)
        self.assertEqual(b['words'][0]['redup_colors'][0]['form'],[[0,len(b['words'][0]['form'])]])
        self.assertEqual(b['words'][0]['redup_colors'][0]['gloss'],[[0,len(b['words'][0]['gloss'])]])
        self.assertNotIn('redup_colors',b['words'][1])
        b=self.body('je<k>je~jepasu','RED<CAUS>~go')
        self.assertEqual(b['words'][0]['redup_colors'][0]['form'],[[0,2],[5,7]])
        self.assertEqual(b['words'][0]['redup_colors'][0]['gloss'],[[0,3]])

    def test_review_and_deleted_relations_remove_old_overlays(self):
        b=self.body();b['words'][0]['form']='ja~jepasu';corpus.analyze(b);colors.attach_reduplication(b)
        self.assertTrue(b['reduplication_info']['relations'][0]['review']);self.assertNotIn('redup_colors',b['words'][0])
        b=self.body();b['reduplications']=[];colors.attach_reduplication(b);self.assertNotIn('redup_colors',b['words'][0])

    def test_combined_source_preserves_its_distinct_fragments(self):
        b=corpus.analyze(dict(ipa='',translation='',words=[dict(form='je-na~jepasu',gloss='RED-GEN~go')]))
        w=b['words'][0];w['morph_groups']=[dict(id='source',type='stem',members=['r:0:host','r:1:host'],gloss='repeated',snapshot={k:w[k] for k in ('form','gloss')})]
        corpus.analyze(b);red.apply(b,dict(source=dict(word=0,key='group:source'),base=dict(word=0,key='r:2:host'),type='full'))
        corpus.analyze(b);colors.attach_reduplication(b)
        self.assertEqual(w['redup_colors'][0]['form'],[[0,2],[3,5]])
        self.assertEqual(w['redup_colors'][0]['gloss'],[[0,3],[4,7]])


class ReduplicationColorReadTests(unittest.TestCase):
    for helper in ('setUp','tearDown','call','seed','entries','get','undo','draft','example','save'):
        locals()[helper]=getattr(test_reduplication.ReduplicationTests,helper)

    def seed(self,content):
        before={e['id'] for e in self.entries()}
        self.assertEqual(self.call('/api/import',dict(title='Reduplication',content=content))[0],200)
        return next(e for e in self.entries() if e['id'] not in before)

    def link(self,e,kind,key,form,word=0):
        if not hasattr(self,'link_targets'):self.link_targets={}
        x=self.link_targets.get(form)
        if not x:
            code,x=self.call('/api/lexeme-save',dict(headword=form,body=dict(entry_type='root')));self.assertEqual(code,200,x)
            self.link_targets[form]=x
        d=self.get(e,kind)
        code,result=self.call('/api/segmentation-link',dict(kind=kind,id=e['id'],revision=d['revision'],word=word,key=key,lexeme_id=x['id'],lexeme_revision=x['revision']))
        self.assertEqual(code,200,result)
        return self.get(e,kind)['body']['words'][0]

    def unlink(self,e,kind,word,key):
        d=self.get(e,kind)
        if kind=='corpus':
            w=d['body']['words'][word]
            uid=w['unit_id'] if key=='@word' else next(c['unit_id'] for c in w['morphemes'] if c['key']==key)
            code,current=self.call('/api/unit-dictionary?id='+uid);self.assertEqual(code,200,current)
            code,result=self.call('/api/lexeme-unlink',dict(id=current['link']['id'],revision=current['link']['revision']))
        else:
            index=next(i for i,t in enumerate(d['body']['targets']) if t['segmentation_ref']['word']==word and t['segmentation_ref']['key']==key)
            code,result=self.call('/api/segmentation-link',dict(kind=kind,id=e['id'],revision=d['revision'],remove_target=index))
        self.assertEqual(code,200,result)

    def test_whole_reduplicant_follows_base_link_unlink_undo_and_redo(self):
        import grammar_survey
        for kind in ('corpus','independent'):
            e=self.example(kind,form='x',gloss='RED')
            self.save(e,kind,source=dict(word=0,key='@word'),base=dict(word=1,key='@word'),type='full')
            self.assertFalse(self.get(e,kind)['body']['words'][0]['dictionary_linked'])
            self.assertTrue(self.link(e,kind,'@word','x',word=1)['dictionary_linked'])
            with server.connect(audit=False) as db:
                self.assertTrue(grammar_survey.reference(db,kind,e['id'],'ordos')['body']['words'][0]['dictionary_linked'])
            w=self.get(e,kind)['body']['words'][0];self.assertFalse(any(c['linked'] for c in w['morph_colors']))
            self.unlink(e,kind,1,'@word')
            self.assertFalse(self.get(e,kind)['body']['words'][0]['dictionary_linked'])
            with server.connect(audit=False) as db:
                self.assertFalse(grammar_survey.reference(db,kind,e['id'],'ordos')['body']['words'][0]['dictionary_linked'])
            self.assertEqual(self.undo()[0],200);self.assertTrue(self.get(e,kind)['body']['words'][0]['dictionary_linked'])
            self.assertEqual(self.undo('redo')[0],200);self.assertFalse(self.get(e,kind)['body']['words'][0]['dictionary_linked'])

    def test_whole_reduplicant_requires_its_exact_base_span_to_be_linked(self):
        for kind in ('corpus','independent'):
            e=self.example(kind,form='x',gloss='RED')
            draft=self.draft(kind,e);draft['body']['words'][1].update(form='x-na',gloss='go-PL')
            self.assertEqual(self.call('/api/inline-save',draft)[0],200)
            self.save(e,kind,source=dict(word=0,key='@word'),base=dict(word=1,key='@word'),type='full')
            self.assertFalse(self.link(e,kind,'1:host','na',word=1)['dictionary_linked'])
            self.assertTrue(self.link(e,kind,'0:host','x',word=1)['dictionary_linked'])
            self.unlink(e,kind,1,'0:host');self.assertFalse(self.get(e,kind)['body']['words'][0]['dictionary_linked'])
            d=self.get(e,kind)
            self.assertEqual(self.call('/api/segmentation-save',dict(kind=kind,id=e['id'],revision=d['revision'],action='redup-save',relation_id=d['body']['reduplications'][0]['id'],source=dict(word=0,key='@word'),base=dict(word=1,key='1:host'),type='modified'))[0],200)
            self.assertTrue(self.get(e,kind)['body']['words'][0]['dictionary_linked'])

    def test_whole_reduplicant_chains_propagate_backwards_and_stale_relations_do_not(self):
        for kind in ('corpus','independent'):
            if kind=='corpus':e=self.seed('#pass([], (([x],[RED]),([x],[RED]),([x],[go])), [chain])')
            else:
                code,e=self.call('/api/example-save',dict(body=dict(ipa='',translation='chain',words=[dict(form='x',gloss=g) for g in ('RED','RED','go')],targets=[])));self.assertEqual(code,200,e)
            self.save(e,kind,source=dict(word=0,key='@word'),base=dict(word=1,key='@word'),type='full')
            self.save(e,kind,source=dict(word=1,key='@word'),base=dict(word=2,key='@word'),type='full')
            self.link(e,kind,'0:host','x',word=2)
            self.assertTrue(all(w['dictionary_linked'] for w in self.get(e,kind)['body']['words']))
            self.unlink(e,kind,2,'0:host');self.assertFalse(any(w['dictionary_linked'] for w in self.get(e,kind)['body']['words']))
            self.assertEqual(self.undo()[0],200)
            draft=self.draft(kind,e);draft['body']['words'][1]['form']='changed'
            self.assertEqual(self.call('/api/inline-save',draft)[0],200)
            self.assertFalse(any(w['dictionary_linked'] for w in self.get(e,kind)['body']['words'][:2]))

    def test_linked_remainder_completes_word_and_relation_delete_undo_refreshes_it(self):
        import grammar_survey
        for kind in ('corpus','independent'):
            e=self.example(kind);self.save(e,kind)
            w=self.link(e,kind,'r:1:host','jepasu')
            self.assertTrue(w['dictionary_linked']);self.assertEqual([c['linked'] for c in w['morph_colors']],[False,True])
            with server.connect(audit=False) as db:
                reference=grammar_survey.reference(db,kind,e['id'],'ordos')
                self.assertTrue(reference['body']['words'][0]['dictionary_linked'])
            d=self.get(e,kind)
            code,result=self.call('/api/segmentation-save',dict(kind=kind,id=e['id'],revision=d['revision'],action='redup-delete',relation_id=d['body']['reduplications'][0]['id']))
            self.assertEqual(code,200,result);self.assertFalse(self.get(e,kind)['body']['words'][0]['dictionary_linked'])
            self.assertEqual(self.undo()[0],200);self.assertTrue(self.get(e,kind)['body']['words'][0]['dictionary_linked'])

    def test_candidate_or_stale_relation_does_not_exempt_an_unlinked_component(self):
        for kind in ('corpus','independent'):
            e=self.example(kind)
            self.assertFalse(self.link(e,kind,'r:1:host','jepasu')['dictionary_linked'])
            self.save(e,kind);self.assertTrue(self.get(e,kind)['body']['words'][0]['dictionary_linked'])
            draft=self.draft(kind,e);draft['body']['words'][0]['form']='ja~jepasu'
            self.assertEqual(self.call('/api/inline-save',draft)[0],200)
            w=self.get(e,kind)['body']['words'][0]
            self.assertFalse(w['dictionary_linked']);self.assertNotIn('redup_colors',w)

    def test_non_reduplicant_affix_and_infix_still_need_their_own_links(self):
        for kind in ('corpus','independent'):
            for form,gloss,key,affix in [('je~jepasu-na','RED~go-PL','r:2:host','na'),('je<k>je~jepasu','RED<CAUS>~go','r:0:infix:0','k')]:
                e=self.example(kind,form,gloss);self.save(e,kind)
                self.assertFalse(self.link(e,kind,'r:1:host','jepasu')['dictionary_linked'])
                self.assertTrue(self.link(e,kind,key,affix)['dictionary_linked'])

    def test_coverage_requires_every_fragment_and_never_exempts_blank_ranges(self):
        self.assertTrue(colors.covered([[0,2],[5,7]],[[0,2],[5,7]]))
        self.assertTrue(colors.covered([[0,4]],[[0,2],[2,4]]))
        self.assertFalse(colors.covered([[0,7]],[[0,2],[5,7]]))
        self.assertFalse(colors.covered([[0,2],[5,7]],[[0,2]]))
        self.assertFalse(colors.covered([],[[0,2]]))

    def test_sources_references_analysis_and_reads_do_not_write(self):
        import grammar_survey
        for kind in ('corpus','independent'):
            e=self.example(kind);self.save(e,kind)
            with server.connect(audit=False) as db:
                before={t:list(map(tuple,db.execute('SELECT * FROM '+t))) for t in ('entries','dictionary_examples','lexical_links','gloss_bindings')}
                d=grammar_survey.reference(db,kind,e['id'],'ordos')
                self.assertEqual(d['body']['words'][0]['redup_colors'][0]['form'],[[0,2]])
            for path in ['segmentation?kind='+kind+'&id='+e['id'],'annotations?kind='+kind+'&id='+e['id']]:
                code,d=self.call('/api/'+path);self.assertEqual(code,200,d)
                # annotations is the raw editing draft; visible references are enriched.
                if path.startswith('segmentation'):self.assertEqual(d['body']['words'][0]['redup_colors'][0]['gloss'],[[0,3]])
            code,run=self.call('/api/analysis-run',dict(_language='ordos',query=dict(scope={'source':'all'},conditions=[dict(field='reduplication',value='jepasu')])));self.assertEqual(code,200,run)
            code,result=self.call('/api/analysis-result?language=ordos&id='+run['id']);self.assertEqual(code,200,result)
            for item in result['items']:
                w=item['record']['body']['words'][0]
                self.assertEqual(w['redup_colors'][0]['form'],[[0,2]])
                self.assertFalse(w['dictionary_linked']);self.assertFalse(any(c['linked'] for c in w['morph_colors']))
            with server.connect(audit=False) as db:
                for t,rows in before.items():self.assertEqual(list(map(tuple,db.execute('SELECT * FROM '+t))),rows)

    def test_secondary_sentence_views_match_live_source_after_base_link_and_unlink(self):
        import analysis_workspace
        import grammar
        import grammar_survey
        for kind in ('corpus','independent'):
            for whole in (False,True):
                e=self.example(kind,form='x' if whole else 'je~jepasu',gloss='RED' if whole else 'RED~go')
                self.save(e,kind,**(dict(source=dict(word=0,key='@word'),base=dict(word=1,key='@word'),type='full') if whole else {}))
                word=1 if whole else 0;key='@word' if whole else 'r:1:host'
                self.link(e,kind,key,'x' if whole else 'jepasu',word=word)
                for linked in (True,False):
                    if not linked:self.unlink(e,kind,word,key)
                    timeline=self.get(e,kind)['body']
                    self.assertEqual(timeline['effective_language_id'],'ordos')
                    self.assertEqual(timeline['text_language_id'],'ordos')
                    self.assertEqual(timeline['words'][0]['dictionary_linked'],linked)
                    def display(body):
                        return [{k:w.get(k) for k in ('form','gloss','morph_colors','redup_colors','dictionary_linked')} for w in body['words']]
                    with server.connect(audit=False) as db:
                        before=db.total_changes
                        survey=grammar_survey.reference(db,kind,e['id'],'ordos')['body']
                        hit=dict(entry_id=('independent:' if kind=='independent' else '')+e['id'])
                        analysis=next(analysis_workspace.materialized_items(db,[hit]))[1]['body']
                        audit=dict(issues=[dict(kind=kind,id=e['id'],body={},issue='usage')],tags=[],unknown=[],ignored=[],counts={},sentences=1)
                        checked=grammar.audit_page(db,{},audit)['items'][0]['body']
                        for body in (survey,analysis,checked):self.assertEqual(display(body),display(timeline))
                        self.assertEqual(db.total_changes,before)
                    if kind=='corpus':
                        source=next(item for item in self.entries() if item['id']==e['id'])
                        self.assertEqual(display(source),display(timeline))

    def test_reorder_review_delete_and_undo_restore_the_source_overlay(self):
        for kind in ('corpus','independent'):
            e=self.example(kind);self.save(e,kind)
            draft=self.draft(kind,e);draft['slot_ids'].reverse();draft['body']['words'].reverse()
            self.assertEqual(self.call('/api/inline-save',draft)[0],200)
            b=self.get(e,kind)['body'];self.assertNotIn('redup_colors',b['words'][0]);self.assertEqual(b['words'][1]['redup_colors'][0]['form'],[[0,2]])
            draft=self.draft(kind,e);draft['body']['words'][1]['form']='changed~jepasu'
            self.assertEqual(self.call('/api/inline-save',draft)[0],200);self.assertNotIn('redup_colors',self.get(e,kind)['body']['words'][1])
            self.assertEqual(self.undo()[0],200);d=self.get(e,kind);self.assertTrue(d['body']['words'][1]['redup_colors'])
            code,result=self.call('/api/segmentation-save',dict(kind=kind,id=e['id'],revision=d['revision'],action='redup-delete',relation_id=d['body']['reduplications'][0]['id']));self.assertEqual(code,200,result)
            self.assertFalse(any(w.get('redup_colors') for w in self.get(e,kind)['body']['words']))
            self.assertEqual(self.undo()[0],200);self.assertTrue(self.get(e,kind)['body']['words'][1]['redup_colors'])
            with server.connect(audit=False) as db:
                table='entries' if kind=='corpus' else 'dictionary_examples'
                raw=json.loads(db.execute('SELECT body FROM '+table+' WHERE id=?',(e['id'],)).fetchone()[0])
                self.assertFalse(any(w.get('redup_colors') for w in raw['words']))
