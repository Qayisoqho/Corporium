"""Literal dictionary search postings and their resolved research labels."""
from functools import lru_cache
import hashlib
from itertools import islice
import json

import dictionary_data
import dictionary_search
import long_tasks
import material_search_index
import read_views
import record_sources
from search_keys import Values


TABLES=('dictionary_own_keys','dictionary_own_docs','dictionary_own_names','dictionary_own_dependencies','dictionary_own_state','dictionary_catalog_tokens',
        'dictionary_own_scopes','dictionary_own_dirty','dictionary_own_catalog_dirty','dictionary_own_contributions','dictionary_own_base_edges')
MAPPINGS=('names','tags','types','people')
LITERAL_RESULTS=read_views.Cache(12*1024**2)


def initialize(db):
    record_sources.schema_sql(db, '''
        CREATE TABLE IF NOT EXISTS dictionary_own_keys(context TEXT,kind TEXT,id TEXT,value_id INTEGER,
          PRIMARY KEY(context,kind,id,value_id)) WITHOUT ROWID;
        CREATE INDEX IF NOT EXISTS dictionary_own_values ON dictionary_own_keys(value_id,context,kind,id);
        CREATE TABLE IF NOT EXISTS dictionary_own_docs(context TEXT,id TEXT,fingerprint BLOB,PRIMARY KEY(context,id)) WITHOUT ROWID;
        CREATE TABLE IF NOT EXISTS dictionary_own_names(context TEXT,key TEXT,value TEXT,PRIMARY KEY(context,key)) WITHOUT ROWID;
        CREATE TABLE IF NOT EXISTS dictionary_own_dependencies(context TEXT,key TEXT,id TEXT,PRIMARY KEY(context,key,id)) WITHOUT ROWID;
        CREATE INDEX IF NOT EXISTS dictionary_own_doc_deps ON dictionary_own_dependencies(context,id);
        CREATE TABLE IF NOT EXISTS dictionary_catalog_tokens(context TEXT PRIMARY KEY,token BLOB);
        CREATE TABLE IF NOT EXISTS dictionary_own_state(context TEXT PRIMARY KEY,token BLOB);
    ''')
    if record_sources.native(db):
        initialize_incremental(db)
        import dictionary_cold
        dictionary_cold.initialize(db)


def drop(db):
    import dictionary_cold
    dictionary_cold.drop(db)
    for name, in db.execute("SELECT name FROM sqlite_master WHERE type='trigger' AND name GLOB 'dictionary_own_watch_*'").fetchall():
        db.execute('DROP TRIGGER '+name)
    for table in TABLES:db.execute('DROP TABLE IF EXISTS '+table)


