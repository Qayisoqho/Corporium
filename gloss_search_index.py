"""Rebuildable effective words shared by structural input, never by occurrences.

Meaning edits dirty dependent recipes. Source/binding edits dirty owners. Both
queues are transactional, so rollback, undo and external SQL use the same path.
The full effective word is also the input to dictionary evidence projections.
"""
import copy
import hashlib
import json
import re
from collections import defaultdict, OrderedDict

import corpus
import gloss_inheritance as gloss
import long_tasks
from search_keys import Values

VERSION = 'shared-effective-words-v1'
TABLES = ('gloss_search_words', 'gloss_search_keys', 'gloss_search_dependencies',
          'gloss_search_dirty', 'gloss_search_recipes', 'gloss_search_owners', 'gloss_search_version')


def encode(value):
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(',', ':'))


def available(db):
    return bool(db.execute("SELECT 1 FROM sqlite_master WHERE name='gloss_search_version'").fetchone())


def queue(ref, kind, identity='id'):
    # An outer UPSERT overrides a trigger's OR IGNORE policy in SQLite.
    return f"INSERT INTO gloss_search_dirty SELECT '{kind}',{ref}.{identity} WHERE NOT EXISTS(SELECT 1 FROM gloss_search_dirty WHERE kind='{kind}' AND owner_id={ref}.{identity});"


def drop(db):
    for row in db.execute("SELECT name FROM sqlite_master WHERE type='trigger' AND name LIKE 'gloss_search_%'").fetchall():
        db.execute('DROP TRIGGER "'+row[0].replace('"', '""')+'"')
    for table in TABLES:
        db.execute('DROP TABLE IF EXISTS '+table)


