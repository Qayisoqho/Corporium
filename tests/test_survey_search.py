import json
import unittest
import uuid
from urllib.parse import urlencode
import server
import survey_search
import test_grammar_survey


class SurveySearchTests(unittest.TestCase):
    for _name in ('setUp','tearDown','call','state','survey','node','example','evidence'):
        locals()[_name]=getattr(test_grammar_survey.SurveyTests,_name)

    def search(self,q,scope='all',**extra):
        code,result=self.call('/api/survey-search?'+urlencode(dict(q=q,scope=scope,language='ordos',**extra)))
        self.assertEqual(code,200,result);return result

    def locate(self,item,field,q='否定',**extra):
        code,result=self.call('/api/survey-locate?'+urlencode(dict(node_id=item['node_id'],evidence_id=item.get('evidence_id') or '',field=field,q=q,scope='all',language='ordos',**extra)))
        self.assertEqual(code,200,result);return result

    def test_rich_runs_fields_grouping_paths_and_literal_unicode_queries(self):
        root=self.node('动词短语');child=self.node('否定祈使句',root,'question',dict(content=[dict(text='调查否',bold=True),dict(text='定：自然吗？',italic=True)],notes=[dict(text='需补问否定。e\u0301 [x]')]))
        result=self.search('否定','survey')
        self.assertEqual(result['total'],1);self.assertEqual(result['nodes'],1)
        self.assertEqual(result['items'][0]['path'],['动词短语','否定祈使句'])
        self.assertEqual([f['field'] for f in result['items'][0]['fields']],['title','content','notes'])
        self.assertEqual(self.search('动词短语')['total'],1) # Parent paths are context, not inherited matches.
        self.assertEqual(self.search('É')['total'],1);self.assertEqual(self.search('[x]')['total'],1)
        self.assertEqual(self.search('否定','examples')['total'],0)
        other=self.node('新层级')
        old=next(n for n in self.state()['nodes'] if n['id']==child)
        code,_=self.survey('save',id=child,title='已改名',parent_id=other,kind='question',body=old['body']);self.assertEqual(code,200)
        target=self.locate(result['items'][0],'content');self.assertEqual(target['node_id'],child);self.assertTrue(target['matched'])
        self.assertEqual(self.search('否定')['items'][0]['path'],['新层级','已改名'])
        self.assertIn('命中',survey_search.excerpt('e\u0301'*1000+'命中'+'x'*100,'命中'))
        self.assertIn('命中',survey_search.excerpt('İ'*1000+'命中'+'x'*100,'命中'))

    def test_scope_shared_references_and_unreferenced_sentences(self):
        a=self.node('问题甲');b=self.node('问题乙');rid=self.example(a);e=self.evidence(a)[0]
        self.survey('evidence',node_id=a,evidence_id=e['id'],kind='independent',record_id=rid,body=dict(notes=[dict(text='否定本处笔记')],context=[dict(text='否定调查提示')],judgment='否定可用'))
        self.survey('evidence',node_id=b,kind='independent',record_id=rid,body={})
        status,row=self.call('/api/independent-example?id='+rid);self.assertEqual(status,200)
        row['body']['translation']='否定回答';self.call('/api/example-save',dict(id=rid,revision=row['revision'],body=row['body']))
        self.call('/api/example-save',dict(body=dict(translation='否定但未引用',words=[])))
        found=self.search('否定');self.assertEqual(found['total'],2);self.assertEqual(found['nodes'],2)
        self.assertEqual(self.search('否定','survey')['total'],1)
        self.assertEqual(self.search('否定','examples')['total'],2)
        fields={f['field'] for f in found['items'][0]['fields']}
        self.assertTrue({'judgment','context','local_notes','translation'}<=fields)
        self.assertTrue(self.locate(found['items'][0],'local_notes')['matched'])
        self.call('/api/example-delete',dict(id=rid,revision=self.call('/api/independent-example?id='+rid)[1]['revision'],confirmed=True))
        self.assertEqual(self.search('否定','examples')['total'],0)
        self.assertEqual(self.search('否定','survey')['total'],1)

    def test_current_evidence_page_is_resolved_after_deletions_and_stale_text(self):
        nid=self.node();rid=self.example(nid);first=self.evidence(nid)[0]
        ids=[first['id']]+[str(uuid.uuid4()) for _ in range(25)]
        with server.connect() as db:
            db.executemany('INSERT INTO survey_evidence VALUES(?,?,?,?,?,?,?,1)',[(eid,'ordos',nid,'independent',rid,i,json.dumps(dict(notes=[dict(text='否定'+str(i))],context=[]))) for i,eid in enumerate(ids[1:],1)])
        result=self.search('否定');self.assertEqual(result['total'],25);self.assertEqual(result['pages'],2)
        last=self.search('否定',page=2)['items'][-1]
        self.assertEqual(self.locate(last,'local_notes')['page'],2)
        with server.connect() as db:
            db.executemany('DELETE FROM survey_evidence WHERE id=?',[(eid,) for eid in ids[:10]])
        self.assertEqual(self.locate(last,'local_notes')['page'],1)
        with server.connect() as db:db.execute('UPDATE survey_evidence SET body=? WHERE id=?',(json.dumps(dict(notes=[dict(text='内容已更新')])),last['evidence_id']))
        self.assertFalse(self.locate(last,'local_notes')['matched'])

    def test_language_isolation_empty_and_invalid_requests_leave_history_untouched(self):
        self.node('否定');before=self.call('/api/undo-state')[1]['generation']
        other=self.call('/api/save-language',dict(name='Other',metadata={}))[1]['id']
        self.assertEqual(self.call('/api/survey-search?'+urlencode(dict(q='否定',language=other)))[1]['total'],0)
        before=self.call('/api/undo-state')[1]['generation']
        self.assertEqual(self.search('')['total'],0);self.assertEqual(self.search('absent')['total'],0)
        for query in (dict(q='否定',language='all'),dict(q='x',language='ordos',scope='bad'),dict(q='x'*201,language='ordos')):
            self.assertEqual(self.call('/api/survey-search?'+urlencode(query))[0],400)
        self.assertEqual(self.call('/api/undo-state')[1]['generation'],before)
        item=self.search('否定')['items'][0]
        self.assertEqual(self.call('/api/survey-locate?'+urlencode(dict(node_id=item['node_id'],field='title',q='否定',language=other)))[0],400)

    def test_corpus_fields_scripts_and_batched_independent_sources(self):
        nid=self.node();code,text=self.call('/api/import',dict(title='调查引用',content='#pass([ana], (([ana],[neg#sub[POT]]),), [否定回答])'));self.assertEqual(code,200)
        entry=self.call('/api/entries?text='+text['id'])[1]['items'][0]
        self.survey('evidence',node_id=nid,kind='corpus',record_id=entry['id'],body={})
        self.assertEqual(self.search('negPOT','examples')['items'][0]['fields'][0]['field'],'gloss')
        self.assertEqual(self.search('否定','examples')['total'],1)
        with server.connect() as db:
            for i in range(405):
                rid=str(uuid.uuid4());eid=str(uuid.uuid4())
                db.execute('INSERT INTO dictionary_examples VALUES(?,?,?,1)',(rid,'ordos',json.dumps(dict(ipa='测试'+str(i),translation='批次命中',words=[]))))
                db.execute('INSERT INTO survey_evidence VALUES(?,?,?,?,?,?,?,1)',(eid,'ordos',nid,'independent',rid,i+1,'{}'))
        self.assertEqual(self.search('批次命中','examples')['total'],405)


if __name__=='__main__':unittest.main()