def initialize_incremental(db):
    record_sources.schema_sql(db, '''
        CREATE TABLE IF NOT EXISTS dictionary_own_scopes(context TEXT PRIMARY KEY,lid TEXT NOT NULL,mode TEXT NOT NULL) WITHOUT ROWID;
        CREATE TABLE IF NOT EXISTS dictionary_own_dirty(context TEXT,id TEXT,PRIMARY KEY(context,id)) WITHOUT ROWID;
        CREATE TABLE IF NOT EXISTS dictionary_own_catalog_dirty(context TEXT PRIMARY KEY) WITHOUT ROWID;
        CREATE TABLE IF NOT EXISTS dictionary_own_contributions(context TEXT,owner TEXT,id TEXT,name TEXT,form TEXT COLLATE NOCASE,
          number,position INTEGER,kind TEXT,PRIMARY KEY(context,owner,id)) WITHOUT ROWID;
        CREATE INDEX IF NOT EXISTS dictionary_own_name_priority ON dictionary_own_contributions(context,id,form,number,position,kind);
        CREATE TABLE IF NOT EXISTS dictionary_own_base_edges(context TEXT,owner TEXT,base TEXT,relation TEXT,
          PRIMARY KEY(context,owner)) WITHOUT ROWID;
        CREATE INDEX IF NOT EXISTS dictionary_own_base_targets ON dictionary_own_base_edges(context,base);
    ''')

    def watch(table,event,sql,when='',suffix=''):
        record_sources.trigger(db,f'dictionary_own_watch_{table}_{event}{suffix}',f'AFTER {event} ON {table}{when} BEGIN {sql} END')

    def work(owners):
        return ('INSERT INTO dictionary_own_dirty SELECT context,id FROM ('+owners+') WHERE 1 ON CONFLICT DO NOTHING;')

    def invalidate():
        return "UPDATE read_view_tokens SET token=randomblob(16) WHERE domain IN ('content','dictionary','own');"

    for table,kind,field,modes in (('lexemes','lexeme','headword',"'words','targets'"),
                                  ('morphemes','morpheme','form',"'morphemes','targets'")):
        for event in ('INSERT','UPDATE','DELETE'):
            refs=('OLD','NEW') if event=='UPDATE' else ('OLD',) if event=='DELETE' else ('NEW',)
            if event=='UPDATE':
                columns=['rowid','id','language_id',field,'homonym_number' if kind=='lexeme' else 'number']
                changed=' OR '.join(f'OLD.{key} IS NOT NEW.{key}' for key in columns)+' OR '+record_sources.change_sql(db,table)
            else:
                changed=''
            sql=''.join(work(f"SELECT s.context,{ref}.id id FROM dictionary_own_scopes s WHERE s.mode IN ({modes}) AND s.lid IN ('all',{ref}.language_id)") for ref in refs)
            if kind=='morpheme':
                for ref in refs:
                    # Unified targets show a number only in a group with peers.
                    # A deletion or rename can change an untouched peer's number.
                    group=f'{ref}.language_id=d.language_id AND {ref}.form=d.form'
                    if event=='UPDATE':group+=' AND (OLD.language_id IS NOT NEW.language_id OR OLD.form IS NOT NEW.form)'
                    sql+=work(f"""SELECT s.context,d.id FROM {table} d JOIN dictionary_own_scopes s
                        ON s.mode='targets' AND s.lid IN ('all',d.language_id) WHERE {group}""")
            exists=f'EXISTS(SELECT 1 FROM dictionary_own_scopes WHERE mode IN ({modes}))'
            watch(table,event,sql,' WHEN '+exists+(' AND ('+changed+')' if changed else ''))
            values=''.join(work(f"""SELECT s.context,d.id FROM {table} d JOIN dictionary_own_scopes s
                ON s.mode IN ({modes}) AND s.lid IN ('all',d.language_id)
                WHERE {ref}.target_kind='{kind}' AND d.id={ref}.target_id
                  AND NOT {record_sources.is_native(table,ref+'.target_id')}""") for ref in refs)
            matching=' OR '.join(f"""({ref}.target_kind='{kind}' AND NOT {record_sources.is_native(table,ref+'.target_id')}
                AND EXISTS(SELECT 1 FROM {table} WHERE id={ref}.target_id))""" for ref in refs)
            watch('dictionary_value_rows',event,values+invalidate(),f' WHEN {matching}',suffix='_'+kind)

    for table in ('object_media','timeline_media','independent_links','dictionary_examples'):
        for event in ('INSERT','UPDATE','DELETE'):
            refs=('OLD','NEW') if event=='UPDATE' else ('OLD',) if event=='DELETE' else ('NEW',)
            fields={'object_media':('kind','record_id','language_id','asset_id','body'),
                    'timeline_media':('id','name'), 'independent_links':('example_id','lexeme_id'),
                    'dictionary_examples':('id','language_id')}[table]
            changed=' OR '.join(f'OLD.{key} IS NOT NEW.{key}' for key in fields) if event=='UPDATE' else ''
            changes=[]
            for ref in refs:
                if table in ('object_media','timeline_media'):
                    direct,selected=(f'(SELECT {ref}.record_id record_id,{ref}.kind kind,{ref}.language_id language_id)', '1') if table=='object_media' else ('object_media',f'asset_id={ref}.id')
                    changes.append(f"SELECT s.context,m.record_id id FROM {direct} m JOIN dictionary_own_scopes s ON s.lid IN ('all',m.language_id) WHERE m.kind='lexeme' AND {selected}")
                    changes.append(f"""SELECT s.context,l.lexeme_id id FROM {direct} m
                      JOIN independent_links l ON l.example_id=m.record_id JOIN dictionary_examples e ON e.id=m.record_id
                      JOIN dictionary_own_scopes s ON s.lid IN ('all',m.language_id) AND s.lid IN ('all',e.language_id)
                      WHERE m.kind='independent' AND {selected}""")
                elif table=='independent_links':
                    changes.append(f"""SELECT s.context,{ref}.lexeme_id id FROM object_media m
                      JOIN dictionary_own_scopes s ON s.lid IN ('all',m.language_id)
                      WHERE m.kind='independent' AND m.record_id={ref}.example_id""")
                else:
                    changes.append(f"""SELECT s.context,l.lexeme_id id FROM independent_links l
                      JOIN object_media m ON m.kind='independent' AND m.record_id=l.example_id
                      JOIN dictionary_own_scopes s ON s.lid IN ('all',m.language_id) WHERE l.example_id={ref}.id""")
            active="EXISTS(SELECT 1 FROM dictionary_own_scopes)"
            if table in ('independent_links','dictionary_examples'):
                field='example_id' if table=='independent_links' else 'id'
                active+=' AND EXISTS(SELECT 1 FROM object_media WHERE kind=\'independent\' AND record_id IN ('+','.join(ref+'.'+field for ref in refs)+'))'
            watch(table,event,work(' UNION ALL '.join(changes)),' WHEN '+active+(' AND ('+changed+')' if changed else ''))

    for table in ('category_classes','semantic_classes','grammar_tags','writing_types','timeline_speakers'):
        for event in ('INSERT','UPDATE','DELETE'):
            refs=('OLD','NEW') if event=='UPDATE' else ('OLD',) if event=='DELETE' else ('NEW',)
            scope='1' if table=='timeline_speakers' else "lid IN ('all',"+','.join(ref+'.language_id' for ref in refs)+')'
            sql='INSERT INTO dictionary_own_catalog_dirty SELECT context FROM dictionary_own_scopes WHERE '+scope+' ON CONFLICT DO NOTHING;'
            if table=='writing_types':
                # The resolved definition contains writing labels and spacing
                # alongside the shared type name used by the matcher.
                keys=','.join("'types:'||"+ref+'.id' for ref in refs)
                sql+=work(f"""SELECT s.context,d.id FROM dictionary_own_scopes s CROSS JOIN dictionary_own_dependencies d
                    ON d.context=s.context AND d.key IN ({keys}) WHERE s.mode!='morphemes'""")
            watch(table,event,sql)


