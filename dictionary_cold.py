"""Query native leaves before building a scope-wide dictionary projection.

The B-trees below index source columns/extension values. They contain no rendered
dictionary or sentence copies. Candidate definitions still use the established
matcher, and changed inherited words use the established effective-slot reader.
"""
from functools import lru_cache
from itertools import islice
import json
import re
import unicodedata
import hashlib

import corpus
import dictionary_search as search
import long_tasks
import material_search_index as material
import record_sources
import read_views

SOURCE_VALUES=read_views.Cache(64*1024**2)
CHANGED_WORDS=read_views.Cache(8*1024**2)
HEADER_HITS=read_views.Cache(16*1024**2)
OWN_RESULTS=read_views.Cache(16*1024**2)
EVIDENCE_RESULTS=read_views.Cache(16*1024**2)
HEADER_REFERENCES=read_views.Cache(4*1024**2)
EFFECTIVE_VALUES=read_views.Cache(64*1024**2)
REFERENCE_KEYS=tuple(key for key in search.LABELS if key.endswith('_id') and key not in search.HIDDEN_KEYS)
REFERENCE_VALUE=re.compile(r'"(?:'+'|'.join(REFERENCE_KEYS)+r')"\s*:\s*"([^"\\]*)"')
REFERENCE_ARRAY=re.compile(r'"(?:features|semantic_classes|speakers)"\s*:\s*\[([^\]]*)\]')
ANNOTATION_ID=re.compile(r',?"annotation_id"\s*:\s*"[^"\\]*"\s*,?')


def source_references(extra):
    if '\\' not in extra:
        found=set(REFERENCE_VALUE.findall(extra))
        for value in REFERENCE_ARRAY.findall(extra):found.update(re.findall(r'"([^"\\]*)"',value))
        return found
    found=set()
    def walk(value):
        if isinstance(value,dict):
            for key,item in value.items():
                if key in REFERENCE_KEYS and isinstance(item,str):found.add(item)
                elif key in ('features','semantic_classes','speakers') and isinstance(item,list):found.update(v for v in item if isinstance(v,str))
                else:walk(item)
        elif isinstance(value,list):
            for item in value:walk(item)
    walk(json.loads(extra))
    return found

SCALARS="value_type NOT IN ('object','array','null') AND value IS NOT NULL AND value<>''"
EXTRA="json_remove(extra,"+','.join("'$."+key+"'" for key in sorted(search.HIDDEN_KEYS))+')'
INDEXES=('dictionary_source_leaves_v2','dictionary_source_special','sentence_source_gloss','sentence_source_extra','annotation_source_value',
         'dictionary_changed_binding','dictionary_inherited_binding')
SPECIAL="slot IN ('gloss_addition','base_id','pos','subclass') AND "+SCALARS


