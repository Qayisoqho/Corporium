"""Typed SQLite rows for dictionary definitions and their ordered nested fields."""
from collections import defaultdict
import sqlite3
import record_sources


LOOKUP_SLOTS = "'conditions','definition','form','gloss','gloss_mode','homonym_note','note','notes','short_gloss','text','value'"
LOOKUP_VALUES = f"((v.value_type='text' AND v.slot IN ({LOOKUP_SLOTS})) OR (v.value_type='array' AND v.slot='form_parts'))"


def lookup_values(db):
    indexed=db.execute("SELECT 1 FROM sqlite_master WHERE name='dictionary_typed_lookup'").fetchone()
    return 'dictionary_value_rows v'+(' INDEXED BY dictionary_typed_lookup' if indexed else '')


SOURCES = {'lexeme': ('lexemes', 'headword'), 'morpheme': ('morphemes', 'form')}


def _value_rows(kind, table, where):
    # The tree's node number is local to one record. The array key carries
    # position separately. JSON integers outside SQLite's range stay exact.
    return f"""SELECT '{kind}',d.id,j.id,j.parent,j.key,j.type,
        CASE WHEN j.type='integer' AND typeof(j.atom)='real' THEN d.body->j.fullkey ELSE j.atom END
        FROM {table} d,json_tree(d.body) j {where}"""


def initialize(db):
    record_sources.initialize(db)
    db.execute('''CREATE TABLE IF NOT EXISTS dictionary_value_rows(
        target_kind TEXT NOT NULL,target_id TEXT NOT NULL,node INTEGER NOT NULL,
        parent INTEGER,slot BLOB,value_type TEXT NOT NULL,value BLOB,
        PRIMARY KEY(target_kind,target_id,node)
    ) WITHOUT ROWID''')
    db.execute("""CREATE INDEX IF NOT EXISTS dictionary_inline_examples
        ON dictionary_value_rows(target_kind,target_id) WHERE parent=0 AND slot='examples'""")
    db.execute("""CREATE INDEX IF NOT EXISTS dictionary_component_reference
        ON dictionary_value_rows(target_kind,value,target_id)
        WHERE slot='lexeme_id' AND value_type='text' AND value<>''""")
    db.execute(f"""CREATE INDEX IF NOT EXISTS dictionary_typed_lookup
        ON dictionary_value_rows(slot,target_kind,value,target_id,value_type)
        WHERE {LOOKUP_VALUES.replace('v.','')}""")
    for kind, (table, _) in SOURCES.items():
        events = ('DELETE',) if record_sources.native(db) else ('INSERT','UPDATE OF body,id','DELETE')
        for event in events:
            suffix = event.split()[0].lower()
            ids = '(OLD.id,NEW.id)' if suffix=='update' else '(OLD.id)' if suffix=='delete' else '(NEW.id)'
            when = ''
            if suffix!='delete':
                when = ' WHEN NOT '+record_sources.is_native(table,'NEW.id')
                if suffix=='update':
                    when += ' AND (OLD.body IS NOT NEW.body OR OLD.id IS NOT NEW.id)'
            name=f'dictionary_rows_{table}_{suffix}'
            sql=f'''CREATE TRIGGER {name}
              AFTER {event} ON {table}{when} BEGIN
              DELETE FROM dictionary_value_rows WHERE target_kind='{kind}' AND target_id IN {ids};
            END'''
            prior=db.execute("SELECT sql FROM sqlite_master WHERE type='trigger' AND name=?",(name,)).fetchone()
            if not prior or prior[0]!=sql:
                db.execute('DROP TRIGGER IF EXISTS '+name)
                db.execute(sql)


def drop_triggers(db):
    for table, _ in SOURCES.values():
        for event in ('insert','update','delete'):
            db.execute(f'DROP TRIGGER IF EXISTS dictionary_rows_{table}_{event}')


def _decode(rows):
    nodes = {}
    for row in rows:
        value = row['value']
        kind = row['value_type']
        if kind=='array':
            value=[]
        elif kind=='object':
            value={}
        elif kind in ('true','false'):
            value=kind=='true'
        elif kind=='integer' and isinstance(value,str):
            value=int(value)
        nodes[row['node']]=value
    result = None
    for row in rows:
        value=nodes[row['node']]
        if row['parent'] is None:
            result=value
        else:
            parent=nodes[row['parent']]
            slot=row['slot']
            if isinstance(parent,list) and len(parent)<=slot:
                parent.extend([None]*(slot+1-len(parent)))
            parent[slot]=value
    return result


