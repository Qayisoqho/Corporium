import unittest
import test_morpheme_registry


class MorphemeSyncTests(unittest.TestCase):
    for helper in ('setUp','tearDown','call','seed','entries','undo','fixture','assign'):
        locals()[helper]=getattr(test_morpheme_registry.MorphemeRegistryTests,helper)

    def api(self,path,body=None):
        code,result=self.call('/api/'+path,body)
        self.assertEqual(code,200,result)
        return result

    def setup_shared(self):
        entry,x=self.fixture()
        a,b=x['body']['word_structure']['analyses']
        a['components'][0]['readings']=['ha']
        b['components'][0].update(form='local-form',readings=['local-reading'])
        x=self.api('lexeme-save',x)
        m=self.api('morpheme-save',dict(form='home',body=dict(gloss='家',readings=['ha'])))
        code,result=self.assign(x,create=None,morpheme_id=m['id'],morpheme_revision=m['revision'],components=[dict(analysis_id='a',component_id='c'),dict(analysis_id='b',component_id='d')])
        self.assertEqual(code,200,result)
        return entry,x,self.api('morpheme?id='+m['id'])

    def test_shared_form_reading_gloss_sync_preserves_local_override_and_corpus(self):
        entry,x,m=self.setup_shared()
        before=self.api('entries')['items']
        changed=self.api('morpheme-save',{**m,'form':'new-home','body':{**m['body'],'gloss':'新释义','readings':['new-reading']}})
        fresh=self.api('lexeme?id='+x['id']);a,b=fresh['body']['word_structure']['analyses']
        self.assertEqual((a['components'][0]['form'],a['components'][0]['gloss'],a['components'][0]['readings']),('new-home','新释义',['new-reading']))
        self.assertEqual((b['components'][0]['form'],b['components'][0]['gloss'],b['components'][0]['readings']),('local-form','另一解释',['local-reading']))
        self.assertGreater(fresh['revision'],x['revision'])
        after=self.api('entries')['items']
        self.assertEqual([(e['ipa'],e['translation'],[(w['form'],w['gloss']) for w in e['words']]) for e in before],[(e['ipa'],e['translation'],[(w['form'],w['gloss']) for w in e['words']]) for e in after])
        self.assertEqual(self.call('/api/lexeme-save',x)[0],400)
        table=self.api('homophones?language=ordos')
        self.assertEqual({g['reading'] for g in table['groups']},{'new-reading','local-reading'})
        self.assertFalse(any('待核对' in r['reason'] for r in table['review']))
        item=next(g for g in table['groups'] if g['reading']=='new-reading')['items'][0]
        self.assertEqual((item['identity'],item['form'],item['gloss']),(changed['id'],'new-home','新释义'))
        local=next(g for g in table['groups'] if g['reading']=='local-reading')['items'][0]
        self.assertEqual(local['form'],'new-home')
        self.assertEqual(local['sources'][0]['form'],'local-form')

    def test_sync_is_one_undo_step_and_redo_restores_all_owners(self):
        _,x,m=self.setup_shared()
        changed=self.api('morpheme-save',{**m,'form':'renamed','body':{**m['body'],'readings':['new']}})
        self.assertEqual(self.api('undo-state')['undo']['label'],'保存语素')
        self.assertEqual(self.undo()[0],200)
        self.assertEqual(self.api('morpheme?id='+m['id'])['form'],'home')
        self.assertEqual(self.api('lexeme?id='+x['id'])['body']['word_structure']['analyses'][0]['components'][0]['form'],'home')
        state=self.api('undo-state');self.api('redo',dict(generation=state['generation']))
        self.assertEqual(self.api('morpheme?id='+m['id'])['form'],'renamed')
        self.assertEqual(self.api('lexeme?id='+x['id'])['body']['word_structure']['analyses'][0]['components'][0]['form'],'renamed')
        self.assertEqual({g['reading'] for g in self.api('homophones?language=ordos')['groups']},{'new','local-reading'})

    def test_stale_save_cannot_partially_sync_components(self):
        _,x,m=self.setup_shared();self.api('morpheme-save',{**m,'form':'first'})
        self.assertEqual(self.call('/api/morpheme-save',{**m,'form':'stale'})[0],400)
        self.assertEqual(self.api('lexeme?id='+x['id'])['body']['word_structure']['analyses'][0]['components'][0]['form'],'first')


if __name__=='__main__':unittest.main()
