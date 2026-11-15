"""Typed snapshots attached to independent-example links and word slots."""
from collections import defaultdict
from hashlib import sha256
import json
from struct import pack


REF_COLUMNS = ('ref_form', 'ref_gloss', 'ref_unit_form', 'ref_unit_gloss', 'ref_detached', 'ref_snapshot')
REF_FIELDS = ('form', 'gloss', 'unit_form', 'unit_gloss')
WHOLE_REF_FIELDS = frozenset(('word','key','fragments',*REF_FIELDS))
DETACHED_REF_FIELDS = WHOLE_REF_FIELDS|{'detached'}
WORD_FIELDS = ('form', 'gloss', 'annotation_id', 'unit_id')
NODE_COLUMNS = 'node,parent,slot,value_type,value'
FRAGMENTS = 'independent_link_fragments'
REF_VALUES = 'independent_link_ref_values'
OVERRIDE_VALUES = 'independent_override_values'
FROZEN_VALUES = 'independent_frozen_values'


def enabled(db):
    # The schema only changes at startup or in an explicit migration.
    cached = getattr(db, 'independent_annotations', None)
    if cached is None:
        cached = db.execute("SELECT 1 FROM sqlite_master WHERE name=?", (FRAGMENTS,)).fetchone() is not None
        from record_sources import Connection
        if isinstance(db, Connection):
            db.independent_annotations = cached
    return cached


def encoded(value):
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(',', ':'))


def nodes(value):
    from dictionary_rows import _encode
    return enumerate(_encode(value))


def decode(rows):
    from dictionary_rows import _decode
    return _decode(rows)


def node_stamp(values):
    # The encoder returns only ordered tuples of typed scalar values. Include
    # their order since older binding hashes depend on nested key order.
    return sha256(repr(values).encode('utf-8')).hexdigest()


def fragment_stamp(fragments):
    digest = sha256()
    for part in fragments:
        text = part['text'].encode('utf-8')
        digest.update(pack('>qqQ',part['start'],part['end'],len(text)))
        digest.update(text)
    return digest.hexdigest()


def create(db):
    for col in REF_COLUMNS:
        db.execute(f'ALTER TABLE independent_links ADD COLUMN {col} ' +
                   ('INTEGER' if col == 'ref_detached' else 'TEXT'))
    db.execute(f'''CREATE TABLE {FRAGMENTS}(
        parent_id TEXT NOT NULL,snapshot TEXT NOT NULL,ordinal INTEGER NOT NULL,
        start INTEGER NOT NULL,end INTEGER NOT NULL,text TEXT NOT NULL,
        PRIMARY KEY(parent_id,snapshot,ordinal),
        FOREIGN KEY(parent_id) REFERENCES independent_links(id) ON DELETE CASCADE DEFERRABLE INITIALLY DEFERRED
    ) WITHOUT ROWID''')
    for col in ('snapshot', *WORD_FIELDS, 'word_fields'):
        db.execute(f'ALTER TABLE independent_word_overrides ADD COLUMN {col} ' +
                   ('INTEGER' if col == 'word_fields' else 'TEXT'))
    for table, parent in ((REF_VALUES, 'independent_links'), (OVERRIDE_VALUES, 'independent_word_overrides')):
        db.execute(f'''CREATE TABLE {table}(
            parent_id TEXT NOT NULL,snapshot TEXT NOT NULL,node INTEGER NOT NULL,
            parent INTEGER,slot BLOB,value_type TEXT NOT NULL,value BLOB,
            PRIMARY KEY(parent_id,snapshot,node),
            FOREIGN KEY(parent_id) REFERENCES {parent}(id) ON DELETE CASCADE DEFERRABLE INITIALLY DEFERRED
        ) WITHOUT ROWID''')
    db.execute(f'''CREATE TABLE {FROZEN_VALUES}(
        owner_id TEXT NOT NULL,position INTEGER NOT NULL,node INTEGER NOT NULL,
        parent INTEGER,slot BLOB,value_type TEXT NOT NULL,value BLOB,
        kind TEXT NOT NULL DEFAULT 'independent' CHECK(kind='independent'),
        PRIMARY KEY(owner_id,position,node),
        FOREIGN KEY(kind,owner_id,position) REFERENCES sentence_word_rows(kind,owner_id,position)
            ON DELETE CASCADE DEFERRABLE INITIALLY DEFERRED
    ) WITHOUT ROWID''')


