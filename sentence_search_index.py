"""Disposable SQL search keys for scalar sentence fields and lexical forms.

Source documents and stable units remain authoritative. Effective words share
structural recipes. Morphological forms are derived with the existing reader, separately
from the cheap scalar/form projection. Source triggers cover undo and external
writes; dirty work and its publication share the caller's transaction.
"""
import copy
import json
import sqlite3
from collections import OrderedDict, defaultdict

import corpus
import gloss_inheritance
import long_tasks
import gloss_search_index
import material_search_index

VERSION = 'sentence-fields-v3'
FIELDS = frozenset(('ipa', 'translation', 'notes', 'form', 'morpheme', 'gloss', 'all', 'original', 'layers', 'writings'))


def supports(field):
    return isinstance(field,str) and (field in FIELDS or field.startswith(('layer:','writing:')))
TABLES = ('sentence_search_postings', 'sentence_search_values',
          'sentence_search_dirty', 'sentence_search_owners', 'sentence_search_version')
SOURCES = (('entries', 'corpus', 'id'), ('dictionary_examples', 'independent', 'id'),
           ('text_info', 'text', 'text_id'))


def drop_triggers(db):
    for table, _, _ in SOURCES:
        for event in ('INSERT', 'UPDATE', 'DELETE'):
            db.execute(f'DROP TRIGGER IF EXISTS sentence_search_{table}_{event}')
    for event in ('INSERT', 'UPDATE', 'DELETE'):
        db.execute(f'DROP TRIGGER IF EXISTS sentence_search_bindings_{event}')
    db.execute('DROP TRIGGER IF EXISTS sentence_search_meaning')


def drop(db):
    """Portable snapshots omit all regenerable search data and trusted triggers."""
    drop_triggers(db)
    db.execute('DROP TABLE IF EXISTS sentence_search_fts')
    for table in TABLES:
        db.execute('DROP TABLE IF EXISTS ' + table)
    material_search_index.drop(db)
    gloss_search_index.drop(db)
    db.execute('DROP TABLE IF EXISTS projection_search_fts')
    db.execute('DROP TABLE IF EXISTS projection_search_values')


