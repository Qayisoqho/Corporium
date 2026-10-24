import copy
import unittest
import test_inline

class SlotTests(unittest.TestCase):
    setUp=test_inline.InlineTests.setUp
    tearDown=test_inline.InlineTests.tearDown
    call=test_inline.InlineTests.call
    entries=test_inline.InlineTests.entries
    seed=test_inline.InlineTests.seed
    layer=test_inline.InlineTests.layer
    annotate=test_inline.InlineTests.annotate
    undo=test_inline.InlineTests.undo
    word=test_inline.InlineTests.word
    example=test_inline.InlineTests.example

    def draft(self,kind,e):
        d=self.call('/api/annotations?kind='+kind+'&id='+e['id'])[1]
        return dict(kind=kind,id=e['id'],revision=d['revision'],before=copy.deepcopy(d['cells']),layers=d['layers'],cells=d['cells'],body=d['body'],slot_ids=[w['id'] for w in d['words']])

    def test_reorder_insert_layers_and_undo(self):
        e=self.seed();l=self.layer();self.annotate('corpus',e,l);d=self.draft('corpus',e);old=copy.deepcopy(d)
        d['slot_ids'].reverse();d['body']['words'].reverse()
        d['slot_ids'].insert(1,'new:test');d['body']['words'].insert(1,dict(form='new',gloss='新'))
        d['cells'].append(dict(unit_id='new:test',layer_id=l['id'],value='V'))
        code,r=self.call('/api/inline-save',d);self.assertEqual(code,200,r)
        fresh=self.draft('corpus',e);self.assertEqual(fresh['slot_ids'][2],old['slot_ids'][0]);self.assertEqual(fresh['slot_ids'][0],old['slot_ids'][1])
        self.assertEqual({c['unit_id']:c['value'] for c in fresh['cells']},{old['slot_ids'][0]:'NOUN',fresh['slot_ids'][1]:'V'})
        self.assertEqual(self.undo()[0],200);self.assertEqual(self.draft('corpus',e)['slot_ids'],old['slot_ids'])

    def test_delete_confirmation_orphans_and_empty_sentence(self):
        e=self.seed();l=self.layer();self.annotate('corpus',e,l);d=self.draft('corpus',e)
        d['slot_ids']=[];d['body']['words']=[];d['cells']=[]
        self.assertEqual(self.call('/api/inline-save',d)[0],400)
        d['delete_confirmed']=True;code,r=self.call('/api/inline-save',d);self.assertEqual(code,200,r)
        self.assertEqual(len(self.call('/api/annotations?kind=corpus&id='+e['id'])[1]['orphaned']),1)
        d=self.draft('corpus',e);d['slot_ids']=['new:blank','new:filled'];d['body']['words']=[dict(form='',gloss=''),dict(form='go',gloss='去')];d['cells']=[]
        code,r=self.call('/api/inline-save',d);self.assertEqual(code,200,r)
        self.assertEqual([w['form'] for w in self.draft('corpus',e)['body']['words']],['go'])

    def test_independent_identity_and_invalid_slots(self):
        e=self.example(self.word());d=self.draft('independent',e);old=d['slot_ids'][0]
        d['slot_ids'].insert(0,'new:test');d['body']['words'].insert(0,dict(form='new',gloss='新'))
        code,r=self.call('/api/inline-save',d);self.assertEqual(code,200,r)
        self.assertEqual(self.draft('independent',e)['slot_ids'][1],old)
        d=self.draft('independent',e);d['slot_ids'][0]=old
        self.assertEqual(self.call('/api/inline-save',d)[0],400)