def _read_nodes(db,kind,ids,prepare=True):
    import material_search_index

    if not ids:return {}
    if not db.in_transaction:db.execute('BEGIN')
    table=SOURCES[kind][0]
    grouped=defaultdict(list)
    scope=' WHERE target_kind=? AND target_id IN ('+','.join('?' for _ in ids)+')'
    query='SELECT * FROM dictionary_value_rows'+scope+' ORDER BY target_id,node'
    try:
        rows=list(db.execute(query,[kind,*ids]))
    except sqlite3.OperationalError as exc:
        if 'no such table: dictionary_value_rows' not in str(exc):
            raise
        rows=[]
        prepare=False
    missing=set(ids)-{r['target_id'] for r in rows}
    if missing and not record_sources.native(db):
        where='WHERE d.id IN ('+','.join('?' for _ in missing)+')'
        select=_value_rows(kind,table,where)
        if prepare:
            try:
                with material_search_index.preparing(db):
                    db.execute('INSERT INTO dictionary_value_rows '+select,list(missing))
                rows=list(db.execute(query,[kind,*ids]))
            except material_search_index.Unavailable:
                prepare=False
        if not prepare:
            names=('target_kind','target_id','node','parent','slot','value_type','value')
            rows.extend(dict(zip(names,row)) for row in db.execute(select+' ORDER BY d.id,j.id',list(missing)))
    for row in rows:
        grouped[row['target_id']].append(row)
    return grouped


def raw_bodies(db,kind,ids,*,prepare=True):
    """Assemble values for selected definitions without decoding a body JSON string."""
    result={}
    for start in range(0,len(ids),200):
        for owner,rows in _read_nodes(db,kind,ids[start:start+200],prepare).items():
            result[owner]=_decode(rows)
    return result


def _encode(body):
    nodes=[]
    def append(value,parent=None,slot=None):
        node=len(nodes)
        if isinstance(value,dict):
            kind,scalar='object',None
            children=value.items()
        elif isinstance(value,list):
            kind,scalar='array',None
            children=enumerate(value)
        else:
            children=()
            if value is None:
                kind,scalar='null',None
            elif isinstance(value,bool):
                kind,scalar=('true' if value else 'false'),int(value)
            elif isinstance(value,int):
                kind,scalar='integer',value if -(2**63)<=value<2**63 else str(value)
            elif isinstance(value,float):
                kind,scalar='real',value
            elif isinstance(value,str):
                kind,scalar='text',value
            else:
                raise ValueError('词典字段值格式不正确')
        nodes.append((parent,slot,kind,scalar))
        for key,child in children:
            append(child,node,key)
    append(body)
    return nodes


def write(db,kind,owner,body,*,columns=None,insert=False,bump=True):
    """Write the typed value tree and update its affected dictionary identities."""
    import independent_links

    table=SOURCES[kind][0]
    old_rows=[] if insert else _read_nodes(db,kind,[owner]).get(owner,[])
    previous=_decode(old_rows) if old_rows else None
    def apply():
        if not insert and previous == body:
            return
        old_nodes={r['node']:tuple(r[k] for k in ('parent','slot','value_type','value')) for r in old_rows}
        nodes=_encode(body)
        db.executemany('''INSERT INTO dictionary_value_rows VALUES(?,?,?,?,?,?,?)
            ON CONFLICT(target_kind,target_id,node) DO UPDATE SET parent=excluded.parent,slot=excluded.slot,
            value_type=excluded.value_type,value=excluded.value''',
            ((kind,owner,i,*node) for i,node in enumerate(nodes) if old_nodes.get(i)!=node))
        if any(i>=len(nodes) for i in old_nodes):
            db.execute('DELETE FROM dictionary_value_rows WHERE target_kind=? AND target_id=? AND node>=?',
                       (kind,owner,len(nodes)))
        independent_links.refresh_keys(db,kind,owner,body)

    record_sources.publish(db,table,owner,body,previous,columns or {},apply_rows=apply,insert=insert,bump=bump)


