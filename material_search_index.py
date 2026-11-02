"""Shared record parts, dictionary evidence and custom sentence search keys.

Only dirty sources are expanded. Effective words refer to the gloss projection;
dictionary predicates join matching part IDs to current association identities.
No derived row belongs to business exports or undo history.
"""
import copy
import hashlib
import json
import sqlite3
import uuid
import weakref
from collections import OrderedDict
from contextlib import contextmanager

import corpus
import dictionary_targets
import gloss_inheritance as gloss
import gloss_search_index as words
import long_tasks
from search_keys import Values

TABLES = ('material_search_keys','material_search_dependencies','material_search_word_docs',
          'material_search_records','material_search_documents','material_search_catalog',
          'material_search_custom','material_search_custom_deps','material_search_targets',
          'material_search_owners','material_search_dirty','material_search_options')


def available(db):
    return bool(db.execute("SELECT 1 FROM sqlite_master WHERE name='material_search_owners'").fetchone())


class Unavailable(Exception):
    """A read-only or pinned reader can use the original source matcher."""


@contextmanager
def preparing(db):
    """Ready keys need no writer lock; contested preparation falls back promptly."""
    timeout=db.execute('PRAGMA busy_timeout').fetchone()[0]
    name='search_projection_'+uuid.uuid4().hex
    db.execute('PRAGMA busy_timeout=0')
    db.execute('SAVEPOINT '+name)
    try:
        yield
    except BaseException as exc:
        if db.in_transaction:
            try:
                db.execute('ROLLBACK TO '+name);db.execute('RELEASE '+name)
            except sqlite3.Error:pass
        if isinstance(exc,sqlite3.OperationalError) and ('readonly' in str(exc).lower() or
                getattr(exc,'sqlite_errorcode',None) in (sqlite3.SQLITE_BUSY,sqlite3.SQLITE_LOCKED,sqlite3.SQLITE_BUSY_SNAPSHOT)):
            raise Unavailable() from None
        raise
    else:
        db.execute('RELEASE '+name)
    finally:
        db.execute('PRAGMA busy_timeout='+str(timeout))


def drop(db):
    for row in db.execute("SELECT name FROM sqlite_master WHERE type='trigger' AND name LIKE 'material_search_%'").fetchall():
        db.execute('DROP TRIGGER "'+row[0].replace('"','""')+'"')
    for table in TABLES:
        db.execute('DROP TABLE IF EXISTS '+table)


