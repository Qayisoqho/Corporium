"""Installed font metadata, cross-machine settings and safe application routes."""
import json
import sys
import unittest
from unittest.mock import patch
import font_catalog
import system_fonts
import test_server
import test_dictionary_evidence_assets as assets


class SystemFontTests(unittest.TestCase):
    def test_reversible_bounded_ids_survive_missing_fonts(self):
        for name in ('Research Sans','思源黑体','A "quoted" Family','IPA / Æ', '\U00010400 Research'):
            value=system_fonts.font_id(name)
            self.assertEqual(system_fonts.font_name(value),name)
            self.assertTrue(font_catalog.valid_font(value))
        for invalid in ('',None,12,{},'systemfont-ff','systemfont-0a','systemfont-4076657274','systemfont-'+ '41'*257,'localfont-../../file'):
            self.assertIsNone(system_fonts.font_name(invalid))
            self.assertFalse(font_catalog.valid_font(invalid))
        self.assertFalse(font_catalog.valid_font('@global'))

    def test_discovery_is_cached_refreshable_and_failure_keeps_last_catalog(self):
        state=system_fonts._cached,system_fonts._checked
        try:
            system_fonts._cached=None
            with patch.object(system_fonts.sys,'platform','win32'),patch.object(system_fonts,'_enumerate',return_value=[{'name':'Test'}]) as enumerate_:
                first=system_fonts.catalog();self.assertIs(system_fonts.catalog(),first);self.assertEqual(enumerate_.call_count,1)
                system_fonts.catalog(True);self.assertEqual(enumerate_.call_count,2)
                enumerate_.side_effect=OSError('test failure')
                failed=system_fonts.catalog(True);self.assertEqual(failed['families'],first['families']);self.assertEqual(failed['status'],'error')
        finally:system_fonts._cached,system_fonts._checked=state

    def test_native_catalog_has_only_metadata_and_unique_family_ids(self):
        data=system_fonts.catalog(True)
        if sys.platform!='win32':self.assertEqual(data['status'],'unsupported');return
        self.assertEqual(data['status'],'ready',data['error']);self.assertGreater(len(data['families']),0)
        self.assertEqual(len(data['families']),len({f['id'] for f in data['families']}))
        for family in data['families']:
            self.assertEqual(system_fonts.font_name(family['id']),family['name'])
            for face in family['faces']:
                self.assertTrue(face['local']);self.assertNotIn('url',face);self.assertNotIn('path',face)
                self.assertIn(face['style'],('normal','italic','oblique'));self.assertTrue(1<=int(face['weight'])<=1000)


class FontSettingsAPITests(unittest.TestCase):
    setUp=test_server.APITests.setUp
    tearDown=test_server.APITests.tearDown
    call=test_server.APITests.call

    def test_language_global_mode_and_missing_system_font_roundtrip(self):
        metadata={'ipa_font':'@global','annotation_font':'@global','gloss_font':system_fonts.font_id('Missing Research Font'),'translation_font':'Junicode','morpheme_variant':'italic','ipa_scale':1.2}
        code,result=self.call('/api/save-language',{'name':'Font test','metadata':metadata})
        self.assertEqual(code,200,result)
        rows=self.call('/api/languages')[1];saved=next(x for x in rows if x['id']==result['id'])
        self.assertEqual(json.loads(saved['metadata']),metadata)
        bundle=self.call('/api/export-language?language='+result['id'])[1]
        exported=json.loads(bundle['language']['metadata'])
        self.assertEqual({k:exported[k] for k in metadata},metadata)
        for font in ('systemfont-ff','systemfont-0a','@global; color:red'):
            self.assertEqual(self.call('/api/save-language',{'name':'Bad','metadata':{'ipa_font':font}})[0],400)

    def test_custom_layers_keep_global_mode_and_independent_type_and_spacing(self):
        for anchor in ('word','ipa','translation'):
            code,result=self.call('/api/layer-save',dict(name='Follow '+anchor,font='@global',style='italic',anchor=anchor,line_spacing=-25,size=125))
            self.assertEqual(code,200,result)
        layers=self.call('/api/layers?language=ordos')[1]
        self.assertEqual(len(layers),3)
        for layer in layers:
            self.assertEqual((layer['font'],layer['style'],layer['line_spacing'],layer['size']),('@global','italic',-25,125))
        bundle=self.call('/api/export-language?language=ordos')[1]
        self.assertTrue(all(layer['font']=='@global' for layer in bundle['annotation_layers']))


class FontStackAssetTests(unittest.TestCase):
    check_asset=assets.DictionaryEvidenceAssetTests.check_asset
    def test_font_stack_js(self):self.check_asset('font-stack.js','text/javascript; charset=utf-8')
    def test_font_stack_css(self):self.check_asset('font-stack.css','text/css; charset=utf-8')
