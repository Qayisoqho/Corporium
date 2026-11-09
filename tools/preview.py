"""Run the current web/backend against a marked, synthetic preview project.

The listener is loopback-only. SQLite connections are confined to the selected
preview directory; neither the normal project nor its media are imported.
"""
import argparse
import io
import json
import os
from pathlib import Path
import sys
import tempfile
from urllib.parse import unquote, urlsplit
import uuid

ROOT = Path(__file__).resolve().parents[1]
MARKER = '.corporium-synthetic-preview.json'
FORMAT = 'corporium-synthetic-browser-preview-v1'


def state_directory(value):
    state = Path(value).resolve()
    build = (ROOT / 'build').resolve()
    if state == build or not state.is_relative_to(build):
        raise ValueError('Preview state must be a dedicated subdirectory of this source copy\'s build directory')
    marker = state / MARKER
    if marker.exists():
        metadata = json.loads(marker.read_text(encoding='utf-8'))
        if metadata.get('format') != FORMAT:
            raise ValueError('Unrecognized preview marker; refusing to open existing material')
    else:
        if state.exists() and any(state.iterdir()):
            raise ValueError('Unmarked nonempty directory; refusing to open or seed existing material')
        state.mkdir(parents=True, exist_ok=True)
        metadata = {'format': FORMAT, 'seeded': False}
        marker.write_text(json.dumps(metadata, indent=2), encoding='utf-8')
    return state, metadata


def confine_sqlite(state):
    def guard(event, args):
        if event != 'sqlite3.connect':
            return
        name = os.fsdecode(args[0])
        if name in ('', ':memory:'):
            return
        if name.startswith('file:'):
            name = unquote(urlsplit(name).path)
            if len(name) > 2 and name[0] == '/' and name[2] == ':':
                name = name[1:]
        if not Path(name).resolve().is_relative_to(state):
            raise RuntimeError('Preview may open SQLite databases only within its synthetic state directory')
    sys.addaudithook(guard)


def call(server, path, body=None):
    """Use the real HTTP dispatch for the small fixture, without a test dependency."""
    handler = object.__new__(server.Handler)
    handler.path = path
    payload = json.dumps(body).encode('utf-8')
    handler.headers = {'Content-Type': 'application/json', 'Content-Length': str(len(payload)), 'Host': '127.0.0.1'}
    handler.rfile = io.BytesIO(payload)
    result = []
    handler.send = lambda data, code=200, mime=None: result.append((code, data))
    handler.do_GET() if body is None else handler.do_POST()
    code, data = result[0]
    if code != 200:
        raise RuntimeError(f'Fixture request failed: {path}: {code}: {data}')
    return data


def prepare(state, metadata):
    scratch = state / 'tmp'
    scratch.mkdir(exist_ok=True)
    tempfile.tempdir = str(scratch)
    os.environ.update(TEMP=str(scratch), TMP=str(scratch))
    confine_sqlite(state)
    sys.path.insert(0, str(ROOT))
    import server
    server.DB = state / 'ui.sqlite3'
    server.init()
    if not metadata.get('seeded'):
        if not call(server, '/api/texts'):
            call(server, '/api/import', {
                'title': 'Synthetic browser preview',
                'content': '#pass([Synthetic preview], (([a-b=ke],[A-B=CL]),([c],[C])), [Example translation])',
            })
        entry = call(server, '/api/entries')['items'][0]
        existing = {layer['name'] for layer in call(server, '/api/layers')}
        for anchor in ('word', 'ipa', 'translation'):
            name = 'Preview ' + anchor
            if name in existing:
                continue
            layer = call(server, '/api/layer-save', {'name': name, 'font': 'Junicode', 'anchor': anchor})
            with server.connect(audit=False) as db:
                unit = db.execute("SELECT id FROM corpus_units WHERE entry_id=? AND kind='word' AND active=1 ORDER BY position LIMIT 1", (entry['id'],)).fetchone()[0] if anchor == 'word' else '@sentence'
                db.execute('INSERT INTO annotation_cells VALUES(?,?,?,?,?,?,1)', (
                    str(uuid.uuid4()), 'corpus', entry['id'], unit, layer['id'],
                    'a̋ŋɡə̃ · First\nŋa · Second\ntə · Third',
                ))
        metadata['seeded'] = True
        (state / MARKER).write_text(json.dumps(metadata, indent=2), encoding='utf-8')
    return server


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--port', type=int, default=8916)
    parser.add_argument('--state-dir', type=Path, default=ROOT / 'build' / 'browser-preview')
    parser.add_argument('--prepare-only', action='store_true', help='Initialize the isolated fixture without opening a listener')
    args = parser.parse_args()
    if not 1 <= args.port <= 65535:
        parser.error('--port must be between 1 and 65535')
    try:
        state, metadata = state_directory(args.state_dir)
        server = prepare(state, metadata)
    except (ValueError, RuntimeError) as exc:
        parser.exit(1, str(exc) + '\n')
    print(f'Synthetic database: {server.DB}', flush=True)
    print(f'Current web source: {ROOT / "web"}', flush=True)
    if args.prepare_only:
        return
    class Handler(server.Handler):
        def log_message(self, *args):
            pass
    try:
        with server.ThreadingHTTPServer(('127.0.0.1', args.port), Handler) as listener:
            print(f'READY http://127.0.0.1:{args.port}/?ui=zh-CN', flush=True)
            print(f'English: http://127.0.0.1:{args.port}/?ui=en', flush=True)
            print('Stop this preview with Ctrl+C.', flush=True)
            try:
                listener.serve_forever()
            except KeyboardInterrupt:
                pass
    except OSError as exc:
        parser.exit(1, f'Cannot listen on 127.0.0.1:{args.port}: {exc}\n')


if __name__ == '__main__':
    main()
