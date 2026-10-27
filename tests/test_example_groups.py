import json
import unittest
from pathlib import Path
import test_server
import server
import example_groups
import grammar_survey
import languages
from restore_backup import restore


class ExampleGroupTests(unittest.TestCase):
    setUp=test_server.APITests.setUp
    tearDown=test_server.APITests.tearDown
    call=test_server.APITests.call
    def example(self, text='来', symbol=''):
        code, result=self.call('/api/example-save',dict(body=dict(ipa=text,translation=text,words=[dict(form=text,gloss='来')],grammaticality=symbol)))
        self.assertEqual(code,200,result);return result['id']

    def create(self, ids=None):
        ids=ids or [self.example('a'),self.example('b')]
        code,result=self.call('/api/example-group-save',dict(body=dict(name='问答',context='共同语境',numbering='letters'),members=[dict(example_id=e,role='Q' if i==0 else 'A') for i,e in enumerate(ids)]))
        self.assertEqual(code,200,result);return result

    def group(self,gid):
        code,result=self.call('/api/example-group?language=ordos&id='+gid);self.assertEqual(code,200,result);return result

    def save(self,g,members):
        return self.call('/api/example-group-save',dict(id=g['id'],token=g['token'],body=g['body'],members=members))

    def node(self):
        state=self.call('/api/survey?language=ordos')[1]
        code,result=self.call('/api/survey-save',dict(title='调查',body={},version=state['version']))
        self.assertEqual(code,200,result);return result['id']

    def cite(self,nid,g):
        state=self.call('/api/survey?language=ordos')[1]
        return self.call('/api/survey-evidence-groups',dict(node_id=nid,groups=[dict(id=g['id'],token=g['token'])],version=state['version']))

    def undo(self,redo=False):
        generation=self.call('/api/undo-state')[1]['generation']
        code,result=self.call('/api/'+('redo' if redo else 'undo'),dict(generation=generation));self.assertEqual(code,200,result)

    def test_groups_keep_sentences_and_source_ids_and_undo(self):
        ids=[self.example('one'),self.example('two')]
        before=[self.call('/api/independent-example?id='+x)[1] for x in ids]
        g=self.create(ids);self.assertEqual([m['example_id'] for m in g['members']],ids)
        self.assertEqual([self.call('/api/independent-example?id='+x)[1] for x in ids],before)
        self.undo();self.assertEqual(self.call('/api/example-group?id='+g['id'])[0],400)
        self.undo(True);self.assertEqual(len(self.group(g['id'])['members']),2)

    def test_reorder_roles_and_retired_member_identity(self):
        g=self.create();members=g['members'];self.assertEqual(self.save(g,list(reversed(members)))[0],200)
        new=self.group(g['id']);self.assertEqual([m['role'] for m in new['members']],['A','Q'])
        self.assertEqual([m['label'] for m in new['members']],['a.','b.'])
        self.assertEqual(self.save(new,[new['members'][0]])[0],200)
        old_id=members[0]['id'];one=self.group(g['id']);self.assertEqual(len(one['retired']),1)
        self.assertEqual(self.save(one,[dict(example_id=m['example_id'],role=m['role']) for m in members])[0],200)
        self.assertEqual(self.group(g['id'])['members'][0]['id'],old_id)

    def test_stale_cross_language_text_and_duplicates_rejected_atomically(self):
        g=self.create();self.assertEqual(self.save(g,g['members'])[0],200)
        self.assertEqual(self.save(g,list(reversed(g['members'])))[0],400)
        fresh=self.group(g['id']);self.assertEqual(self.save(fresh,[fresh['members'][0]]*2)[0],400)
        code,text=self.call('/api/import',dict(title='text',content='#pass([x], (([x],[来]),), [x])'));self.assertEqual(code,200,text)
        eid=self.call('/api/entries?text_id='+text['id'])[1]['items'][0]['id']
        self.assertEqual(self.save(fresh,[fresh['members'][0],dict(example_id=eid)])[0],400)
        foreign=self.example('foreign')
        with server.connect() as db:
            db.execute("INSERT INTO languages VALUES('foreign','foreign','{}',1)")
            db.execute('UPDATE dictionary_examples SET language_id=? WHERE id=?',('foreign',foreign))
        self.assertEqual(self.save(fresh,[fresh['members'][0],dict(example_id=foreign)])[0],400)

    def test_cite_live_group_and_block_dissolve(self):
        g=self.create();nid=self.node();self.assertEqual(self.cite(nid,g)[0],200)
        current=self.group(g['id']);self.assertEqual(current['references'],1)
        self.assertEqual(self.call('/api/example-group-delete',dict(id=g['id'],token=current['token'],confirmed=True))[0],400)
        self.assertEqual(self.save(current,list(reversed(current['members'])))[0],200)
        evidence=self.call('/api/survey-detail?language=ordos&id='+nid)[1]['items'][0]
        self.assertEqual(evidence['kind'],example_groups.KIND)
        self.assertEqual(evidence['record']['body']['members'][0]['role'],'A')
        self.assertEqual(self.cite(nid,self.group(g['id']))[0],400)

    def test_local_notes_follow_member_removal_reorder_and_exchange(self):
        g=self.create();nid=self.node();self.assertEqual(self.cite(nid,g)[0],200)
        e=self.call('/api/survey-detail?language=ordos&id='+nid)[1]['items'][0];mid=g['members'][0]['id']
        body=dict(e['body'],member_notes={mid:dict(notes=[dict(text='保留的成员笔记')],judgment='本处判断',example_id=g['members'][0]['example_id'],source_label='a')})
        state=self.call('/api/survey?language=ordos')[1]
        code,r=self.call('/api/survey-evidence',dict(node_id=nid,evidence_id=e['id'],kind=e['kind'],record_id=e['record_id'],body=body,version=state['version']));self.assertEqual(code,200,r)
        current=self.group(g['id']);self.assertEqual(self.save(current,[current['members'][1]])[0],200)
        with server.connect() as db:
            import language_exchange
            bundle=language_exchange.export_bundle(db,'ordos')
            db.execute("INSERT INTO languages VALUES('copy','copy','{}',1)")
            result=languages.import_bundle(db,bundle,'copy')
            copied=db.execute("SELECT * FROM survey_evidence WHERE language_id='copy'").fetchone()
            self.assertIsNotNone(copied)
            notes=json.loads(copied['body'])['member_notes'];self.assertNotIn(mid,notes)
            self.assertEqual(next(iter(notes.values()))['notes'][0]['text'],'保留的成员笔记')
            group=example_groups.detail(db,'copy',copied['record_id']);self.assertEqual(len(group['members']),1)
            self.assertIn(next(iter(notes)),[m['id'] for m in group['retired']])

    def test_search_group_context_keeps_matching_counts_and_sentence_statistics(self):
        g=self.create();self.example('extra')
        result=self.call('/api/example-groups-library')[1];self.assertEqual(result['sentence_total'],3);self.assertEqual(result['total'],2)
        self.assertEqual(result['items'][0]['matched_ids'],[])
        self.assertEqual(self.call('/api/example-groups-library?group_filter=groups')[1]['sentence_total'],2)
        found=self.call('/api/example-groups-library?q=a&field=ipa')[1]
        self.assertEqual(found['sentence_total'],2);self.assertEqual(len(found['items'][0]['group']['members']),2)
        named=self.call('/api/example-groups-library?q=共同语境')[1];self.assertEqual(named['group_total'],1)
        nid=self.node();self.assertEqual(self.cite(nid,g)[0],200)
        search=self.call('/api/survey-search?language=ordos&q=共同语境&scope=examples')[1];self.assertEqual(search['total'],1)

    def test_backup_restore_groups_and_history(self):
        g=self.create();nid=self.node();self.assertEqual(self.cite(nid,g)[0],200)
        backup=self.call('/api/backup')[1];path=Path(self.temp.name)/'groups.json';path.write_text(json.dumps(backup),encoding='utf-8')
        target=Path(self.temp.name)/'restored.sqlite3';restore(path,target);server.DB=target
        self.assertEqual(self.group(g['id'])['references'],1);self.undo()
        self.assertEqual(self.group(g['id'])['references'],0)

    def test_deleted_source_is_missing_and_undo_restores(self):
        g=self.create();source=g['members'][0]['example_id'];record=self.call('/api/independent-example?id='+source)[1]
        self.assertEqual(self.call('/api/example-delete',dict(id=source,revision=record['revision'],confirmed=True))[0],200)
        self.assertIsNone(self.group(g['id'])['members'][0]['record']);self.undo()
        self.assertIsNotNone(self.group(g['id'])['members'][0]['record'])

    def test_labels(self):
        self.assertEqual([example_groups.label('letters',n) for n in (0,25,26,27)],['a.','z.','aa.','ab.'])
        self.assertEqual(example_groups.label('none',0),'');self.assertEqual(example_groups.label('numbers',0),'1.')

    def test_batch_citation_is_atomic_when_one_group_is_stale(self):
        first=self.create();second=self.create();nid=self.node()
        self.assertEqual(self.save(second,second['members'])[0],200)
        state=self.call('/api/survey?language=ordos')[1]
        code,r=self.call('/api/survey-evidence-groups',dict(node_id=nid,version=state['version'],groups=[dict(id=g['id'],token=g['token']) for g in (first,second)]))
        self.assertEqual(code,400,r)
        self.assertEqual(self.call('/api/survey-detail?language=ordos&id='+nid)[1]['total'],0)

    def test_empty_group_is_kept_and_cannot_be_cited_then_dissolves_with_undo(self):
        g=self.create();self.assertEqual(self.save(g,[])[0],200);empty=self.group(g['id'])
        self.assertEqual(empty['members'],[]);nid=self.node();self.assertEqual(self.cite(nid,empty)[0],400)
        self.assertEqual(self.call('/api/example-group-delete',dict(id=empty['id'],token=empty['token'],confirmed=True))[0],200)
        self.undo();self.assertEqual(self.group(g['id'])['members'],[])

    def test_new_sentence_joins_group_atomically_and_stale_token_rolls_back(self):
        g=self.create();payload=dict(kind='independent',body=dict(ipa='new',translation='新句',words=[]),slot_ids=[],cells=[],layers=[],example_group=g['id'],example_group_token=g['token'])
        code,r=self.call('/api/sentence-create',payload);self.assertEqual(code,200,r)
        current=self.group(g['id']);self.assertIn(r['id'],[m['example_id'] for m in current['members']])
        count=self.call('/api/example-library?source=independent')[1]['total']
        self.assertEqual(self.call('/api/sentence-create',payload)[0],400)
        self.assertEqual(self.call('/api/example-library?source=independent')[1]['total'],count)
        self.undo();self.assertEqual(len(self.group(g['id'])['members']),2)
        self.assertEqual(self.call('/api/independent-example?id='+r['id'])[0],400)

    def test_group_name_matching_modes_and_overlapping_groups_do_not_duplicate_counts(self):
        g=self.create();self.create([m['example_id'] for m in g['members']])
        all_groups=self.call('/api/example-groups-library')[1]
        self.assertEqual(all_groups['sentence_total'],2);self.assertEqual(all_groups['group_total'],2)
        exact=self.call('/api/example-groups-library?q=共同&mode=exact')[1];self.assertEqual(exact['total'],0)
        prefix=self.call('/api/example-groups-library?q=共同&mode=prefix')[1];self.assertEqual(prefix['group_total'],2)
        self.assertEqual(self.call('/api/example-groups-library?group_filter=ungrouped')[1]['total'],0)

    def test_nested_judges_are_protected_exported_and_remapped(self):
        import collaborators
        g=self.create();nid=self.node();self.assertEqual(self.cite(nid,g)[0],200)
        with server.connect() as db:
            import timeline_hierarchy
            catalog=timeline_hierarchy.catalog(db)
            db.execute("INSERT INTO timeline_speakers VALUES('judge','判断者','{}',1)")
        e=self.call('/api/survey-detail?language=ordos&id='+nid)[1]['items'][0];mid=g['members'][0]['id']
        state=self.call('/api/survey?language=ordos')[1]
        body=dict(e['body'],member_notes={mid:dict(judges=['judge'],notes=[dict(text='本人判断')])})
        code,r=self.call('/api/survey-evidence',dict(node_id=nid,evidence_id=e['id'],kind=e['kind'],record_id=e['record_id'],body=body,version=state['version']));self.assertEqual(code,200,r)
        with server.connect() as db:
            self.assertTrue(collaborators.referenced(db,'judge'))
            self.assertIn('judge',[p['id'] for p in collaborators.export_bundle(db,'ordos')['timeline_speakers']])

    def test_sqlite_backup_and_language_delete_keep_unrelated_groups(self):
        import project_backup
        import language_exchange
        import language_deletion
        g=self.create()
        with server.connect() as db:
            package=project_backup.prepare(db,server.DB)
            path=language_exchange.staged(server.DB,package['token'],'project-backup')
            target=Path(self.temp.name)/'sqlite-restored/corpus.sqlite3'
            project_backup.restore(path,target)
            bundle=language_exchange.export_bundle(db,'ordos')
            db.execute("INSERT INTO languages VALUES('copy','copy','{}',1)")
            languages.import_bundle(db,bundle,'copy')
        old=server.DB;server.DB=target
        try:self.assertEqual(len(self.group(g['id'])['members']),2)
        finally:server.DB=old
        with server.connect() as db:
            language=dict(db.execute("SELECT * FROM languages WHERE id='copy'").fetchone())
            preview=language_deletion.preview(db,dict(id='copy',revision=language['revision']))
        with server.connect() as db:
            db.execute('BEGIN IMMEDIATE')
            language_deletion.remove(db,server.DB,dict(id='copy',revision=language['revision'],token=preview['token'],confirmed=True))
        self.assertEqual(len(self.group(g['id'])['members']),2)

    def test_dictionary_inheritance_and_sentence_link_identity_survive_grouping(self):
        code,x=self.call('/api/lexeme-save',dict(headword='home',body=dict(usages=[dict(pos='名词',senses=[dict(short_gloss='家')])])));self.assertEqual(code,200,x)
        code,e=self.call('/api/example-save',dict(body=dict(words=[dict(form='home',gloss='手写')])));self.assertEqual(code,200,e)
        detail=self.call('/api/segmentation?kind=independent&id='+e['id'])[1]
        u=x['body']['usages'][0]
        code,r=self.call('/api/segmentation-link',dict(kind='independent',id=e['id'],revision=detail['revision'],word=0,key='@word',lexeme_id=x['id'],lexeme_revision=x['revision'],usage_id=u['id'],sense_id=u['senses'][0]['id']));self.assertEqual(code,200,r)
        before=self.call('/api/independent-example?id='+e['id'])[1]
        g=self.create([e['id'],self.example('other')])
        x=self.call('/api/lexeme?id='+x['id'])[1];x['body']['usages'][0]['senses'][0]['short_gloss']='住所'
        self.assertEqual(self.call('/api/lexeme-save',x)[0],200)
        member=self.group(g['id'])['members'][0]['record']['body'];self.assertEqual(member['words'][0]['gloss'],'住所')
        self.assertEqual(member['targets'],self.call('/api/independent-example?id='+e['id'])[1]['body']['targets'])
        self.assertEqual(before['body']['words'][0]['annotation_id'],member['words'][0]['annotation_id'])
        self.assertEqual(self.call('/api/example-groups-library?language=ordos&q=住所&field=gloss')[1]['sentence_total'],1)

    def test_source_change_invalidates_citation_preview(self):
        g=self.create();nid=self.node();record=self.call('/api/independent-example?id='+g['members'][0]['example_id'])[1]
        record['body']['translation']='另一窗口刚修改'
        self.assertEqual(self.call('/api/example-save',record)[0],200)
        self.assertEqual(self.cite(nid,g)[0],400)
        self.assertEqual(self.call('/api/survey-detail?language=ordos&id='+nid)[1]['total'],0)
        fresh=self.group(g['id']);self.assertEqual(self.cite(nid,fresh)[0],200)
        found=self.call('/api/example-groups-library?language=ordos&group_filter=groups&survey_node='+nid)[1]
        self.assertEqual(found['cited_ids'],[g['id']])

    def test_startup_adds_empty_group_tables_after_backup_without_rewriting_sentences(self):
        self.example('原句')
        with server.connect() as db:
            before=[tuple(r) for r in db.execute('SELECT * FROM dictionary_examples')]
            db.execute('DROP TABLE example_group_members');db.execute('DROP TABLE example_groups')
        server.init()
        with server.connect() as db:
            self.assertEqual(before,[tuple(r) for r in db.execute('SELECT * FROM dictionary_examples')])
            self.assertEqual(db.execute('SELECT COUNT(*) FROM example_groups').fetchone()[0],0)
        self.assertTrue(list((server.DB.parent/'backups').glob('*.sqlite3')))

    def test_group_reads_and_search_previews_do_not_write(self):
        g=self.create()
        with server.connect(audit=False) as db:
            example_groups.detail(db,'ordos',g['id'])
            example_groups.library(db,'ordos',{'q':'共同语境'})
            self.assertEqual(db.total_changes,0)
