import json
import unittest
from urllib.parse import urlencode
import server
import test_collaborators as base
import test_analysis_workspace as research

class PeopleDialogueTests(unittest.TestCase):
    setUp=base.CollaboratorTests.setUp
    tearDown=base.CollaboratorTests.tearDown
    call=base.CollaboratorTests.call
    detail=base.CollaboratorTests.detail
    mutation=base.CollaboratorTests.mutation
    add=base.CollaboratorTests.add
    person=base.CollaboratorTests.person
    assign=base.CollaboratorTests.assign
    links=base.CollaboratorTests.links
    execute=research.AnalysisTests.execute
    page=research.AnalysisTests.page

    def query(self,**scope):return self.execute(field='ipa',value='',scope={'source':'all',**scope})
    def dialogue(self,**extra):
        code,r=self.call('/api/dialogue?'+urlencode(dict(text_id=self.tid,session_id=self.sid,**extra)))
        self.assertEqual(code,200,r);return r
    def independent(self):
        with server.connect(audit=False) as db:
            body=dict(ipa='solo',translation='独立',notes='笔记',words=[dict(form='solo',gloss='N',annotation_id='slot')],targets=[])
            db.execute("INSERT INTO dictionary_examples(id,language_id,body) VALUES('solo','ordos',?)",(json.dumps(body),))
        return 'solo'
    def test_text_participant_does_not_infer_sentence_speaker(self):
        p=self.person();self.assign([dict(person_id=p,role='转写人')],'text',self.tid)
        self.assertEqual(self.query(speaker_ids=[p])['summary']['sentences'],0)
        self.assertEqual(self.query(collaborator_ids=[p],collaborator_role='转写人')['summary']['sentences'],2)
        self.assertEqual(self.query(collaborator_ids=[p],collaborator_role='发言人')['summary']['sentences'],0)
        self.assertEqual(self.query(collaborator_ids=['missing'])['summary']['sentences'],0)
    def test_inheritance_conflict_manual_and_explicit_empty(self):
        a,b=self.person(),self.person('乙');track=self.detail()['tracks'][0]['id']
        self.mutation('track',track_id=track,name='甲',speaker_id=a);self.add()
        self.assertEqual(self.query(speaker_ids=[a])['summary']['sentences'],1)
        self.mutation('track',name='乙',kind='sentence',speaker_id=b);other=self.detail()['tracks'][1]['id'];self.add(track=other)
        self.assertEqual(self.query(speaker_ids=[a])['summary']['sentences'],0)
        self.assertEqual(self.query(speaker_state='conflict')['summary']['sentences'],1)
        self.assign([dict(person_id=b,role='发言人')]);self.assertEqual(self.query(speaker_ids=[b])['summary']['sentences'],1)
        self.assign([]);self.assertEqual(self.query(speaker_state='unassigned')['summary']['sentences'],2)
    def test_independent_any_all_snapshot_and_text_scope(self):
        rid=self.independent();a,b=self.person(),self.person('乙')
        self.assign([dict(person_id=a,role='发言人'),dict(person_id=b,role='发言人')],'independent',rid)
        self.assign([dict(person_id=a,role='发言人')])
        q=self.query(speaker_ids=[a,b]);self.assertEqual(q['summary']['sentences'],2)
        q=self.query(speaker_ids=[a,b],speaker_match='all');self.assertEqual(q['summary']['sentences'],1)
        page=self.page(q,dimension='sentence_speaker');self.assertEqual({r['label'] for r in page['frequencies']},{'甲','乙'})
        record=page['items'][0]['record'];self.assertEqual(record['kind'],'independent');self.assertEqual(record['id'],'solo')
        self.assertEqual(self.query(text_id=self.tid,speaker_ids=[b])['summary']['sentences'],0)
        self.assertEqual(self.query(source='independent')['summary']['sentences'],1)
        code,saved=self.call('/api/analysis-save',dict(kind='snapshot',name='people',run_id=q['id']));self.assertEqual(code,200,saved)
        self.assign([],'independent',rid)
        frozen=self.page(saved,snapshot='true');self.assertEqual(frozen['items'][0]['record']['attribution']['names'],['甲','乙'])
    def test_independent_forms_morphemes_notes_and_layers(self):
        self.independent()
        for field,value in [('form','solo'),('morpheme','solo'),('notes','笔记')]:
            r=self.execute(field=field,value=value,conditions=[dict(field=field,value=value,mode='contains')],scope={'source':'independent'})
            self.assertEqual(r['summary']['sentences'],1,(field,r))
        code,layer=self.call('/api/layer-save',dict(name='独立词级层',font='Junicode',style='normal'));self.assertEqual(code,200,layer)
        d=self.call('/api/annotations?kind=independent&id=solo')[1]
        code,result=self.call('/api/annotation-save',dict(kind='independent',id='solo',revision=d['revision'],before=d['cells'],layers=d['layers'],cells=[dict(unit_id='slot',layer_id=layer['id'],value='noun')]))
        self.assertEqual(code,200,result)
        run=self.execute(field='layer_word:'+layer['id'],value='noun',scope={'source':'independent'})
        self.assertEqual(run['summary']['hits'],1);self.assertEqual(self.page(run)['items'][0]['record']['body']['words'][0]['extra_layers'][0]['value'],'noun')
    def test_dialogue_order_overlap_duplicates_and_original_positions(self):
        a,b=self.person(),self.person('乙');first=self.detail()['tracks'][0]['id']
        self.mutation('track',track_id=first,name='甲',speaker_id=a)
        self.mutation('track',name='乙',kind='sentence',speaker_id=b);second=self.detail()['tracks'][1]['id']
        self.add(100,700,1,first);self.add(100,500,0,second);self.add(800,900,1,first)
        r=self.dialogue();self.assertEqual([x['position'] for x in r['items']],[2,1,2]);self.assertEqual([x['overlap'] for x in r['items']],[True,True,False]);self.assertEqual(r['sentences'],2)
        self.assertEqual(r['items'][0]['occurrences'],2);self.assertEqual(r['items'][0]['attribution']['names'],['甲'])
        self.assertEqual(self.query()['summary']['sentences'],2)
        actual=self.call('/api/entries?text='+self.tid)[1]['items'];self.assertEqual([x['id'] for x in actual],self.eids)
    def test_pending_single_speaker_touching_and_scope(self):
        a=self.person();first=self.detail()['tracks'][0]['id'];self.mutation('track',track_id=first,name='甲',speaker_id=a)
        self.add(100,300);r=self.dialogue();self.assertEqual(r['unaligned'],1);self.assertIsNone(r['items'][1]['interval_id']);self.assertEqual(r['single_speaker'],a)
        self.add(300,400,1);self.assertFalse(any(x['overlap'] for x in self.dialogue()['items']))
        self.assertEqual(self.call('/api/dialogue?'+urlencode(dict(text_id=self.tid,session_id='missing')))[0],400)
        self.assertEqual(self.call('/api/dialogue?'+urlencode(dict(text_id=self.tid,session_id=self.sid,language='other')))[0],400)
    def test_overlap_across_page_boundary_and_manual_context(self):
        first=self.detail()['tracks'][0]['id'];a=self.person();b=self.person('乙')
        self.mutation('track',track_id=first,name='甲',speaker_id=a)
        self.mutation('track',name='长句',kind='sentence',speaker_id=b);second=self.detail()['tracks'][1]['id']
        self.add(0,40000,1,second)
        for i in range(12):self.add(i*2000+1,i*2000+1000,0,first)
        r=self.dialogue(page_size=10,page=2);self.assertEqual(r['pages'],2);self.assertEqual(r['total'],13)
        self.assertTrue(all(x['overlap'] for x in r['items']));self.assertEqual(len({x['overlap_group'] for x in r['items']}),1)
        self.assign([dict(person_id=b,role='发言人')]);r=self.dialogue(page_size=10,page=2)
        self.assertTrue(all(x['attribution']['names']==['乙'] for x in r['items']))

if __name__=='__main__':unittest.main()