def initialize(db):
    if not record_sources.native(db):return
    db.execute(f'''CREATE INDEX IF NOT EXISTS dictionary_source_leaves_v2 ON dictionary_value_rows
        (value,slot,target_kind,target_id,parent,node,value_type) WHERE {SCALARS}''')
    db.execute(f'''CREATE INDEX IF NOT EXISTS dictionary_source_special ON dictionary_value_rows
        (slot,target_kind,target_id,parent,value,value_type) WHERE {SPECIAL}''')
    db.execute('CREATE INDEX IF NOT EXISTS sentence_source_gloss ON sentence_word_rows(gloss,kind,owner_id,position)')
    db.execute(f'CREATE INDEX IF NOT EXISTS sentence_source_extra ON sentence_word_rows({EXTRA},kind,owner_id,position)')
    db.execute('CREATE INDEX IF NOT EXISTS annotation_source_value ON annotation_cells(value,id)')
    db.execute('''CREATE INDEX IF NOT EXISTS dictionary_changed_binding ON gloss_bindings(owner_kind,owner_id,meaning_id)
                  WHERE source_binding_revision IS NOT revision''')
    db.execute("""CREATE INDEX IF NOT EXISTS dictionary_inherited_binding ON gloss_bindings(meaning_id,source_meaning_revision,owner_kind,owner_id)
                  WHERE mode='inherit'""")
    record_sources.schema_sql(db, '''
      CREATE TABLE IF NOT EXISTS dictionary_cold_value_state(id INTEGER PRIMARY KEY CHECK(id=1),identity BLOB,version BLOB,base BLOB,active INTEGER DEFAULT 0,header BLOB,manual BLOB);
      INSERT OR IGNORE INTO dictionary_cold_value_state(id,identity,version,base) VALUES(1,randomblob(16),X'',X'');
      CREATE TABLE IF NOT EXISTS dictionary_cold_value_dirty(field TEXT,value TEXT,PRIMARY KEY(field,value)) WITHOUT ROWID;
      CREATE TABLE IF NOT EXISTS dictionary_cold_query_state(context TEXT PRIMARY KEY,token BLOB);
    ''')
    if 'active' not in {r[1] for r in db.execute('PRAGMA table_info(dictionary_cold_value_state)')}:
        db.execute('ALTER TABLE dictionary_cold_value_state ADD COLUMN active INTEGER DEFAULT 0')
    if 'header' not in {r[1] for r in db.execute('PRAGMA table_info(dictionary_cold_value_state)')}:
        db.execute('ALTER TABLE dictionary_cold_value_state ADD COLUMN header BLOB')
    if 'manual' not in {r[1] for r in db.execute('PRAGMA table_info(dictionary_cold_value_state)')}:
        db.execute('ALTER TABLE dictionary_cold_value_state ADD COLUMN manual BLOB')
    db.execute('UPDATE dictionary_cold_value_state SET header=randomblob(16) WHERE header IS NULL')
    db.execute('UPDATE dictionary_cold_value_state SET manual=randomblob(16) WHERE manual IS NULL')
    identity=db.execute('SELECT identity FROM dictionary_cold_value_state WHERE id=1').fetchone()[0]
    if SOURCE_VALUES.get((db.execute('PRAGMA database_list').fetchone()[2],identity)) is None:
        # A new process has no value bag to advance. Do not accumulate copied
        # extension values through imports while nobody uses this search path.
        db.execute('UPDATE dictionary_cold_value_state SET active=0 WHERE id=1')
        db.execute('DELETE FROM dictionary_cold_value_dirty')
    for event in ('INSERT','UPDATE','DELETE'):
        when=' WHEN OLD.form IS NOT NEW.form OR OLD.gloss IS NOT NEW.gloss OR OLD.extra IS NOT NEW.extra' if event=='UPDATE' else ''
        sql='UPDATE dictionary_cold_value_state SET version=randomblob(16) WHERE id=1;'
        if event!='DELETE':
            for field,value in (('form','NEW.form'),('gloss','NEW.gloss'),('extra',EXTRA.replace('extra,','NEW.extra,'))):
                sql+=f"INSERT INTO dictionary_cold_value_dirty SELECT '{field}',{value} FROM dictionary_cold_value_state WHERE active=1 AND {value} IS NOT NULL ON CONFLICT DO NOTHING;"
        record_sources.trigger(db,'dictionary_cold_value_'+event,f'AFTER {event} ON sentence_word_rows{when} BEGIN {sql} END')
        record_sources.trigger(db,'dictionary_cold_header_'+event,f'''AFTER {event} ON sentence_text_rows
            BEGIN UPDATE dictionary_cold_value_state SET header=randomblob(16) WHERE id=1; END''')
        for table in ('annotation_cells','annotation_layers'):
            record_sources.trigger(db,'dictionary_cold_'+table+'_'+event,f'''AFTER {event} ON {table}
                BEGIN UPDATE dictionary_cold_value_state SET manual=randomblob(16) WHERE id=1; END''')
        for table in ('independent_frozen_values','independent_override_values'):
            if not db.execute('SELECT 1 FROM sqlite_master WHERE name=?',(table,)).fetchone():continue
            refs=('OLD','NEW') if event=='UPDATE' else ('OLD',) if event=='DELETE' else ('NEW',)
            def external(ref):
                owner=(f'{ref}.owner_id' if table=='independent_frozen_values' else
                       f'(SELECT example_id FROM independent_word_overrides WHERE id={ref}.parent_id AND snapshot={ref}.snapshot)')
                return f"({owner} IS NOT NULL AND NOT {record_sources.is_native('dictionary_examples',owner)})"
            record_sources.trigger(db,'dictionary_cold_'+table+'_'+event,f'''AFTER {event} ON {table}
                WHEN {' OR '.join(external(ref) for ref in refs)}
                BEGIN UPDATE dictionary_cold_value_state SET version=randomblob(16) WHERE id=1; END''')


