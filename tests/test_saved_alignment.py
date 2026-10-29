import copy
import unittest
import corpus
import test_inline_slots


class SavedAlignmentTests(unittest.TestCase):
    for name in ('setUp','tearDown','call','seed','entries','undo','draft','layer','annotate'):
        locals()[name]=getattr(test_inline_slots.SlotTests,name)

    def test_cleanup_rechecks_boundaries_without_losing_nonempty_cells(self):
        cases=[('opened-ne','开.pst-sg-','opened-ne','开.pst-sg'),
               ('opened--ne','开.pst-sg','opened-ne','开.pst-sg'),
               ('a--b','A-.-B','a-b','A-B'),('a-=b','A=B','a=b','A=B'),
               ('a--b','A-ZERO-B','a--b','A-ZERO-B'),
               ('a=b','A-B','a=b','A-B'),('a=-b','A=B','a=-b','A=B'),
               (r'a\--b','A-B',r'a\--b','A-B')]
        for form,gloss,f,g in cases:
            with self.subTest(form=form,gloss=gloss):self.assertEqual(corpus.normalize_edited_pair(form,gloss),(f,g))

    def test_user_edit_both_sentence_kinds_and_both_inline_payloads(self):
        source=self.seed('#pass([opened-ne], (([opened-ne],[开.pst-pl]),), [Opened example])')
        code,ind=self.call('/api/example-save',dict(body=dict(ipa='opened-ne',translation='Opened example',words=[dict(form='opened-ne',gloss='开.pst-pl')],targets=[])))
        self.assertEqual(code,200,ind)
        for kind,record in [('corpus',source),('independent',ind)]:
            for slots in [True,False]:
                with self.subTest(kind=kind,slots=slots):
                    d=self.draft(kind,record);original=copy.deepcopy(d);uid=d['slot_ids'][0]
                    d['body']['words'][0]['gloss']='开.pst-sg-'
                    if not slots:d.pop('slot_ids')
                    code,r=self.call('/api/inline-save',d);self.assertEqual(code,200,r)
                    fresh=self.draft(kind,record);w=fresh['body']['words'][0]
                    self.assertEqual((w['form'],w['gloss']),('opened-ne','开.pst-sg'))
                    self.assertEqual([(m['form'],m['gloss']) for m in w['morphemes']],[('opened','开.pst'),('ne','sg')])
                    self.assertEqual(fresh['slot_ids'][0],uid)
                    self.undo();self.assertEqual(self.draft(kind,record)['body']['words'][0]['gloss'],original['body']['words'][0]['gloss'])

    def test_empty_form_cell_realigns_layers_stay_with_word_and_undo_restores(self):
        e=self.seed('#pass([ipa], (([opened--ne],[开.pst--pl]),), [Opened example])');layer=self.layer();self.annotate('corpus',e,layer)
        d=self.draft('corpus',e);uid=d['slot_ids'][0];d['body']['words'][0]['gloss']='开.pst-sg-'
        code,r=self.call('/api/inline-save',d);self.assertEqual(code,200,r)
        fresh=self.draft('corpus',e);self.assertEqual((fresh['body']['words'][0]['form'],fresh['body']['words'][0]['gloss']),('opened-ne','开.pst-sg'))
        self.assertEqual(fresh['slot_ids'][0],uid);self.assertEqual(fresh['cells'][0]['value'],'NOUN')
        self.undo();old=self.draft('corpus',e);self.assertEqual(old['body']['words'][0]['form'],'opened--ne');self.assertEqual(old['cells'][0]['value'],'NOUN')

    def test_full_tab_save_reanalyzes_clean_pair_and_leaves_untouched_material(self):
        e=self.seed('#pass([ipa], (([opened--ne],[开.pst--pl]),([m],[GEN.])), [Opened example])')
        e['notes']='';e['words'][0]['gloss']='开.pst-sg-'
        code,r=self.call('/api/save',e);self.assertEqual(code,200,r)
        words=self.entries()[0]['words'];self.assertEqual((words[0]['form'],words[0]['gloss']),('opened-ne','开.pst-sg'))
        self.assertEqual(words[1]['gloss'],'GEN.')