def initialize(db):
    db.executescript('''
        CREATE TABLE IF NOT EXISTS sentence_search_values(
          id INTEGER PRIMARY KEY,value TEXT NOT NULL UNIQUE,folded TEXT NOT NULL,
          reversed_value TEXT NOT NULL,reversed_folded TEXT NOT NULL);
        CREATE INDEX IF NOT EXISTS sentence_search_folded ON sentence_search_values(folded);
        CREATE INDEX IF NOT EXISTS sentence_search_reverse ON sentence_search_values(reversed_value);
        CREATE INDEX IF NOT EXISTS sentence_search_reverse_folded ON sentence_search_values(reversed_folded);
        CREATE TABLE IF NOT EXISTS sentence_search_postings(
          kind TEXT,owner_id TEXT,field TEXT,word INTEGER,value_id INTEGER,unit_id TEXT,
          PRIMARY KEY(kind,owner_id,field,word,value_id)) WITHOUT ROWID;
        CREATE INDEX IF NOT EXISTS sentence_search_value_owners
          ON sentence_search_postings(value_id,field,kind,owner_id,word);
        CREATE TABLE IF NOT EXISTS sentence_search_dirty(
          kind TEXT,owner_id TEXT,basic INTEGER NOT NULL,morph INTEGER NOT NULL,
          PRIMARY KEY(kind,owner_id)) WITHOUT ROWID;
        CREATE INDEX IF NOT EXISTS sentence_search_basic_dirty ON sentence_search_dirty(kind,owner_id) WHERE basic=1;
        CREATE INDEX IF NOT EXISTS sentence_search_morph_dirty ON sentence_search_dirty(kind,owner_id) WHERE morph=1;
        CREATE TABLE IF NOT EXISTS sentence_search_owners(
          kind TEXT,owner_id TEXT,PRIMARY KEY(kind,owner_id)) WITHOUT ROWID;
        CREATE TABLE IF NOT EXISTS sentence_search_version(value TEXT PRIMARY KEY);
    ''')
    previous=db.execute('SELECT value FROM sentence_search_version LIMIT 1').fetchone()
    compatible=previous and previous[0] in ('sentence-fields-v1','sentence-fields-v2')
    if compatible:
        # Existing fields keep their meaning. Only the newly supported literal
        # original/text-note keys need refreshing; preserve prepared large keys.
        for table,kind in (('entries','corpus'),('dictionary_examples','independent')):
            affected=f"SELECT id FROM {table} WHERE COALESCE(json_extract(body,'$.original'),'')!='' OR COALESCE(json_extract(body,'$.text_notes'),'')!=''"
            db.execute('INSERT OR IGNORE INTO sentence_search_dirty SELECT ?,id,1,0 FROM ('+affected+')',(kind,))
            db.execute('UPDATE sentence_search_dirty SET basic=1 WHERE kind=? AND owner_id IN ('+affected+')',(kind,))
        db.execute('DELETE FROM sentence_search_version')
        db.execute('INSERT INTO sentence_search_version VALUES(?)',(VERSION,))
    elif not db.execute('SELECT 1 FROM sentence_search_version WHERE value=?', (VERSION,)).fetchone():
        db.execute('DELETE FROM sentence_search_postings')
        db.execute('DELETE FROM sentence_search_values')
        db.execute('DELETE FROM sentence_search_dirty')
        db.execute('DELETE FROM sentence_search_owners')
        db.execute('DELETE FROM sentence_search_version')
        db.execute('INSERT INTO sentence_search_version VALUES(?)', (VERSION,))
        db.execute('DROP TABLE IF EXISTS sentence_search_fts')
    had_fts = bool(db.execute("SELECT 1 FROM sqlite_master WHERE name='sentence_search_fts'").fetchone())
    try:
        # The three-character token is only a candidate filter. instr below
        # implements exact literal substring semantics, including punctuation.
        db.execute("CREATE VIRTUAL TABLE IF NOT EXISTS sentence_search_fts USING fts5(value,folded,content='sentence_search_values',content_rowid='id',tokenize='trigram case_sensitive 1',detail=none)")
        if not had_fts:
            db.execute("INSERT INTO sentence_search_fts(sentence_search_fts) VALUES('rebuild')")
    except sqlite3.OperationalError as exc:
        if 'no such module' not in str(exc) and 'tokenizer' not in str(exc):
            raise
    drop_triggers(db)
    for table, kind, identity in SOURCES:
        for event in ('INSERT', 'UPDATE', 'DELETE'):
            ref = 'OLD' if event == 'DELETE' else 'NEW'
            changed = (' WHEN OLD.' + ('metadata' if kind == 'text' else 'body') + ' IS NOT NEW.' +
                       ('metadata' if kind == 'text' else 'body') + f' OR OLD.{identity} IS NOT NEW.{identity}') if event == 'UPDATE' else ''
            previous = f'''INSERT INTO sentence_search_dirty SELECT '{kind}',OLD.{identity},1,{int(kind != 'text')}
                  WHERE OLD.{identity} IS NOT NEW.{identity} AND NOT EXISTS(SELECT 1 FROM sentence_search_dirty WHERE kind='{kind}' AND owner_id=OLD.{identity});
                UPDATE sentence_search_dirty SET basic=1,morph={int(kind != 'text')}
                  WHERE kind='{kind}' AND owner_id=OLD.{identity} AND OLD.{identity} IS NOT NEW.{identity};''' if event == 'UPDATE' else ''
            db.execute(f'''CREATE TRIGGER sentence_search_{table}_{event} AFTER {event} ON {table}{changed}
              BEGIN {previous}
                INSERT INTO sentence_search_dirty SELECT '{kind}',{ref}.{identity},1,{int(kind != 'text')}
                  WHERE NOT EXISTS(SELECT 1 FROM sentence_search_dirty WHERE kind='{kind}' AND owner_id={ref}.{identity});
                UPDATE sentence_search_dirty SET basic=1,morph={int(kind != 'text')}
                  WHERE kind='{kind}' AND owner_id={ref}.{identity};
              END''')
        db.execute(f'''INSERT INTO sentence_search_dirty
            SELECT '{kind}',s.{identity},1,{int(kind != 'text')} FROM {table} s
            WHERE NOT EXISTS(SELECT 1 FROM sentence_search_owners o WHERE o.kind=? AND o.owner_id=s.{identity})
              AND NOT EXISTS(SELECT 1 FROM sentence_search_dirty d WHERE d.kind=? AND d.owner_id=s.{identity})''', (kind, kind))
    for event in ('INSERT', 'UPDATE', 'DELETE'):
        refs = ('OLD', 'NEW') if event == 'UPDATE' else ('OLD',) if event == 'DELETE' else ('NEW',)
        statements = []
        for ref in refs:
            statements.append(f'''INSERT INTO sentence_search_dirty SELECT {ref}.owner_kind,{ref}.owner_id,0,1
                WHERE NOT EXISTS(SELECT 1 FROM sentence_search_dirty WHERE kind={ref}.owner_kind AND owner_id={ref}.owner_id);
                UPDATE sentence_search_dirty SET morph=1 WHERE kind={ref}.owner_kind AND owner_id={ref}.owner_id;''')
        db.execute(f'CREATE TRIGGER sentence_search_bindings_{event} AFTER {event} ON gloss_bindings BEGIN ' + ''.join(statements) + ' END')
    db.execute('''CREATE TRIGGER sentence_search_meaning AFTER UPDATE OF gloss ON gloss_meanings
        WHEN OLD.gloss IS NOT NEW.gloss BEGIN
        INSERT INTO sentence_search_dirty SELECT DISTINCT b.owner_kind,b.owner_id,0,1 FROM gloss_bindings b
          WHERE b.meaning_id=NEW.id AND b.mode='inherit' AND NOT EXISTS(
            SELECT 1 FROM sentence_search_dirty d WHERE d.kind=b.owner_kind AND d.owner_id=b.owner_id);
        UPDATE sentence_search_dirty SET morph=1 WHERE EXISTS(SELECT 1 FROM gloss_bindings b
          WHERE b.meaning_id=NEW.id AND b.mode='inherit' AND b.owner_kind=sentence_search_dirty.kind AND b.owner_id=sentence_search_dirty.owner_id);
        END''')
    gloss_search_index.initialize(db)
    material_search_index.initialize(db)