def evidence_context(lid,targets,morphemes=False):
    return 'literal:'+('MorphemeIndex:' if morphemes else 'TargetSearchIndex:' if targets else 'SearchIndex:')+lid


def generation(db,lid,targets,token,full,morphemes=False):
    if not full:return token
    row=db.execute('SELECT token FROM dictionary_catalog_tokens WHERE context=?',(evidence_context(lid,targets,morphemes),)).fetchone()
    return b'literal-v2:'+token+(row[0] if row else b'')


def evidence_kinds(targets,morphemes):
    if morphemes:return ('morpheme',)
    return ('lexeme','morpheme') if targets else ('lexeme',)


def literal_index(db,lid,context):
    if (record_sources.native(db) and db.execute("SELECT 1 FROM sqlite_master WHERE name='dictionary_own_scopes'").fetchone()
            and db.execute('SELECT 1 FROM dictionary_own_scopes WHERE context=?',(context,)).fetchone()):
        return document_index(db,lid,context)
    index=shared_index(db,lid)
    mappings={name:{} for name in MAPPINGS}
    for key,value in db.execute('SELECT key,value FROM dictionary_own_names WHERE context=?',(context,)):
        name,identifier=key.split(':',1)
        mappings[name][identifier]=json.loads(value)
    for name,values in mappings.items():setattr(index,name,values)
    return index


NAME_ORDER='form DESC,number DESC,position DESC,kind DESC,owner DESC'


def document_index(db,lid,context):
    index=shared_index(db,lid)
    shared=index.names
    @lru_cache(maxsize=4096)
    def lookup(key,default):
        row=db.execute(f'''SELECT name FROM dictionary_own_contributions WHERE context=? AND id=?
                          ORDER BY {NAME_ORDER} LIMIT 1''',(context,key)).fetchone()
        return row[0] if row else shared.get(key,default)

    class Names:
        def get(self,key,default=None):
            return lookup(key,default)
    index.names=Names()
    return index


def shared_index(db,lid):
    return dictionary_search.SearchIndex(db,lid,[],names_only=True,literal_projection=True)


def definitions(db,lid,mode,ids):
    import dictionary_rows
    import paradigms

    writings={r['id']:r for r in db.execute('SELECT * FROM writing_types')} if mode!='morphemes' else None
    ids=iter(ids)
    while batch:=list(islice(ids,200)):
        if mode=='morphemes':
            from morpheme_search import project_row
            args=() if lid=='all' else (lid,)
            scope='' if lid=='all' else ' AND language_id=?'
            rows=db.execute("SELECT *, 'morpheme' target_kind FROM morphemes WHERE id IN ("+
                            ','.join('?' for _ in batch)+')'+scope,(*batch,*args))
            records=(project_row(row) for row in record_sources.with_bodies(db,'morphemes',rows))
        else:
            records=(row for row in dictionary_rows.targets(db,batch).values()
                     if (lid=='all' or row['language_id']==lid) and (mode=='targets' or row['target_kind']=='lexeme'))
        for row in long_tasks.steps(records):
            if writings is not None:dictionary_data.resolve(db,row['body'],writings)
            row['body']=paradigms.project(row['body'])
            yield row


