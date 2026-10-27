import json
import unittest
from pathlib import Path
import server
import test_server
from restore_backup import restore


class LexiconTests(unittest.TestCase):
    setUp=test_server.APITests.setUp
    tearDown=test_server.APITests.tearDown
    call=test_server.APITests.call

    def test_example_kind_filter_counts_and_pages(self):
        e=self.seed();x=self.word()
        self.link(e['words'][0]['unit_id'],x)
        self.link(e['words'][0]['morphemes'][0]['unit_id'],x)
        base='/api/lexeme-examples?id='+x['id']
        self.assertEqual(self.call(base)[1]['total'],2)
        for kind in ('word','morpheme'):
            code,result=self.call(base+'&kind='+kind+'&page=99')
            self.assertEqual(code,200);self.assertEqual(result['total'],1)
            self.assertEqual(result['page'],1);self.assertEqual(result['pages'],1)
            self.assertEqual([r['kind'] for r in result['items']],[kind])
        self.assertEqual(self.call(base+'&kind=bad')[0],400)

    def test_expanded_history_limits_and_trim(self):
        for limit in (30,40):
            state=self.call('/api/undo-state')[1]
            self.assertEqual(self.call('/api/undo-limit',{'limit':limit,'generation':state['generation']})[0],200)
            self.assertEqual(self.call('/api/undo-state')[1]['step_limit'],limit)
        for i in range(42):
            self.call('/api/lexeme-save',{'headword':str(i),'body':{}})
        state=self.call('/api/undo-state')[1]
        self.assertEqual(len(state['steps']),40)
        self.assertEqual(self.call('/api/undo-limit',{'limit':30,'generation':state['generation']})[0],200)
        self.assertEqual(len(self.call('/api/undo-state')[1]['steps']),30)
        self.assertEqual(self.undo()[0],200);self.assertEqual(self.undo('redo')[0],200)

    def test_auto_exact_scope_dedup_and_undo(self):
        e=self.seed('#pass([ipa], (([home],[家]),([home-n],[家-GEN]),([Home],[家]),([home],[家园])), [translation])')
        x=self.word()
        plan=self.call('/api/lexeme-auto-preview?language=ordos&text_id='+e['text_id'])[1]
        self.assertEqual(len(plan['matches']),2,plan)
        self.assertEqual({r['kind'] for r in plan['matches']},{'word','morpheme'})
        payload={'token':plan['token'],'text_id':e['text_id']}
        self.assertEqual(self.call('/api/lexeme-auto-link',payload)[1]['count'],2)
        self.assertEqual(self.call('/api/lexeme-auto-link',payload)[0],400)
        self.assertEqual(self.call('/api/lexeme-examples?id='+x['id'])[1]['total'],2)
        self.assertEqual(self.undo()[0],200)
        self.assertEqual(self.call('/api/lexeme-examples?id='+x['id'])[1]['total'],0)
        self.assertEqual(self.undo('redo')[0],200)
        plan=self.call('/api/lexeme-auto-preview?language=ordos')[1]
        self.assertEqual(len(plan['matches']),0);self.assertEqual(plan['already_linked'],2)
        self.assertEqual(self.entries()[0]['words'][1]['gloss'],'家-GEN')

    def test_auto_ambiguity_stale_and_language(self):
        self.seed();x=self.word()
        plan=self.call('/api/lexeme-auto-preview?language=ordos')[1]
        self.assertEqual(len(plan['matches']),1)
        self.word()
        self.assertEqual(self.call('/api/lexeme-auto-link',{'token':plan['token']})[0],400)
        plan=self.call('/api/lexeme-auto-preview?language=ordos')[1]
        self.assertEqual(len(plan['matches']),0);self.assertEqual(len(plan['ambiguous']),1)
        other=self.call('/api/save-language',{'name':'Other','metadata':{}})[1]['id']
        self.assertEqual(self.call('/api/lexeme-auto-preview?language='+other)[1]['matches'],[])
        self.assertEqual(self.call('/api/lexeme-auto-preview?language=all')[0],400)

    def test_orthographies_roundtrip_validation_and_undo(self):
        x=self.word();x['body']['orthographies']=[{'label':'IPA','text':'həʊm','font':'IPAPANNEW'},{'label':'汉字','text':'家','font':'KaiTi'}]
        code,x=self.call('/api/lexeme-save',x);self.assertEqual(code,200,x)
        self.assertEqual(x['body']['orthographies'][1]['font'],'KaiTi')
        bundle=self.call('/api/export-language?language=ordos')[1]
        other=self.call('/api/save-language',{'name':'Copy','metadata':{}})[1]['id']
        self.assertEqual(self.call('/api/import-language',{'_language':other,'bundle':bundle})[0],200)
        copied=self.call('/api/lexemes?language='+other)[1]['items'][0]['body']['orthographies']
        self.assertEqual(copied[0]['text'],'həʊm');self.assertNotEqual(copied[0]['id'],x['body']['orthographies'][0]['id'])
        x['body']['orthographies'][0]['font']='unsafe-font'
        self.assertEqual(self.call('/api/lexeme-save',x)[0],400)
        self.assertEqual(self.undo()[0],200)
        self.assertEqual(self.call('/api/lexeme?id='+x['id'])[1]['body'].get('orthographies',[]),[])

    def test_auto_preserves_existing_morpheme_link_and_actual_language(self):
        e=self.seed('#pass([ipa], (([home],[家]),), [translation])');x=self.word()
        self.link(e['words'][0]['morphemes'][0]['unit_id'],x)
        plan=self.call('/api/lexeme-auto-preview?language=ordos')[1]
        self.assertEqual(plan['matches'],[]);self.assertEqual(plan['already_linked'],1)
        self.assertEqual(self.undo()[0],200)
        plan=self.call('/api/lexeme-auto-preview?language=ordos')[1]
        other=self.call('/api/save-language',{'name':'Other','metadata':{}})[1]['id']
        self.assertEqual(self.call('/api/save',{**e,'notes':'','language_id':other})[0],200)
        self.assertEqual(self.call('/api/lexeme-auto-link',{'token':plan['token']})[0],400)
        self.assertEqual(self.call('/api/lexeme-auto-preview?language=ordos')[1]['matches'],[])

    def seed(self,content='#pass([ipa], (([home-n],[家-GEN]),([go],[去])), [translation])'):
        self.call('/api/import',{'title':'Text','content':content})
        return self.entries()[0]

    def entries(self):return self.call('/api/entries')[1]['items']

    def word(self):
        confirmation=self.call('/api/homonym-preview?form=home&language=ordos')[1]['token']
        code,x=self.call('/api/lexeme-save',{'headword':'home','homonym_confirmation':confirmation,'body':{'tags':[{'type':'region','value':'西部'}],'usages':[{'pos':'名词','senses':[{'short_gloss':'家','definition':'家庭居住的住所。','tags':[{'type':'register','value':'文语'}]}]},{'pos':'动词','senses':[{'short_gloss':'回家','definition':'返回住所。'}]}],'variants':[{'form':'hom','tags':[{'type':'generation','value':'青年人常用'}]}]}})
        self.assertEqual(code,200,x);return x

    def link(self,uid,x):
        u=self.call('/api/unit-dictionary?id='+uid)[1]
        usage=x['body']['usages'][0];sense=usage['senses'][0]
        code,result=self.call('/api/lexeme-link',{'unit_id':uid,'unit_revision':u['revision'],'entry_revision':u['entry_revision'],'revision':u['link'].get('revision',0),'lexeme_id':x['id'],'lexeme_revision':x['revision'],'usage_id':usage['id'],'sense_id':sense['id'],'status':'confirmed','notes':'evidence','_language':u['language_id']})
        self.assertEqual(code,200,result);return result

    def undo(self,kind='undo',language='ordos'):
        s=self.call('/api/undo-state?language='+language)[1]
        return self.call('/api/'+kind,{'generation':s['generation'],'_language':language})

    def test_dictionary_meaning_sync_and_independent_sentence_edits(self):
        e=self.seed();uid=e['words'][0]['morphemes'][0]['unit_id'];x=self.word();self.link(uid,x)
        x['body']['usages'][0]['senses'][0]['short_gloss']='住所'
        self.assertEqual(self.call('/api/lexeme-save',x)[0],200)
        self.assertEqual(self.entries()[0]['words'][0]['gloss'],'住所-GEN')
        e=self.entries()[0];e['words'][0]['gloss']='屋-GEN'
        self.assertEqual(self.call('/api/save',{**e,'notes':''})[0],200)
        self.assertEqual(self.entries()[0]['words'][0]['morphemes'][0]['unit_id'],uid)
        examples=self.call('/api/lexeme-examples?id='+x['id'])[1]
        self.assertEqual(examples['items'][0]['gloss'],'屋')
        self.assertFalse(examples['items'][0]['needs_review'])
        self.assertEqual(self.call('/api/lexeme?id='+x['id'])[1]['body']['usages'][0]['senses'][0]['short_gloss'],'住所')

    def test_insertion_split_and_undo_identity(self):
        e=self.seed();uid=e['words'][0]['unit_id'];x=self.word();self.link(uid,x)
        e['words'].insert(0,{'form':'new','gloss':'新','form_kind':'content','gloss_kind':'content'})
        self.call('/api/save',{**e,'notes':''})
        self.assertEqual(self.entries()[0]['words'][1]['unit_id'],uid)
        e=self.entries()[0];e['words'][1]['form']='house';e['words'][1]['gloss']='屋'
        self.call('/api/save',{**e,'notes':''})
        examples=self.call('/api/lexeme-examples?id='+x['id'])[1]['items']
        self.assertTrue(examples[0]['needs_review'])
        self.assertEqual(examples[0]['form'],'home-n')
        self.assertEqual(self.undo()[0],200)
        self.assertEqual(self.entries()[0]['words'][1]['unit_id'],uid)
        self.assertFalse(self.call('/api/lexeme-examples?id='+x['id'])[1]['items'][0]['needs_review'])
        self.assertEqual(self.undo('redo')[0],200)
        self.assertTrue(self.call('/api/lexeme-examples?id='+x['id'])[1]['items'][0]['needs_review'])

    def test_ambiguous_repeated_tokens_are_not_reassigned(self):
        e=self.seed('#pass([ipa], (([a],[A]),([a],[A])), [translation])')
        uid=e['words'][0]['unit_id'];x=self.word();self.link(uid,x)
        e['words'].pop();self.call('/api/save',{**e,'notes':''})
        self.assertNotEqual(self.entries()[0]['words'][0]['unit_id'],uid)
        self.assertTrue(self.call('/api/lexeme-examples?id='+x['id'])[1]['items'][0]['needs_review'])

    def test_reference_validation_and_stale_edits(self):
        e=self.seed();x=self.word();uid=e['words'][0]['unit_id'];self.link(uid,x)
        invalid={**x,'body':{**x['body'],'usages':[]}}
        self.assertEqual(self.call('/api/lexeme-save',invalid)[0],400)
        self.assertEqual(self.call('/api/lexeme-delete',{'id':x['id'],'revision':x['revision'],'confirmed':True})[0],400)
        self.assertEqual(self.call('/api/lexeme-save',x)[0],200)
        self.assertEqual(self.call('/api/lexeme-save',x)[0],400)
        link=self.call('/api/unit-dictionary?id='+uid)[1]['link']
        self.assertEqual(self.call('/api/lexeme-unlink',link)[0],200)
        x=self.call('/api/lexeme?id='+x['id'])[1]
        self.assertEqual(self.call('/api/lexeme-delete',{**x,'confirmed':True})[0],200)
        self.assertEqual(self.undo()[0],200)
        self.assertEqual(self.undo()[0],200)
        self.assertEqual(self.call('/api/lexeme-examples?id='+x['id'])[1]['total'],1)

    def test_backup_and_deleted_sentence_evidence(self):
        e=self.seed();x=self.word();self.link(e['words'][0]['unit_id'],x)
        self.call('/api/delete-entry',{'id':e['id'],'text_id':e['text_id'],'revision':e['revision'],'confirmed':True})
        self.assertIsNone(self.call('/api/lexeme-examples?id='+x['id'])[1]['items'][0]['entry'])
        path=Path(self.temp.name)/'backup.json';path.write_text(json.dumps(self.call('/api/backup')[1]),encoding='utf-8')
        dest=Path(self.temp.name)/'restored.db';restore(path,dest);server.DB=dest
        self.assertEqual(self.undo()[0],200)
        self.assertEqual(self.entries()[0]['words'][0]['unit_id'],e['words'][0]['unit_id'])
        self.assertEqual(self.call('/api/lexeme-examples?id='+x['id'])[1]['total'],1)

    def test_cross_language_dependency_blocks_dangling_undo(self):
        other=self.call('/api/save-language',{'name':'Other','metadata':{}})[1]['id']
        e=self.seed('#pass([ipa], (([home],[home])), [translation])');self.assertEqual(self.call('/api/save',{**e,'notes':'','language_id':other})[0],200)
        x=self.call('/api/lexeme-save',{'_language':other,'headword':'home','body':{'usages':[{'pos':'N','senses':[{'short_gloss':'home'}]}]}})[1]
        self.link(self.entries()[0]['words'][0]['unit_id'],x)
        self.assertEqual(self.undo(language=other)[0],400)
        self.assertEqual(self.call('/api/lexeme?id='+x['id'])[0],200)
        self.assertEqual(self.undo()[0],200)
        self.assertEqual(self.undo(language=other)[0],200)

    def test_migration_does_not_rewrite_corpus(self):
        e=self.seed()
        with server.connect() as db:
            before=db.execute('SELECT body FROM entries WHERE id=?',(e['id'],)).fetchone()[0]
            db.execute('DROP TABLE lexical_links');db.execute('DROP TABLE lexemes');db.execute('DROP TABLE corpus_units')
        server.init()
        with server.connect() as db:
            self.assertEqual(before,db.execute('SELECT body FROM entries WHERE id=?',(e['id'],)).fetchone()[0])
        uid=self.entries()[0]['words'][0]['unit_id'];server.init()
        self.assertEqual(self.entries()[0]['words'][0]['unit_id'],uid)
        self.assertTrue(list((server.DB.parent/'backups').glob('before-lexicon-*.sqlite3')))

    def test_language_exchange_preserves_links_with_new_ids(self):
        e=self.seed();x=self.word();self.link(e['words'][0]['unit_id'],x)
        bundle=self.call('/api/export-language?language=ordos')[1]
        other=self.call('/api/save-language',{'name':'Copy','metadata':{}})[1]['id']
        code,result=self.call('/api/import-language',{'_language':other,'bundle':bundle})
        self.assertEqual(code,200,result)
        copied=self.call('/api/lexemes?language='+other)[1]['items'][0]
        self.assertNotEqual(copied['id'],x['id'])
        self.assertEqual(copied['body']['usages'][0]['senses'][0]['definition'],'家庭居住的住所。')
        examples=self.call('/api/lexeme-examples?id='+copied['id'])[1]
        self.assertEqual(examples['total'],1)
        self.assertNotEqual(examples['items'][0]['entry_id'],e['id'])
        self.assertFalse(examples['items'][0]['needs_review'])
        self.assertEqual(self.undo(language=other)[0],200)
        self.assertEqual(self.call('/api/lexemes?language='+other)[1]['total'],0)
        self.assertEqual(self.call('/api/lexeme-examples?id='+x['id'])[1]['total'],1)
        self.assertEqual(self.undo('redo',other)[0],200)
        self.assertEqual(self.call('/api/lexeme-examples?id='+copied['id'])[1]['total'],1)

    def test_pending_lexeme_only_link_and_homonyms(self):
        e=self.seed();x=self.word();another=self.word()
        x=self.call('/api/lexeme?id='+x['id'])[1]  # Automatic numbering updates its revision.
        self.assertNotEqual(x['id'],another['id'])
        uid=e['words'][0]['unit_id'];u=self.call('/api/unit-dictionary?id='+uid)[1]
        code,result=self.call('/api/lexeme-link',{'unit_id':uid,'unit_revision':u['revision'],'entry_revision':u['entry_revision'],'lexeme_id':x['id'],'lexeme_revision':x['revision']})
        self.assertEqual(code,200,result)
        link=self.call('/api/unit-dictionary?id='+uid)[1]['link']
        self.assertIsNone(link['usage_id']);self.assertIsNone(link['sense_id']);self.assertEqual(link['status'],'confirmed')

    def test_move_preserves_units_and_linked_evidence(self):
        e=self.seed();x=self.word();uid=e['words'][0]['morphemes'][0]['unit_id'];self.link(uid,x)
        target=self.call('/api/new-text',{'title':'Target'})[1]['id']
        code,result=self.call('/api/move',{'source_id':e['text_id'],'target_id':target,'ids':[e['id']],'where':'start'})
        self.assertEqual(code,200,result)
        example=self.call('/api/lexeme-examples?id='+x['id'])[1]['items'][0]
        self.assertEqual(example['text_id'],target);self.assertEqual(example['unit_id'],uid)
        self.assertEqual(self.undo()[0],200)
        self.assertEqual(self.call('/api/lexeme-examples?id='+x['id'])[1]['items'][0]['text_id'],e['text_id'])

    def test_exchange_retains_deleted_sentence_reference(self):
        e=self.seed();x=self.word();self.link(e['words'][0]['morphemes'][0]['unit_id'],x)
        self.call('/api/delete-entry',{'id':e['id'],'text_id':e['text_id'],'revision':e['revision'],'confirmed':True})
        bundle=self.call('/api/export-language?language=ordos')[1]
        other=self.call('/api/save-language',{'name':'Copy','metadata':{}})[1]['id']
        code,result=self.call('/api/import-language',{'_language':other,'bundle':bundle})
        self.assertEqual(code,200,result)
        copied=self.call('/api/lexemes?language='+other)[1]['items'][0]
        example=self.call('/api/lexeme-examples?id='+copied['id'])[1]['items'][0]
        self.assertTrue(example['needs_review']);self.assertIsNone(example['entry'])
