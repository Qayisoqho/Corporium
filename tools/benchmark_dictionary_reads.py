"""Measure dictionary reads against an existing isolated fixture; never seed data."""
import argparse
import hashlib
import json
from pathlib import Path
import statistics
import sys
import tempfile
import time
from urllib.parse import urlsplit
from urllib.request import url2pathname
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--database', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--initialize', action='store_true')
    parser.add_argument('--source-root', type=Path, default=ROOT)
    parser.add_argument('--only', nargs='+')
    parser.add_argument('--reset-form-keys', action='store_true', help='Rebuild only disposable dictionary form keys before the first query')
    parser.add_argument('--runs', type=int, default=3)
    args = parser.parse_args()
    database = args.database.resolve()
    if not database.is_file() or not database.is_relative_to(ROOT / 'build'):
        parser.error('Use an existing synthetic database under build/. No data is generated.')
    if args.runs < 1:
        parser.error('--runs must be positive')
    allowed = (database.parent, args.output.resolve().parent)

    def guard(event, values):
        if event == 'sqlite3.connect' and str(values[0]) != ':memory:':
            value = str(values[0])
            path = Path(url2pathname(urlsplit(value).path) if value.startswith('file:') else value).resolve()
            if not any(path.is_relative_to(base) for base in allowed):
                raise RuntimeError('Benchmark refused to open a database outside its fixture: ' + str(path))

    sys.addaudithook(guard)
    scratch = args.output.resolve().parent / 'tmp'
    scratch.mkdir(parents=True, exist_ok=True)
    tempfile.tempdir = str(scratch)
    source = args.source_root.resolve()
    if not (source / 'lexicon.py').is_file():
        parser.error('--source-root must contain Corporium source')
    sys.path.insert(0, str(source))
    import server
    import lexicon
    import morpheme_registry
    server.DB = database
    if args.initialize:
        start = time.perf_counter()
        server.init()
        print('Initialized existing fixture in %.3fs' % (time.perf_counter() - start), flush=True)
    if args.reset_form_keys:
        import dictionary_read
        import search_keys
        with server.connect(audit=False) as db:
            owned = [r[0] for r in db.execute('SELECT DISTINCT value_id FROM dictionary_form_search')]
            dictionary_read.drop(db)
            search_keys.Values(db).release(owned)
            dictionary_read.initialize(db)

    with server.connect(audit=False) as db:
        counts = {table: db.execute('SELECT count(*) FROM ' + table).fetchone()[0]
                  for table in ('lexemes', 'morphemes', 'entries', 'dictionary_examples')}
        lid = db.execute('SELECT language_id FROM lexemes GROUP BY language_id ORDER BY count(*) DESC').fetchone()[0]
        word = db.execute('SELECT headword FROM lexemes WHERE language_id=? ORDER BY headword LIMIT 1', (lid,)).fetchone()[0]
        form = db.execute('SELECT form FROM morphemes WHERE language_id=? ORDER BY form LIMIT 1', (lid,)).fetchone()[0]
    entry = {'scope': 'entry'}
    operations = {
        'page30': lambda db: lexicon.list_lexemes(db, lid, summary=True),
        'last_page30': lambda db: lexicon.list_lexemes(db, lid, page=999999, summary=True),
        'picker_empty': lambda db: lexicon.list_lexemes(db, lid, targets=True, counts=False, search=entry),
        'headword_contains': lambda db: lexicon.list_lexemes(db, lid, word[:-1], summary=True, search={'field': 'headword'}),
        'headword_exact': lambda db: lexicon.list_lexemes(db, lid, summary=True, search={'conditions': [{'field': 'headword', 'op': 'exact', 'value': word}]}),
        'headword_prefix': lambda db: lexicon.list_lexemes(db, lid, summary=True, search={'conditions': [{'field': 'headword', 'op': 'prefix', 'value': word[:-1]}]}),
        'target_headword_prefix': lambda db: lexicon.list_lexemes(db, lid, targets=True, counts=False, search={'scope': 'entry', 'conditions': [{'field': 'headword', 'op': 'prefix', 'value': word[:-1]}]}),
        'morpheme_picker_empty': lambda db: morpheme_registry.listing(db, lid, search=entry, page_size=20),
        'morpheme_form_prefix': lambda db: morpheme_registry.listing(db, lid, search={'conditions': [{'field': 'form', 'op': 'prefix', 'value': form[:-1]}]}, page_size=20),
    }
    if args.only:
        if any(name not in operations for name in args.only):
            parser.error('Unknown operation')
        operations = {name: operations[name] for name in args.only}
    result = {'database': str(database.relative_to(ROOT)), 'source': str(source),
              'source_hashes': {name: hashlib.sha256((source / name).read_bytes()).hexdigest() for name in ('lexicon.py', 'morpheme_registry.py', 'dictionary_read.py') if (source / name).exists()},
              'reset_form_keys': args.reset_form_keys, 'counts': counts,
              'language_id': lid, 'word': word, 'form': form, 'operations': {}}
    for name, operation in operations.items():
        samples = []
        for run in range(args.runs + 1):
            with server.connect(audit=False) as db:
                start = time.perf_counter()
                data = operation(db)
                backend_ms = (time.perf_counter() - start) * 1000
                start = time.perf_counter()
                payload = json.dumps(data, ensure_ascii=False, sort_keys=True).encode('utf8')
                serialize_ms = (time.perf_counter() - start) * 1000
            samples.append(dict(backend_ms=backend_ms, serialize_ms=serialize_ms))
        loads = json.loads
        decoded = 0

        def decode(value, *a, **kw):
            nonlocal decoded
            decoded += 1
            return loads(value, *a, **kw)

        # Instrument separately so mocks and tracing do not inflate timings.
        with server.connect(audit=False) as db:
            statements = []
            db.set_trace_callback(statements.append)
            with patch.object(json, 'loads', side_effect=decode):
                operation(db)
            db.set_trace_callback(None)
            plans = [{'sql': sql, 'plan': [r[3] for r in db.execute('EXPLAIN QUERY PLAN ' + sql)]}
                     for sql in statements if sql.startswith(('SELECT count(*) FROM (', 'SELECT x.id,x.target_kind FROM ('))]
        result['operations'][name] = dict(first=samples[0], warm=samples[1:],
                                         median_ms=statistics.median(s['backend_ms'] for s in samples[1:]),
                                         json_decodes=decoded, sql_statements=len(statements),
                                         plans=plans,
                                         response_bytes=len(payload), sha256=hashlib.sha256(payload).hexdigest(),
                                         total=data['total'], ids=[r['id'] for r in data['items']])
        print(name, json.dumps({k: result['operations'][name][k] for k in ('median_ms', 'response_bytes', 'total')}), flush=True)
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding='utf8')


if __name__ == '__main__':
    main()
