"""Sentence blocks read live IPA instead of old interval label snapshots."""
import unittest
import server
import test_timeline as base


class TimelineLiveTextTests(unittest.TestCase):
    setUp=base.TimelineTests.setUp
    tearDown=base.TimelineTests.tearDown
    call=base.TimelineTests.call
    detail=base.TimelineTests.detail
    mutation=base.TimelineTests.mutation
    add=base.TimelineTests.add
    undo=base.TimelineTests.undo

    def test_sentence_ipa_wins_legacy_label_and_follows_edit_undo_and_offscreen_selection(self):
        interval=self.add();iid=interval['id']
        with server.connect(audit=False) as db:
            db.execute('UPDATE timeline_intervals SET label=? WHERE id=?',('old IPA snapshot',iid))
        self.assertEqual(self.detail()['intervals'][0]['text'],'a')
        old=self.call('/api/entries?text_id='+self.tid)[1]['items'][0]
        code,result=self.call('/api/save',{**old,'ipa':'tʃʰãŋa ɡəː','notes':old.get('notes','')})
        self.assertEqual(code,200,result)
        for tail in ('','&complete=1','&start=500000&end=600000&selected_interval='+iid):
            code,detail=self.call('/api/timeline-detail?id='+self.sid+'&language=ordos'+tail)
            self.assertEqual(code,200,detail)
            item=detail['selected_interval'] if 'selected_interval=' in tail else detail['intervals'][0]
            self.assertEqual(item['text'],'tʃʰãŋa ɡəː')
            self.assertEqual(item['label'],'old IPA snapshot')
            self.assertNotIn('track_kind',item)
        self.assertEqual(self.undo()[0],200)
        self.assertEqual(self.detail()['intervals'][0]['text'],'a')
        self.assertEqual(self.undo('redo')[0],200)
        self.assertEqual(self.detail()['intervals'][0]['text'],'tʃʰãŋa ɡəː')
        fresh=self.call('/api/entries?text_id='+self.tid)[1]['items'][0]
        code,result=self.call('/api/save',{**fresh,'ipa':'','translation':'current translation','notes':fresh.get('notes','')})
        self.assertEqual(code,200,result)
        self.assertEqual(self.detail()['intervals'][0]['text'],'current translation')

    def test_event_caption_and_missing_sentence_fallback_are_preserved(self):
        interval=self.add();iid=interval['id']
        with server.connect(audit=False) as db:
            db.execute('UPDATE timeline_intervals SET label=? WHERE id=?',('old IPA snapshot',iid))
        self.mutation('track',name='event',kind='event')
        event_track=next(t['id'] for t in self.detail()['tracks'] if t['kind']=='event')
        code,r=self.mutation('interval',track_id=event_track,label='laughter',start_ms=20,end_ms=800)
        self.assertEqual(code,200,r)
        self.assertIn('laughter',[i['text'] for i in self.detail()['intervals']])
        entry=self.call('/api/entries?text_id='+self.tid)[1]['items'][0]
        code,r=self.call('/api/delete-entry',dict(id=entry['id'],text_id=self.tid,revision=entry['revision'],confirmed=True))
        self.assertEqual(code,200,r)
        missing=next(i for i in self.detail()['intervals'] if i['id']==iid)
        self.assertTrue(missing['missing_entry']);self.assertEqual(missing['text'],'old IPA snapshot')

    def test_independent_sentence_uses_current_ipa_without_changing_saved_interval_label(self):
        code,example=self.call('/api/example-save',dict(body=dict(ipa='old independent',translation='translation',words=[dict(form='root',gloss='ROOT')],notes='')))
        self.assertEqual(code,200,example)
        track=self.detail()['tracks'][0]['id']
        code,result=self.mutation('interval',track_id=track,entry_id='independent:'+example['id'],start_ms=10,end_ms=900)
        self.assertEqual(code,200,result)
        interval=self.detail()['intervals'][0]
        with server.connect(audit=False) as db:db.execute('UPDATE timeline_intervals SET label=? WHERE id=?',('old copied text',interval['id']))
        self.assertEqual(self.detail()['intervals'][0]['text'],'old independent')
        example['body']['ipa']='new independent ɣəː'
        code,result=self.call('/api/example-save',example)
        self.assertEqual(code,200,result)
        updated=self.detail()['intervals'][0]
        self.assertEqual(updated['text'],'new independent ɣəː');self.assertEqual(updated['label'],'old copied text')
