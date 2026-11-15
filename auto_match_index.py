"""Rebuildable SQLite match keys and occurrences for automatic dictionary links."""
from collections import defaultdict
from functools import lru_cache
from itertools import groupby
import json
import sqlite3
import struct
import unicodedata
from hashlib import sha256

import auto_match_sources as sources
import corpus
import independent_annotations
import long_tasks
import record_sources


VERSION = 2
BATCH = 400
TABLES = ('auto_match_occurrences', 'auto_match_owners', 'auto_match_keys', 'auto_match_targets', 'auto_match_multipart',
          'auto_match_dirty', 'auto_match_scopes', 'auto_match_tag_keys', 'auto_match_state')
TARGET_FIELDS = ('lexeme_id','target_kind','headword','homonym_number','usage_id','pos','sense_id',
                 'form_id','match_reason','matched_form','short_gloss','sense_label','definition')


def drop(db):
    for name, in db.execute("SELECT name FROM sqlite_master WHERE type='trigger' AND name GLOB 'auto_match_*'").fetchall():
        db.execute('DROP TRIGGER "'+name.replace('"','""')+'"')
    for table in TABLES:
        db.execute('DROP TABLE IF EXISTS '+table)


def initialize(db):
    drop(db)
    record_sources.schema_sql(db, '''
      CREATE TABLE auto_match_state(version INTEGER NOT NULL);
      CREATE TABLE auto_match_tag_keys(lid TEXT PRIMARY KEY,hash TEXT NOT NULL) WITHOUT ROWID;
      CREATE TABLE auto_match_scopes(kind TEXT,lid TEXT,PRIMARY KEY(kind,lid)) WITHOUT ROWID;
      CREATE TABLE auto_match_dirty(kind TEXT,id TEXT,PRIMARY KEY(kind,id)) WITHOUT ROWID;
      CREATE TABLE auto_match_keys(id INTEGER PRIMARY KEY,lid TEXT,form_key TEXT,edge_key TEXT,all_key TEXT,
        gloss_key BLOB,match_form TEXT,match_gloss TEXT,form TEXT,gloss TEXT,display_form TEXT,alias TEXT,
        UNIQUE(lid,match_form,match_gloss,form,gloss,display_form,alias));
      CREATE INDEX auto_match_key_exact ON auto_match_keys(lid,form_key,gloss_key);
      CREATE INDEX auto_match_key_edges ON auto_match_keys(lid,edge_key,gloss_key);
      CREATE INDEX auto_match_key_all ON auto_match_keys(lid,all_key,gloss_key);
      CREATE TABLE auto_match_owners(id INTEGER PRIMARY KEY,kind INTEGER,owner_id TEXT,UNIQUE(kind,owner_id));
      CREATE TABLE auto_match_occurrences(kind INTEGER,owner INTEGER,position INTEGER,ordinal INTEGER,unit TEXT,shadow TEXT,key_id INTEGER,
        PRIMARY KEY(kind,owner,position,ordinal)) WITHOUT ROWID;
      CREATE INDEX auto_match_occurrences_key ON auto_match_occurrences(key_id,kind,owner);
      CREATE TABLE auto_match_multipart(kind TEXT,id TEXT,PRIMARY KEY(kind,id)) WITHOUT ROWID;
      CREATE TABLE auto_match_targets(lexeme_id TEXT,target_kind TEXT,ordinal INTEGER,lid TEXT,
        form_key TEXT,edge_key TEXT,all_key TEXT,gloss_key BLOB,headword TEXT,homonym_number INTEGER,
        usage_id TEXT,pos TEXT,sense_id TEXT,form_id TEXT,match_reason TEXT,matched_form TEXT,
        short_gloss TEXT,sense_label TEXT,definition TEXT,
        PRIMARY KEY(lexeme_id,target_kind,ordinal)) WITHOUT ROWID;
    ''')
    db.execute('INSERT INTO auto_match_state(version) VALUES(?)',(VERSION,))
    dependencies={
        'entries': ("'corpus'",'id',('id','text_id','rowid')),
        'dictionary_examples': ("'independent'",'id',('id','language_id','rowid')),
        'sentence_text_rows': ('{ref}.kind','owner_id',('kind','owner_id','language_id')),
        'sentence_word_rows': ('{ref}.kind','owner_id',('kind','owner_id','position','form','gloss','extra')),
        'corpus_units': ("'corpus'",'entry_id',('id','entry_id','kind','parent_id','position','form','gloss','active')),
        'independent_word_overrides': ("'independent'",'example_id',('example_id','position',
            'snapshot' if independent_annotations.enabled(db) else 'word')),
        'lexemes': ("'lexeme'",'id',('id','language_id','headword','homonym_number')),
        'morphemes': ("'morpheme'",'id',('id','language_id','form','number')),
        'dictionary_value_rows': ('{ref}.target_kind','target_id',('target_kind','target_id','node','parent','slot','value_type','value')),
    }
    for table,(kind,owner,fields) in dependencies.items():
        for event,ref in (('INSERT','NEW'),('DELETE','OLD'),('UPDATE','NEW')):
            sql=queue(kind.format(ref=ref),f'{ref}.{owner}')
            when=''
            if event=='UPDATE':
                when=' WHEN '+' OR '.join(f'OLD.{field} IS NOT NEW.{field}' for field in fields)
                old_kind=kind.format(ref='OLD')
                sql+=queue(old_kind,f'OLD.{owner}',f' AND ({old_kind} IS NOT {kind.format(ref="NEW")} OR OLD.{owner} IS NOT NEW.{owner})')
            if table in ('lexemes','morphemes'):
                # An edit can change the inferred number of other members of a homonym group.
                form=fields[2]
                refs=('OLD','NEW') if event=='UPDATE' else (ref,)
                sql+=''.join(f'''INSERT INTO auto_match_dirty SELECT {kind},x.id FROM {table} x
                    WHERE x.language_id={r}.language_id AND x.{form}={r}.{form}
                    AND NOT EXISTS(SELECT 1 FROM auto_match_dirty d WHERE d.kind={kind} AND d.id=x.id);''' for r in refs)
                if table=='lexemes':
                    sql+=''.join(queue("'morpheme'",f'{r}.id',f' AND EXISTS(SELECT 1 FROM morphemes WHERE id={r}.id)') for r in refs)
            db.execute(f'CREATE TRIGGER auto_match_{table}_{event} AFTER {event} ON {table}{when} BEGIN {sql} END')
    for event,ref in (('INSERT','NEW'),('DELETE','OLD'),('UPDATE OF id,language_id','NEW')):
        changed=' WHEN OLD.id IS NOT NEW.id OR OLD.language_id IS NOT NEW.language_id' if event.startswith('UPDATE') else ''
        refs='(OLD.id,NEW.id)' if changed else f'({ref}.id)'
        db.execute(f'''CREATE TRIGGER auto_match_text_{event.split()[0]} AFTER {event} ON texts{changed} BEGIN
          INSERT INTO auto_match_dirty SELECT 'corpus',e.id FROM entries e WHERE e.text_id IN {refs}
            AND NOT EXISTS(SELECT 1 FROM auto_match_dirty d WHERE d.kind='corpus' AND d.id=e.id);
          END''')


