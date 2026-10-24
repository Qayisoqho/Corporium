import json
import unittest
import server
import test_annotations
import test_lexicon


class SentenceWorkflowTests(unittest.TestCase):
    setUp=test_annotations.AnnotationTests.setUp
    tearDown=test_annotations.AnnotationTests.tearDown
    call=test_annotations.AnnotationTests.call
    seed=test_annotations.AnnotationTests.seed
    entries=test_annotations.AnnotationTests.entries
    word=test_annotations.AnnotationTests.word
    layer=test_annotations.AnnotationTests.layer
    annotate=test_annotations.AnnotationTests.annotate
    undo=test_annotations.AnnotationTests.undo
    link=test_lexicon.LexiconTests.link

    def create(self,kind='independent',**extra):
        return self.call('/api/sentence-create',dict(kind=kind,body=dict(ipa='',translation='',notes='',words=[]),slot_ids=[],cells=[],layers=self.call('/api/layers')[1],**extra))

    def test_empty_save_and_single_undo(self):
        for kind in ('independent','corpus'):
            extra={}
            if kind=='corpus':extra['text_id']=self.call('/api/new-text',dict(title='Empty',empty=True))[1]['id']
            code,r=self.create(kind,**extra);self.assertEqual(code,200,r)
            self.assertEqual(self.call('/api/annotations?kind='+kind+'&id='+r['id'])[1]['words'],[])
            self.assertEqual(self.undo()[0],200)
            self.assertEqual(self.call('/api/annotations?kind='+kind+'&id='+r['id'])[0],400)
            self.assertEqual(self.undo('redo')[0],200)

    def test_creation_layers_and_failure_atomicity(self):
        e=self.seed();layer=self.layer()
        payload=dict(kind='corpus',text_id=e['text_id'],body=dict(ipa='',translation='',notes='',words=[dict(form='home',gloss='家')]),slot_ids=['new:one'],cells=[dict(unit_id='new:one',layer_id=layer['id'],value='N')],layers=[layer])
        code,r=self.call('/api/sentence-create',payload);self.assertEqual(code,200,r)
        d=self.call('/api/annotations?kind=corpus&id='+r['id'])[1]
        self.assertEqual(d['cells'][0]['unit_id'],d['words'][0]['id'])
        payload['cells'][0]['unit_id']='wrong'
        count=len(self.entries());self.assertEqual(self.call('/api/sentence-create',payload)[0],400);self.assertEqual(len(self.entries()),count)

    def test_batch_copy_preserves_links_and_undo(self):
        e=self.seed();x=self.word();self.link(e['words'][0]['morphemes'][0]['unit_id'],x)
        l=self.layer();self.annotate('corpus',e,l)
        other=self.call('/api/add',dict(text_id=e['text_id']))[1]
        target=self.call('/api/new-text',dict(title='Target',empty=True))[1]['id']
        code,r=self.call('/api/copy-entries',dict(source_id=e['text_id'],target_id=target,ids=[other['id'],e['id']],where='end'))
        self.assertEqual(code,200,r)
        rows=self.call('/api/entries?text='+target)[1]['items'];self.assertEqual(len(rows),2);self.assertEqual(rows[0]['ipa'],e['ipa'])
        self.assertNotEqual(rows[0]['id'],e['id'])
        self.assertEqual(self.call('/api/annotations?kind=corpus&id='+rows[0]['id'])[1]['cells'][0]['value'],'NOUN')
        with server.connect(audit=False) as db:self.assertEqual(db.execute('SELECT COUNT(*) FROM lexical_links').fetchone()[0],2)
        self.assertEqual(self.undo()[0],200);self.assertEqual(self.call('/api/entries?text='+target)[1]['total'],0)
        self.assertEqual(self.call('/api/entries?text='+e['text_id'])[1]['total'],2)

    def test_independent_all_text_and_auto_link(self):
        self.seed();self.word()
        payload=dict(kind='independent',body=dict(ipa='ind',translation='',words=[dict(form='home',gloss='家')]),slot_ids=['new:one'],cells=[],layers=[])
        code,r=self.call('/api/sentence-create',payload);self.assertEqual(code,200,r)
        allrows=self.call('/api/entries?include_independent=true')[1];self.assertEqual(allrows['total'],2)
        self.assertEqual(self.call('/api/entries?include_independent=true&q=ind')[1]['items'][0]['kind'],'independent')
        plan=self.call('/api/lexeme-auto-preview?language=ordos&text_id=@independent')[1];self.assertEqual(len(plan['matches']),1,plan)
        self.assertEqual(self.call('/api/lexeme-auto-link',dict(text_id='@independent',token=plan['token']))[0],200)
        self.assertEqual(len(self.call('/api/independent-example?id='+r['id'])[1]['body']['targets']),1)
        self.assertEqual(self.call('/api/lexeme-auto-link',dict(text_id='@independent',token=plan['token']))[0],400)
        self.assertEqual(self.undo()[0],200);self.assertEqual(self.call('/api/independent-example?id='+r['id'])[1]['body']['targets'],[])

    def test_cross_text_word_move_rejected_copy_allowed(self):
        s=self.seed();target=self.call('/api/new-text',dict(title='Other'))[1]['id'];t=self.call('/api/entries?text='+target)[1]['items'][0]
        a=self.call('/api/word-transfer-snapshot?kind=corpus&id='+s['id'])[1];z=self.call('/api/word-transfer-snapshot?kind=corpus&id='+t['id'])[1]
        p=dict(source=dict(kind='corpus',id=s['id'],token=a['transfer_token']),target=dict(kind='corpus',id=t['id'],token=z['transfer_token']),slots=[a['words'][0]['id']],mode='move',confirmed=True,position=0)
        self.assertEqual(self.call('/api/word-transfer',p)[0],400)
        p['mode']='copy';self.assertEqual(self.call('/api/word-transfer',p)[0],200)

    def test_survey_draft_commits_reference_and_layers_together(self):
        state=self.call('/api/survey?language=ordos')[1]
        node=self.call('/api/survey-save',dict(version=state['version'],title='Question',kind='question',body={}))[1]
        state=self.call('/api/survey?language=ordos')[1]
        code,r=self.create(survey_node=node['id'],survey_version=state['version']);self.assertEqual(code,200,r)
        detail=self.call('/api/survey-detail?language=ordos&id='+node['id'])[1]
        self.assertEqual(detail['items'][0]['record_id'],r['id'])
        self.assertEqual(self.undo()[0],200)
        self.assertEqual(self.call('/api/survey-detail?language=ordos&id='+node['id'])[1]['items'],[])
        self.assertEqual(self.call('/api/independent-example?id='+r['id'])[0],400)

if __name__=='__main__':unittest.main()
