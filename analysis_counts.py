"""Disposable, paged indexes of complete immutable statistics snapshots."""
from array import array
import hashlib
import json
import math
import sqlite3
import sys
import time
import unicodedata
import zlib

import long_tasks
import analysis_payload
from material_search_index import writing_cache


BLOCK_SIZE = 512


def drop(db):
    for name, in db.execute("SELECT name FROM sqlite_master WHERE type='trigger' AND name GLOB 'analysis_count_*'").fetchall():
        db.execute('DROP TRIGGER "'+name.replace('"','""')+'"')
    for name in ('analysis_count_garbage','analysis_count_items','analysis_count_positions','analysis_count_blocks','analysis_count_headers','analysis_count_sources','analysis_count_cache'):
        db.execute('DROP TABLE IF EXISTS '+name)


def initialize(db):
    had_garbage=db.execute("SELECT 1 FROM sqlite_master WHERE name='analysis_count_garbage'").fetchone()
    db.executescript('''
        CREATE TABLE IF NOT EXISTS analysis_count_cache(
          key BLOB PRIMARY KEY,statistics TEXT NOT NULL,selection TEXT);
        CREATE TABLE IF NOT EXISTS analysis_count_sources(
          source TEXT,id TEXT,key BLOB NOT NULL,version TEXT,PRIMARY KEY(source,id)) WITHOUT ROWID;
        CREATE INDEX IF NOT EXISTS analysis_count_references ON analysis_count_sources(key);
        CREATE TABLE IF NOT EXISTS analysis_count_garbage(key BLOB PRIMARY KEY,started INTEGER NOT NULL DEFAULT 0);
        CREATE TABLE IF NOT EXISTS analysis_count_items(
          key BLOB,family TEXT,item TEXT,form TEXT,language TEXT,kind TEXT,
          count INTEGER,search_form TEXT,search_gloss TEXT,data TEXT,
          PRIMARY KEY(key,family,item)) WITHOUT ROWID;
        CREATE TABLE IF NOT EXISTS analysis_count_positions(
          key BLOB,family TEXT,item TEXT,indices BLOB,PRIMARY KEY(key,family,item)) WITHOUT ROWID;
        CREATE INDEX IF NOT EXISTS analysis_count_frequency
          ON analysis_count_items(key,family,count DESC,form,language,item);
        CREATE INDEX IF NOT EXISTS analysis_count_forms
          ON analysis_count_items(key,family,form,language,item);
        CREATE TABLE IF NOT EXISTS analysis_count_blocks(
          key BLOB,block INTEGER,data BLOB,PRIMARY KEY(key,block)) WITHOUT ROWID;
        CREATE TABLE IF NOT EXISTS analysis_count_headers(
          key BLOB,view TEXT,total INTEGER,denominator INTEGER,PRIMARY KEY(key,view)) WITHOUT ROWID;
    ''')
    # Removing a recent source must not delete tens of thousands of frequency
    # rows on the foreground path. Saved snapshots share the same reference set.
    for name in ('source','cache','header','position'):
        db.execute('DROP TRIGGER IF EXISTS analysis_count_'+name+'_cleanup')
    db.executescript('''
        CREATE TRIGGER analysis_count_source_cleanup AFTER DELETE ON analysis_count_sources BEGIN
          INSERT INTO analysis_count_garbage SELECT OLD.key,0
            WHERE NOT EXISTS(SELECT 1 FROM analysis_count_sources WHERE key=OLD.key)
              AND NOT EXISTS(SELECT 1 FROM analysis_count_garbage WHERE key=OLD.key);
        END;
        CREATE TRIGGER analysis_count_cache_cleanup AFTER DELETE ON analysis_count_cache BEGIN
          INSERT INTO analysis_count_garbage SELECT OLD.key,1
            WHERE NOT EXISTS(SELECT 1 FROM analysis_count_garbage WHERE key=OLD.key);
        END;
    ''')
    if not had_garbage:
        db.execute('''INSERT INTO analysis_count_garbage SELECT key,0 FROM analysis_count_cache c
          WHERE NOT EXISTS(SELECT 1 FROM analysis_count_sources s WHERE s.key=c.key)''')
    if any(row[1]=='indices' for row in db.execute('PRAGMA table_info(analysis_count_items)')):
        db.execute('''INSERT OR IGNORE INTO analysis_count_positions
          SELECT key,family,item,indices FROM analysis_count_items''')
        db.execute('ALTER TABLE analysis_count_items DROP COLUMN indices')
    for table, source in (('analysis_runs', 'run'), ('analysis_saved', 'saved')):
        columns = 'id,payload,query,version' if source=='run' else 'id,payload,kind,body'
        for suffix, event, references in (('insert','INSERT','NEW.id'), ('delete','DELETE','OLD.id'),
                                          ('update','UPDATE OF '+columns,'OLD.id,NEW.id')):
            name = f'analysis_count_{table}_{suffix}'
            sql = f'''CREATE TRIGGER {name} AFTER {event} ON {table} BEGIN
              DELETE FROM analysis_count_sources WHERE source='{source}' AND id IN ({references}); END'''
            previous = db.execute("SELECT sql FROM sqlite_master WHERE type='trigger' AND name=?",(name,)).fetchone()
            if previous and previous[0] != sql:
                db.execute('DROP TRIGGER '+name)
            if not previous or previous[0] != sql:
                db.execute(sql)
        db.execute(f'''DELETE FROM analysis_count_sources WHERE source=?
          AND NOT EXISTS(SELECT 1 FROM {table} WHERE id=analysis_count_sources.id)''', (source,))


