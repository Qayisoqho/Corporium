import tempfile
import shutil
import unittest
from pathlib import Path
import font_catalog

class FontTests(unittest.TestCase):
    def test_nested_discovery_invalid_file_and_safe_access(self):
        old=font_catalog.ROOT
        with tempfile.TemporaryDirectory() as temp:
            try:
                root=Path(temp);(root/'nested').mkdir()
                shutil.copyfile(old/'Junicode/Junicode.ttf',root/'nested'/'renamed.ttf')
                (root/'bad.otf').write_bytes(b'bad font')
                font_catalog.ROOT=root
                data=font_catalog.scan(True)
                self.assertEqual(data['file_count'],1)
                self.assertEqual(data['families'][0]['name'],'Junicode')
                self.assertEqual(len(data['errors']),1)
                fid=data['families'][0]['faces'][0]['url'].split('=')[1]
                self.assertTrue(font_catalog.font_file(fid)[0])
                with self.assertRaises(ValueError):font_catalog.font_file('../server.py')
                self.assertTrue(font_catalog.valid_font(data['families'][0]['id']))
                self.assertFalse(font_catalog.valid_font('evil";color:red'))
                (root/'nested'/'renamed.ttf').unlink()
                self.assertEqual(font_catalog.scan(True)['file_count'],0)
                with self.assertRaises(ValueError):font_catalog.font_file(fid)
            finally:
                font_catalog.ROOT=old;font_catalog.scan(True)

    def test_font_family_styles(self):
        data=font_catalog.scan(True)
        junicode=next(f for f in data['families'] if f['name']=='Junicode')
        self.assertEqual({f['style'] for f in junicode['faces']},{'normal','italic'})
