"""Disposable welcome-sample identities, updated with their source transaction.

One dense slot represents each exact (language, primary text, translation).
Slots make a uniform sample independent of source count. The representative is
always the first corpus/text-position source, then the first independent ID.
"""
from collections.abc import Sequence
import hashlib
import random

import long_tasks
import record_sources
import material_search_index

VERSION = 'home-candidates-v3'
TABLES = ('home_candidate_slots', 'home_candidate_sources', 'home_candidate_values',
          'home_candidate_dirty', 'home_candidate_state')


def drop(db):
    for name, in db.execute("SELECT name FROM sqlite_master WHERE type='trigger' AND name GLOB 'home_candidate_*'").fetchall():
        db.execute('DROP TRIGGER "'+name.replace('"','""')+'"')
    for table in TABLES:
        db.execute('DROP TABLE IF EXISTS '+table)


def initialize(db):
    existed = db.execute("SELECT 1 FROM sqlite_master WHERE name='home_candidate_state'").fetchone()
    if existed:
        prior=db.execute('SELECT version FROM home_candidate_state WHERE id=1').fetchone()
        if not prior or prior[0] != VERSION:drop(db)
    statements = (
        '''CREATE TABLE IF NOT EXISTS home_candidate_state(
          id INTEGER PRIMARY KEY CHECK(id=1),version TEXT,n INTEGER,rebuild INTEGER)''',
        '''CREATE TABLE IF NOT EXISTS home_candidate_values(
          value_id INTEGER PRIMARY KEY,language_id TEXT,primary_text TEXT,translation TEXT,
          UNIQUE(language_id,primary_text,translation))''',
        '''CREATE TABLE IF NOT EXISTS home_candidate_sources(
          kind TEXT,id TEXT,value_id INTEGER,sort_text TEXT,position INTEGER,source_rowid INTEGER,
          PRIMARY KEY(kind,id)) WITHOUT ROWID''',
        '''CREATE INDEX IF NOT EXISTS home_candidate_representative ON
          home_candidate_sources(value_id,kind,sort_text,position,source_rowid,id)''',
        '''CREATE TABLE IF NOT EXISTS home_candidate_slots(
          slot INTEGER PRIMARY KEY,value_id INTEGER UNIQUE,kind TEXT,id TEXT,language_id TEXT)''',
        '''CREATE TABLE IF NOT EXISTS home_candidate_dirty(
          kind TEXT,id TEXT,PRIMARY KEY(kind,id)) WITHOUT ROWID''',
    )
    for sql in statements:
        db.execute(sql)
    db.execute('INSERT OR IGNORE INTO home_candidate_state VALUES(1,?,0,1)', (VERSION,))
    for table, kind in (('entries','corpus'), ('dictionary_examples','independent')):
        for event in ('INSERT','UPDATE','DELETE'):
            refs = ('OLD','NEW') if event == 'UPDATE' else ('OLD',) if event == 'DELETE' else ('NEW',)
            when = ''
            if event == 'UPDATE':
                fields = ('id','text_id','position') if kind == 'corpus' else ('id','language_id')
                changed = ['OLD.'+f+' IS NOT NEW.'+f for f in ('rowid', *fields)]
                checks = [f"json_extract(OLD.body,'$.{f}') IS NOT json_extract(NEW.body,'$.{f}')"
                          for f in ('language_id','ipa','translation','words', *(() if kind == 'corpus' else ('original',)))]
                changed.append(record_sources.change_sql(db,table,record_sources.HOME,' OR '.join(checks)))
                when = ' WHEN '+' OR '.join(changed)
            body = ''.join(f"INSERT INTO home_candidate_dirty SELECT '{kind}',{ref}.id WHERE NOT EXISTS(SELECT 1 FROM home_candidate_dirty WHERE kind='{kind}' AND id={ref}.id);" for ref in refs)
            name=f'home_candidate_{table}_{event}'
            sql=f'CREATE TRIGGER {name} AFTER {event} ON {table}{when} BEGIN {body} END'
            previous=db.execute("SELECT sql FROM sqlite_master WHERE type='trigger' AND name=?",(name,)).fetchone()
            if previous and previous[0]==sql:continue
            if previous:db.execute('DROP TRIGGER '+name)
            db.execute(sql)
    for event in ('INSERT','UPDATE','DELETE'):
        refs = ('OLD','NEW') if event == 'UPDATE' else ('OLD',) if event == 'DELETE' else ('NEW',)
        when = ' WHEN OLD.id IS NOT NEW.id OR OLD.language_id IS NOT NEW.language_id' if event == 'UPDATE' else ''
        body = ''.join(f"INSERT INTO home_candidate_dirty SELECT 'corpus',e.id FROM entries e WHERE e.text_id={ref}.id AND NOT EXISTS(SELECT 1 FROM home_candidate_dirty d WHERE d.kind='corpus' AND d.id=e.id);" for ref in refs)
        db.execute(f'CREATE TRIGGER IF NOT EXISTS home_candidate_texts_{event} AFTER {event} ON texts{when} BEGIN {body} END')
        when = ' WHEN OLD.id IS NOT NEW.id' if event == 'UPDATE' else ''
        body = ''.join(f"INSERT INTO home_candidate_dirty SELECT 'language',{ref}.id WHERE NOT EXISTS(SELECT 1 FROM home_candidate_dirty WHERE kind='language' AND id={ref}.id);" for ref in refs)
        db.execute(f'''CREATE TRIGGER IF NOT EXISTS home_candidate_languages_{event} AFTER {event} ON languages{when}
          BEGIN {body} END''')