def signature(payload):
    return hashlib.sha256(payload.encode('ascii')).digest()


GARBAGE_PARTS=(('analysis_count_items',('family','item')),
               ('analysis_count_positions',('family','item')),
               ('analysis_count_blocks',('block',)),('analysis_count_headers',('view',)))


def reclaim(db, *, budget_ms=12, batch=128):
    """Bounded idle work. An interrupted/rolled-back batch is safe to repeat."""
    start=time.monotonic();removed=0
    while time.monotonic()-start < budget_ms/1000:
        row=db.execute('SELECT key,started FROM analysis_count_garbage LIMIT 1').fetchone()
        if row is None:break
        key,started=row
        if db.execute('SELECT 1 FROM analysis_count_sources WHERE key=? LIMIT 1',(key,)).fetchone():
            db.execute('DELETE FROM analysis_count_garbage WHERE key=?',(key,));continue
        if not started:
            # The header is the completeness proof. Never publish partially
            # reclaimed indexes as a complete reusable result.
            db.execute('UPDATE analysis_count_garbage SET started=1 WHERE key=?',(key,))
            db.execute('DELETE FROM analysis_count_cache WHERE key=?',(key,))
        for table,fields in GARBAGE_PARTS:
            columns=','.join(fields)
            count=db.execute(f'''DELETE FROM {table} WHERE key=? AND ({columns}) IN
              (SELECT {columns} FROM {table} WHERE key=? LIMIT ?)''',(key,key,batch)).rowcount
            removed+=count
            if count:break
        else:
            db.execute('DELETE FROM analysis_count_garbage WHERE key=?',(key,))
    return dict(removed=removed,pending=bool(db.execute('SELECT 1 FROM analysis_count_garbage LIMIT 1').fetchone()))


def encode(value):
    return json.dumps(value, ensure_ascii=False, separators=(',', ':'))


def packed_indices(indices):
    values = array('Q', indices)
    if sys.byteorder != 'little':
        values.byteswap()
    return values.tobytes()


def unpack_indices(data):
    values = array('Q')
    values.frombytes(data)
    if sys.byteorder != 'little':
        values.byteswap()
    return list(values)


def indexed_row(db, source, identifier, language):
    table = 'analysis_runs' if source=='run' else 'analysis_saved'
    columns = 'r.id,r.language_id,r.created,r.query,r.summary,r.version' if source=='run' else 'r.id,r.language_id,r.kind,r.name,r.notes,r.created,r.body'
    condition = "json_extract(r.query,'$.kind')='counts'" if source=='run' else "r.kind='snapshot' AND json_extract(r.body,'$.query.kind')='counts'"
    try:
        return db.execute('SELECT '+columns+''',s.key _count_key FROM '''+table+''' r
          JOIN analysis_count_sources s ON s.source=? AND s.id=r.id
          JOIN analysis_count_cache c ON c.key=s.key WHERE r.id=? AND r.language_id=? AND '''+condition,
                          (source,identifier,language)).fetchone()
    except sqlite3.OperationalError as error:
        if 'no such table' in str(error):
            return None
        raise