def name_rows(context,mode,row):
    ordinal=row.get('rowid') if mode!='morphemes' else None
    number=row['number'] if mode=='morphemes' else row['body'].get('homonym_number')
    for key,label in dictionary_search.registered_names(row,row['body']).items():
        yield context,row['id'],key,label,row['headword'],number,ordinal,row['target_kind']


def relation(row):
    linked=row['body'].get('relation') or {}
    base=linked.get('base_id')
    return (base,linked['type']) if base else None


def contribution_batch(db,context,mode,rows):
    db.executemany('INSERT INTO dictionary_own_contributions VALUES(?,?,?,?,?,?,?,?)',
                   (item for row in long_tasks.steps(rows) for item in name_rows(context,mode,row)))
    edges=((row['id'],relation(row)) for row in rows)
    db.executemany('INSERT INTO dictionary_own_base_edges VALUES(?,?,?,?)',
                   ((context,owner,*edge) for owner,edge in edges if edge))


def refresh_contributions(db,context,mode,ids,rows):
    affected=set()
    incoming={row['id']:relation(row) for row in rows}
    previous={}
    keys={item[2] for row in rows for item in name_rows(context,mode,row)}
    def winners():
        result={}
        for key in long_tasks.steps(keys):
            row=db.execute(f'''SELECT name FROM dictionary_own_contributions WHERE context=? AND id=?
                              ORDER BY {NAME_ORDER} LIMIT 1''',(context,key)).fetchone()
            if row:result[key]=row[0]
        return result

    for start in range(0,len(ids),400):
        batch=ids[start:start+400]
        marks=','.join('?' for _ in batch)
        keys.update(r[0] for r in db.execute('SELECT DISTINCT id FROM dictionary_own_contributions WHERE context=? AND owner IN ('+marks+')',
                                            (context,*batch)))
        previous.update((r[0],(r[1],r[2])) for r in db.execute('SELECT owner,base,relation FROM dictionary_own_base_edges WHERE context=? AND owner IN ('+marks+')',
                                                              (context,*batch)))
    old=winners()
    for start in range(0,len(ids),400):
        batch=ids[start:start+400]
        marks=','.join('?' for _ in batch)
        db.execute('DELETE FROM dictionary_own_contributions WHERE context=? AND owner IN ('+marks+')',(context,*batch))
        db.execute('DELETE FROM dictionary_own_base_edges WHERE context=? AND owner IN ('+marks+')',(context,*batch))
    contribution_batch(db,context,mode,rows)
    now=winners()
    for owner in previous.keys()|incoming.keys():
        before,after=previous.get(owner),incoming.get(owner)
        if before==after:continue
        affected.update(edge[0] for edge in (before,after) if edge)
    return {'names:'+key for key in old.keys()|now.keys() if old.get(key)!=now.get(key)},affected


def refresh_shared_catalog(db,index,context):
    current={name+':'+key:json.dumps(value,ensure_ascii=False,sort_keys=True)
             for name in MAPPINGS for key,value in getattr(index,name).items()}
    previous=dict(db.execute('SELECT key,value FROM dictionary_own_names WHERE context=?',(context,)))
    changed={key for key in current.keys()|previous.keys() if current.get(key)!=previous.get(key)}
    db.executemany('INSERT OR REPLACE INTO dictionary_own_names VALUES(?,?,?)',((context,key,current[key]) for key in changed if key in current))
    db.executemany('DELETE FROM dictionary_own_names WHERE context=? AND key=?',((context,key) for key in changed-current.keys()))
    db.execute('DELETE FROM dictionary_own_catalog_dirty WHERE context=?',(context,))
    return changed


def extra_values(db,index,lid,context,ids):
    marks=','.join('?' for _ in ids)
    media_scope='' if lid=='all' else ' AND m.language_id=?'
    media_args=() if lid=='all' else (lid,)
    for row in db.execute(f"""SELECT m.record_id,m.body,a.name FROM object_media m
      LEFT JOIN timeline_media a ON a.id=m.asset_id WHERE m.kind='lexeme' AND m.record_id IN ({marks}){media_scope}""",(*ids,*media_args)):
        media=index.extra[row['record_id']]['media']
        media.append(json.loads(row['body']))
        if row['name'] is not None:media.append({'name':row['name']})
    owner_scope='' if lid=='all' else ' AND e.language_id=?'
    if db.execute("SELECT 1 FROM object_media WHERE kind='independent' LIMIT 1").fetchone():
        for row in db.execute(f'''SELECT DISTINCT l.lexeme_id,m.id,m.body,a.name FROM independent_links l
          CROSS JOIN object_media m ON m.kind='independent' AND m.record_id=l.example_id
          CROSS JOIN dictionary_examples e ON e.id=l.example_id CROSS JOIN timeline_media a ON a.id=m.asset_id
          WHERE l.lexeme_id IN ({marks}){media_scope}{owner_scope}''',(*ids,*media_args,*media_args)):
            index.extra[row['lexeme_id']]['media'].append({'name':row['name'],**json.loads(row['body'])})
    for row in db.execute('SELECT owner,base,relation FROM dictionary_own_base_edges WHERE context=? AND base IN ('+marks+')',(context,*ids)):
        index.extra[row['base']]['relation'].append({'type':row['relation'],'base_id':row['owner']})


