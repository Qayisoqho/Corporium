import json
import unittest
import test_lexicon
import server

class ContextualReplaceTests(unittest.TestCase):
    setUp=test_lexicon.LexiconTests.setUp
    tearDown=test_lexicon.LexiconTests.tearDown
    call=test_lexicon.LexiconTests.call
    seed=test_lexicon.LexiconTests.seed
    entries=test_lexicon.LexiconTests.entries
    undo=test_lexicon.LexiconTests.undo

    def ok(self,path,body=None):
        code,result=self.call('/api/'+path,body);self.assertEqual(code,200,result);return result

    def example(self,**body):
        return self.ok('example-save',dict(body=dict(ipa='old old',translation='old',words=[dict(form='root-n',gloss='根-NPST')],targets=[],**body)))

    def plan(self,**extra):
        args=dict(owner_kind='independent',field='ipa',find='old',replacement='new');args.update(extra)
        return args,self.ok('text-replace-preview',args)

    def apply(self,args,p,**extra):
        return self.call('/api/text-replace-apply',{**args,'token':p['token'],'keys':[c['key'] for c in p['changes']],**extra})

    def test_independent_scope_partial_results_undo_and_other_language(self):
        corpus=self.seed('#pass([old old], (([root-n],[根-NPST]),), [old])');example=self.example()
        foreign=self.ok('save-language',dict(name='Other',metadata={}))['id']
        self.ok('example-save',dict(_language=foreign,body=dict(ipa='old old',words=[],targets=[])))
        args,p=self.plan();self.assertEqual(p['records'],1);self.assertEqual(len(p['changes']),2)
        code,r=self.apply(args,p,keys=[p['changes'][0]['key']]);self.assertEqual(code,200,r)
        self.assertEqual(self.ok('independent-example?id='+example['id'])['body']['ipa'],'new old')
        self.assertEqual(self.entries()[0]['ipa'],corpus['ipa'])
        self.assertEqual(self.ok('example-library?language='+foreign)['items'][0]['body']['ipa'],'old old')
        self.assertEqual(self.undo()[0],200);self.assertEqual(self.undo('redo')[0],200)
        args,p=self.plan();self.assertEqual(len(p['changes']),1);self.assertEqual(self.apply(args,p)[0],200)
        self.assertEqual(self.ok('independent-example?id='+example['id'])['body']['ipa'],'new new')
        self.assertEqual(self.call('/api/text-replace-preview',dict(**args,text_id=corpus['text_id']))[0],400)

    def test_fixed_slots_keep_dictionary_targets_layers_and_language_marks(self):
        example=self.example();eid=example['id']
        morph=self.ok('morpheme-save',dict(form='n',body=dict(gloss='NPST',entry_type='affix')))
        d=self.ok('segmentation?kind=independent&id='+eid)
        self.ok('segmentation-link',dict(kind='independent',id=eid,revision=d['revision'],word=0,key='1:host',lexeme_id=morph['id'],lexeme_revision=morph['revision']))
        code=self.ok('timeline-code-save',dict(name='混用',metadata={}))['id']
        d=self.ok('code-detail?kind=independent&id='+eid)
        self.ok('code-save',dict(kind='independent',record_id=eid,token=d['token'],word_ids=[d['words'][0]['id']],code_id=code))
        layer=self.ok('layer-save',dict(name='额外行',anchor='word',font='Junicode',style='normal',size=100,position=0,visible=True,searchable=True))
        a=self.ok('annotations?kind=independent&id='+eid)
        self.ok('annotation-save',dict(kind='independent',id=eid,revision=a['revision'],before=a['cells'],layers=a['layers'],cells=[dict(unit_id=a['words'][0]['id'],layer_id=layer['id'],value='保留')],discard=[]))
        before=self.ok('independent-example?id='+eid)['body']
        args,p=self.plan(field='form',find='root',replacement='stem')
        self.assertFalse(p['conflicts']);self.assertEqual(self.apply(args,p)[0],200)
        after=self.ok('independent-example?id='+eid)['body'];self.assertEqual(after['words'][0]['form'],'stem-n')
        self.assertEqual(after['words'][0]['annotation_id'],before['words'][0]['annotation_id'])
        self.assertEqual(after['targets'][0]['lexeme_id'],before['targets'][0]['lexeme_id'])
        self.assertEqual(after['targets'][0]['segmentation_ref']['unit_form'],'n')
        self.assertFalse(after['targets'][0].get('segmentation_review'))
        self.assertEqual(self.ok('annotations?kind=independent&id='+eid)['cells'][0]['value'],'保留')
        self.assertEqual(self.ok('code-detail?kind=independent&id='+eid)['spans'][0]['positions'],[0])
        self.assertEqual(self.undo()[0],200)
        self.assertEqual(self.ok('independent-example?id='+eid)['body']['words'][0]['form'],'root-n')

    def test_stale_morpheme_target_and_invalid_batch_are_atomic(self):
        e=self.example();m=self.ok('morpheme-save',dict(form='n',body=dict(gloss='NPST',entry_type='affix')))
        d=self.ok('segmentation?kind=independent&id='+e['id'])
        self.ok('segmentation-link',dict(kind='independent',id=e['id'],revision=d['revision'],word=0,key='1:host',lexeme_id=m['id'],lexeme_revision=m['revision']))
        args,p=self.plan();m['body']['entry_type']='clitic';self.ok('morpheme-save',m)
        self.assertEqual(self.apply(args,p)[0],400)
        self.assertEqual(self.ok('independent-example?id='+e['id'])['body']['ipa'],'old old')
        self.example();args,p=self.plan(replacement='[');self.assertTrue(p['blocked'])
        self.assertEqual(self.apply(args,p)[0],400)
        self.assertEqual({r['body']['ipa'] for r in self.ok('example-library')['items']},{'old old'})

if __name__=='__main__':unittest.main()
