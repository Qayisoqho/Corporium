"""Local cold storage for retired build fixtures; never opens application databases.

The catalog and compressed objects live under build/test-archives. Restores are
verified independent files, never links to the sealed test-materials store.
"""
import argparse
import atexit
import gzip
import hashlib
import json
import os
from pathlib import Path
import shutil
import sys
import uuid

ROOT = Path(__file__).resolve().parents[1]
ACTIVE = {
    'build/layer-performance-20261026/after-1000.sqlite3',
    'build/layer-performance-20261026/after-10000.sqlite3',
    'build/layer-performance-20261026/after-dense-inherited-10000.sqlite3',
    'build/performance-after-20261016/synthetic-50000.sqlite3',
}
PROTECTED = ('build/test-materials', 'build/test-archives', 'build/Corporium-dev',
             'build/media-preview', 'build/media-venv')
SIDECARS = ('-journal', '-wal', '-shm')


def digest(path):
    with Path(path).open('rb') as stream:
        return hashlib.file_digest(stream, 'sha256').hexdigest()


class ArchiveStore:
    def __init__(self, root=ROOT):
        self.root = Path(root).resolve()
        self.directory = self.root / 'build/test-archives'
        self.catalog_path = self.directory / 'catalog.json'

    def catalog(self):
        if not self.catalog_path.exists():
            return {'version': 1, 'entries': {}, 'retired': {}}
        self.checked(self.catalog_path, storage=True)
        data = json.loads(self.catalog_path.read_text(encoding='utf-8'))
        if data.get('version') != 1:
            raise ValueError('Unsupported test archive catalog')
        return data

    def checked(self, name, *, storage=False, baseline=False):
        path = Path(name)
        if not path.is_absolute():
            path = self.root / path
        path = Path(os.path.abspath(path))
        build = self.root / 'build'
        if not path.is_relative_to(build) or path == build:
            raise ValueError('Test archive paths must stay under build/')
        for part in (path, *path.parents):
            if part == self.root:
                break
            if part.is_symlink() or part.is_junction():
                raise ValueError('Test archive paths cannot use links')
        path = path.resolve()
        relative = path.relative_to(self.root).as_posix()
        if storage:
            if not path.is_relative_to(self.directory):
                raise ValueError('Compressed object must stay in the archive store')
        elif baseline:
            if not path.is_relative_to(build / 'test-materials/objects'):
                raise ValueError('Baseline source must stay in test-materials/objects')
        elif relative in ACTIVE or any(path == self.root / p or path.is_relative_to(self.root / p) for p in PROTECTED):
            raise ValueError('Protected test material or development project')
        return path

    def group(self, name, data=None):
        data = data or self.catalog()
        entries = data['entries']
        if name not in entries:
            raise ValueError('Unknown archived test file: ' + name)
        group = entries[name].get('group', name)
        return sorted(k for k, item in entries.items() if item.get('group', k) == group)

    def payload(self, name, data=None, seen=None):
        data = data or self.catalog()
        seen = set() if seen is None else seen
        if name in seen:
            raise ValueError('Archive reference cycle')
        seen.add(name)
        item = data['entries'][name]
        kind = item['storage']
        if kind == 'reference':
            target = item['source']
            if target in data['entries']:
                path, compressed, source_item = self.payload(target, data, seen)
                if (source_item['sha256'], source_item['bytes']) != (item['sha256'], item['bytes']):
                    raise ValueError('Archive reference checksum differs')
                return path, compressed, item
            path = self.checked(target, baseline=target.startswith('build/test-materials/objects/'))
            return path, False, item
        if kind != 'gzip':
            raise ValueError('Unknown archive storage')
        return self.checked(item['object'], storage=True), True, item

    def verify(self, name, data=None):
        path, compressed, item = self.payload(name, data)
        if compressed and item.get('compressed_sha256') and digest(path) != item['compressed_sha256']:
            raise ValueError('Compressed archive checksum mismatch: ' + name)
        h = hashlib.sha256()
        count = 0
        with (gzip.open(path, 'rb') if compressed else path.open('rb')) as stream:
            while chunk := stream.read(1024 * 1024):
                count += len(chunk)
                if count > item['bytes']:
                    raise ValueError('Archive exceeds recorded size')
                h.update(chunk)
        if count != item['bytes'] or h.hexdigest() != item['sha256']:
            raise ValueError('Archive payload checksum mismatch: ' + name)
        return count

    def restore(self, name, *, destination=None):
        data = self.catalog()
        names = self.group(name, data)
        base = data['entries'][name].get('group', name)
        if destination is not None and name != base:
            raise ValueError('Restore a database group by its primary path')
        targets = {}
        for key in names:
            target = str(destination) + key[len(base):] if destination is not None else key
            targets[key] = self.checked(target)
        if any(path.exists() for path in targets.values()):
            raise ValueError('Refusing to overwrite existing test files')
        # A destination with a stale SQLite sidecar must never be reused.
        main = targets.get(base)
        if main and any(Path(str(main) + s).exists() for s in SIDECARS):
            raise ValueError('Destination has SQLite recovery files')
        staged = {}
        created = []
        try:
            for key, target in targets.items():
                source, compressed, item = self.payload(key, data)
                if compressed and item.get('compressed_sha256') and digest(source) != item['compressed_sha256']:
                    raise ValueError('Compressed archive checksum mismatch')
                target.parent.mkdir(parents=True, exist_ok=True)
                temporary = target.with_name('.' + target.name + '.' + uuid.uuid4().hex + '.restore')
                staged[key] = temporary
                h = hashlib.sha256()
                count = 0
                with (gzip.open(source, 'rb') if compressed else source.open('rb')) as inp, temporary.open('xb') as out:
                    while chunk := inp.read(1024 * 1024):
                        count += len(chunk)
                        if count > item['bytes']:
                            raise ValueError('Archive exceeds recorded size')
                        h.update(chunk)
                        out.write(chunk)
                    out.flush()
                    os.fsync(out.fileno())
                if count != item['bytes'] or h.hexdigest() != item['sha256']:
                    raise ValueError('Archive payload checksum mismatch')
            # Publish only after every member of the database group verifies.
            for key, target in targets.items():
                with target.open('xb') as out:
                    created.append(target)
                    with staged[key].open('rb') as inp:
                        shutil.copyfileobj(inp, out, 1024 * 1024)
                    out.flush()
                    os.fsync(out.fileno())
                if digest(target) != data['entries'][key]['sha256']:
                    raise ValueError('Restored file checksum mismatch')
                stamp = data['entries'][key].get('mtime_ns')
                if stamp:
                    os.utime(target, ns=(stamp, stamp))
            return list(targets.values())
        except BaseException:
            for path in reversed(created):
                path.unlink(missing_ok=True)
            raise
        finally:
            for path in staged.values():
                path.unlink(missing_ok=True)