def initialize(db):
    db.executescript('''
      CREATE TABLE IF NOT EXISTS material_search_dirty(kind TEXT,owner_id TEXT,basic INTEGER NOT NULL,custom INTEGER NOT NULL,
        PRIMARY KEY(kind,owner_id)) WITHOUT ROWID;
      CREATE INDEX IF NOT EXISTS material_search_basic_dirty ON material_search_dirty(kind,owner_id) WHERE basic=1;
      CREATE INDEX IF NOT EXISTS material_search_custom_dirty ON material_search_dirty(kind,owner_id) WHERE custom=1;
      CREATE TABLE IF NOT EXISTS material_search_owners(kind TEXT,owner_id TEXT,PRIMARY KEY(kind,owner_id)) WITHOUT ROWID;
      CREATE TABLE IF NOT EXISTS material_search_documents(id INTEGER PRIMARY KEY,context TEXT,identity TEXT,source TEXT,
        prefix TEXT,fields TEXT NOT NULL DEFAULT '{}',dirty INTEGER NOT NULL DEFAULT 1,classes TEXT NOT NULL DEFAULT '[]',UNIQUE(context,identity));
      CREATE INDEX IF NOT EXISTS material_search_document_dirty ON material_search_documents(context,id) WHERE dirty=1;
      CREATE TABLE IF NOT EXISTS material_search_keys(doc_id INTEGER,field TEXT,value_id INTEGER,
        PRIMARY KEY(doc_id,field,value_id)) WITHOUT ROWID;
      CREATE INDEX IF NOT EXISTS material_search_key_values ON material_search_keys(value_id,field,doc_id);
      CREATE TABLE IF NOT EXISTS material_search_dependencies(context TEXT,identifier TEXT,doc_id INTEGER,
        PRIMARY KEY(context,identifier,doc_id)) WITHOUT ROWID;
      CREATE INDEX IF NOT EXISTS material_search_doc_dependencies ON material_search_dependencies(doc_id);
      CREATE TABLE IF NOT EXISTS material_search_catalog(context TEXT,identifier TEXT,value TEXT,
        PRIMARY KEY(context,identifier)) WITHOUT ROWID;
      CREATE TABLE IF NOT EXISTS material_search_records(context TEXT,kind TEXT,owner_id TEXT,doc_id INTEGER,
        PRIMARY KEY(context,kind,owner_id)) WITHOUT ROWID;
      CREATE INDEX IF NOT EXISTS material_search_record_docs ON material_search_records(doc_id);
      CREATE TABLE IF NOT EXISTS material_search_word_docs(context TEXT,recipe_id INTEGER,revision INTEGER,doc_id INTEGER,
        PRIMARY KEY(context,recipe_id)) WITHOUT ROWID;
      CREATE INDEX IF NOT EXISTS material_search_word_documents ON material_search_word_docs(doc_id);
      CREATE TABLE IF NOT EXISTS material_search_custom(kind TEXT,owner_id TEXT,field TEXT,word INTEGER,origin TEXT,value_id INTEGER,display TEXT,
        PRIMARY KEY(kind,owner_id,field,word,origin,value_id)) WITHOUT ROWID;
      CREATE INDEX IF NOT EXISTS material_search_custom_values ON material_search_custom(value_id,field,kind,owner_id,word);
      CREATE TABLE IF NOT EXISTS material_search_custom_deps(recipe_id INTEGER,kind TEXT,owner_id TEXT,revision INTEGER,
        PRIMARY KEY(recipe_id,kind,owner_id)) WITHOUT ROWID;
      CREATE INDEX IF NOT EXISTS material_search_custom_owner_deps ON material_search_custom_deps(kind,owner_id);
      CREATE TABLE IF NOT EXISTS material_search_targets(target_id TEXT,kind TEXT,owner_id TEXT,
        PRIMARY KEY(target_id,kind,owner_id)) WITHOUT ROWID;
      CREATE INDEX IF NOT EXISTS material_search_target_owners ON material_search_targets(kind,owner_id);
      CREATE TABLE IF NOT EXISTS material_search_options(kind TEXT,language_id TEXT,body TEXT,
        PRIMARY KEY(kind,language_id)) WITHOUT ROWID;
    ''')
    if 'display' not in {r[1] for r in db.execute('PRAGMA table_info(material_search_custom)')}:
        db.execute('ALTER TABLE material_search_custom ADD COLUMN display TEXT')
        db.execute('UPDATE material_search_dirty SET custom=1')
    if 'classes' not in {r[1] for r in db.execute('PRAGMA table_info(material_search_documents)')}:
        db.execute("ALTER TABLE material_search_documents ADD COLUMN classes TEXT NOT NULL DEFAULT '[]'")
        db.execute('UPDATE material_search_documents SET dirty=1')
    for row in db.execute("SELECT name FROM sqlite_master WHERE type='trigger' AND name LIKE 'material_search_%'").fetchall():
        db.execute('DROP TRIGGER "'+row[0].replace('"','""')+'"')

    def queue(kind, rid, basic=0):
        return f'''INSERT INTO material_search_dirty SELECT {kind},{rid},{basic},1 WHERE NOT EXISTS(
            SELECT 1 FROM material_search_dirty WHERE kind={kind} AND owner_id={rid});
          UPDATE material_search_dirty SET custom=1,basic=max(basic,{basic}) WHERE kind={kind} AND owner_id={rid};'''

    for table, kind in (('entries','corpus'),('dictionary_examples','independent')):
        for event in ('INSERT','UPDATE','DELETE'):
            refs=('OLD','NEW') if event=='UPDATE' else ('OLD',) if event=='DELETE' else ('NEW',)
            body=''.join(queue("'"+kind+"'",ref+'.id',1) for ref in refs)
            when=' WHEN OLD.body IS NOT NEW.body OR OLD.id IS NOT NEW.id' if event=='UPDATE' else ''
            db.execute(f'CREATE TRIGGER material_search_{table}_{event} AFTER {event} ON {table}{when} BEGIN '+body+' END')
        db.execute(f'''INSERT OR IGNORE INTO material_search_dirty SELECT ?,s.id,1,1 FROM {table} s
          WHERE NOT EXISTS(SELECT 1 FROM material_search_owners o WHERE o.kind=? AND o.owner_id=s.id)''',(kind,kind))
    for table in ('annotation_cells','gloss_bindings','corpus_units','lexical_links'):
        for event in ('INSERT','UPDATE','DELETE'):
            refs=('OLD','NEW') if event=='UPDATE' else ('OLD',) if event=='DELETE' else ('NEW',)
            statements=[]
            for ref in refs:
                if table=='annotation_cells':statements.append(queue(ref+'.owner_kind',ref+'.record_id'))
                elif table=='gloss_bindings':statements.append(queue(ref+'.owner_kind',ref+'.owner_id'))
                elif table=='corpus_units':statements.append(queue("'corpus'",ref+'.entry_id'))
                else:
                    statements.append(f'''INSERT INTO material_search_dirty SELECT 'corpus',entry_id,0,1 FROM corpus_units u WHERE id={ref}.unit_id
                        AND NOT EXISTS(SELECT 1 FROM material_search_dirty d WHERE d.kind='corpus' AND d.owner_id=u.entry_id);
                      UPDATE material_search_dirty SET custom=1 WHERE kind='corpus' AND owner_id IN (SELECT entry_id FROM corpus_units WHERE id={ref}.unit_id);''')
            db.execute(f'CREATE TRIGGER material_search_{table}_{event} AFTER {event} ON {table} BEGIN '+''.join(statements)+' END')
    # Metadata edits can change validity, names or derived layer values. They
    # invalidate custom projections, without invalidating scalar/gloss indexes.
    for table in ('lexical_reviews','morphology_analyses','component_links'):
        for event in ('INSERT','UPDATE','DELETE'):
            refs=('OLD','NEW') if event=='UPDATE' else ('OLD',) if event=='DELETE' else ('NEW',)
            statements=''.join(f'''INSERT INTO material_search_dirty SELECT DISTINCT 'corpus',u.entry_id,0,1
              FROM lexical_links l JOIN corpus_units u ON u.id=l.unit_id WHERE l.id={ref}.id
                AND NOT EXISTS(SELECT 1 FROM material_search_dirty d WHERE d.kind='corpus' AND d.owner_id=u.entry_id);
              UPDATE material_search_dirty SET custom=1 WHERE kind='corpus' AND owner_id IN (
                SELECT u.entry_id FROM lexical_links l JOIN corpus_units u ON u.id=l.unit_id WHERE l.id={ref}.id);''' for ref in refs)
            db.execute(f'CREATE TRIGGER material_search_{table}_{event} AFTER {event} ON {table} BEGIN '+statements+' END')
    for table in ('annotation_layers','writing_types','category_classes','semantic_classes','texts'):
        if not db.execute('SELECT 1 FROM sqlite_master WHERE type=\'table\' AND name=?',(table,)).fetchone():
            continue
        for event in ('INSERT','UPDATE','DELETE'):
            refs=('OLD','NEW') if event=='UPDATE' else ('OLD',) if event=='DELETE' else ('NEW',)
            if table=='texts':
                affected="o.kind='corpus' AND o.owner_id IN (SELECT id FROM entries WHERE text_id IN ("+','.join(ref+'.id' for ref in refs)+'))'
                when=' WHEN OLD.language_id IS NOT NEW.language_id OR OLD.id IS NOT NEW.id' if event=='UPDATE' else ''
            else:
                lids=','.join(ref+'.language_id' for ref in refs)
                affected=f'''(o.kind='corpus' AND EXISTS(SELECT 1 FROM entries e JOIN texts t ON t.id=e.text_id WHERE e.id=o.owner_id
                  AND COALESCE(NULLIF(json_extract(e.body,'$.language_id'),''),t.language_id) IN ({lids})) OR o.kind='independent' AND EXISTS(
                    SELECT 1 FROM dictionary_examples e WHERE e.id=o.owner_id AND e.language_id IN ({lids})))'''
                when=''
                if event=='UPDATE' and table=='annotation_layers':
                    when=' WHEN OLD.language_id IS NOT NEW.language_id OR OLD.source IS NOT NEW.source OR OLD.anchor IS NOT NEW.anchor OR OLD.dictionary_field IS NOT NEW.dictionary_field'
                elif event=='UPDATE' and table=='writing_types':
                    when=' WHEN OLD.language_id IS NOT NEW.language_id OR OLD.id IS NOT NEW.id'
            db.execute(f'''CREATE TRIGGER material_search_{table}_{event} AFTER {event} ON {table}{when} BEGIN
              INSERT INTO material_search_dirty SELECT kind,owner_id,0,1 FROM material_search_owners o WHERE {affected}
                AND NOT EXISTS(SELECT 1 FROM material_search_dirty d WHERE d.kind=o.kind AND d.owner_id=o.owner_id);
              UPDATE material_search_dirty SET custom=1 WHERE (kind,owner_id) IN (SELECT kind,owner_id FROM material_search_owners o WHERE {affected}); END''')
    for table in ('lexemes','morphemes'):
        for event in ('INSERT','UPDATE','DELETE'):
            refs=('OLD','NEW') if event=='UPDATE' else ('OLD',) if event=='DELETE' else ('NEW',)
            statements=''.join(f'''INSERT INTO material_search_dirty SELECT kind,owner_id,0,1 FROM material_search_targets t WHERE target_id={ref}.id
                AND NOT EXISTS(SELECT 1 FROM material_search_dirty d WHERE d.kind=t.kind AND d.owner_id=t.owner_id);
              UPDATE material_search_dirty SET custom=1 WHERE (kind,owner_id) IN (SELECT kind,owner_id FROM material_search_targets WHERE target_id={ref}.id);''' for ref in refs)
            when=''' WHEN OLD.id IS NOT NEW.id OR OLD.language_id IS NOT NEW.language_id
              OR json_extract(OLD.body,'$.orthographies') IS NOT json_extract(NEW.body,'$.orthographies')
              OR json_extract(OLD.body,'$.writings') IS NOT json_extract(NEW.body,'$.writings')
              OR json_extract(OLD.body,'$.word_structure') IS NOT json_extract(NEW.body,'$.word_structure')
              OR EXISTS(SELECT 1 FROM annotation_layers WHERE source='dictionary')''' if event=='UPDATE' else ''
            db.execute(f'CREATE TRIGGER material_search_{table}_{event} AFTER {event} ON {table}{when} BEGIN '+statements+' END')
    for table in ('lexemes','morphemes','category_classes','semantic_classes','grammar_tags','writing_types','annotation_layers'):
        for event in ('INSERT','UPDATE','DELETE'):
            db.execute(f'CREATE TRIGGER material_search_options_{table}_{event} AFTER {event} ON {table} BEGIN DELETE FROM material_search_options; END')


