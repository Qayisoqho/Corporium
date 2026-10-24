import base64
import io
import json
import unittest
import zipfile
from pathlib import Path
import test_lexicon
import server
import excel_exchange as x

class ExcelTests(unittest.TestCase):
    setUp=test_lexicon.LexiconTests.setUp
    tearDown=test_lexicon.LexiconTests.tearDown
    call=test_lexicon.LexiconTests.call
    undo=test_lexicon.LexiconTests.undo

    def action(self,action,**b):
        code,r=self.call('/api/excel-'+action,b);self.assertEqual(code,200,r);return r

    def upload(self,sheets):return self.action('inspect',data=base64.b64encode(x.workbook(sheets)).decode())

    def config(self,index=0,**kw):return dict(index=index,title='导入文本',start=2,mappings=[dict(column=1,target='form'),dict(column=2,target='gloss'),dict(column=3,target='ipa')],**kw)

    def import_plan(self,upload,configs):
        b=dict(token=upload['token'],sheets=configs);p=self.action('preview',**b)
        return self.action('import',**b,signature=p['signature'])

    def test_sparse_alignment_no_translation_and_undo(self):
        u=self.upload([('test',[['Morph','Gloss','IPA'],['a','','ɑ'],['','GEN','n'],[],[],['b','B','b']])]);c=self.config()
        p=self.action('preview',token=u['token'],sheets=[c]);self.assertEqual(p['texts'][0]['sentences'],2);self.assertEqual(p['texts'][0]['partial'],2)
        result=self.import_plan(u,[c]);self.assertEqual(result['count'],2)
        with server.connect(audit=False) as db:
            b=json.loads(db.execute('SELECT body FROM entries ORDER BY position').fetchone()[0]);self.assertEqual(b['ipa'],'ɑ n');self.assertEqual(b['translation'],'');self.assertEqual([(w['form'],w['gloss']) for w in b['words']],[('a',''),('','GEN')]);self.assertEqual(db.execute('SELECT COUNT(*) FROM languages').fetchone()[0],1)
        self.assertEqual(self.undo()[0],200)
        with server.connect(audit=False) as db:self.assertEqual(db.execute('SELECT COUNT(*) FROM texts').fetchone()[0],0)
        self.assertEqual(self.undo('redo')[0],200)

    def test_layers_sentence_join_word_alignment_and_validation(self):
        wl=self.call('/api/layer-save',dict(name='词层',font='Junicode',anchor='word'))[1]['id'];sl=self.call('/api/layer-save',dict(name='句层',font='Junicode',anchor='ipa'))[1]['id']
        u=self.upload([('s',[['m','g','ipa','w','s'],['a','A','a','甲','一'],['b','B','b','','二'],['','','c','丙','']])]);c=self.config();c['mappings'] += [dict(column=4,target=wl),dict(column=5,target=sl,separator='\n')]
        r=self.import_plan(u,[c])
        with server.connect(audit=False) as db:
            rid=db.execute('SELECT id FROM entries').fetchone()[0];d=x.annotations.get(db,'corpus',rid)
            self.assertEqual(len(d['words']),3);self.assertEqual(sorted(v['value'] for v in d['cells']),sorted(['甲','丙','一\n二']))
        foreign=self.call('/api/save-language',dict(name='外语',metadata={}))[1]['id']
        self.assertEqual(self.call('/api/excel-preview',dict(token=u['token'],sheets=[c],_language=foreign))[0],400)
        self.assertEqual(self.call('/api/excel-export',dict(ids=r['ids'],_language=foreign))[0],400)

    def test_all_sheets_validate_before_writes_and_signature(self):
        u=self.upload([('a',[['m','g','i'],['a','b','c']]),('b',[['m','g','i'],['d','e','f']])]);a=self.config();b=self.config(1)
        p=self.action('preview',token=u['token'],sheets=[a,b]);b['mappings'][1]['target']='ipa'
        self.assertEqual(self.call('/api/excel-import',dict(token=u['token'],sheets=[a,b],signature=p['signature']))[0],400)
        with server.connect(audit=False) as db:self.assertEqual(db.execute('SELECT COUNT(*) FROM texts').fetchone()[0],0)
        a['title']='changed';self.assertEqual(self.call('/api/excel-import',dict(token=u['token'],sheets=[a],signature=p['signature']))[0],400)

    def test_roundtrip_empty_sentences_slots_literals_and_sheet_names(self):
        rows=[['SentenceID','WordIndex','Morph','Gloss','IPA','Translation','Notes'],['1','1','=abc','[x]','a\nb','译','备注'],['1','2','','','','',''],[],['2','0','','','','',''],[],['3','1','z','Z','','','']]
        u=self.upload([('a/b'*20,rows),('a/b'*20,rows)])
        c=dict(index=0,title='a/b'*20,start=2,sentence_column=1,slot_column=2,mappings=[dict(column=i,target=t) for i,t in enumerate(['form','gloss','ipa','translation','notes'],3)])
        r=self.import_plan(u,[c,{**c,'index':1}]);e=self.action('export',ids=r['ids']);raw=base64.b64decode(e['data']);s=x.read(io.BytesIO(raw));self.assertEqual(len(s),2);self.assertNotEqual(s[0]['name'],s[1]['name']);self.assertEqual(s[0]['rows'][2][3],'=abc')
        u2=self.action('inspect',data=e['data']);r2=self.import_plan(u2,[c]);
        with server.connect(audit=False) as db:
            bodies=[json.loads(row[0]) for row in db.execute('SELECT body FROM entries WHERE text_id=? ORDER BY position',(r2['ids'][0],))];self.assertEqual([len(b['words']) for b in bodies],[2,0,1]);self.assertEqual(bodies[0]['ipa'],'a\nb')
        zipped=self.action('export',ids=r['ids'],separate=True)
        with zipfile.ZipFile(io.BytesIO(base64.b64decode(zipped['data']))) as z:self.assertEqual(len(z.namelist()),2)

    def test_sample_without_translation(self):
        from public_fixtures import excel_without_translation
        u=self.action('inspect',data=base64.b64encode(excel_without_translation()).decode());c=dict(index=0,title='合成无译文工作表',start=2,mappings=[dict(column=4,target='ipa'),dict(column=5,target='form'),dict(column=6,target='gloss'),dict(column=7,target='notes')])
        p=self.action('preview',token=u['token'],sheets=[c]);self.assertGreater(p['texts'][0]['sentences'],10);r=self.import_plan(u,[c]);e=self.action('export',ids=r['ids']);self.assertTrue(e['data'])
        with server.connect(audit=False) as db:
            bodies=[json.loads(row[0]) for row in db.execute('SELECT body FROM entries')];self.assertTrue(all(b['translation']=='' for b in bodies));self.assertTrue(bodies[0]['ipa'].startswith('synthetic0 ipa'))

    def test_desktop_save_as_cancel_and_project_scope(self):
        from unittest.mock import Mock,patch
        import desktop,types
        u=self.upload([('s',[['m','g','i'],['a','A','ɑ']])]);r=self.import_plan(u,[self.config()]);e=self.action('export',ids=r['ids'])
        dest=Path(self.temp.name)/'chosen-folder';dest.mkdir();dest=dest/'自定义文件名.xlsx'
        bridge=desktop.Bridge(None);bridge._origin='http://127.0.0.1:123';bridge._window=Mock();bridge._window.get_current_url.return_value=bridge._origin+'/'
        with patch.dict('sys.modules',webview=types.SimpleNamespace(FileDialog=types.SimpleNamespace(SAVE=1))):
            bridge._window.create_file_dialog.return_value=None
            self.assertTrue(bridge.save_excel_export(e['token'],e['name'])['cancelled']);self.assertFalse(dest.exists())
            bridge._window.create_file_dialog.return_value=[str(dest)]
            result=bridge.save_excel_export(e['token'],e['name']);self.assertTrue(result.get('ok'),result);self.assertEqual(dest.read_bytes(),base64.b64decode(e['data']))
            self.assertIn('xlsx',bridge._window.create_file_dialog.call_args.kwargs['file_types'][0])
            old=server.DB
            try:
                server.DB=Path(self.temp.name)/'another.sqlite3'
                self.assertIn('error',bridge.save_excel_export(e['token'],e['name']))
            finally:server.DB=old

if __name__=='__main__':unittest.main()

