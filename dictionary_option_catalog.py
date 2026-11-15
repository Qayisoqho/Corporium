"""Disposable search-field contributions from typed dictionary definitions."""
from contextlib import nullcontext
from itertools import groupby, islice
from operator import itemgetter

import dictionary_rows
import long_tasks
import material_search_index
import record_sources


TABLES = ('material_search_option_state','material_search_option_dirty',
          'material_search_option_fields','material_search_option_references','material_search_option_summary')


def initialize(db):
    if not record_sources.native(db):
        return
    record_sources.schema_sql(db, '''
        CREATE TABLE IF NOT EXISTS material_search_option_state(
          kind TEXT,language_id TEXT,PRIMARY KEY(kind,language_id)) WITHOUT ROWID;
        CREATE TABLE IF NOT EXISTS material_search_option_dirty(
          kind TEXT,language_id TEXT,target_id TEXT,
          PRIMARY KEY(kind,language_id,target_id)) WITHOUT ROWID;
        CREATE TABLE IF NOT EXISTS material_search_option_fields(
          kind TEXT,language_id TEXT,target_id TEXT,position INTEGER,ordinal INTEGER,field TEXT,name TEXT,
          PRIMARY KEY(kind,language_id,target_id,ordinal)) WITHOUT ROWID;
        CREATE INDEX IF NOT EXISTS material_search_option_by_field ON
          material_search_option_fields(kind,language_id,field,position,ordinal,name);
        CREATE TABLE IF NOT EXISTS material_search_option_summary(
          kind TEXT,language_id TEXT,field TEXT,position INTEGER,ordinal INTEGER,name TEXT,
          PRIMARY KEY(kind,language_id,field)) WITHOUT ROWID;
        CREATE TABLE IF NOT EXISTS material_search_option_references(
          reference TEXT,kind TEXT,language_id TEXT,target_id TEXT,
          PRIMARY KEY(reference,kind,language_id,target_id)) WITHOUT ROWID;
        CREATE INDEX IF NOT EXISTS material_search_option_reference_owner ON
          material_search_option_references(kind,language_id,target_id);
    ''')
    for kind,(table,_) in dictionary_rows.SOURCES.items():
        for event in ('INSERT','UPDATE','DELETE'):
            refs = ('OLD','NEW') if event == 'UPDATE' else ('OLD',) if event == 'DELETE' else ('NEW',)
            when = ''
            if event == 'UPDATE':
                changed = record_sources.change_sql(db,table)
                when = f''' WHEN OLD.id IS NOT NEW.id OR OLD.language_id IS NOT NEW.language_id
                  OR OLD.rowid IS NOT NEW.rowid OR {changed}'''
            sql = ''.join(f"""INSERT INTO material_search_option_dirty
                SELECT kind,language_id,{ref}.id FROM material_search_option_state
                WHERE kind='{kind}' AND language_id IN ('all',{ref}.language_id)
                ON CONFLICT DO NOTHING;""" for ref in refs)
            record_sources.trigger(db,f'material_search_option_{table}_{event}',f'AFTER {event} ON {table}{when} BEGIN {sql} END')
        for event in ('INSERT','UPDATE','DELETE'):
            refs=('OLD','NEW') if event=='UPDATE' else ('OLD',) if event=='DELETE' else ('NEW',)
            sql=''.join(f"""INSERT INTO material_search_option_dirty
                SELECT s.kind,s.language_id,{ref}.target_id FROM {table} d
                JOIN material_search_option_state s ON s.kind='{kind}' AND s.language_id IN ('all',d.language_id)
                WHERE {ref}.target_kind='{kind}' AND d.id={ref}.target_id
                  AND NOT {record_sources.is_native(table,ref+'.target_id')}
                ON CONFLICT DO NOTHING;""" for ref in refs)
            record_sources.trigger(db,f'material_search_option_value_{kind}_{event}',
                f"AFTER {event} ON dictionary_value_rows WHEN EXISTS(SELECT 1 FROM material_search_option_state WHERE kind='{kind}') BEGIN {sql} END")

    for table in ('writing_types','category_classes','semantic_classes'):
        for event in ('INSERT','UPDATE','DELETE'):
            refs = 'OLD.id,NEW.id' if event == 'UPDATE' else 'OLD.id' if event == 'DELETE' else 'NEW.id'
            when = ''
            if event == 'UPDATE':
                keys = ('id','language_id','name')
                if table == 'writing_types':
                    keys += ('position','space_before','space_after')
                if table == 'category_classes':
                    keys += ('kind',)
                when = ' WHEN ' + ' OR '.join(f'OLD.{key} IS NOT NEW.{key}' for key in keys)
            record_sources.trigger(db,f'material_search_option_{table}_{event}',f'''AFTER {event} ON {table}{when}
                BEGIN INSERT INTO material_search_option_dirty
                    SELECT kind,language_id,target_id FROM material_search_option_references
                    WHERE reference IN ({refs}) ON CONFLICT DO NOTHING;
                END''')