def available(db):
    return bool(db.execute("SELECT 1 FROM sqlite_master WHERE name='sentence_search_version'").fetchone())


def pending(db, field):
    if not supports(field) or not available(db):
        return 0
    if field == 'gloss':
        return gloss_search_index.pending(db)
    if field == 'all' or field in ('layers','writings') or field.startswith(('layer:','writing:')):
        return min(201,gloss_search_index.pending(db)+material_search_index.pending(db)+
                   (pending(db,'form') if field=='all' else 0))
    flag = 'morph' if field == 'morpheme' else 'basic'
    return db.execute(f'SELECT COUNT(*) FROM (SELECT 1 FROM sentence_search_dirty WHERE {flag}=1 LIMIT 201)').fetchone()[0]


def refresh(db, field):
    """Refresh bounded dirty batches; ordinary meaning edits never dirty scalars."""
    if field == 'gloss':
        return gloss_search_index.refresh(db)
    if field == 'all' or field in ('layers','writings') or field.startswith(('layer:','writing:')):
        if field=='all':
            refresh(db,'form')
        return material_search_index.refresh_custom(db)
    morph = field == 'morpheme'
    flag = 'morph' if morph else 'basic'
    fts = bool(db.execute("SELECT 1 FROM sqlite_master WHERE name='sentence_search_fts'").fetchone())
    values = OrderedDict()
    value_bytes = 0
    analysis = corpus.WordAnalysisCache()
    total = db.execute(f'SELECT COUNT(*) FROM sentence_search_dirty WHERE {flag}=1').fetchone()[0]
    completed = 0

    def intern(text):
        nonlocal value_bytes
        text = corpus.normalize(text, True)
        saved = values.get(text)
        if saved is not None:
            values.move_to_end(text)
            return saved
        folded = text.casefold()
        row = db.execute('SELECT id FROM sentence_search_values WHERE value=?', (text,)).fetchone()
        if row is None:
            vid = db.execute('INSERT INTO sentence_search_values(value,folded,reversed_value,reversed_folded) VALUES(?,?,?,?)',
                             (text, folded, text[::-1], folded[::-1])).lastrowid
            if fts:
                db.execute('INSERT INTO sentence_search_fts(rowid,value,folded) VALUES(?,?,?)', (vid, text, folded))
        else:
            vid = row[0]
        size = 128 + 4 * len(text)
        if size <= 1024 * 1024:
            values[text] = vid
            # Keep refresh memory independent of vocabulary size.
            value_bytes += size
            while len(values) > 2048 or value_bytes > 8 * 1024**2:
                evicted, _ = values.popitem(last=False)
                value_bytes -= 128 + 4 * len(evicted)
        return vid

    while batch := db.execute(f'SELECT kind,owner_id FROM sentence_search_dirty WHERE {flag}=1 LIMIT 200').fetchall():
        for kind in ('corpus', 'independent', 'text'):
            ids = [r['owner_id'] for r in batch if r['kind'] == kind]
            if not ids:
                continue
            marks = ','.join('?' for _ in ids)
            table = 'entries' if kind == 'corpus' else 'dictionary_examples' if kind == 'independent' else 'text_info'
            identity = 'text_id' if kind == 'text' else 'id'
            rows = {r['rid']: r for r in db.execute(f'SELECT {identity} rid,' + ('metadata' if kind == 'text' else 'body') + f' body FROM {table} WHERE {identity} IN ({marks})', ids)}
            unit_ids = {(r['entry_id'], r['position']): r['id'] for r in db.execute(f"SELECT entry_id,position,id FROM corpus_units WHERE kind='word' AND active=1 AND entry_id IN ({marks})", ids)} if kind == 'corpus' else {}
            if morph:
                gloss_inheritance.prefetch(db, kind, list(rows))
            long_tasks.checkpoint(100 * completed / max(1, total), '正在更新句子检索索引…')
            for rid in long_tasks.steps(ids):
                old = {r[0] for r in db.execute('SELECT value_id FROM sentence_search_postings WHERE kind=? AND owner_id=? AND ' + ("field='morpheme'" if morph else "field!='morpheme'"), (kind, rid))}
                db.execute('DELETE FROM sentence_search_postings WHERE kind=? AND owner_id=? AND ' + ("field='morpheme'" if morph else "field!='morpheme'"), (kind, rid))
                row = rows.get(rid)
                postings = set()
                if row:
                    body = gloss_inheritance.load(db, kind, rid, row['body'], metadata=False, lightweight=True) if morph else json.loads(row['body'])
                    def add(name, word, value, uid=None):
                        if value:
                            postings.add((kind, rid, name, word, intern(value), uid))
                    if kind == 'text':
                        add('notes', -1, corpus.plain(body.get('notes', '')))
                    elif not morph:
                        for name in ('ipa', 'translation', 'notes', 'language_notes', 'text_notes', 'original'):
                            add(name, -1, body.get(name,'') if name=='original' else corpus.plain(body.get(name, '')))
                        for i, word in enumerate(body.get('words', [])):
                            if not corpus.boundary_count(word['form']):
                                add('form', i, corpus.clean(word['form']), unit_ids.get((rid, i), word.get('annotation_id')))
                    else:
                        for i, word in enumerate(body.get('words', [])):
                            if corpus.boundary_count(word['form']):
                                continue
                            # Match corpus.match's one-word morphology precisely.
                            one = corpus.analyze(dict(ipa='', translation='', words=[copy.deepcopy(word)]), cache=analysis)
                            for unit in one['words'][0]['morphemes']:
                                add('morpheme', i, unit['form'], unit_ids.get((rid, i), word.get('annotation_id')))
                    db.executemany('INSERT INTO sentence_search_postings VALUES(?,?,?,?,?,?)', postings)
                    db.execute('INSERT INTO sentence_search_owners SELECT ?,? WHERE NOT EXISTS(SELECT 1 FROM sentence_search_owners WHERE kind=? AND owner_id=?)', (kind, rid, kind, rid))
                else:
                    db.execute('DELETE FROM sentence_search_owners WHERE kind=? AND owner_id=?', (kind, rid))
                db.execute(f'UPDATE sentence_search_dirty SET {flag}=0 WHERE kind=? AND owner_id=?', (kind, rid))
                db.execute('DELETE FROM sentence_search_dirty WHERE kind=? AND owner_id=? AND basic=0 AND morph=0', (kind, rid))
                # Remove obsolete values, without rescanning the full value table.
                for vid in old:
                    if db.execute('SELECT 1 FROM sentence_search_postings WHERE value_id=? LIMIT 1', (vid,)).fetchone():
                        continue
                    value = db.execute('SELECT value,folded FROM sentence_search_values WHERE id=?', (vid,)).fetchone()
                    if value:
                        if values.pop(value['value'], None) is not None:
                            value_bytes -= 128 + 4 * len(value['value'])
                        if fts:
                            db.execute("INSERT INTO sentence_search_fts(sentence_search_fts,rowid,value,folded) VALUES('delete',?,?,?)", (vid, value['value'], value['folded']))
                        db.execute('DELETE FROM sentence_search_values WHERE id=?', (vid,))
                completed += 1


