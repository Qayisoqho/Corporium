import json
import sqlite3
from contextlib import closing
import unittest
from pathlib import Path
import server
import grammar_survey
import test_timeline as base
from restore_backup import restore

class SurveyTests(unittest.TestCase):
    setUp=base.TimelineTests.setUp
    tearDown=base.TimelineTests.tearDown
    call=base.TimelineTests.call
    detail=base.TimelineTests.detail
    mutation=base.TimelineTests.mutation
    undo=base.TimelineTests.undo

    def state(self,lid='ordos'):
        code,r=self.call('/api/survey?language='+lid);self.assertEqual(code,200,r);return r
    def survey(self,endpoint,**b):
        b.setdefault('version',self.state(b.get('_language','ordos'))['version'])
        return self.call('/api/survey-'+endpoint,b)
    def node(self,title='长短元音',parent=None,kind='section',body=None):
        code,r=self.survey('save',title=title,parent_id=parent,kind=kind,body=body or {})
        self.assertEqual(code,200,r);return r['id']
    def example(self,nid):
        code,r=self.survey('new-example',node_id=nid,example=dict(ipa='aː',translation='回答',words=[dict(form='aː',gloss='INTJ'),dict(form='#',gloss='')]))
        self.assertEqual(code,200,r);return r['record_id']
    def evidence(self,nid):
        code,r=self.call('/api/survey-detail?language=ordos&id='+nid);self.assertEqual(code,200,r);return r['items']

    def test_template_no_corpus_and_editable_copy(self):
        before=self.call('/api/entries')[1]['total'];code,r=self.survey('template');self.assertEqual(code,200,r)
        nodes=self.state()['nodes'];self.assertEqual(len(nodes),37);self.assertEqual(len([n for n in nodes if n['parent_id'] is None]),5)
        self.assertIn('副词等其他状语',[n['title'] for n in nodes])
        self.assertEqual(self.call('/api/entries')[1]['total'],before)
        self.assertEqual(self.survey('copy',id=r['id'])[0],200)
        self.assertEqual(len(self.state()['nodes']),43)
        self.assertEqual(self.undo()[0],200);self.assertEqual(len(self.state()['nodes']),37)

    def test_autosave_returns_committed_node_and_version_without_a_followup_read(self):
        code,first=self.survey('save',title='页内条目',body=dict(content=[dict(text='说明',bold=True)]))
        self.assertEqual(code,200,first)
        self.assertEqual(first['version'],self.state()['version'])
        self.assertEqual(first['node']['revision'],1)
        self.assertEqual(first['node']['body']['content'],[dict(text='说明',bold=True)])
        code,second=self.call('/api/survey-save',dict(id=first['id'],title='改名',body=first['node']['body'],version=first['version']))
        self.assertEqual(code,200,second);self.assertEqual(second['node']['revision'],2)
        self.assertNotEqual(second['version'],first['version'])
        self.assertEqual(second['version'],self.state()['version'])
        code,stale=self.call('/api/survey-save',dict(id=first['id'],title='陈旧覆盖',body={},version=first['version']))
        self.assertEqual(code,400,stale)
        self.assertEqual(next(n for n in self.state()['nodes'] if n['id']==first['id'])['title'],'改名')

    def test_evidence_autosave_response_and_undo_keep_shared_sentence_unchanged(self):
        nid=self.node();rid=self.example(nid);e=self.evidence(nid)[0]
        before=self.call('/api/independent-example?id='+rid)[1]
        code,saved=self.survey('evidence',node_id=nid,evidence_id=e['id'],kind=e['kind'],record_id=rid,body=dict(notes=[dict(text='本处笔记')],judgment='自然'))
        self.assertEqual(code,200,saved)
        self.assertEqual(saved['evidence']['revision'],e['revision']+1)
        self.assertEqual(saved['evidence']['body']['notes'],[dict(text='本处笔记')])
        self.assertEqual(saved['version'],self.state()['version'])
        self.assertEqual(saved['node']['evidence_count'],1)
        self.assertEqual(self.call('/api/independent-example?id='+rid)[1],before)
        self.assertEqual(self.undo()[0],200)
        self.assertEqual(self.evidence(nid)[0]['body']['notes'],[])

    def test_multi_root_template_deduplicates_descendants_and_keeps_order(self):
        a=self.node('A');child=self.node('A child',a);b=self.node('B');self.node('B child',b)
        code,result=self.survey('template-file',action='save',node_ids=[b,child,a],name='Combined')
        self.assertEqual(code,200,result)
        folder=server.DB.parent/'templates'/'grammar'
        stored=json.loads((folder/(result['id']+'.json')).read_text(encoding='utf-8'))
        self.assertEqual(len(stored['nodes']),4)
        self.assertEqual([n['title'] for n in stored['nodes'] if n['parent_id'] is None],['A','B'])
        code,imported=self.survey('template-file',action='import',id=result['id'])
        self.assertEqual(code,200,imported)
        self.assertEqual([n['title'] for n in self.state()['nodes'] if n['parent_id'] is None],['A','B','A','B'])
        self.assertEqual(self.survey('template-file',action='save',node_ids=[a,'missing'],name='Invalid')[0],400)
        self.assertEqual(self.survey('template-file',action='save',node_ids=[],name='Empty')[0],400)

    def test_missing_source_notes_remain_editable_and_cannot_retarget(self):
        nid=self.node();rid=self.example(nid);e=self.evidence(nid)[0]
        with server.connect() as db:db.execute('DELETE FROM dictionary_examples WHERE id=?',(rid,))
        self.assertEqual(self.survey('evidence',node_id=nid,evidence_id=e['id'],kind='independent',record_id=rid,body={'notes':[{'text':'保留调查记录'}]})[0],200)
        self.assertEqual(self.evidence(nid)[0]['body']['notes'][0]['text'],'保留调查记录')
        self.assertEqual(self.survey('evidence',node_id=nid,evidence_id=e['id'],kind='independent',record_id='other',body={})[0],400)

    def test_empty_independent_sentence_can_be_created_linked_and_filled_later(self):
        nid=self.node()
        code,r=self.survey('new-example',node_id=nid,example={})
        self.assertEqual(code,200,r);rid=r['record_id']
        entry=self.call('/api/independent-example?id='+rid)[1]
        self.assertEqual(entry['body']['words'],[]);self.assertEqual(entry['body']['ipa'],'')
        code,saved=self.call('/api/example-save',dict(id=rid,revision=entry['revision'],body=dict(words=[dict(form='a',gloss=''),dict(form='#',gloss='')],targets=[])))
        self.assertEqual(code,200,saved)
        self.assertEqual(self.evidence(nid)[0]['record']['body']['words'][0]['form'],'a')

    def test_bulk_move_preserves_subtrees_order_and_undo(self):
        a=self.node('A');b=self.node('B');c=self.node('C',a);q=self.node('Question',c,'question');d=self.node('D',a)
        rid=self.example(q)
        code,result=self.survey('move',ids=[d,q,c],parent_id=b)
        self.assertEqual(code,200,result);self.assertEqual(result['moved_ids'],[c,d])
        nodes={n['id']:n for n in self.state()['nodes']}
        self.assertEqual(nodes[c]['parent_id'],b);self.assertEqual(nodes[q]['parent_id'],c)
        self.assertLess(nodes[c]['position'],nodes[d]['position']);self.assertEqual(self.evidence(q)[0]['record_id'],rid)
        self.assertEqual(self.undo()[0],200)
        self.assertEqual(next(n for n in self.state()['nodes'] if n['id']==c)['parent_id'],a)
        self.assertEqual(self.survey('move',ids=[a],parent_id=c)[0],400)
        self.assertEqual(self.survey('move',ids=[d],parent_id=q)[0],400)
        code,r=self.survey('move',ids=[d],parent_id=None,anchor_id=b,placement='before');self.assertEqual(code,200,r)
        roots=[n['id'] for n in self.state()['nodes'] if n['parent_id'] is None];self.assertEqual(roots,[a,d,b])

    def test_inline_notes_only_change_notes_and_reject_stale_update(self):
        nid=self.node('标题',body={'status':'done','content':[{'text':'说明'}]});old=self.state()['version']
        self.assertEqual(self.survey('notes',id=nid,notes=[{'text':'现场笔记','italic':True}])[0],200)
        n=self.state()['nodes'][0];self.assertEqual(n['title'],'标题');self.assertEqual(n['body']['status'],'done');self.assertEqual(n['body']['content'],[{'text':'说明'}])
        self.assertEqual(self.survey('notes',id=nid,version=old,notes=[])[0],400)
        self.assertEqual(self.undo()[0],200);self.assertEqual(self.state()['nodes'][0]['body']['notes'],[])

    def test_template_files_lifecycle_and_portable_writing_type(self):
        typ=self.call('/api/writing-save',dict(name='调查音标',font='Junicode'))[1]
        root=self.node(body=dict(content=[dict(text='a',type_id=typ['id'],bold=True)],notes=[dict(text='不导出笔记')],status='done'))
        child=self.node('调查问题',root,'question');self.example(child)
        code,result=self.survey('template-file',action='save',node_id=root,name='../自定义模板')
        self.assertEqual(code,200,result);ident=result['id']
        folder=server.DB.parent/'templates'/'grammar'
        stored=json.loads((folder/(ident+'.json')).read_text(encoding='utf-8'))
        self.assertEqual(len(stored['nodes']),2);self.assertNotIn('notes',stored['nodes'][0]);self.assertNotIn('survey_evidence',stored)
        self.assertEqual(self.survey('template-file',action='rename',id=ident,name='重命名')[0],200)
        copy=self.survey('template-file',action='copy',id=ident,name='副本')[1]['id'];self.assertNotEqual(copy,ident)
        lid=self.call('/api/save-language',dict(name='模板目标语言',metadata={}))[1]['id']
        code,result=self.survey('template-file',action='import',id=copy,_language=lid);self.assertEqual(code,200,result)
        nodes=self.state(lid)['nodes'];self.assertEqual(len(nodes),2)
        self.assertEqual(nodes[0]['body']['status'],'unasked');self.assertEqual(nodes[0]['body']['notes'],[])
        self.assertNotEqual(nodes[0]['body']['content'][0]['type_id'],typ['id'])
        self.assertTrue(all(n['evidence_count']==0 for n in nodes))
        self.assertEqual(self.survey('template-file',action='delete',id=ident,confirmed=True)[0],200)
        self.assertFalse((folder/(ident+'.json')).exists());self.assertTrue((folder/'deleted'/(ident+'.json')).exists())
        self.assertEqual(self.survey('template-file',action='rename',id='../bad',name='x')[0],400)

    def test_hierarchy_scope_cycle_and_stale_version(self):
        a=self.node();old=self.state()['version'];b=self.node(parent=a)
        self.assertEqual(self.survey('save',id=a,parent_id=b,title='循环',kind='section')[0],400)
        self.assertEqual(self.survey('save',title='旧窗口',version=old)[0],400)
        q=self.node('问题',a,'question');self.assertEqual(self.survey('save',title='不允许',parent_id=q)[0],400)
        other=self.call('/api/save-language',dict(name='other',metadata={}))[1]['id']
        self.assertEqual(self.survey('save',id=a,title='跨语言',_language=other)[0],400)
        self.assertEqual(self.survey('order',id=b,direction='down')[0],200)

    def test_live_reference_copy_delete_keeps_sentence_and_undo(self):
        nid=self.node();rid=self.example(nid);original=self.evidence(nid)[0]
        code,r=self.survey('copy',id=nid,include_evidence=True);self.assertEqual(code,200,r)
        self.assertEqual(self.evidence(r['id'])[0]['record_id'],rid)
        self.assertEqual(self.call('/api/example-library?source=independent')[1]['total'],1)
        self.assertEqual(self.survey('delete',id=nid,confirmed=True)[0],200)
        self.assertEqual(self.call('/api/independent-example?id='+rid)[0],200)
        self.assertEqual(self.undo()[0],200);self.assertEqual(self.evidence(nid)[0]['id'],original['id'])
        ex=self.call('/api/independent-example?id='+rid)[1]
        self.assertEqual(self.call('/api/example-delete',dict(id=rid,revision=ex['revision'],confirmed=True))[0],200)
        self.assertIsNone(self.evidence(nid)[0]['record'])
        self.assertEqual(self.undo()[0],200);self.assertIsNotNone(self.evidence(nid)[0]['record'])

    def test_new_example_atomic_failure_and_global_search(self):
        nid=self.node()
        code,r=self.survey('new-example',node_id=nid,example=dict(ipa='bad'),body=dict(judges=['missing']))
        self.assertEqual(code,400,r);self.assertEqual(self.call('/api/example-library?source=independent')[1]['total'],0)
        rid=self.example(nid)
        self.assertEqual(self.call('/api/example-library?q=a&source=independent')[1]['items'][0]['id'],rid)
        code,r=self.call('/api/grammar-audit?language=ordos');self.assertNotEqual(code,500,r)
        self.assertIn(rid,[s['id'] for s in self.call('/api/home')[1]['samples']])

    def test_judgment_and_writing_type_guards(self):
        pid=self.call('/api/timeline-speaker-save',dict(name='判断者'))[1]['id']
        typ=self.call('/api/writing-save',dict(name='IPA',font='Junicode'))[1]
        nid=self.node(body={'content':[dict(text='aː',type_id=typ['id'],bold=True)]});self.example(nid);e=self.evidence(nid)[0]
        self.assertEqual(self.survey('evidence',node_id=nid,evidence_id=e['id'],kind=e['kind'],record_id=e['record_id'],body=dict(judges=[pid],judgment='自然',notes=[dict(text='仅此处',highlight=True)]))[0],200)
        self.assertEqual(self.call('/api/writing-delete',dict(id=typ['id'],revision=typ['revision'],confirmed=True))[0],400)
        p=next(p for p in self.call('/api/collaborators')[1]['speakers'] if p['id']==pid)
        self.assertEqual(self.call('/api/timeline-speaker-delete',dict(record_id=pid,revision=p['revision'],confirmed=True))[0],400)
        replacement=self.call('/api/writing-save',dict(name='IPA2',font='Junicode'))[1]
        self.assertEqual(self.call('/api/writing-delete',dict(id=typ['id'],revision=typ['revision'],confirmed=True,replacement_id=replacement['id']))[0],200)
        self.assertEqual(self.state()['nodes'][0]['body']['content'][0]['type_id'],replacement['id'])
        self.assertEqual(self.undo()[0],200)

    def test_independent_alignment_audio_and_speaker(self):
        nid=self.node();rid=self.example(nid);key='independent:'+rid
        pending=self.call('/api/timeline-pending?id='+self.sid+'&language=ordos&text_id=@independent')[1]
        self.assertEqual(pending['items'][0]['id'],key)
        pid=self.call('/api/timeline-speaker-save',dict(name='甲'))[1]['id'];track=self.detail()['tracks'][0]['id']
        self.assertEqual(self.mutation('track',track_id=track,name='句子',speaker_id=pid)[0],200)
        self.assertEqual(self.mutation('interval',track_id=track,entry_id=key,start_ms=100,end_ms=1000)[0],200)
        interval=self.detail()['intervals'][0];self.assertFalse(interval['missing_entry']);self.assertEqual(interval['text'],'aː')
        clips=self.call('/api/timeline-clips?ids='+key)[1];self.assertEqual(len(clips[key]),1)
        links=self.call('/api/collaborator-links?kind=independent&ids='+rid)[1][rid];self.assertEqual(links['effective'][0]['person_id'],pid)
        with server.connect(audit=False) as db:self.assertEqual(server.people_queries.Context(db).attribution('independent',rid)['ids'],[pid])

    def test_backup_restore_and_language_exchange_remaps_every_reference(self):
        typ=self.call('/api/writing-save',dict(name='音标',font='Junicode'))[1]
        pid=self.call('/api/timeline-speaker-save',dict(name='判断者'))[1]['id']
        nid=self.node(body=dict(content=[dict(text='a',type_id=typ['id'])]));rid=self.example(nid);e=self.evidence(nid)[0]
        self.survey('evidence',node_id=nid,evidence_id=e['id'],kind='independent',record_id=rid,body=dict(judges=[pid]))
        self.mutation('interval',track_id=self.detail()['tracks'][0]['id'],entry_id='independent:'+rid,start_ms=0,end_ms=500)
        bundle=self.call('/api/export-language?language=ordos')[1]
        lid=self.call('/api/save-language',dict(name='导入语言',metadata={}))[1]['id']
        code,r=self.call('/api/import-language',dict(bundle=bundle,_language=lid));self.assertEqual(code,200,r)
        copied=self.state(lid)['nodes'][0];self.assertNotEqual(copied['id'],nid)
        detail=self.call('/api/survey-detail?language='+lid+'&id='+copied['id'])[1]['items'][0]
        self.assertNotEqual(detail['record_id'],rid);self.assertNotEqual(detail['body']['judges'],[pid])
        self.assertNotEqual(copied['body']['content'][0]['type_id'],typ['id'])
        with server.connect(audit=False) as db:
            key=db.execute('SELECT i.entry_id FROM timeline_intervals i JOIN timeline_sessions s ON s.id=i.session_id WHERE s.language_id=?',(lid,)).fetchone()[0]
            self.assertEqual(key,'independent:'+detail['record_id'])
        backup=Path(self.temp.name)/'backup.json';backup.write_text(json.dumps(self.call('/api/backup')[1]),encoding='utf-8');dest=Path(self.temp.name)/'restored.sqlite3';restore(backup,dest)
        with closing(sqlite3.connect(dest)) as db:self.assertEqual(db.execute('SELECT COUNT(*) FROM survey_nodes').fetchone()[0],2)

if __name__=='__main__':unittest.main()
