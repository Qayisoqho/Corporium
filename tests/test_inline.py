import copy
import unittest
import test_annotations

class InlineTests(unittest.TestCase):
    setUp=test_annotations.AnnotationTests.setUp
    tearDown=test_annotations.AnnotationTests.tearDown
    call=test_annotations.AnnotationTests.call
    seed=test_annotations.AnnotationTests.seed
    entries=test_annotations.AnnotationTests.entries
    word=test_annotations.AnnotationTests.word
    example=test_annotations.AnnotationTests.example
    layer=test_annotations.AnnotationTests.layer
    annotate=test_annotations.AnnotationTests.annotate
    undo=test_annotations.AnnotationTests.undo

    def draft(self,kind,e):
        d=self.call('/api/annotations?kind='+kind+'&id='+e['id'])[1]
        return dict(kind=kind,id=e['id'],revision=d['revision'],before=copy.deepcopy(d['cells']),layers=d['layers'],cells=d['cells'],body=d['body'])

    def test_core_layers_notes_save_and_single_undo(self):
        e=self.seed();l=self.layer();self.annotate('corpus',e,l)
        d=self.draft('corpus',e);d['body']['words'][0].update(form='house-n',gloss='住所-GEN');d['body']['notes']='核查读音\n与发言人确认';d['cells'][0]['value']='N'
        code,r=self.call('/api/inline-save',d);self.assertEqual(code,200,r)
        current=self.draft('corpus',e)
        self.assertEqual(current['body']['notes'],d['body']['notes']);self.assertEqual(current['cells'][0]['value'],'N')
        self.assertNotEqual(current['cells'][0]['unit_id'],d['cells'][0]['unit_id'])
        self.assertEqual(self.call('/api/annotations?kind=corpus&id='+e['id'])[1]['orphaned'],[])
        self.assertEqual(self.call('/api/inline-save',d)[0],400)
        self.assertEqual(self.undo()[0],200)
        restored=self.draft('corpus',e);self.assertEqual(restored['body']['words'][0]['form'],'home-n');self.assertEqual(restored['cells'][0]['value'],'NOUN');self.assertFalse(restored['body'].get('notes'))

    def test_independent_keeps_targets_and_ids(self):
        x=self.word();y=self.word();e=self.example(x,[y]);l=self.layer();self.annotate('independent',e,l)
        d=self.draft('independent',e);oldid=d['body']['words'][0]['annotation_id'];d['body']['words'][0].update(form='house',gloss='住所');d['body']['notes']='用例备注'
        code,r=self.call('/api/inline-save',d);self.assertEqual(code,200,r)
        for word in (x,y):
            b=self.call('/api/dictionary-examples?id='+word['id'])[1][0]['body']
            self.assertEqual(b['notes'],'用例备注');self.assertEqual(b['words'][0]['annotation_id'],oldid)
        self.assertEqual(self.undo()[0],200)
        self.assertEqual(self.draft('independent',e)['body']['words'][0]['form'],'home')

    def test_invalid_core_rolls_back_layers_and_conflicts(self):
        e=self.seed();l=self.layer();self.annotate('corpus',e,l);d=self.draft('corpus',e)
        d['cells'][0]['value']='changed';d['body']['words'][0]['form']='['
        self.assertEqual(self.call('/api/inline-save',d)[0],400)
        self.assertEqual(self.draft('corpus',e)['cells'][0]['value'],'NOUN')
        d=self.draft('corpus',e)
        self.assertEqual(self.call('/api/layer-save',{**l,'name':'POS'})[0],200)
        self.assertEqual(self.call('/api/inline-save',d)[0],400)

    def test_explicit_slot_correspondence_when_words_swap(self):
        e=self.seed();l=self.layer();self.annotate('corpus',e,l);d=self.draft('corpus',e)
        d['body']['words'].reverse()
        code,r=self.call('/api/inline-save',d);self.assertEqual(code,200,r)
        fresh=self.call('/api/annotations?kind=corpus&id='+e['id'])[1]
        self.assertEqual(fresh['cells'][0]['unit_id'],fresh['words'][0]['id'])