def value_query(db, query, case, mode):
    key = 'value' if case else 'folded'
    needle = corpus.normalize(query, case)
    if mode == 'exact':
        return f'SELECT id FROM sentence_search_values WHERE {key}=?', [needle]
    if mode in ('prefix', 'suffix'):
        if mode == 'suffix':
            key = 'reversed_' + key
            needle = needle[::-1]
        chars = list(needle)
        while chars and ord(chars[-1]) == 0x10ffff:
            chars.pop()
        code = ord(chars[-1]) + 1 if chars else None
        if code == 0xd800:
            code = 0xe000
        upper = ''.join(chars[:-1]) + chr(code) if chars else None
        return ('SELECT id FROM sentence_search_values WHERE ' + key + '>=?' + (' AND ' + key + '<?' if upper else ''), [needle, upper] if upper else [needle])
    sql = 'SELECT id FROM sentence_search_values WHERE '
    args = []
    if len(needle) >= 3 and '\0' not in needle and db.execute("SELECT 1 FROM sqlite_master WHERE name='sentence_search_fts'").fetchone():
        token = needle[:3].replace('"', '""')
        sql += 'id IN (SELECT rowid FROM sentence_search_fts WHERE sentence_search_fts MATCH ?) AND '
        # detail=none has no column filters. Searching both columns is a safe
        # superset; instr on the selected key below enforces case exactly.
        args.append('"' + token + '"')
    # Short strings and missing FTS support scan deduplicated keys in SQLite.
    return sql + f'instr({key},?)>0', args + [needle]


