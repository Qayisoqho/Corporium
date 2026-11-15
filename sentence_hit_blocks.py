"""Disposable inverted lists in blocks of 256 stable sentence identities.

One bit marks an owner at one word position. Unioning several matching values
therefore counts a position exactly once, including across different fields.
The original postings remain the source for rebuilding a changed block.
"""
from collections import defaultdict

import long_tasks
import material_search_index
import read_views
from search_keys import Values


WIDTH = 256
SCOPES = read_views.Cache(96*1024**2)
MATCHES = read_views.Cache(16*1024**2)
TABLES = ('sentence_hit_bits', 'sentence_hit_dirty', 'sentence_hit_owners')
SOURCES = {
    'basic': ('sentence_search_postings', 'p.field', 'p.value_id'),
    'recipe': ('gloss_search_words', "''", 'p.recipe_id'),
    'custom': ('material_search_custom', 'p.field', 'p.value_id'),
}


def drop(db):
    for name, in db.execute("SELECT name FROM sqlite_master WHERE type='trigger' AND name GLOB 'sentence_hit_*'").fetchall():
        db.execute('DROP TRIGGER "' + name.replace('"', '""') + '"')
    for table in TABLES:
        db.execute('DROP TABLE IF EXISTS ' + table)


def initialize(db):
    existing = available(db)
    read_views.initialize(db)
    db.executescript('''
        CREATE TABLE IF NOT EXISTS sentence_hit_owners(
          n INTEGER PRIMARY KEY AUTOINCREMENT, kind TEXT NOT NULL, id TEXT NOT NULL, UNIQUE(kind,id));
        CREATE TABLE IF NOT EXISTS sentence_hit_bits(
          family TEXT, field TEXT, value_id INTEGER, block INTEGER, word INTEGER, mask BLOB NOT NULL,
          PRIMARY KEY(family,field,value_id,block,word)) WITHOUT ROWID;
        CREATE INDEX IF NOT EXISTS sentence_hit_by_block ON sentence_hit_bits(family,block);
        CREATE INDEX IF NOT EXISTS sentence_hit_by_value ON sentence_hit_bits(family,value_id,field);
        CREATE TABLE IF NOT EXISTS sentence_hit_dirty(
          family TEXT, block INTEGER, PRIMARY KEY(family,block)) WITHOUT ROWID;
    ''')
    for table, kind in (('entries', 'corpus'), ('dictionary_examples', 'independent')):
        for event, ref in (('INSERT', 'NEW'), ('UPDATE OF id', 'NEW')):
            suffix = 'insert' if event == 'INSERT' else 'rename'
            condition = '' if event == 'INSERT' else ' WHEN OLD.id IS NOT NEW.id'
            db.execute(f"""CREATE TRIGGER IF NOT EXISTS sentence_hit_{table}_{suffix} AFTER {event} ON {table}{condition}
                BEGIN INSERT INTO sentence_hit_owners(kind,id) SELECT '{kind}',{ref}.id
                WHERE NOT EXISTS(SELECT 1 FROM sentence_hit_owners WHERE kind='{kind}' AND id={ref}.id); END""")
        if not existing:
            db.execute(f"INSERT INTO sentence_hit_owners(kind,id) SELECT '{kind}',id FROM {table} ORDER BY rowid")
    for family, (table, _, _) in SOURCES.items():
        for event in ('INSERT', 'UPDATE', 'DELETE'):
            refs = ('OLD','NEW') if event == 'UPDATE' else (('OLD',) if event == 'DELETE' else ('NEW',))
            body = ''
            for ref in refs:
                # Explicit NOT EXISTS also works inside an outer INSERT OR REPLACE.
                body += f"""INSERT INTO sentence_hit_dirty SELECT '{family}',n/{WIDTH}
                    FROM sentence_hit_owners o WHERE kind={ref}.kind AND id={ref}.owner_id
                    AND NOT EXISTS(SELECT 1 FROM sentence_hit_dirty d WHERE d.family='{family}' AND d.block=o.n/{WIDTH});"""
            db.execute(f'CREATE TRIGGER IF NOT EXISTS sentence_hit_{table}_{event} AFTER {event} ON {table} BEGIN {body} END')
        if not existing:
            db.execute(f'INSERT INTO sentence_hit_dirty SELECT ?,n/{WIDTH} FROM sentence_hit_owners GROUP BY n/{WIDTH}', (family,))


def available(db):
    return db.execute("SELECT 1 FROM sqlite_master WHERE name='sentence_hit_dirty'").fetchone() is not None