def rows(db, kind, ids=None):
    native = record_sources.native(db)
    if native:
        forms = (f"(SELECT COALESCE(group_concat(COALESCE(form,''),' '),'') FROM (SELECT w.form "
                 f"FROM sentence_word_rows w WHERE w.kind='{kind}' AND w.owner_id=e.id ORDER BY w.position))")
        header = f" JOIN sentence_text_rows s ON s.kind='{kind}' AND s.owner_id=e.id"
    else:
        forms = "(SELECT COALESCE(group_concat(COALESCE(json_extract(w.value,'$.form'),''),' '),'') FROM json_each(e.body,'$.words') w)"
        header = ''
    language, ipa, original, translation = (('s.'+key if native else f"json_extract(e.body,'$.{key}')")
                                            for key in ('language_id','ipa','original','translation'))
    if kind == 'corpus':
        sql = f"SELECT e.id,COALESCE(NULLIF({language},''),t.language_id),COALESCE(NULLIF({ipa},''),{forms}),COALESCE({translation},''),t.id,e.position,e.rowid FROM entries e JOIN texts t ON t.id=e.text_id{header}"
        order = ' ORDER BY t.id,e.position'
    else:
        sql = f"SELECT e.id,e.language_id,COALESCE(NULLIF({ipa},''),NULLIF({original},''),{forms}),COALESCE({translation},''),e.id,0,e.rowid FROM dictionary_examples e{header}"
        order = ' ORDER BY e.id'
    return db.execute(sql+' WHERE e.id IN ('+','.join('?' for _ in ids)+')' if ids is not None else sql+order, ids or ())


def _record(db, kind, row, languages):
    rid, lid, primary, translation, sort_text, position, source_rowid = row
    if lid not in languages or not (primary.strip() or translation.strip()):
        return None
    db.execute('INSERT OR IGNORE INTO home_candidate_values(language_id,primary_text,translation) VALUES(?,?,?)', (lid,primary,translation))
    value = db.execute('SELECT value_id FROM home_candidate_values WHERE language_id=? AND primary_text=? AND translation=?', (lid,primary,translation)).fetchone()[0]
    db.execute('INSERT INTO home_candidate_sources VALUES(?,?,?,?,?,?)', (kind,rid,value,sort_text,position,source_rowid))
    return value


def _reconcile(db, value, n):
    representative = db.execute('''SELECT s.kind,s.id,v.language_id FROM home_candidate_sources s
      JOIN home_candidate_values v USING(value_id) WHERE s.value_id=?
      ORDER BY s.kind,s.sort_text,s.position,s.source_rowid,s.id LIMIT 1''', (value,)).fetchone()
    slot = db.execute('SELECT slot FROM home_candidate_slots WHERE value_id=?', (value,)).fetchone()
    if representative:
        if slot:
            db.execute('UPDATE home_candidate_slots SET kind=?,id=?,language_id=? WHERE value_id=?', (*representative,value))
        else:
            db.execute('INSERT INTO home_candidate_slots VALUES(?,?,?,?,?)', (n,value,*representative))
            n += 1
    elif slot:
        # Swap the last identity into the removed slot; every identity retains
        # exactly one chance of selection without renumbering all later rows.
        db.execute('DELETE FROM home_candidate_slots WHERE slot=?', (slot[0],))
        if slot[0] != n-1:
            db.execute('UPDATE home_candidate_slots SET slot=? WHERE slot=?', (slot[0],n-1))
        n -= 1
    if not representative:
        db.execute('DELETE FROM home_candidate_values WHERE value_id=?', (value,))
    return n