def install_cleanup(db):
    for table, parent, key in ((FRAGMENTS, 'independent_links', 'ref_snapshot'),
                               (REF_VALUES, 'independent_links', 'ref_snapshot'),
                               (OVERRIDE_VALUES, 'independent_word_overrides', 'snapshot')):
        db.execute(f'''CREATE TRIGGER IF NOT EXISTS independent_snapshot_{table} AFTER UPDATE OF {key} ON {parent}
            WHEN OLD.{key} IS NOT NEW.{key} AND OLD.{key} IS NOT NULL
            BEGIN DELETE FROM {table} WHERE parent_id=OLD.id AND snapshot=OLD.{key}; END''')
    for table, column, field, condition in (
            ('independent_links', 'payload', 'segmentation_ref', ''),
            ('sentence_word_rows', 'extra', 'gloss_frozen', "NEW.kind='independent' AND ")):
        for event in ('INSERT', 'UPDATE OF '+column):
            name = 'independent_snapshot_guard_'+field+'_'+event.split()[0].lower()
            db.execute(f'''CREATE TRIGGER IF NOT EXISTS {name} BEFORE {event} ON {table}
                WHEN {condition}json_type(NEW.{column},'$.{field}') IS NOT NULL
                BEGIN SELECT RAISE(ABORT,'该项目的独立例句快照需要新版 Corporium 源码'); END''')


def reference_fields(target, cache=None):
    if 'segmentation_ref' not in target:
        return (None,) * len(REF_COLUMNS), None
    ref = target['segmentation_ref']
    detached = ref.get('detached') if isinstance(ref, dict) else None
    if isinstance(ref, dict) and ref.keys() in (WHOLE_REF_FIELDS, DETACHED_REF_FIELDS):
        fragments = ref['fragments']
        if (type(ref['word']) is int and isinstance(ref['key'], str)
                and all(isinstance(ref[key], str) for key in REF_FIELDS)
                and ('detached' not in ref or isinstance(detached, bool))
                and isinstance(fragments, list) and all(
                    isinstance(part, dict) and set(part) == {'start', 'end', 'text'}
                    and all(type(part[key]) is int and -(2**63) <= part[key] < 2**63 for key in ('start', 'end'))
                    and isinstance(part['text'], str) for part in fragments)):
            stamp = None
            if fragments:
                if cache is None:
                    stamp='f'+fragment_stamp(fragments)
                else:
                    key=tuple((part['start'],part['end'],part['text']) for part in fragments)
                    stamp=cache.get(key)
                    if stamp is None:
                        stamp='f'+fragment_stamp(fragments)
                        if len(cache)<1024:cache[key]=stamp
            return (*(ref[key] for key in REF_FIELDS), detached, stamp), fragments if stamp else None
    values=list(nodes(ref))
    return (None,None,None,None,None if detached is None else bool(detached),'v'+node_stamp(values)),values


def store_references(db, references):
    fragments, values = [], []
    for link, stamp, ref in references:
        if stamp is None:
            continue
        if stamp.startswith('f'):
            fragments.extend((link, stamp, pos, part['start'], part['end'], part['text']) for pos, part in enumerate(ref))
        else:
            values.extend((link, stamp, node, *value) for node, value in ref)
    for table, rows, fields in ((FRAGMENTS, fragments, '(?,?,?,?,?,?)'), (REF_VALUES, values, '(?,?,?,?,?,?,?)')):
        rows.sort()
        for start in range(0,len(rows),400):
            batch=rows[start:start+400]
            db.execute(f'INSERT OR IGNORE INTO {table} VALUES '+','.join([fields]*len(batch)),
                       [field for row in batch for field in row])


