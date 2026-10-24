import copy
import json
import unittest
import server
import test_text_tools
import test_segmentation
import test_annotations

class DuplicateTests(unittest.TestCase):
    setUp=test_text_tools.TextToolsTests.setUp
    tearDown=test_text_tools.TextToolsTests.tearDown
    call=test_text_tools.TextToolsTests.call
    seed=test_text_tools.TextToolsTests.seed
    entries=test_text_tools.TextToolsTests.entries
    undo=test_text_tools.TextToolsTests.undo
    draft=test_text_tools.TextToolsTests.draft

    def payload(self,e,**extra):
        return dict(id=e['id'],text_id=e['text_id'],revision=e['revision'],order=[v['id'] for v in self.call('/api/positions?id='+e['text_id'])[1]],where='after',anchor_id=e['id'],**extra)

    def test_full_clone_independent_ids_groups_links_layers_undo(self):
        e=self.seed('#pass([ipa], (([we-amos-la],[pst-go-pst]),), [translation])')
        h=test_segmentation.SegmentationTests();h.call=self.call
        d=h.group(e);x=h.word();h.link(d,x,d['body']['words'][0]['morphemes'][0]['key'])
        layer=test_annotations.AnnotationTests.layer(self);test_annotations.AnnotationTests.annotate(self,'corpus',e,layer)
        e=self.entries()[0];e['notes']='研究备注';self.assertEqual(self.call('/api/save',e)[0],200)
        e=self.entries()[0];original=self.draft('corpus',e)
        code,result=self.call('/api/duplicate-entry',self.payload(e));self.assertEqual(code,200,result)
        entries=self.entries();self.assertEqual(len(entries),2);a,b=entries
        self.assertEqual([r['position'] for r in entries],[1,2]);self.assertEqual(b['id'],result['id'])
        for field in ('ipa','translation','notes'):self.assertEqual(a[field],b[field])
        self.assertEqual(b['words'][0]['group_reviews'],[])
        self.assertNotEqual(a['words'][0]['unit_id'],b['words'][0]['unit_id'])
        self.assertNotEqual(a['words'][0]['morphemes'][0]['unit_id'],b['words'][0]['morphemes'][0]['unit_id'])
        clone=self.draft('corpus',b);self.assertEqual(clone['cells'][0]['value'],original['cells'][0]['value']);self.assertNotEqual(clone['cells'][0]['id'],original['cells'][0]['id'])
        self.assertEqual(clone['cells'][0]['unit_id'],clone['slot_ids'][0])
        self.assertEqual(self.call('/api/lexeme-examples?id='+x['id'])[1]['total'],2)
        self.assertEqual(self.undo()[0],200);self.assertEqual(len(self.entries()),1)
        self.assertEqual(self.undo('redo')[0],200);self.assertEqual(self.entries()[1]['id'],b['id'])
        clone=self.draft('corpus',b);clone['body']['translation']='副本修改';self.assertEqual(self.call('/api/inline-save',clone)[0],200)
        self.assertEqual(self.entries()[0]['translation'],'translation');self.assertEqual(self.entries()[1]['translation'],'副本修改')

    def test_positions_stale_scope_and_cancel_has_no_write(self):
        e=self.seed('#pass([a], (([a],[A]),), [first])\n#pass([b], (([b],[B]),), [second])')
        p=self.payload(e);p['where']='before';p['anchor_id']=e['id']
        code,r=self.call('/api/duplicate-entry',p);self.assertEqual(code,200,r);self.assertEqual(r['position'],1)
        self.assertEqual(self.entries()[1]['id'],e['id']);self.assertEqual(self.call('/api/duplicate-entry',p)[0],400)
        p=self.payload(self.entries()[1]);p['where']='end';p['revision']=-1
        self.assertEqual(self.call('/api/duplicate-entry',p)[0],400)
        p=self.payload(self.entries()[1]);p['anchor_id']='missing';self.assertEqual(self.call('/api/duplicate-entry',p)[0],400)
        other=self.call('/api/save-language',dict(name='Other',metadata={}))[1]['id']
        p=self.payload(self.entries()[1]);self.assertEqual(self.call('/api/duplicate-entry',{**p,'_language':other})[0],400)
        p['where']='end';code,r=self.call('/api/duplicate-entry',p);self.assertEqual(code,200,r);self.assertEqual(r['position'],4)

    def test_retired_evidence_and_sentence_layers_remain_independent(self):
        e=self.seed('#pass([ipa], (([we-amos-la],[pst-go-pst]),), [translation])')
        h=test_segmentation.SegmentationTests();h.call=self.call
        d=h.group(e);x=h.word();h.link(d,x,d['body']['words'][0]['morphemes'][0]['key'])
        e=self.entries()[0];e['words'][0]['form']='wu-amos-la';e['notes']='';self.assertEqual(self.call('/api/save',e)[0],200)
        e=self.entries()[0];self.assertTrue(e['words'][0]['group_reviews'])
        code,r=self.call('/api/duplicate-entry',self.payload(e));self.assertEqual(code,200,r)
        b=self.entries()[1];self.assertTrue(b['words'][0]['group_reviews'])
        evidence=self.call('/api/lexeme-examples?id='+x['id'])[1]['items'];self.assertEqual(len(evidence),2);self.assertTrue(all(v['needs_review'] for v in evidence))
        with server.connect() as db:
            a_ids={v[0] for v in db.execute('SELECT id FROM corpus_units WHERE entry_id=?',(e['id'],))}
            b_ids={v[0] for v in db.execute('SELECT id FROM corpus_units WHERE entry_id=?',(b['id'],))}
        self.assertFalse(a_ids&b_ids);self.assertEqual(len(a_ids),len(b_ids))