def queue(kind,owner,where=''):
    # An outer UPSERT may override OR IGNORE in a trigger.
    return (f'INSERT INTO auto_match_dirty SELECT {kind},{owner} WHERE NOT EXISTS('
            f'SELECT 1 FROM auto_match_dirty WHERE kind={kind} AND id={owner}){where};')


def gloss_bytes(key):
    category,base,features=key
    # Length prefixes preserve ordered and repeated feature atoms, including unusual IDs.
    parts=(category,base,*features)
    return b''.join(struct.pack('>I',len(item))+item for item in (s.encode('utf-8') for s in parts))


MARKERS=str.maketrans('','','-=.')


@lru_cache(maxsize=4096)
def form_keys(form):
    key=unicodedata.normalize('NFC',corpus.plain(form))
    return key,key.strip('-=.'),key.translate(MARKERS)


def exists(db):
    return db.execute("SELECT 1 FROM sqlite_master WHERE name='auto_match_state'").fetchone() is not None


def available(db):
    return exists(db) and db.execute('SELECT 1 FROM auto_match_state WHERE version=?',(VERSION,)).fetchone() is not None


def pending(db,kind,lid):
    if kind=='corpus':
        source='entries s WHERE s.text_id=?'
    elif kind=='independent':
        source='dictionary_examples s WHERE s.language_id=?'
    else:
        source={'lexeme':'lexemes','morpheme':'morphemes'}[kind]+' s WHERE s.language_id=?'
    if db.execute('SELECT 1 FROM auto_match_scopes WHERE kind=? AND lid=?',(kind,lid)).fetchone():return
    db.execute(f'INSERT OR IGNORE INTO auto_match_dirty SELECT ?,s.id FROM {source}',(kind,lid))
    db.execute('INSERT INTO auto_match_scopes VALUES(?,?)',(kind,lid))