def delete_references(db, rows):
    """Delete the batch's active child rows by their composite primary keys."""
    import long_tasks

    groups={'f': [], 'v': []}
    for row in rows:
        if stamp:=row[-1]:groups[stamp[0]].append((row[1],stamp))
    for prefix,table in (('f',FRAGMENTS),('v',REF_VALUES)):
        keys=groups[prefix]
        keys.sort()
        for start in range(0,len(keys),400):
            long_tasks.checkpoint()
            batch=keys[start:start+400]
            # Drive the deletion from the requested pairs. The primary key
            # begins with (parent_id,snapshot) for both child tables.
            db.execute(f'DELETE FROM {table} WHERE (parent_id,snapshot) IN (VALUES '+
                       ','.join(['(?,?)']*len(batch))+')',[part for pair in batch for part in pair])


def read_references(db, links):
    result = {}
    pending = {'f': {}, 'v': {}}
    for row in links:
        stamp = row['ref_snapshot']
        if stamp:
            pending[stamp[0]][row['id']] = stamp
    for prefix, table, columns, order in (('f', FRAGMENTS, 'start,end,text', 'ordinal'),
                                          ('v', REF_VALUES, NODE_COLUMNS, 'node')):
        stamps = pending[prefix]
        ids = list(stamps)
        groups = defaultdict(list)
        for start in range(0, len(ids), 400):
            batch = ids[start:start+400]
            marks = ','.join('?' for _ in batch)
            for row in db.execute(f'''SELECT parent_id,snapshot,{columns} FROM {table}
                    WHERE parent_id IN ({marks}) ORDER BY parent_id,snapshot,{order}''', batch):
                if stamps[row['parent_id']] == row['snapshot']:
                    groups[row['parent_id']].append(row)
        for owner, values in groups.items():
            result[owner] = ([{key: row[key] for key in ('start', 'end', 'text')} for row in values]
                             if prefix == 'f' else decode(values))
        if groups.keys() != stamps.keys():
            raise ValueError('独立例句关联缺少分段快照')
    return result


def read_reference(db, row):
    stamp = row['ref_snapshot']
    if not stamp:
        return reference(row, {})
    owner = row['id']
    if stamp[0] == 'f':
        fragments = [dict(part) for part in db.execute(f'''SELECT start,end,text FROM {FRAGMENTS}
                     WHERE parent_id=? AND snapshot=? ORDER BY ordinal''', (owner, stamp))]
        if fragments:
            return reference(row, {owner: fragments})
    else:
        values = db.execute(f'''SELECT {NODE_COLUMNS} FROM {REF_VALUES}
                            WHERE parent_id=? AND snapshot=? ORDER BY node''', (owner, stamp)).fetchall()
        if values:
            return decode(values)
    raise ValueError('独立例句关联缺少分段快照')


def reference(row, values):
    stamp = row['ref_snapshot']
    if stamp and stamp.startswith('v'):
        return values[row['id']]
    if row['ref_form'] is None:
        return None
    ref = dict(word=row['word_position'], key=row['unit_key'], fragments=values[row['id']] if stamp else [])
    ref.update((key, row['ref_'+key]) for key in REF_FIELDS)
    if row['ref_detached'] is not None:
        ref['detached'] = bool(row['ref_detached'])
    return ref


def override_fields(db, owner, source, word):
    if isinstance(source, str):
        source = json.loads(source)
    mask = sum(1 << i for i, key in enumerate(WORD_FIELDS) if key in word)
    scalar = tuple(word.get(key) for key in WORD_FIELDS)
    values = list(nodes(dict(source=source,extra={key:value for key,value in word.items() if key not in WORD_FIELDS})))
    stamp = node_stamp((mask,scalar,values))
    db.executemany(f'INSERT OR IGNORE INTO {OVERRIDE_VALUES} VALUES(?,?,?,?,?,?,?)',
                   ((owner, stamp, node, *item) for node, item in values))
    return (stamp, *scalar, mask)


