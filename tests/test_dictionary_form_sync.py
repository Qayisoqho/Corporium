import json
import unittest
from unittest.mock import patch
import test_dictionary_gloss_sync
import server


class FormSyncTests(unittest.TestCase):
    setUp=test_dictionary_gloss_sync.DictionaryGlossSyncTests.setUp
    tearDown=test_dictionary_gloss_sync.DictionaryGlossSyncTests.tearDown
    call=test_dictionary_gloss_sync.DictionaryGlossSyncTests.call
    seed=test_dictionary_gloss_sync.DictionaryGlossSyncTests.seed
    entries=test_dictionary_gloss_sync.DictionaryGlossSyncTests.entries
    undo=test_dictionary_gloss_sync.DictionaryGlossSyncTests.undo
    api=test_dictionary_gloss_sync.DictionaryGlossSyncTests.api
    word=test_dictionary_gloss_sync.DictionaryGlossSyncTests.word
    example=test_dictionary_gloss_sync.DictionaryGlossSyncTests.example
    detail=test_dictionary_gloss_sync.DictionaryGlossSyncTests.detail

    def bind(self,r,x,key,kind='corpus',word=0,form=None):
        d=self.detail(r,kind);x=self.api('lexeme?id='+x['id']);u=x['body']['usages'][0]
        self.api('segmentation-link',dict(kind=kind,id=r['id'],revision=d['revision'],word=word,key=key,lexeme_id=x['id'],lexeme_revision=x['revision'],usage_id=u['id'],sense_id=u['senses'][0]['id'],form_id=form))

    def save(self,x,kind):return self.api(kind+'-save',x)

    def test_base_and_variant_are_separate_in_both_targets_and_owners_with_undo(self):
        for target_kind in ('lexeme','morpheme'):
            with self.subTest(target_kind=target_kind):
                suffix='n' if target_kind=='lexeme' else 'm';variant=suffix+'e'
                x=self.api('lexeme-save',dict(headword='-'+suffix,body=dict(usages=[dict(senses=[dict(short_gloss='GEN')])],variants=[dict(form='-'+variant)]))) if target_kind=='lexeme' else self.api('morpheme-save',dict(form='-'+suffix,body=dict(gloss='GEN',variants=[dict(form='-'+variant)])))
                fid=x['body']['variants'][0]['id']
                text=self.api('import',dict(title=target_kind,content='#pass([unchanged], (([root-'+suffix+'],[根-GEN]),([root-'+variant+'],[根-GEN]),([root-'+suffix+'],[根-GEN])), [keep translation])'))
                e=self.api('entries?text='+text['id'])['items'][0];ex=self.example([('root-'+suffix,'根-GEN'),('root-'+variant,'根-GEN'),('root-'+suffix,'根-GEN')])
                for kind,r in [('corpus',e),('independent',ex)]:
                    self.bind(r,x,'1:host',kind,0);self.bind(r,x,'1:host',kind,1,fid)
                before=self.detail(e)['body'];ids=[(w['unit_id'],[m['unit_id'] for m in w['morphemes']]) for w in before['words']]
                x['headword' if target_kind=='lexeme' else 'form']='-'+suffix+'a';x=self.save(x,target_kind)
                for kind,r in [('corpus',e),('independent',ex)]:
                    self.assertEqual([w['form'] for w in self.detail(r,kind)['body']['words']],['root-'+suffix+'a','root-'+variant,'root-'+suffix])
                x['body']['variants'][0]['form']='-'+variant+'i';self.save(x,target_kind)
                for kind,r in [('corpus',e),('independent',ex)]:
                    body=self.detail(r,kind)['body'];self.assertEqual([w['form'] for w in body['words']],['root-'+suffix+'a','root-'+variant+'i','root-'+suffix]);self.assertEqual(body['warnings'],[])
                    if kind=='independent':self.assertTrue(all(not t['segmentation_review'] for t in body['targets']))
                current=self.detail(e)['body'];self.assertEqual(ids,[(w['unit_id'],[m['unit_id'] for m in w['morphemes']]) for w in current['words']]);self.assertEqual(current['ipa'],'unchanged')
                self.assertEqual(self.undo()[0],200);self.assertEqual(self.detail(e)['body']['words'][1]['form'],'root-'+variant)
                self.assertEqual(self.undo()[0],200);self.assertEqual(self.detail(e)['body']['words'][0]['form'],'root-'+suffix)
                self.assertEqual(self.undo('redo')[0],200);self.assertEqual(self.detail(e)['body']['words'][0]['form'],'root-'+suffix+'a')

    def test_simultaneous_spelling_and_meaning_edit_and_other_links_survive(self):
        e=self.seed('#pass([keep], (([root-n],[根-GEN.SG]),), [keep])');ex=self.example([('root-n','根-GEN.SG')])
        root=self.word('root',['根']);n=self.word('-n',['GEN'])
        for kind,r in [('corpus',e),('independent',ex)]:self.bind(r,root,'0:host',kind);self.bind(r,n,'1:host',kind)
        n['headword']='-ni';n['body']['usages'][0]['senses'][0]['short_gloss']='POSS';self.save(n,'lexeme')
        for kind,r in [('corpus',e),('independent',ex)]:
            b=self.detail(r,kind)['body'];self.assertEqual((b['words'][0]['form'],b['words'][0]['gloss']),('root-ni','根-POSS.SG'));self.assertTrue(b['words'][0]['dictionary_linked'])

    def test_infix_and_discontinuous_host_preserve_fragments_and_refs(self):
        e=self.seed('#pass([], (([so<l>ma],[home<GEN>.SG]),), [])');ex=self.example([('so<l>ma','home<GEN>.SG')])
        host=self.word('soma',['home']);infix=self.word('l',['GEN'])
        for kind,r in [('corpus',e),('independent',ex)]:self.bind(r,host,'0:host',kind);self.bind(r,infix,'0:infix:0',kind)
        host['headword']='suma';self.save(host,'lexeme');infix['headword']='li';self.save(infix,'lexeme')
        for kind,r in [('corpus',e),('independent',ex)]:
            b=self.detail(r,kind)['body'];self.assertEqual(b['words'][0]['form'],'su<li>ma');self.assertEqual(b['warnings'],[])
            if kind=='independent':self.assertTrue(all(not t['segmentation_review'] for t in b['targets']))

    def test_circumfix_updates_only_its_members(self):
        e=self.seed('#pass([], (([we-amos-la],[pst-go-pst]),), [])');ex=self.example([('we-amos-la','pst-go-pst')]);x=self.word('we…la',['PST'])
        for kind,r in [('corpus',e),('independent',ex)]:
            d=self.detail(r,kind);self.api('segmentation-save',dict(kind=kind,id=r['id'],revision=d['revision'],word=0,action='save',members=['0:host','2:host'],type='circumfix',gloss='PST'))
            self.bind(r,x,self.detail(r,kind)['body']['words'][0]['morphemes'][0]['key'],kind)
        x['headword']='wa…le';self.save(x,'lexeme')
        for kind,r in [('corpus',e),('independent',ex)]:
            b=self.detail(r,kind)['body'];self.assertEqual(b['words'][0]['form'],'wa-amos-le');self.assertEqual(b['words'][0]['group_reviews'],[])

    def test_unicode_and_script_wrappers_and_outer_punctuation(self):
        e=self.seed('#pass([], (([«ǰi»],[GEN]),([#sub[n]],[GEN])), [])');a=self.word('ǰi',['GEN']);n=self.word('n',['GEN'])
        self.bind(e,a,'@word',word=0);self.bind(e,n,'0:host',word=1)
        a['headword']='či';self.save(a,'lexeme');n['headword']='na';self.save(n,'lexeme')
        self.assertEqual([w['form'] for w in self.detail(e)['body']['words']],['«či»','#sub[na]'])

    def test_unselected_allomorph_sentence_evidence_and_other_fields_do_not_guess(self):
        x=self.word('n',['GEN']);e=self.seed('#pass([], (([na],[GEN]),), [])');self.bind(e,x,'@word')
        ex=self.api('example-save',dict(body=dict(words=[dict(form='n',gloss='GEN')],targets=[dict(lexeme_id=x['id'])])))
        x['headword']='ni';x=self.save(x,'lexeme')
        self.assertEqual(self.detail(e)['body']['words'][0]['form'],'na');self.assertEqual(self.detail(ex,'independent')['body']['words'][0]['form'],'n')
        x['body']['notes']='unrelated'
        with patch('dictionary_form_sync.apply_record',side_effect=AssertionError('No spelling changed')):self.save(x,'lexeme')

    def test_whole_word_base_reference_updates_a_unique_component_without_substring_guessing(self):
        e=self.seed('#pass([], (([home-n],[家-GEN]),([home-home],[家-家]),([homeland],[家园])), [])');x=self.word('home',['家'])
        for i in range(3):self.bind(e,x,'@word',word=i)
        x['headword']='house';self.save(x,'lexeme')
        self.assertEqual([w['form'] for w in self.detail(e)['body']['words']],['house-n','home-home','homeland'])

    def test_incompatible_boundary_changes_roll_back_atomically(self):
        x=self.word('n',['GEN']);e=self.seed('#pass([], (([root-n],[根-GEN]),), [])');self.bind(e,x,'1:host')
        before=self.api('undo-state');x['headword']='ni-ka'
        code,r=self.call('/api/lexeme-save',x);self.assertEqual(code,400,r);self.assertIn('语素切分',r['error'])
        self.assertEqual(self.api('lexeme?id='+x['id'])['headword'],'n');self.assertEqual(self.detail(e)['body']['words'][0]['form'],'root-n');self.assertEqual(self.api('undo-state')['generation'],before['generation'])

    def test_invalid_new_markup_does_not_break_export_or_partially_save(self):
        e=self.seed('#pass([], (([n],[GEN]),), [])');x=self.word('n',['GEN']);self.bind(e,x,'@word')
        x['headword']='[';code,data=self.call('/api/lexeme-save',x)
        self.assertEqual(code,400,data);self.assertIn('括号',data['error']);self.assertEqual(self.detail(e)['body']['words'][0]['form'],'n');self.assertEqual(self.api('lexeme?id='+x['id'])['headword'],'n')

    def test_shared_timeline_survey_evidence_and_replace_use_live_spelling(self):
        e=self.seed('#pass([], (([root-n],[根-GEN]),), [])');ex=self.example([('root-n','根-GEN')]);x=self.word('n',['GEN'])
        for kind,r in [('corpus',e),('independent',ex)]:self.bind(r,x,'1:host',kind)
        version=lambda:self.api('survey?language=ordos')['version']
        node=self.api('survey-save',dict(version=version(),title='Spelling',kind='section',body={}))['id']
        for kind,r in [('corpus',e),('independent',ex)]:self.api('survey-evidence',dict(version=version(),node_id=node,kind=kind,record_id=r['id'],body={}))
        sid=self.api('timeline-create',dict(name='Spelling'))['id'];url='timeline-detail?language=ordos&id='+sid+'&start=0&end=10000'
        for i,rid in enumerate((e['id'],'independent:'+ex['id'])):
            t=self.api(url);self.api('timeline-interval',dict(id=sid,revision=t['session']['revision'],track_id=t['tracks'][0]['id'],entry_id=rid,start_ms=i*2000,end_ms=i*2000+1000))
        timeline_before=self.api(url)
        args=dict(kind='lexeme',scope='current',field='headword',lexeme_id=x['id'],find='n',replacement='ni',mode='exact');p=self.api('dictionary-replace-preview',args)
        self.api('dictionary-replace-apply',dict(**args,token=p['token'],keys=[c['key'] for c in p['changes']],confirm_conflicts=True))
        self.assertEqual([r['record']['body']['words'][0]['form'] for r in self.api('survey-detail?language=ordos&id='+node)['items']],['root-ni','root-ni'])
        for before,after in zip(timeline_before['intervals'],self.api(url)['intervals']):
            self.assertGreater(after['entry_revision'],before['entry_revision']);self.assertEqual(after['revision'],before['revision'])
        self.assertEqual(self.api('lexeme-examples?id='+x['id'])['items'][0]['entry']['words'][0]['form'],'root-ni')
        self.assertEqual(self.api('dictionary-examples?id='+x['id'])[0]['body']['words'][0]['form'],'root-ni')

    def test_synced_forms_exchange_and_backup_preserve_actual_values_and_undo(self):
        from pathlib import Path
        from restore_backup import restore
        e=self.seed('#pass([], (([n],[GEN]),), [])');ex=self.example([('n','GEN')]);x=self.word('n',['GEN'])
        for kind,r in [('corpus',e),('independent',ex)]:self.bind(r,x,'@word',kind)
        x['headword']='ni';self.save(x,'lexeme')
        bundle=self.api('export-language?language=ordos');lid=self.api('save-language',dict(name='Form copy',metadata={}))['id']
        self.api('import-language',dict(_language=lid,bundle=bundle))
        self.assertEqual(self.api('entries?language='+lid)['items'][0]['words'][0]['form'],'ni')
        backup=Path(self.temp.name)/'form-backup.json';backup.write_text(json.dumps(self.api('backup')),encoding='utf-8')
        restored=Path(self.temp.name)/'restored.sqlite3';restore(backup,restored);original=server.DB
        try:
            server.DB=restored;self.assertEqual(self.detail(e)['body']['words'][0]['form'],'ni')
            self.assertEqual(self.undo()[0],200);self.assertEqual(self.detail(e)['body']['words'][0]['form'],'n');self.assertEqual(self.detail(ex,'independent')['body']['words'][0]['form'],'n')
        finally:server.DB=original
