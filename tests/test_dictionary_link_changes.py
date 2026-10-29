import copy,json,unittest
from unittest.mock import patch
import server,dictionary_link_changes
import test_paradigms,test_long_task_writes


class LinkChangeTests(unittest.TestCase):
    for name in ('setUp','tearDown','call','api','source','detail','args','undo','complete','entry','get','link','gloss'):
        locals()[name]=getattr(test_paradigms.ParadigmTests,name)
    wait=test_long_task_writes.WriteTasks.wait
    submit=test_long_task_writes.WriteTasks.submit
    execute=test_long_task_writes.WriteTasks.execute

    def plan(self,body,kind='lexeme'):return self.api('dictionary-save-impact',dict(body,kind=kind))
    def save(self,body,kind='lexeme'):
        p=self.plan(body,kind)
        return self.api(kind+'-save',dict(body,link_change_token=p['token'],confirm_link_changes=True)),p

    def basic(self):
        return self.api('lexeme-save',dict(headword='go',body=dict(usages=[dict(id='verb',pos='V',senses=[dict(id='go-meaning',short_gloss='去'),dict(id='stay',short_gloss='留')])],variants=[dict(id='went',form='went')],notes='Keep me')))

    def test_sense_removal_reviews_both_sources_preserves_other_links_and_undo(self):
        x=self.basic();sources=[self.source(k,[('go','旧'),('go','留')]) for k in ('corpus','independent')]
        for src in sources:self.link(src,x,'go-meaning',None)
        x=self.get(x);before=copy.deepcopy(x);x['body']['usages'][0]['senses'].pop(0)
        p=self.plan(x);self.assertEqual((p['corpus'],p['independent'],p['sentences']),(1,1,2))
        self.assertEqual(self.call('/api/lexeme-save',x)[0],400);self.assertEqual(self.get(x),before)
        self.assertEqual(self.call('/api/lexeme-save',dict(x,link_change_token=p['token']))[0],400)
        result,_=self.save(x);self.assertEqual([self.gloss(s) for s in sources],['去','去']);self.assertEqual(result['body']['notes'],'Keep me')
        self.undo();self.assertEqual(self.get(x)['body'],before['body']);self.assertEqual([self.gloss(s) for s in sources],['去','去'])
        self.undo(True);self.assertEqual([self.gloss(s) for s in sources],['去','去'])

    def test_remove_paradigm_keeps_forms_and_only_detaches_removed_meanings(self):
        x=self.entry();a=self.source('corpus',[('went','past')]);b=self.source('independent',[('goes','present')]);self.link(a,x);self.link(b,x,'goes-meaning','goes')
        x=self.get(x);x['body']['paradigms'][0]['rows'].pop(0);result,p=self.save(x)
        self.assertEqual((p['corpus'],p['independent']),(1,0));self.assertEqual(self.gloss(a),'去.PST');self.assertEqual(self.gloss(b),'去.PRS.3SG')
        result['body']['paradigms'][0]['rows'][0]['realizations'][0]['meanings'][0]['short_gloss']='仍关联'
        self.api('lexeme-save',result);self.assertEqual(self.gloss(b),'仍关联');self.assertEqual(self.gloss(a),'去.PST')

    def test_whole_usage_and_variant_removal_are_reviewed(self):
        x=self.basic();a=self.source('corpus',[('went','typed')]);self.link(a,x,'go-meaning','went')
        x=self.get(x);x['body']['variants']=[];_,p=self.save(x);self.assertEqual(p['items'][0]['reason'],'form');self.assertEqual(self.gloss(a),'去')
        x=self.get(x);b=self.source('independent',[('go','typed')]);self.link(b,x,'stay',None);x=self.get(x);x['body']['usages']=[]
        _,p=self.save(x);self.assertEqual(p['independent'],1);self.assertEqual(self.gloss(b),'留')

    def test_blank_override_is_frozen_and_restored(self):
        x=self.entry();sources=[self.source(k,[('went','x')]) for k in ('corpus','independent')]
        for src in sources:
            self.link(src,x);d=self.detail(src);binding=d['body']['words'][0]['gloss_sources'][0]
            self.api('gloss-source-save',dict(kind=src['kind'],id=src['id'],revision=d['revision'],binding_id=binding['id'],binding_revision=binding['revision'],gloss_revision=d['body']['gloss_revision'],mode='override',value=''))
        x=self.get(x);x['body']['paradigms']=[];self.save(x);self.assertEqual([self.gloss(s) for s in sources],['',''])
        self.undo();self.assertEqual([self.gloss(s) for s in sources],['',''])

    def test_confirmation_binds_proposal_language_and_concurrent_links(self):
        x=self.entry();a=self.source('corpus',[('went','x')]);self.link(a,x);x=self.get(x);x['body']['paradigms']=[];p=self.plan(x)
        altered=copy.deepcopy(x);altered['body']['notes']='A different proposal'
        self.assertEqual(self.call('/api/lexeme-save',dict(altered,link_change_token=p['token'],confirm_link_changes=True))[0],400)
        b=self.source('independent',[('went','x')]);self.link(b,self.get(x))
        self.assertEqual(self.call('/api/lexeme-save',dict(x,link_change_token=p['token'],confirm_link_changes=True))[0],400)
        self.assertEqual(self.call('/api/dictionary-save-impact',dict(x,_language='missing'))[0],400)
        self.assertEqual(self.plan(x)['independent'],1)

    def test_failed_write_rolls_back_detach_and_background_save_is_one_step(self):
        x=self.entry();a=self.source('corpus',[('went','x')]);self.link(a,x);x=self.get(x);before=copy.deepcopy(x);x['body']['paradigms']=[];p=self.plan(x)
        with patch('lexicon.homonyms.clear_singleton',side_effect=ValueError('late failure')):
            changed=dict(x,headword='changed',link_change_token=p['token'],confirm_link_changes=True)
            # Changing the proposal must itself be reviewed first.
            p2=self.plan(changed);changed['link_change_token']=p2['token'];self.assertEqual(self.call('/api/lexeme-save',changed)[0],400)
        self.assertEqual(self.get(x),before);self.assertEqual(self.gloss(a),'去.PST')
        p=self.plan(x);self.execute('lexeme-save',dict(x,link_change_token=p['token'],confirm_link_changes=True));self.undo();self.assertEqual(self.get(x)['body'],before['body'])

    def test_native_morpheme_extra_sense_can_be_removed_after_confirmation(self):
        m=self.api('morpheme-save',dict(form='root',body=dict(gloss='根',senses=[dict(id='extra',gloss='另外')])));common=self.api('lexeme?id='+m['id'])
        src=self.source('independent',[('root','x')]);d=self.detail(src)
        self.api('segmentation-link',dict(**self.args(src),word=0,key='@word',link_revision=0,lexeme_id=m['id'],lexeme_revision=m['revision'],usage_id='@morpheme',sense_id='extra'))
        request=dict(id=m['id'],revision=m['revision'],form=m['form'],body={**m['body'],'senses':[]})
        self.assertEqual(self.plan(request,'morpheme')['independent'],1);self.save(request,'morpheme');self.assertEqual(self.gloss(src),'另外')
        self.undo();self.assertEqual(len(self.api('morpheme?id='+m['id'])['body']['senses']),1)

    def test_ordinary_meaning_edit_has_no_dependency_scan_or_confirmation(self):
        x=self.entry();x['body']['notes']='ordinary edit'
        with server.connect(audit=False) as db:
            old=self.get(x);statements=[];db.set_trace_callback(statements.append);plan=dictionary_link_changes.collect(db,old,x['body'])
            self.assertFalse(plan['items']);self.assertFalse(any('lexical_links' in sql for sql in statements))
        self.api('lexeme-save',x)

    def test_two_meanings_in_one_example_detach_only_the_deleted_binding(self):
        x=self.entry();src=self.source('independent',[('went','past'),('goes','present')]);self.link(src,x)
        self.api('segmentation-link',dict(**self.args(src),word=1,key='@word',link_revision=0,lexeme_id=x['id'],lexeme_revision=x['revision'],usage_id='verb',sense_id='goes-meaning',form_id='goes'))
        x=self.get(x);x['body']['paradigms'][0]['rows'].pop(0);saved,p=self.save(x)
        self.assertEqual((p['independent'],p['sentences']),(1,1));body=self.detail(src)['body'];self.assertEqual([w['gloss'] for w in body['words']],['去.PST','去.PRS.3SG'])
        saved['body']['paradigms'][0]['rows'][0]['realizations'][0]['meanings'][0]['short_gloss']='仍然跟随';self.api('lexeme-save',saved)
        self.assertEqual([w['gloss'] for w in self.detail(src)['body']['words']],['去.PST','仍然跟随'])