def drop(db):
    for event in ('INSERT','UPDATE','DELETE'):
        db.execute('DROP TRIGGER IF EXISTS dictionary_cold_value_'+event)
        db.execute('DROP TRIGGER IF EXISTS dictionary_cold_header_'+event)
        for table in ('annotation_cells','annotation_layers','independent_frozen_values','independent_override_values'):
            db.execute('DROP TRIGGER IF EXISTS dictionary_cold_'+table+'_'+event)
    for name in ('dictionary_cold_value_dirty','dictionary_cold_value_state','dictionary_cold_query_state'):db.execute('DROP TABLE IF EXISTS '+name)
    for name in INDEXES:db.execute('DROP INDEX IF EXISTS '+name)


def source_values(db):
    identity,version,base,active=db.execute('SELECT identity,version,base,active FROM dictionary_cold_value_state WHERE id=1').fetchone()
    key=(db.execute('PRAGMA database_list').fetchone()[2],identity)
    saved=SOURCE_VALUES.get(key)
    if saved and saved[0]==version:
        if not active:db.execute('UPDATE dictionary_cold_value_state SET active=1,base=version WHERE id=1')
        return saved[1]
    if saved and active and saved[0]==base:
        values={field:set(items) for field,items in saved[1].items()}
        for field,value in db.execute('SELECT field,value FROM dictionary_cold_value_dirty'):
            values[field].add(value)
            if field=='extra':values['references'].update(source_references(value))
    else:
        values={'form':{r[0] for r in long_tasks.steps(db.execute('SELECT DISTINCT form FROM sentence_word_rows INDEXED BY sentence_word_form'))},
                'gloss':{r[0] for r in long_tasks.steps(distinct(db,'sentence_word_rows','sentence_source_gloss','gloss'))}}
        values['extra']={r[0] for r in long_tasks.steps(distinct(db,'sentence_word_rows','sentence_source_extra',EXTRA))}
        values['references']=set()
        for extra in values['extra']:values['references'].update(source_references(extra))
    # Old keys can remain in this bounded negative prefilter: every positive is
    # joined to live source rows. Rollback/process changes must match the base
    # version, otherwise rebuild from SQLite rather than trust a missing queue.
    db.execute('DELETE FROM dictionary_cold_value_dirty')
    db.execute('UPDATE dictionary_cold_value_state SET base=version,active=1 WHERE id=1')
    values={field:frozenset(items) for field,items in values.items()}
    cost=sum(256+4*len(str(value)) for items in values.values() for value in items)
    SOURCE_VALUES.put(key,(version,values),cost)
    return values


def available(db):
    return db.execute("SELECT count(*) FROM sqlite_master WHERE type='index' AND name IN ("+','.join('?' for _ in INDEXES)+')',INDEXES).fetchone()[0]==len(INDEXES)


def batches(items,size=200):
    iterator=iter(items)
    while batch:=list(islice(iterator,size)):yield batch


def distinct(db,table,index,column,where='1'):
    # Seek the next different key, rather than walk every repeated word/blob.
    # BINARY ordering is essential: case-sensitive searches distinguish peers.
    return db.execute(f'''WITH RECURSIVE keys(value) AS (
      SELECT min({column}) FROM {table} INDEXED BY {index} WHERE {where}
      UNION ALL SELECT (SELECT min({column}) FROM {table} INDEXED BY {index}
        WHERE {where} AND {column}>keys.value) FROM keys WHERE value IS NOT NULL)
      SELECT value FROM keys WHERE value IS NOT NULL''')


def reference_pattern(keys):
    trie={}
    for key in keys:
        branch=trie
        for char in key:branch=branch.setdefault(char,{})
        branch['']=None
    def render(branch):
        parts=[re.escape(key)+render(child) for key,child in branch.items() if key]
        pattern=parts[0] if len(parts)==1 else '(?:'+'|'.join(parts)+')' if parts else ''
        return '(?:'+pattern+')?' if '' in branch and pattern else pattern
    return re.compile('"'+render(trie)+'"') if trie else None