def catalog(db,kind,lid,value=None):
    import sentence_search_index
    if not available(db) or not sentence_search_index.available(db):return None
    if value is not None:
        try:
            with preparing(db):
                db.execute('INSERT OR REPLACE INTO material_search_options VALUES(?,?,?)',(kind,lid,words.encode(value)))
        except Unavailable:pass
        return value
    row=db.execute('SELECT body FROM material_search_options WHERE kind=? AND language_id=?',(kind,lid)).fetchone()
    return json.loads(row[0]) if row else None


def pending(db):
    if not available(db):return 0
    return db.execute('''SELECT count(*) FROM (SELECT 1 FROM material_search_dirty WHERE custom=1 UNION ALL
      SELECT 1 FROM material_search_custom_deps d LEFT JOIN gloss_search_recipes r ON r.id=d.recipe_id
      WHERE r.id IS NULL OR r.dirty=1 OR r.revision!=d.revision LIMIT 201)''').fetchone()[0]


def refresh_sources(db, owner_table=None):
    # A narrow invalidation pass, with no sentence JSON crossing into Python.
    scope=words.owner_filter(owner_table,'d')
    if not db.execute('SELECT 1 FROM material_search_dirty d WHERE basic=1'+scope+' LIMIT 1').fetchone():return
    db.execute('''DELETE FROM material_search_records WHERE EXISTS(SELECT 1 FROM material_search_dirty d
      WHERE d.basic=1 AND d.kind=material_search_records.kind AND d.owner_id=material_search_records.owner_id'''+scope+')')
    db.execute('INSERT OR IGNORE INTO material_search_owners SELECT kind,owner_id FROM material_search_dirty d WHERE basic=1'+scope)
    db.execute('UPDATE material_search_dirty AS d SET basic=0 WHERE basic=1'+scope)