def refresh_documents(db,lid,context,rows,pending,*,fresh):
    index=document_index(db,lid,context)
    seen=set()
    for name in MAPPINGS:setattr(index,name,material_search_index.Tracked(getattr(index,name),name+':',seen))
    values=Values(db)
    released=set()
    postings=" FROM dictionary_own_keys WHERE context=? AND kind IN ('lexeme','morpheme') AND id=?"
    iterator=iter(rows)
    updating=not fresh or bool(pending)
    while batch:=list(islice(iterator,200)):
        index.extra.clear()
        extra_values(db,index,lid,context,[r['id'] for r in batch])
        inserts=[];docs=[];dependencies=[]
        for row in long_tasks.steps(batch):
            xid=row['id']
            pending.discard(xid)
            seen.clear()
            document=index.document(row,all_only=True,project=False)
            terms=sorted({term for term in document.get('all',[]) if term.strip()})
            fingerprint=hashlib.sha256(json.dumps((row['target_kind'],terms),ensure_ascii=False).encode()).digest()
            prior=db.execute('SELECT fingerprint FROM dictionary_own_docs WHERE context=? AND id=?',(context,xid)).fetchone() if updating else None
            if not prior or prior[0]!=fingerprint:
                vids={values.intern(v) for v in terms}
                if prior:
                    released.update(r[0] for r in db.execute('SELECT value_id'+postings,(context,xid)) if r[0] not in vids)
                    db.execute('DELETE'+postings,(context,xid))
                inserts.extend((context,row['target_kind'],xid,v) for v in sorted(vids))
                docs.append((context,xid,fingerprint))
            dependencies.extend((context,key,xid) for key in seen)
        db.executemany('INSERT OR IGNORE INTO dictionary_own_keys VALUES(?,?,?,?)',inserts)
        db.executemany('INSERT OR REPLACE INTO dictionary_own_docs VALUES(?,?,?)',docs)
        keys=[r['id'] for r in batch]
        if updating:
            db.execute('DELETE FROM dictionary_own_dependencies WHERE context=? AND id IN ('+
                       ','.join('?' for _ in keys)+')',(context,*keys))
        db.executemany('INSERT INTO dictionary_own_dependencies VALUES(?,?,?)',sorted(dependencies))
    for xid in long_tasks.steps(pending):
        released.update(r[0] for r in db.execute('SELECT value_id'+postings,(context,xid)))
        db.execute('DELETE'+postings,(context,xid))
        db.execute('DELETE FROM dictionary_own_dependencies WHERE context=? AND id=?',(context,xid))
        db.execute('DELETE FROM dictionary_own_docs WHERE context=? AND id=?',(context,xid))
    values.release(released)


def prepare_incremental(db,lid,context,targets,morphemes):
    mode='morphemes' if morphemes else 'targets' if targets else 'words'
    fresh=db.execute('SELECT 1 FROM dictionary_own_scopes WHERE context=?',(context,)).fetchone() is None
    if fresh:
        db.execute('INSERT INTO dictionary_own_scopes VALUES(?,?,?)',(context,lid,mode))
        sql,args=material_search_index.target_scope(evidence_kinds(targets,morphemes),lid)
        ids=sorted({r[1] for r in db.execute(sql,args)})
        rows=list(definitions(db,lid,mode,ids))
        for start in range(0,len(rows),200):
            contribution_batch(db,context,mode,rows[start:start+200])
        refresh_shared_catalog(db,shared_index(db,lid),context)
        previous={r[0] for r in db.execute('SELECT id FROM dictionary_own_docs WHERE context=?',(context,))}
        db.execute('DELETE FROM dictionary_own_state WHERE context IN (?,?)',(context,'documents:'+context))
        refresh_documents(db,lid,context,rows,previous,fresh=True)
    else:
        ids=[r[0] for r in db.execute('SELECT id FROM dictionary_own_dirty WHERE context=?',(context,))]
        catalog=db.execute('SELECT 1 FROM dictionary_own_catalog_dirty WHERE context=?',(context,)).fetchone()
        if not ids and not catalog:return
        rows=list(definitions(db,lid,mode,ids))
        changed,affected=refresh_contributions(db,context,mode,ids,rows)
        if catalog:
            changed.update(refresh_shared_catalog(db,shared_index(db,lid),context))
        for key in long_tasks.steps(changed):
            affected.update(r[0] for r in db.execute('SELECT id FROM dictionary_own_dependencies WHERE context=? AND key=?',(context,key)))
        material_search_index.invalidate_literal_dependencies(db,evidence_context(lid,targets,morphemes),changed)
        rows.extend(definitions(db,lid,mode,sorted(affected-set(ids))))
        affected.update(ids)
        refresh_documents(db,lid,context,rows,affected,fresh=False)
    db.execute('DELETE FROM dictionary_own_dirty WHERE context=?',(context,))


