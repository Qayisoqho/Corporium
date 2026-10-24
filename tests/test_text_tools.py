import copy
import unittest
from urllib.parse import urlencode
import server
import test_lexicon
import test_inline_slots
import test_segmentation

class TextToolsTests(unittest.TestCase):
    setUp=test_lexicon.LexiconTests.setUp
    tearDown=test_lexicon.LexiconTests.tearDown
    call=test_lexicon.LexiconTests.call
    seed=test_lexicon.LexiconTests.seed
    entries=test_lexicon.LexiconTests.entries
    undo=test_lexicon.LexiconTests.undo
    word=test_lexicon.LexiconTests.word
    link=test_lexicon.LexiconTests.link
    draft=test_inline_slots.SlotTests.draft

    def plan(self,e,field,find,replacement,**more):
        b=dict(text_id=e['text_id'],field=field,find=find,replacement=replacement,**more)
        code,p=self.call('/api/text-replace-preview',b);self.assertEqual(code,200,p)
        return b,p
    def apply(self,b,p,**more):
        return self.call('/api/text-replace-apply',{**b,'token':p['token'],'keys':[c['key'] for c in p['changes']],**more})

    def test_notes_search_all_and_notes_only_dictionary_nested(self):
        e=self.seed();e['notes']='田野核查甲';self.assertEqual(self.call('/api/save',e)[0],200)
        for field in ('all','notes'):
            code,r=self.call('/api/entries?'+urlencode(dict(q='田野核查甲',field=field)));self.assertEqual(r['total'],1)
        self.assertEqual(self.call('/api/entries?'+urlencode(dict(q='田野核查甲',field='ipa')))[1]['total'],0)
        self.assertEqual(self.call('/api/save-text-info',dict(id=e['text_id'],revision=0,title='备注检索',metadata={'notes':'文本备注丁'}))[0],200)
        self.assertEqual(self.call('/api/entries?'+urlencode(dict(q='文本备注丁',field='notes',text=e['text_id'])))[1]['total'],1)
        x=self.word();x['body']['notes']='词条备注乙';x['body']['usages'][0]['senses'][0]['notes']='义项备注丙'
        self.assertEqual(self.call('/api/lexeme-save',x)[0],200)
        for q in ('词条备注乙','义项备注丙'):
            self.assertEqual(self.call('/api/lexemes?'+urlencode(dict(q=q)))[1]['total'],1)

    def test_inline_punctuation_conservative_and_undo(self):
        e=self.seed();d=self.draft('corpus',e)
        d['slot_ids']+=['new:punct','new:bang','new:boundary','new:gloss']
        d['body']['words'] += [dict(form='。',gloss=''),dict(form='!',gloss=''),dict(form='#',gloss=''),dict(form='?',gloss='Q')]
        code,r=self.call('/api/inline-save',d);self.assertEqual(code,200,r)
        result=self.entries()[0];self.assertEqual([w['unit_type'] for w in result['words'][-4:]],['punctuation','word','phonological_boundary','word'])
        self.assertTrue(any('可能是标点' in w for w in result['warnings']))
        self.assertEqual(self.undo()[0],200);self.assertEqual(len(self.entries()[0]['words']),len(e['words']))

    def test_replace_single_all_identity_links_layers_and_undo(self):
        e=self.seed('#pass([Aa aa], (([home-home],[家-家]),([home],[家])), [aa aa])');x=self.word()
        uid=e['words'][0]['morphemes'][0]['unit_id'];self.link(uid,x)
        before=self.call('/api/unit-dictionary?id='+uid)[1]['link']
        b,p=self.plan(e,'form','home','house');self.assertEqual(len(p['changes']),3);self.assertEqual(p['conflicts'],[])
        code,r=self.apply(b,p,keys=[p['changes'][0]['key']]);self.assertEqual(code,200,r)
        w=self.entries()[0]['words'][0];self.assertEqual(w['form'],'house-home');self.assertEqual(w['morphemes'][0]['unit_id'],uid)
        self.assertEqual(self.call('/api/unit-dictionary?id='+uid)[1]['link'],before)
        self.assertEqual(self.apply(b,p)[0],400)
        b,p=self.plan(e,'form','home','house');self.assertEqual(self.apply(b,p)[0],200)
        self.assertEqual([w['form'] for w in self.entries()[0]['words']],['house-house','house'])
        self.assertEqual(self.undo()[0],200);self.assertEqual(self.entries()[0]['words'][0]['form'],'house-home')
        self.assertEqual(self.undo('redo')[0],200)
        b,p=self.plan(e,'ipa','aa','Z',case=False);self.assertEqual(len(p['changes']),2);self.assertEqual(self.apply(b,p)[0],200)
        self.assertEqual(self.entries()[0]['ipa'],'Z Z');self.assertEqual(self.entries()[0]['translation'],'aa aa')
        b,p=self.plan(e,'translation','aa','',mode='suffix');self.assertEqual(self.apply(b,p)[0],200);self.assertEqual(self.entries()[0]['translation'],'aa ')

    def test_group_preserved_then_conflict_confirmation(self):
        e=self.seed('#pass([], (([we-amos-la],[pst-go-pst]),), [])')
        helper=test_segmentation.SegmentationTests();helper.call=self.call
        d=helper.group(e);x=helper.word();helper.link(d,x,d['body']['words'][0]['morphemes'][0]['key'])
        old=self.entries()[0]['words'][0];uid=old['morphemes'][0]['unit_id']
        b,p=self.plan(e,'form','we','wu');self.assertEqual(p['conflicts'],[])
        self.assertEqual(self.apply(b,p)[0],200)
        w=self.entries()[0]['words'][0];self.assertEqual(w['group_reviews'],[]);self.assertEqual(w['morphemes'][0]['unit_id'],uid)
        self.assertFalse(self.call('/api/lexeme-examples?id='+x['id'])[1]['items'][0]['needs_review'])
        b,p=self.plan(e,'form','-la','');self.assertTrue(p['conflicts'])
        generation=self.call('/api/undo-state')[1]['generation']
        code,r=self.apply(b,p);self.assertEqual(code,200);self.assertTrue(r['needs_confirmation'])
        self.assertEqual(self.entries()[0]['words'][0]['form'],'wu-amos-la');self.assertEqual(self.call('/api/undo-state')[1]['generation'],generation)
        self.assertEqual(self.apply(b,p,confirm_conflicts=True)[0],200)
        self.assertTrue(self.entries()[0]['words'][0]['group_reviews']);self.assertTrue(self.call('/api/lexeme-examples?id='+x['id'])[1]['items'][0]['needs_review'])
        self.assertEqual(self.undo()[0],200);self.assertEqual(self.entries()[0]['words'][0]['group_reviews'],[])

    def test_stale_link_scope_export_block_and_noop(self):
        e=self.seed();b,p=self.plan(e,'form','home','new');x=self.word();self.link(e['words'][0]['unit_id'],x)
        self.assertEqual(self.apply(b,p)[0],400)
        lid=self.call('/api/save-language',dict(name='Other',metadata={}))[1]['id']
        self.assertEqual(self.call('/api/text-replace-preview',{**b,'_language':lid})[0],400)
        b,p=self.plan(e,'translation',e['translation'],'[');self.assertTrue(p['blocked']);self.assertEqual(self.apply(b,p)[0],400)
        b,p=self.plan(e,'form','home','home');self.assertEqual(p['changes'],[])

    def test_unset_analysis_metadata(self):
        x=self.word();x['body']['word_structure']={'analyses':[{'components':[{'form':'home'}]}]}
        code,r=self.call('/api/lexeme-save',x);self.assertEqual(code,200,r)
        a=r['body']['word_structure']['analyses'][0];self.assertEqual(a['level'],'unspecified');self.assertNotIn('status',a);self.assertEqual(a['title'],'')

    def test_remaining_matches_do_not_revisit_replacement(self):
        e=self.seed('#pass([a a a], (([x],[X]),), [])')
        b,p=self.plan(e,'ipa','a','aa')
        code,r=self.apply(b,p,keys=[p['changes'][0]['key']],pending_keys=[c['key'] for c in p['changes']]);self.assertEqual(code,200,r)
        self.assertEqual(len(r['remaining_keys']),2)
        b,p=self.plan(e,'ipa','a','aa')
        self.assertEqual(len(p['changes']),4)
        code,r=self.apply(b,p,keys=r['remaining_keys'],pending_keys=r['remaining_keys']);self.assertEqual(code,200,r)
        self.assertEqual(r['remaining_keys'],[]);self.assertEqual(self.entries()[0]['ipa'],'aa aa aa')

    def test_protected_punctuation_and_replacement_layers(self):
        import test_annotations
        e=self.seed();x=self.word();self.link(e['words'][0]['unit_id'],x)
        layer=test_annotations.AnnotationTests.layer(self)
        test_annotations.AnnotationTests.annotate(self,'corpus',e,layer)
        d=self.draft('corpus',e);old_cells=copy.deepcopy(d['cells'])
        d['body']['words'][0].update(form='。',gloss='')
        code,result=self.call('/api/inline-save',d);self.assertEqual(code,200,result)
        self.assertEqual(self.entries()[0]['words'][0]['unit_type'],'word')
        self.assertEqual(self.undo()[0],200)
        b,p=self.plan(e,'form','home','house');self.assertEqual(self.apply(b,p)[0],200)
        self.assertEqual(self.draft('corpus',e)['cells'],old_cells)

    def test_replacement_atomic_on_invalid_export(self):
        e=self.seed('#pass([first], (([x],[X]),), [text])\n#pass([second], (([x],[X]),), [text])')
        b,p=self.plan(e,'ipa','i','[')
        self.assertTrue(p['blocked'])
        generation=self.call('/api/undo-state')[1]['generation']
        self.assertEqual(self.apply(b,p)[0],400)
        self.assertEqual([e['ipa'] for e in self.entries()],['first','second'])
        self.assertEqual(self.call('/api/undo-state')[1]['generation'],generation)