def refresh(db):
    state = db.execute('SELECT n,rebuild FROM home_candidate_state WHERE id=1').fetchone()
    languages = {r[0] for r in db.execute('SELECT id FROM languages')}
    n = state[0]
    if state[1]:
        for table in TABLES[:-1]:
            db.execute('DELETE FROM '+table)
        n = _build(db,languages)
        db.execute('UPDATE home_candidate_state SET n=?,rebuild=0 WHERE id=1', (n,))
        return
    language_ids=[r[0] for r in db.execute("SELECT id FROM home_candidate_dirty WHERE kind='language'")]
    if language_ids:
        source = 'corpus_sentence_keys' if record_sources.native(db) else 'entries'
        language = 'e.language_id' if record_sources.native(db) else "json_extract(e.body,'$.language_id')"
        for start in range(0,len(language_ids),400):
            batch=language_ids[start:start+400];marks=','.join('?' for _ in batch)
            db.execute(f"INSERT OR IGNORE INTO home_candidate_dirty SELECT 'corpus',e.id FROM {source} e JOIN texts t ON t.id=e.text_id WHERE COALESCE(NULLIF({language},''),t.language_id) IN ({marks})",batch)
            db.execute("INSERT OR IGNORE INTO home_candidate_dirty SELECT 'independent',id FROM dictionary_examples WHERE language_id IN ("+marks+')',batch)
        db.execute("DELETE FROM home_candidate_dirty WHERE kind='language'")
    for kind in ('corpus','independent'):
        while batch := db.execute('SELECT id FROM home_candidate_dirty WHERE kind=? LIMIT 400', (kind,)).fetchall():
            ids = [r[0] for r in batch];marks = ','.join('?' for _ in ids)
            affected = {r[0] for r in db.execute('SELECT value_id FROM home_candidate_sources WHERE kind=? AND id IN ('+marks+')', [kind,*ids])}
            db.execute('DELETE FROM home_candidate_sources WHERE kind=? AND id IN ('+marks+')', [kind,*ids])
            for row in rows(db,kind,ids):
                value = _record(db,kind,row,languages)
                if value is not None:affected.add(value)
            for value in sorted(affected):n = _reconcile(db,value,n)
            db.execute('DELETE FROM home_candidate_dirty WHERE kind=? AND id IN ('+marks+')', [kind,*ids])
            db.execute('UPDATE home_candidate_state SET n=? WHERE id=1', (n,))
            long_tasks.checkpoint()


def _build(db,languages):
    # Retain only compact fingerprints and one bounded write batch. A repeated
    # fingerprint is checked against the full SQL identity, so collisions cannot
    # merge different examples. Batches avoid several SQL round trips per source.
    seen=set();values=[];sources=[];slots=[];n=0
    def flush():
        if values:db.executemany('INSERT INTO home_candidate_values VALUES(?,?,?,?)',values)
        if sources:db.executemany('INSERT INTO home_candidate_sources VALUES(?,?,?,?,?,?)',sources)
        if slots:db.executemany('INSERT INTO home_candidate_slots VALUES(?,?,?,?,?)',slots)
        values.clear();sources.clear();slots.clear();long_tasks.checkpoint()
    with material_search_index.writing_cache(db):
        for kind in ('corpus','independent'):
            for rid,lid,primary,translation,sort_text,position,source_rowid in rows(db,kind):
                if lid not in languages or not (primary.strip() or translation.strip()):continue
                fingerprint=hashlib.sha256((lid+'\0'+primary+'\0'+translation).encode('utf8')).digest()
                value=None
                if fingerprint in seen:
                    flush()
                    found=db.execute('SELECT value_id FROM home_candidate_values WHERE language_id=? AND primary_text=? AND translation=?',(lid,primary,translation)).fetchone()
                    if found:value=found[0]
                if value is None:
                    n+=1;value=n;seen.add(fingerprint)
                    values.append((value,lid,primary,translation));slots.append((n-1,value,kind,rid,lid))
                sources.append((kind,rid,value,sort_text,position,source_rowid))
                if len(sources)>=400:flush()
        flush()
    return n


class Population(Sequence):
    def __init__(self, db):
        self.db = db
        self.n = db.execute('SELECT n FROM home_candidate_state WHERE id=1').fetchone()[0]

    def __len__(self):return self.n

    def __getitem__(self, index):
        if index < 0:index += self.n
        if not 0 <= index < self.n:raise IndexError(index)
        row = self.db.execute('SELECT kind,id,language_id FROM home_candidate_slots WHERE slot=?', (index,)).fetchone()
        if row is None:raise IndexError(index)
        return tuple(row)


def sample(db):
    if not db.execute("SELECT 1 FROM sqlite_master WHERE name='home_candidate_state'").fetchone():
        return None
    rebuild = db.execute('SELECT rebuild FROM home_candidate_state WHERE id=1').fetchone()[0]
    if rebuild or db.execute('SELECT 1 FROM home_candidate_dirty LIMIT 1').fetchone():
        try:
            with material_search_index.preparing(db):refresh(db)
        except material_search_index.Unavailable:
            return None
    population = Population(db)
    return random.sample(population,min(24,len(population)))
