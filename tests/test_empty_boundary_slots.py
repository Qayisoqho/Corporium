import unittest
import corpus
import test_inline_slots


class EmptyBoundaryTests(unittest.TestCase):
    for name in ('setUp','tearDown','call','entries','seed','layer','annotate','undo','draft'):
        locals()[name]=getattr(test_inline_slots.SlotTests,name)

    def test_all_empty_boundary_combinations_compact_but_escaped_literals_survive(self):
        for form in ('=','~','<>','< >','-','+','＝','=~<>-+'):
            for gloss in ('','=', '~', '<>','...'):
                with self.subTest(form=form,gloss=gloss):self.assertEqual(corpus.compact_empty_pairs(form,gloss),('',''))
        for form,gloss in [(r'\~',''),('x~',''),('','LOC'),('<a>',''),('#',''),('=','0')]:
            with self.subTest(form=form,gloss=gloss):self.assertNotEqual(corpus.compact_empty_pairs(form,gloss),('',''))

    def test_cleared_existing_slot_retires_layer_and_undo_restores_identity(self):
        e=self.seed();layer=self.layer();self.annotate('corpus',e,layer);old=self.draft('corpus',e)
        for marker in ('=','~','<>','-','+'):
            d=self.draft('corpus',e);d['body']['words'][0].update(form=marker,gloss='')
            code,r=self.call('/api/inline-save',d);self.assertEqual(code,200,r)
            fresh=self.draft('corpus',e);self.assertEqual(len(fresh['slot_ids']),len(old['slot_ids'])-1)
            self.assertNotIn(old['slot_ids'][0],fresh['slot_ids'])
            self.assertEqual(len(self.call('/api/annotations?kind=corpus&id='+e['id'])[1]['orphaned']),1)
            self.undo();self.assertEqual(self.draft('corpus',e)['slot_ids'],old['slot_ids'])

    def test_full_tab_save_discards_only_changed_empty_boundary_cells(self):
        e=self.seed();e['words'][0].update(form='=',gloss='');e['notes']=''
        code,r=self.call('/api/save',e);self.assertEqual(code,200,r)
        self.assertEqual(len(self.entries()[0]['words']),1)
        self.undo();self.assertEqual(len(self.entries()[0]['words']),2)
