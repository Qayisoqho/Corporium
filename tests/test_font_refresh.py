import hashlib
import os
import tempfile
import unittest
from pathlib import Path
from urllib.parse import urlparse,parse_qs
from unittest.mock import patch
import font_catalog
import server


class FontRefreshTests(unittest.TestCase):
    def setUp(self):
        self.state=(font_catalog.ROOT,font_catalog._catalog,font_catalog._files,font_catalog._signature)
        self.temp=tempfile.TemporaryDirectory();font_catalog.ROOT=Path(self.temp.name)
        self.data=(font_catalog.ASSET_ROOT/'Junicode/Junicode.ttf').read_bytes()

    def tearDown(self):
        font_catalog.ROOT,font_catalog._catalog,font_catalog._files,font_catalog._signature=self.state
        self.temp.cleanup()

    def write(self,data):
        path=font_catalog.ROOT/'Junicode/Junicode.ttf';path.parent.mkdir(parents=True,exist_ok=True);path.write_bytes(data);return path

    def face(self,data):return data['families'][0]['faces'][0]

    def call(self,path):
        handler=object.__new__(server.Handler);handler.path=path;handler.headers={};result=[]
        handler.send=lambda data,code=200,mime=None:result.append((code,data,mime))
        with patch('server.connect',side_effect=AssertionError('Font reads must not open a corpus database')):handler.do_GET()
        return result[0]

    def test_overwrite_changes_url_without_changing_saved_family_identity(self):
        path=self.write(self.data);first=font_catalog.scan(True);original=self.face(first)
        second_data=self.data+b'new revision';self.write(second_data);second=font_catalog.scan()
        self.assertEqual(first['families'][0]['id'],second['families'][0]['id']);self.assertNotEqual(original['url'],self.face(second)['url'])
        old=parse_qs(urlparse(original['url']).query);new=parse_qs(urlparse(self.face(second)['url']).query)
        self.assertEqual(old['id'],new['id']);self.assertEqual(new['v'][0],hashlib.sha256(second_data).hexdigest())
        self.assertEqual(font_catalog.font_file(new['id'][0],new['v'][0])[0],second_data)
        with self.assertRaisesRegex(ValueError,'已更新'):font_catalog.font_file(old['id'][0],old['v'][0])
        self.assertEqual(font_catalog.font_file(new['id'][0])[0],second_data)  # Legacy unversioned callers.

    def test_explicit_scan_rechecks_contents_even_if_metadata_is_unchanged(self):
        self.write(self.data+b'one')
        with patch('font_catalog.file_stamp',return_value=('unchanged',)):
            first=font_catalog.scan(True);self.write(self.data+b'two');second=font_catalog.scan(True)
        self.assertNotEqual(self.face(first)['url'],self.face(second)['url'])

    def test_updated_face_takes_priority_over_older_copies_in_other_folders(self):
        updated=self.write(self.data+b'updated');older=font_catalog.ROOT/'z-old-copy.ttf';older.write_bytes(self.data)
        os.utime(older,ns=(1_000_000_000,1_000_000_000))
        catalog=font_catalog.scan(True);faces=catalog['families'][0]['faces'];self.assertEqual(len(faces),2)
        query=parse_qs(urlparse(faces[-1]['url']).query)
        self.assertEqual(font_catalog.font_file(query['id'][0],query['v'][0])[0],self.data+b'updated')
        self.assertTrue(older.exists());self.assertTrue(updated.exists())

    def test_file_removed_during_scan_does_not_leave_a_partial_catalogue(self):
        path=self.write(self.data);inspect=font_catalog.inspect_font
        def remove_after_inspection(p,data):
            result=inspect(p,data);p.unlink();return result
        with patch('font_catalog.inspect_font',side_effect=remove_after_inspection):catalog=font_catalog.scan(True)
        self.assertEqual(catalog['file_count'],0);self.assertFalse(catalog['families']);self.assertTrue(catalog['errors'])
        self.write(self.data);self.assertEqual(font_catalog.scan()['file_count'],1)

    def test_add_remove_and_project_switch_invalidate_the_catalogue(self):
        self.write(self.data+b'first');first=font_catalog.scan(True)
        with tempfile.TemporaryDirectory() as other:
            font_catalog.ROOT=Path(other);path=self.write(self.data+b'other');second=font_catalog.scan()
            self.assertNotEqual(self.face(first)['url'],self.face(second)['url']);self.assertEqual(first['families'][0]['id'],second['families'][0]['id'])
            extra=path.with_name('Copy.ttf');extra.write_bytes(self.data);self.assertEqual(font_catalog.scan()['file_count'],2)
            path.unlink();extra.unlink();self.assertEqual(font_catalog.scan()['file_count'],0)

    def test_builtin_aliases_have_content_versions_and_update_with_the_same_file(self):
        self.write(self.data);first=font_catalog.scan(True)
        normal=next(f for f in first['builtins'] if f['family']=='Junicode' and f['style']=='normal' and f['weight']=='400')
        self.write(self.data+b'updated');second=font_catalog.scan()
        current=next(f for f in second['builtins'] if f['family']=='Junicode' and f['style']=='normal' and f['weight']=='400')
        self.assertNotEqual(normal['url'],current['url']);self.assertEqual(self.call(current['url'])[:2],(200,self.data+b'updated'))
        self.assertEqual(self.call(normal['url'])[0],400)
        ipa=next(f for f in second['builtins'] if f['family']=='IPAPANNEW')
        self.assertEqual(self.call(ipa['url'])[:2],(200,self.data))  # Bundled fallback is unchanged.

    def test_api_rescan_and_versioned_files_are_read_only(self):
        self.write(self.data);code,first,_=self.call('/api/fonts');self.assertEqual(code,200)
        self.write(self.data+b'new');code,second,_=self.call('/api/fonts?refresh=true');self.assertEqual(code,200)
        self.assertNotEqual(self.face(first)['url'],self.face(second)['url'])
        code,data,mime=self.call(self.face(second)['url']);self.assertEqual((code,data,mime),(200,self.data+b'new','font/ttf'))
        self.assertEqual(self.call('/api/font-file?id=../server.py')[0],400)
