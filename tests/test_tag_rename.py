import copy
import json
import unittest
import grammar_rename
import server
import test_grammar
import test_paradigm_inheritance
import test_component_links


class TagRenameTests(test_grammar.GrammarTests):
    def test_recognized_atoms_respect_lexical_words_scripts_person_and_underscore(self):
        old=dict(symbol='PST',aliases=['PAST'],language_id='ordos')
        for before,after in [('go.pst.direct','go.PRET.direct'),('go.past','go.PRET'),('pastoral','pastoral'),('PST_label','PST_label'),('pst#sub[A]','pst#sub[A]'),('#sup[pst]','#sup[PRET]'),('go.<pst>','go.<PRET>')]:
            self.assertEqual(grammar_rename.replace(before,old,'PRET'),after)
        old.update(symbol='SG',aliases=[])
        self.assertEqual(grammar_rename.replace('pron.3sg.dat',old,'SING'),'pron.3SING.dat')
        old.update(symbol='PASS')
        self.assertEqual(grammar_rename.replace('pass.[pass].PASS',old,'PASSIVE'),'pass.[PASSIVE].PASSIVE')

    def test_renaming_updates_dictionary_sentences_inheritance_and_undo(self):
        x=self.word();x['body']['usages'][0]['senses'][0]['short_gloss']='go.pst.direct'
        x=self.call('/api/lexeme-save',x)[1]
        e=self.seed('#pass([ipa], (([go],[go.pst.direct])), [translation])')
        independent=self.example(x);independent['body']['words'][0]['gloss']='go.pst.direct'
        self.assertEqual(self.call('/api/example-save',independent)[0],200)
        morph=self.call('/api/morpheme-save',dict(form='-d',body=dict(gloss='pst',gloss_addition='direct')))[1]
        tag=self.tag('PST');before=self.call('/api/undo-state')[1]['generation']
        code,result=self.call('/api/grammar-save',{**tag,'symbol':'PAST'})
        self.assertEqual(code,200,result);self.assertEqual(self.call('/api/undo-state')[1]['generation'],before+1)
        self.assertEqual(self.call('/api/lexeme?id='+x['id'])[1]['body']['usages'][0]['senses'][0]['short_gloss'],'go.PAST.direct')
        self.assertEqual(self.entries()[0]['words'][0]['gloss'],'go.PAST.direct')
        self.assertEqual(self.call('/api/dictionary-examples?id='+x['id'])[1][0]['body']['words'][0]['gloss'],'go.PAST.direct')
        self.assertEqual(self.call('/api/morpheme?id='+morph['id'])[1]['body']['gloss'],'PAST')
        self.undo();self.assertEqual(self.entries()[0]['words'][0]['gloss'],'go.pst.direct')
        self.undo('redo');self.assertEqual(self.entries()[0]['words'][0]['gloss'],'go.PAST.direct')

    def test_new_registration_keeps_text_and_inherited_paradigm_rename_keeps_links(self):
        helper=test_paradigm_inheritance.ParadigmInheritanceTests();helper.call=self.call
        helper.api=lambda p,b=None:self.call('/api/'+p,b)[1]
        b=test_paradigm_inheritance.body();b['usages'][0]['senses'][0]['short_gloss']='go.pst.direct'
        x=self.call('/api/lexeme-save',dict(headword='go',body=b))[1]
        self.tag('DIRECT');self.assertEqual(self.call('/api/lexeme?id='+x['id'])[1]['body']['usages'][0]['senses'][0]['short_gloss'],'go.pst.direct')
        tag=self.tag('PST');code,r=self.call('/api/grammar-save',{**tag,'symbol':'PAST'});self.assertEqual(code,200,r)
        x=self.call('/api/lexeme?id='+x['id'])[1]
        self.assertEqual(x['body']['usages'][0]['senses'][0]['short_gloss'],'go.PAST.direct')
        self.assertEqual(x['body']['paradigms'][0]['rows'][0]['realizations'][0]['meanings'][0]['gloss_mode'],'inherit')


class LinkedRenameTests(test_paradigm_inheritance.ParadigmInheritanceTests):
    def test_registered_rename_preserves_links_and_other_language(self):
        tag_id=self.api('grammar-save',dict(symbol='ACC'))['id']
        tag=next(t for t in self.api('grammar-tags') if t['id']==tag_id)
        x=self.entry();sources=[self.source(k,[('went','old')]) for k in ('corpus','independent')]
        for src in sources:self.link(src,x)
        self.api('grammar-save',{**tag,'symbol':'OBJ'})
        self.assertEqual([self.gloss(s) for s in sources],['1SG.OBJ']*2)
        self.assertEqual(self.api('lexeme-examples?id='+x['id'])['total'],1)
        self.assertEqual(len(self.api('dictionary-examples?id='+x['id'])),1)
        self.undo();self.assertEqual([self.gloss(s) for s in sources],['1SG.ACC']*2)
        self.undo(True);self.assertEqual([self.gloss(s) for s in sources],['1SG.OBJ']*2)

class ComponentRenameTests(test_component_links.ComponentLinkTests):
    def test_component_snapshot_renames_without_creating_review(self):
        self.call('/api/grammar-save',dict(symbol='PST'))
        tag=self.call('/api/grammar-tags')[1][0]
        e,x=self.fixture();x['body']['word_structure']['analyses'][0]['components'][0]['gloss']='pst'
        x=self.call('/api/lexeme-save',x)[1];self.assertEqual(self.link(e,x)[0],200)
        code,result=self.call('/api/grammar-save',{**tag,'symbol':'PAST'});self.assertEqual(code,200,result)
        uid=e['words'][0]['morphemes'][0]['unit_id'];link=self.call('/api/unit-dictionary?id='+uid)[1]['link']
        self.assertFalse(link['component_review']);self.assertEqual(link['component_ref']['snapshot']['component']['gloss'],'PAST')
