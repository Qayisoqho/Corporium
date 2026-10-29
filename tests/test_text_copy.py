import json
import unittest
from unittest.mock import patch
import server
import test_lexicon
import test_long_task_writes


class TextCopyTests(unittest.TestCase):
    setUp=test_lexicon.LexiconTests.setUp
    tearDown=test_lexicon.LexiconTests.tearDown
    call=test_lexicon.LexiconTests.call
    seed=test_lexicon.LexiconTests.seed
    entries=test_lexicon.LexiconTests.entries
    word=test_lexicon.LexiconTests.word
    link=test_lexicon.LexiconTests.link
    undo=test_lexicon.LexiconTests.undo
    wait=test_long_task_writes.WriteTasks.wait
    submit=test_long_task_writes.WriteTasks.submit
    execute=test_long_task_writes.WriteTasks.execute

    def plan(self,tid):
        code,p=self.call('/api/text-copy-preview?id='+tid);self.assertEqual(code,200,p);return p

    def copy(self,p,**more):return self.call('/api/copy-text',dict(id=p['id'],token=p['token'],title='Independent copy',**more))

    def test_metadata_order_links_and_source_unchanged_undo_redo(self):
        e=self.seed();x=self.word();self.link(e['words'][0]['unit_id'],x)
        f=self.call('/api/save-folder',dict(name='Folder',metadata={}))[1]['id']
        self.assertEqual(self.call('/api/save-text-info',dict(id=e['text_id'],revision=0,title='Original',source='fieldwork',folder_id=f,metadata={'notes':'keep','reading_mode':'dialogue'}))[0],200)
        with server.connect() as db:
            original={t:[dict(r) for r in db.execute('SELECT * FROM '+t)] for t in ('texts','entries','corpus_units','lexical_links','gloss_bindings','text_info')}
        p=self.plan(e['text_id']);code,result=self.copy(p);self.assertEqual(code,200,result)
        with server.connect() as db:
            for table,rows in original.items():
                for row in rows:
                    key='text_id' if table=='text_info' else 'id'
                    self.assertEqual(dict(db.execute('SELECT * FROM '+table+' WHERE '+key+'=?',(row[key],)).fetchone()),row,table)
            cloned=list(db.execute('SELECT * FROM entries WHERE text_id=? ORDER BY position',(result['id'],)));self.assertEqual([r['position'] for r in cloned],[1])
            uid=db.execute('SELECT unit_id FROM lexical_links WHERE unit_id IN (SELECT id FROM corpus_units WHERE entry_id=?)',(cloned[0]['id'],)).fetchone()[0]
            self.assertNotEqual(uid,e['words'][0]['unit_id'])
            info=db.execute('SELECT * FROM text_info WHERE text_id=?',(result['id'],)).fetchone();self.assertEqual(info['folder_id'],f);self.assertEqual(json.loads(info['metadata'])['notes'],'keep')
            self.assertIsNone(db.execute('SELECT digest FROM texts WHERE id=?',(result['id'],)).fetchone()[0])
        self.assertEqual(self.undo()[0],200)
        self.assertNotIn(result['id'],[r['id'] for r in self.call('/api/texts')[1]])
        self.assertEqual(self.undo('redo')[0],200)
        self.assertIn(result['id'],[r['id'] for r in self.call('/api/texts')[1]])

    def test_stale_repeated_and_cross_language_requests_are_atomic(self):
        e=self.seed();p=self.plan(e['text_id']);self.word()
        self.assertEqual(self.copy(p)[0],400)
        p=self.plan(e['text_id']);self.assertEqual(self.copy(p,_language='missing')[0],400)
        self.assertEqual(len(self.call('/api/texts')[1]),1)
        code,r=self.copy(p);self.assertEqual(code,200,r);self.assertEqual(self.copy(p)[0],400)
        self.assertEqual(len(self.call('/api/texts')[1]),2)

    def test_empty_text_and_invalid_title(self):
        tid=self.call('/api/new-text',dict(title='Empty',empty=True))[1]['id'];p=self.plan(tid)
        self.assertEqual(self.call('/api/copy-text',dict(id=tid,token=p['token'],title=' '))[0],400)
        code,r=self.copy(p);self.assertEqual(code,200,r);self.assertEqual(r['count'],0)

    def test_manual_and_inherited_collaborators_keep_modes(self):
        e=self.seed()
        with server.connect() as db:
            db.execute("INSERT INTO timeline_speakers VALUES('person','Speaker','{}',1)")
            for kind,rid,mode in [('text',e['text_id'],'manual'),('corpus',e['id'],'auto')]:
                db.execute('INSERT INTO collaborator_assignments VALUES(?,?,?,?,?,1)',(kind,kind,rid,json.dumps([dict(person_id='person',role='发言人')]),mode))
        code,r=self.copy(self.plan(e['text_id']));self.assertEqual(code,200,r)
        with server.connect() as db:
            eid=db.execute('SELECT id FROM entries WHERE text_id=?',(r['id'],)).fetchone()[0]
            rows=list(db.execute('SELECT * FROM collaborator_assignments WHERE record_id IN (?,?)',(r['id'],eid)));self.assertEqual(len(rows),2)
            self.assertEqual({x['kind']:x['mode'] for x in rows},{'text':'manual','corpus':'auto'});self.assertFalse({'text','corpus'}&{x['id'] for x in rows})

    def test_alignment_copies_retain_playback_and_independent_hierarchy(self):
        e=self.seed();other=self.call('/api/new-text',dict(title='Unrelated',empty=False))[1]['id']
        sid=self.call('/api/timeline-create',dict(name='Recording'))[1]['id']
        with server.connect() as db:
            track=db.execute('SELECT id FROM timeline_tracks WHERE session_id=?',(sid,)).fetchone()[0]
            db.execute("INSERT INTO timeline_intervals(id,session_id,track_id,entry_id,start_ms,end_ms) VALUES('aligned',?,?,?,?,?)",(sid,track,e['id'],0,1000))
            db.execute('INSERT INTO timeline_text_orders VALUES(?,?,1)',(e['text_id'],sid))
        code,r=self.copy(self.plan(e['text_id']));self.assertEqual(code,200,r);self.assertEqual(r['timelines'],1)
        with server.connect() as db:
            new=db.execute('SELECT i.* FROM timeline_intervals i JOIN entries e ON e.id=i.entry_id WHERE e.text_id=?',(r['id'],)).fetchone()
            self.assertNotEqual(new['id'],'aligned');self.assertNotEqual(new['session_id'],sid);self.assertEqual(new['start_ms'],0)
            self.assertEqual(db.execute('SELECT session_id FROM timeline_text_orders WHERE id=?',(r['id'],)).fetchone()[0],new['session_id'])
            self.assertEqual(db.execute('SELECT COUNT(*) FROM timeline_intervals WHERE session_id=?',(new['session_id'],)).fetchone()[0],1)
        self.assertEqual(self.undo()[0],200);self.assertEqual(self.undo('redo')[0],200)

    def test_mid_copy_failure_rolls_back_every_new_row(self):
        e=self.seed();p=self.plan(e['text_id'])
        with patch('text_copy.alignments',side_effect=ValueError('copy interrupted')):
            self.assertEqual(self.copy(p)[0],400)
        self.assertEqual(len(self.call('/api/texts')[1]),1);self.assertEqual(len(self.entries()),1)
        self.assertEqual(self.copy(p)[0],200)

    def test_background_copy_uses_same_atomic_history_and_stale_guard(self):
        self.assertEqual(self.call('/text-copy.js')[0],200)
        e=self.seed();p=self.plan(e['text_id'])
        result=self.execute('copy-text',dict(id=p['id'],token=p['token'],title='Background copy'))
        self.assertEqual(result['count'],1);self.assertEqual(self.undo()[0],200)
        self.assertNotIn(result['id'],[r['id'] for r in self.call('/api/texts')[1]])
        self.assertEqual(self.undo('redo')[0],200)
        failed=self.wait(self.submit('copy-text',dict(id=p['id'],token=p['token'],title='Stale')))
        self.assertEqual(failed['state'],'error');self.assertEqual(len(self.call('/api/texts')[1]),2)

    def test_layers_and_code_time_links_follow_new_word_and_interval_identities(self):
        import test_code_switching,test_annotations
        c=test_code_switching.CodeSwitchingTests();c.call=self.call;c.seed();marked=c.mark();sid,parent,interval,change=c.session()
        with server.connect() as db:span=db.execute('SELECT id FROM code_spans WHERE record_id=?',(c.eid,)).fetchone()[0]
        c.link(span,interval)
        a=test_annotations.AnnotationTests();a.call=self.call;layer=a.layer()
        entry=self.call('/api/entries?text='+c.tid)[1]['items'][0];a.annotate('corpus',entry,layer)
        code,r=self.copy(self.plan(c.tid));self.assertEqual(code,200,r)
        with server.connect() as db:
            eid=db.execute('SELECT id FROM entries WHERE text_id=?',(r['id'],)).fetchone()[0]
            newspan=db.execute('SELECT * FROM code_spans WHERE record_id=?',(eid,)).fetchone();self.assertNotEqual(newspan['id'],span)
            correspondence=db.execute('SELECT * FROM code_time_links WHERE span_id=?',(newspan['id'],)).fetchone();self.assertIsNotNone(correspondence);self.assertNotEqual(correspondence['interval_id'],interval)
            child=db.execute('SELECT * FROM timeline_intervals WHERE id=?',(correspondence['interval_id'],)).fetchone()
            self.assertEqual(db.execute('SELECT entry_id FROM timeline_intervals WHERE id=?',(child['parent_id'],)).fetchone()[0],eid)
            cells=list(db.execute('SELECT * FROM annotation_cells WHERE record_id=?',(eid,)));self.assertEqual(len(cells),1);self.assertEqual(cells[0]['value'],'NOUN')
            self.assertIsNotNone(db.execute('SELECT id FROM corpus_units WHERE id=? AND entry_id=?',(cells[0]['unit_id'],eid)).fetchone())
        self.assertEqual(self.undo()[0],200);self.assertEqual(self.undo('redo')[0],200)