def store_headers(db, key, vocabulary=None):
    if db.execute('SELECT 1 FROM analysis_count_headers WHERE key=? LIMIT 1',(key,)).fetchone():
        return
    for view in ('forms','morphemes','roots','stems','affixes','custom'):
        family = 'forms' if view=='forms' else 'custom' if view=='custom' else 'morphemes'
        kind = {'roots':'root','stems':'stem','affixes':'affix'}.get(view)
        if vocabulary is not None:
            rows = vocabulary.get('selection',{}).get('rows',[]) if family=='custom' else vocabulary[family]
            if kind:
                rows = [row for row in rows if row['kind']==kind]
            total,denominator = len(rows),sum(row['count'] for row in rows)
        else:
            where = 'key=? AND family=?'+(' AND kind=?' if kind else '')
            args = [key,family,*([kind] if kind else [])]
            total,denominator = db.execute('SELECT count(*),COALESCE(sum(count),0) FROM analysis_count_items WHERE '+where,args).fetchone()
        if family=='custom':
            selection = vocabulary.get('selection') if vocabulary is not None else json.loads(db.execute('SELECT selection FROM analysis_count_cache WHERE key=?',(key,)).fetchone()[0] or 'null')
            denominator = selection['occurrences'] if selection else 0
        db.execute('INSERT INTO analysis_count_headers VALUES(?,?,?,?)',(key,view,total,denominator))


def store(db, source, identifier, payload, result=None, version=None):
    if result is None:
        _store(db,source,identifier,payload,result,version)
    else:
        with writing_cache(db):
            _store(db,source,identifier,payload,result,version)


