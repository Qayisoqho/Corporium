import copy
import json
import unittest
from pathlib import Path
from unittest.mock import patch

import server
import test_lexicon


class DictionaryGlossSyncTests(unittest.TestCase):
    for name in ('setUp','tearDown','call','seed','entries','undo'):
        locals()[name]=getattr(test_lexicon.LexiconTests,name)

    def test_sync_cache_keeps_rule_identity_and_returns_independent_words(self):
        import corpus,dictionary_gloss_sync
        cache=dictionary_gloss_sync.SyncCache()
        word=corpus.analyze(dict(ipa='',translation='',words=[dict(form='home',gloss='家')]))['words'][0]
        first=cache.transform(word,{'@word':('家','房屋')},dictionary_gloss_sync.transform)
        first['form']='changed outside cache';first['morphemes'].clear()
        same=cache.transform(word,{'@word':('家','房屋')},dictionary_gloss_sync.transform)
        different=cache.transform(word,{'@word':('家','住所')},dictionary_gloss_sync.transform)
        self.assertEqual((same['form'],same['gloss'],len(same['morphemes'])),('home','房屋',1))
        self.assertEqual(different['gloss'],'住所');self.assertEqual(word['gloss'],'家')

    def api(self,path,body=None):
        code,result=self.call('/api/'+path,body);self.assertEqual(code,200,result);return result

    def word(self,form,labels):
        return self.api('lexeme-save',dict(headword=form,body=dict(usages=[dict(pos='名词',senses=[dict(short_gloss=s) for s in labels])])))

    def example(self,words):
        return self.api('example-save',dict(body=dict(ipa='test ipa',translation='keep translation',notes='keep notes',words=[dict(form=f,gloss=g) for f,g in words])))

    def detail(self,record,kind='corpus'):
        return self.api('segmentation?kind='+kind+'&id='+record['id'])

    def link(self,record,x,key,word=0,sense=0,kind='corpus'):
        d=self.detail(record,kind);target=self.api('lexeme?id='+x['id'])
        b=dict(kind=kind,id=record['id'],revision=d['revision'],word=word,key=key,lexeme_id=x['id'],lexeme_revision=target['revision'])
        if sense is not None:
            u=target['body']['usages'][0];b.update(usage_id=u['id'],sense_id=u['senses'][sense]['id'])
        self.api('segmentation-link',b)

    def test_same_labels_distinct_senses_only_update_bound_occurrences_and_undo(self):
        e=self.seed('#pass([keep ipa], (([root-n],[根-GEN.SG]),([root-n],[根-GEN.SG]),([n],[GEN]),([n],[GEN])), [keep translation])')
        x=self.word('n',['GEN','GEN'])
        ex=self.example([('root-n','根-GEN.SG'),('root-n','根-GEN.SG')])
        for i in (0,1):self.link(e,x,'1:host',word=i,sense=i);self.link(ex,x,'1:host',word=i,sense=i,kind='independent')
        self.link(e,x,'@word',word=2,sense=None)
        before=self.entries()[0];ids=[(w['unit_id'],[m['unit_id'] for m in w['morphemes']]) for w in before['words']]
        ex_before=self.detail(ex,'independent')['body']
        x['body']['usages'][0]['senses'][0]['short_gloss']='POSS';self.api('lexeme-save',x)
        after=self.entries()[0]
        self.assertEqual([w['gloss'] for w in after['words']],['根-POSS.SG','根-GEN.SG','GEN','GEN'])
        self.assertEqual(ids,[(w['unit_id'],[m['unit_id'] for m in w['morphemes']]) for w in after['words']])
        fresh=self.detail(ex,'independent')['body'];self.assertEqual([w['gloss'] for w in fresh['words']],['根-POSS.SG','根-GEN.SG'])
        self.assertEqual([w['annotation_id'] for w in fresh['words']],[w['annotation_id'] for w in ex_before['words']])
        self.assertTrue(all(not t['segmentation_review'] for t in fresh['targets']))
        self.assertEqual((fresh['ipa'],fresh['translation'],fresh['notes']),('test ipa','keep translation','keep notes'))
        self.assertIn('POSS',self.api('export?id='+e['text_id']))
        self.assertEqual(self.undo()[0],200)
        self.assertEqual([w['gloss'] for w in self.entries()[0]['words']],['根-GEN.SG','根-GEN.SG','GEN','GEN'])
        self.assertEqual([w['gloss'] for w in self.detail(ex,'independent')['body']['words']],['根-GEN.SG','根-GEN.SG'])
        self.assertEqual(self.undo('redo')[0],200)
        self.assertEqual(self.entries()[0]['words'][0]['gloss'],'根-POSS.SG')

    def test_features_before_or_after_meaning_and_script_markup_survive(self):
        from dictionary_gloss_sync import replace_short
        for before,old,new,expected in [('SG.GEN','GEN','POSS','SG.POSS'),('SG_GEN','GEN','POSS','SG_POSS'),('#sup[GEN].SG','GEN','POSS','#sup[POSS].SG'),('GEN.SG','GEN','','SG'),('[GEN]','GEN','',''),('PL.SG.GEN','GEN.SG','POSS','PL.POSS'),('家-GEN','家','房屋','房屋-GEN')]:
            with self.subTest(before=before):self.assertEqual(replace_short(before,old,new),expected)

    def test_native_morpheme_main_and_extra_meaning_have_separate_identities(self):
        m=self.api('morpheme-save',dict(form='n',body=dict(gloss='GEN',senses=[dict(gloss='PST')],entry_type='affix')))
        target=self.api('lexeme?id='+m['id']);labels=[s['short_gloss'] for s in target['body']['usages'][0]['senses']]
        main=labels.index('GEN');extra=labels.index('PST')
        e=self.seed('#pass([], (([n],[GEN]),([n],[PST])), [])');ex=self.example([('n','GEN'),('n','PST')])
        for kind,r in [('corpus',e),('independent',ex)]:
            self.link(r,m,'@word',word=0,sense=main,kind=kind);self.link(r,m,'@word',word=1,sense=extra,kind=kind)
        m['body']['gloss']='POSS';m=self.api('morpheme-save',m)
        self.assertEqual([w['gloss'] for w in self.entries()[0]['words']],['POSS','PST'])
        m['body']['senses'][0]['gloss']='ANT';self.api('morpheme-save',m)
        for kind,r in [('corpus',e),('independent',ex)]:self.assertEqual([w['gloss'] for w in self.detail(r,kind)['body']['words']],['POSS','ANT'])

    def test_infix_host_and_other_links_rebase_without_losing_identities(self):
        e=self.seed('#pass([], (([so<l>ma],[home<GEN>.SG]),), [])');ex=self.example([('so<l>ma','home<GEN>.SG')])
        a=self.word('l',['GEN']);host=self.word('soma',['home'])
        for kind,r in [('corpus',e),('independent',ex)]:
            self.link(r,a,'0:infix:0',kind=kind);self.link(r,host,'0:host',kind=kind)
        before=self.entries()[0]['words'][0];ids=[m['unit_id'] for m in before['morphemes']]
        a['body']['usages'][0]['senses'][0]['short_gloss']='POSS';self.api('lexeme-save',a)
        self.assertEqual(self.entries()[0]['words'][0]['gloss'],'home<POSS>.SG')
        host['body']['usages'][0]['senses'][0]['short_gloss']='house';self.api('lexeme-save',host)
        for kind,r in [('corpus',e),('independent',ex)]:
            d=self.detail(r,kind);w=d['body']['words'][0]
            self.assertEqual([m['gloss'] for m in w['morphemes']],['house.SG','POSS'])
            self.assertEqual(d['body']['warnings'],[])
            if kind=='independent':self.assertTrue(all(not t['segmentation_review'] for t in d['body']['targets']))
        self.assertEqual(ids,[m['unit_id'] for m in self.entries()[0]['words'][0]['morphemes']])

    def test_discontinuous_group_updates_members_and_preserves_group_and_refs(self):
        e=self.seed('#pass([], (([we-amos-la],[pst-go-pst]),), [])');ex=self.example([('we-amos-la','pst-go-pst')]);x=self.word('we…la',['PST'])
        for kind,r in [('corpus',e),('independent',ex)]:
            d=self.detail(r,kind)
            self.api('segmentation-save',dict(kind=kind,id=r['id'],revision=d['revision'],word=0,action='save',members=['0:host','2:host'],type='circumfix',gloss='PST'))
            key=self.detail(r,kind)['body']['words'][0]['morphemes'][0]['key'];self.link(r,x,key,kind=kind)
        x['body']['usages'][0]['senses'][0]['short_gloss']='ANT';self.api('lexeme-save',x)
        for kind,r in [('corpus',e),('independent',ex)]:
            d=self.detail(r,kind);w=d['body']['words'][0]
            self.assertEqual(w['gloss'],'ANT-go-ANT');self.assertEqual(w['morphemes'][0]['gloss'],'ANT');self.assertEqual(w['group_reviews'],[])
            if kind=='independent':self.assertFalse(d['body']['targets'][0]['segmentation_review'])
        self.assertEqual(self.undo()[0],200);self.assertEqual(self.entries()[0]['words'][0]['gloss'],'PST-go-PST')

    def test_stale_independent_and_sentence_only_evidence_are_not_guessed(self):
        x=self.word('n',['GEN']);ex=self.example([('n','GEN')]);self.link(ex,x,'@word',kind='independent')
        whole=self.api('example-save',dict(body=dict(ipa='n',words=[dict(form='n',gloss='GEN')],targets=[dict(lexeme_id=x['id'],usage_id=x['body']['usages'][0]['id'],sense_id=x['body']['usages'][0]['senses'][0]['id'])])))
        with server.connect(audit=False) as db:
            body=json.loads(db.execute('SELECT body FROM dictionary_examples WHERE id=?',(ex['id'],)).fetchone()[0]);body['words'][0]['gloss']='GEN.PL'
            db.execute('UPDATE dictionary_examples SET body=?,revision=revision+1 WHERE id=?',(json.dumps(body),ex['id']))
        x['body']['usages'][0]['senses'][0]['short_gloss']='POSS';self.api('lexeme-save',x)
        self.assertEqual(self.detail(ex,'independent')['body']['words'][0]['gloss'],'GEN.PL')
        self.assertEqual(self.detail(whole,'independent')['body']['words'][0]['gloss'],'GEN')

    def test_incompatible_segmentation_rolls_back_dictionary_and_all_occurrences(self):
        e=self.seed();x=self.word('home-n',['家-GEN']);self.link(e,x,'@word')
        before=self.api('undo-state');x['body']['usages'][0]['senses'][0]['short_gloss']='住所'
        code,error=self.call('/api/lexeme-save',x);self.assertEqual(code,400,error);self.assertIn('语素切分',error['error'])
        self.assertEqual(self.entries()[0]['words'][0]['gloss'],'家-GEN')
        self.assertEqual(self.api('lexeme?id='+x['id'])['body']['usages'][0]['senses'][0]['short_gloss'],'家-GEN')
        self.assertEqual(self.api('undo-state')['generation'],before['generation'])

    def test_other_dictionary_fields_do_not_scan_or_rewrite_sentences(self):
        e=self.seed();x=self.word('home',['家']);self.link(e,x,'0:host');before=self.entries()[0]['revision']
        x['body']['notes']='unrelated edit'
        with patch('dictionary_gloss_sync.apply_record',side_effect=AssertionError('No meaning changed')):self.api('lexeme-save',x)
        self.assertEqual(self.entries()[0]['revision'],before)

    def test_whole_word_and_complete_component_link_state_are_shared(self):
        e=self.seed('#pass([], (([root-n],[家-GEN]),), [])');ex=self.example([('root-n','家-GEN')])
        root=self.word('root',['家']);suffix=self.word('n',['GEN'])
        for kind,r in [('corpus',e),('independent',ex)]:
            self.assertFalse(self.detail(r,kind)['body']['words'][0]['dictionary_linked'])
            self.link(r,root,'0:host',kind=kind)
            self.assertFalse(self.detail(r,kind)['body']['words'][0]['dictionary_linked'])
            self.link(r,suffix,'1:host',kind=kind)
            self.assertTrue(self.detail(r,kind)['body']['words'][0]['dictionary_linked'])
        other=self.example([('root-n','家-GEN')]);self.link(other,root,'@word',kind='independent')
        self.assertTrue(self.detail(other,'independent')['body']['words'][0]['dictionary_linked'])
        self.assertTrue(self.detail(other,'independent')['body']['words'][0]['morph_colors'])

    def test_replace_paths_sync_only_selected_lexeme_or_morpheme_sense(self):
        for kind in ('lexeme','morpheme'):
            with self.subTest(kind=kind):
                form='n' if kind=='lexeme' else 'm'
                target=self.word(form,['GEN','GEN']) if kind=='lexeme' else self.api('morpheme-save',dict(form=form,body=dict(gloss='GEN',senses=[dict(gloss='GEN')],entry_type='affix')))
                senses=self.api('lexeme?id='+target['id'])['body']['usages'][0]['senses']
                main=next(i for i,s in enumerate(senses) if s['id']=='@main') if kind=='morpheme' else 0
                order=[main,1-main]
                text=self.api('import',dict(title='Replace '+kind,content='#pass([], ((['+form+'],[GEN.SG]),(['+form+'],[GEN.SG])), [])'));e=self.api('entries?text='+text['id'])['items'][0];ex=self.example([(form,'GEN.SG'),(form,'GEN.SG')])
                for i in (0,1):
                    self.link(e,target,'@word',word=i,sense=order[i]);self.link(ex,target,'@word',word=i,sense=order[i],kind='independent')
                args=dict(kind=kind,scope='current',field='short_gloss',find='GEN',replacement='POSS',mode='exact',**{kind+'_id':target['id']})
                plan=self.api('dictionary-replace-preview',args)
                self.assertEqual(self.detail(e)['body']['words'][0]['gloss'],'GEN.SG')
                path=['body','usages',0,'senses',0,'short_gloss'] if kind=='lexeme' else ['body','gloss']
                selected=next(c for c in plan['changes'] if c['path']==path)
                result=self.api('dictionary-replace-apply',dict(**args,token=plan['token'],keys=[selected['key']],confirm_conflicts=True))
                self.assertEqual(result['replacements'],1)
                for source,record in [('corpus',e),('independent',ex)]:self.assertEqual([w['gloss'] for w in self.detail(record,source)['body']['words']],['POSS.SG','GEN.SG'])
                self.assertEqual(self.undo()[0],200)
                for source,record in [('corpus',e),('independent',ex)]:self.assertEqual([w['gloss'] for w in self.detail(record,source)['body']['words']],['GEN.SG','GEN.SG'])

    def test_shared_survey_timeline_and_dictionary_evidence_read_updated_source(self):
        e=self.seed('#pass([], (([keep],[keep]),([n],[GEN])), [])');ex=self.example([('keep','keep'),('n','GEN')]);x=self.word('n',['GEN'])
        for kind,record in [('corpus',e),('independent',ex)]:self.link(record,x,'@word',word=1,kind=kind)
        version=lambda:self.api('survey?language=ordos')['version']
        node=self.api('survey-save',dict(version=version(),title='Meaning test',kind='section',body={}))['id']
        for kind,record in [('corpus',e),('independent',ex)]:self.api('survey-evidence',dict(version=version(),node_id=node,kind=kind,record_id=record['id'],body={}))
        sid=self.api('timeline-create',dict(name='Meaning test'))['id'];url='timeline-detail?language=ordos&id='+sid+'&start=0&end=10000'
        for i,record_id in enumerate([e['id'],'independent:'+ex['id']]):
            timeline=self.api(url);self.api('timeline-interval',dict(id=sid,revision=timeline['session']['revision'],track_id=timeline['tracks'][0]['id'],entry_id=record_id,start_ms=i*2000,end_ms=i*2000+1000))
        before=self.api(url)
        x['body']['usages'][0]['senses'][0]['short_gloss']='POSS';self.api('lexeme-save',x)
        evidence=self.api('survey-detail?language=ordos&id='+node)['items'];self.assertEqual([r['record']['body']['words'][1]['gloss'] for r in evidence],['POSS','POSS'])
        after=self.api(url)
        self.assertNotEqual(before['gloss_revision'],after['gloss_revision'])
        for a,z in zip(before['intervals'],after['intervals']):
            self.assertEqual((a['id'],a['revision'],a['start_ms'],a['end_ms']),(z['id'],z['revision'],z['start_ms'],z['end_ms']))
            # Live dictionary inheritance does not rewrite the source sentence.
            self.assertEqual(z['entry_revision'],a['entry_revision'])
        for kind,record in [('corpus',e),('independent',ex)]:self.assertEqual(self.api('annotations?kind='+kind+'&id='+record['id'])['body']['words'][1]['gloss'],'POSS')
        corpus=self.api('lexeme-examples?id='+x['id'])['items'][0];self.assertEqual((corpus['word_position'],corpus['entry']['words'][1]['gloss']),(1,'POSS'))
        self.assertEqual(self.api('dictionary-examples?id='+x['id'])[0]['body']['words'][1]['gloss'],'POSS')
        self.assertEqual(self.undo()[0],200)
        self.assertEqual([r['record']['body']['words'][1]['gloss'] for r in self.api('survey-detail?language=ordos&id='+node)['items']],['GEN','GEN'])

    def test_evidence_word_position_uses_parent_slot_for_internal_components(self):
        e=self.seed('#pass([], (([n],[GEN]),([root-n],[root-GEN])), [])');x=self.word('n',['GEN'])
        self.link(e,x,'@word',word=0);self.link(e,x,'1:host',word=1)
        rows=self.api('lexeme-examples?id='+x['id'])['items']
        self.assertEqual({r['kind']:r['word_position'] for r in rows},{'word':0,'morpheme':1})

    def test_exchange_and_backup_retain_synced_values_and_undo(self):
        from restore_backup import restore
        e=self.seed('#pass([], (([n],[GEN]),), [])');ex=self.example([('n','GEN')]);x=self.word('n',['GEN'])
        self.link(e,x,'@word');self.link(ex,x,'@word',kind='independent')
        x['body']['usages'][0]['senses'][0]['short_gloss']='POSS';self.api('lexeme-save',x)
        bundle=self.api('export-language?language=ordos')
        backup=Path(self.temp.name)/'backup.json';backup.write_text(json.dumps(self.api('backup')),encoding='utf-8')
        restored=Path(self.temp.name)/'restored.sqlite3';restore(backup,restored)
        original=server.DB
        try:
            server.DB=restored
            self.assertEqual(self.entries()[0]['words'][0]['gloss'],'POSS')
            self.assertEqual(self.detail(ex,'independent')['body']['words'][0]['gloss'],'POSS')
            self.assertEqual(self.undo()[0],200);self.assertEqual(self.entries()[0]['words'][0]['gloss'],'GEN')
            self.assertEqual(self.undo('redo')[0],200);self.assertEqual(self.entries()[0]['words'][0]['gloss'],'POSS')
        finally:server.DB=original
        lid=self.api('save-language',dict(name='Copy',metadata={}))['id']
        self.api('import-language',dict(_language=lid,bundle=bundle))
        self.assertEqual(self.api('entries?language='+lid)['items'][0]['words'][0]['gloss'],'POSS')


if __name__=='__main__':unittest.main()