def custom_values(db, kind, rid, body, lid, cache):
    import annotations, dictionary_layers, segmentation, word_structure
    definitions=annotations.layers(db,lid)
    units={w['id']:w['position'] for w in annotations.units(db,kind,rid,body)}
    result=[]
    for cell in db.execute('SELECT * FROM annotation_cells WHERE owner_kind=? AND record_id=?',(kind,rid)):
        if annotations.valid_cell(cell,units,definitions):
            result.append(('layer:'+cell['layer_id'],units.get(cell['unit_id'],-1),'cell',cell['value'],cell['value']))
    types={r['id']:dict(r) for r in db.execute('SELECT * FROM writing_types WHERE language_id=?',(lid,))}
    derived=[d for d in definitions if d.get('source')=='dictionary']
    if not types and not derived:
        return result,set()
    if kind=='corpus':
        targets={(r['lexeme_id'],r['word_position']) for r in db.execute('''SELECT l.lexeme_id,COALESCE(p.position,u.position) word_position
          FROM lexical_links l JOIN corpus_units u ON u.id=l.unit_id LEFT JOIN corpus_units p ON p.id=u.parent_id
          WHERE u.entry_id=? AND u.active=1''',(rid,))}
    else:
        analyzed=corpus.analyze(copy.deepcopy(body));segmentation.decorate_refs(analyzed)
        targets={(t.get('lexeme_id'),(t.get('segmentation_ref') or {}).get('word')) for t in analyzed.get('targets',[]) if not t.get('segmentation_review')}
    for xid, position in targets:
        key=(xid,lid)
        if key in cache:
            cache.move_to_end(key);writings=cache[key]
        else:
            target=db.execute('SELECT body,language_id FROM dictionary_targets WHERE id=?',(xid,)).fetchone()
            writings=[]
            if target and target['language_id']==lid:
                value=json.loads(target['body'])
                writings=[('writing:'+w['type_id'],w.get('text','')) for w in [*value.get('orthographies',[]),*value.get('writings',[]),*word_structure.writing_rows(value)] if w.get('type_id') in types]
            # Bound by both count and input bytes; oversized records are not kept.
            if sum(len(text) for _,text in writings)<65536:
                cache[key]=writings
                while len(cache)>64:cache.popitem(last=False)
        result.extend((field,position if position is not None else -1,'writing',text,text) for field,text in writings)
    if derived:
        projected=dictionary_layers.project(db,corpus.analyze(copy.deepcopy(body)),kind,rid,lid,derived,linked_only=True)
        for pos,word in enumerate(projected.get('words',[])):
            for layer in word.get('extra_layers',[]):
                if layer.get('derived') and any(s['values'] for s in layer['segments']):
                    result.extend(('layer:'+layer['id'],pos,'derived',dictionary_layers.text(layer,locale),dictionary_layers.text(layer)) for locale in ('zh-CN','en'))
    return result,{xid for xid,_ in targets if xid}


