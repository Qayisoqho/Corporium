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
