"""Relational source writes, change notifications and portable row images."""
from contextlib import contextmanager
from contextvars import ContextVar
from copy import deepcopy
import json
import sqlite3
from itertools import islice


KINDS = dict(entries='corpus',dictionary_examples='independent',lexemes='lexeme',morphemes='morpheme')
TABLES = frozenset(KINDS)
ATTRIBUTES = dict(entries={'text_id','position'},dictionary_examples={'language_id'},
                  lexemes={'language_id','headword'},morphemes={'language_id','form','number'})
META = {table: ('id', *sorted(fields), 'revision') for table, fields in ATTRIBUTES.items()}
ACTIVE = ContextVar('record_source_write', default=None)
CONTENT, SCOPE, HOME, STATISTICS, WRITING, STRUCTURE = (1 << i for i in range(6))


class Connection(sqlite3.Connection):
    pass


def mode(db):
    if hasattr(db, 'source_mode'):
        return db.source_mode
    if db.execute("SELECT 1 FROM sqlite_master WHERE name='record_source_schema'").fetchone():
        row = db.execute('SELECT mode FROM record_source_schema WHERE id=1').fetchone()
        if row:
            return row[0]
    return 'legacy'


def native(db):
    return mode(db) != 'legacy'


def configure(db):
    if isinstance(db, Connection):
        db.source_mode = mode(db)

    def document(table, owner):
        body = read(db, table, owner)
        return json.dumps(body, ensure_ascii=False) if body is not None else None

    db.create_function('record_document', 2, document)


def document_table(table):
    return table + '_documents' if table in TABLES else table


def drop_views(db):
    for table in KINDS:
        db.execute('DROP VIEW IF EXISTS ' + document_table(table))


def views(db):
    for table in KINDS:
        if not db.execute('SELECT 1 FROM sqlite_master WHERE type=\'table\' AND name=?', (table,)).fetchone():
            continue
        body = f"record_document('{table}',id)" if native(db) else 'body'
        db.execute(f'CREATE VIEW IF NOT EXISTS {document_table(table)} AS '
                   f'SELECT {",".join(META[table])},{body} body,rowid FROM {table}')


def initialize(db):
    db.execute('''CREATE TABLE IF NOT EXISTS record_source_writes(
        source TEXT NOT NULL, owner_id TEXT NOT NULL, flags INTEGER NOT NULL DEFAULT 0,
        PRIMARY KEY(source,owner_id)) WITHOUT ROWID''')
    if 'flags' not in {r[1] for r in db.execute('PRAGMA table_info(record_source_writes)')}:
        db.execute('ALTER TABLE record_source_writes ADD COLUMN flags INTEGER NOT NULL DEFAULT 0')


def is_native(table, owner):
    return (f"EXISTS(SELECT 1 FROM record_source_writes "
            f"WHERE source='{table}' AND owner_id={owner})")


def change_sql(db, table, flags=CONTENT, legacy='OLD.body IS NOT NEW.body'):
    if not native(db):
        return '(' + legacy + ')'
    return (f"EXISTS(SELECT 1 FROM record_source_writes WHERE source='{table}' "
            f'AND owner_id=NEW.id AND flags & {flags} != 0)')


def trigger(db, name, definition):
    sql = f'CREATE TRIGGER {name} {definition}'
    previous = db.execute("SELECT sql FROM sqlite_master WHERE type='trigger' AND name=?", (name,)).fetchone()
    if not previous or previous[0] != sql:
        db.execute('DROP TRIGGER IF EXISTS ' + name)
        db.execute(sql)


def schema_sql(db, script):
    """Execute a schema script without ending a caller's migration transaction."""
    statement = ''
    for part in script.split(';'):
        statement += part + ';'
        if sqlite3.complete_statement(statement):
            if statement.strip() != ';':
                db.execute(statement)
            statement = ''
    if statement.strip():
        raise ValueError('数据库迁移脚本不完整')


def _flags(table, before, after):
    if before == after:
        return 0
    if before is None:
        return CONTENT | SCOPE | HOME | STATISTICS | WRITING | STRUCTURE

    def differs(keys):
        return any(before.get(key) != after.get(key) for key in keys)

    result = CONTENT
    if table in ('entries', 'dictionary_examples'):
        if differs(('language_id', 'grammaticality')):
            result |= SCOPE
        if differs(('language_id', 'ipa', 'original', 'words', 'translation')):
            result |= HOME
    if differs(('orthographies', 'writings', 'word_structure')):
        result |= WRITING
    if differs(('word_structure',)):
        result |= STRUCTURE
    omitted = {'notes', 'translation', 'ipa', 'language_notes'} if table in ('entries','dictionary_examples') else {'notes'}
    if any(key not in omitted and (key not in before or key not in after or before[key] != after[key])
           for key in before.keys() | after.keys()):
        result |= STATISTICS
    return result