def _store(db, source, identifier, payload, result, version):
    key = signature(payload)
    garbage=db.execute('SELECT started FROM analysis_count_garbage WHERE key=?',(key,)).fetchone()
    exists = db.execute('SELECT 1 FROM analysis_count_cache WHERE key=?', (key,)).fetchone()
    if not exists and (result is None or 'statistics' not in result or 'vocabulary' not in result):
        return
    if garbage and (garbage[0] or not exists):
        # This uncommon explicit re-run/restore owns the writer transaction.
        # Discard an interrupted reclamation before rebuilding the same hash.
        for table,_ in GARBAGE_PARTS:db.execute('DELETE FROM '+table+' WHERE key=?',(key,))
        db.execute('DELETE FROM analysis_count_cache WHERE key=?',(key,))
    db.execute('DELETE FROM analysis_count_garbage WHERE key=?',(key,))
    exists = db.execute('SELECT 1 FROM analysis_count_cache WHERE key=?', (key,)).fetchone()
    if not exists:
        if result is None or 'statistics' not in result or 'vocabulary' not in result:
            return
        vocabulary = result['vocabulary']
        selection = vocabulary.get('selection')
        db.execute('INSERT INTO analysis_count_cache VALUES(?,?,?)',
                   (key, encode(result['statistics']), encode({k:v for k,v in selection.items() if k!='rows'}) if selection else None))
        case = result['statistics'].get('case', True)
        def normalized(value):
            value = unicodedata.normalize('NFC', value)
            return value if case else value.casefold()
        families = [('forms', vocabulary['forms']), ('morphemes', vocabulary['morphemes'])]
        if selection:
            families.append(('custom', selection['rows']))
        for family, rows in families:
            def items():
                for index, row in enumerate(sorted(rows,key=lambda value:value['key'])):
                    if index % 400 == 0:
                        long_tasks.checkpoint()
                    public = {k:v for k,v in row.items() if k!='indices'}
                    yield (key, family, row['key'], row['form'], row['language_id'], row.get('kind', ''),
                           row['count'], normalized(row['form']), normalized(row.get('gloss', '')),
                           encode(public))
            db.executemany('INSERT INTO analysis_count_items VALUES(?,?,?,?,?,?,?,?,?,?)', items())
            db.executemany('INSERT INTO analysis_count_positions VALUES(?,?,?,?)',
                           ((key,family,row['key'],packed_indices(row['indices'])) for row in sorted(rows,key=lambda value:value['key'])))
        hits = result['hits']
        for start in long_tasks.steps(range(0, len(hits), BLOCK_SIZE)):
            block = hits[start:start+BLOCK_SIZE]
            value = ({analysis_payload.COUNTED_HITS:list(analysis_payload.counted_groups(block))}
                     if analysis_payload.can_group_counts(block) else block)
            data = zlib.compress(encode(value).encode('utf-8'), 1)
            db.execute('INSERT INTO analysis_count_blocks VALUES(?,?,?)', (key, start//BLOCK_SIZE, data))
    store_headers(db,key,result['vocabulary'] if result is not None else None)
    db.execute('DELETE FROM analysis_count_sources WHERE source=? AND id=? AND key<>?', (source, identifier, key))
    db.execute('''INSERT INTO analysis_count_sources VALUES(?,?,?,?)
      ON CONFLICT(source,id) DO UPDATE SET version=excluded.version''', (source, identifier, key, version))


def page(db, source, row, request):
    key = row['_count_key'] if '_count_key' in row.keys() else signature(row['payload'])
    try:
        header = db.execute('''SELECT c.statistics,c.selection FROM analysis_count_sources s
          JOIN analysis_count_cache c ON c.key=s.key WHERE s.source=? AND s.id=? AND s.key=?''',
                            (source, row['id'], key)).fetchone()
    except sqlite3.OperationalError as error:
        if 'no such table' in str(error):
            return None
        raise
    if header is None:
        return None
    long_tasks.checkpoint()
    statistics = json.loads(header['statistics'])
    selection = json.loads(header['selection']) if header['selection'] else None
    view = request.get('vocabulary_view', 'overview')
    if view not in ('overview','forms','morphemes','roots','stems','affixes','custom'):
        raise ValueError('词汇统计视图无效')
    order = request.get('vocabulary_order', 'frequency')
    if order not in ('frequency', 'form'):
        raise ValueError('词汇统计排序无效')
    family = 'forms' if view in ('overview', 'forms') else 'custom' if view=='custom' else 'morphemes'
    if family == 'custom' and selection is None:
        raise ValueError('此结果没有自定义条目统计，请重新运行')
    where = 'key=? AND family=?'
    args = [key, family]
    kind = {'roots':'root','stems':'stem','affixes':'affix'}.get(view)
    if kind:
        where += ' AND kind=?'
        args.append(kind)
    totals = db.execute('SELECT total,denominator FROM analysis_count_headers WHERE key=? AND view=?',
                       (key,'forms' if view=='overview' else view)).fetchone()
    denominator = totals[1] if totals else selection['occurrences'] if family=='custom' else db.execute(
        'SELECT COALESCE(sum(count),0) FROM analysis_count_items WHERE '+where, args).fetchone()[0]
    query = request.get('vocabulary_query', '')
    if not isinstance(query, str) or len(query)>2000:
        raise ValueError('词频筛选内容无效')
    needle = unicodedata.normalize('NFC', query.strip())
    if not statistics.get('case', True):
        needle = needle.casefold()
    if needle:
        where += ' AND (instr(search_form,?)>0'+(' OR instr(search_gloss,?)>0' if family!='forms' else '')+')'
        args.extend([needle] * (2 if family!='forms' else 1))
    total = totals[0] if totals and not needle else db.execute('SELECT count(*) FROM analysis_count_items WHERE '+where, args).fetchone()[0]
    pages = max(1, math.ceil(total/100))
    try:
        requested_page = int(request.get('vocabulary_page', 1))
    except (ValueError, TypeError):
        raise ValueError('词频页码无效')
    current = max(1, min(requested_page, pages))
    selected = None
    indices = []
    rows = []
    example_total = 0
    if request.get('vocabulary_item'):
        found = db.execute('SELECT data FROM analysis_count_items WHERE '+where+' AND item=?',
                           [*args, request['vocabulary_item']]).fetchone()
        if found is None:
            raise ValueError('词频项目已不存在于当前结果中')
        selected = json.loads(found[0])
        example_total = db.execute('SELECT length(indices)/8 FROM analysis_count_positions WHERE key=? AND family=? AND item=?',
                                  (key,family,request['vocabulary_item'])).fetchone()[0]
        pages = max(1, math.ceil(example_total/30))
        current = max(1, min(requested_page, pages))
        data = db.execute('SELECT substr(indices,?,240) FROM analysis_count_positions WHERE key=? AND family=? AND item=?',
                          ((current-1)*240+1, key, family, request['vocabulary_item'])).fetchone()[0]
        indices = unpack_indices(data)
    elif view != 'overview':
        ordering = 'count DESC,form,language,item' if order=='frequency' else 'form,language,item'
        rows = [json.loads(r[0]) for r in db.execute('SELECT data FROM analysis_count_items WHERE '+where+
                ' ORDER BY '+ordering+' LIMIT 100 OFFSET ?', [*args, (current-1)*100])]
    profile = dict(view=view,order=order,total=total,denominator=denominator,page=current,pages=pages,
                   rows=rows,selected=selected,example_total=example_total)
    if selection:
        profile['selection'] = selection
    blocks = {}
    for number in dict.fromkeys(index//BLOCK_SIZE for index in indices):
        data = db.execute('SELECT data FROM analysis_count_blocks WHERE key=? AND block=?', (key, number)).fetchone()
        value = json.loads(zlib.decompress(data[0]))
        blocks[number] = ([hit for group in value[analysis_payload.COUNTED_HITS] for hit in analysis_payload.count_hits(group)]
                          if isinstance(value,dict) else value)
    hits = [{**blocks[index//BLOCK_SIZE][index%BLOCK_SIZE], 'index':index} for index in indices]
    return statistics, profile, hits