def _shapes(db,kind,owners,all_owners):
    """Stream only the structure and values that can affect field discovery."""
    from dictionary_search import HIDDEN_KEYS, LABELS

    valued = sorted({'label','type','entry_type','space_before','space_after'} |
                    {k for k in LABELS if k.endswith('_id') and k not in HIDDEN_KEYS})
    marks = ','.join('?' for _ in valued)
    sql = f"""SELECT target_id,node,parent,slot,
        CASE value_type WHEN 'object' THEN 1 WHEN 'array' THEN 2 ELSE 0 END,
        CASE WHEN (value IS NOT NULL OR value_type='null') AND slot IN ({marks}) THEN value ELSE 1 END
        FROM dictionary_value_rows WHERE target_kind=?
        AND CASE value_type
            WHEN 'array' THEN slot IS NULL OR slot NOT IN ('features','semantic_classes','speakers')
            WHEN 'object' THEN 1
            WHEN 'null' THEN slot IN ('space_before','space_after')
            ELSE (value IS NOT '' OR slot IN ({marks})) AND slot NOT IN ('id','revision','font','font_variant')
        END"""
    cursor = db.cursor()
    cursor.row_factory = None
    iterator = iter(owners)
    while batch := list(islice(iterator,400 if not all_owners else len(owners))):
        scope = '' if all_owners else ' AND target_id IN ('+','.join('?' for _ in batch)+')'
        rows = cursor.execute(sql+scope+' ORDER BY target_id,node',
                              [*valued,kind,*valued,*([] if all_owners else batch)])
        for owner,nodes in groupby(rows,itemgetter(0)):
            order = {None: -1}
            shape = []
            for _,node,parent,slot,container,value in nodes:
                if slot in HIDDEN_KEYS or parent not in order:
                    continue
                if container:
                    order[node] = len(shape)
                shape.append((order[parent],slot,container,value))
            yield owner,tuple(shape)


def _body(shape):
    nodes = {}
    for node,(parent,slot,container,value) in enumerate(shape):
        if container:
            value = {} if container == 1 else []
            nodes[node] = value
        if parent != -1:
            branch = nodes[parent]
            if isinstance(branch,list):
                branch.append(value)
            else:
                branch[slot] = value
    return nodes[0]


def _contributions(db,index,kind,owners,all_owners,writings):
    import dictionary_data
    from morpheme_search import AFFIX_TYPES

    known = index.fields.keys()
    memo = {}
    for owner,shape in long_tasks.steps(_shapes(db,kind,owners,all_owners)):
        cached = memo.get(shape)
        if cached is None:
            body = _body(shape)
            if kind == 'lexeme':
                # The spelling IDs only serve as keys for the sort in resolve.
                # Their order is already present in the native tree.
                for slot,spelling in enumerate(body.get('orthographies',[])):
                    spelling['id'] = slot
                dictionary_data.resolve(db,body,writings)
            elif body.get('entry_type') not in AFFIX_TYPES:
                body.pop('affix_function',None)
                body.pop('affix_position',None)
            fields = {}
            references = set()
            index.discover((body,),fields=fields,known=known,references=references)
            cached = (tuple(fields.items()),tuple(references))
            if len(memo) < 512 and len(shape) <= 256:
                memo[shape] = cached
        yield owner,*cached