@contextmanager
def writing(db, table, owner, before, after, flags):
    if not db.in_transaction:
        db.execute('BEGIN')
    db.execute('SAVEPOINT record_write')
    try:
        db.execute('INSERT INTO record_source_writes(source,owner_id,flags) VALUES(?,?,?)', (table, owner, flags))
        token = ACTIVE.set((table, {owner:(before,after)}))
        try:
            yield
        finally:
            ACTIVE.reset(token)
        db.execute('DELETE FROM record_source_writes WHERE source=? AND owner_id=?',
                   (table, owner))
    except BaseException:
        db.execute('ROLLBACK TO record_write')
        raise
    finally:
        db.execute('RELEASE record_write')


def image(db, table, owner, operation, legacy):
    current = ACTIVE.get()
    if current and current[0] == table and owner in current[1]:
        return current[1][owner][1 if operation in ('insert','after') else 0]
    return read(db, table, owner) if native(db) else legacy


def bump_example_revisions(db, counts, *, minimum=None):
    """Record metadata-only revisions without fetching identical before/after bodies."""
    import long_tasks

    if not counts:
        return
    audit = getattr(db, 'example_revision_journal', None)
    owners = sorted(counts)
    rows = []
    cursor=db.cursor()
    cursor.row_factory=None
    for start in long_tasks.steps(range(0,len(owners),800)):
        ids=owners[start:start+800]
        rows.extend(cursor.execute('SELECT rowid,id,language_id,revision FROM dictionary_examples WHERE id IN ('+
                               ','.join('?' for _ in ids)+')',ids))
    if len(rows)!=len(owners):
        raise ValueError('例句已不存在')
    rows.sort(key=lambda row:row[0])
    # Raw connections still use the legacy capture callback.
    token=ACTIVE.set(('dictionary_examples',{owner:(None,None) for owner in counts})) if audit is None else None
    if audit is not None:db.capturing_example_revisions=True
    try:
        for start in long_tasks.steps(range(0,len(rows),800)):
            batch=rows[start:start+800]
            ids=[row[0] for row in batch]
            if minimum is None and any(counts[row[1]]!=1 for row in batch):
                sql=('WITH revisions(rid,delta) AS (VALUES '+','.join('(?,?)' for _ in batch)+') '
                     'UPDATE dictionary_examples SET revision=dictionary_examples.revision+revisions.delta '
                     'FROM revisions WHERE dictionary_examples.rowid=revisions.rid')
                parameters=[value for row in batch for value in (row[0],counts[row[1]])]
            else:
                revision='revision+1' if minimum is None else 'max(revision,?)+1'
                sql='UPDATE dictionary_examples SET revision='+revision+' WHERE rowid IN ('+','.join('?' for _ in batch)+')'
                parameters=ids if minimum is None else [minimum,*ids]
            if audit is None:
                db.execute(sql,parameters)
                continue
            saved=dict(cursor.execute(sql+' RETURNING rowid,revision',parameters))
            for rowid,owner,language,revision in batch:
                key='dictionary_examples',rowid
                if key in audit:
                    # Keep the source image if another part of this operation
                    # already edited this example's body or language.
                    audit[key][1]=dict(audit[key][1],revision=saved[rowid])
                else:
                    before=dict(rowid=rowid,id=owner,language_id=language,revision=revision,body=None)
                    audit[key]=[before,dict(before,revision=saved[rowid])]
    finally:
        if audit is not None:db.capturing_example_revisions=False
        if token is not None:ACTIVE.reset(token)


@contextmanager
def writing_batch(db,table,images):
    """Publish the row images and source flags for one bounded SQL batch."""
    if not db.in_transaction:
        db.execute('BEGIN')
    db.execute('SAVEPOINT record_batch')
    keys = [(table,owner) for owner in images]
    try:
        db.executemany('INSERT INTO record_source_writes(source,owner_id,flags) VALUES(?,?,?)',
                       ((table,owner,_flags(table,before,after)) for owner,(before,after) in images.items()))
        token = ACTIVE.set((table,images))
        try:
            yield
        finally:
            ACTIVE.reset(token)
        db.executemany('DELETE FROM record_source_writes WHERE source=? AND owner_id=?',keys)
    except BaseException:
        db.execute('ROLLBACK TO record_batch')
        raise
    finally:
        db.execute('RELEASE record_batch')