def families(field):
    if field == 'all':
        return ('basic','recipe','custom')
    if field == 'gloss':
        return ('recipe',)
    if field in ('layers','writings') or field.startswith(('layer:', 'writing:')):
        return ('custom',)
    return ('basic',)


def pending(db,field):
    if not available(db):return 0
    sources=families(field)
    marks=','.join('?' for _ in sources)
    blocks=db.execute('SELECT DISTINCT block FROM sentence_hit_dirty WHERE family IN ('+marks+') LIMIT 202',sources).fetchall()
    if not blocks:return 0
    # A single changed owner can dirty one block. Count live preparation work
    # without making every small edit open a progress dialog.
    if len(blocks)==1:return 1
    slots=','.join('?' for _ in blocks)
    return db.execute('SELECT count(*) FROM (SELECT n FROM sentence_hit_owners WHERE n/'+str(WIDTH)+' IN ('+slots+') LIMIT 201)',[r[0] for r in blocks]).fetchone()[0]


def refresh(db, field):
    for family in families(field):
        table, column, value = SOURCES[family]
        blocks = db.execute('SELECT block FROM sentence_hit_dirty WHERE family=?', (family,)).fetchall()
        for (block,) in long_tasks.steps(blocks):
            masks = {}
            start = block * WIDTH
            sql = f'''SELECT o.n,{column},{value},p.word FROM sentence_hit_owners o CROSS JOIN {table} p
                      WHERE o.n>=? AND o.n<? AND p.kind=o.kind AND p.owner_id=o.id'''
            for owner, path, term, word in db.execute(sql, (start,start+WIDTH)):
                key = (path,term,word)
                masks[key] = masks.get(key,0) | (1 << (owner-start))
            db.execute('DELETE FROM sentence_hit_bits WHERE family=? AND block=?', (family,block))
            db.executemany('INSERT INTO sentence_hit_bits VALUES(?,?,?,?,?,?)',
                ((family,path,term,block,word,mask.to_bytes((mask.bit_length()+7)//8,'little'))
                 for (path,term,word),mask in masks.items()))
            db.execute('DELETE FROM sentence_hit_dirty WHERE family=? AND block=?', (family,block))


def matching_masks(db,field,query,case,mode,text_notes,language,original):
    import sentence_search_index
    masks = defaultdict(dict)
    def merge(sql,params):
        for block,word,encoded in db.execute(sql,params):
            words=masks[block]
            words[word]=words.get(word,0) | int.from_bytes(encoded,'little')
    sources=families(field)
    text_ids=set()
    if 'basic' in sources:
        values,params=sentence_search_index.value_query(db,query,case,mode)
        paths=[field]
        if field=='all':
            paths=['ipa','translation','notes','language_notes']
            if original:paths+=['original','text_notes']
        elif field=='notes':
            paths=['notes','language_notes'] if text_notes else ['notes','language_notes','text_notes']
        slots=','.join('?' for _ in paths)
        merge(f"SELECT block,word,mask FROM sentence_hit_bits WHERE family='basic' AND field IN ({slots}) AND value_id IN ({values})",[*paths,*params])
        if text_notes and field in ('all','notes'):
            text_ids={r[0] for r in db.execute("SELECT owner_id FROM sentence_search_postings WHERE kind='text' AND field='notes' AND value_id IN ("+values+')',params)}
    if 'recipe' in sources:
        values,params=Values(db).query(query,case,mode)
        paths="('all_form','all_gloss')" if field=='all' else "('gloss')"
        merge("SELECT block,word,mask FROM sentence_hit_bits WHERE family='recipe' AND field='' AND value_id IN (SELECT recipe_id FROM gloss_search_keys WHERE field IN "+paths+' AND value_id IN ('+values+'))',params)
    if 'custom' in sources:
        sql,params=material_search_index.custom_hits(db,field,query,case,mode,language,blocks=True)
        merge(sql,params)
    return masks,text_ids


def match_key(db,field,query,case,mode,text_notes,language,original):
    domain='basic_hits' if field in ('form','translation','ipa','notes','original') else 'word_hits' if field in ('morpheme','gloss') else 'content'
    stamp=read_views.token(db,domain)
    schema=db.execute('PRAGMA main.schema_version').fetchone()[0]
    return (stamp,schema,field,query,case,mode,text_notes,language,original) if stamp else None


def search(db, scope, args, field, query, case, mode, page, size, text_notes, ids_only, language, original):
    import sentence_search_index
    import code_switching
    import sentence_scope_index
    scope = sentence_scope_index.narrow(db,scope)
    key = match_key(db,field,query,case,mode,text_notes,language,original)
    matched = MATCHES.get(key)
    if matched is None:
        matched = matching_masks(db,field,query,case,mode,text_notes,language,original)
        masks,text_ids = matched
        cost = sum(160+112*len(words) for words in masks.values())+160*len(text_ids)+512
        MATCHES.put(key,matched,cost)
    masks,text_ids = matched
    hits = {}
    for block, words in masks.items():
        combined = 0
        for bits in words.values():
            combined |= bits
        hits[block] = combined
    rows = []
    tokens = total = 0
    order = ' ORDER BY r.source_order,r.ordering,r.position'
    if hits or text_ids:
        ordinal = 'r._scope_n' if 'e.n AS _scope_n,' in scope else 'o.n'
        join = '' if ordinal=='r._scope_n' else ' JOIN sentence_hit_owners o ON o.kind=r.kind AND o.id=r.id'
        sql = ('SELECT '+ordinal+' n,r.kind,r.id,r.text_id,r.position,r.ordering,r.source_order FROM ('+scope+') r'+join)
        count = sum(mask.bit_count() for mask in hits.values())
        scope_key = None
        if count <= 100 and not text_ids:
            ids = []
            for block, mask in hits.items():
                while mask:
                    lowest = mask & -mask
                    ids.append(block*WIDTH + lowest.bit_length()-1)
                    mask ^= lowest
            placeholders=','.join('?' for _ in ids)
            owners=[r[0] for r in db.execute('SELECT id FROM sentence_hit_owners WHERE n IN ('+placeholders+')',ids)]
            # Constrain the UNION branches themselves. Joining the tiny ordinal
            # list alone can make SQLite materialize every sentence in the scope.
            sql+=' WHERE r.id IN ('+','.join('?' for _ in owners)+') AND '+ordinal+' IN ('+placeholders+')'
            args=[*args,*owners,*ids]
        else:
            stamp = read_views.token(db,'scope')
            if stamp:
                scope_key = (stamp,db.execute('PRAGMA main.schema_version').fetchone()[0],scope,tuple(args))
        rows = scoped_page(db,sql+order,args,hits,text_ids,masks,page,size,ids_only,scope_key)
        if ids_only:
            return rows
        total,tokens,page,rows,visible = rows
    elif ids_only:
        return sentence_search_index.collected_ids(ids_only,())
    else:
        page = 1
    positions = {}
    for row in rows:
        block,bit = divmod(row['n'],WIDTH)
        positions[(row['kind'],row['id'])] = sorted(w for w,bits in masks.get(block,{}).items() if w>=0 and bits & (1<<bit))
    # Only marked sentences need a membership check for the summary.
    codes = []
    if total:
        sql="""SELECT c.*,o.n FROM code_sentence_index c CROSS JOIN sentence_hit_owners o
               ON o.kind=c.owner_kind AND o.id=c.record_id"""
        for row in db.execute(sql):
            block,bit=divmod(row['n'],WIDTH)
            if hits.get(block,0) & visible.get(block,0) & (1<<bit):codes.append(row)
    return dict(total=total,tokens=tokens,page=page,keys=rows,positions=positions,code_summary=code_switching.summary_rows(db,codes))


def scoped_page(db,sql,args,hits,text_ids,masks,page,size,ids_only,scope_key):
    scope = SCOPES.get(scope_key)
    if scope is None:
        rows = []
        visible = defaultdict(int)
        for row in db.execute(sql,args):
            block,offset = divmod(row['n'],WIDTH)
            bit = 1 << offset
            visible[block] |= bit
            rows.append((block,bit,row))
        scope = rows,visible
        SCOPES.put(scope_key,scope,512*len(rows)+512*len(visible))
    rows,visible = scope
    if text_ids:
        for block,bit,row in rows:
            if row['kind']=='corpus' and row['text_id'] in text_ids:
                hits[block] = hits.get(block,0) | bit
    total = sum((mask & visible.get(block,0)).bit_count() for block,mask in hits.items())
    ordered = (row for block,bit,row in rows if hits.get(block,0) & bit)
    if ids_only:
        import sentence_search_index
        return sentence_search_index.collected_ids(ids_only,(row['id'] for row in ordered))
    page = min(max(1,page),max(1,(total+size-1)//size))
    tokens = sum((mask & visible.get(block,0)).bit_count() for block,words in masks.items() for word,mask in words.items() if word>=0)
    from itertools import islice
    return total,tokens,page,list(islice(ordered,(page-1)*size,page*size)),visible