def _morpheme_body(row, body, writings):
    """Build the shared dictionary fields of a native morpheme."""
    def sense(source, identity=None):
        def value(key, default):
            v=source.get(key)
            return default if v is None else v
        return dict(id=identity or source.get('id'),short_gloss=value('gloss',''),
                    gloss_addition=value('gloss_addition',''),
                    show_gloss_addition=source.get('show_gloss_addition',True),
                    definition=value('definition',''),features=[] if identity else value('features',[]),
                    tags=[] if identity else value('tags',[]))
    body['homonym_number']=row['homonym_number']
    if body.get('usages') is None:
        senses=[sense(item) for item in body.get('senses',[]) or []]+[sense(body,'@main')]
        body['usages']=[dict(id='@morpheme',pos='',features=[],tags=[],senses=senses)]
    if body.get('orthographies') is None:
        body['orthographies']=[]
        for i, item in enumerate(body.get('writings',[]) or []):
            tid=item.get('type_id')
            writing=writings.get(tid,{})
            body['orthographies'].append(dict(id='@writing:'+str(i),type_id=tid,text=item.get('text'),
                                              label=writing.get('name',''),font=writing.get('font','Junicode')))
    if body.get('word_structure') is None:body['word_structure']={}
    if body.get('variants') is None:body['variants']=[]
    return body


def targets(db, ids, *, prepare=True):
    """Return the shared dictionary view as Python values built from SQLite rows."""
    if not ids:return {}
    if not db.in_transaction:db.execute('BEGIN')
    ids=list(dict.fromkeys(ids))
    result={}
    for kind,(table,form) in SOURCES.items():
        rows=[]
        number=("CASE WHEN EXISTS(SELECT 1 FROM morphemes p WHERE p.language_id=d.language_id "
                "AND p.form=d.form AND p.id<>d.id) THEN d.number END homonym_number," if kind=='morpheme' else '')
        for start in range(0,len(ids),200):
            batch=ids[start:start+200]
            rows.extend(db.execute(f"""SELECT d.id,d.language_id,d.{form} headword,d.revision,d.rowid rowid,
                {number}'{kind}' target_kind,l.name language_name FROM {table} d
                LEFT JOIN languages l ON l.id=d.language_id WHERE d.id IN ("""+','.join('?' for _ in batch)+')',batch))
        bodies=raw_bodies(db,kind,[r['id'] for r in rows],prepare=prepare)
        writing_ids={w.get('type_id') for b in bodies.values() if kind=='morpheme' and b.get('orthographies') is None
                     for w in b.get('writings',[]) or [] if w.get('type_id')}
        writings={}
        selected=list(writing_ids)
        for start in range(0,len(selected),200):
            batch=selected[start:start+200]
            writings.update((r['id'],dict(r)) for r in db.execute(
                'SELECT id,name,font FROM writing_types WHERE id IN ('+','.join('?' for _ in batch)+')',batch))
        for row in rows:
            if row['id'] in result:continue
            data=dict(row)
            body=bodies[row['id']]
            if kind=='morpheme':
                _morpheme_body(row,body,writings)
                data.pop('homonym_number')
            result[row['id']]={**data,'body':body}
    return result


def usage_fields(db,kind,ids):
    if not ids:
        return ()
    marks=','.join('?' for _ in ids)
    return db.execute(f"""SELECT a.target_id,
          max(CASE WHEN p.slot='id' THEN p.value END) usage_id,
          max(CASE WHEN p.slot='pos' THEN p.value END) pos,
          max(CASE WHEN p.slot='subclass' THEN p.value END) subclass
        FROM dictionary_value_rows a
        JOIN dictionary_value_rows u ON u.target_kind=a.target_kind AND u.target_id=a.target_id AND u.parent=a.node
        LEFT JOIN dictionary_value_rows p ON p.target_kind=a.target_kind AND p.target_id=a.target_id
          AND p.parent=u.node AND p.slot IN ('id','pos','subclass')
        WHERE a.target_kind=? AND a.target_id IN ({marks}) AND a.parent=0 AND a.slot='usages'
        GROUP BY a.target_id,u.node ORDER BY a.target_id,u.node""",(kind,*ids))


def lexeme_summaries(db,ids):
    """Read only the fields rendered by the ordinary dictionary list."""
    result={}
    for start in range(0,len(ids),200):
        batch=ids[start:start+200]
        marks=','.join('?' for _ in batch)
        for row in db.execute(f"""SELECT d.id,d.language_id,d.headword,d.revision,
            d.homonym_number,l.name language_name,v.value homonym_note
            FROM lexemes d JOIN languages l ON l.id=d.language_id
            LEFT JOIN dictionary_value_rows v ON v.target_kind='lexeme' AND v.target_id=d.id
              AND v.parent=0 AND v.slot='homonym_note' WHERE d.id IN ({marks})""",batch):
            item=dict(row)
            item['body']=dict(homonym_number=item.pop('homonym_number'),homonym_note=item.pop('homonym_note'),usages=[])
            result[item['id']]=item
        for row in usage_fields(db,'lexeme',batch):
            result[row['target_id']]['body']['usages'].append(
                dict(pos=row['pos'] or '',subclass=row['subclass'] or ''))
    return result