class Query:
    def __init__(self,db,lid,mode,query,case):
        import dictionary_own_index as own
        self.db,self.lid,self.mode=db,lid,mode
        self.query,self.case=query,case
        self.needle=corpus.normalize(query,case)
        # In Unicode 14/15 these ASCII characters cannot be produced by NFC or
        # case folding of a non-ASCII character. They are safe negative anchors;
        # the complete Unicode matcher still verifies every positive. Unknown
        # Unicode versions use the full matcher. Exhaustively checked in tests.
        anchors=re.findall('[bcdegmopqruvxz0-9]+',self.needle.lower()) if unicodedata.unidata_version in ('14.0.0','15.0.0') else []
        self.anchor=max(anchors,key=len,default='')
        self.hit=lru_cache(maxsize=32768)(lambda text:bool(text is not None and str(text).strip() and self.needle in corpus.normalize(str(text),case)))
        self.index=own.shared_index(db,lid)
        self.shared=dict(self.index.names)
        self.rows={};self.missing=set();self.row_names={}
        self.references=set()
        self.reference_pattern=None
        self.complete=False
        self.named={};self.base_ids=set();self.checked=set()
        self.header_references=set()
        self.extra_matches=lru_cache(maxsize=1024)(self._extra_matches)
        self.translated=any(self.hit(v) for v in (*search.ENUMS.values(),*search.categories.TAG_NAMES.values(),'是','否'))
        self.names=lru_cache(maxsize=4096)(self.name)
        outer=self
        class Names:
            def get(self,key,default=None):
                value=outer.names(key)
                return default if value is None else value
        self.index.names=Names()

    def definitions(self,ids):
        import dictionary_own_index as own
        for batch in batches(ids):
            missing=[key for key in batch if key not in self.rows and key not in self.missing]
            if missing:
                self.rows.update((row['id'],row) for row in own.definitions(self.db,self.lid,self.mode,missing))
                self.missing.update(set(missing)-self.rows.keys())
            for key in batch:
                if key in self.rows:yield self.rows[key]

    def name(self,key):
        # Names are raw research labels, not recursively resolved references.
        ids={r[0] for r in self.db.execute('SELECT id FROM lexemes WHERE id=? UNION ALL SELECT id FROM morphemes WHERE id=?',(key,key))}
        ids.update(r[0] for r in self.db.execute(f'''SELECT target_id FROM dictionary_value_rows
            INDEXED BY dictionary_source_leaves_v2 WHERE {SCALARS} AND value=? AND slot='id' ''',(key,)))
        import dictionary_own_index as own
        rows=list(self.definitions(ids))
        def order(row):
            number=row.get('number') if self.mode=='morphemes' else row['body'].get('homonym_number')
            position=None if self.mode=='morphemes' else row.get('rowid')
            return (row['headword'].translate(str.maketrans('ABCDEFGHIJKLMNOPQRSTUVWXYZ','abcdefghijklmnopqrstuvwxyz')),
                    number is not None,number or 0,position is not None,position or 0,row['target_kind'],row['id'])
        rows.sort(key=order)
        value=self.shared.get(key)
        for row in rows:value=self.registered(row).get(key,value)
        return value

    def registered(self,row):
        if row['id'] not in self.row_names:self.row_names[row['id']]=search.registered_names(row,row['body'])
        return self.row_names[row['id']]

    def matches(self,body,prefix=(),project=True):
        return any(self.hit(v) for v in self.index.document(dict(id='',headword='',body=body),
            include_extra=False,prefix=prefix,project=project,all_only=True).get('all',()))

    def condition(self,column):
        precise=f'dictionary_cold_hit({column})'
        return f"(instr(lower({column}),'{self.anchor}') AND {precise})" if self.anchor else precise

    def _extra_matches(self,extra,prefix):
        if extra=='{}':return False
        if prefix==('examples',):self.header_references.update(source_references(extra))
        # Raw text is a conservative negative only. Escapes and translated
        # values are always checked by the canonical decoded matcher.
        composed=prefix==('examples',) and 'gloss_addition' in extra
        if not composed and not self.translated and '\\' not in extra and not self.hit(extra) and not (self.reference_pattern and self.reference_pattern.search(extra)):return False
        return self.matches(json.loads(extra),prefix,prefix==('examples',))

    def own(self,only=None):
        db=self.db
        db.create_function('dictionary_cold_hit',1,self.hit,deterministic=True)
        kinds=('morpheme',) if self.mode=='morphemes' else ('lexeme','morpheme') if self.mode=='targets' else ('lexeme',)
        direct=set();total=0
        for kind in (kinds if only is None else ()):
            table,field=('lexemes','headword') if kind=='lexeme' else ('morphemes','form')
            args=(self.lid,self.lid)
            total+=db.execute(f"SELECT count(*) FROM {table} WHERE ?='all' OR language_id=?",args).fetchone()[0]
            direct.update((kind,r[0]) for r in db.execute(f"SELECT id FROM {table} WHERE (?='all' OR language_id=?) AND {self.condition(field)}",args))
        if only is None and len(direct)==total:
            self.complete=True
            return direct
        # Match each distinct scalar once; repeated empty/default leaves require
        # neither Python tree assembly nor normalization on every occurrence.
        values=[r[0] for r in long_tasks.steps(db.execute(f'''SELECT DISTINCT value FROM dictionary_value_rows
            INDEXED BY dictionary_source_leaves_v2 WHERE {SCALARS} AND {self.condition('value')}'''))] if only is None else []
        ids=set(only or ())
        for batch in batches(values):
            ids.update(r[0] for r in db.execute(f'''SELECT target_id FROM dictionary_value_rows
                INDEXED BY dictionary_source_leaves_v2 WHERE {SCALARS} AND value IN ({','.join('?' for _ in batch)})''',batch))
        for kind in (kinds if only is None else ()):
            table,field=('lexemes','headword') if kind=='lexeme' else ('morphemes','form')
            number='homonym_number' if kind=='lexeme' else 'number'
            ids.update(r[0] for r in db.execute(f'''SELECT id FROM {table} WHERE (?='all' OR language_id=?)
                AND ({self.condition(field)} OR {self.condition(number)})''',(self.lid,self.lid)))
        # Composed glosses and translated values may not contain the needle in
        # any raw leaf. Keep their owners for exact canonical verification.
        translated=[key for key,value in {**search.ENUMS,**search.categories.TAG_NAMES}.items() if self.hit(value)]
        if self.hit('是'):translated.append(1)
        if self.hit('否'):translated.append(0)
        for value in (translated if only is None else ()):
            ids.update(r[0] for r in db.execute(f'''SELECT target_id FROM dictionary_value_rows
                INDEXED BY dictionary_source_leaves_v2 WHERE {SCALARS} AND value=?''',(value,)))
        if only is None:
            additions={r[0] for r in db.execute(f'''SELECT target_id FROM dictionary_value_rows
                INDEXED BY dictionary_source_special WHERE {SPECIAL} AND slot='gloss_addition' ''')}
            # Composition inserts a dot, or joins a digit to the next label.
            # An ASCII letter-only anchor must therefore already occur in a
            # raw gloss/addition in the same definition, including its base sense.
            anchors=re.findall('[bcdegmopqruvxz]+',self.anchor)
            if anchors:
                import dictionary_rows
                anchor=max(anchors,key=len)
                possible={r[0] for r in db.execute(f'''SELECT v.target_id FROM {dictionary_rows.lookup_values(db)}
                    WHERE {dictionary_rows.LOOKUP_VALUES} AND v.slot IN ('short_gloss','gloss')
                      AND instr(lower(v.value),?)''',(anchor,))}
                possible.update(r[0] for r in db.execute(f'''SELECT target_id FROM dictionary_value_rows
                    INDEXED BY dictionary_source_special WHERE {SPECIAL} AND slot='gloss_addition' AND instr(lower(value),?)''',(anchor,)))
                additions.intersection_update(possible)
            ids.update(additions)
        if only is None and '/' in self.needle:
            ids.update(r[0] for r in db.execute(f'''SELECT target_id FROM dictionary_value_rows
                INDEXED BY dictionary_source_special WHERE {SPECIAL} AND slot IN ('pos','subclass')'''))
        references={key for key,value in self.shared.items() if self.hit(value)}
        references.update(key for key,value in self.index.people.items() if self.hit(value))
        references.update(key for key,tag in self.index.tags.items()
                          if any(self.hit(v) for v in (tag.get('symbol',''),tag.get('description',''),*tag.get('aliases',[]))))
        old_references=set()
        for owner in ids:old_references.update(self.named.pop(owner,()))
        for row in list(self.definitions(ids)):
            keys=frozenset(key for key,value in self.registered(row).items() if self.hit(value))
            if keys:self.named[row['id']]=keys
        for keys in self.named.values():references.update(keys)
        self.references=references
        self.reference_pattern=reference_pattern(references)
        for batch in batches(references|old_references):
            ids.update(r[0] for r in db.execute(f'''SELECT target_id FROM dictionary_value_rows
                INDEXED BY dictionary_source_leaves_v2 WHERE {SCALARS} AND value IN ({','.join('?' for _ in batch)})''',batch))
        # Reverse base relations and attached media are small, separate source
        # sets, and use the same visible-value rules as the ordinary index.
        extra={}
        ids.update(self.base_ids)
        self.base_ids=set()
        for row in db.execute(f'''SELECT target_id,value FROM dictionary_value_rows INDEXED BY dictionary_source_special
            WHERE {SPECIAL} AND slot='base_id' '''):
            for owner in self.definitions([row[0]]):
                rel=owner['body'].get('relation') or {}
                if rel.get('base_id')==row[1]:
                    self.base_ids.add(row[1])
                    extra.setdefault(row[1],[]).append({'relation':[dict(type=rel.get('type'),base_id=row[0])]})
        ids.update(self.base_ids)
        media_cache={}
        for row in db.execute("""SELECT m.kind,m.record_id,m.body,a.name FROM object_media m
            LEFT JOIN timeline_media a ON a.id=m.asset_id WHERE ?='all' OR m.language_id=?""",(self.lid,self.lid)):
            key=(row['body'],row['name'])
            if key not in media_cache:
                media_cache[key]=self.matches({'media':[json.loads(row['body']),{'name':row['name']}]},('media',),False)
            if not media_cache[key]:continue
            owners=[row['record_id']] if row['kind']=='lexeme' else [r[0] for r in db.execute('''SELECT l.lexeme_id
                FROM independent_links l JOIN dictionary_examples e ON e.id=l.example_id
                WHERE l.example_id=? AND (?='all' OR e.language_id=?)''',(row['record_id'],self.lid,self.lid))]
            for owner in owners:extra.setdefault(owner,[]).append({'notes':' '.join([self.needle])})
        found=set()
        for owner,items in extra.items():
            if any(self.matches(item,('extra',),False) for item in items):
                for row in self.definitions([owner]):found.add((row['target_kind'],owner))
        for row in long_tasks.steps(self.definitions(ids)):
            if any(self.hit(v) for v in self.index.document(row,include_extra=True,all_only=True,project=False).get('all',())):
                found.add((row['target_kind'],row['id']))
        self.checked=ids|set(extra)
        return found

    def own_cached(self):
        db=self.db
        context='cold:'+hashlib.sha256(repr((self.lid,self.mode,self.query,self.case)).encode()).hexdigest()
        state=db.execute('SELECT token FROM dictionary_cold_query_state WHERE context=?',(context,)).fetchone()
        saved=OWN_RESULTS.get(state[0]) if state else None
        catalog=db.execute('SELECT 1 FROM dictionary_own_catalog_dirty WHERE context=?',(context,)).fetchone()
        dirty={r[0] for r in db.execute('SELECT id FROM dictionary_own_dirty WHERE context=?',(context,))}
        if saved and not catalog:
            found,named,base,refs=saved
            self.named=dict(named);self.base_ids=set(base);self.references=set(refs)
            self.reference_pattern=reference_pattern(refs)
            if not dirty:return set(found)
            updated=self.own(dirty)
            result={pair for pair in found if pair[1] not in self.checked}|updated
        else:
            result=self.own()
        if self.complete:return result
        db.execute('INSERT OR IGNORE INTO dictionary_own_scopes VALUES(?,?,?)',(context,self.lid,self.mode))
        db.execute('DELETE FROM dictionary_own_dirty WHERE context=?',(context,))
        db.execute('DELETE FROM dictionary_own_catalog_dirty WHERE context=?',(context,))
        token=db.execute('SELECT randomblob(16)').fetchone()[0]
        db.execute('INSERT OR REPLACE INTO dictionary_cold_query_state VALUES(?,?)',(context,token))
        for old, in db.execute('SELECT context FROM dictionary_cold_query_state ORDER BY rowid DESC LIMIT -1 OFFSET 8').fetchall():
            for table in ('dictionary_own_scopes','dictionary_own_dirty','dictionary_own_catalog_dirty','dictionary_cold_query_state'):
                db.execute('DELETE FROM '+table+' WHERE context=?',(old,))
        result=frozenset(result);refs=frozenset(self.references);base=frozenset(self.base_ids)
        cost=512+sum(256+4*len(rid) for _,rid in result)+sum(256+sum(128+4*len(key) for key in keys) for keys in self.named.values())+sum(128+4*len(key) for key in refs|base)
        OWN_RESULTS.put(token,(result,dict(self.named),base,refs),cost)
        return set(result)

    def evidence(self,kinds):
        import gloss_search_index as words
        import gloss_inheritance as gloss
        import sentence_rows
        db=self.db
        db.execute('DROP TABLE IF EXISTS temp.dictionary_cold_evidence')
        db.execute('CREATE TEMP TABLE dictionary_cold_evidence(kind TEXT,id TEXT,PRIMARY KEY(kind,id)) WITHOUT ROWID')
        native_values=source_values(db)
        version,header_token,manual_token=db.execute('SELECT version,header,manual FROM dictionary_cold_value_state WHERE id=1').fetchone()
        prior_header_refs=HEADER_REFERENCES.get(header_token)
        def cache_key(header_refs):
            used=self.references & (native_values['references']|header_refs)
            labels=tuple(sorted((key,self.names(key),repr(self.index.tags.get(key)),self.index.people.get(key)) for key in used))
            return (self.lid,self.mode,self.query,self.case,version,header_token,manual_token,
                    read_views.token(db,'word_hits'),read_views.token(db,'scope'),labels)
        if prior_header_refs is not None:
            saved=EVIDENCE_RESULTS.get(cache_key(prior_header_refs))
            if saved is not None:
                db.executemany('INSERT INTO dictionary_cold_evidence VALUES(?,?)',saved)
                sql,args=material.matching_targets('SELECT kind,id FROM dictionary_cold_evidence',(),self.lid,kinds,db=db)
                return {tuple(row) for row in db.execute(sql,args)}
        db.execute('DROP TABLE IF EXISTS temp.dictionary_cold_changed')
        db.execute('CREATE TEMP TABLE dictionary_cold_changed(kind TEXT,id TEXT,PRIMARY KEY(kind,id)) WITHOUT ROWID')
        token=read_views.token(db,'word_hits')
        changed=CHANGED_WORDS.get(token) if token is not None else None
        if changed is None:
            changed=tuple(tuple(row) for row in db.execute('''
                SELECT b.owner_kind,b.owner_id FROM gloss_bindings b INDEXED BY dictionary_changed_binding
                JOIN gloss_meanings m ON m.id=b.meaning_id WHERE b.source_binding_revision IS NOT b.revision
                UNION SELECT b.owner_kind,b.owner_id FROM gloss_meanings m
                CROSS JOIN gloss_bindings b INDEXED BY dictionary_inherited_binding ON b.meaning_id=m.id
                WHERE b.mode='inherit' AND b.source_meaning_revision IS NOT m.revision'''))
            if token is not None:CHANGED_WORDS.put(token,changed,256+sum(256+4*len(rid) for _,rid in changed))
        db.executemany('INSERT OR IGNORE INTO dictionary_cold_changed VALUES(?,?)',changed)
        db.execute("INSERT OR IGNORE INTO dictionary_cold_changed SELECT 'independent',example_id FROM independent_word_overrides")
        # Frozen metadata is hidden, but the override source can replace visible
        # fields. Changed owners are checked through the canonical native reader.
        for field,index in (('form','sentence_word_form'),('gloss','sentence_source_gloss')):
            values=native_values[field]
            for value in long_tasks.steps(values):
                if not self.hit(value):continue
                for kind in ('corpus','independent'):
                    db.execute(f'''INSERT OR IGNORE INTO dictionary_cold_evidence SELECT kind,owner_id
                        FROM sentence_word_rows INDEXED BY {index} WHERE kind=? AND {field}=?
                        AND NOT EXISTS(SELECT 1 FROM dictionary_cold_changed c WHERE c.kind=sentence_word_rows.kind AND c.id=owner_id)''',(kind,value))
        for value in long_tasks.steps(native_values['extra']):
            if not self.extra_matches(value,('examples','words')):continue
            db.execute(f'''INSERT OR IGNORE INTO dictionary_cold_evidence SELECT kind,owner_id
                FROM sentence_word_rows INDEXED BY sentence_source_extra WHERE {EXTRA}=?
                AND NOT EXISTS(SELECT 1 FROM dictionary_cold_changed c WHERE c.kind=sentence_word_rows.kind AND c.id=owner_id)''',(value,))
        db.create_function('dictionary_cold_hit',1,self.hit,deterministic=True)
        # Header fields are already native scalars; the uncommon extension bag
        # alone needs the original leaf matcher (including label references).
        db.create_function('dictionary_cold_extra',1,lambda extra:self.extra_matches(extra,('examples',)))
        fields=[self.condition(f) for f in sentence_rows.FIELDS if f not in search.HIDDEN_KEYS and f!='edited']
        fields+=["(edited_type='true' AND dictionary_cold_hit('是'))","(edited_type='false' AND dictionary_cold_hit('否'))",
                 "(edited_type NOT IN ('true','false') AND dictionary_cold_hit(edited))"]
        header_key=(header_token,self.query,self.case)
        headers=HEADER_HITS.get(header_key) if header_token is not None else None
        if headers is None:
            headers=tuple(tuple(row) for row in db.execute('SELECT kind,owner_id FROM sentence_text_rows WHERE '+' OR '.join(fields)))
            if header_token is not None:HEADER_HITS.put(header_key,headers,256+sum(256+4*len(rid) for _,rid in headers))
        db.executemany('INSERT OR IGNORE INTO dictionary_cold_evidence VALUES(?,?)',headers)
        db.execute('INSERT OR IGNORE INTO dictionary_cold_evidence SELECT kind,owner_id FROM sentence_text_rows WHERE dictionary_cold_extra(extra)')
        label_stamp=tuple(sorted((key,self.names(key),repr(self.index.tags.get(key)),self.index.people.get(key)) for key in native_values['references']))
        effective_key=(token,version,label_stamp)
        effective=EFFECTIVE_VALUES.get(effective_key)
        if effective is None:
            effective_matches=read_views.Cache(32*1024**2)
            groups={}
            def values(form,value,extra,binding):
                # Stable occurrence identities are hidden from full-field search.
                # Strip only that identity for the cache key; render the original
                # input so source hashes and frozen overrides keep their semantics.
                # Provider IDs and revision numbers only select a live label or
                # determine whether the source is current. Preserve those exact
                # comparisons, not unique per-occurrence revision timestamps.
                key=(form,value,ANNOTATION_ID.sub('',extra),tuple(
                    (item[0],item[2],item[3],item[4],item[5]==item[6],item[7]==item[10],item[8],item[9]) for item in binding))
                saved=effective_matches.get(key)
                if saved is not None:return saved
                body=words.effective_slot(form,value,extra,binding)
                result=tuple(self.index.document(dict(id='',headword='',body=body),include_extra=False,
                    prefix=('examples','words'),project=False,all_only=True).get('all',()))
                effective_matches.put(key,result,512+4*(len(extra)+len(str(binding))+len(form or '')+len(value or '')))
                return result
            for kind in ('corpus','independent'):
                ids=(r[0] for r in db.execute('SELECT id FROM dictionary_cold_changed WHERE kind=?',(kind,)))
                for batch in batches(ids):
                    for row,binding in words.effective_inputs(db,kind,batch):
                        items=values(row['form'],row['gloss'],row['extra'],binding)
                        groups.setdefault(items,set()).add((kind,row['owner_id']))
                    long_tasks.checkpoint()
            effective=tuple((items,tuple(owners)) for items,owners in groups.items())
            cost=sum(256+sum(128+4*len(value) for value in items)+sum(128+4*len(rid) for _,rid in owners) for items,owners in effective)
            EFFECTIVE_VALUES.put(effective_key,effective,cost)
        for items,owners in long_tasks.steps(effective):
            if any(self.hit(value) for value in items):
                db.executemany('INSERT OR IGNORE INTO dictionary_cold_evidence VALUES(?,?)',owners)
        # Use the existing validity checks without preparing a full manual index.
        layers,args=material.manual_hits(db,'all','contains',self.query,self.case,prepare=False)
        db.execute('INSERT OR IGNORE INTO dictionary_cold_evidence '+layers,args)
        header_refs=frozenset(self.header_references)
        HEADER_REFERENCES.put(header_token,header_refs,256+sum(128+4*len(key) for key in header_refs))
        records=tuple(tuple(row) for row in db.execute('SELECT kind,id FROM dictionary_cold_evidence'))
        EVIDENCE_RESULTS.put(cache_key(header_refs),records,256+sum(256+4*len(rid) for _,rid in records))
        sql,args=material.matching_targets('SELECT kind,id FROM dictionary_cold_evidence',(),self.lid,kinds,db=db)
        return {tuple(row) for row in db.execute(sql,args)}


def find(db,lid,mode,query,case,kinds):
    probe=Query(db,lid,mode,query,case)
    found=probe.own_cached()
    if not probe.complete:found.update(probe.evidence(kinds))
    return found

