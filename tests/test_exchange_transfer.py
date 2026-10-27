import copy
import json
import unittest
import io
import zipfile
from pathlib import Path
import test_annotations
import test_lexicon
import server
import language_exchange
import media_engine

class ExchangeTransferTests(test_annotations.AnnotationTests):
    # Reuse fixture helpers, run these focused tests independently of inherited cases.
    link=test_lexicon.LexiconTests.link
    def snap(self,kind,e):return self.call('/api/word-transfer-snapshot?kind='+kind+'&id='+e['id'])[1]
    def payload(self,s,t,mode='move'):
        return dict(source=dict(kind=s['kind'],id=s['id'],token=s['transfer_token']),target=dict(kind=t['kind'],id=t['id'],token=t['transfer_token']),slots=[s['words'][0]['id']],mode=mode,confirmed=True,position=len(t['words']))
    def empty(self):
        source=self.entries()[0]
        r=self.call('/api/add',dict(text_id=source['text_id']))[1]
        return next(e for e in self.entries() if e['id']==r['id'])
    def test_transfer_corpus_links_layers_and_atomic_undo(self):
        s=self.seed();x=self.word();self.link(s['words'][0]['unit_id'],x);self.link(s['words'][0]['morphemes'][0]['unit_id'],x)
        layer=self.layer();self.annotate('corpus',s,layer);t=self.empty();a=self.snap('corpus',s);z=self.snap('corpus',t)
        code,r=self.call('/api/word-transfer',self.payload(a,z));self.assertEqual(code,200,r)
        after=self.snap('corpus',t);self.assertEqual(after['body']['words'][-1]['form'],a['body']['words'][0]['form']);self.assertEqual(after['cells'][0]['value'],'NOUN');self.assertFalse(after['orphaned'])
        with server.connect() as db:
            self.assertEqual(db.execute('SELECT COUNT(*) FROM lexical_links l JOIN corpus_units u ON u.id=l.unit_id WHERE u.entry_id=? AND u.active=1',(t['id'],)).fetchone()[0],2)
        self.assertEqual(len(self.snap('corpus',s)['words']),len(a['words'])-1)
        self.assertEqual(self.undo()[0],200);self.assertEqual(self.snap('corpus',s)['words'],a['words']);self.assertEqual(self.snap('corpus',t)['words'],z['words'])
        self.assertEqual(self.undo('redo')[0],200)
    def test_transfer_cross_kind_roundtrip(self):
        s=self.seed();x=self.word();self.link(s['words'][0]['unit_id'],x);self.link(s['words'][0]['morphemes'][0]['unit_id'],x);t=self.example(x)
        a=self.snap('corpus',s);z=self.snap('independent',t);p=self.payload(a,z,'copy');self.assertEqual(self.call('/api/word-transfer',p)[0],200)
        z=self.snap('independent',t);self.assertEqual(len(z['body']['targets']),3)
        t2=self.empty();p=self.payload(z,self.snap('corpus',t2),'copy');p['slots']=[z['words'][-1]['id']]
        code,r=self.call('/api/word-transfer',p);self.assertEqual(code,200,r)
        with server.connect() as db:self.assertEqual(db.execute('SELECT COUNT(*) FROM lexical_links l JOIN corpus_units u ON u.id=l.unit_id WHERE u.entry_id=?',(t2['id'],)).fetchone()[0],2)
    def test_transfer_stale_and_cross_language_rollback(self):
        s=self.seed();t=self.empty();a=self.snap('corpus',s);z=self.snap('corpus',t);p=self.payload(a,z);p['target']['token']='stale'
        self.assertEqual(self.call('/api/word-transfer',p)[0],400);self.assertEqual(self.snap('corpus',s)['words'],a['words'])
        p=self.payload(a,z);p['position']=999;self.assertEqual(self.call('/api/word-transfer',p)[0],400)
        lid=self.call('/api/save-language',dict(name='Other',metadata={}))[1]['id']
        with server.connect() as db:db.execute('UPDATE texts SET language_id=? WHERE id=?',(lid,t['text_id']))
        p=self.payload(a,self.snap('corpus',t));self.assertEqual(self.call('/api/word-transfer',p)[0],400)
    def test_transfer_new_empty_source_and_undo(self):
        s=self.seed();a=self.snap('corpus',s);p=self.payload(a,a);p['target']={'kind':'corpus','new':True};p['slots']=[w['id'] for w in a['words']];p['position']=0
        code,r=self.call('/api/word-transfer',p);self.assertEqual(code,200,r)
        self.assertEqual(self.snap('corpus',s)['words'],[]);self.assertEqual(self.snap('corpus',{'id':r['target']['id']})['body']['ipa'],'')
        self.assertEqual(self.undo()[0],200);self.assertEqual(self.snap('corpus',s)['words'],a['words'])
    def test_package_new_name_conflict_and_remap(self):
        self.seed();self.word();code,p=self.call('/api/language-package-export',dict(_language='ordos'));self.assertEqual(code,200,p)
        path=language_exchange.staged(server.DB,p['token'],'export');token=language_exchange.stage(server.DB,path,'import')
        code,r=self.call('/api/language-package-import',dict(token=token,name=p['name']));self.assertEqual(code,400,r)
        code,r=self.call('/api/language-package-import',dict(token=token,name='Imported'));self.assertEqual(code,200,r)
        lid=r['language_id'];b=self.call('/api/export-language?language='+lid)[1];original=self.call('/api/export-language?language=ordos')[1]
        self.assertEqual(len(b['texts']),1);self.assertNotEqual(b['texts'][0]['id'],original['texts'][0]['id']);self.assertEqual(len(b['lexemes']),1)
        self.assertEqual(self.call('/api/language-package-import',dict(token=token,name=' imported '))[0],400)
        with server.connect() as db:self.assertEqual(db.execute('SELECT COUNT(*) FROM languages WHERE name=?',('Imported',)).fetchone()[0],1)
    def test_package_failure_rolls_back_language(self):
        self.seed();b=self.call('/api/export-language?language=ordos')[1];b['texts'][0]['entries'][0]['body']='invalid'
        p=Path(self.temp.name)/'bad.json';p.write_text(json.dumps(b),encoding='utf-8');token=language_exchange.stage(server.DB,p,'import')
        code,r=self.call('/api/language-package-import',dict(token=token,name='Failure'));self.assertEqual(code,400,r)
        with server.connect() as db:self.assertFalse(db.execute('SELECT 1 FROM languages WHERE name=?',('Failure',)).fetchone())
    def test_package_media_roundtrip(self):
        import wave
        p=Path(self.temp.name)/'sample.wav'
        with wave.open(str(p),'wb') as w:w.setnchannels(1);w.setsampwidth(2);w.setframerate(8000);w.writeframes(b'\0\0'*800)
        with server.connect() as db:
            import timeline
            asset=dict(name=p.name,path=str(p),storage='link',metadata=dict(fingerprint=media_engine.fingerprint(p),duration_ms=100))
            timeline.mutate(db,'ordos','create',dict(name='Media'),asset)
        code,r=self.call('/api/language-package-export',dict(include_media=True));self.assertEqual(code,200,r);self.assertEqual(r['included_media'],1)
        path=language_exchange.staged(server.DB,r['token'],'export');token=language_exchange.stage(server.DB,path,'import')
        code,r=self.call('/api/language-package-import',dict(token=token,name='Media copy'));self.assertEqual(code,200,r)
        with server.connect() as db:
            asset=dict(db.execute('SELECT * FROM timeline_media WHERE language_id=?',(r['language_id'],)).fetchone());self.assertEqual(media_engine.resolve(server.DB,asset).read_bytes(),p.read_bytes())


    def test_circumfix_multi_selection_and_stale_link(self):
        import test_segmentation
        source='#pass([], (([we-amos-la],[pst-go-pst]),([home],[N])), [])'
        s=self.seed(source)
        d=self.call('/api/segmentation?kind=corpus&id='+s['id'])[1]
        code,r=self.call('/api/segmentation-save',dict(kind='corpus',id=s['id'],revision=d['revision'],action='save',word=0,members=['0:host','2:host'],type='circumfix',status='confirmed',gloss='PST'))
        self.assertEqual(code,200,r)
        t=self.empty();a=self.snap('corpus',s);z=self.snap('corpus',t);p=self.payload(a,z,'copy');p['slots']=[w['id'] for w in reversed(a['words'])]
        code,r=self.call('/api/word-transfer',p);self.assertEqual(code,200,r)
        after=self.snap('corpus',t);self.assertEqual([w['form'] for w in after['body']['words'][-2:]],['we-amos-la','home']);self.assertEqual(after['body']['words'][-2]['morph_groups'],a['body']['words'][0]['morph_groups'])
        self.assertEqual(after['body']['words'][-2]['group_reviews'],[])
        p=self.payload(a,self.snap('corpus',t));x=self.word();current=self.entries()[0];self.link(current['words'][1]['unit_id'],x)
        self.assertEqual(self.call('/api/word-transfer',p)[0],400)
    def test_desktop_save_picker_writes_selected_file(self):
        from unittest.mock import Mock,patch
        import desktop,types
        self.seed();p=self.call('/api/language-package-export',dict(_language='ordos'))[1]
        dest=Path(self.temp.name)/'Chosen.corporium'
        bridge=desktop.Bridge(None);bridge._origin='http://127.0.0.1:123';bridge._window=Mock();bridge._window.get_current_url.return_value=bridge._origin+'/'
        bridge._window.create_file_dialog.return_value=[str(dest)]
        with patch.dict('sys.modules',webview=types.SimpleNamespace(FileDialog=types.SimpleNamespace(SAVE=1))):
            r=bridge.save_language_package(p['token'],'Chosen.corporium')
        self.assertTrue(r.get('ok'),r);self.assertEqual(language_exchange.read(dest)['language']['id'],'ordos')
        self.assertEqual(bridge._window.create_file_dialog.call_args.args,(1,))
