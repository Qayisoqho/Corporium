import json
import io
import math
import os
from pathlib import Path
import struct
import time
import unittest
from unittest.mock import patch
import wave

import media_engine
import recorder
import server
import test_server
from restore_backup import restore


class SyntheticInput:
    """Deterministic PCM fixture; never opens the physical microphone."""
    amplitude = .5
    warning = False
    failure = False

    def __init__(self, config):
        self.config=config
        self.reads=0
        rate=config['rate'];bits=config['bits'];channels=config['channels']
        values=[round(math.sin(i*2*math.pi*1000/rate)*((1<<(bits-1))-1)*self.amplitude)
                for i in range(rate//10) for _ in range(channels)]
        self.chunk=b''.join(v.to_bytes(bits//8,'little',signed=True) for v in values)

    def __enter__(self):return self
    def __exit__(self,*args):pass
    def read(self,stop):
        if self.failure and self.reads:raise OSError('Synthetic device disconnected')
        if stop.wait(.01):return b'',False
        self.reads+=1
        return self.chunk,self.warning
    def drain(self):return iter(())


class RecorderTests(unittest.TestCase):
    call=test_server.APITests.call

    def setUp(self):
        test_server.APITests.setUp(self)
        self.service=recorder.Recorder(SyntheticInput)
        self.old_service=recorder.SERVICE;recorder.SERVICE=self.service

    def tearDown(self):
        self.service.shutdown();recorder.SERVICE=self.old_service
        test_server.APITests.tearDown(self)

    def example(self):
        code,result=self.call('/api/example-save',dict(language_id='ordos',body={'ipa':'test','words':[],'translation':''}))
        self.assertEqual(code,200,result)
        return result['id']

    def test_pending_uses_discovered_manifests_without_locking_directory_scan(self):
        take=self.capture()
        result=self.service.stop(server.DB,take['token'])
        self.assertEqual(result['state'],'ready')
        cold=recorder.Recorder(SyntheticInput);glob=Path.glob;patterns=[]
        def scanned(path,pattern):
            patterns.append(pattern)
            self.assertFalse(cold.lock._is_owned())
            yield from glob(path,pattern)
        with patch.object(Path,'glob',scanned):
            pending=cold.pending(server.DB,'ordos')
        self.assertEqual([t['token'] for t in pending],[take['token']])
        self.assertEqual(patterns,['*/*/*/recording.json'])
        self.assertEqual(cold.pending(server.DB,'other'),[])

    def capture(self,kind='timeline',rid='',**config):
        code,take=self.call('/api/recorder-start',dict(kind=kind,record_id=rid,**{'bits':16,**config}))
        self.assertEqual(code,200,take)
        token=take['token']
        deadline=time.monotonic()+5
        while time.monotonic()<deadline:
            current=self.service.status(server.DB,token)
            if current['bytes'] or current['state']=='ready':break
            time.sleep(.01)
        code,result=self.call('/api/recorder-stop',dict(token=token))
        self.assertEqual(code,200,result)
        self.assertEqual(result['state'],'ready',result)
        self.assertGreater(result['bytes'],0,result)
        return result

    def keep(self,take,**fields):
        return self.call('/api/recorder-keep',dict(token=take['token'],**fields))

    def undo(self,kind='undo'):
        generation=self.call('/api/undo-state')[1]['generation']
        result=self.call('/api/'+kind,dict(generation=generation))
        self.assertEqual(result[0],200,result)

    def test_real_pcm_specs_meter_and_trial_cannot_attach(self):
        for bits in (16,24):
            for channels in (1,2):
                with self.subTest(bits=bits,channels=channels):
                    take=self.capture(bits=bits,channels=channels)
                    path=self.service.file(self.service._find(server.DB,take['token']))
                    with wave.open(str(path)) as wav:
                        self.assertEqual(wav.getparams()[:3],(channels,bits//8,48000))
                        self.assertEqual(wav.getnframes(),take['bytes']//(channels*bits//8))
                    self.assertAlmostEqual(take['peak_db'],-6,delta=.2)
                    self.assertFalse(take['clipped'])
        take=self.capture(trial=True)
        self.assertEqual(self.keep(take)[0],400)
        self.assertNotIn(take['token'],[t['token'] for t in self.service.pending(server.DB,'ordos')])

    def test_dictionary_attachment_retake_idempotency_undo_and_backup(self):
        code,word=self.call('/api/lexeme-save',dict(headword='word',body=dict(usages=[dict(pos='N',senses=[dict(short_gloss='word')])],variants=[dict(form='word-variant')])) )
        self.assertEqual(code,200,word)
        take=self.capture('lexeme',word['id'])
        self.assertEqual(self.keep(take,name='first')[0],200)
        self.assertEqual(self.keep(take,name='retry')[0],200)
        items=self.call('/api/object-media?kind=lexeme&id='+word['id'])[1]['items']
        self.assertEqual(len(items),1)
        original=media_engine.resolve(server.DB,items[0]['asset'])
        self.undo();self.assertEqual(len(self.call('/api/object-media?kind=lexeme&id='+word['id'])[1]['items']),0)
        self.assertTrue(original.exists())
        self.undo('redo')
        second=self.capture('lexeme',word['id']);self.assertEqual(self.keep(second)[0],200)
        self.assertEqual(len(self.call('/api/object-media?kind=lexeme&id='+word['id'])[1]['items']),2)
        import project_backup
        with server.connect(audit=False) as db:prepared=project_backup.prepare(db,server.DB)
        import language_exchange
        package=language_exchange.staged(server.DB,prepared['token'],'project-backup')
        destination=Path(self.temp.name)/'restored'/'data'/'corpus.sqlite3'
        restore(package,destination)
        old=server.DB
        try:
            server.DB=destination
            restored=self.call('/api/object-media?kind=lexeme&id='+word['id'])[1]['items']
            self.assertEqual(len(restored),2)
            for item in restored:
                p=media_engine.resolve(server.DB,item['asset']);self.assertTrue(p.is_relative_to(destination.parent))
        finally:server.DB=old

    def test_corpus_recording_rejected_and_existing_timeline_playback_preserved(self):
        self.call('/api/import',dict(title='test',content='#pass([ipa], (([word],[N]),), [translation])'))
        entry=self.call('/api/entries')[1]['items'][0]
        resolved=self.call('/api/recorder-context?kind=corpus&id='+entry['id']+'&language=all')
        self.assertEqual(resolved[0],400,resolved)
        self.assertEqual(self.call('/api/recorder-start',dict(kind='corpus',record_id=entry['id']))[0],400)
        take=self.capture('timeline')
        code,result=self.keep(take);self.assertEqual(code,200,result)
        with server.connect(audit=False) as db:
            track=db.execute('SELECT id FROM timeline_tracks WHERE session_id=?',(result['id'],)).fetchone()[0]
        code,aligned=self.call('/api/timeline-interval',dict(id=result['id'],revision=1,track_id=track,entry_id=entry['id'],start_ms=0,end_ms=100))
        self.assertEqual(code,200,aligned)
        clips=self.call('/api/timeline-clips?ids='+entry['id'])[1][entry['id']]
        self.assertEqual(len(clips),1)
        self.assertEqual(clips[0]['start_ms'],0)
        with server.connect(audit=False) as db:
            old=list(db.execute('SELECT id,media_id FROM timeline_sessions'))
        second=self.capture();self.assertEqual(self.keep(second)[0],200)
        with server.connect(audit=False) as db:
            rows=list(db.execute('SELECT id,media_id FROM timeline_sessions'))
            self.assertEqual(len(rows),2);self.assertTrue(all(tuple(r) in [tuple(v) for v in rows] for r in old))

    def test_independent_identity_language_owner_and_target_validation(self):
        rid=self.example();take=self.capture('independent',rid)
        self.assertEqual(self.keep(take,_language='missing')[0],400)
        self.assertEqual(self.keep(take,speaker='missing')[0],400)
        self.assertEqual(self.keep(take)[0],200)
        self.assertEqual(len(self.call('/api/object-media?kind=independent&id='+rid)[1]['items']),1)
        self.assertEqual(self.call('/api/recorder-start',dict(kind='corpus',record_id=rid))[0],400)
        self.assertEqual(self.call('/api/recorder-start',dict(kind='lexeme',record_id='../bad'))[0],400)
        self.assertEqual(self.call('/api/recorder-status?token=../bad')[0],400)
        self.assertEqual(self.call('/api/recorder-start',dict(kind='timeline',rate=True))[0],400)

    def test_capture_failure_clipping_and_buffer_warning_preserve_audio(self):
        class Fault(SyntheticInput):
            amplitude=1
            warning=True
            failure=True
        self.service.capture=Fault
        take=self.capture()
        self.assertTrue(take['clipped']);self.assertTrue(take['buffer_warning'])
        self.assertEqual(take['error'],'Synthetic device disconnected')
        self.assertEqual(self.keep(take)[0],200)

    def test_interrupted_recovery_and_foreign_process_no_rewrite(self):
        take=self.capture();original=self.service._find(server.DB,take['token']);path=self.service.file(original)
        data=json.loads((original['_folder']/'recording.json').read_text(encoding='utf-8'))
        data.update(state='recording',process_id=-1,bytes=0)
        (original['_folder']/'recording.json').write_text(json.dumps(data),encoding='utf-8')
        with path.open('r+b') as f:f.write(recorder.header(48000,16,1,0))
        recovered=recorder.Recorder().status(server.DB,take['token'])
        self.assertTrue(recovered['recovered']);self.assertEqual(recovered['bytes'],take['bytes'])
        data.update(process_id=os.getpid())
        (original['_folder']/'recording.json').write_text(json.dumps(data),encoding='utf-8')
        before=path.read_bytes()
        with self.assertRaisesRegex(ValueError,'另一个'):
            recorder.Recorder().status(server.DB,take['token'])
        self.assertEqual(path.read_bytes(),before)

    def test_recording_root_is_project_local_and_path_traversal_rejected(self):
        old=server.DB
        project=Path(self.temp.name)/'project';(project/'data').mkdir(parents=True)
        try:
            server.DB=project/'data'/'corpus.sqlite3';server.init()
            take=self.capture();self.assertEqual(self.keep(take)[0],200)
            with server.connect(audit=False) as db:
                asset=server.timeline.media_view(db,db.execute('SELECT id FROM timeline_media').fetchone()[0])
            self.assertTrue(media_engine.resolve(server.DB,asset).is_relative_to(project/'media'/'recordings'))
            import language_exchange
            with server.connect(audit=False) as db:package=language_exchange.prepare(db,server.DB,'ordos',True)
            source=language_exchange.staged(server.DB,package['token'],'export')
            with server.connect() as db:
                imported=language_exchange.import_new(db,server.DB,source,'Imported recording',[])
                mid=db.execute('SELECT id FROM timeline_media WHERE language_id=?',(imported['language_id'],)).fetchone()[0]
                copied=server.timeline.media_view(db,mid)
            self.assertEqual(media_engine.resolve(server.DB,copied).read_bytes(),media_engine.resolve(server.DB,asset).read_bytes())
            with self.assertRaises(ValueError):media_engine.resolve(server.DB,{**asset,'path':'../secret.wav'})
            with self.assertRaises(ValueError):self.service.status(old,take['token'])
        finally:server.DB=old

    def test_single_capture_cross_origin_and_discard_keeps_file(self):
        code,take=self.call('/api/recorder-start',dict(kind='timeline',bits=16))
        self.assertEqual(code,200,take)
        self.assertEqual(self.call('/api/recorder-start',dict(kind='timeline',bits=16))[0],400)
        self.assertEqual(self.call('/api/recorder-stop',dict(token=take['token']),origin='https://other.example')[0],403)
        self.service.stop(server.DB,take['token'])
        self.assertEqual(self.call('/api/recorder-discard',dict(token=take['token']))[0],400)
        self.assertEqual(self.call('/api/recorder-discard',dict(token=take['token'],confirmed=True))[0],200)
        self.assertTrue(self.service.file(self.service._find(server.DB,take['token'])).exists())
        self.assertFalse(self.service.pending(server.DB,'ordos'))

    def test_desktop_project_and_language_change_blocked_during_capture(self):
        import desktop
        code,take=self.call('/api/recorder-start',dict(kind='timeline',bits=16))
        self.assertEqual(code,200,take)
        projects=desktop.Projects(Path(self.temp.name)/'settings')
        destination=Path(self.temp.name)/'new-project'
        with self.assertRaisesRegex(ValueError,'停止录音'):projects.create(destination)
        self.assertFalse(destination.exists())
        with self.assertRaisesRegex(ValueError,'停止录音'):projects.set_ui_language('en')
        self.service.stop(server.DB,take['token'])

    def test_pending_error_is_localized_without_translating_names_or_source(self):
        import ui_localization
        value={'items':[dict(error='已有录音进行中，请先停止',context={'record_id':'已有录音进行中，请先停止'})]}
        result=ui_localization.present(value,'/api/recorder-pending','en')
        self.assertEqual(result['items'][0]['error'],'A recording is already in progress. Stop it first.')
        self.assertEqual(result['items'][0]['context'],value['items'][0]['context'])

    def test_trial_memory_only_download_release_and_formal_auto_save(self):
        before=list(recorder.recording_root(server.DB).rglob('*'))
        take=self.capture(trial=True)
        self.assertEqual(list(recorder.recording_root(server.DB).rglob('*')),before)
        source,name=self.service.playback(server.DB,take['token']);self.assertIsInstance(source,bytes)
        with wave.open(io.BytesIO(source)) as audio:self.assertGreater(audio.getnframes(),0)
        import desktop
        from types import SimpleNamespace
        destination=Path(self.temp.name)/'user-download.wav'
        bridge=desktop.Bridge(SimpleNamespace(settings={}))
        bridge._origin='http://127.0.0.1:1234';bridge._window=SimpleNamespace(get_current_url=lambda:bridge._origin+'/',create_file_dialog=lambda *a,**kw:[str(destination)])
        self.assertTrue(bridge.save_recording(take['token'])['ok']);self.assertEqual(destination.read_bytes(),source)
        self.assertEqual(list(recorder.recording_root(server.DB).rglob('*')),before)
        self.assertEqual(self.call('/api/recorder-release',dict(token=take['token']))[0],200)
        self.assertEqual(self.call('/api/recorder-status?token='+take['token'])[0],400)
        formal=self.capture();path=self.service.file(self.service._find(server.DB,formal['token']))
        self.assertTrue(path.is_file());self.assertEqual(self.call('/api/recorder-release',dict(token=formal['token']))[0],400);self.assertTrue(path.is_file())

    def test_trial_preview_range_and_new_test_releases_previous_buffer(self):
        first=self.capture(trial=True);data,name=self.service.playback(server.DB,first['token'])
        class Handler:
            headers={'Range':'bytes=0-43'}
            def __init__(self):self.wfile=io.BytesIO();self.response_headers={}
            def send_response(self,code):self.code=code
            def send_header(self,key,value):self.response_headers[key]=value
            def end_headers(self):pass
        handler=Handler();media_engine.stream_bytes(handler,data,name)
        self.assertEqual(handler.code,206);self.assertEqual(handler.wfile.getvalue(),data[:44])
        second=self.capture(trial=True)
        self.assertNotEqual(first['token'],second['token'])
        self.assertEqual(self.call('/api/recorder-status?token='+first['token'])[0],400)
        self.assertFalse(recorder.recording_root(server.DB).exists())
