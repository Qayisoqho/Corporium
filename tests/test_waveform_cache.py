import base64
from fractions import Fraction
import json
from pathlib import Path
import tempfile
import threading
import time
import unittest
from unittest.mock import patch
import wave

import numpy as np
import media_engine
import waveform_cache as wc


class WaveformTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.folder = Path(self.temp.name)
        self.db = self.folder / 'corpus.sqlite3'
        self.path = self.folder / 'native.wav'
        self.rate = 48000
        t = np.arange(self.rate*6)/self.rate
        self.original = np.stack([.4*np.sin(2*np.pi*12000*t),.2*np.sin(2*np.pi*317*t)],axis=1)
        self.original[1234,0] = .95
        self.pcm = np.rint(self.original*32767).astype('<i2')
        with wave.open(str(self.path),'wb') as output:
            output.setparams((2,2,self.rate,0,'NONE','not compressed'))
            output.writeframes(self.pcm.tobytes())
        self.asset = dict(path=str(self.path), storage='link', metadata=media_engine.probe(self.path))
        self.key = media_engine.cache_key(self.asset)
        self.overview = wc.overview_path(self.db,self.key)
        wc.build(self.db,self.key,self.path,self.asset['metadata'],lambda *_:None)

    def tearDown(self):
        manager = wc.cache(self.db)
        manager.pending = None
        for _ in range(300):
            if not manager.prefetching:
                break
            time.sleep(.01)
        self.temp.cleanup()

    def data(self,a,z,pixels=1200,compact=False):
        return media_engine.wave_data(self.db,self.asset,a,z,pixels,compact)

    def test_native_samples_preserve_high_frequency_stereo_and_seek_position(self):
        result = self.data(3025,3030)
        self.assertEqual(result['mode'],'samples')
        self.assertEqual(result['sample_rate'],48000)
        self.assertEqual(len(result['channels']),2)
        expected=self.pcm[145200:145440].T.astype(np.float32)/32768
        np.testing.assert_array_equal(np.array(result['channels']),expected)
        self.assertAlmostEqual(result['step_ms'],1000/48000)

    def test_peak_pyramid_keeps_spike_and_channel_separation(self):
        result=self.data(0,6000,100)
        peaks=np.array(result['channels'])
        self.assertGreater(peaks[0,:,1].max(),.94)
        self.assertLess(peaks[1,:,1].max(),.21)
        manifest=json.loads((self.overview/'manifest.json').read_text())
        self.assertEqual(manifest['base'],64)
        self.assertGreater(len(manifest['levels']),8)
        for level in range(len(manifest['levels'])-1):
            child=np.load(self.overview/f'{level}.npy')
            parent=np.load(self.overview/f'{level+1}.npy')
            self.assertEqual(parent[0,0,0],child[:2,0,0].min())
            self.assertEqual(parent[0,0,1],child[:2,0,1].max())

    def test_submillisecond_peak_bins_match_original_samples_across_tile_boundary(self):
        result=self.data(1997,2004,100)
        self.assertLess(result['step_ms'],.1)
        step=round(result['step_ms']*self.rate/1000)
        values=self.pcm[round(result['start_ms']*48):2004*48].astype(np.float32)/32768
        for n,pairs in enumerate(result['channels']):
            for i,(lo,hi) in enumerate(pairs):
                expected=values[i*step:(i+1)*step,n]
                self.assertAlmostEqual(lo,float(expected.min()),delta=2/32767)
                self.assertAlmostEqual(hi,float(expected.max()),delta=2/32767)

    def test_compact_wire_format_is_bounded_and_decodes_without_rounding_samples(self):
        for end in [5,350,6000]:
            result=self.data(0,end,1300,True)
            values=np.frombuffer(base64.b64decode(result['values']),dtype='<f4' if result['mode']=='samples' else '<i2')
            self.assertEqual(len(values),result['count']*2*(1 if result['mode']=='samples' else 2))
            self.assertLessEqual(result['count'],1301)
            self.assertLess(len(result['values']),30000)

    def test_cache_hit_uses_tile_without_opening_or_decoding_source_again(self):
        with patch.object(wc,'prefetch'):
            before=self.data(3000,3005)
            with patch.object(wc,'decode_tile',side_effect=AssertionError('unexpected decode')):
                self.assertEqual(before,self.data(3000,3005))
        self.assertLessEqual(wc.settings(self.db)['memory_bytes'],96*wc.MIB)

    def test_settings_are_validated_persisted_and_keep_projects_separate(self):
        self.assertEqual(wc.settings(self.db)['memory_mb'],128)
        self.assertEqual(wc.settings(self.db)['disk_mb'],2048)
        wc.settings(self.db,dict(memory_mb=32,disk_mb=64))
        self.assertEqual(wc.settings(self.db)['browser_bytes'],8*wc.MIB)
        other=self.folder/'other'/'corpus.sqlite3'
        self.assertEqual(wc.settings(other)['memory_mb'],128)
        with wc._guard:
            wc._managers.pop(str(wc.cache(self.db).root))
        self.assertEqual(wc.settings(self.db)['memory_mb'],32)
        for value in [True,0,15,4097,128.5,'128']:
            with self.assertRaises(ValueError):
                wc.settings(self.db,dict(memory_mb=value,disk_mb=2048))

    def test_memory_lru_obeys_budget_and_protects_recent_tiles(self):
        manager=wc.cache(self.db)
        wc.settings(self.db,dict(memory_mb=16,disk_mb=64))
        arrays=[np.full(1024*1024,i,dtype=np.float32) for i in range(5)]
        for i,value in enumerate(arrays[:3]):manager.put(str(i),value)
        manager.get('0')
        manager.put('3',arrays[3])
        self.assertIsNone(manager.get('1'))
        self.assertIsNotNone(manager.get('0'))
        self.assertLessEqual(manager.memory_bytes,12*wc.MIB)

    def test_disk_eviction_prefers_detail_and_does_not_touch_source_proxy_or_pinned_units(self):
        manager=wc.cache(self.db)
        wc.settings(self.db,dict(memory_mb=16,disk_mb=64))
        detail=self.overview.parent/'detail';detail.mkdir(exist_ok=True)
        old=detail/'old.npy';recent=detail/'recent.npy'
        for path in [old,recent]:
            with path.open('wb') as f:f.truncate(40*wc.MIB)
            manager.register(path,'detail')
        proxy=self.folder/'media-cache'/'keep.mp4';proxy.write_bytes(b'playback')
        with manager.pin(recent):
            with manager.lock:manager.trim()
            self.assertFalse(old.exists());self.assertTrue(recent.exists())
            self.assertTrue((self.overview/'manifest.json').exists())
        self.assertEqual(proxy.read_bytes(),b'playback')
        self.assertTrue(self.path.is_file())
        self.assertLessEqual(wc.settings(self.db)['disk_bytes'],64*wc.MIB)
        legacy=manager.root.parent/('d'*64+'.npz')
        unrelated=manager.root.parent/'not-a-waveform.npz';unrelated.write_bytes(b'keep')
        with legacy.open('wb') as f:f.truncate(80*wc.MIB)
        manager.register(legacy,'legacy')
        with manager.lock:manager.trim()
        self.assertFalse(legacy.exists())
        self.assertTrue((self.overview/'manifest.json').exists())
        self.assertEqual(unrelated.read_bytes(),b'keep')

    def test_cancelled_generation_removes_partial_cache_and_releases_reservation(self):
        key='c'*64
        def cancel(*_):raise ValueError('cancelled')
        with self.assertRaisesRegex(ValueError,'cancelled'):
            wc.build(self.db,key,self.path,self.asset['metadata'],cancel)
        self.assertFalse((wc.overview_path(self.db,key)/'manifest.json').exists())
        self.assertFalse(list(wc.overview_path(self.db,key).parent.glob('.building-*')))
        self.assertEqual(wc.cache(self.db).reserved,0)

    def test_negative_and_outside_view_ranges_do_not_create_large_tiles(self):
        self.assertEqual(self.data(-200,-1)['channels'],[])
        self.assertEqual(self.data(10000,12000)['channels'],[])
        self.assertEqual(self.data(-100,5)['start_ms'],0)
        self.assertLessEqual(len(self.data(5900,100000000,500)['channels'][0]),501)

    def test_evicted_overview_is_rebuilt_by_prepare(self):
        import shutil
        shutil.rmtree(self.overview)
        self.assertFalse(self.data(0,1)['ready'])
        result=media_engine.prepare(self.db,self.asset,'wave')
        for _ in range(500):
            job=media_engine.job_view(self.db,result['job'])
            if job['state'] in ('done','error'):break
            time.sleep(.01)
        self.assertEqual(job['state'],'done',job)
        self.assertTrue(self.data(0,1)['ready'])

    def test_compressed_seek_matches_full_decode_with_timestamp_origin(self):
        import av
        target=self.folder/'seek.m4a'
        with av.open(str(target),'w') as output:
            stream=output.add_stream('aac',rate=self.rate);stream.layout='stereo'
            for a in range(0,len(self.pcm),1024):
                frame=av.AudioFrame.from_ndarray((self.pcm[a:a+1024].T.astype(np.float32)/32768).copy(),format='fltp',layout='stereo')
                frame.sample_rate=self.rate;frame.pts=a;frame.time_base=Fraction(1,self.rate)
                for packet in stream.encode(frame):output.mux(packet)
            for packet in stream.encode(None):output.mux(packet)
        meta=media_engine.probe(target)
        manifest=dict(sample_rate=48000,channel_count=2,frames=6*48000)
        actual=wc.decode_tile(target,meta,manifest,3*48000,240)
        expected=np.zeros((240,2),dtype=np.float32)
        with av.open(str(target)) as container:
            for frame in container.decode(audio=0):
                position=round((frame.time-meta['start_us']/av.time_base)*48000)
                a,z=max(3*48000,position),min(3*48000+240,position+frame.samples)
                if z>a:expected[a-3*48000:z-3*48000]=frame.to_ndarray()[:,a-position:z-position].T
        # AAC's decoder state can differ below one 16-bit step after seeking.
        # A shifted waveform would differ by orders of magnitude more here.
        np.testing.assert_allclose(actual,expected,atol=1/32768)

    def test_audio_offset_and_44100_hz_are_preserved(self):
        rate=44100
        path=self.folder/'offset.wav'
        with wave.open(str(path),'wb') as f:
            f.setparams((1,2,rate,0,'NONE','not compressed'))
            f.writeframes(np.arange(rate,dtype='<i2').tobytes())
        meta=media_engine.probe(path)
        meta.update(start_us=-250000,duration_ms=1250)
        asset=dict(path=str(path),storage='link',metadata=meta)
        key=media_engine.cache_key(asset)
        wc.build(self.db,key,path,meta,lambda *_:None)
        with patch.object(wc,'prefetch'):
            silent=media_engine.wave_data(self.db,asset,0,2)
            real=media_engine.wave_data(self.db,asset,250,252)
        self.assertEqual(real['sample_rate'],44100)
        self.assertTrue(np.all(np.array(silent['channels'])==0))
        # 250 ms falls half-way between two 44.1 kHz samples; timestamps are rounded consistently.
        self.assertGreater(max(real['channels'][0]),.001)