def prepare(db,lid,targets,context,token,full,morphemes=False):
    native=record_sources.native(db)
    documents_context='documents:'+context
    own=read_views.token(db,'own') if full and native and not db.execute('SELECT 1 FROM object_media LIMIT 1').fetchone() else None
    if own is not None:
        saved=db.execute('SELECT token FROM dictionary_own_state WHERE context=?',(documents_context,)).fetchone()
        if saved and saved[0]==own:
            db.execute('INSERT OR REPLACE INTO dictionary_own_state VALUES(?,?)',
                       (context,generation(db,lid,targets,token,True,morphemes)))
            return
    types={r['id']:r for r in db.execute('SELECT * FROM writing_types')}
    import dictionary_rows
    import dictionary_read
    rows=[]
    fingerprints={}
    old={r[0]:r[1] for r in db.execute('SELECT id,fingerprint FROM dictionary_own_docs WHERE context=?',(context,))}
    if morphemes:
        source=db.execute("""SELECT *,form AS headword,'morpheme' AS target_kind FROM morphemes
            WHERE (?='all' OR language_id=?) ORDER BY form COLLATE NOCASE,number,id""",(lid,lid))
        rows=list(record_sources.with_bodies(db,'morphemes',source))
        from morpheme_search import MorphemeIndex
        builder=MorphemeIndex
        options={}
    else:
        identities=dictionary_read.page(db,lid,1,'all',targets=targets,ids_only=True)
        for start in range(0,len(identities),200):
            selected=identities[start:start+200]
            batch=dictionary_rows.targets(db,selected)
            for rid in long_tasks.steps(selected):
                row=batch[rid]
                row['body']=dictionary_data.resolve(db,row['body'],types)
                rows.append(row)
        builder=dictionary_search.SearchIndex
        options={'evidence_kinds':evidence_kinds(targets,morphemes)}
    if full:
        field=('form' if morphemes else 'headword') if native else 'examples'
        index=builder(db,lid,rows,search_spec={'field':field},query='',
                      evidence_context=evidence_context(lid,targets,morphemes),literal_projection=True,**options)
        if not native and index.material_evidence is None:raise material_search_index.Unavailable()
        fingerprints={r['id']:hashlib.sha256(json.dumps(index.documents[r['id']].get('all',[]),ensure_ascii=False).encode()).digest() for r in rows}
    else:
        index=builder(db,lid,rows,search_spec={'scope':'entry'},names_only=True,**options)
        fingerprints={r['id']:hashlib.sha256(json.dumps([r['headword'],r['body']],ensure_ascii=False,separators=(',',':')).encode()).digest() for r in rows}
    current={name+':'+key:json.dumps(v,ensure_ascii=False,sort_keys=True) for name in MAPPINGS for key,v in getattr(index,name).items()}
    previous=dict(db.execute('SELECT key,value FROM dictionary_own_names WHERE context=?',(context,)).fetchall())
    if native and full and current!=previous:
        db.execute('INSERT OR REPLACE INTO dictionary_catalog_tokens VALUES(?,randomblob(16))',
                   (evidence_context(lid,targets,morphemes),))
    dirty={key for key in old.keys()|fingerprints.keys() if old.get(key)!=fingerprints.get(key)}
    for key in previous.keys()|current.keys():
        if previous.get(key)==current.get(key):continue
        if not full and old:
            dirty.update(r[0] for r in db.execute('SELECT id FROM dictionary_own_dependencies WHERE context=? AND key=?',(context,key)))
        if key in current:db.execute('INSERT OR REPLACE INTO dictionary_own_names VALUES(?,?,?)',(context,key,current[key]))
        else:db.execute('DELETE FROM dictionary_own_names WHERE context=? AND key=?',(context,key))
    released=set()
    for xid in dirty & old.keys():
        released.update(r[0] for r in db.execute("SELECT value_id FROM dictionary_own_keys WHERE context=? AND kind IN ('lexeme','morpheme') AND id=?",(context,xid)))
        db.execute("DELETE FROM dictionary_own_keys WHERE context=? AND kind IN ('lexeme','morpheme') AND id=?",(context,xid))
        for table in ('dictionary_own_dependencies','dictionary_own_docs'):
            db.execute('DELETE FROM '+table+' WHERE context=? AND id=?',(context,xid))
    seen=set()
    if not full:
        for name in MAPPINGS:setattr(index,name,material_search_index.Tracked(getattr(index,name),name+':',seen))
    values=Values(db)
    for row in long_tasks.steps(rows):
        xid=row['id']
        if xid not in dirty:continue
        seen.clear()
        document=index.documents[xid] if full else index.document(row,include_extra=False)
        vids={values.intern(v) for v in document.get('all',[]) if v.strip()}
        db.executemany('INSERT INTO dictionary_own_keys VALUES(?,?,?,?)',
                       ((context,row.get('target_kind','lexeme'),xid,v) for v in vids))
        if not full:db.executemany('INSERT INTO dictionary_own_dependencies VALUES(?,?,?)',((context,k,xid) for k in seen))
        db.execute('INSERT INTO dictionary_own_docs VALUES(?,?,?)',(context,xid,fingerprints[xid]))
    values.release(released)
    db.execute('INSERT OR REPLACE INTO dictionary_own_state VALUES(?,?)',(context,generation(db,lid,targets,token,full,morphemes)))
    if full:
        if own is None:db.execute('DELETE FROM dictionary_own_state WHERE context=?',(documents_context,))
        else:db.execute('INSERT OR REPLACE INTO dictionary_own_state VALUES(?,?)',(documents_context,own))


