import io
import json
import math
import struct
import unittest
import wave
from pathlib import Path
import test_lexicon
import server
import object_media
import language_exchange
import media_engine
from restore_backup import restore

class ObjectMediaTests(unittest.TestCase):
    setUp=test_lexicon.LexiconTests.setUp
    tearDown=test_lexicon.LexiconTests.tearDown
    call=test_lexicon.LexiconTests.call
    undo=test_lexicon.LexiconTests.undo
    word=test_lexicon.LexiconTests.word

    def audio(self):
        p=Path(self.temp.name)/'sample.wav'
        with wave.open(str(p),'wb') as w:
            w.setparams((1,2,8000,0,'NONE','not compressed'));w.writeframes(b''.join(struct.pack('<h',round(math.sin(n*.3)*1000)) for n in range(8000)))
        return p

    def image(self,extension='.png'):
        import av
        import numpy as np
        p=Path(self.temp.name)/('sample'+extension)
        with av.open(str(p),'w',format='image2') as c:
            codec={'.png':'png','.bmp':'bmp','.tiff':'tiff','.jpg':'mjpeg'}[extension]
            s=c.add_stream(codec);s.width=32;s.height=24;s.pix_fmt='yuvj420p' if extension=='.jpg' else 'bgr24' if extension=='.bmp' else 'rgb24'
            frame=av.VideoFrame.from_ndarray(np.full((24,32,3),120,dtype=np.uint8),format='rgb24')
            for packet in s.encode(frame):c.mux(packet)
            for packet in s.encode():c.mux(packet)
        return p

    def add(self,x,path,body=None,kind='lexeme'):
        token=language_exchange.stage(server.DB,path,'object-media-upload')
        current=self.call('/api/object-media?kind='+kind+'&id='+x['id'])[1]
        return self.call('/api/object-media-save',dict(kind=kind,record_id=x['id'],snapshot=[[i['id'],i['revision']] for i in current['items']],token=token,filename=path.name,body=body or {}))

    def test_audio_speaker_target_undo_and_scope(self):
        x=self.word();pid=self.call('/api/timeline-speaker-save',dict(name='speaker',metadata={}))[1]['id']
        code,r=self.add(x,self.audio(),dict(speakers=[pid],target_id=x['body']['variants'][0]['id'],start_ms=100,end_ms=900));self.assertEqual(code,200,r)
        data=self.call('/api/object-media?kind=lexeme&id='+x['id'])[1];item=data['items'][0]
        with server.connect(audit=False) as db:
            original=media_engine.resolve(server.DB,item['asset']);self.assertEqual(original.read_bytes(),self.audio().read_bytes());self.assertTrue(media_engine.playable(server.DB,item['asset']).is_file())
        self.assertEqual(item['body']['speakers'],[pid]);self.assertEqual(self.undo()[0],200);self.assertEqual(self.call('/api/object-media?kind=lexeme&id='+x['id'])[1]['items'],[]);self.assertEqual(self.undo('redo')[0],200)
        payload=dict(kind='lexeme',record_id=x['id'],snapshot=[],asset_id=item['asset_id'],body={})
        self.assertEqual(self.call('/api/object-media-save',payload)[0],400)
        payload['_language']='other';self.assertEqual(self.call('/api/object-media-save',payload)[0],400)
        fresh=self.call('/api/lexeme?id='+x['id'])[1];fresh['body']['variants']=[]
        self.assertEqual(self.call('/api/lexeme-save',dict(id=x['id'],revision=fresh['revision'],headword=x['headword'],body=fresh['body']))[0],400)
        p=self.call('/api/timeline-catalog')[1]['speakers'][0]
        self.assertEqual(self.call('/api/timeline-speaker-delete',dict(record_id=p['id'],revision=p['revision'],confirmed=True))[0],400)

    def test_image_formats_and_failed_save_no_orphan(self):
        x=self.word()
        for ext in ['.png','.bmp','.tiff','.jpg']:
            code,r=self.add(x,self.image(ext));self.assertEqual(code,200,r)
        files=list((server.DB.parent/'media').iterdir());code,r=self.add(x,self.audio(),dict(start_ms=2000,end_ms=3000));self.assertEqual(code,400,r);self.assertEqual(list((server.DB.parent/'media').iterdir()),files)
        bad=Path(self.temp.name)/'bad.png';bad.write_bytes(b'not image');self.assertEqual(self.add(x,bad)[0],400)

    def test_backup_and_language_package_roundtrip(self):
        x=self.word();pid=self.call('/api/timeline-speaker-save',dict(name='speaker',metadata={}))[1]['id']
        self.assertEqual(self.add(x,self.audio(),dict(speakers=[pid],target_id=x['body']['variants'][0]['id']))[0],200)
        self.assertEqual(self.add(x,self.image())[0],200)
        backup=self.call('/api/backup')[1];self.assertEqual(len(backup['object_media_files']),2)
        source=Path(self.temp.name)/'backup.json';source.write_text(json.dumps(backup),encoding='utf-8');old=server.DB;destination=Path(self.temp.name)/'restored'/'corpus.sqlite3';destination.parent.mkdir();restore(source,destination)
        server.DB=destination
        with server.connect(audit=False) as db:
            for i in object_media.listing(db,'lexeme',x['id'])['items']:self.assertTrue(media_engine.resolve(server.DB,i['asset']).is_file())
        server.DB=old
        with server.connect(audit=False) as db:package=language_exchange.prepare(db,server.DB,'ordos',False)
        path=language_exchange.staged(server.DB,package['token'],'export');self.assertEqual(package['included_media'],2)
        with server.connect() as db:
            result=language_exchange.import_new(db,server.DB,path,'Imported',[])
            rows=list(db.execute('SELECT * FROM object_media WHERE language_id=?',(result['language_id'],)));self.assertEqual(len(rows),2)
            for row in rows:
                owner=object_media.owner(db,row['kind'],row['record_id']);self.assertNotEqual(owner['id'],x['id']);asset=server.timeline.media_view(db,row['asset_id']);media_engine.resolve(server.DB,asset)
                body=json.loads(row['body'])
                if body['speakers']:self.assertNotEqual(body['speakers'][0],pid);self.assertIn(body['target_id'],[v['id'] for v in json.loads(owner['body'])['variants']])

    def test_undone_media_is_portable_and_redo_uses_restored_file(self):
        x=self.word();self.assertEqual(self.add(x,self.image())[0],200);self.assertEqual(self.undo()[0],200)
        backup=self.call('/api/backup')[1];self.assertEqual(len(backup['object_media_files']),1)
        source=Path(self.temp.name)/'undone.json';source.write_text(json.dumps(backup),encoding='utf-8')
        destination=Path(self.temp.name)/'undone-restored'/'corpus.sqlite3';destination.parent.mkdir();restore(source,destination);server.DB=destination
        self.assertEqual(self.undo('redo')[0],200)
        item=self.call('/api/object-media?kind=lexeme&id='+x['id'])[1]['items'][0]
        path=media_engine.resolve(server.DB,item['asset']);self.assertTrue(path.is_relative_to(destination.parent))

    def test_independent_and_delete_cleanup(self):
        code,e=self.call('/api/example-save',dict(language_id='ordos',body={'ipa':'sample','words':[],'translation':''}));self.assertEqual(code,200,e)
        self.assertEqual(self.add(e,self.audio(),kind='independent')[0],200)
        self.assertEqual(self.add(e,self.image(),kind='independent')[0],400)
        x=self.word();self.assertEqual(self.add(x,self.image())[0],200)
        code,r=self.call('/api/lexeme-delete',dict(id=x['id'],revision=x['revision'],confirmed=True));self.assertEqual(code,200,r)
        with server.connect(audit=False) as db:self.assertFalse(db.execute('SELECT 1 FROM object_media WHERE record_id=?',(x['id'],)).fetchone())
        self.assertEqual(self.undo()[0],200)
        self.assertEqual(len(self.call('/api/object-media?kind=lexeme&id='+x['id'])[1]['items']),1)

if __name__=='__main__':unittest.main()