def read_overrides(db, rows):
    owners = {row['id']: row for row in rows}
    if not owners:
        return {}
    groups = defaultdict(list)
    ids = list(owners)
    for start in range(0, len(ids), 400):
        batch = ids[start:start+400]
        marks = ','.join('?' for _ in batch)
        for node in db.execute(f'''SELECT * FROM {OVERRIDE_VALUES} WHERE parent_id IN ({marks})
                              ORDER BY parent_id,snapshot,node''', batch):
            if owners[node['parent_id']]['snapshot'] == node['snapshot']:
                groups[node['parent_id']].append(node)
    if groups.keys() != owners.keys():
        raise ValueError('独立例句词格缺少冻结标注')
    result = {}
    for owner, row in owners.items():
        data = decode(groups[owner])
        word = data['extra']
        word.update((key, row[key]) for i, key in enumerate(WORD_FIELDS) if row['word_fields'] & (1 << i))
        result[owner] = data['source'], word
    return result


def frozen_for_owners(db, ids, *, position=None):
    if not ids or not enabled(db):
        return {}
    marks = ','.join('?' for _ in ids)
    groups = defaultdict(list)
    where = '' if position is None else ' AND position=?'
    for row in db.execute(f'''SELECT owner_id,position,{NODE_COLUMNS} FROM {FROZEN_VALUES}
                    WHERE owner_id IN ({marks}){where} ORDER BY owner_id,position,node''',
                          ids if position is None else [*ids, position]):
        groups[row['owner_id'], row['position']].append(row)
    return {key: decode(rows) for key, rows in groups.items()}


def write_frozen(db, owner, position, word, previous=None):
    if previous and 'gloss_frozen' in previous:
        db.execute(f'DELETE FROM {FROZEN_VALUES} WHERE owner_id=? AND position=?', (owner, position))
    if 'gloss_frozen' in word:
        db.executemany(f'''INSERT INTO {FROZEN_VALUES}(owner_id,position,{NODE_COLUMNS})
                       VALUES(?,?,?,?,?,?,?)''',
                       ((owner, position, node, *item) for node, item in nodes(word['gloss_frozen'])))


def frozen_sql(db, alias='w'):
    """Add a frozen list only when an existing derived reader needs a word image."""
    if not enabled(db) or not db.execute(f'SELECT 1 FROM {FROZEN_VALUES} LIMIT 1').fetchone():
        return alias+'.extra'

    def frozen(owner, position, extra):
        rows = db.execute(f'SELECT {NODE_COLUMNS} FROM {FROZEN_VALUES} WHERE owner_id=? AND position=? ORDER BY node',
                          (owner, position)).fetchall()
        return json.dumps(dict(json.loads(extra),gloss_frozen=decode(rows)),ensure_ascii=False,separators=(',',':')) if rows else extra

    register_projection(db,'independent_frozen_extra',3,frozen)
    return (f"CASE WHEN {alias}.kind='independent' AND EXISTS(SELECT 1 FROM {FROZEN_VALUES} f "
            f"WHERE f.owner_id={alias}.owner_id AND f.position={alias}.position) "
            f"THEN independent_frozen_extra({alias}.owner_id,{alias}.position,{alias}.extra) ELSE {alias}.extra END")


def has_frozen_sql(db, alias='w', *, nonempty=False):
    if not enabled(db):
        value = f"{alias}.extra->'$.gloss_frozen'"
        if nonempty:
            kind=f"json_type({alias}.extra,'$.gloss_frozen')"
            return f"({kind} IS NOT NULL AND ({kind}<>'array' OR json_array_length({value})<>0))"
        return f"{value} IS NOT NULL"
    condition = "AND (f.node>0 OR f.value_type<>'array')" if nonempty else 'AND f.node=0'
    return (f'EXISTS(SELECT 1 FROM {FROZEN_VALUES} f WHERE f.owner_id={alias}.owner_id '
            f'AND f.position={alias}.position {condition})')


