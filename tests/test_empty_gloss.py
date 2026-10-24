import copy
import unittest
import corpus
import test_inline_slots


class EmptyGlossTests(unittest.TestCase):
    setUp=test_inline_slots.SlotTests.setUp
    tearDown=test_inline_slots.SlotTests.tearDown
    call=test_inline_slots.SlotTests.call
    seed=test_inline_slots.SlotTests.seed
    entries=test_inline_slots.SlotTests.entries
    undo=test_inline_slots.SlotTests.undo
    draft=test_inline_slots.SlotTests.draft

    def test_empty_tags_preserve_morpheme_boundaries_and_decorated_content(self):
        cases={'GEN.':'GEN','GEN_':'GEN','.SG':'SG','GEN..SG':'GEN.SG','GEN._SG':'GEN.SG',
               '根-GEN._=PL_':'根-GEN=PL','GEN.-':'GEN','-GEN_':'GEN','GEN.-_SG':'GEN-SG',
               'GEN#sub[SG].':'GEN#sub[SG]','根<GEN.SG>.':'根<GEN.SG>','[GEN.SG]_':'[GEN.SG]',
               'GEN_ _':'GEN','._':'','A-B=':'A-B'}
        for value,expected in cases.items():
            with self.subTest(value=value):self.assertEqual(corpus.compact_gloss(value),expected)

    def test_both_owners_and_inline_save_formats_normalize_only_changed_gloss(self):
        corpus_entry=self.seed('#pass([test], (([m],[GEN.SG]),), [test])')
        code,ind=self.call('/api/example-save',dict(body=dict(ipa='test',translation='test',words=[dict(form='m',gloss='GEN_SG')],targets=[])))
        self.assertEqual(code,200,ind)
        for kind,record in [('corpus',corpus_entry),('independent',ind)]:
            for slots in [True,False]:
                with self.subTest(kind=kind,slots=slots):
                    d=self.draft(kind,record);before=copy.deepcopy(d);uid=d['slot_ids'][0]
                    d['body']['words'][0]['gloss']='GEN.' if slots else 'GEN_'
                    if not slots:d.pop('slot_ids')
                    code,result=self.call('/api/inline-save',d);self.assertEqual(code,200,result)
                    saved=self.draft(kind,record);self.assertEqual(saved['body']['words'][0]['gloss'],'GEN')
                    self.assertEqual(saved['slot_ids'][0],uid)
                    self.assertEqual(self.undo()[0],200)
                    self.assertEqual(self.draft(kind,record)['body']['words'][0]['gloss'],before['body']['words'][0]['gloss'])
                    self.assertEqual(self.undo('redo')[0],200)
                    self.assertEqual(self.draft(kind,record)['body']['words'][0]['gloss'],'GEN')
                    self.assertEqual(self.undo()[0],200)


if __name__=='__main__':unittest.main()
