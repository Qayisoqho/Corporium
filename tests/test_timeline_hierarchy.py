import json
import unittest
import server
import timeline
import test_timeline as base

class TimelineHierarchyTests(unittest.TestCase):
    setUp=base.TimelineTests.setUp
    tearDown=base.TimelineTests.tearDown
    call=base.TimelineTests.call
    detail=base.TimelineTests.detail
    mutation=base.TimelineTests.mutation
    add=base.TimelineTests.add
    undo=base.TimelineTests.undo

    def tree(self):
        parent=self.add(100,1800)
        speaker=self.call('/api/timeline-speaker-save',{'name':'调查者甲','metadata':{'number':'P01','custom':{'地区':'测试'}}})[1]['id']
        root=self.detail()['tracks'][0]
        self.assertEqual(self.mutation('track',track_id=root['id'],name='句子',speaker_id=speaker)[0],200)
        self.assertEqual(self.mutation('track',name='语言片段',kind='language',parent_id=root['id'])[0],200)
        child=next(t for t in self.detail()['tracks'] if t['parent_id'])
        code=self.call('/api/timeline-code-save',{'name':'汉语','metadata':{'number':'ZH'}})[1]['id']
        status,result=self.mutation('interval',track_id=child['id'],parent_id=parent['id'],start_ms=300,end_ms=700,code_id=code)
        self.assertEqual(status,200,result)
        interval=next(i for i in self.detail()['intervals'] if i['parent_id'])
        return parent,root,child,interval,speaker,code

    def test_move_parent_moves_children_and_one_undo_restores_both(self):
        parent,root,child,interval,*_=self.tree()
        self.assertEqual(self.mutation('interval',interval_id=parent['id'],track_id=root['id'],entry_id=parent['entry_id'],start_ms=1100,end_ms=2800)[0],200)
        shifted=next(i for i in self.detail()['intervals'] if i['id']==interval['id'])
        self.assertEqual((shifted['start_ms'],shifted['end_ms']),(1300,1700))
        self.assertEqual(self.undo()[0],200)
        self.assertEqual(next(i for i in self.detail()['intervals'] if i['id']==interval['id'])['start_ms'],300)

    def test_resize_crossing_split_and_invalid_child_leave_data_unchanged(self):
        parent,root,child,interval,*_=self.tree();before=self.detail()['intervals']
        self.assertEqual(self.mutation('interval',interval_id=parent['id'],track_id=root['id'],entry_id=parent['entry_id'],start_ms=100,end_ms=600)[0],400)
        self.assertEqual(self.mutation('split',interval_id=parent['id'],at_ms=500)[0],400)
        self.assertEqual(self.mutation('interval',track_id=child['id'],parent_id=parent['id'],start_ms=1600,end_ms=1900)[0],400)
        self.assertEqual(before,self.detail()['intervals'])

    def test_split_assigns_children_and_merge_preserves_them(self):
        parent,root,child,interval,*_=self.tree()
        self.assertEqual(self.mutation('split',interval_id=parent['id'],at_ms=200)[0],200)
        right=next(i for i in self.detail()['intervals'] if i['track_id']==root['id'] and i['start_ms']==200)
        self.assertEqual(next(i for i in self.detail()['intervals'] if i['id']==interval['id'])['parent_id'],right['id'])
        self.assertEqual(self.mutation('merge',interval_id=parent['id'],other_id=right['id'])[0],200)
        self.assertEqual(next(i for i in self.detail()['intervals'] if i['id']==interval['id'])['parent_id'],parent['id'])

    def test_delete_parent_needs_explicit_cascade_and_undo_restores(self):
        parent,*_=self.tree()
        self.assertEqual(self.mutation('delete-interval',interval_id=parent['id'],confirmed=True)[0],400)
        self.assertEqual(self.mutation('delete-interval',interval_id=parent['id'],confirmed=True,include_children=True)[0],200)
        self.assertEqual(self.detail()['intervals'],[])
        self.assertEqual(self.undo()[0],200);self.assertEqual(len(self.detail()['intervals']),2)

    def test_tree_cycles_invalid_parent_and_referenced_speaker_delete_are_blocked(self):
        parent,root,child,interval,speaker,code=self.tree()
        self.assertEqual(self.mutation('track',track_id=root['id'],name='cycle',kind='event',parent_id=child['id'])[0],400)
        self.assertEqual(self.mutation('track',name='wrong',kind='language')[0],400)
        self.assertEqual(self.mutation('delete-track',track_id=root['id'],confirmed=True)[0],400)
        person=next(p for p in self.detail()['speakers'] if p['id']==speaker)
        self.assertEqual(self.call('/api/timeline-speaker-delete',{'record_id':speaker,'revision':person['revision'],'confirmed':True})[0],400)
        self.assertIsNone(child['speaker_id'])

    def test_duplicate_and_language_exchange_remap_parents_keep_shared_identity(self):
        parent,root,child,interval,speaker,code=self.tree()
        status,result=self.mutation('duplicate');self.assertEqual(status,200);self.sid=result['id']
        d=self.detail();newparent=next(i for i in d['intervals'] if i['entry_id'])
        self.assertNotEqual(newparent['id'],parent['id']);self.assertEqual(next(i for i in d['intervals'] if i['code_id'])['parent_id'],newparent['id'])
        self.assertEqual(next(t for t in d['tracks'] if not t['parent_id'])['speaker_id'],speaker)
        with server.connect(audit=False) as db:
            bundle=timeline.export_bundle(db,'ordos');timeline.import_bundle(db,bundle,'ordos',{e:e for e in self.eids});timeline.hierarchy.validate(db)
            self.assertEqual(db.execute('SELECT COUNT(*) FROM timeline_speakers').fetchone()[0],2)

    def test_catalog_revision_and_rename_are_shared(self):
        _,_,_,_,speaker,code=self.tree();person=next(p for p in self.detail()['speakers'] if p['id']==speaker)
        args={'record_id':speaker,'revision':person['revision'],'name':'匿名甲','metadata':json.loads(person['metadata'])}
        self.assertEqual(self.call('/api/timeline-speaker-save',args)[0],200)
        self.assertEqual(self.call('/api/timeline-speaker-save',args)[0],400)
        self.assertEqual(self.call('/api/timeline-catalog?language=all')[1]['speakers'][0]['name'],'匿名甲')

    def test_child_same_track_collision_and_different_tracks(self):
        parent,root,child,interval,speaker,code=self.tree()
        self.assertEqual(self.mutation('interval',track_id=child['id'],start_ms=600,end_ms=800,code_id=code)[0],400)
        self.assertEqual(self.mutation('track',name='动作',kind='event',parent_id=root['id'])[0],200)
        event=next(t for t in self.detail()['tracks'] if t['kind']=='event')
        self.assertEqual(self.mutation('interval',track_id=event['id'],start_ms=600,end_ms=800,label='点头')[0],200)

    def test_nested_children_move_and_out_of_bounds_undo_is_blocked(self):
        parent,root,child,interval,*_=self.tree()
        self.assertEqual(self.mutation('track',name='动作',kind='event',parent_id=root['id'])[0],200)
        event=next(t for t in self.detail()['tracks'] if t['kind']=='event')
        self.assertEqual(self.mutation('interval',track_id=event['id'],start_ms=800,end_ms=1600,label='动作')[0],200)
        self.assertEqual(self.mutation('track',name='动作阶段',kind='event',parent_id=event['id'])[0],200)
        sub=next(t for t in self.detail()['tracks'] if t['parent_id']==event['id'])
        self.assertEqual(self.mutation('interval',track_id=sub['id'],start_ms=1000,end_ms=1400,label='保持')[0],200)
        self.assertEqual(self.mutation('interval',interval_id=parent['id'],track_id=root['id'],entry_id=parent['entry_id'],start_ms=2100,end_ms=3800)[0],200)
        self.assertEqual(next(i for i in self.detail()['intervals'] if i['track_id']==sub['id'])['start_ms'],3000)

    def test_backup_restore_keeps_hierarchy_and_global_records(self):
        from pathlib import Path
        from restore_backup import restore
        import sqlite3
        from contextlib import closing
        self.tree();backup=self.call('/api/backup')[1]
        path=Path(self.temp.name)/'hierarchy.json';path.write_text(json.dumps(backup),encoding='utf-8')
        target=Path(self.temp.name)/'restored.sqlite3';restore(path,target)
        with closing(sqlite3.connect(target)) as db:
            db.row_factory=sqlite3.Row;timeline.hierarchy.validate(db)
            self.assertEqual(db.execute('SELECT COUNT(*) FROM timeline_intervals WHERE parent_id IS NOT NULL').fetchone()[0],1)
            self.assertEqual(db.execute('SELECT COUNT(*) FROM timeline_speakers').fetchone()[0],1)

    def test_global_record_undo_does_not_overwrite_later_edits(self):
        person=self.call('/api/timeline-speaker-save',{'name':'甲'})[1]['id']
        with server.connect(audit=False) as db:db.execute('UPDATE timeline_speakers SET name=?,revision=revision+1 WHERE id=?',('其他语言中的更正',person))
        self.assertEqual(self.undo()[0],400)
        self.assertEqual(self.call('/api/timeline-catalog')[1]['speakers'][0]['name'],'其他语言中的更正')

    def test_global_record_undo_cannot_remove_a_new_reference(self):
        person=self.call('/api/timeline-speaker-save',{'name':'甲'})[1]['id']
        with server.connect(audit=False) as db:db.execute('UPDATE timeline_tracks SET speaker_id=? WHERE session_id=?',(person,self.sid))
        self.assertEqual(self.undo()[0],400)
        self.assertEqual(len(self.call('/api/timeline-catalog')[1]['speakers']),1)

    def test_event_cycle_cross_session_parent_and_invalid_exchange_are_rejected(self):
        self.assertEqual(self.mutation('track',name='动作',kind='event')[0],200)
        root=next(t for t in self.detail()['tracks'] if t['kind']=='event')
        self.assertEqual(self.mutation('track',name='阶段',kind='event',parent_id=root['id'])[0],200)
        child=next(t for t in self.detail()['tracks'] if t['parent_id'])
        self.assertEqual(self.mutation('track',track_id=root['id'],name='循环',kind='event',parent_id=child['id'])[0],400)
        other=self.call('/api/timeline-create',{})[1]['id']
        with server.connect(audit=False) as db:
            foreign=db.execute('SELECT id FROM timeline_tracks WHERE session_id=?',(other,)).fetchone()[0]
        self.assertEqual(self.mutation('track',name='跨会话',kind='event',parent_id=foreign)[0],400)
        with self.assertRaises(ValueError),server.connect(audit=False) as db:
            bundle=timeline.export_bundle(db,'ordos');bundle['timeline_tracks'][0]['parent_id']='missing';timeline.import_bundle(db,bundle,'ordos',{})

    def test_language_rename_does_not_break_merging_same_code(self):
        parent,root,child,interval,speaker,code=self.tree()
        record=next(c for c in self.detail()['codes'] if c['id']==code)
        self.assertEqual(self.call('/api/timeline-code-save',{'record_id':code,'revision':record['revision'],'name':'汉语（修订）'})[0],200)
        self.assertEqual(self.mutation('interval',track_id=child['id'],start_ms=700,end_ms=900,code_id=code)[0],200)
        other=next(i for i in self.detail()['intervals'] if i['track_id']==child['id'] and i['start_ms']==700)
        self.assertEqual(self.mutation('merge',interval_id=interval['id'],other_id=other['id'])[0],200)
        self.assertEqual(next(i for i in self.detail()['intervals'] if i['code_id'])['text'],'汉语（修订）')