def refresh_custom(db, owner_table=None):
    if not available(db):return
    if not db.in_transaction:db.execute('BEGIN')
    scope=words.owner_filter(owner_table,'d')
    words.refresh(db,owner_table=owner_table);refresh_sources(db,owner_table)
    active=db.execute('SELECT 1 FROM annotation_layers UNION ALL SELECT 1 FROM writing_types LIMIT 1').fetchone()
    if not active:
        old=[r[0] for r in db.execute('SELECT DISTINCT value_id FROM material_search_custom')]
        for table in ('material_search_custom','material_search_custom_deps','material_search_targets'):
            if db.execute('SELECT 1 FROM '+table+' LIMIT 1').fetchone():db.execute('DELETE FROM '+table)
        if db.execute('SELECT 1 FROM material_search_dirty d WHERE basic=0'+scope+' LIMIT 1').fetchone():
            db.execute('DELETE FROM material_search_dirty AS d WHERE basic=0'+scope)
        Values(db).release(old)
        return
    changed='SELECT d.kind,d.owner_id FROM material_search_custom_deps d LEFT JOIN gloss_search_recipes r ON r.id=d.recipe_id WHERE (r.id IS NULL OR r.revision!=d.revision)'+scope
    if db.execute(changed+' LIMIT 1').fetchone():
        db.execute('INSERT OR IGNORE INTO material_search_dirty SELECT DISTINCT kind,owner_id,0,1 FROM ('+changed+')')
        db.execute('UPDATE material_search_dirty SET custom=1 WHERE (kind,owner_id) IN ('+changed+')')
    if not db.execute('SELECT 1 FROM material_search_dirty d WHERE custom=1'+scope+' LIMIT 1').fetchone():return
    derived_languages={r[0] for r in db.execute("SELECT DISTINCT language_id FROM annotation_layers WHERE source='dictionary'")}
    writing_languages={r[0] for r in db.execute('SELECT DISTINCT language_id FROM writing_types')}
    values=Values(db);cache=OrderedDict()
    while batch:=db.execute('SELECT kind,owner_id FROM material_search_dirty d WHERE custom=1'+scope+' LIMIT 100').fetchall():
        for row in long_tasks.steps(batch):
            kind,rid=row['kind'],row['owner_id']
            source=db.execute('SELECT e.body,COALESCE(NULLIF(json_extract(e.body,\'$.language_id\'),\'\'),t.language_id) language_id FROM entries e JOIN texts t ON t.id=e.text_id WHERE e.id=?' if kind=='corpus' else 'SELECT body,language_id FROM dictionary_examples WHERE id=?',(rid,)).fetchone()
            old=[r[0] for r in db.execute('SELECT value_id FROM material_search_custom WHERE kind=? AND owner_id=?',(kind,rid))]
            for table in ('material_search_custom','material_search_custom_deps','material_search_targets'):
                db.execute('DELETE FROM '+table+' WHERE kind=? AND owner_id=?',(kind,rid))
            if source:
                dependent=source['language_id'] in derived_languages or kind=='independent' and source['language_id'] in writing_languages
                body=gloss.load(db,kind,rid,source['body'],metadata=False) if dependent else json.loads(source['body'])
                entries,targets=custom_values(db,kind,rid,body,source['language_id'],cache)
                db.executemany('INSERT OR IGNORE INTO material_search_custom VALUES(?,?,?,?,?,?,?)',
                  [(kind,rid,field,pos,origin,values.intern(text),display) for field,pos,origin,text,display in entries if text])
                db.executemany('INSERT OR IGNORE INTO material_search_targets VALUES(?,?,?)',[(xid,kind,rid) for xid in targets])
                if dependent:
                    db.execute('''INSERT OR IGNORE INTO material_search_custom_deps SELECT DISTINCT w.recipe_id,w.kind,w.owner_id,r.revision
                      FROM gloss_search_words w JOIN gloss_search_recipes r ON r.id=w.recipe_id WHERE w.kind=? AND w.owner_id=?''',(kind,rid))
            else:
                db.execute('DELETE FROM material_search_owners WHERE kind=? AND owner_id=?',(kind,rid))
            db.execute('UPDATE material_search_dirty SET custom=0 WHERE kind=? AND owner_id=?',(kind,rid))
            db.execute('DELETE FROM material_search_dirty WHERE kind=? AND owner_id=? AND basic=0 AND custom=0',(kind,rid))
            values.release(old)
            long_tasks.checkpoint(None,'正在更新附加层与书写检索索引…')