def evidence_translation(db,lid,spec,query,kinds):
    """A scalar example predicate needs no entry documents or word recipes."""
    import corpus
    if not record_sources.native(db):
        return None
    for kind in kinds:
        table='morphemes' if kind=='morpheme' else 'lexemes'
        scope='' if lid=='all' else ' AND s.language_id=?'
        args=(kind,) if lid=='all' else (kind,lid)
        if db.execute(f"""SELECT 1 FROM dictionary_value_rows v
            CROSS JOIN {table} s ON s.id=v.target_id
            WHERE v.target_kind=? AND v.parent=0 AND v.slot='examples'{scope} LIMIT 1""",args).fetchone():
            return None
    case=spec.get('case',False)
    needle=corpus.normalize(query.strip(),case)
    db.create_function('dictionary_translation_match',1,lambda value:
        bool(value and needle in corpus.normalize(value,case)),deterministic=True)
    hits="""SELECT kind,owner_id AS id FROM sentence_text_rows
        WHERE dictionary_translation_match(translation)"""
    sql,args=material_search_index.matching_targets(hits,(),lid,kinds)
    db.execute('DROP TABLE IF EXISTS temp.dictionary_literal_hits')
    db.execute('CREATE TEMP TABLE dictionary_literal_hits(kind TEXT,record_id TEXT,PRIMARY KEY(kind,record_id)) WITHOUT ROWID')
    db.execute('INSERT INTO dictionary_literal_hits '+sql,args)
    return 'SELECT kind,record_id FROM dictionary_literal_hits',[]