def object_value(value, *, mutable=True):
    """Give a caller its own structured value, including historical row images."""
    if isinstance(value,(dict,list)):
        return deepcopy(value) if mutable else value
    return json.loads(value)


def body(row, *, mutable=True):
    return object_value(row['body'],mutable=mutable)


def same_body(before, after):
    if before == after:
        return True
    if before is None or after is None:
        return False
    left = before if isinstance(before, dict) else json.loads(before)
    right = after if isinstance(after, dict) else json.loads(after)
    return left == right


def publish(db, table, owner, body, before, columns, *, apply_rows, insert=False, bump=True):
    """Publish one relational change and its metadata in the caller's transaction."""
    allowed=ATTRIBUTES[table]|{'revision'}
    if insert:allowed.add('rowid')
    if not columns.keys()<=allowed:
        raise ValueError('正文行的身份字段无效')
    flags = _flags(table, before, body)
    changed = insert or bool(flags)
    if not changed and not columns and not bump:
        return
    current_mode = mode(db)
    mirror = current_mode in ('legacy', 'dual') and changed
    fields_to_write = dict(columns)
    if mirror:
        fields_to_write['body'] = json.dumps(body, ensure_ascii=False)
    elif insert and current_mode == 'single':
        fields_to_write['body'] = '{}'
    if current_mode != 'legacy' and table == 'lexemes' and changed:
        fields_to_write['homonym_number'] = body.get('homonym_number')
    with writing(db, table, owner, before, body, flags):
        if current_mode != 'legacy' and changed:
            apply_rows()
        if insert:
            fields = ('id', *fields_to_write)
            db.execute(f'INSERT INTO {table}('+','.join(fields)+') VALUES('+
                       ','.join('?' for _ in fields)+')', (owner,*fields_to_write.values()))
        else:
            setters = [f'{name}=?' for name in fields_to_write]
            if bump and 'revision' not in columns:
                setters.append('revision=revision+1')
            if not setters:
                setters.append('revision=revision')
            db.execute(f'UPDATE {table} SET '+','.join(setters)+' WHERE id=?',(*fields_to_write.values(),owner))
        if current_mode == 'legacy':
            apply_rows()


def read(db,table,owner):
    return read_many(db,table,[owner]).get(owner)


def read_many(db,table,ids):
    if table in ('entries','dictionary_examples'):
        import sentence_rows
        return sentence_rows.read(db,KINDS[table],ids)
    import dictionary_rows
    return dictionary_rows.raw_bodies(db,KINDS[table],ids)


def with_bodies(db, table, rows):
    """Attach structured values to metadata rows in bounded batches."""
    iterator = iter(rows)
    while batch := list(islice(iterator, 200)):
        bodies = read_many(db, table, [row['id'] for row in batch])
        for row in batch:
            yield dict(row, body=bodies[row['id']])


def portable_row(row):
    return dict(row, body=json.dumps(row['body'],ensure_ascii=False))


def backup_rows(db,table):
    import independent_links
    if table in independent_links.TABLES:
        return list(independent_links.portable_rows(db,table,db.execute('SELECT rowid,* FROM '+table).fetchall()))
    if table=='analysis_runs':
        return [dict(row) for row in db.execute('SELECT * FROM analysis_run_documents')]
    if table not in TABLES:
        return [dict(row) for row in db.execute('SELECT rowid AS rowid,* FROM '+table)]
    columns = ','.join(META[table])
    rows = db.execute(f'SELECT rowid AS rowid,{columns} FROM {table}')
    return [portable_row(row) for row in with_bodies(db,table,rows)]


def write(db,table,owner,body,*,columns=None,insert=False,bump=True,previous=None):
    if table in ('entries','dictionary_examples'):
        import sentence_rows
        sentence_rows.write(db,KINDS[table],owner,body,columns=columns,insert=insert,bump=bump,previous=previous)
        if table=='dictionary_examples' and 'targets' in body:
            import independent_links
            independent_links.write_targets(db,owner,body['targets'])
    else:
        import dictionary_rows
        dictionary_rows.write(db,KINDS[table],owner,body,columns=columns,insert=insert,bump=bump)
