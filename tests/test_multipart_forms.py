import copy
import json
import unittest
import server
import test_dictionary_gloss_sync as helpers
import multipart_forms
from pathlib import Path
from restore_backup import restore


class MultipartFormsTests(unittest.TestCase):
    for name in ('setUp','tearDown','call','seed','entries','undo','api','example','detail'):
        locals()[name]=getattr(helpers.DictionaryGlossSyncTests,name)

    def target(self,parts=('we-','-la'),gloss='PST',kind='morpheme',**extra):
        if kind=='morpheme':
            return self.api('morpheme-save',dict(form='…'.join(parts),body=dict(
                entry_type='affix',affix_position='circumfix',gloss=gloss,form_parts=list(parts),notes='retain notes',**extra)))
        return self.api('lexeme-save',dict(headword='…'.join(parts),body=dict(form_parts=list(parts),
            usages=[dict(senses=[dict(short_gloss=gloss)])],notes='retain notes',**extra)))

    def plan(self,scope=''):
        return self.api('lexeme-auto-preview?language=ordos&text_id='+scope)

    def apply(self,plan,items=None):
        return self.api('lexeme-auto-link',dict(token=plan['token'],text_id=plan['text_id'],
            mode='candidates',selected=items or [r['candidate_id'] for r in plan['suggestions'] if r.get('default_selected')],
            ignore_symbols=plan['ignore_symbols'],ignore_position=plan['ignore_position']))

    def test_normalized_forms_variants_and_invalid_circumfix(self):
        x=self.target(variants=[dict(form='wu…lu',form_parts=['wu-','-lu'],notes='variant notes')])
        self.assertEqual(x['form'],'we-…-la')
        self.assertEqual(x['body']['form_parts'],[dict(text='we',left='',right='-'),dict(text='la',left='-',right='')])
        self.assertEqual(x['body']['variants'][0]['form'],'wu-…-lu')
        for parts in ([],['we'],['we',''],['we','la','ka']):
            code,r=self.call('/api/morpheme-save',dict(form='we',body=dict(entry_type='affix',affix_position='circumfix',form_parts=parts)))
            self.assertEqual(code,400,r)
        with self.assertRaises(ValueError):multipart_forms.normalize(['a',' '])

    def test_preview_read_only_both_sources_apply_undo_redo_and_inheritance(self):
        e=self.seed('#pass([], (([we-amos-la],[PST-go-PST]),), [])')
        ex=self.example([('we-amos-la','PST-go-PST')]);x=self.target()
        with server.connect(audit=False) as db:before=db.total_changes
        plan=self.plan();rows=plan['suggestions']
        self.assertEqual(len(rows),2,plan);self.assertTrue(all(r['default_selected'] for r in rows))
        self.assertEqual(self.detail(e)['body']['words'][0].get('morph_groups',[]),[])
        self.assertEqual(self.apply(plan)['count'],2)
        for kind,row in [('corpus',e),('independent',ex)]:
            w=self.detail(row,kind)['body']['words'][0]
            self.assertEqual(w['gloss'],'PST-go-PST');self.assertEqual(len(w['morph_groups']),1)
            self.assertEqual([m['form'] for m in w['morphemes']],['we…la','amos'])
            self.assertEqual(w['gloss_sources'][0]['mode'],'inherit')
        self.assertEqual(self.plan()['suggestions'],[])
        self.assertEqual(self.undo()[0],200)
        self.assertFalse(self.detail(e)['body']['words'][0].get('morph_groups'))
        self.assertEqual(self.undo('redo')[0],200)
        x['body']['gloss']='PAST';self.api('morpheme-save',x)
        for kind,row in [('corpus',e),('independent',ex)]:self.assertEqual(self.detail(row,kind)['body']['words'][0]['gloss'],'PAST-go-PAST')

    def test_three_parts_exact_order_and_dot_false_positive(self):
        e=self.seed('#pass([], (([ki-am-nu-os-ta-em],[3SG-go-NPST-go-DUR-go]),([we-amos],[PST-go.PST])), [])')
        x=self.target(('am-','-os-','-em'),'go',kind='lexeme')
        self.target()
        plan=self.plan();self.assertEqual(len(plan['suggestions']),1,plan)
        row=plan['suggestions'][0]
        self.assertEqual(row['multipart_group']['group']['members'],['1:host','3:host','5:host'])
        self.apply(plan);w=self.detail(e)['body']['words'][0]
        self.assertEqual(w['morphemes'][1]['form'],'am…os…em')
        self.assertEqual(w['gloss'],'3SG-go-NPST-go-DUR-go')
        self.assertFalse(self.detail(e)['body']['words'][1].get('morph_groups'))

    def test_conflicting_targets_overlaps_and_atomic_rejection(self):
        e=self.seed('#pass([], (([we-x-la-y-ka],[PST-go-PST-go-PST]),), [])')
        self.target();self.target(('la-','-ka'));plan=self.plan()
        self.assertEqual(len(plan['suggestions']),2,plan)
        self.assertFalse(any(r['default_selected'] for r in plan['suggestions']))
        code,r=self.call('/api/lexeme-auto-link',dict(token=plan['token'],mode='candidates',selected=[r['candidate_id'] for r in plan['suggestions']]))
        self.assertEqual(code,400,r);self.assertFalse(self.detail(e)['body']['words'][0].get('morph_groups'))
        self.apply(plan,[plan['suggestions'][0]['candidate_id']])

    def test_existing_manual_group_is_not_replaced_and_legacy_data_survive(self):
        e=self.seed('#pass([], (([we-x-la],[PST-go-PST]),), [])');x=self.target()
        d=self.detail(e)
        self.api('segmentation-save',dict(kind='corpus',id=e['id'],revision=d['revision'],word=0,action='save',members=['0:host','2:host'],type='circumfix',gloss='PST',notes='manual research'))
        plan=self.plan();self.assertFalse(plan['suggestions']);self.assertEqual(len(plan['matches']),1)
        self.api('lexeme-auto-link',dict(token=plan['token']))
        self.assertEqual(self.detail(e)['body']['words'][0]['morph_groups'][0]['notes'],'manual research')
        old=dict(analyses=[dict(id='analysis',title='old analysis',notes='research',components=[dict(id='component',form='a…b',segments=['a','b'],features=[],notes='component notes',source='source')])])
        y=self.target(('a-','-b'),'gloss',kind='lexeme',word_structure=old)
        self.assertEqual(y['body']['word_structure']['analyses'][0]['components'][0]['segments'],['a','b'])
        self.assertEqual(y['body']['word_structure']['analyses'][0]['components'][0]['notes'],'component notes')

    def test_stale_preview_form_edits_and_unicode_equivalence(self):
        e=self.seed('#pass([], (([ǰa-x-la],[PST-go-PST]),), [])')
        x=self.target(('j\u030ca-','-la'));plan=self.plan();self.assertEqual(len(plan['suggestions']),1)
        x['body']['notes']='changed';self.api('morpheme-save',x)
        code,r=self.call('/api/lexeme-auto-link',dict(token=plan['token'],mode='candidates',selected=[plan['suggestions'][0]['candidate_id']]))
        self.assertEqual(code,400,r)
        self.assertFalse(self.detail(e)['body']['words'][0].get('morph_groups'))

    def test_form_edit_syncs_each_part_and_preserves_features_notes_and_snapshots(self):
        e=self.seed('#pass([], (([we-x-la],[PST-go-PST]),), [])');ex=self.example([('we-x-la','PST-go-PST')]);x=self.target()
        self.apply(self.plan());x['body']['form_parts']=['wu-','-lu'];self.api('morpheme-save',x)
        for kind,row in [('corpus',e),('independent',ex)]:
            w=self.detail(row,kind)['body']['words'][0]
            self.assertEqual(w['form'],'wu-x-lu');self.assertEqual(w['group_reviews'],[])
            self.assertEqual(w['morph_groups'][0]['snapshot']['form'],'wu-x-lu')
        self.assertEqual(self.undo()[0],200)
        self.assertEqual(self.detail(e)['body']['words'][0]['form'],'we-x-la')

    def test_exchange_and_full_backup_keep_new_forms_and_group_bindings(self):
        e=self.seed('#pass([], (([we-x-la],[PST-go-PST]),), [])');ex=self.example([('we-x-la','PST-go-PST')]);x=self.target()
        self.apply(self.plan());bundle=self.api('export-language?language=ordos')
        dest=self.api('save-language',dict(name='Copy',metadata={}))['id']
        self.api('import-language',dict(bundle=bundle,_language=dest))
        with server.connect(audit=False) as db:
            copies=[json.loads(r[0]) for r in db.execute('SELECT body FROM morphemes WHERE language_id=?',(dest,))]
            self.assertEqual(copies[0]['form_parts'],x['body']['form_parts'])
            self.assertEqual(db.execute('PRAGMA integrity_check').fetchone()[0],'ok')
            self.assertFalse(db.execute('PRAGMA foreign_key_check').fetchall())
        backup=self.api('backup');path=Path(self.temp.name)/'multipart-backup.json'
        path.write_text(json.dumps(backup,ensure_ascii=False),encoding='utf-8')
        restored=Path(self.temp.name)/'restored.sqlite3';restore(path,restored)
        old=server.DB
        try:
            server.DB=restored
            self.assertEqual(self.detail(e)['body']['words'][0]['morphemes'][0]['form'],'we…la')
            self.assertEqual(self.detail(ex,'independent')['body']['words'][0]['morphemes'][0]['form'],'we…la')
        finally:server.DB=old

    def test_literal_replacement_updates_structured_parts_for_both_target_kinds(self):
        for kind in ('lexeme','morpheme'):
            with self.subTest(kind=kind):
                x=self.target(kind=kind,variants=[dict(form='wu…lu',form_parts=['wu-','-lu'])])
                args=dict(kind=kind,field='headword' if kind=='lexeme' else 'form',scope='current',find='we',replacement='ve',
                          **{'lexeme_id' if kind=='lexeme' else 'morpheme_id':x['id']})
                plan=self.api('dictionary-replace-preview',args);self.assertFalse(plan['blocked'],plan)
                self.api('dictionary-replace-apply',dict(**args,token=plan['token'],keys=[r['key'] for r in plan['changes']]))
                route='lexeme' if kind=='lexeme' else 'morpheme'
                after=self.api(route+'?id='+x['id'])
                self.assertEqual(after['body']['form_parts'][0]['text'],'ve')
                args.update(field='variant',find='wu',replacement='vu')
                plan=self.api('dictionary-replace-preview',args);self.assertFalse(plan['blocked'],plan)
                self.api('dictionary-replace-apply',dict(**args,token=plan['token'],keys=[r['key'] for r in plan['changes']]))
                after=self.api(route+'?id='+x['id'])
                self.assertEqual(after['body']['variants'][0]['form'],'vu-…-lu')
                self.assertEqual(after['body']['variants'][0]['form_parts'][0]['text'],'vu')

    def test_linked_member_and_overflow_do_not_silently_group_or_choose(self):
        import corpus
        self.target()
        e=self.seed('#pass([], (([we-x-la],[PST-go-PST]),), [])')
        x=self.target(('we-','-la'),'OTHER')
        single=self.api('lexeme-save',dict(headword='we',body=dict(usages=[dict(senses=[dict(short_gloss='PST')])])))
        d=self.detail(e);u=d['body']['words'][0]['morphemes'][0]
        self.api('segmentation-link',dict(kind='corpus',id=e['id'],revision=d['revision'],word=0,key=u['key'],
            lexeme_id=single['id'],lexeme_revision=single['revision'],usage_id=single['body']['usages'][0]['id'],sense_id=single['body']['usages'][0]['senses'][0]['id']))
        self.assertFalse(any(r.get('multipart_group') for r in self.plan()['suggestions']))
        catalog=multipart_forms.Catalog()
        catalog.add('ordos','g',multipart_forms.normalize(['a','a','a','a']),dict(id='target'),{})
        word=corpus.analyze(dict(ipa='',translation='',words=[dict(form='-'.join(['a']*60),gloss='-'.join(['g']*60))]))['words'][0]
        proposals,overflow=catalog.proposals(word,'ordos',lambda g:g)
        self.assertTrue(overflow)
        # No guesses from the abandoned exponential branch.
        self.assertEqual(proposals,[])

    def test_features_local_override_and_unlink_freeze_survive_multipart_links(self):
        tag=self.api('grammar-save',dict(symbol='SG',description='singular'))['id']
        e=self.seed('#pass([], (([we-x-la],[PST.SG-go-PST.SG]),), [])')
        ex=self.example([('we-x-la','PST.SG-go-PST.SG')]);x=self.target(features=[tag])
        self.apply(self.plan());d=self.detail(e);source=d['body']['words'][0]['gloss_sources'][0]
        self.api('gloss-source-save',dict(kind='corpus',id=e['id'],revision=d['revision'],binding_id=source['id'],
            binding_revision=source['revision'],gloss_revision=d['body']['gloss_revision'],mode='override',value='LOCAL.SG'))
        x['body']['gloss']='PAST';x=self.api('morpheme-save',x)
        self.assertEqual(x['body']['features'],[tag]);self.assertEqual(x['body']['notes'],'retain notes')
        self.assertEqual(self.detail(e)['body']['words'][0]['gloss'],'LOCAL.SG-go-LOCAL.SG')
        self.assertEqual(self.detail(ex,'independent')['body']['words'][0]['gloss'],'PAST.SG-go-PAST.SG')
        d=self.detail(e);u=self.api('unit-dictionary?id='+d['body']['words'][0]['morphemes'][0]['unit_id'])
        self.api('lexeme-unlink',dict(id=u['link']['id'],revision=u['link']['revision']))
        d=self.detail(ex,'independent');self.api('segmentation-link',dict(kind='independent',id=ex['id'],revision=d['revision'],remove_target=0))
        x['body']['gloss']='FUT';self.api('morpheme-save',x)
        self.assertEqual(self.detail(e)['body']['words'][0]['gloss'],'LOCAL.SG-go-LOCAL.SG')
        self.assertEqual(self.detail(ex,'independent')['body']['words'][0]['gloss'],'PAST.SG-go-PAST.SG')

    def test_explicit_variant_matches_and_edits_both_sources(self):
        e=self.seed('#pass([], (([wu-x-lu],[PST-go-PST]),), [])');ex=self.example([('wu-x-lu','PST-go-PST')])
        x=self.target(variants=[dict(form='wu…lu',form_parts=['wu-','-lu'],notes='keep variant')])
        plan=self.plan();self.assertEqual(len(plan['suggestions']),2)
        vid=x['body']['variants'][0]['id']
        self.assertTrue(all(r['form_id']==vid for r in plan['suggestions']))
        self.apply(plan)
        x['body']['variants'][0]['form_parts']=['vu-','-lu'];self.api('morpheme-save',x)
        for kind,row in [('corpus',e),('independent',ex)]:self.assertEqual(self.detail(row,kind)['body']['words'][0]['form'],'vu-x-lu')


if __name__=='__main__':unittest.main()