def override_sql(db, alias='o'):
    """Return SQL for three scalar fields and an optional word image."""
    if not enabled(db):
        return tuple(f"{alias}.word->>'$.{key}'" for key in WORD_FIELDS[:3]) + (f'{alias}.word',)

    def image(owner):
        if owner is None:
            return None
        rows = db.execute('SELECT * FROM independent_word_overrides WHERE id=?', (owner,)).fetchall()
        return json.dumps(read_overrides(db,rows)[owner][1],ensure_ascii=False,separators=(',',':'))

    register_projection(db,'independent_override_image',1,image)
    return tuple(f'{alias}.{key}' for key in WORD_FIELDS[:3]) + (f'independent_override_image({alias}.id)',)


def register_projection(db, name, arguments, function):
    # Replacing an SQL function fails while a batch on this connection is
    # still consuming a cursor. Register each projection once per connection.
    functions=getattr(db,'independent_projections',None)
    if functions is None:
        from record_sources import Connection
        functions=set()
        if isinstance(db,Connection):db.independent_projections=functions
    if name not in functions:
        db.create_function(name,arguments,function)
        functions.add(name)


def detached_sql(db, alias=''):
    prefix = alias+'.' if alias else ''
    return prefix+'ref_detached' if enabled(db) else prefix+"payload->>'$.segmentation_ref.detached'"


def needed(db):
    return not enabled(db) and db.execute("SELECT 1 FROM sqlite_master WHERE name='independent_links'").fetchone() is not None