def custom_hits(db,field,query,case,mode,lid,details=False):
    import annotations
    if field.startswith(('layer:','writing:')) and field not in {f['id'] for f in annotations.search_catalog(db,lid)['fields']}:
        raise ValueError('自定义检索字段已删除或不属于当前语言，请重新选择')
    sql,args=Values(db).query(query,case,mode)
    columns='kind,owner_id id,word,field,value_id,display' if details else 'kind,owner_id id,word'
    if not query.strip():return 'SELECT '+columns+' FROM material_search_custom WHERE 0',[]
    clauses=['value_id IN ('+sql+')']
    if field.startswith(('layer:','writing:')):
        clauses.append('field=?');args.append(field)
    elif field=='layers':clauses.append("field LIKE 'layer:%'")
    elif field=='writings':clauses.append("field LIKE 'writing:%'")
    if not field.startswith('layer:'):
        clauses.append("(field NOT LIKE 'layer:%' OR substr(field,7) IN (SELECT id FROM annotation_layers WHERE searchable=1))")
    if lid!='all':
        clauses.append("(field LIKE 'layer:%' AND substr(field,7) IN (SELECT id FROM annotation_layers WHERE language_id=?) OR field LIKE 'writing:%' AND substr(field,9) IN (SELECT id FROM writing_types WHERE language_id=?))")
        args.extend([lid,lid])
    return 'SELECT '+columns+' FROM material_search_custom WHERE '+' AND '.join(clauses),args


class Tracked(dict):
    def __init__(self,source,prefix,seen):super().__init__(source);self.prefix=prefix;self.seen=seen
    def get(self,key,default=None):self.seen.add(self.prefix+str(key));return super().get(key,default)
    def __getitem__(self,key):self.seen.add(self.prefix+str(key));return super().__getitem__(key)
    def __contains__(self,key):self.seen.add(self.prefix+str(key));return super().__contains__(key)


