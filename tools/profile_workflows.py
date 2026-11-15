"""Serve an existing isolated fixture for workflow timing; no material is seeded.

Run ordinary timing and --profile attribution separately. Profiling adds timers,
SQL fetch accounting and cProfile; those durations are not baseline latencies.
"""
import argparse
from collections import defaultdict
from contextlib import contextmanager
import cProfile
import functools
import hashlib
import json
from pathlib import Path
import pstats
import sqlite3
import sys
import tempfile
import threading
import time
from types import SimpleNamespace
from urllib.parse import parse_qs, urlsplit
from urllib.request import url2pathname

ROOT = Path(__file__).resolve().parents[1]


class Probe:
    def __init__(self, folder):
        self.folder = folder
        self.local = threading.local()
        self.lock = threading.Lock()
        self.profiler_lock = threading.Lock()
        self.operation = 'setup'
        self.sequence = 0

    @contextmanager
    def span(self, name):
        active = getattr(self.local, 'active', None)
        if active is None:
            yield
            return
        node = [time.perf_counter(), 0]
        active['stack'].append(node)
        try:
            yield
        finally:
            elapsed = (time.perf_counter() - node[0]) * 1000
            active['stack'].pop()
            if active['stack']:
                active['stack'][-1][1] += elapsed
            values = active['phases'][name]
            values[0] += 1
            values[1] += elapsed
            values[2] += elapsed - node[1]

    def wrap(self, owner, name, label=None):
        original = getattr(owner, name, None)
        if original is None:
            return
        @functools.wraps(original)
        def measured(*args, **kwargs):
            with self.span(label or owner.__name__ + '.' + name):
                return original(*args, **kwargs)
        setattr(owner, name, measured)

    def run(self, label, function, *args, **kwargs):
        if getattr(self.local, 'active', None) is not None:
            return function(*args, **kwargs)
        with self.lock:
            self.sequence += 1
            identifier = str(self.sequence)
        active = dict(id=identifier, label=label, operation=self.operation, stack=[],
                      phases=defaultdict(lambda: [0, 0., 0.]), sql=defaultdict(lambda: [0, 0., 0]), rows=0)
        self.local.active = active
        profiler = None
        wants_profile = label.startswith('job:') or label == 'POST /api/inline-save' or label.startswith('GET /api/dictionary-search-options')
        if wants_profile and self.profiler_lock.acquire(blocking=False):
            profiler = cProfile.Profile()
            try:
                profiler.enable()
            except ValueError as error:
                active['profiler_error'] = str(error)
                profiler = None
                self.profiler_lock.release()
        start = time.perf_counter()
        try:
            return function(*args, **kwargs)
        finally:
            if profiler is not None:
                profiler.disable()
                self.profiler_lock.release()
            active['wall_ms'] = (time.perf_counter() - start) * 1000
            self.local.active = None
            active.pop('stack')
            active['phases'] = dict(active['phases'])
            active['sql'] = dict(active['sql'])
            active['functions'] = []
            if profiler is not None:
                profiler.dump_stats(str(self.folder / (identifier + '.prof')))
                stats = pstats.Stats(profiler)
                active['functions'] = [dict(file=k[0], line=k[1], name=k[2], calls=v[1], own_ms=v[2]*1000, cumulative_ms=v[3]*1000)
                    for k, v in sorted(stats.stats.items(), key=lambda kv: kv[1][3], reverse=True)[:70]]
            (self.folder / (identifier + '.json')).write_text(json.dumps(active, ensure_ascii=False, indent=2), encoding='utf8')

    def install(self, server):
        probe = self
        original_connect = sqlite3.connect
        import desktop
        original_lock = desktop.LOCK
        class DesktopLock:
            def __enter__(self):
                with probe.span('desktop.lock.wait'):
                    return original_lock.__enter__()
            def __exit__(self, *args):
                return original_lock.__exit__(*args)
            def __getattr__(self, name):
                return getattr(original_lock, name)
        desktop.LOCK = DesktopLock()
        class Cursor(sqlite3.Cursor):
            def account(self, start, rows=0, execute=False):
                active = getattr(probe.local, 'active', None)
                if active is not None:
                    record = active['sql'][getattr(self, 'statement', '?')]
                    record[0] += int(execute)
                    record[1] += (time.perf_counter() - start)*1000
                    record[2] += rows
            def execute(self, *args, **kw):
                self.statement = str(args[0]); start = time.perf_counter()
                words = self.statement.lstrip().split(None, 1)
                verb = words[0].upper() if words else ''
                label = 'sql.begin' if verb == 'BEGIN' else 'sql.write' if verb in ('INSERT', 'UPDATE', 'DELETE', 'REPLACE') else 'sql.execute'
                with probe.span(label):
                    try:
                        return super().execute(*args, **kw)
                    finally:
                        self.account(start, execute=True)
            def executemany(self, *args, **kw):
                self.statement = str(args[0]); start = time.perf_counter()
                with probe.span('sql.executemany'):
                    try:
                        return super().executemany(*args, **kw)
                    finally:
                        self.account(start, execute=True)
            def executescript(self, *args, **kw):
                self.statement = str(args[0]); start = time.perf_counter()
                with probe.span('sql.executescript'):
                    try:
                        return super().executescript(*args, **kw)
                    finally:
                        self.account(start, execute=True)
            def __next__(self):
                start = time.perf_counter()
                with probe.span('sql.fetch'):
                    try:
                        value = super().__next__()
                    except StopIteration:
                        self.account(start)
                        raise
                    self.account(start, 1)
                    if getattr(probe.local, 'active', None):
                        probe.local.active['rows'] += 1
                    return value
            def fetchone(self):
                start = time.perf_counter()
                with probe.span('sql.fetch'):
                    result = super().fetchone()
                    self.account(start, int(result is not None))
                    if getattr(probe.local, 'active', None) and result is not None:
                        probe.local.active['rows'] += 1
                    return result
            def fetchall(self):
                start = time.perf_counter()
                with probe.span('sql.fetch'):
                    result = super().fetchall()
                    self.account(start, len(result))
                    if getattr(probe.local, 'active', None):
                        probe.local.active['rows'] += len(result)
                    return result
            def fetchmany(self, *args, **kwargs):
                start = time.perf_counter()
                with probe.span('sql.fetch'):
                    result = super().fetchmany(*args, **kwargs)
                    self.account(start, len(result))
                    if getattr(probe.local, 'active', None):
                        probe.local.active['rows'] += len(result)
                    return result
        class Connection(sqlite3.Connection):
            def cursor(self, *args, **kw):
                if not args:
                    kw.setdefault('factory', Cursor)
                return super().cursor(*args, **kw)
            def execute(self, *args, **kw):
                return self.cursor().execute(*args, **kw)
            def executemany(self, *args, **kw):
                return self.cursor().executemany(*args, **kw)
            def executescript(self, *args, **kw):
                return self.cursor().executescript(*args, **kw)
            def commit(self):
                with probe.span('db.commit'):
                    return super().commit()
            def rollback(self):
                with probe.span('db.rollback'):
                    return super().rollback()
        def connect(*args, **kw):
            if len(args) <= 5:
                kw.setdefault('factory', Connection)
            with probe.span('db.open'):
                return original_connect(*args, **kw)
        sqlite3.connect = connect
        original_context = server.connect
        @contextmanager
        def context(*args, **kw):
            manager = original_context(*args, **kw)
            with probe.span('transaction.enter'):
                db = manager.__enter__()
            try:
                yield db
            except BaseException:
                with probe.span('transaction.exit'):
                    if not manager.__exit__(*sys.exc_info()):
                        raise
            else:
                with probe.span('transaction.exit'):
                    manager.__exit__(None, None, None)
        server.connect = context
        modules = {
            'lexicon': ('mutate', 'sync_changes', 'validate_changes', 'validate_links', 'get_lexeme', 'list_lexemes', 'occurrence_count'),
            'dictionary_link_changes': ('preview', 'apply'),
            'annotations': ('inline_save', 'inline_data'),
            'journal': ('watch', 'record', 'state', 'undo'),
            'gloss_inheritance': ('sync_meanings', 'synchronize', 'validate_meaning_changes'),
            'dictionary_form_sync': ('sync',),
            'grammar_audit_cache': ('prepare_promotion', 'promote'),
            'grammaticality': ('normalize_rows', 'validate'),
            'manual_status': ('normalize_rows',),
            'save_validation': ('begin', 'complete', 'text_only'),
            'example_numbering': ('assign_missing', 'needed'),
            'dictionary_organization': ('filter_sort',),
            'dictionary_data': ('resolve',),
            'homonyms': ('prepare', 'plan'),
            'morpheme_registry': ('save_plan',),
            'object_media': ('validate',),
            'json': ('loads', 'dumps'),
        }
        for module, names in modules.items():
            owner = __import__(module)
            for name in names:
                self.wrap(owner, name)
        import save_validation
        text_only = save_validation.text_only
        plain_loads = getattr(json.loads, '__wrapped__', json.loads)
        def scoped(changed):
            result = text_only(changed)
            active = getattr(probe.local, 'active', None)
            if active is not None:
                details = []
                for table, before, after in changed:
                    fields = []
                    if before and after and 'body' in before and 'body' in after:
                        try:
                            a, b = plain_loads(before['body']), plain_loads(after['body'])
                            fields = sorted(k for k in a.keys() | b.keys() if a.get(k) != b.get(k))
                        except (ValueError,TypeError,AttributeError):
                            fields = ['unreadable body']
                    details.append(dict(table=table, before=bool(before), after=bool(after), fields=fields))
                active.setdefault('validation_scope', []).append(dict(text_only=result, rows=details))
            return result
        save_validation.text_only = scoped
        import dictionary_search
        for name in ('__init__', 'document', 'matches'):
            self.wrap(dictionary_search.SearchIndex, name, 'SearchIndex.' + name)
        self.wrap(server.Handler, 'send', 'response.encode_and_send')
        original_run = server.long_tasks.run
        def run(job):
            return self.run('job:' + str(job.get('kind')), original_run, job)
        server.long_tasks.run = run


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--database', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--port', type=int, required=True)
    parser.add_argument('--profile', action='store_true')
    args = parser.parse_args()
    database, out = args.database.resolve(), args.output.resolve()
    if not database.is_file() or not database.is_relative_to(ROOT / 'build') or not out.is_relative_to(ROOT / 'build'):
        parser.error('Use an existing isolated database and output under build/.')
    out.mkdir(parents=True, exist_ok=True)
    scratch = out / 'tmp'
    scratch.mkdir(exist_ok=True)
    tempfile.tempdir = str(scratch)
    def guard(event, values):
        if event != 'sqlite3.connect' or str(values[0]) == ':memory:':
            return
        value = str(values[0])
        path = Path(url2pathname(urlsplit(value).path) if value.startswith('file:') else value).resolve()
        if path != database and not path.is_relative_to(scratch) and not path.is_relative_to(database.parent / 'backups'):
            raise AssertionError('Workflow probe refused another database: ' + str(path))
    sys.addaudithook(guard)
    sys.path.insert(0, str(ROOT))
    import server
    import desktop
    import record_sources
    server.DB = database
    server.init()
    with server.connect(audit=False) as db:
        target = dict(db.execute('SELECT x.id,x.headword,x.language_id,count(l.id) links FROM lexemes x LEFT JOIN lexical_links l ON l.lexeme_id=x.id GROUP BY x.id ORDER BY links DESC,x.id LIMIT 1').fetchone())
        target['body'] = record_sources.read(db,'lexemes',target['id'])
        first = dict(db.execute('SELECT id,text_id,position FROM entries ORDER BY rowid LIMIT 1').fetchone())
        counts = {table: db.execute('SELECT count(*) FROM ' + table).fetchone()[0] for table in ('lexemes', 'morphemes', 'entries', 'dictionary_examples')}
    meta = dict(database=str(database.relative_to(ROOT)), target=target, first=first, counts=counts,
                profile=args.profile, python=sys.version, hashes={p.name: hashlib.sha256(p.read_bytes()).hexdigest() for p in ROOT.glob('*.py')})
    (out / 'metadata.json').write_text(json.dumps(meta, ensure_ascii=False, indent=2), encoding='utf8')
    probe = Probe(out / 'profiles')
    probe.folder.mkdir(exist_ok=True)
    if args.profile:
        probe.install(server)
    projects = SimpleNamespace(current=database.parent, generation='workflow-probe', settings={'ui_language': 'zh-CN', 'recent': []}, startup_error='')
    projects.status = lambda: desktop.Projects.status(projects)
    Base = desktop.make_handler(projects, 'workflow-probe')
    class Handler(Base):
        def log_message(self, *_):
            pass
        def ui_language(self):
            locale = server.ui_localization.language(self.headers)
            projects.settings['ui_language'] = locale
            return locale
        def do_GET(self):
            parsed = urlsplit(self.path)
            if parsed.path == '/__workflow/meta':
                return self.send(meta)
            if parsed.path == '/__workflow/operation':
                probe.operation = parse_qs(parsed.query).get('name', ['idle'])[0]
                return self.send({'operation': probe.operation})
            if parsed.path == '/__workflow/jobs':
                with server.long_tasks.LOCK:
                    jobs = [{k: j.get(k) for k in ('id', 'kind', 'state', 'message', 'progress')}
                            for j in server.long_tasks.JOBS.values()]
                return self.send(jobs)
            if parsed.path == '/__workflow/cancel':
                server.long_tasks.cancel_all()
                return self.send({'cancel_requested': True})
            if parsed.path == '/__workflow/row':
                query = parse_qs(parsed.query)
                table = {'lexeme': 'lexemes', 'corpus': 'entries', 'independent': 'dictionary_examples'}[query['kind'][0]]
                with server.connect(audit=False) as db:
                    row = db.execute('SELECT * FROM ' + table + ' WHERE id=?', (query['id'][0],)).fetchone()
                return self.send(dict(row) if row else None)
            return self.dispatch('GET', super().do_GET)
        def do_POST(self):
            return self.dispatch('POST', super().do_POST)
        def dispatch(self, method, function):
            self.workflow_start = time.perf_counter()
            if args.profile and self.path.startswith('/api/'):
                return probe.run(method + ' ' + self.path, function)
            return function()
        def end_headers(self):
            if hasattr(self, 'workflow_start'):
                self.send_header('Server-Timing', 'handler;dur=' + str(round((time.perf_counter() - self.workflow_start)*1000, 3)))
            return super().end_headers()
    with server.ThreadingHTTPServer(('127.0.0.1', args.port), Handler) as listener:
        print('READY ' + str(args.port), flush=True)
        try:
            listener.serve_forever()
        except KeyboardInterrupt:
            pass


if __name__ == '__main__':
    main()
