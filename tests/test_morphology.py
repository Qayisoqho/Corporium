import json
import unittest
from pathlib import Path
import server
from restore_backup import restore
import test_lexicon
from contextlib import closing


class MorphologyTests(unittest.TestCase):
    setUp=test_lexicon.LexiconTests.setUp
    tearDown=test_lexicon.LexiconTests.tearDown
    call=test_lexicon.LexiconTests.call
    seed=test_lexicon.LexiconTests.seed
    entries=test_lexicon.LexiconTests.entries
    undo=test_lexicon.LexiconTests.undo

    def tag(self,symbol='PST',language='ordos'):
        code,r=self.call('/api/grammar-save',{'symbol':symbol,'description':'test','_language':language})
        self.assertEqual(code,200,r);return r['id']

    def word(self,tag,base=None):
        b={'entry_type':'stem','features':[],'usages':[{'pos':'V','features':[],'senses':[{'short_gloss':'去'}]}],
           'variants':[{'form':'went','kind':'inflected','variation':'conditioned','condition_types':['morphological'],'conditions':'过去时环境','features':[tag],'pronunciation':'wɛnt','status':'confirmed','source':'test','tags':[{'type':'region','value':'西部'}]}]}
        if base:b['relation']={'base_id':base,'type':'stem'}
        code,x=self.call('/api/lexeme-save',{'headword':'go' if not base else 'went','body':b})
        self.assertEqual(code,200,x);return x

    def link(self,e,x,features):
        uid=e['words'][0]['unit_id'];u=self.call('/api/unit-dictionary?id='+uid)[1]
        payload={'unit_id':uid,'unit_revision':u['revision'],'entry_revision':u['entry_revision'],'revision':u['link'].get('revision',0),'lexeme_id':x['id'],'lexeme_revision':x['revision'],'form_id':x['body']['variants'][0]['id'],'features':features,'status':'confirmed'}
        code,r=self.call('/api/lexeme-link',payload);self.assertEqual(code,200,r);return r,payload

    def test_dot_features_and_independent_word_morpheme_links(self):
        tag=self.tag();e=self.seed('#pass([went], (([went],[去.PST]),), [translation])');x=self.word(tag)
        self.assertEqual(len(e['words'][0]['morphemes']),1)
        uid=e['words'][0]['unit_id'];u=self.call('/api/unit-dictionary?id='+uid)[1]
        self.assertEqual(u['suggested_features'],[tag]);r,p=self.link(e,x,[tag])
        p.update(unit_id=e['words'][0]['morphemes'][0]['unit_id'],revision=0)
        self.assertEqual(self.call('/api/lexeme-link',p)[0],200)
        base='/api/lexeme-examples?id='+x['id']+'&form_id='+x['body']['variants'][0]['id']
        result=self.call(base)[1];self.assertEqual(result['total'],2)
        self.assertEqual(result['items'][0]['features'],[tag]);self.assertEqual(self.call(base+'&kind=morpheme')[1]['total'],1)
        self.assertEqual(self.call('/api/lexeme-examples?id='+x['id']+'&form_id=unassigned')[1]['total'],0)
        self.assertEqual(self.entries()[0]['words'][0]['gloss'],'去.PST')
        # Editing a link from an older client does not silently lose its analysis.
        del p['features'];del p['form_id'];p['revision']=1
        self.assertEqual(self.call('/api/lexeme-link',p)[0],200)
        self.assertEqual(self.call(base)[1]['total'],2)

    def test_reference_guards_and_undo(self):
        tag=self.tag();x=self.word(tag);e=self.seed();r,p=self.link(e,x,[tag])
        bad={**x,'body':{**x['body'],'variants':[]}}
        self.assertEqual(self.call('/api/lexeme-save',bad)[0],400)
        definition=self.call('/api/grammar-tags?language=ordos')[1][0]
        self.assertEqual(self.call('/api/grammar-delete',{**definition,'confirmed':True})[0],400)
        self.assertEqual(self.undo()[0],200)
        with server.connect() as db:self.assertEqual(db.execute('SELECT COUNT(*) FROM morphology_analyses').fetchone()[0],0)
        self.assertEqual(self.undo('redo')[0],200)
        self.assertEqual(self.call('/api/unit-dictionary?id='+p['unit_id'])[1]['link']['form_id'],x['body']['variants'][0]['id'])
        current=self.call('/api/unit-dictionary?id='+p['unit_id'])[1]['link']
        self.assertEqual(self.call('/api/lexeme-unlink',{'id':r['id'],'revision':current['revision']})[0],200)
        self.assertEqual(self.undo()[0],200)
        self.assertEqual(self.call('/api/unit-dictionary?id='+p['unit_id'])[1]['link']['features'],[tag])

    def test_validation_and_relations(self):
        tag=self.tag();x=self.word(tag);child=self.word(tag,x['id'])
        x['body']['relation']={'base_id':child['id'],'type':'stem'}
        self.assertEqual(self.call('/api/lexeme-save',x)[0],400)
        self.assertEqual(self.call('/api/lexeme-delete',{'id':x['id'],'revision':x['revision'],'confirmed':True})[0],400)
        x['body']['relation']=None;x['body']['variants'][0]['conditions']=''
        code,x=self.call('/api/lexeme-save',x);self.assertEqual(code,200,x)
        self.assertEqual(x['body']['variants'][0]['variation'],'conditioned')
        self.assertEqual(x['body']['variants'][0]['conditions'],'')
        x['body']['variants'][0]['variation']='free'
        self.assertEqual(self.call('/api/lexeme-save',x)[0],200)
        other=self.call('/api/save-language',{'name':'Other','metadata':{}})[1]['id'];foreign=self.tag('PST',other)
        x=self.call('/api/lexeme?id='+x['id'])[1];x['body']['features']=[foreign]
        self.assertEqual(self.call('/api/lexeme-save',x)[0],400)

    def test_export_import_backup_and_independent_evidence(self):
        tag=self.tag();x=self.word(tag);child=self.word(tag,x['id']);e=self.seed();r,p=self.link(e,x,[tag])
        target={'lexeme_id':x['id'],'form_id':x['body']['variants'][0]['id'],'features':[tag]}
        code,standalone=self.call('/api/example-save',{'body':{'ipa':'went','translation':'去过','targets':[target]}})
        self.assertEqual(code,200,standalone)
        bundle=self.call('/api/export-language?language=ordos')[1]
        other=self.call('/api/save-language',{'name':'Copy','metadata':{}})[1]['id']
        code,result=self.call('/api/import-language',{'bundle':bundle,'_language':other});self.assertEqual(code,200,result)
        copied=self.call('/api/lexemes?language='+other)[1]['items'];base=next(c for c in copied if c['headword']=='go');stem=next(c for c in copied if c['headword']=='went')
        self.assertEqual(stem['body']['relation']['base_id'],base['id'])
        form=base['body']['variants'][0];self.assertNotEqual(form['id'],target['form_id']);self.assertNotEqual(form['features'],[tag])
        evidence=self.call('/api/lexeme-examples?id='+base['id'])[1]['items'][0]
        self.assertEqual(evidence['form_id'],form['id']);self.assertEqual(evidence['features'],form['features'])
        independent=self.call('/api/dictionary-examples?id='+base['id'])[1][0]['body']['targets'][0]
        self.assertEqual(independent['form_id'],form['id']);self.assertEqual(independent['features'],form['features'])
        backup=self.call('/api/backup')[1];source=server.DB.parent/'morph-backup.json';dest=server.DB.parent/'restored.sqlite3'
        source.write_text(json.dumps(backup),encoding='utf-8');restore(source,dest)
        import sqlite3
        with closing(sqlite3.connect(dest)) as db:self.assertEqual(db.execute('SELECT COUNT(*) FROM morphology_analyses').fetchone()[0],2)

    def test_independent_form_prevents_deletion_and_tag_rename_keeps_identity(self):
        tag=self.tag();x=self.word(tag)
        self.assertEqual(self.call('/api/example-save',{'body':{'translation':'example','targets':[{'lexeme_id':x['id'],'form_id':x['body']['variants'][0]['id']}]}})[0],200)
        x['body']['variants']=[];self.assertEqual(self.call('/api/lexeme-save',x)[0],400)
        t=self.call('/api/grammar-tags?language=ordos')[1][0]
        self.assertEqual(self.call('/api/grammar-save',{**t,'symbol':'PAST','aliases':['PST']})[0],200)
        self.assertEqual(self.call('/api/lexeme?id='+x['id'])[1]['body']['variants'][0]['features'],[tag])
        self.assertEqual(self.call('/api/lexemes?language=ordos&q=PAST')[1]['total'],1)
        self.assertEqual(self.call('/api/lexemes?language=ordos&q=PST')[1]['total'],1)

if __name__=='__main__':unittest.main()