class Evidence:
    def __init__(self,db,index,lid):
        self.db=db;self.index=weakref.proxy(index);self.context=type(index).__name__+':'+lid;self.values=Values(db);self.matches={}
        token=uuid.uuid4().hex
        self.owners_table='dictionary_query_owners_'+token
        self.docs_table='dictionary_query_docs_'+token
        self.records_table='dictionary_query_records_'+token
        if not db.in_transaction:db.execute('BEGIN')
        self.execute('CREATE TEMP TABLE dictionary_query_owners(kind TEXT,id TEXT,target_id TEXT,PRIMARY KEY(kind,id,target_id)) WITHOUT ROWID')
        self.execute('''INSERT OR IGNORE INTO dictionary_query_owners SELECT 'corpus',u.entry_id,l.lexeme_id FROM lexical_links l
          JOIN corpus_units u ON u.id=l.unit_id JOIN '''+dictionary_targets.IDENTITIES+''' t ON t.id=l.lexeme_id
          WHERE (?='all' OR t.language_id=?)''',(lid,lid))
        self.execute('''INSERT OR IGNORE INTO dictionary_query_owners SELECT 'independent',e.id,json_extract(t.value,'$.lexeme_id')
          FROM dictionary_examples e,json_each(e.body,'$.targets') t WHERE (?='all' OR e.language_id=?)
          AND json_extract(t.value,'$.lexeme_id') IS NOT NULL''',(lid,lid))
        self.execute('CREATE TEMP TABLE dictionary_query_records(kind TEXT,id TEXT,PRIMARY KEY(kind,id)) WITHOUT ROWID')
        self.execute('INSERT INTO dictionary_query_records SELECT DISTINCT kind,id FROM dictionary_query_owners')
        self.has_owners=bool(self.execute('SELECT 1 FROM dictionary_query_records LIMIT 1').fetchone())
        if self.has_owners:
            refresh_custom(db,owner_table=self.records_table)
            self.sync_catalog()
            self.prepare()

    def execute(self, sql, params=()):
        sql=sql.replace('dictionary_query_owners',self.owners_table).replace('dictionary_query_docs',self.docs_table).replace('dictionary_query_records',self.records_table)
        return self.db.execute(sql,params)

    def sync_catalog(self):
        current={prefix+str(k):words.encode(v) for prefix,name in (('names:','names'),('tags:','tags'),('types:','types'),('people:','people')) for k,v in getattr(self.index,name).items()}
        previous={r['identifier']:r['value'] for r in self.execute('SELECT identifier,value FROM material_search_catalog WHERE context=?',(self.context,))}
        for key in current.keys()|previous.keys():
            if current.get(key)==previous.get(key):continue
            self.execute('''UPDATE material_search_documents SET dirty=1 WHERE id IN (
              SELECT doc_id FROM material_search_dependencies WHERE context=? AND identifier=?)''',(self.context,key))
            if key in current:self.execute('INSERT OR REPLACE INTO material_search_catalog VALUES(?,?,?)',(self.context,key,current[key]))
            else:self.execute('DELETE FROM material_search_catalog WHERE context=? AND identifier=?',(self.context,key))

    def document(self,source,prefix):
        encoded=words.encode(source);identity=hashlib.sha256((prefix+'\0'+encoded).encode()).hexdigest()
        row=self.execute('SELECT id FROM material_search_documents WHERE context=? AND identity=?',(self.context,identity)).fetchone()
        if row:return row[0]
        return self.execute('INSERT INTO material_search_documents(context,identity,source,prefix) VALUES(?,?,?,?)',(self.context,identity,encoded,prefix)).lastrowid

    def prepare(self):
        while batch:=self.execute('''SELECT q.kind,q.id FROM dictionary_query_records q
          WHERE NOT EXISTS(SELECT 1 FROM material_search_records r WHERE r.context=? AND r.kind=q.kind AND r.owner_id=q.id) LIMIT 200''',(self.context,)).fetchall():
            for row in long_tasks.steps(batch):
                table='entries' if row['kind']=='corpus' else 'dictionary_examples'
                source=self.execute('SELECT body FROM '+table+' WHERE id=?',(row['id'],)).fetchone()
                if source:
                    body=json.loads(source[0]);body.pop('words',None)
                    doc_id=self.document(body,'examples')
                    self.execute('INSERT INTO material_search_records VALUES(?,?,?,?)',(self.context,row['kind'],row['id'],doc_id))
                else:
                    self.execute('DELETE FROM dictionary_query_owners WHERE kind=? AND id=?',(row['kind'],row['id']))
                    self.execute('DELETE FROM dictionary_query_records WHERE kind=? AND id=?',(row['kind'],row['id']))
        while batch:=self.execute('''SELECT r.id,r.output,r.revision FROM gloss_search_recipes r WHERE
          NOT EXISTS(SELECT 1 FROM material_search_word_docs d WHERE d.context=? AND d.recipe_id=r.id AND d.revision=r.revision)
          AND EXISTS(SELECT 1 FROM gloss_search_words w JOIN dictionary_query_records q ON q.kind=w.kind AND q.id=w.owner_id WHERE w.recipe_id=r.id)
          LIMIT 200''',(self.context,)).fetchall():
            for row in long_tasks.steps(batch):
                doc_id=self.document(json.loads(row['output']),'examples.words')
                self.execute('INSERT OR REPLACE INTO material_search_word_docs VALUES(?,?,?,?)',(self.context,row['id'],row['revision'],doc_id))
        while batch:=self.execute('SELECT * FROM material_search_documents WHERE context=? AND dirty=1 LIMIT 100',(self.context,)).fetchall():
            for row in long_tasks.steps(batch):
                seen=set();fields={};previous={}
                for name in ('names','tags','types','people'):
                    previous[name]=getattr(self.index,name);setattr(self.index,name,Tracked(previous[name],name+':',seen))
                try:
                    doc=self.index.document(dict(id='',headword='',body=json.loads(row['source'])),include_extra=False,prefix=tuple(row['prefix'].split('.')),field_catalog=fields,project=row['prefix']=='examples')
                finally:
                    for name,value in previous.items():setattr(self.index,name,value)
                old=[r[0] for r in self.execute('SELECT value_id FROM material_search_keys WHERE doc_id=?',(row['id'],))]
                self.execute('DELETE FROM material_search_keys WHERE doc_id=?',(row['id'],))
                self.db.executemany('INSERT OR IGNORE INTO material_search_keys VALUES(?,?,?)',[(row['id'],field,self.values.intern(text)) for field,texts in doc.items() for text in texts if isinstance(text,str) and text.strip()])
                self.execute('DELETE FROM material_search_dependencies WHERE doc_id=?',(row['id'],))
                self.db.executemany('INSERT INTO material_search_dependencies VALUES(?,?,?)',[(self.context,key,row['id']) for key in seen])
                self.execute('UPDATE material_search_documents SET fields=?,classes=?,dirty=0 WHERE id=?',(words.encode(fields),words.encode(doc.get('_grammar_classes',[])),row['id']))
                self.values.release(old)
                long_tasks.checkpoint(None,'正在更新词典关联例证检索索引…')
        self.execute('DROP TABLE IF EXISTS temp.dictionary_query_docs')
        self.execute('CREATE TEMP TABLE dictionary_query_docs(id INTEGER PRIMARY KEY)')
        self.execute('''INSERT OR IGNORE INTO dictionary_query_docs SELECT r.doc_id FROM material_search_records r
          JOIN dictionary_query_records q ON q.kind=r.kind AND q.id=r.owner_id WHERE r.context=?''',(self.context,))
        self.execute('''INSERT OR IGNORE INTO dictionary_query_docs SELECT d.doc_id FROM material_search_word_docs d
          JOIN gloss_search_words w ON w.recipe_id=d.recipe_id JOIN dictionary_query_records q ON q.kind=w.kind AND q.id=w.owner_id
          WHERE d.context=?''',(self.context,))
        for row in self.execute('SELECT DISTINCT fields FROM material_search_documents WHERE id IN (SELECT id FROM dictionary_query_docs)'):
            self.index.fields.update(json.loads(row[0]))
        self.collect()

    def collect(self):
        if self.execute('SELECT 1 FROM material_search_word_docs WHERE recipe_id NOT IN (SELECT id FROM gloss_search_recipes) LIMIT 1').fetchone():
            self.execute('DELETE FROM material_search_word_docs WHERE recipe_id NOT IN (SELECT id FROM gloss_search_recipes)')
        # Old versions are released after their replacement has been linked, so
        # shared words, other language contexts and undo reuse remain safe.
        while obsolete:=self.execute('''SELECT id FROM material_search_documents d WHERE
          NOT EXISTS(SELECT 1 FROM material_search_records r WHERE r.doc_id=d.id) AND
          NOT EXISTS(SELECT 1 FROM material_search_word_docs w WHERE w.doc_id=d.id) LIMIT 200''').fetchall():
            for row in long_tasks.steps(obsolete):
                old=[r[0] for r in self.execute('SELECT value_id FROM material_search_keys WHERE doc_id=?',(row['id'],))]
                self.execute('DELETE FROM material_search_keys WHERE doc_id=?',(row['id'],))
                self.execute('DELETE FROM material_search_dependencies WHERE doc_id=?',(row['id'],))
                self.execute('DELETE FROM material_search_documents WHERE id=?',(row['id'],))
                self.values.release(old)

    def owners(self,kind,rid):
        return {r[0] for r in self.execute('SELECT target_id FROM dictionary_query_owners WHERE kind=? AND id=?',(kind,rid))}

    def matching(self,field,op,value,case):
        if not self.has_owners:return frozenset()
        op='present' if op in ('empty','present') else 'contains' if op=='not_contains' else op
        key=(field,op,value,bool(case))
        if key in self.matches:return self.matches[key]
        sql,args=self.values.query(value,case,op)
        sql='SELECT id FROM projection_search_values WHERE nonblank=1 AND id IN ('+sql+')'
        matched='SELECT doc_id FROM material_search_keys WHERE field=? AND value_id IN ('+sql+')'
        params=[field,*args]
        if field=='_grammar_classes':
            matched='SELECT id doc_id FROM material_search_documents d WHERE id IN ('+matched+") AND EXISTS(SELECT 1 FROM json_each(d.classes) WHERE value=?)"
            params.append(value)
        query='''WITH matched AS MATERIALIZED ('''+matched+'''),
          hits AS MATERIALIZED (SELECT r.kind,r.owner_id id FROM material_search_records r
          WHERE r.context=? AND r.doc_id IN (SELECT doc_id FROM matched)
          UNION SELECT w.kind,w.owner_id id FROM gloss_search_words w
          JOIN material_search_word_docs d ON d.recipe_id=w.recipe_id WHERE d.context=? AND d.doc_id IN (SELECT doc_id FROM matched)'''
        params.extend([self.context,self.context])
        if field in ('all','examples') or field.startswith('layer:'):
            query+=''' UNION SELECT c.kind,c.owner_id id FROM material_search_custom c
              WHERE c.origin='cell' AND c.value_id IN ('''+sql+')'
            params+=args
            if field.startswith('layer:'):query+=' AND c.field=?';params.append(field)
        query+=' ) SELECT DISTINCT q.target_id FROM hits h JOIN dictionary_query_owners q ON q.kind=h.kind AND q.id=h.id'
        found={r[0] for r in self.execute(query,params)}
        self.matches[key]=found
        return found
