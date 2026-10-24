import copy
import unittest
import corpus
import test_inline_slots


class CleanupTests(unittest.TestCase):
    setUp=test_inline_slots.SlotTests.setUp
    tearDown=test_inline_slots.SlotTests.tearDown
    call=test_inline_slots.SlotTests.call
    seed=test_inline_slots.SlotTests.seed
    entries=test_inline_slots.SlotTests.entries
    undo=test_inline_slots.SlotTests.undo
    draft=test_inline_slots.SlotTests.draft
    layer=test_inline_slots.SlotTests.layer
    annotate=test_inline_slots.SlotTests.annotate

    def ok(self,path,b=None):
        code,data=self.call('/api/'+path,b);self.assertEqual(code,200,data);return data

    def test_separators_only_connect_filled_cells(self):
        for before,after in [('root-GEN-NOM-','root-GEN-NOM'),('root-GEN-.NOM-_','root-GEN-NOM'),('root--GEN==PL++','root-GEN=PL'),('-.GEN','GEN'),('A_/B;','A_B'),('GEN.#sub[].','GEN'),('._-=+',''),('root<GEN.SG>-','root<GEN.SG>'),('A#sub[2]-B_','A#sub[2]-B')]:
            with self.subTest(before=before):self.assertEqual(corpus.compact_gloss(before),after)
        self.assertEqual(corpus.compact_empty_pairs('a--b=','A--B='),('a-b','A-B'))
        self.assertEqual(corpus.compact_empty_pairs('a-n','A-'),('a-n','A-'))

    def test_edit_delete_insert_sequence_and_both_save_formats(self):
        e=self.seed('#pass([keep], (([root-gen-dat],[root-GEN-DAT.PL]),), [keep])')
        for explicit in (False,True):
            d=self.draft('corpus',e);old=d['body']['words'][0]['gloss'];d['body']['words'][0]['gloss']='root-GEN-NOM-'
            if not explicit:d.pop('slot_ids')
            self.ok('inline-save',d);saved=self.draft('corpus',e)
            self.assertEqual(saved['body']['words'][0]['gloss'],'root-GEN-NOM');self.assertEqual(saved['body']['warnings'],[])
            self.assertEqual(self.undo()[0],200);self.assertEqual(self.draft('corpus',e)['body']['words'][0]['gloss'],old)

    def test_all_empty_positions_symbols_and_protected_links_are_removed(self):
        for kind in ('corpus','independent'):
            words=[dict(form=f,gloss=g) for f,g in [('left','L'),('#',''),(',', ''),('right','R'),('x','X')]]
            if kind=='corpus':
                record=self.ok('import',dict(title='cleanup',content='#pass([], (([left],[L]),([#],[]),([,],[]),([right],[R]),([x],[X])), [])'))
                record=self.ok('entries?text='+record['id'])['items'][0]
            else:record=self.ok('example-save',dict(body=dict(ipa='keep',words=words)))
            target=self.ok('morpheme-save',dict(form='x',body=dict(gloss='X')))
            source=self.ok('segmentation?kind='+kind+'&id='+record['id'])
            self.ok('segmentation-link',dict(kind=kind,id=record['id'],revision=source['revision'],word=4,key='@word',lexeme_id=target['id'],lexeme_revision=target['revision']))
            d=self.draft(kind,record);before=copy.deepcopy(d);kept=d['slot_ids'][3]
            for i in (0,1,2,4):d['body']['words'][i].update(form='',gloss='')
            self.ok('inline-save',d);saved=self.draft(kind,record)
            self.assertEqual([w['form'] for w in saved['body']['words']],['right']);self.assertEqual(saved['slot_ids'],[kept])
            if kind=='independent':self.assertTrue(saved['body']['targets'][0]['segmentation_ref']['detached'])
            self.assertEqual(self.undo()[0],200);restored=self.draft(kind,record)
            self.assertEqual(restored['slot_ids'],before['slot_ids']);self.assertEqual([w['form'] for w in restored['body']['words']],[w['form'] for w in before['body']['words']])

    def test_empty_middle_component_pair_and_whole_legacy_slot(self):
        e=self.seed('#pass([], (([a--b],[A--B]),([#],[]),([tail],[T])), [])')
        d=self.draft('corpus',e);d.pop('slot_ids');d['body']['words'][0].update(form='aa--b',gloss='A--B');d['body']['words'][1].update(form='',gloss='')
        self.ok('inline-save',d);saved=self.draft('corpus',e)
        self.assertEqual([(w['form'],w['gloss']) for w in saved['body']['words']],[('aa-b','A-B'),('tail','T')])

    def test_layer_content_of_cleared_pair_remains_recoverable_and_undoable(self):
        e=self.seed();l=self.layer();self.annotate('corpus',e,l);d=self.draft('corpus',e);uid=d['slot_ids'][0]
        d['body']['words'][0].update(form='',gloss='');d['cells'][0]['value']='typed before clearing'
        self.ok('inline-save',d);saved=self.draft('corpus',e)
        self.assertNotIn(uid,saved['slot_ids']);self.assertEqual(saved['cells'][0]['value'],'typed before clearing')
        self.assertEqual(self.ok('annotations?kind=corpus&id='+e['id'])['orphaned'][0]['value'],'typed before clearing')
        self.assertEqual(self.undo()[0],200);self.assertEqual(self.draft('corpus',e)['cells'][0]['value'],'NOUN')

    def test_full_and_tab_save_entries_share_changed_pair_cleanup(self):
        e=self.seed('#pass([], (([root-gen-dat],[root-GEN-DAT.PL]),([#],[]),([tail],[T])), [])')
        fresh=self.entries()[0];fresh.update(notes='');fresh['words'][0]['gloss']='root-GEN-NOM-';fresh['words'][1].update(form='',gloss='')
        self.ok('save',fresh)
        self.assertEqual([(w['form'],w['gloss']) for w in self.draft('corpus',e)['body']['words']],[('root-gen-dat','root-GEN-NOM'),('tail','T')])
        ex=self.ok('example-save',dict(body=dict(words=[dict(form='root-gen-dat',gloss='root-GEN-NOM-'),dict(form='',gloss=''),dict(form='tail',gloss='T')])))
        self.assertEqual([(w['form'],w['gloss']) for w in ex['body']['words']],[('root-gen-dat','root-GEN-NOM'),('tail','T')])
