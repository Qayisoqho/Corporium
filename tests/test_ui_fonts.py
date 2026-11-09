"""Bundled interface fonts work offline without opening or changing a project."""
import hashlib
from pathlib import Path
from types import SimpleNamespace
import tempfile
import unittest
from unittest.mock import patch
import desktop
import font_catalog
import server


class InterfaceFontTests(unittest.TestCase):
    def call(self, handler_class, path, authenticated=True):
        handler=object.__new__(handler_class)
        handler.path=path
        handler.headers={'Cookie':'corporium=font-test'} if authenticated else {}
        result=[]
        handler.send=lambda data,code=200,mime=None:result.append((code,data,mime))
        with patch('server.connect',side_effect=AssertionError('Interface font reads must not open a corpus')):
            handler.do_GET()
        return result[0]

    def test_original_faces_and_weights_are_available_in_an_empty_project(self):
        with tempfile.TemporaryDirectory() as temp,patch.object(font_catalog,'ROOT',Path(temp)):
            for family,relative,slant,weight in font_catalog.UI_BUILTIN_FILES:
                with self.subTest(relative=relative):
                    path=font_catalog.builtin_path(relative)
                    self.assertTrue(path.is_relative_to(font_catalog.ASSET_ROOT))
                    parsed=font_catalog.inspect_font(path)
                    self.assertEqual((parsed[0],parsed[2],parsed[3]),(family,weight,slant))
                    code,data,mime=self.call(server.Handler,'/font/'+relative)
                    self.assertEqual(code,200)
                    self.assertEqual(hashlib.sha256(data).digest(),hashlib.sha256(path.read_bytes()).digest())
                    self.assertEqual(mime,'font/otf' if relative.endswith('.otf') else 'font/ttf')
                    self.assertTrue(font_catalog.valid_font(family))
            self.assertFalse(list(Path(temp).iterdir()),'Bundled UI fonts must not be copied into a user project')

    def test_project_font_files_cannot_replace_application_interface_assets(self):
        relative=font_catalog.UI_BUILTIN_FILES[0][1]
        with tempfile.TemporaryDirectory() as temp,patch.object(font_catalog,'ROOT',Path(temp)):
            conflicting=Path(temp)/relative
            conflicting.parent.mkdir();conflicting.write_bytes(b'project custom font')
            self.assertEqual(font_catalog.builtin_path(relative),font_catalog.ASSET_ROOT/relative)
            self.assertEqual(conflicting.read_bytes(),b'project custom font')

    def test_projectless_desktop_serves_only_authenticated_font_requests(self):
        projects=SimpleNamespace(current=None,settings={'ui_language':'en'})
        handler=desktop.make_handler(projects,'font-test')
        for _,relative,_,_ in font_catalog.UI_BUILTIN_FILES:
            with self.subTest(relative=relative):
                self.assertEqual(self.call(handler,'/font/'+relative)[0],200)
                self.assertEqual(self.call(handler,'/font/'+relative,authenticated=False)[0],403)
        self.assertEqual(self.call(handler,'/font/not-approved.ttf')[0],409)

    def test_build_manifest_contains_every_font_and_its_license(self):
        root=Path(__file__).resolve().parents[1]
        source=(root/'packaging/Corporium.spec').read_text(encoding='utf-8').split('a=Analysis(')[0]
        context={'SPECPATH':str(root/'packaging')}
        exec(compile(source,'Corporium.spec','exec'),context)
        included={str(Path(source).resolve()) for source,_ in context['datas']}
        for _,relative,_,_ in font_catalog.UI_BUILTIN_FILES:
            self.assertIn(str((root/'font'/relative).resolve()),included)
        for family in ('STIXTwoText',):
            self.assertIn(str((root/'font'/family/'OFL.txt').resolve()),included)
            self.assertIn(str((root/'font'/family/'SOURCE.json').resolve()),included)
        self.assertFalse(any(any(name in path for name in ('NotoSans','SourceHanSansSC','msjh.','msjhbd.','msjhl.')) for path in included))

    def test_system_chinese_font_and_legacy_choices_do_not_need_bundled_files(self):
        self.assertEqual({family for family,*_ in font_catalog.UI_BUILTIN_FILES},{'STIX Two Text'})
        self.assertEqual(len(font_catalog.UI_BUILTIN_FILES),8)
        for name in ('Microsoft JhengHei','Noto Sans','Source Han Sans SC'):
            self.assertTrue(font_catalog.valid_font(name))
        for relative in ('msjh.ttc','NotoSans/NotoSans-VF.ttf','SourceHanSansSC/SourceHanSansSC-Regular.otf'):
            with self.assertRaises(ValueError):font_catalog.builtin_path(relative)


if __name__=='__main__':unittest.main()