_temporary = []


def enable_legacy(script, selector, *, root=ROOT):
    """Use the existing material selector; restore only missing referenced groups."""
    store = ArchiveStore(root)
    data = store.catalog()
    names = selector(data['entries'])
    restored = []
    processed = set()
    for name in names:
        group = data['entries'][name].get('group', name)
        if group in processed:
            continue
        processed.add(group)
        members = store.group(name, data)
        if any(store.checked(key).exists() for key in members):
            continue
        paths = store.restore(group)
        restored.extend(paths)
        _temporary.append((store, {key: data['entries'][key] for key in members}))
    return restored


def cleanup_temporary():
    # A modified database, or a new transaction sidecar, stays as test evidence.
    for store, members in list(_temporary):
        try:
            paths = {key: store.checked(key) for key in members}
            primary = next(iter(members.values())).get('group')
            if primary and any((store.root / (primary + s)).exists() and primary + s not in members for s in SIDECARS):
                continue
            if not all(path.exists() and path.stat().st_size == members[key]['bytes'] and digest(path) == members[key]['sha256'] for key, path in paths.items()):
                continue
            for path in paths.values():
                path.unlink()
        except (OSError, ValueError):
            pass
    _temporary.clear()


atexit.register(cleanup_temporary)


def main():
    parser = argparse.ArgumentParser(description='Local test archives: list, verify, or restore independent files')
    sub = parser.add_subparsers(dest='command', required=True)
    listing = sub.add_parser('list')
    listing.add_argument('--purpose')
    for command in ('verify', 'restore'):
        action = sub.add_parser(command)
        action.add_argument('path')
        if command == 'restore':
            action.add_argument('--destination')
    args = parser.parse_args()
    store = ArchiveStore()
    data = store.catalog()
    if args.command == 'list':
        rows = {key: item for key, item in data['entries'].items() if not args.purpose or item['purpose'] == args.purpose}
        print(json.dumps(rows, ensure_ascii=False, indent=2))
    elif args.command == 'verify':
        for key in store.group(args.path, data):
            print(key, store.verify(key, data))
    else:
        for path in store.restore(args.path, destination=args.destination):
            print(path)


if __name__ == '__main__':
    main()
