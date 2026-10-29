import copy,unittest
import test_sentence_dictionary as base

class DictionaryIntakeRefreshTests(unittest.TestCase):
    for name in ('setUp','tearDown','call','api','source','detail','args','undo'):
        locals()[name]=getattr(base.SentenceDictionaryTests,name)

    def target(self,kind):
        if kind=='lexeme':
            return self.api('lexeme-save',dict(headword='go',body=dict(usages=[dict(id='u',senses=[dict(id='s',short_gloss='GO')])]))), 'u','s'
        m=self.api('morpheme-save',dict(form='go',body=dict(gloss='GO')))
        return m,'@morpheme','@main'

    def link(self,src,target,uid,sid):
        return self.api('segmentation-link',dict(**self.args(src),word=0,key='@word',lexeme_id=target['id'],lexeme_revision=target['revision'],usage_id=uid,sense_id=sid))

    def state(self,x):return self.api('dictionary-reference-state?id='+x['id'])

    def test_reference_state_becomes_deletable_after_both_source_types_are_unlinked(self):
        for kind in ('lexeme','morpheme'):
            x,uid,sid=self.target(kind);a=self.source('corpus',[('go','GO')]);b=self.source('independent',[('go','GO')])
            self.link(a,x,uid,sid);self.link(b,x,uid,sid)
            state=self.state(x);self.assertEqual(state['references'],dict(corpus=1,independent=1));self.assertFalse(state['can_delete'])
            e=self.api('lexeme-examples?id='+x['id'])['items'][0]
            self.api('lexeme-unlink',dict(id=e['id'],revision=e['revision']))
            self.assertEqual(self.state(x)['references'],dict(corpus=0,independent=1));self.assertFalse(self.state(x)['can_delete'])
            ex=self.api('independent-example?id='+b['id'])
            self.api('dictionary-examples-unlink',dict(lexeme_id=x['id'],items=[dict(id=ex['id'],revision=ex['revision'])]))
            state=self.state(x);self.assertTrue(state['can_delete']);self.assertEqual(state['revision'],x['revision'])
            self.api(kind+'-delete',dict(id=x['id'],revision=x['revision'],confirmed=True))

    def test_reference_state_is_read_only_and_checks_scope_and_missing_records(self):
        x,_,_=self.target('lexeme');before=self.api('undo-state');self.assertTrue(self.state(x)['can_delete']);after=self.api('undo-state')
        self.assertEqual(before['workspace_revision'],after['workspace_revision']);self.assertEqual(before['generation'],after['generation'])
        self.assertEqual(self.call('/api/dictionary-reference-state?id='+x['id']+'&language=missing')[0],400)
        self.assertEqual(self.call('/api/dictionary-reference-state?id=missing')[0],400)

    def test_component_reference_still_blocks_deletion_without_sentence_links(self):
        x=self.api('lexeme-save',dict(headword='host',body=dict(word_structure=dict(analyses=[dict(id='a',components=[dict(id='c',form='root',gloss='ROOT')])]))))
        m=self.api('morpheme-assign',dict(lexeme_id=x['id'],lexeme_revision=x['revision'],components=[dict(analysis_id='a',component_id='c',revision=0)],create=dict(form='root',body=dict(gloss='ROOT'))))
        mid=m.get('id') or m.get('morpheme_id')
        if not mid:mid=self.api('morpheme-components?id='+x['id'])['items'][0]['link']['morpheme_id']
        state=self.api('dictionary-reference-state?id='+mid);self.assertEqual(state['components'],1);self.assertFalse(state['can_delete'])

    def proposal(self,src,**values):
        return dict(**self.args(src),word=0,key='@word',mode='new',target_kind='morpheme',form='new-'+src['kind'],gloss='北方',gloss_addition='LOC',show_gloss_addition=True,**values)

    def test_morpheme_intake_saves_free_gloss_and_tags_separately_in_both_sources(self):
        self.api('grammar-save',dict(symbol='LOC',description='Local'))
        for kind in ('corpus','independent'):
            src=self.source(kind,[('n','原标注')]);b=self.proposal(src);p=self.api('sentence-dictionary-preview',b)
            result=self.api('sentence-dictionary-apply',dict(b,token=p['token']));m=self.api('morpheme?id='+result['id'])
            self.assertEqual(m['body']['gloss'],'北方');self.assertEqual(m['body']['gloss_addition'],'LOC');self.assertTrue(m['body']['show_gloss_addition'])
            self.assertEqual(self.detail(src)['body']['words'][0]['gloss'],'北方.LOC')
            self.undo();self.assertEqual(self.call('/api/morpheme?id='+result['id'])[0],400);self.assertEqual(self.detail(src)['body']['words'][0]['gloss'],'原标注')

    def test_tag_only_intake_and_hidden_tags_do_not_invent_an_empty_display(self):
        src=self.source('corpus',[('n','原标注')]);b=self.proposal(src);b.update(gloss='',gloss_addition='NEG')
        p=self.api('sentence-dictionary-preview',b);x=self.api('sentence-dictionary-apply',dict(b,token=p['token']));self.assertEqual(self.api('morpheme?id='+x['id'])['body']['gloss'],'')
        src=self.source('independent',[('n','原标注')]);b=self.proposal(src);b.update(gloss='',gloss_addition='NEG',show_gloss_addition=False)
        p=self.api('sentence-dictionary-preview',b);self.assertEqual(self.call('/api/sentence-dictionary-apply',dict(b,token=p['token']))[0],400)

    def test_intake_confirmation_binds_tag_text_and_visibility(self):
        src=self.source('independent',[('n','原标注')]);b=self.proposal(src);p=self.api('sentence-dictionary-preview',b)
        for changed in [dict(b,gloss_addition='DAT'),dict(b,show_gloss_addition=False)]:
            self.assertEqual(self.call('/api/sentence-dictionary-apply',dict(changed,token=p['token']))[0],400)
        self.assertEqual(self.api('lexemes?targets=all')['total'],0)

    def test_new_native_meaning_keeps_hidden_tags_separate(self):
        target,uid,sid=self.target('morpheme');src=self.source('independent',[('go','原标注')])
        b=dict(**self.args(src),word=0,key='@word',mode='sense',target_kind='morpheme',target_id=target['id'],usage_id=uid,gloss='方向',gloss_addition='LOC',show_gloss_addition=False)
        p=self.api('sentence-dictionary-preview',b);self.api('sentence-dictionary-apply',dict(b,token=p['token']))
        sense=self.api('morpheme?id='+target['id'])['body']['senses'][0]
        self.assertEqual((sense['gloss'],sense['gloss_addition'],sense['show_gloss_addition']),('方向','LOC',False))
