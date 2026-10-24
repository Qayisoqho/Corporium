import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
from tools import test_materials as materials


class TestMaterialsTests(unittest.TestCase):
    def setUp(self):
        scratch=Path(__file__).resolve().parents[1]/'build/t';scratch.mkdir(parents=True,exist_ok=True)
        self.temp=tempfile.TemporaryDirectory(dir=scratch)
        self.root=Path(self.temp.name);self.store=self.root/'build/test-materials';self.store.mkdir(parents=True)
        self.patches=[patch.object(materials,'ROOT',self.root),patch.object(materials,'STORE',self.store),patch.object(materials,'CATALOG',self.store/'catalog.json'),patch.object(materials,'_verified',{}),patch.object(materials,'_restored',{})]
        for p in self.patches:p.start()
        self.original=self.store/'baseline.sqlite3';self.original.write_bytes(b'original test baseline')
        self.sha=materials.digest(self.original)
        self.alias='build/old-run/baseline.sqlite3'
        self.data=dict(version=1,objects={self.sha:dict(path=self.original.relative_to(self.root).as_posix(),bytes=self.original.stat().st_size)},aliases={self.alias:self.sha},profiles={'smoke':dict(sha256=self.sha,fixture={'sentences':12})})
        self.save()

    def save(self):materials.CATALOG.write_text(json.dumps(self.data),encoding='utf-8')

    def tearDown(self):
        for p in reversed(self.patches):p.stop()
        self.temp.cleanup()

    def test_checkout_copies_are_independent_and_cannot_overwrite(self):
        a=materials.checkout('smoke','build/run-a/a.sqlite3');b=materials.checkout('smoke','build/run-b/b.sqlite3')
        a.write_bytes(b'changed')
        self.assertEqual(b.read_bytes(),self.original.read_bytes())
        self.assertEqual(json.loads(a.with_suffix('.fixture.json').read_text()),{'sentences':12})
        with self.assertRaisesRegex(ValueError,'overwrite'):materials.checkout('smoke',a)

    def test_production_store_and_environments_are_not_working_destinations(self):
        for path in ('data/corpus.sqlite3','test_lang/db.sqlite3','build/test-materials/new.sqlite3','build/media-venv/new.sqlite3','build/Corporium-dev/new.sqlite3'):
            with self.subTest(path=path),self.assertRaises(ValueError):materials.checkout('smoke',path)

    def test_modified_baseline_is_detected_before_copy(self):
        self.original.write_bytes(b'corrupt')
        with self.assertRaisesRegex(ValueError,'checksum'):materials.checkout('smoke','build/new.sqlite3')
        self.assertFalse((self.root/'build/new.sqlite3').exists())

    def test_catalog_cannot_use_live_production_or_automatic_backup_paths(self):
        protected=self.root/'data/backups/history.sqlite3';protected.parent.mkdir(parents=True);protected.write_bytes(self.original.read_bytes())
        self.data['objects'][self.sha]['path']='data/backups/history.sqlite3';self.save()
        with self.assertRaisesRegex(ValueError,'outside the test material store'):materials.checkout('smoke','build/new.sqlite3')
        self.assertEqual(protected.read_bytes(),b'original test baseline')

    def test_legacy_local_input_is_restored_and_unchanged_copy_is_released(self):
        script=self.root/'build/old-run/check.py';script.parent.mkdir(parents=True)
        script.write_text("from pathlib import Path\np=Path(__file__).parent/'baseline.sqlite3'\n")
        restored=materials.enable_legacy(script);self.assertEqual(len(restored),1)
        self.assertEqual(restored[0].read_bytes(),self.original.read_bytes())
        materials._cleanup_restored();self.assertFalse(restored[0].exists());self.assertTrue(self.original.exists())

    def test_changed_legacy_result_and_journal_are_retained(self):
        script=self.root/'build/old-run/check.py';script.parent.mkdir(parents=True);script.write_text("p='baseline.sqlite3'\n")
        path=materials.enable_legacy(script)[0];path.write_bytes(b'changed result')
        materials._cleanup_restored();self.assertEqual(path.read_bytes(),b'changed result')
        path.write_bytes(self.original.read_bytes());journal=Path(str(path)+'-journal');journal.write_bytes(b'recovery')
        materials._cleanup_restored();self.assertTrue(path.exists());self.assertTrue(journal.exists())

    def test_explicit_cross_directory_and_dynamic_size_sources(self):
        self.data['aliases']={'build/performance-old/backup-1000.sqlite3':self.sha};self.save()
        script=self.root/'build/check.py';script.write_text("n=1000\np=f'build/performance-old/backup-{n}.sqlite3'\n")
        restored=materials.enable_legacy(script);self.assertEqual(len(restored),1)
        materials._cleanup_restored()

    def test_unknown_material_and_existing_metadata_are_not_overwritten(self):
        with self.assertRaisesRegex(ValueError,'Unknown'):materials.checkout('missing','build/missing.sqlite3')
        dest=self.root/'build/new.sqlite3';dest.with_suffix('.fixture.json').write_text('keep')
        with self.assertRaisesRegex(ValueError,'overwrite'):materials.checkout('smoke',dest)
        self.assertFalse(dest.exists())

    def test_legacy_glob_and_relative_source_argument_find_virtual_inputs(self):
        script=self.root/'build/old-run/check.py';script.parent.mkdir(parents=True);script.write_text("files=Path(__file__).parent.glob('*.sqlite3')\n")
        self.assertEqual(materials.referenced_aliases(script),[self.alias])
        script=self.root/'check.py';script.write_text("p=source/f'baseline.sqlite3'\n")
        with patch.object(materials.sys,'argv',['check.py','--source','build/old-run']):self.assertEqual(materials.referenced_aliases(script),[self.alias])