def predicate(db,lid,spec,query,targets,*,morphemes=False):
    spec={} if spec is None else spec
    if not isinstance(spec,dict) or spec.get('scope','all') not in ('all','entry') or not query.strip():return None
    full=spec.get('scope','all')=='all'
    if spec.get('conditions',[])!=[] or spec.get('class_id','')!='' or spec.get('combine','all') not in ('all','any') or type(spec.get('case',False)) is not bool:return None
    if spec.get('field')=='examples.translation' and full:
        return evidence_translation(db,lid,spec,query,evidence_kinds(targets,morphemes))
    if spec.get('field','all')!='all':return None
    if full:
        import sentence_search_index
        if not sentence_search_index.available(db) or not material_search_index.available(db):return None
    if not db.execute("SELECT 1 FROM sqlite_master WHERE name='dictionary_own_state'").fetchone():return None
    token=read_views.token(db,'content' if full else 'own')
    if token is None:return None
    context=('full:' if full else 'entry:')+('morphemes:' if morphemes else 'targets:' if targets else 'words:')+lid
    native_full=full and record_sources.native(db)
    if native_full and not db.execute('SELECT 1 FROM dictionary_own_scopes WHERE context=?',(context,)).fetchone():
        import dictionary_cold
        if dictionary_cold.available(db):
            key=(token,'cold:'+context,query.strip(),spec.get('case',False))
            matches=LITERAL_RESULTS.get(key)
            if matches is None:
                try:
                    with material_search_index.preparing(db),material_search_index.writing_cache(db):
                        matches=dictionary_cold.find(db,lid,'morphemes' if morphemes else 'targets' if targets else 'words',
                                                    query.strip(),spec.get('case',False),evidence_kinds(targets,morphemes))
                except material_search_index.Unavailable:
                    return None
                LITERAL_RESULTS.put(key,matches,512+sum(256+4*len(rid) for _,rid in matches))
            db.execute('DROP TABLE IF EXISTS temp.dictionary_literal_hits')
            db.execute('CREATE TEMP TABLE dictionary_literal_hits(kind TEXT,record_id TEXT,PRIMARY KEY(kind,record_id)) WITHOUT ROWID')
            db.executemany('INSERT INTO dictionary_literal_hits VALUES(?,?)',matches)
            return 'SELECT kind,record_id FROM dictionary_literal_hits',[]
    incremental=native_full and db.execute("SELECT 1 FROM sqlite_master WHERE name='dictionary_own_scopes'").fetchone()
    if incremental:
        try:
            with material_search_index.preparing(db),material_search_index.writing_cache(db):
                prepare_incremental(db,lid,context,targets,morphemes)
        except material_search_index.Unavailable:
            return None
    else:
        ready=db.execute('SELECT token FROM dictionary_own_state WHERE context=?',(context,)).fetchone()
        if not ready or ready[0]!=generation(db,lid,targets,token,full,morphemes):
            try:
                with material_search_index.preparing(db),material_search_index.writing_cache(db):
                    prepare(db,lid,targets,context,token,full,morphemes)
            except material_search_index.Unavailable:
                return None
    sql,args=Values(db).query(query.strip(),spec.get('case',False),'contains')
    local='SELECT DISTINCT k.kind,k.id record_id FROM ('+sql+') v CROSS JOIN dictionary_own_keys k ON k.value_id=v.id WHERE k.context=?'
    args=[*args,context]
    if full and not native_full:
        hits,params=material_search_index.matching_records(Values(db),evidence_context(lid,targets,morphemes),'all','contains',query.strip(),spec.get('case',False))
        sql,params=material_search_index.matching_targets(hits,params,lid,evidence_kinds(targets,morphemes))
        local+=' UNION SELECT * FROM ('+sql+')'
        args.extend(params)
    # The page reader counts, orders and selects from this same narrow set.
    db.execute('DROP TABLE IF EXISTS temp.dictionary_literal_hits')
    db.execute('CREATE TEMP TABLE dictionary_literal_hits(kind TEXT,record_id TEXT,PRIMARY KEY(kind,record_id)) WITHOUT ROWID')
    db.execute('INSERT INTO dictionary_literal_hits '+local,args)
    if native_full:
        key=(token,context,query.strip(),spec.get('case',False))
        matches=LITERAL_RESULTS.get(key)
        if matches is None:
            try:
                with material_search_index.preparing(db),material_search_index.writing_cache(db):
                    kinds=evidence_kinds(targets,morphemes)
                    if '\0' in query or not db.execute("SELECT 1 FROM sqlite_master WHERE name='material_search_literal_records'").fetchone():
                        index=literal_index(db,lid,context)
                        matches=material_search_index.literal_targets(db,index,lid,kinds,query.strip(),spec.get('case',False))
                    else:
                        ec=evidence_context(lid,targets,morphemes)
                        stamp=db.execute('SELECT token FROM dictionary_catalog_tokens WHERE context=?',(ec,)).fetchone()
                        material_search_index.literal_records(db,lambda:literal_index(db,lid,context),
                                                              ec,lid,kinds,material_search_index.LITERAL_DEPENDENCY_TOKEN if incremental else (stamp[0] if stamp else b''),token)
                        import corpus
                        needle=corpus.normalize(query.strip(),spec.get('case',False))
                        layers,params=material_search_index.manual_hits(db,'all','contains',query.strip(),spec.get('case',False))
                        hits,values=material_search_index.literal_hits(db,ec,needle,spec.get('case',False))
                        hits+=f' UNION SELECT * FROM ({layers})'
                        sql,params=material_search_index.matching_targets(hits,[*values,*params],lid,kinds,db=db)
                        matches={tuple(row) for row in db.execute(sql,params)}
            except material_search_index.Unavailable:
                return None
            LITERAL_RESULTS.put(key,matches,512+sum(256+4*len(rid) for _,rid in matches))
        db.executemany('INSERT OR IGNORE INTO dictionary_literal_hits VALUES(?,?)',matches)
    return 'SELECT kind,record_id FROM dictionary_literal_hits',[]