def dirty_targets(db,kind):
    while ids:=[r[0] for r in db.execute('SELECT id FROM auto_match_dirty WHERE kind=? ORDER BY id LIMIT ?',(kind,BATCH))]:
        yield ids,','.join('?' for _ in ids)
        db.execute('DELETE FROM auto_match_dirty WHERE kind=? AND id IN ('+','.join('?' for _ in ids)+')',(kind,*ids))


def refresh_targets(db,lookups,tag_names):
    from dictionary_rows import SOURCES, _morpheme_body, targets
    from homonyms import decorate_many
    from lexicon import auto_definitions

    columns=','.join(('ordinal','lid','form_key','edge_key','all_key','gloss_key',*TARGET_FIELDS))
    insert=f'INSERT INTO auto_match_targets({columns}) VALUES('+','.join('?' for _ in range(6+len(TARGET_FIELDS)))+')'
    for kind,(table,form) in SOURCES.items():
        number=('homonym_number' if kind=='lexeme' else
                'CASE WHEN EXISTS(SELECT 1 FROM morphemes p WHERE p.language_id=d.language_id AND p.form=d.form AND p.id<>d.id) THEN d.number END')
        for ids,marks in long_tasks.steps(dirty_targets(db,kind)):
            db.execute(f'DELETE FROM auto_match_targets WHERE target_kind=? AND lexeme_id IN ({marks})',(kind,*ids))
            db.execute(f'DELETE FROM auto_match_multipart WHERE kind=? AND id IN ({marks})',(kind,*ids))
            skip=" AND NOT EXISTS(SELECT 1 FROM lexemes x WHERE x.id=d.id)" if kind=='morpheme' else ''
            records=db.execute(f'''SELECT d.id,d.language_id,d.revision,d.{form} headword,? target_kind,
                {number} homonym_number FROM {table} d WHERE d.id IN ({marks}){skip}''',(kind,*ids)).fetchall()
            bodies=sources.matching_bodies(db,records)
            if len(bodies)!=len(records):
                fallback=targets(db,[r['id'] for r in records],prepare=False)
                items=[fallback[r['id']] for r in records if r['id'] in fallback]
            else:
                items=[]
                for row in records:
                    body=bodies[row['id']]
                    body['homonym_number']=row['homonym_number']
                    if kind=='morpheme':_morpheme_body(row,body,{})
                    items.append(dict(row,body=body))
            if kind=='lexeme':decorate_many(db,items)
            multipart=set()
            def values():
                for row in items:
                    lid=row['language_id']
                    for ordinal,(key,parts,candidate) in enumerate(auto_definitions(row,lookups.get(lid,{}),tag_names)):
                        if parts:multipart.add(row['id'])
                        yield (ordinal,lid,*form_keys(candidate['matched_form']),gloss_bytes(key),
                               *(candidate[name] for name in TARGET_FIELDS))
            db.executemany(insert,values())
            db.executemany('INSERT INTO auto_match_multipart VALUES(?,?)',((kind,rid) for rid in multipart))


def independent_words(db,ids,*,slots=False):
    form,gloss,inputs=sources.independent_inputs(db)
    if slots:
        scope='WITH selected(id,position) AS (VALUES '+','.join('(?,?)' for _ in ids)+')'
        owners='selected p CROSS JOIN dictionary_examples e ON e.id=p.id'
        condition=' AND w.position=p.position'
        args=[value for slot in ids for value in slot]
    else:
        scope=''
        owners='dictionary_examples e'
        condition=' WHERE e.id IN ('+','.join('?' for _ in ids)+')'
        args=ids
    return db.execute(f'''{scope} SELECT e.id,w.position,{form} form,{gloss} gloss,{inputs} inputs,
        COALESCE(NULLIF(s.language_id,''),e.language_id) effective_language_id
      FROM {owners} CROSS JOIN sentence_text_rows s ON s.kind='independent' AND s.owner_id=e.id
      CROSS JOIN sentence_word_rows w ON w.kind='independent' AND w.owner_id=e.id {condition if slots else ''}
      LEFT JOIN independent_word_overrides o ON o.example_id=e.id AND o.position=w.position {condition if not slots else ''}''',args)


