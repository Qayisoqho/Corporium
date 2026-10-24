import unittest,json
import server,punctuation
import test_lexicon,test_annotations,test_dictionary_manager
from corpus import parse,export_entry

class PunctuationTests(unittest.TestCase):
    setUp=test_lexicon.LexiconTests.setUp
    tearDown=test_lexicon.LexiconTests.tearDown
    call=test_lexicon.LexiconTests.call
    seed=test_lexicon.LexiconTests.seed
    entries=test_lexicon.LexiconTests.entries
    undo=test_lexicon.LexiconTests.undo
    word=test_lexicon.LexiconTests.word
    link=test_lexicon.LexiconTests.link
    layer=test_annotations.AnnotationTests.layer
    annotate=test_annotations.AnnotationTests.annotate
    example=test_dictionary_manager.DictionaryManagerTests.example

    def plan(self,b):
        code,p=self.call('/api/punctuation-preview',b);self.assertEqual(code,200,p);return p
    def apply(self,b,p):return self.call('/api/punctuation-apply',{**b,'token':p.get('token')})

    def test_text_ids_layers_links_export_idempotence_and_undo(self):
        e=self.seed('#pass([ipa], (([« home. »],[家]),([home],[家])), [translation])');x=self.word();self.link(e['words'][0]['unit_id'],x)
        layer=self.layer();d=self.annotate('corpus',e,layer);oldid=d['words'][0]['id'];otherid=d['words'][1]['id']
        b={'text_id':e['text_id']};p=self.plan(b);self.assertEqual(len(p['changes']),1,p)
        code,r=self.apply(b,p);self.assertEqual(code,200,r)
        after=self.entries()[0];self.assertEqual([w['form'] for w in after['words']],['«','home','.','»','home'])
        self.assertEqual(after['words'][1]['unit_id'],oldid);self.assertEqual(after['words'][4]['unit_id'],otherid)
        self.assertEqual(after['words'][1]['extra_layers'][0]['value'],'NOUN')
        self.assertEqual(self.call('/api/unit-dictionary?id='+oldid)[1]['link']['lexeme_id'],x['id'])
        self.assertEqual(after['ipa'],'ipa');self.assertEqual(after['translation'],'translation')
        self.assertEqual(after['words'][0]['morphemes'],[])
        self.assertEqual(self.call('/api/unit-dictionary?id='+after['words'][0]['unit_id'])[1]['unit_type'],'punctuation')
        checked,errors=parse(export_entry(after));self.assertEqual(errors,[]);self.assertEqual([w['form'] for w in checked[0]['words']],[w['form'] for w in after['words']])
        repeated=self.plan(b);self.assertEqual(repeated['changes'],[])
        generation=self.call('/api/undo-state')[1]['generation']
        self.assertEqual(self.apply(b,repeated)[0],200)
        self.assertEqual(self.call('/api/undo-state')[1]['generation'],generation)
        self.assertEqual(self.undo()[0],200);self.assertEqual(self.entries()[0]['words'][0]['form'],'« home. »')
        self.assertEqual(self.undo('redo')[0],200);self.assertEqual(self.entries()[0]['words'][1]['unit_id'],oldid)

    def test_bang_confirmation_stale_preview_and_ambiguous(self):
        e=self.seed('#pass([ipa], (([soma!],[家]),([soma, ama],[家和父亲]),([so-ma],[家]),([soma...],[家])), [t])')
        b={'text_id':e['text_id'],'internal':True};p=self.plan(b);self.assertTrue(p['needs_bang_confirmation'])
        self.assertEqual(self.apply(b,p)[0],400)
        b['bang_confirmed']=True;p=self.plan(b);self.assertEqual(len(p['changes']),2,p);self.assertEqual(len(p['blocked']),1)
        e['notes']='changed';self.assertEqual(self.call('/api/save',e)[0],200)
        self.assertEqual(self.apply(b,p)[0],400)
        p=self.plan(b);self.assertEqual(self.apply(b,p)[0],200)
        forms=[w['form'] for w in self.entries()[0]['words']];self.assertIn('...',forms);self.assertIn('soma, ama',forms);self.assertIn('so-ma',forms)

    def test_independent_layers_scope_and_custom_settings(self):
        x=self.word();e=self.example(x);e['body']['words']=[{'form':'home|','gloss':'家'}]
        code,e=self.call('/api/example-save',e);self.assertEqual(code,200,e)
        layer=self.layer();d=self.annotate('independent',e,layer);uid=d['words'][0]['id']
        b={'records':[{'kind':'independent','id':e['id']}],'symbols':['|']};p=self.plan(b)
        self.assertEqual(self.apply(b,p)[0],200)
        d=self.call('/api/annotations?kind=independent&id='+e['id'])[1]
        self.assertEqual([w['form'] for w in d['body']['words']],['home','|']);self.assertEqual(d['words'][0]['id'],uid);self.assertEqual(d['orphaned'],[])
        self.assertEqual(d['body']['targets'][0]['lexeme_id'],x['id']);self.assertEqual(self.call('/api/punctuation-settings?language=ordos')[1]['symbols'],['|'])
        lid=self.call('/api/save-language',{'name':'Other','metadata':{}})[1]['id'];self.assertEqual(self.call('/api/punctuation-preview',{**b,'_language':lid})[0],400)
        self.assertEqual(self.undo()[0],200);self.assertEqual(len(self.call('/api/annotations?kind=independent&id='+e['id'])[1]['body']['words']),1)

    def test_longest_edge_and_internal_rules(self):
        opt={'symbols':['.','...','«','»',','],'internal':False}
        self.assertEqual(punctuation.split('« soma... »',opt),[('«',True),('soma',False),('...',True),('»',True)])
        self.assertEqual(punctuation.split('so,ma',opt),[('so,ma',False)])
        self.assertEqual(punctuation.split('so,ma',{**opt,'internal':True}),[('so',False),(',',True),('ma',False)])
        with self.assertRaises(ValueError):punctuation.options({'symbols':['word']})
    def test_brackets_export_and_morpheme_link_preserved(self):
        e=self.seed('#gloss([ipa], (("[home]",[家]),), [translation])');x=self.word();uid=e['words'][0]['morphemes'][0]['unit_id'];self.link(uid,x)
        b={'text_id':e['text_id']};p=self.plan(b);self.assertEqual(len(p['changes']),1,p);self.assertEqual(self.apply(b,p)[0],200)
        after=self.entries()[0];self.assertEqual([w['form'] for w in after['words']],['[','home',']'])
        self.assertEqual(after['words'][1]['morphemes'][0]['unit_id'],uid)
        self.assertEqual(self.call('/api/unit-dictionary?id='+uid)[1]['link']['lexeme_id'],x['id'])
        checked,errors=parse(export_entry(after));self.assertEqual(errors,[]);self.assertEqual([w['form'] for w in checked[0]['words']],['[','home',']'])
        self.assertEqual(self.call('/api/lexeme-link',{'unit_id':after['words'][0]['unit_id'],'lexeme_id':x['id']})[0],400)
        # Re-saving through the full editor must retain the punctuation identity.
        after['notes']='note';self.assertEqual(self.call('/api/save',after)[0],200)
        self.assertTrue(self.entries()[0]['words'][0]['punctuation'])
