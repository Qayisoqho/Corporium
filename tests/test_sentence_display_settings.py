import json
import unittest
from unittest.mock import patch
from urllib.parse import urlencode
import server
import test_server

class SentenceDisplaySettingsTests(unittest.TestCase):
    setUp=test_server.APITests.setUp
    tearDown=test_server.APITests.tearDown
    call=test_server.APITests.call

    def ok(self,path,body=None):
        code,value=self.call(path,body);self.assertEqual(code,200,value);return value

    def test_picker_excludes_shared_examples_for_both_target_kinds(self):
        x=self.ok('/api/lexeme-save',{'headword':'alpha','body':{'notes':'own-needle','variants':[{'form':'variant-needle'}]}})
        m=self.ok('/api/morpheme-save',{'form':'beta','body':{'gloss':'meaning-needle','readings':['reading-needle']}})
        self.ok('/api/example-save',{'body':{'ipa':'evidence-only','translation':'evidence-only','words':[{'form':'evidence-only','gloss':'evidence-only'}],'targets':[{'lexeme_id':x['id']},{'lexeme_id':m['id']}]}})
        def search(q,scope=None):
            return self.ok('/api/lexemes?'+urlencode({'targets':'all','counts':'0','q':q,'search':json.dumps({'scope':scope} if scope else {})}))
        self.assertEqual({r['id'] for r in search('evidence-only')['items']},{x['id'],m['id']})
        # No example decoding/indexing is needed for any picker query.
        with patch('dictionary_search.example_rows',side_effect=AssertionError('evidence was read')):
            self.assertEqual(search('evidence-only','entry')['total'],0)
            for q,id in [('own-needle',x['id']),('variant-needle',x['id']),('meaning-needle',m['id']),('reading-needle',m['id'])]:
                self.assertEqual([r['id'] for r in search(q,'entry')['items']],[id])
        self.assertEqual(self.call('/api/lexemes?'+urlencode({'search':json.dumps({'scope':'bad'}),'q':'a'}))[0],400)

    def test_picker_excludes_corpus_evidence_and_keeps_both_own_forms(self):
        self.ok('/api/import',{'title':'Text','content':'#pass([corpus-only-needle], (([alpha],[A]),([beta],[B])), [corpus-only-needle])'})
        x=self.ok('/api/lexeme-save',{'headword':'alpha','body':{}})
        m=self.ok('/api/morpheme-save',{'form':'beta','body':{'gloss':'B'}})
        words=self.ok('/api/entries')['items'][0]['words']
        for word,target in zip(words,[x,m]):
            u=self.ok('/api/unit-dictionary?id='+word['unit_id'])
            self.ok('/api/lexeme-link',{'unit_id':u['id'],'unit_revision':u['revision'],'entry_revision':u['entry_revision'],'revision':0,'lexeme_id':target['id'],'lexeme_revision':target['revision']})
        params={'targets':'all','counts':'0','q':'corpus-only-needle'}
        self.assertEqual(self.ok('/api/lexemes?'+urlencode(params))['total'],2)
        self.assertEqual(self.ok('/api/lexemes?'+urlencode({**params,'search':json.dumps({'scope':'entry'})}))['total'],0)

    def test_create_independent_sentence_for_native_morpheme_and_undo(self):
        m=self.ok('/api/morpheme-save',{'form':'beta','body':{'gloss':'B'}})
        saved=self.ok('/api/sentence-create',{'kind':'independent','targets':[{'lexeme_id':m['id']}],'body':{'ipa':'beta','translation':'Native example','words':[{'form':'beta','gloss':'B'}]},'slot_ids':['new:one'],'cells':[],'layers':[]})
        examples=lambda:self.ok('/api/dictionary-examples?id='+m['id'])
        self.assertEqual([e['id'] for e in examples()],[saved['id']])
        for command,total in [('undo',0),('redo',1)]:
            state=self.ok('/api/undo-state')
            self.ok('/api/'+command,{'generation':state['generation']})
            self.assertEqual(len(examples()),total)

    def test_four_rows_persist_independently_and_undo(self):
        metadata={'ipa_font':'IPAPANNEW','annotation_font':'Junicode','gloss_font':'KaiTi','translation_font':'SimSun','ipa_variant':'regular','morpheme_variant':'italic','gloss_variant':'bold','translation_variant':'bolditalic','ipa_scale':.8,'morpheme_scale':1.2,'gloss_scale':1.3,'translation_scale':1.5}
        a=self.ok('/api/save-language',{'name':'A','metadata':metadata})['id']
        b=self.ok('/api/save-language',{'name':'B','metadata':{**metadata,'ipa_scale':2,'gloss_font':'Junicode'}})['id']
        def read(id):return next(r for r in self.ok('/api/languages') if r['id']==id)
        self.assertEqual(json.loads(read(a)['metadata']),metadata)
        before=read(b)
        self.ok('/api/save-language',{'id':a,'revision':read(a)['revision'],'name':'A','metadata':{**metadata,'gloss_scale':.6},'_language':a})
        self.assertEqual(read(b),before)
        state=self.ok('/api/undo-state?language='+a)
        self.ok('/api/undo',{'generation':state['generation'],'_language':a})
        self.assertEqual(json.loads(read(a)['metadata']),metadata)
        self.assertEqual(read(b),before)

    def test_new_row_settings_reject_invalid_values_without_writes(self):
        for key in ['ipa_scale','morpheme_scale','gloss_scale','translation_scale']:
            for invalid in [True,None,0,3,'1',{},[]]:
                self.assertEqual(self.call('/api/save-language',{'name':'Invalid','metadata':{key:invalid}})[0],400,(key,invalid))
        for key in ['gloss_variant','translation_variant']:
            for invalid in [None,'smallcaps',True,{}]:
                self.assertEqual(self.call('/api/save-language',{'name':'Invalid','metadata':{key:invalid}})[0],400)
        for key in ['gloss_font','translation_font']:
            self.assertEqual(self.call('/api/save-language',{'name':'Invalid','metadata':{key:'not-a-font'}})[0],400)
        self.assertEqual(len(self.ok('/api/languages')),1)

if __name__=='__main__':unittest.main()