def refresh_sources(db,lookups,word):
    from lexicon import auto_gloss_key

    @lru_cache(maxsize=16384)
    def recipe(lid,form,gloss,raw_form,raw_gloss,display,aliases):
        if not form.strip() or corpus.boundary_count(form):return None
        fields=(lid,form,gloss,raw_form,raw_gloss,display,aliases)
        row=db.execute('SELECT id FROM auto_match_keys WHERE (lid,match_form,match_gloss,form,gloss,display_form,alias)=(?,?,?,?,?,?,?)',fields).fetchone()
        if row:return row[0]
        return db.execute('''INSERT INTO auto_match_keys(lid,match_form,match_gloss,form,gloss,display_form,alias,
                          form_key,edge_key,all_key,gloss_key) VALUES(?,?,?,?,?,?,?,?,?,?,?)''',
                          (*fields,*form_keys(form),gloss_bytes(auto_gloss_key(gloss,lookups.get(lid,{}))))).lastrowid

    for kind,table,number in (('corpus','entries',0),('independent','dictionary_examples',1)):
        for ids,marks in long_tasks.steps(dirty_targets(db,kind)):
            scope=f'SELECT id FROM auto_match_owners WHERE kind=? AND owner_id IN ({marks})'
            db.execute('CREATE TEMP TABLE IF NOT EXISTS auto_match_retired(id INTEGER PRIMARY KEY)')
            db.execute(f'''INSERT OR IGNORE INTO temp.auto_match_retired SELECT key_id FROM auto_match_occurrences
              WHERE kind=? AND owner IN ({scope})''',(number,number,*ids))
            db.execute(f'DELETE FROM auto_match_occurrences WHERE kind=? AND owner IN ({scope})',(number,number,*ids))
            db.execute(f'''DELETE FROM auto_match_owners WHERE kind=? AND owner_id IN ({marks})
                          AND NOT EXISTS(SELECT 1 FROM {table} e WHERE e.id=owner_id)''',(number,*ids))
            db.execute(f'INSERT OR IGNORE INTO auto_match_owners(kind,owner_id) SELECT ?,id FROM {table} WHERE id IN ({marks})',(number,*ids))
            owners={r['owner_id']:r['id'] for r in db.execute(
                f'SELECT id,owner_id FROM auto_match_owners WHERE kind=? AND owner_id IN ({marks})',(number,*ids))}
            if kind=='corpus':
                def slots():
                    for entry,_,units,semantic in sources.corpus_batches(db,None,None,word,False,owners=ids):
                        lid=entry['effective_language_id']
                        for order,(unit,duplicate,labels) in enumerate(sources.corpus_slots(units,semantic)):
                            form,gloss,display=labels
                            key=recipe(lid,form,gloss,unit['form'],unit['gloss'],display,'')
                            if key is not None:yield (0,owners[entry['id']],order,0,unit['id'],duplicate['id'] if duplicate else None,key)
            else:
                def slots():
                    for row in independent_words(db,ids):
                        source=word(row['form'],row['gloss'],row['inputs'])
                        lid=row['effective_language_id']
                        for ordinal,(unit,aliases) in enumerate(sources.independent_slots(source)):
                            form,gloss=unit['form'],unit['gloss']
                            key=recipe(lid,unit.get('lookup_form',form),unit.get('display_gloss',gloss),
                                       form,gloss,unit.get('display_form',form),'\x1f'.join(aliases))
                            if key is not None:yield (1,owners[row['id']],row['position'],ordinal,unit['key'],None,key)
            db.executemany('INSERT INTO auto_match_occurrences VALUES(?,?,?,?,?,?,?)',slots())


