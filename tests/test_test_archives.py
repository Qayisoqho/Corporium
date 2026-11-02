import gzip
import hashlib
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
from tools import test_archives as archives
from tools import test_materials as materials


class TestArchivesTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(dir=Path(__file__).resolve().parents[1] / 'build/t')
        self.root = Path(self.temp.name)
        self.store = archives.ArchiveStore(self.root)
        self.store.directory.mkdir(parents=True)
        self.name = 'build/old-run/work.sqlite3'
        self.content = b'archived test payload' * 30
        self.data = {'version': 1, 'entries': {}, 'retired': {}}
        self.add(self.name, self.content)

    def tearDown(self):
        archives.cleanup_temporary()
        self.temp.cleanup()

    def add(self, name, content, group=None):
        sha = hashlib.sha256(content).hexdigest()
        obj = self.store.directory / (sha + '.gz')
        obj.write_bytes(gzip.compress(content))
        self.data['entries'][name] = {'storage': 'gzip', 'object': obj.relative_to(self.root).as_posix(),
            'sha256': sha, 'compressed_sha256': archives.digest(obj), 'bytes': len(content),
            'group': group or name, 'purpose': 'regression'}
        self.save()

    def save(self):
        self.store.catalog_path.write_text(json.dumps(self.data), encoding='utf-8')

    def test_restore_is_independent_and_never_overwrites(self):
        restored = self.store.restore(self.name)[0]
        self.assertEqual(restored.read_bytes(), self.content)
        restored.write_bytes(b'edited')
        self.assertEqual(self.store.verify(self.name), len(self.content))
        with self.assertRaisesRegex(ValueError, 'overwrite'):
            self.store.restore(self.name)

    def test_corrupt_payload_publishes_no_database_or_sidecar(self):
        self.add(self.name + '-journal', b'recovery', self.name)
        obj = self.root / self.data['entries'][self.name + '-journal']['object']
        obj.write_bytes(b'broken')
        with self.assertRaises(ValueError):
            self.store.restore(self.name)
        self.assertFalse((self.root / self.name).exists())
        self.assertFalse((self.root / (self.name + '-journal')).exists())
        self.assertEqual(list((self.root / 'build/old-run').glob('*.restore')), [])

    def test_database_and_recovery_files_restore_together_to_another_destination(self):
        self.add(self.name + '-journal', b'recovery', self.name)
        target = 'build/recheck/corpus.sqlite3'
        restored = self.store.restore(self.name, destination=target)
        self.assertEqual(len(restored), 2)
        self.assertEqual((self.root / target).read_bytes(), self.content)
        self.assertEqual((self.root / (target + '-journal')).read_bytes(), b'recovery')

    def test_production_protected_and_linked_destinations_are_refused(self):
        for target in ('data/corpus.sqlite3', '../escape.sqlite3', 'build/test-materials/new.sqlite3',
                       'build/media-preview/new.sqlite3', 'build/Corporium-dev/new.sqlite3',
                       *archives.ACTIVE):
            with self.subTest(target=target), self.assertRaises(ValueError):
                self.store.restore(self.name, destination=target)

    def test_source_cannot_escape_store_and_payload_size_is_bounded(self):
        self.data['entries'][self.name]['object'] = 'data/private.gz'
        self.save()
        with self.assertRaises(ValueError):
            self.store.restore(self.name)
        self.data['entries'][self.name]['object'] = 'build/test-archives/' + hashlib.sha256(self.content).hexdigest() + '.gz'
        self.data['entries'][self.name]['bytes'] = 1
        self.save()
        with self.assertRaisesRegex(ValueError, 'exceeds'):
            self.store.restore(self.name)
        self.assertFalse((self.root / self.name).exists())

    def test_baseline_reference_and_recursive_reference_are_checked(self):
        baseline = self.root / 'build/test-materials/objects/base.sqlite3'
        baseline.parent.mkdir(parents=True)
        baseline.write_bytes(self.content)
        item = self.data['entries'][self.name]
        item.update(storage='reference', source=baseline.relative_to(self.root).as_posix())
        self.save()
        self.assertEqual(self.store.restore(self.name)[0].read_bytes(), self.content)
        baseline.write_bytes(b'changed')
        with self.assertRaisesRegex(ValueError, 'checksum'):
            self.store.verify(self.name)
        item['source'] = self.name
        self.save()
        with self.assertRaisesRegex(ValueError, 'cycle'):
            self.store.verify(self.name)

    def test_legacy_restores_referenced_group_and_releases_only_unchanged_files(self):
        self.add(self.name + '-journal', b'recovery', self.name)
        restored = archives.enable_legacy('ignored', lambda names: [self.name], root=self.root)
        self.assertEqual(len(restored), 2)
        archives.cleanup_temporary()
        self.assertFalse((self.root / self.name).exists())
        self.assertFalse((self.root / (self.name + '-journal')).exists())
        archives.enable_legacy('ignored', lambda names: [self.name], root=self.root)
        (self.root / self.name).write_bytes(b'changed test result')
        archives.cleanup_temporary()
        self.assertTrue((self.root / self.name).exists())
        self.assertTrue((self.root / (self.name + '-journal')).exists())

    def test_legacy_keeps_new_recovery_files_and_existing_work_is_never_overwritten(self):
        archives.enable_legacy('ignored', lambda names: [self.name], root=self.root)
        (self.root / (self.name + '-wal')).write_bytes(b'new transaction')
        archives.cleanup_temporary()
        self.assertTrue((self.root / self.name).exists())
        self.assertEqual(archives.enable_legacy('ignored', lambda names: [self.name], root=self.root), [])

    def test_materials_entrypoint_selects_archived_local_input(self):
        script = self.root / 'build/old-run/check.py'
        script.parent.mkdir(parents=True)
        script.write_text("p='work.sqlite3'\n", encoding='utf-8')
        with patch.object(materials, 'ROOT', self.root), patch.object(materials, 'catalog', return_value={'aliases': {}}):
            restored = materials.enable_legacy(script)
        self.assertEqual(len(restored), 1)
        self.assertEqual(restored[0].read_bytes(), self.content)
        archives.cleanup_temporary()
        self.assertFalse(restored[0].exists())


if __name__ == '__main__':
    unittest.main()
