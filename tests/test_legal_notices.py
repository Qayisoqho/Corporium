from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

import legal_notices
import desktop
import server
import app_info


class LegalNoticesTests(unittest.TestCase):
    def test_catalog_reads_only_bundled_notices_and_plain_text(self):
        with tempfile.TemporaryDirectory() as temp:
            root=Path(temp);folder=root/'licenses';folder.mkdir()
            (folder/legal_notices.APP_LICENSE).write_text('允许使用。',encoding='utf-8')
            (folder/'Other-LICENSE').write_text('<script>not executable</script>',encoding='utf-8')
            (folder/'AUTHORS.pyc').write_bytes(b'not a notice')
            (root/'private.txt').write_text('must not be served',encoding='utf-8')
            with patch.object(legal_notices,'ROOT',root):
                self.assertEqual([r['id'] for r in legal_notices.catalog()['items']],[legal_notices.APP_LICENSE,'Other-LICENSE'])
                self.assertEqual(legal_notices.document(legal_notices.APP_LICENSE)['text'],'允许使用。')
                self.assertEqual(legal_notices.document('Other-LICENSE')['text'],'<script>not executable</script>')
                for name in ('../private.txt','..\\private.txt',str(root/'private.txt'),'AUTHORS.pyc','missing'):
                    with self.subTest(name=name),self.assertRaises(ValueError):legal_notices.document(name)

    def test_source_directory_fallback_and_utf16(self):
        with tempfile.TemporaryDirectory() as temp:
            root=Path(temp);folder=root/'packaging'/'licenses';folder.mkdir(parents=True)
            (folder/'LICENSE.txt').write_text('许可',encoding='utf-16')
            with patch.object(legal_notices,'ROOT',root):
                self.assertEqual(legal_notices.directory(),folder)
                self.assertEqual(legal_notices.document('LICENSE.txt')['text'],'许可')

    def test_viewer_endpoints_need_no_database_and_serve_html_as_html(self):
        for path in ('/licenses','/license-notices.js','/license-notices.css','/licenses/catalog','/licenses/developer-font','/licenses/document?id='+legal_notices.RUNTIME_LICENSE):
            handler=object.__new__(server.Handler);handler.path=path;out=[]
            handler.send=lambda data,code=200,mime='application/json':out.append((code,data,mime))
            with patch.object(server,'connect',side_effect=AssertionError('Legal notices must not touch a project')):
                handler.do_GET()
            self.assertEqual(out[0][0],200,(path,out))
            if path=='/licenses':self.assertTrue(out[0][2].startswith('text/html'))
            if path=='/licenses/developer-font':
                self.assertEqual(out[0][2],'font/ttf')
                self.assertEqual(out[0][1],(server.ROOT/'font/Junicode/Junicode.ttf').read_bytes())
        handler=object.__new__(server.Handler);handler.path='/licenses/document?id=..%2Fdesktop.py';out=[]
        handler.send=lambda data,code=200,mime=None:out.append((code,data));handler.do_GET()
        self.assertEqual(out[0][0],400)

    def test_complete_webview_terms_and_required_notice_are_shipped(self):
        text=legal_notices.document(legal_notices.RUNTIME_LICENSE)['text']
        for part in ('DISTRIBUTABLE CODE','REQUIRED NOTICES TO END USERS','DISCLAIMER OF WARRANTY','EFFET JURIDIQUE'):
            self.assertIn(part,text)
        self.assertGreater(len(text),16000)
        self.assertIn('SmartScreen',legal_notices.document(legal_notices.NOTICES)['text'])
        self.assertIn('https://privacy.microsoft.com',legal_notices.document(legal_notices.NOTICES)['text'])

    def test_release_version_metadata_agrees(self):
        root=Path(__file__).resolve().parents[1]
        self.assertEqual(desktop.VERSION,'0.9.01026.4')
        self.assertEqual(legal_notices.catalog()['about']['version'],desktop.VERSION)
        self.assertEqual(app_info.about()['developer'],'Erči S\u030ca.')
        self.assertEqual(app_info.about()['project_url'],'https://github.com/Qayisoqho/Corporium')
        self.assertEqual(app_info.about()['issues_url'],'https://github.com/Qayisoqho/Corporium/issues')
        iss=(root/'packaging/Corporium.iss').read_text(encoding='utf-8-sig')
        self.assertIn('AppVersion='+desktop.VERSION,iss)
        self.assertIn('Corporium-'+desktop.VERSION+'-Windows-x64-Setup',iss)
        version=(root/'packaging/version.txt').read_text(encoding='utf-8')
        self.assertIn("'ProductVersion','"+desktop.VERSION+"'",version)
        self.assertIn('filevers=(0,9,1026,4)',version)
        self.assertIn('AppId={{D06731DF-0CEC-448C-A02A-77BB3684C3F0}',iss)


if __name__=='__main__':unittest.main()