def search(db, scope, args, field, query, case=False, mode='contains', page=1, size=20,
           text_notes=False, ids_only=False, custom_language='all', include_original=False):
    """Return None for unsupported/old databases; all normal hits stay in SQL."""
    if not supports(field) or not query or not available(db) or field=='original' and not include_original:
        return None
    if field in ('all','gloss','layers','writings') or field.startswith(('layer:','writing:')):
        if not material_search_index.available(db):
            return None
    if not db.in_transaction:
        db.execute('BEGIN')
    try:
        with material_search_index.preparing(db):
            refresh(db, field)
    except material_search_index.Unavailable:
        return None
    if field == 'gloss':
        if not gloss_search_index.available(db):
            return None
        raw, params = gloss_search_index.hits(db,query,case,mode)
    elif field=='all' or field in ('layers','writings') or field.startswith(('layer:','writing:')):
        if not gloss_search_index.available(db) or not material_search_index.available(db):
            return None
        raw, params = material_search_index.custom_hits(db,field,query,case,mode,custom_language)
        if field=='all':
            word_hits,word_args=gloss_search_index.hits(db,query,case,mode,all_fields=True)
            values,scalar_args=value_query(db,query,case,mode)
            scalar_fields="('ipa','translation','notes','language_notes','text_notes','original')" if include_original else "('ipa','translation','notes','language_notes')"
            raw+=' UNION '+word_hits+f' UNION SELECT kind,owner_id id,word FROM sentence_search_postings WHERE value_id IN ({values}) AND field IN '+scalar_fields
            params+=word_args+scalar_args
            if text_notes:
                raw+=f" UNION SELECT kind,owner_id id,word FROM sentence_search_postings WHERE kind='text' AND field='notes' AND value_id IN ({values})"
                params+=scalar_args
    else:
        values, params = value_query(db, query, case, mode)
        fields = ("('notes','language_notes')" if text_notes else "('notes','language_notes','text_notes')") if field == 'notes' else '(?)'
        if field != 'notes':
            params.append(field)
        # The surrounding scope preserves each caller's owner/actual-language rules.
        raw = f'SELECT p.kind,p.owner_id id,p.word FROM sentence_search_postings p WHERE p.value_id IN ({values}) AND p.field IN {fields}'
    cte = 'WITH scope AS (SELECT id,kind,text_id,position,ordering,source_order FROM (' + scope + ')),raw_hits AS MATERIALIZED (' + raw + '),'
    bindings = list(args) + params
    hits = "SELECT kind,id,word FROM raw_hits WHERE kind!='text'"
    if field in ('notes','all') and text_notes:
        hits += " UNION SELECT r.kind,r.id,-1 FROM scope r JOIN raw_hits h ON h.kind='text' AND h.id=r.text_id WHERE r.kind='corpus'"
    cte += 'hits AS MATERIALIZED (SELECT DISTINCT kind,id,word FROM (' + hits + ')) '
    order = ' ORDER BY source_order,ordering,position'
    # Materialize only narrow identities in SQLite's per-connection temporary
    # storage. Counts, pages, positions and code summaries share one match pass.
    # No full hit list or off-page sentence document crosses into Python.
    db.execute('DROP TABLE IF EXISTS temp.sentence_query_hits')
    db.execute('DROP TABLE IF EXISTS temp.sentence_query_matches')
    db.execute('CREATE TEMP TABLE sentence_query_hits(kind TEXT,id TEXT,word INTEGER,text_id TEXT,position INTEGER,ordering INTEGER,source_order INTEGER,PRIMARY KEY(kind,id,word)) WITHOUT ROWID')
    db.execute(cte + 'INSERT INTO sentence_query_hits SELECT h.kind,h.id,h.word,r.text_id,r.position,r.ordering,r.source_order FROM hits h JOIN scope r ON r.kind=h.kind AND r.id=h.id ORDER BY h.kind,h.id,h.word', bindings)
    db.execute('CREATE TEMP TABLE sentence_query_matches AS SELECT id,kind,text_id,position,ordering,source_order FROM sentence_query_hits GROUP BY kind,id')
    db.execute('CREATE INDEX sentence_query_order ON sentence_query_matches(source_order,ordering,position)')
    if ids_only:
        result = {'ids': [r[0] for r in db.execute('SELECT id FROM sentence_query_matches' + order)]}
        db.execute('DROP TABLE sentence_query_hits');db.execute('DROP TABLE sentence_query_matches')
        return result
    total = db.execute('SELECT COUNT(*) FROM sentence_query_matches').fetchone()[0]
    tokens = db.execute('SELECT COUNT(*) FROM sentence_query_hits WHERE word>=0').fetchone()[0]
    page = min(max(1, int(page)), max(1, (total + size - 1) // size))
    keys = list(db.execute('SELECT * FROM sentence_query_matches' + order + ' LIMIT ? OFFSET ?', [size, (page - 1) * size]))
    positions = defaultdict(list)
    if keys:
        marks = ','.join('(?,?)' for _ in keys)
        pairs = [v for r in keys for v in (r['kind'], r['id'])]
        for r in db.execute(f'SELECT kind,id,word FROM sentence_query_hits WHERE word>=0 AND (kind,id) IN ({marks}) ORDER BY word', pairs):
            positions[(r['kind'], r['id'])].append(r['word'])
    import code_switching
    codes = list(db.execute('SELECT c.* FROM code_sentence_index c JOIN sentence_query_matches m ON m.kind=c.owner_kind AND m.id=c.record_id'))
    result = dict(total=total, tokens=tokens, page=page, keys=keys, positions=positions,
                  code_summary=code_switching.summary_rows(db, codes))
    db.execute('DROP TABLE sentence_query_hits');db.execute('DROP TABLE sentence_query_matches')
    return result
