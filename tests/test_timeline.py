import json
import time
import wave
import unittest
from pathlib import Path
import server
import timeline
import media_engine
import test_server
from restore_backup import restore

class TimelineTests(unittest.TestCase):
    tearDown=test_server.APITests.tearDown
    call=test_server.APITests.call
    def setUp(self):
        test_server.APITests.setUp(self)
        self.wav=Path(self.temp.name)/'sample.wav'
        with wave.open(str(self.wav),'wb') as w:
            w.setparams((1,2,16000,0,'NONE','not compressed'));w.writeframes(b'\0\0'*32000)
        asset=dict(name='sample.wav',path=str(self.wav),storage='link',metadata=dict(duration_ms=2000,start_us=0,fingerprint=media_engine.fingerprint(self.wav),streams=[dict(type='audio',codec='pcm_s16le',channels=1)]))
        self.job=media_engine.submit(server.DB,'test-import',lambda update:asset)
        while media_engine.job_view(server.DB,self.job)['state'] not in ('done','error'):time.sleep(.01)
        code,r=self.call('/api/timeline-create',dict(job=self.job,name='test'))
        self.assertEqual(code,200,r);self.sid=r['id']
        code,r=self.call('/api/import',dict(title='alignment test',content='#pass([a], (([a],[A]),), [one])\n#pass([b], (([b],[B]),), [two])'))
        self.tid=r['id'];self.eids=[r['id'] for r in self.call('/api/entries?text_id='+self.tid)[1]['items']]

    def detail(self):return self.call('/api/timeline-detail?id='+self.sid+'&language=ordos&start=-10000&end=100000')[1]
    def mutation(self,action,**extra):return self.call('/api/timeline-'+action,dict(id=self.sid,revision=self.detail()['session']['revision'],**extra))
    def add(self,start=100,end=800,entry=0,track=None):
        code,r=self.mutation('interval',track_id=track or self.detail()['tracks'][0]['id'],entry_id=self.eids[entry],start_ms=start,end_ms=end)
        self.assertEqual(code,200,r);return self.detail()['intervals'][-1]
    def undo(self,kind='undo'):
        state=self.call('/api/undo-state')[1];return self.call('/api/'+kind,{'generation':state['generation']})

    def test_complete_detail_preloads_offscreen_intervals_and_neighbors(self):
        with server.connect() as db:
            track=db.execute('SELECT id FROM timeline_tracks WHERE session_id=?',(self.sid,)).fetchone()[0]
            for i in range(2100):
                db.execute("INSERT INTO timeline_intervals(id,session_id,track_id,start_ms,end_ms,label,status,revision) VALUES(?,?,?,?,?,?,?,1)",
                           (f'cache-{i}',self.sid,track,i*1000,i*1000+500,f'Interval {i}','confirmed'))
        code,r=self.call('/api/timeline-detail?language=ordos&id='+self.sid+'&start=0&end=1000&complete=1')
        self.assertEqual(code,200,r);self.assertTrue(r['complete']);self.assertFalse(r['truncated']);self.assertEqual(len(r['intervals']),2100)
        middle=next(x for x in r['intervals'] if x['id']=='cache-1000')
        self.assertEqual(middle['previous_ms'],999500);self.assertEqual(middle['next_ms'],1001000)
        code,r=self.call('/api/timeline-detail?language=ordos&id='+self.sid+'&start=0&end=1000')
        self.assertEqual(code,200,r);self.assertFalse(r['complete']);self.assertEqual(len(r['intervals']),2)

    def test_selected_interval_survives_viewport_but_not_deletion(self):
        interval=self.add()
        url='/api/timeline-detail?id='+self.sid+'&language=ordos&start=10000&end=20000&selected_interval='+interval['id']
        code,result=self.call(url)
        self.assertEqual(code,200,result)
        self.assertEqual(result['intervals'],[])
        self.assertEqual(result['selected_interval']['id'],interval['id'])
        self.assertEqual(result['selected_interval']['entry_id'],self.eids[0])
        self.mutation('delete-interval',interval_id=interval['id'],confirmed=True)
        self.assertIsNone(self.call(url)[1]['selected_interval'])

    def test_missing_and_changed_media_preserve_alignment(self):
        self.add()
        self.assertNotIn('unavailable',self.detail()['media'])
        moved=self.wav.with_name('moved.wav')
        self.wav.rename(moved)
        missing=self.detail()
        self.assertIn('unavailable',missing['media'])
        self.assertEqual(len(missing['intervals']),1)
        moved.rename(self.wav)
        self.assertNotIn('unavailable',self.detail()['media'])
        with self.wav.open('ab') as f:f.write(b'changed')
        self.assertIn('unavailable',self.detail()['media'])

    def test_pending_rejects_foreign_text_scope(self):
        with server.connect() as db:
            db.execute("UPDATE texts SET language_id='other-language' WHERE id=?",(self.tid,))
        code,result=self.call('/api/timeline-pending?id='+self.sid+'&language=ordos&text_id='+self.tid)
        self.assertEqual(code,200,result)
        self.assertEqual(result['items'],[])
        self.assertEqual(result['total'],0)

    def test_collision_boundaries_other_tracks_and_negative_times(self):
        self.add();track=self.detail()['tracks'][0]['id']
        self.assertEqual(self.mutation('interval',track_id=track,entry_id=self.eids[1],start_ms=700,end_ms=900)[0],400)
        self.add(800,1000,1)
        self.mutation('track',name='other',kind='sentence');self.add(200,900,1,self.detail()['tracks'][1]['id'])
        self.add(-1000,-10,0)
        self.assertEqual(len(self.detail()['intervals']),4)
        self.assertEqual(self.detail()['extent'][0],-1000)

    def test_replace_preview_confirmation_stale_token_and_undo(self):
        self.add(500,4000);before=self.call('/api/entries?text_id='+self.tid)[1]
        p=self.mutation('replace-preview',job=self.job,offset_ms=-1500)[1]
        self.assertEqual(p['outside'],1)
        self.assertEqual(self.mutation('replace',job=self.job,offset_ms=-1500,token=p['token'])[0],400)
        self.assertEqual(self.mutation('replace',job=self.job,offset_ms=0,token=p['token'],confirmed=True)[0],400)
        code,r=self.mutation('replace',job=self.job,offset_ms=-1500,token=p['token'],confirmed=True);self.assertEqual(code,200,r)
        self.assertEqual(self.detail()['intervals'][0]['start_ms'],-1000)
        self.assertEqual(self.detail()['intervals'][0]['end_ms'],2500)
        self.assertEqual(before,self.call('/api/entries?text_id='+self.tid)[1])
        self.assertEqual(self.undo()[0],200);self.assertEqual(self.detail()['intervals'][0]['start_ms'],500)
        self.assertEqual(self.undo('redo')[0],200);self.assertEqual(self.detail()['intervals'][0]['start_ms'],-1000)

    def test_revision_and_language_guards(self):
        rev=self.detail()['session']['revision'];self.add()
        self.assertEqual(self.call('/api/timeline-track',dict(id=self.sid,revision=rev,name='stale',kind='event'))[0],400)
        lid=self.call('/api/save-language',dict(name='other',metadata={}))[1]['id']
        self.assertEqual(self.call('/api/timeline-track',dict(id=self.sid,revision=self.detail()['session']['revision'],name='wrong',_language=lid))[0],400)

    def test_pending_split_delete_does_not_delete_corpus(self):
        self.add();pending='/api/timeline-pending?id='+self.sid+'&language=ordos'
        self.assertEqual(self.call(pending)[1]['total'],1)
        i=self.detail()['intervals'][0]
        self.assertEqual(self.mutation('split',interval_id=i['id'],at_ms=400)[0],200)
        self.assertEqual(len(self.detail()['intervals']),2)
        self.assertEqual(self.call(pending)[1]['total'],1)
        for i in self.detail()['intervals']:self.assertEqual(self.mutation('delete-interval',interval_id=i['id'],confirmed=True)[0],200)
        self.assertEqual(self.call(pending)[1]['total'],2)
        self.assertEqual(len(self.call('/api/entries?text_id='+self.tid)[1]['items']),2)

    def test_backup_and_language_exchange_remap(self):
        self.add()
        backup=self.call('/api/backup')[1];path=Path(self.temp.name)/'backup.json';path.write_text(json.dumps(backup),encoding='utf-8')
        dest=Path(self.temp.name)/'restored.sqlite3';restore(path,dest)
        import sqlite3
        from contextlib import closing
        with closing(sqlite3.connect(dest)) as db:self.assertEqual(db.execute('SELECT COUNT(*) FROM timeline_intervals').fetchone()[0],1)
        bundle=self.call('/api/export-language?language=ordos')[1]
        lid=self.call('/api/save-language',dict(name='destination',metadata={}))[1]['id']
        code,r=self.call('/api/import-language',dict(bundle=bundle,_language=lid));self.assertEqual(code,200,r)
        sid=self.call('/api/timeline-list?language='+lid)[1][0]['id'];self.assertNotEqual(sid,self.sid)
        d=self.call('/api/timeline-detail?language='+lid+'&id='+sid)[1]
        self.assertNotEqual(d['intervals'][0]['entry_id'],self.eids[0]);self.assertFalse(d['intervals'][0]['missing_entry']);self.assertEqual(d['media']['storage'],'missing')

    def test_source_change_and_worker_waveform(self):
        asset=self.detail()['media'];r=media_engine.prepare(server.DB,asset,'wave')
        for _ in range(500):
            j=media_engine.job_view(server.DB,r['job'])
            if j['state'] in ('done','error'):break
            time.sleep(.01)
        self.assertEqual(j['state'],'done',j)
        result=media_engine.wave_data(server.DB,asset,0,2000)
        self.assertTrue(result['ready']);self.assertEqual(len(result['channels']),1)
        self.wav.write_bytes(b'changed')
        with self.assertRaisesRegex(ValueError,'修改'):media_engine.resolve(server.DB,asset)

    def test_copy_import_and_shorter_source_confirmation(self):
        r=media_engine.import_media(server.DB,{'path':str(self.wav),'storage':'copy'})
        for _ in range(500):
            j=media_engine.job_view(server.DB,r['job'])
            if j['state'] in ('done','error'):break
            time.sleep(.01)
        self.assertEqual(j['state'],'done',j)
        asset=media_engine.imported(server.DB,r['job']);self.assertEqual(asset['storage'],'copy')
        self.assertTrue(media_engine.resolve(server.DB,asset).is_relative_to(server.DB.parent/'media'))
        self.add(1000,5000)
        short={**asset,'metadata':{**asset['metadata'],'duration_ms':1000}}
        jid=media_engine.submit(server.DB,'short',lambda update:short)
        while media_engine.job_view(server.DB,jid)['state']!='done':time.sleep(.01)
        p=self.mutation('replace-preview',job=jid,offset_ms=0)[1]
        self.assertEqual((p['old_duration_ms'],p['new_duration_ms']),(2000,1000));self.assertTrue(p['warnings'])
        self.mutation('track',name='new track',kind='event')
        self.assertEqual(self.mutation('replace',job=jid,offset_ms=0,token=p['token'],confirmed=True)[0],400)
        p=self.mutation('replace-preview',job=jid,offset_ms=0)[1]
        self.assertEqual(self.mutation('replace',job=jid,offset_ms=0,token=p['token'],confirmed=True)[0],200)
        self.assertEqual(self.detail()['intervals'][0]['end_ms'],5000)

    def test_event_layers_and_audio_proxy(self):
        self.mutation('track',name='laugh',kind='event');track=self.detail()['tracks'][-1]['id']
        self.assertEqual(self.mutation('interval',track_id=track,label='laughter',start_ms=10,end_ms=1000,status='review')[0],200)
        self.assertEqual(self.detail()['intervals'][0]['status'],'review')
        target=Path(self.temp.name)/'proxy.mp4'
        media_engine.proxy(self.wav,target,self.detail()['media']['metadata'],lambda *_:None)
        meta=media_engine.probe(target);self.assertEqual(meta['streams'][0]['codec'],'aac');self.assertAlmostEqual(meta['duration_ms'],2000,delta=60)

    def test_deleted_sentence_retains_interval(self):
        i=self.add();e=next(e for e in self.call('/api/entries?text_id='+self.tid)[1]['items'] if e['id']==i['entry_id']);code,r=self.call('/api/delete-entry',dict(id=i['entry_id'],text_id=self.tid,revision=e['revision'],confirmed=True));self.assertEqual(code,200,r)
        self.assertTrue(self.detail()['intervals'][0]['missing_entry'])
        self.undo();self.assertFalse(self.detail()['intervals'][0]['missing_entry'])

    def test_empty_timeline_then_attach_default_name(self):
        code,r=self.call('/api/timeline-create',{})
        self.assertEqual(code,200,r);self.sid=r['id']
        d=self.detail();self.assertIsNone(d['media']);self.assertEqual(d['session']['name'],'未命名时间轴')
        self.add(500,4000)
        p=self.mutation('replace-preview',job=self.job)[1]
        self.assertEqual(p['outside'],1)
        self.assertEqual(self.mutation('replace',job=self.job,token=p['token'],confirmed=True)[0],200)
        self.assertEqual(self.detail()['session']['name'],'sample.wav')
        self.assertEqual(self.detail()['intervals'][0]['end_ms'],4000)
        self.undo();self.assertIsNone(self.detail()['media'])

    def test_copy_delete_rename_and_undo_preserve_corpus_and_media(self):
        original=self.add();before=self.call('/api/entries?text_id='+self.tid)[1];source=self.sid
        code,r=self.mutation('duplicate');self.assertEqual(code,200,r);self.sid=r['id']
        d=self.detail();copy=d['intervals'][0]
        self.assertNotEqual(original['id'],copy['id']);self.assertNotEqual(original['track_id'],copy['track_id'])
        self.assertEqual(original['entry_id'],copy['entry_id'])
        self.assertEqual(self.mutation('rename',name='新名称')[0],200)
        self.assertEqual(self.detail()['session']['name'],'新名称')
        self.assertEqual(self.mutation('delete')[0],400)
        self.assertEqual(self.mutation('delete',confirmed=True)[0],200)
        self.assertEqual(before,self.call('/api/entries?text_id='+self.tid)[1]);self.assertTrue(self.wav.exists())
        self.undo();self.assertEqual(len(self.detail()['intervals']),1)
        self.sid=source;self.assertEqual(self.detail()['intervals'][0]['id'],original['id'])

    def test_empty_timeline_exchange_and_scope_guards(self):
        code,r=self.call('/api/timeline-create',{});self.assertEqual(code,200)
        with server.connect(audit=False) as db:
            bundle=timeline.export_bundle(db,'ordos')
            timeline.import_bundle(db,bundle,'ordos',{})
        self.assertEqual(self.call('/api/timeline-delete',dict(id=self.sid,revision=self.detail()['session']['revision'],confirmed=True,_language='all'))[0],400)

    def test_sentence_clips_batch_reflects_replace_delete_and_undo(self):
        self.add(-100,700);self.add(900,3000,1)
        def clips():return self.call('/api/timeline-clips?ids='+','.join(self.eids))[1]
        c=clips();self.assertEqual(c[self.eids[0]][0]['play_start_ms'],0)
        self.assertEqual(c[self.eids[1]][0]['play_end_ms'],2000)
        old=c[self.eids[0]][0]['asset']
        plan=self.mutation('replace-preview',job=self.job,offset_ms=100)[1]
        self.mutation('replace',job=self.job,offset_ms=100,token=plan['token'],confirmed=True)
        c=clips();self.assertNotEqual(c[self.eids[0]][0]['asset'],old)
        self.assertEqual(c[self.eids[0]][0]['end_ms'],800)
        self.mutation('delete',confirmed=True);self.assertEqual(clips()[self.eids[0]],[])
        self.undo();self.assertEqual(len(clips()[self.eids[0]]),1)

    def test_sentence_clips_excludes_events_silent_media_and_outside(self):
        self.add(4000,5000)
        self.assertEqual(self.call('/api/timeline-clips?ids='+self.eids[0])[1][self.eids[0]],[])
        self.add(100,200,1)
        with server.connect(audit=False) as db:
            media=self.detail()['media'];meta=media['metadata'];meta['streams']=[{'type':'video','codec':'h264'}]
            db.execute('UPDATE timeline_media SET metadata=? WHERE id=?',(json.dumps(meta),media['id']))
        self.assertEqual(self.call('/api/timeline-clips?ids='+self.eids[1])[1][self.eids[1]],[])
        self.assertEqual(self.call('/api/timeline-clips?ids='+','.join(str(i) for i in range(201)))[0],400)
