"""Cross-feature workflows found by the October 2026 comprehensive audit."""
import copy
import json
import unittest
import corpus
import reduplication
import server
import test_reduplication
import test_segmentation


class AuditInteractionTests(unittest.TestCase):
    for name in ('setUp','tearDown','call','seed','entries','get','undo','example','draft'):
        locals()[name]=getattr(test_reduplication.ReduplicationTests,name)
    group=test_segmentation.SegmentationTests.group

    def ok(self,path,body=None):
        status,result=self.call('/api/'+path,body)
        self.assertEqual(status,200,result)
        return result

    api=ok
    detail=get

    def test_tilde_tags_reach_candidates_formal_analysis_and_cached_audit(self):
        for kind in ('corpus','independent'):
            self.example(kind,gloss='PL~go.SG')
        audit=self.ok('grammar-audit')
        self.assertEqual({r['symbol']:r['uses'] for r in audit['unknown']},{'PL':2,'SG':2})
        self.ok('grammar-save',dict(symbol='PL',description='复数'))
        self.ok('grammar-save',dict(symbol='SG',description='单数'))
        cached=self.ok('grammar-audit?reuse=1')
        self.assertEqual({r['symbol']:r['uses'] for r in cached['tags']},{'PL':2,'SG':2})
        run=self.ok('analysis-run',dict(query=dict(scope={'source':'all'},conditions=[dict(field='tag',value='PL',mode='exact')])))
        self.assertEqual(run['summary']['hits'],2)

    def test_clearing_a_word_preserves_manual_groups_like_deleting_it(self):
        for kind in ('corpus','independent'):
            e=self.example(kind,form='a-root-b',gloss='PST-root-PST')
            before=self.group(e,kind)['body']['words'][0]
            draft=self.draft(kind,e)
            draft['body']['words'][0].update(form='',gloss='')
            self.ok('inline-save',draft)
            body=self.get(e,kind)['body']
            self.assertEqual(body.get('orphaned_morphology',[]),[{k:before[k] for k in ('form','gloss','morph_groups') if k in before}])
            self.assertEqual(self.undo()[0],200)
            self.assertEqual(self.get(e,kind)['body']['words'][0]['morph_groups'],before['morph_groups'])

    def test_retargeting_base_releases_unused_word_protection(self):
        e=self.example()
        d=test_reduplication.ReduplicationTests.save(self,e,base=dict(word=1,key='@word'))
        oldid=d['body']['words'][1]['redup_id']
        d=test_reduplication.ReduplicationTests.save(self,e,relation_id=d['body']['reduplications'][0]['id'])
        self.assertNotIn('redup_id',d['body']['words'][1])
        draft=self.ok('annotations?kind=corpus&id='+e['id'])
        self.assertFalse(draft['words'][1]['protected'])
        self.assertEqual(self.undo()[0],200)
        self.assertEqual(self.get(e)['body']['words'][1]['redup_id'],oldid)

    def test_preview_invalid_relation_shape_returns_a_validation_error(self):
        body=corpus.analyze(dict(ipa='',translation='',words=[dict(form='a~b',gloss='RED~root')]))
        for malformed in ([None],[{'id':'r','source':None,'base':None,'type':'partial'}]):
            with self.subTest(value=malformed):
                status,result=self.call('/api/reduplication-preview',dict(body={**body,'reduplications':malformed}))
                self.assertEqual(status,400,result)

    def test_full_editor_removal_keeps_infix_confirmation(self):
        import segmentation
        word=dict(form='a<x>b',gloss='root<TAG>',infix_confirmation=dict(form='a<x>b',gloss='root<TAG>'))
        old=dict(words=[word]);new=dict(words=[])
        segmentation.preserve(old,new)
        self.assertEqual(new.get('orphaned_morphology'),[word])

    def test_reduplication_boundary_survives_inherited_whole_word_gloss(self):
        import test_gloss_inheritance
        helper=test_gloss_inheritance.GlossInheritanceTests
        x=helper.word(self,'jepasu',['go'])
        for kind in ('corpus','independent'):
            e=self.example(kind)
            helper.link(self,e,x,'@word',kind=kind)
            self.assertEqual(self.get(e,kind)['body']['words'][0]['gloss'],'RED~go')

    def test_pending_reduplication_is_reported_by_full_check(self):
        e=self.example()
        test_reduplication.ReduplicationTests.save(self,e)
        draft=self.draft('corpus',e);draft['body']['words'][0]['form']='ja~jepasu'
        self.ok('inline-save',draft)
        self.assertTrue(self.get(e)['body']['reduplication_info']['relations'][0]['review'])
        audit=self.ok('grammar-audit?issue=pending')
        self.assertTrue(any(r['id']==e['id'] and '重叠' in r['message'] for r in audit['items']))