def initialize(db):
    Values.initialize(db)
    db.executescript('''
      CREATE TABLE IF NOT EXISTS gloss_search_recipes(id INTEGER PRIMARY KEY,identity TEXT UNIQUE NOT NULL,
        body TEXT NOT NULL,output TEXT NOT NULL DEFAULT '',revision TEXT NOT NULL DEFAULT '',dirty INTEGER NOT NULL DEFAULT 1);
      CREATE INDEX IF NOT EXISTS gloss_search_recipe_dirty ON gloss_search_recipes(id) WHERE dirty=1;
      CREATE TABLE IF NOT EXISTS gloss_search_words(kind TEXT,owner_id TEXT,word INTEGER,recipe_id INTEGER,unit_id TEXT,
        PRIMARY KEY(kind,owner_id,word)) WITHOUT ROWID;
      CREATE INDEX IF NOT EXISTS gloss_search_recipe_words ON gloss_search_words(recipe_id,kind,owner_id,word);
      CREATE TABLE IF NOT EXISTS gloss_search_keys(recipe_id INTEGER,field TEXT,value_id INTEGER,
        PRIMARY KEY(recipe_id,field,value_id)) WITHOUT ROWID;
      CREATE INDEX IF NOT EXISTS gloss_search_key_values ON gloss_search_keys(value_id,field,recipe_id);
      CREATE TABLE IF NOT EXISTS gloss_search_dependencies(meaning_id TEXT,recipe_id INTEGER,
        PRIMARY KEY(meaning_id,recipe_id)) WITHOUT ROWID;
      CREATE INDEX IF NOT EXISTS gloss_search_recipe_dependencies ON gloss_search_dependencies(recipe_id,meaning_id);
      CREATE TABLE IF NOT EXISTS gloss_search_dirty(kind TEXT,owner_id TEXT,PRIMARY KEY(kind,owner_id)) WITHOUT ROWID;
      CREATE TABLE IF NOT EXISTS gloss_search_owners(kind TEXT,owner_id TEXT,PRIMARY KEY(kind,owner_id)) WITHOUT ROWID;
      CREATE TABLE IF NOT EXISTS gloss_search_version(value TEXT PRIMARY KEY);
    ''')
    if not db.execute('SELECT 1 FROM gloss_search_version WHERE value=?', (VERSION,)).fetchone():
        for table in TABLES:
            db.execute('DELETE FROM '+table)
        db.execute('INSERT INTO gloss_search_version VALUES(?)', (VERSION,))
    for row in db.execute("SELECT name FROM sqlite_master WHERE type='trigger' AND name LIKE 'gloss_search_%'").fetchall():
        db.execute('DROP TRIGGER "'+row[0].replace('"', '""')+'"')
    for table, kind in (('entries', 'corpus'), ('dictionary_examples', 'independent')):
        for event in ('INSERT', 'UPDATE', 'DELETE'):
            refs = ('OLD', 'NEW') if event == 'UPDATE' else ('OLD',) if event == 'DELETE' else ('NEW',)
            changed = ' WHEN OLD.body IS NOT NEW.body OR OLD.id IS NOT NEW.id' if event == 'UPDATE' else ''
            db.execute(f'CREATE TRIGGER gloss_search_{table}_{event} AFTER {event} ON {table}{changed} BEGIN '+''.join(queue(ref,kind) for ref in refs)+' END')
        db.execute(f"INSERT OR IGNORE INTO gloss_search_dirty SELECT ?,id FROM {table} s WHERE NOT EXISTS(SELECT 1 FROM gloss_search_owners o WHERE o.kind=? AND o.owner_id=s.id)", (kind, kind))
    for table in ('gloss_bindings', 'corpus_units'):
        for event in ('INSERT', 'UPDATE', 'DELETE'):
            refs = ('OLD', 'NEW') if event == 'UPDATE' else ('OLD',) if event == 'DELETE' else ('NEW',)
            statement = ''.join(f'INSERT INTO gloss_search_dirty SELECT {ref}.owner_kind,{ref}.owner_id WHERE NOT EXISTS(SELECT 1 FROM gloss_search_dirty WHERE kind={ref}.owner_kind AND owner_id={ref}.owner_id);' if table=='gloss_bindings' else queue(ref,'corpus','entry_id') for ref in refs)
            db.execute(f'CREATE TRIGGER gloss_search_{table}_{event} AFTER {event} ON {table} BEGIN '+statement+' END')
    db.execute('''CREATE TRIGGER gloss_search_meaning_update AFTER UPDATE ON gloss_meanings BEGIN
      UPDATE gloss_search_recipes SET dirty=1 WHERE id IN (
        SELECT recipe_id FROM gloss_search_dependencies WHERE meaning_id IN (OLD.id,NEW.id));
      INSERT INTO gloss_search_dirty SELECT DISTINCT owner_kind,owner_id FROM gloss_bindings b
        WHERE meaning_id IN (OLD.id,NEW.id) AND OLD.id IS NOT NEW.id AND NOT EXISTS(
          SELECT 1 FROM gloss_search_dirty d WHERE d.kind=b.owner_kind AND d.owner_id=b.owner_id);
      END''')
    for event in ('INSERT', 'DELETE'):
        ref = 'OLD' if event=='DELETE' else 'NEW'
        db.execute(f'''CREATE TRIGGER gloss_search_meaning_{event} AFTER {event} ON gloss_meanings BEGIN
          INSERT INTO gloss_search_dirty SELECT DISTINCT owner_kind,owner_id FROM gloss_bindings b WHERE meaning_id={ref}.id
            AND NOT EXISTS(SELECT 1 FROM gloss_search_dirty d WHERE d.kind=b.owner_kind AND d.owner_id=b.owner_id);
          UPDATE gloss_search_recipes SET dirty=1 WHERE id IN (SELECT recipe_id FROM gloss_search_dependencies WHERE meaning_id={ref}.id);
          END''')


def pending(db):
    if not available(db):
        return 0
    return db.execute('''SELECT count(*) FROM (SELECT 1 FROM gloss_search_dirty UNION ALL
      SELECT 1 FROM gloss_search_recipes WHERE dirty=1 LIMIT 201)''').fetchone()[0]


def recipe(word, rows):
    # Stable occurrence IDs are deliberately absent from the shared input.
    source = {k:v for k,v in word.items() if k not in ('annotation_id','unit_id')}
    bindings = [{k:r[k] for k in ('unit_key','meaning_id','mode','override_text','pattern',
                                 'revision','source_binding_revision','source_meaning_revision')} for r in rows]
    return {'word':source, 'bindings':bindings}