def migrate(db):
    """Check the round trip before dropping the old copies. Retain undo bytes."""
    import independent_links as links
    from gloss_inheritance import source_hash
    import record_sources
    import save_validation
    from source_schema import same_value

    # Dual mode exists for tests and still writes compatibility documents.
    # Publish this schema only once those documents are no longer written.
    if record_sources.mode(db) not in ('single', 'drop') or not needed(db):
        return False
    if not db.in_transaction:
        db.execute('BEGIN IMMEDIATE')
    prior = save_validation.snapshot(db)
    db.execute('SAVEPOINT independent_annotation_migration')
    try:
        save_validation.drop_triggers(db)
        # Cached facts still describe the same research data. Replace only the
        # auto-match trigger whose UPDATE condition names the retiring column.
        triggers = db.execute("""SELECT name,sql FROM sqlite_master WHERE type='trigger'
          AND tbl_name IN ('independent_links','independent_word_overrides','sentence_word_rows')""").fetchall()
        for name, _ in triggers:
            db.execute('DROP TRIGGER '+save_validation.quote(name))
        create(db)
        if isinstance(db, record_sources.Connection):
            db.independent_annotations = True
        last = None
        while True:
            where, params = ('', ()) if last is None else ('WHERE rowid>?', (last,))
            rows = db.execute(f'SELECT rowid,* FROM independent_links {where} ORDER BY rowid LIMIT 400', params).fetchall()
            if not rows:
                break
            values, references = [], []
            last = rows[-1]['rowid']
            for row in rows:
                target = links.target(row)
                fields, ref = reference_fields(target)
                values.append((links._payload(target, relational=True), *fields, row['rowid']))
                references.append((row['id'], fields[-1], ref))
            store_references(db, references)
            db.executemany('UPDATE independent_links SET payload=?,'+','.join(c+'=?' for c in REF_COLUMNS)+' WHERE rowid=?', values)
            moved = db.execute('SELECT rowid,* FROM independent_links WHERE rowid IN ('+','.join('?' for _ in rows)+') ORDER BY rowid',
                               [row['rowid'] for row in rows]).fetchall()
            for original, new in zip(rows, links.images(db, moved), strict=True):
                if not same_value(links.target(original), links.target(new)):
                    raise ValueError('独立例句关联分段快照迁移校验失败')
        last = None
        while True:
            where, params = ('', ()) if last is None else ('WHERE rowid>?', (last,))
            rows = db.execute(f'SELECT rowid,* FROM independent_word_overrides {where} ORDER BY rowid LIMIT 200', params).fetchall()
            if not rows:
                break
            last = rows[-1]['rowid']
            columns = ('snapshot', *WORD_FIELDS, 'word_fields')
            db.executemany('UPDATE independent_word_overrides SET '+','.join(c+'=?' for c in columns)+' WHERE rowid=?',
                           ((*override_fields(db, row['id'], row['source'], json.loads(row['word'])), row['rowid']) for row in rows))
            moved = db.execute('SELECT rowid,* FROM independent_word_overrides WHERE rowid IN ('+','.join('?' for _ in rows)+') ORDER BY rowid',
                               [row['rowid'] for row in rows]).fetchall()
            for original, new in zip(rows, links.override_images(db, moved), strict=True):
                old_word=json.loads(original['word'])
                if (not same_value(json.loads(original['source']),new['source']) or
                        not same_value(old_word,new['word']) or source_hash(old_word)!=source_hash(new['word'])):
                    raise ValueError('独立例句词格冻结标注迁移校验失败')
        rows = db.execute("""SELECT owner_id,position,extra FROM sentence_word_rows
          WHERE kind='independent' AND json_type(extra,'$.gloss_frozen') IS NOT NULL""").fetchall()
        for start in range(0,len(rows),400):
            batch=rows[start:start+400]
            words={(owner,position):json.loads(extra) for owner,position,extra in batch}
            for (owner,position),word in words.items():
                write_frozen(db,owner,position,word)
            frozen=frozen_for_owners(db,list(dict.fromkeys(owner for owner,_ in words)))
            for key,word in words.items():
                if not same_value(word.pop('gloss_frozen'),frozen[key]):
                    raise ValueError('独立例句正文冻结标注迁移校验失败')
            db.executemany("UPDATE sentence_word_rows SET extra=? WHERE kind='independent' AND owner_id=? AND position=?",
                           ((json.dumps(word,ensure_ascii=False,separators=(',',':')),*key) for key,word in words.items()))
        for column in ('source', 'word'):
            db.execute(f'ALTER TABLE independent_word_overrides DROP COLUMN {column}')
        for name, sql in triggers:
            if name == 'auto_match_independent_word_overrides_UPDATE':
                sql = sql.replace('OLD.word IS NOT NEW.word', 'OLD.snapshot IS NOT NEW.snapshot')
            db.execute(sql)
        install_cleanup(db)
        import material_search_index
        if material_search_index.available(db):
            for table in (FROZEN_VALUES,OVERRIDE_VALUES):
                material_search_index.install_literal_source_triggers(db,table)
        # A first native migration creates these snapshot tables after the
        # ordinary source indexes. Install their external-edit invalidation too.
        import dictionary_cold
        if dictionary_cold.available(db):dictionary_cold.initialize(db)
        save_validation.initialize(db)
        if prior:
            db.execute('UPDATE save_validation_state SET checked_epoch=epoch WHERE id=1')
        for table in (FRAGMENTS, REF_VALUES, OVERRIDE_VALUES, FROZEN_VALUES, 'independent_word_overrides', 'independent_links'):
            if db.execute(f"PRAGMA quick_check('{table}')").fetchone()[0] != 'ok' or db.execute(
                    f"PRAGMA foreign_key_check('{table}')").fetchone():
                raise ValueError('独立例句快照完整性检查未通过')
    except BaseException:
        db.execute('ROLLBACK TO independent_annotation_migration')
        if isinstance(db, record_sources.Connection):
            db.independent_annotations = False
        raise
    finally:
        db.execute('RELEASE independent_annotation_migration')
    return True