def _ready(db,index,kind,lid):
    table = dictionary_rows.SOURCES[kind][0]
    key = (kind,lid)
    scope = '' if lid == 'all' else ' WHERE language_id=?'
    params = () if lid == 'all' else (lid,)
    ready = db.execute('SELECT 1 FROM material_search_option_state WHERE kind=? AND language_id=?',key).fetchone()
    dirty = [r[0] for r in db.execute('SELECT target_id FROM material_search_option_dirty WHERE kind=? AND language_id=?',key)]
    if ready and not dirty:
        return
    owners = {}
    affected = set()
    if ready:
        for start in range(0,len(dirty),400):
            ids = dirty[start:start+400]
            marks = ','.join('?' for _ in ids)
            match = (' AND ' if scope else ' WHERE ') + f'id IN ({marks})'
            owners.update(db.execute('SELECT id,rowid FROM '+table+scope+match,(*params,*ids)))
            fields_scope = f' WHERE kind=? AND language_id=? AND target_id IN ({marks})'
            affected.update(r[0] for r in db.execute('SELECT field FROM material_search_option_fields'+fields_scope,(*key,*ids)))
            for target in ('material_search_option_fields','material_search_option_references'):
                db.execute(f'DELETE FROM {target}'+fields_scope,(*key,*ids))
    else:
        owners.update(db.execute('SELECT id,rowid FROM '+table+scope,params))
    all_owners = not ready and (lid == 'all' or len(owners) == db.execute(f'SELECT count(*) FROM {table}').fetchone()[0])
    writings = {r['id']:r for r in db.execute('SELECT * FROM writing_types')} if kind == 'lexeme' else {}
    with material_search_index.writing_cache(db) if not ready else nullcontext():
        fields = []
        references = []
        for owner,values,deps in _contributions(db,index,kind,owners,all_owners,writings):
            fields.extend((*key,owner,owners[owner],order,field,name) for order,(field,name) in enumerate(values))
            references.extend((ref,*key,owner) for ref in deps)
            affected.update(field for field,_ in values)
            if len(fields)+len(references)>=4000:
                db.executemany('INSERT INTO material_search_option_fields VALUES(?,?,?,?,?,?,?)',fields)
                db.executemany('INSERT INTO material_search_option_references VALUES(?,?,?,?)',references)
                fields.clear()
                references.clear()
        db.executemany('INSERT INTO material_search_option_fields VALUES(?,?,?,?,?,?,?)',fields)
        db.executemany('INSERT INTO material_search_option_references VALUES(?,?,?,?)',references)
        db.execute('DELETE FROM material_search_option_dirty WHERE kind=? AND language_id=?',key)
        db.execute('INSERT INTO material_search_option_state VALUES(?,?) ON CONFLICT DO NOTHING',key)
        for field in affected:
            args = (*key,field)
            scope = ' WHERE kind=? AND language_id=? AND field=?'
            first = db.execute('SELECT position,ordinal FROM material_search_option_fields'+scope+
                               ' ORDER BY position,ordinal LIMIT 1',args).fetchone()
            if first is None:
                db.execute('DELETE FROM material_search_option_summary'+scope,args)
                continue
            name = db.execute('SELECT name FROM material_search_option_fields'+scope+
                              ' ORDER BY position DESC,ordinal DESC LIMIT 1',args).fetchone()[0]
            db.execute('''INSERT INTO material_search_option_summary VALUES(?,?,?,?,?,?)
                ON CONFLICT(kind,language_id,field) DO UPDATE SET
                  position=excluded.position,ordinal=excluded.ordinal,name=excluded.name''',(*args,*first,name))


def read(db,kind,lid):
    from dictionary_search import SearchIndex
    from morpheme_search import MorphemeIndex

    index_type = SearchIndex if kind == 'lexeme' else MorphemeIndex
    index = index_type(db,lid,(),catalog_only=True)
    key = (kind,lid)
    exists = db.execute("SELECT 1 FROM sqlite_master WHERE name='material_search_option_state'").fetchone()
    if exists:
        try:
            with material_search_index.preparing(db):
                _ready(db,index,kind,lid)
            rows = db.execute('''SELECT field,name FROM material_search_option_summary
                WHERE kind=? AND language_id=? ORDER BY position,ordinal''',key)
            fields = dict(rows)
        except material_search_index.Unavailable:
            exists = False
    if not exists:
        table = dictionary_rows.SOURCES[kind][0]
        scope,args = ('',()) if lid == 'all' else (' WHERE language_id=?',(lid,))
        owners = dict(db.execute('SELECT id,rowid FROM '+table+scope+' ORDER BY rowid',args))
        writings = {r['id']:r for r in db.execute('SELECT * FROM writing_types')} if kind == 'lexeme' else {}
        by_owner = {owner:fields for owner,fields,_ in _contributions(db,index,kind,owners,lid=='all',writings)}
        fields = dict(field for owner in owners for field in by_owner.get(owner,()))
    if kind == 'morpheme':
        # The existing morpheme selector presents evidence fields before the
        # remaining definition-specific paths.
        index.fields.update((key,name) for key,name in fields.items()
                            if key.startswith(('writing:','layer:','tag:','examples.')) or key=='examples')
        fields.pop('headword',None)
    index.fields.update(fields)
    return index.catalog()
