"""Narrow sentence identities for scope filtering without scanning source JSON pages."""
import long_tasks
import record_sources
import material_search_index


def initialize(db):
    existed = db.execute("SELECT 1 FROM sqlite_master WHERE name='sentence_scope_dirty'").fetchone()
    native = record_sources.native(db)
    fields = 'source_language TEXT,grammaticality TEXT' if native else 'body TEXT'
    record_sources.schema_sql(db, f'''
        CREATE TABLE IF NOT EXISTS sentence_scope_records(
          kind TEXT,id TEXT,text_id TEXT,position INTEGER,source_rowid INTEGER,
          language_id TEXT,{fields},n INTEGER,PRIMARY KEY(kind,id)) WITHOUT ROWID;
        CREATE INDEX IF NOT EXISTS sentence_scope_language
          ON sentence_scope_records(kind,language_id,source_rowid,id);
        CREATE INDEX IF NOT EXISTS sentence_scope_text
          ON sentence_scope_records(kind,text_id,position,id);
        CREATE TABLE IF NOT EXISTS sentence_scope_dirty(
          kind TEXT,id TEXT,PRIMARY KEY(kind,id)) WITHOUT ROWID;
    ''')
    if native and 'body' in {r[1] for r in db.execute('PRAGMA table_info(sentence_scope_records)')}:
        db.execute('ALTER TABLE sentence_scope_records ADD COLUMN source_language TEXT')
        db.execute('ALTER TABLE sentence_scope_records ADD COLUMN grammaticality TEXT')
        db.execute("UPDATE sentence_scope_records SET source_language=body->>'$.language_id',grammaticality=body->>'$.grammaticality'")
        db.execute('ALTER TABLE sentence_scope_records DROP COLUMN body')
    for table, kind in (('entries', 'corpus'), ('dictionary_examples', 'independent')):
        for event in ('INSERT', 'UPDATE', 'DELETE'):
            refs = ('OLD','NEW') if event=='UPDATE' else ('OLD',) if event=='DELETE' else ('NEW',)
            when = ''
            if event == 'UPDATE':
                fields = ('id','text_id','position') if kind=='corpus' else ('id','language_id')
                changed = [f'OLD.{field} IS NOT NEW.{field}' for field in ('rowid',*fields)]
                checks=[f"json_extract(OLD.body,'$.{field}') IS NOT json_extract(NEW.body,'$.{field}')"
                        for field in ('language_id','grammaticality')]
                changed.append(record_sources.change_sql(db,table,record_sources.SCOPE,' OR '.join(checks)))
                when = ' WHEN '+' OR '.join(changed)
            body = ''.join(f'''INSERT INTO sentence_scope_dirty SELECT '{kind}',{ref}.id
              WHERE NOT EXISTS(SELECT 1 FROM sentence_scope_dirty WHERE kind='{kind}' AND id={ref}.id);'''
                           for ref in refs)
            name=f'sentence_scope_{table}_{event}'
            sql=f'CREATE TRIGGER {name} AFTER {event} ON {table}{when} BEGIN {body} END'
            previous=db.execute("SELECT sql FROM sqlite_master WHERE type='trigger' AND name=?",(name,)).fetchone()
            if previous and previous[0]==sql:continue
            if previous:db.execute('DROP TRIGGER '+name)
            db.execute(sql)
    if not existed:
        db.execute("INSERT INTO sentence_scope_dirty SELECT 'corpus',id FROM entries UNION ALL SELECT 'independent',id FROM dictionary_examples")


def drop(db):
    for name, in db.execute("SELECT name FROM sqlite_master WHERE type='trigger' AND name GLOB 'sentence_scope_*'").fetchall():
        db.execute('DROP TRIGGER "'+name.replace('"','""')+'"')
    for name in ('sentence_scope_records','sentence_scope_dirty'):
        db.execute('DROP TABLE IF EXISTS '+name)


def available(db):
    return bool(db.execute("SELECT 1 FROM sqlite_master WHERE name='sentence_scope_dirty'").fetchone())


def pending(db):
    if not available(db):
        return 0
    return db.execute('SELECT count(*) FROM (SELECT 1 FROM sentence_scope_dirty LIMIT 201)').fetchone()[0]


def refresh(db):
    native = record_sources.native(db)
    for table, kind in (('entries', 'corpus'), ('dictionary_examples', 'independent')):
        while rows := db.execute('SELECT id FROM sentence_scope_dirty WHERE kind=? LIMIT 400',(kind,)).fetchall():
            ids = [row[0] for row in rows]
            marks = ','.join('?' for _ in ids)
            db.execute('DELETE FROM sentence_scope_records WHERE kind=? AND id IN ('+marks+')',[kind,*ids])
            text = 'e.text_id' if kind=='corpus' else 'NULL'
            position = 'e.position' if kind=='corpus' else 'e.rowid'
            language = "''" if kind=='corpus' else 'e.language_id'
            columns = ('source_language,grammaticality' if native else 'body')
            fields = ('s.language_id,s.grammaticality' if native else
                      "json_object('language_id',json_extract(e.body,'$.language_id'),'grammaticality',json_extract(e.body,'$.grammaticality'))")
            header = "JOIN sentence_text_rows s ON s.kind=o.kind AND s.owner_id=e.id" if native else ''
            db.execute(f'''INSERT INTO sentence_scope_records(kind,id,text_id,position,source_rowid,language_id,{columns},n)
              SELECT ?,e.id,{text},{position},e.rowid,{language},
                {fields},o.n FROM {table} e JOIN sentence_hit_owners o ON o.kind=? AND o.id=e.id
                {header} WHERE e.id IN ({marks})''',
                       [kind,kind,*ids])
            db.execute('DELETE FROM sentence_scope_dirty WHERE kind=? AND id IN ('+marks+')',[kind,*ids])
            long_tasks.checkpoint()


def narrow(db, scope):
    native = record_sources.native(db)
    prefix = ('SELECT e.id,e.text_id,e.position,e.revision,t.title,' if native else
              'SELECT e.id,e.text_id,e.position,e.body,e.revision,t.title,')
    library = native and any(f"SELECT '{kind}' kind,e.id," in scope for kind in ('corpus','independent'))
    if prefix not in scope and not library:
        return scope
    if not db.execute("SELECT 1 FROM sqlite_master WHERE name='sentence_scope_dirty'").fetchone():
        return scope
    try:
        with material_search_index.preparing(db):
            refresh(db)
    except material_search_index.Unavailable:
        return scope
    fields = 'source_language,grammaticality' if native else 'body'
    columns = f'id,text_id,position,source_rowid AS rowid,language_id,{fields},0 revision,n'
    scope = scope.replace('SELECT e.id,','SELECT e.n AS _scope_n,e.id,')
    for table, kind in (('entries','corpus'),('dictionary_examples','independent')):
        if library:
            scope = scope.replace(f"SELECT '{kind}' kind,e.id,", f"SELECT e.n AS _scope_n,'{kind}' kind,e.id,")
        scope = scope.replace(f'FROM {table} e ',
            f"FROM (SELECT {columns} FROM sentence_scope_records WHERE kind='{kind}') e ")
        if native:
            scope = scope.replace(source_join(kind),'')
    if native:
        scope = scope.replace('s.language_id','e.source_language').replace('s.grammaticality','e.grammaticality')
    if library:
        # The matching scope only needs identity and ordering. Titles come from the visible rows.
        scope = scope.replace('s.source','NULL')
    return scope


def source_join(kind):
    return f" JOIN sentence_text_rows s ON s.kind='{kind}' AND s.owner_id=e.id"