def prepare(db,lid,text_id,tags,lookups,tag_names,word):
    import read_views
    import save_validation

    read_views.upgrade(db)
    old=db.execute('SELECT version FROM auto_match_state').fetchone() if exists(db) else None
    # A tag spelling change affects only keys using that language's grammar.
    by_language=defaultdict(list)
    for row in tags:by_language[row['language_id']].append((row['id'],row['symbol'],row['aliases']))
    hashes={lang:sha256(json.dumps(values,ensure_ascii=False,separators=(',',':')).encode()).hexdigest()
            for lang,values in by_language.items()}
    if not old or old['version']!=VERSION:
        prior=save_validation.snapshot(db)
        initialize(db)
        save_validation.initialize(db,prior)
    previous=dict(db.execute('SELECT lid,hash FROM auto_match_tag_keys'))
    from lexicon import auto_gloss_key
    for lang in previous.keys()|hashes.keys():
        if previous.get(lang)==hashes.get(lang):continue
        db.execute("DELETE FROM auto_match_scopes WHERE kind IN ('lexeme','morpheme') AND lid=?",(lang,))
        # Tag edits reinterpret the distinct glosses, not the occurrence rows.
        lookup=lookups.get(lang,{})
        db.create_function('auto_match_gloss_key',1,lambda gloss,lookup=lookup:gloss_bytes(auto_gloss_key(gloss,lookup)),deterministic=True)
        db.execute('UPDATE auto_match_keys SET gloss_key=auto_match_gloss_key(match_gloss) WHERE lid=?',(lang,))
        if lang in hashes:
            db.execute('INSERT OR REPLACE INTO auto_match_tag_keys VALUES(?,?)',(lang,hashes[lang]))
        else:db.execute('DELETE FROM auto_match_tag_keys WHERE lid=?',(lang,))
    for lang, in db.execute('SELECT id FROM languages'):
        pending(db,'lexeme',lang)
        pending(db,'morpheme',lang)
    long_tasks.checkpoint(None,'正在更新自动关联索引…')
    refresh_targets(db,lookups,tag_names)
    # Multipart proposals need ordered spans and live inheritance across a word.
    if db.execute('SELECT 1 FROM auto_match_multipart LIMIT 1').fetchone():return False
    if text_id!='@independent':
        texts=(text_id,) if text_id else (r[0] for r in db.execute('SELECT id FROM texts WHERE language_id=?',(lid,)))
        for tid in texts:pending(db,'corpus',tid)
    if text_id in ('','@independent'):pending(db,'independent',lid)
    refresh_sources(db,lookups,word)
    # Keep only recipes with live postings, after rebuilding all dirty owners.
    if db.execute("SELECT 1 FROM temp.sqlite_master WHERE name='auto_match_retired'").fetchone():
        db.execute('''DELETE FROM auto_match_keys WHERE id IN (SELECT id FROM temp.auto_match_retired)
            AND NOT EXISTS(SELECT 1 FROM auto_match_occurrences o INDEXED BY auto_match_occurrences_key
                           WHERE o.key_id=auto_match_keys.id)''')
        db.execute('DELETE FROM temp.auto_match_retired')
    return True


def choices(db,symbols,position):
    from lexicon import auto_match_choices

    target=','.join('d.'+c for c in TARGET_FIELDS)
    if symbols in ('','-=.'):
        column='form_key' if not symbols else 'edge_key' if position=='edges' else 'all_key'
        join=f'k.lid=d.lid AND k.{column}=d.{column} AND k.gloss_key=d.gloss_key'
        guard=f"WHERE d.{column}<>'' OR k.form_key=d.form_key" if symbols else ''
        matches=f'SELECT k.id,k.form_key=d.form_key exact,d.ordinal,{target} FROM auto_match_targets d CROSS JOIN auto_match_keys k ON {join} {guard}'
    else:
        # Uncommon marker sets only normalize distinct keys. Exact matches with
        # an empty relaxed key remain eligible, as in the ordinary matcher.
        table=str.maketrans('','',symbols)
        normal=lambda s:s.strip(symbols) if position=='edges' else s.translate(table)
        db.create_function('auto_match_normal',1,normal,deterministic=True)
        matches=f'''WITH source AS MATERIALIZED (SELECT id,lid,gloss_key,form_key,auto_match_normal(form_key) relaxed FROM auto_match_keys)
            SELECT k.id,k.form_key=d.form_key exact,d.ordinal,{target} FROM auto_match_targets d
            CROSS JOIN source k ON k.lid=d.lid AND k.gloss_key=d.gloss_key AND k.relaxed=auto_match_normal(d.form_key)
            WHERE k.relaxed<>'' OR k.form_key=d.form_key'''
    query=f'''SELECT m.*,COALESCE(x.revision,p.revision) lexeme_revision FROM ({matches}) m
        LEFT JOIN lexemes x ON m.target_kind='lexeme' AND x.id=m.lexeme_id
        LEFT JOIN morphemes p ON m.target_kind='morpheme' AND p.id=m.lexeme_id
        ORDER BY m.id,m.lexeme_id,m.ordinal'''
    result={}
    for key,rows in groupby(db.execute(query),lambda row:row['id']):
        exact=[];relaxed=[]
        for row in rows:
            item={name:row[name] for name in TARGET_FIELDS};item['lexeme_revision']=row['lexeme_revision']
            (exact if row['exact'] else relaxed).append(item)
        result[key]=auto_match_choices(exact,relaxed)
    return result