def render(value, meanings):
    word = value['word']
    rows = [{**r, 'meaning_gloss':meanings[r['meaning_id']]['gloss']} for r in value['bindings'] if r['meaning_id'] in meanings]
    clean = all(r['source_binding_revision']==r['revision'] and (r['mode']=='override' or
                r['source_meaning_revision']==meanings[r['meaning_id']]['revision']) for r in rows)
    if clean:
        return copy.deepcopy(word)
    identity = ('annotation_id','extra_layers','unit_id','linked_lexeme')
    derived = {'gloss_sources','unit_type','boundary_count','gloss_relations','segments','group_reviews','infix_ambiguous','analysis_form','morphemes'}
    source = {k:v for k,v in word.items() if k not in derived and k not in identity}
    output = gloss.render_word(source, rows)
    for key in identity:
        if key in word:
            output[key] = copy.deepcopy(word[key])
    return output


def owner_filter(table, alias):
    if table is None:return ''
    if not re.fullmatch(r'dictionary_query_records_[0-9a-f]{32}',table):
        raise ValueError('Invalid internal search scope')
    return f' AND EXISTS(SELECT 1 FROM "{table}" scope WHERE scope.kind={alias}.kind AND scope.id={alias}.owner_id)'


def refresh(db, owner_table=None):
    if not available(db):
        return
    if not db.in_transaction:
        db.execute('BEGIN')
    values = Values(db)
    total = pending(db)
    completed = 0
    # A bounded input cache avoids per-occurrence hashing/SQL for repeated words.
    cache = OrderedDict()
    cache_bytes = 0
    scope=owner_filter(owner_table,'d')
    while batch := db.execute('SELECT kind,owner_id FROM gloss_search_dirty d WHERE 1=1'+scope+' LIMIT 200').fetchall():
        for kind, table in (('corpus','entries'), ('independent','dictionary_examples')):
            ids = [r['owner_id'] for r in batch if r['kind']==kind]
            if not ids:
                continue
            marks = ','.join('?' for _ in ids)
            records = {r['id']:r['body'] for r in db.execute(f'SELECT id,body FROM {table} WHERE id IN ({marks})',ids)}
            gloss.prefetch(db,kind,list(records))
            # Derived-table writes invalidate the reader's per-connection
            # cache. Retain only this bounded batch's binding rows locally.
            bound={rid:gloss.bindings(db,kind,rid) for rid in records}
            for rid in long_tasks.steps(ids):
                old = [r[0] for r in db.execute('SELECT DISTINCT recipe_id FROM gloss_search_words WHERE kind=? AND owner_id=?',(kind,rid))]
                db.execute('DELETE FROM gloss_search_words WHERE kind=? AND owner_id=?',(kind,rid))
                if rid in records:
                    body = json.loads(records[rid])
                    groups = defaultdict(list)
                    for row in bound[rid]:
                        pos = gloss.at_word(body,row)
                        if pos is not None and gloss.source_hash(body['words'][pos])==row['source_hash']:
                            groups[pos].append(row)
                    unit_ids = {r['position']:r['id'] for r in db.execute("SELECT id,position FROM corpus_units WHERE entry_id=? AND active=1 AND kind='word'",(rid,))} if kind=='corpus' else {}
                    postings = []
                    for pos, word in enumerate(body.get('words',[])):
                        value = recipe(word,groups[pos])
                        serialized = encode(value)
                        recipe_id = cache.get(serialized)
                        if recipe_id is None:
                            identity = hashlib.sha256(serialized.encode('utf-8')).hexdigest()
                            row = db.execute('SELECT id,body FROM gloss_search_recipes WHERE identity=?',(identity,)).fetchone()
                            if row:
                                if row['body']!=serialized:
                                    raise RuntimeError('检索组合身份冲突')
                                recipe_id = row['id']
                            else:
                                recipe_id = db.execute('INSERT INTO gloss_search_recipes(identity,body) VALUES(?,?)',(identity,serialized)).lastrowid
                                deps = {r['meaning_id'] for r in groups[pos]}
                                db.executemany('INSERT INTO gloss_search_dependencies VALUES(?,?)',[(mid,recipe_id) for mid in deps])
                            cost = 256+4*len(serialized)
                            if cost<=1024**2:
                                cache[serialized]=recipe_id;cache_bytes+=cost
                                while len(cache)>2048 or cache_bytes>8*1024**2:
                                    key,_=cache.popitem(last=False);cache_bytes-=256+4*len(key)
                        else:
                            cache.move_to_end(serialized)
                        postings.append((kind,rid,pos,recipe_id,unit_ids.get(pos,word.get('annotation_id'))))
                    db.executemany('INSERT INTO gloss_search_words VALUES(?,?,?,?,?)',postings)
                    db.execute('INSERT OR IGNORE INTO gloss_search_owners VALUES(?,?)',(kind,rid))
                else:
                    db.execute('DELETE FROM gloss_search_owners WHERE kind=? AND owner_id=?',(kind,rid))
                db.execute('DELETE FROM gloss_search_dirty WHERE kind=? AND owner_id=?',(kind,rid))
                for recipe_id in old:
                    if db.execute('SELECT 1 FROM gloss_search_words WHERE recipe_id=? LIMIT 1',(recipe_id,)).fetchone():
                        continue
                    obsolete = [r[0] for r in db.execute('SELECT value_id FROM gloss_search_keys WHERE recipe_id=?',(recipe_id,))]
                    db.execute('DELETE FROM gloss_search_keys WHERE recipe_id=?',(recipe_id,))
                    db.execute('DELETE FROM gloss_search_dependencies WHERE recipe_id=?',(recipe_id,))
                    db.execute('DELETE FROM gloss_search_recipes WHERE id=?',(recipe_id,))
                    values.release(obsolete)
                    cache.clear();cache_bytes=0
                completed += 1
                long_tasks.checkpoint(None,'正在更新有效标注检索索引…')
    recipe_scope=f' AND EXISTS(SELECT 1 FROM gloss_search_words w JOIN "{owner_table}" scope ON scope.kind=w.kind AND scope.id=w.owner_id WHERE w.recipe_id=r.id)' if owner_table else ''
    while batch := db.execute('SELECT id,body,output,revision FROM gloss_search_recipes r WHERE dirty=1'+recipe_scope+' LIMIT 200').fetchall():
        ids = [r['id'] for r in batch]
        meanings = {r['id']:dict(r) for r in db.execute('''SELECT m.id,m.gloss,m.revision FROM gloss_meanings m WHERE m.id IN
          (SELECT meaning_id FROM gloss_search_dependencies WHERE recipe_id IN ('''+','.join('?' for _ in ids)+'))',ids)}
        for row in long_tasks.steps(batch):
            output = render(json.loads(row['body']),meanings)
            saved = encode(output)
            if saved != row['output']:
                old = [r[0] for r in db.execute('SELECT value_id FROM gloss_search_keys WHERE recipe_id=?',(row['id'],))]
                db.execute('DELETE FROM gloss_search_keys WHERE recipe_id=?',(row['id'],))
                fields = {'all_form':[corpus.plain(output['form'])], 'all_gloss':[corpus.plain(output['gloss'])]}
                if not corpus.boundary_count(output['form']):
                    fields['gloss'] = corpus.split_gloss_morphemes(corpus.clean(output['gloss']))[0]+re.findall(r'#(?:sub|sup|super)\[([^]]*)\]',output['gloss'])
                db.executemany('INSERT OR IGNORE INTO gloss_search_keys VALUES(?,?,?)',
                               [(row['id'],field,values.intern(text)) for field,texts in fields.items() for text in set(texts) if text])
                # Content versions stay safe if an unused INTEGER row ID is
                # later reused, and permit reuse after an undo round trip.
                revision='word:'+hashlib.sha256(saved.encode('utf-8')).hexdigest()
                db.execute('UPDATE gloss_search_recipes SET output=?,revision=? WHERE id=?',(saved,revision,row['id']))
                values.release(old)
            db.execute('UPDATE gloss_search_recipes SET dirty=0 WHERE id=?',(row['id'],))
            completed += 1
            long_tasks.checkpoint(None,'正在更新有效标注检索索引…')


def hits(db, query, case=False, mode='contains', all_fields=False):
    values, args = Values(db).query(query,case,mode)
    fields = "('all_form','all_gloss')" if all_fields else "('gloss')"
    return '''SELECT kind,owner_id id,word FROM gloss_search_words WHERE recipe_id IN (
      SELECT recipe_id FROM gloss_search_keys WHERE field IN '''+fields+' AND value_id IN ('+values+'))', args