def corpus_hits(db,lid,text_id,*,linked=False):
    present='''(EXISTS(SELECT 1 FROM lexical_links l WHERE l.unit_id=o.unit) OR
                 EXISTS(SELECT 1 FROM lexical_links l WHERE l.unit_id=o.shadow))'''
    condition=present if linked else 'NOT '+present
    if text_id:
        # A single text can address its own postings by owner, including when
        # a high-frequency match occurs in most of the other texts.
        query=''
        sources='''FROM texts t CROSS JOIN entries e ON e.text_id=t.id
          CROSS JOIN auto_match_owners a ON a.kind=0 AND a.owner_id=e.id
          CROSS JOIN auto_match_occurrences o ON o.kind=0 AND o.owner=a.id
          CROSS JOIN temp.auto_match_hits h ON h.id=o.key_id'''
        where=f'WHERE t.language_id=? AND t.id=? AND {condition}'
    else:
        query=f'''WITH hits AS MATERIALIZED (
          SELECT o.unit,o.owner,o.position,o.key_id FROM temp.auto_match_hits h
          CROSS JOIN auto_match_occurrences o INDEXED BY auto_match_occurrences_key ON o.key_id=h.id AND o.kind=0
          WHERE {condition}
        ) '''
        sources='''FROM hits o JOIN auto_match_owners a ON a.id=o.owner
          JOIN entries e ON e.id=a.owner_id JOIN texts t ON t.id=e.text_id'''
        where='WHERE t.language_id=?'
    if linked:
        query+=f'SELECT count(*) {sources} {where}'
    else:
        query+=f'''SELECT o.unit id,u.entry_id,u.kind,u.revision,k.form,k.gloss,k.match_form,k.match_gloss,k.display_form,
          k.lid effective_language_id,e.revision entry_revision,e.position sentence_position,t.title,k.id key_id
          {sources} JOIN corpus_units u ON u.id=o.unit JOIN auto_match_keys k ON k.id=o.key_id
          {where} ORDER BY t.id,e.position,o.position'''
    return db.execute(query,(lid,text_id) if text_id else (lid,))


def independent_hits(db,lid):
    # Sentence numbering includes unmatched examples. Materialize the narrow
    # metadata once, so the postings join is an indexed lookup in either order.
    db.execute('CREATE TEMP TABLE IF NOT EXISTS auto_match_example_order(id TEXT PRIMARY KEY,revision INTEGER,position INTEGER) WITHOUT ROWID')
    db.execute('DELETE FROM temp.auto_match_example_order')
    db.execute('''INSERT INTO temp.auto_match_example_order SELECT id,revision,row_number() OVER(ORDER BY rowid)
                  FROM dictionary_examples WHERE language_id=?''',(lid,))
    detached=independent_annotations.detached_sql(db,'l')
    return db.execute(f'''SELECT e.id,e.revision,e.position sentence_position,o.position,o.unit,o.key_id,k.form,k.gloss,k.lid,
       k.display_form,k.match_form,k.match_gloss,
       EXISTS(SELECT 1 FROM independent_links l WHERE l.example_id=e.id AND l.word_position=o.position
         AND (l.unit_key=o.unit OR k.alias<>'' AND instr(char(31)||k.alias||char(31),char(31)||l.unit_key||char(31)))
         AND NOT COALESCE({detached},0)) link_id
    FROM temp.auto_match_hits h
    CROSS JOIN auto_match_occurrences o INDEXED BY auto_match_occurrences_key ON o.key_id=h.id AND o.kind=1
    CROSS JOIN auto_match_owners a ON a.id=o.owner
    CROSS JOIN temp.auto_match_example_order e ON e.id=a.owner_id
    CROSS JOIN auto_match_keys k ON k.id=o.key_id
    ORDER BY e.position,o.position,o.ordinal''')


def read_hits(db,lid,text_id,options,word):
    chosen=choices(db,*options[1:])
    if not chosen:return
    db.execute('CREATE TEMP TABLE IF NOT EXISTS auto_match_hits(id INTEGER PRIMARY KEY)')
    db.execute('DELETE FROM temp.auto_match_hits')
    db.executemany('INSERT INTO temp.auto_match_hits VALUES(?)',((key,) for key in chosen))
    if text_id!='@independent':
        count=corpus_hits(db,lid,text_id,linked=True).fetchone()[0]
        if count:yield count
        for row in long_tasks.steps(corpus_hits(db,lid,text_id)):
            yield dict(row,choices=chosen[row['key_id']])
    if text_id in ('','@independent'):
        import segmentation
        # Whole-word references are available from the indexed labels. Read the
        # original cell only for a matched morpheme's fragment offsets.
        hits=independent_hits(db,lid)
        while batch:=hits.fetchmany(BATCH):
            wanted=defaultdict(set)
            for r in batch:
                if not r['link_id'] and r['unit']!='@word':wanted[r['id'],r['position']].add(r['unit'])
            slots={}
            if wanted:
                # Compare the exact owner and word position, not every slot in the sentence.
                for row in independent_words(db,wanted,slots=True):
                    slot=row['id'],row['position']
                    if slot in wanted:
                        w=word(row['form'],row['gloss'],row['inputs'])
                        slots[slot]={u['key']:segmentation.reference(w,slot[1],u) for u,_ in sources.independent_slots(w)
                                     if u['key'] in wanted[slot]}
            for row in long_tasks.steps(batch):
                if row['link_id']:
                    yield 1
                    continue
                rid,wi,key,revision=row['id'],row['position'],row['unit'],row['revision']
                form,gloss=row['form'],row['gloss']
                ref=(dict(word=wi,key=key,form=form,gloss=gloss,unit_form=form,unit_gloss=gloss,fragments=[])
                     if key=='@word' else slots[rid,wi][key])
                yield dict(id=f'independent:{rid}:{wi}:{key}',entry_id=rid,entry_revision=revision,revision=revision,
                    kind='word' if key=='@word' else 'morpheme',position=wi,form=form,gloss=gloss,
                    display_form=row['display_form'],match_form=row['match_form'],
                    match_gloss=row['match_gloss'],choices=chosen[row['key_id']],
                    sentence_position=row['sentence_position'],title='独立例句库',owner_kind='independent',
                    effective_language_id=row['lid'],segmentation_ref=ref)


def rows(db,lid,options,tags,lookups,tag_names,word):
    text_id=options[0]
    if text_id:
        kind,owner=('independent',lid) if text_id=='@independent' else ('corpus',text_id)
        # Keep first-use scoped requests bounded on an unprepared project.
        if not available(db) or not db.execute('SELECT 1 FROM auto_match_scopes WHERE kind=? AND lid=?',(kind,owner)).fetchone():
            return None
    db.execute('SAVEPOINT auto_match_projection')
    try:
        ready=prepare(db,lid,text_id,tags,lookups,tag_names,word)
    except BaseException as error:
        # Do not mask cancellation if SQLite already rolled back an interrupted
        # write. Both preview entry points own the surrounding transaction.
        if db.in_transaction:
            if long_tasks.CURRENT.get() is not None:db.set_progress_handler(None,0)
            db.execute('ROLLBACK TO auto_match_projection')
            db.execute('RELEASE auto_match_projection')
        if isinstance(error,sqlite3.OperationalError) and str(error) in ('attempt to write a readonly database','database is locked'):
            job=long_tasks.CURRENT.get()
            if job:db.set_progress_handler(lambda:int(job['cancel'].is_set()),5000)
            return None
        raise
    db.execute('RELEASE auto_match_projection')
    return read_hits(db,lid,text_id,options,word) if ready else None
