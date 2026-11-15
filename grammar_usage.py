"""Incremental frequencies of effective word recipes for the label registry."""
from collections import Counter,defaultdict
from functools import lru_cache
import hashlib
import json
import record_sources
import read_views

import corpus
import gloss_search_index
import long_tasks
import material_search_index


WEIGHTS=read_views.Cache(16*1024**2)
REGISTRIES=read_views.Cache(6*1024**2)
POLICIES=read_views.Cache(256*1024)

VERSION='grammar-usage-v2'
DIRECT_VERSION='grammar-usage-label-counts-v1'
COLD_OWNER_LIMIT=512
TABLES=('grammar_usage_words','grammar_usage_totals','grammar_usage_dirty','grammar_usage_labels',
        'grammar_usage_recipe_dirty','grammar_usage_state','grammar_usage_registry',
        'grammar_usage_source_dirty','grammar_usage_source_state','grammar_usage_cells','grammar_usage_label_totals')


def drop(db):
    for name, in db.execute("SELECT name FROM sqlite_master WHERE type='trigger' AND name GLOB 'grammar_usage_*'").fetchall():
        db.execute('DROP TRIGGER "'+name.replace('"','""')+'"')
    for table in TABLES:db.execute('DROP TABLE IF EXISTS '+table)


def initialize(db):
    existed=db.execute("SELECT 1 FROM sqlite_master WHERE name='grammar_usage_dirty'").fetchone()
    had_recipes=db.execute("SELECT 1 FROM sqlite_master WHERE name='grammar_usage_recipe_dirty'").fetchone()
    db.executescript('''
        CREATE TABLE IF NOT EXISTS grammar_usage_dirty(kind TEXT,id TEXT,PRIMARY KEY(kind,id)) WITHOUT ROWID;
        CREATE TABLE IF NOT EXISTS grammar_usage_words(kind TEXT,id TEXT,lid TEXT,recipe INTEGER,n INTEGER,
          PRIMARY KEY(kind,id,lid,recipe)) WITHOUT ROWID;
        CREATE TABLE IF NOT EXISTS grammar_usage_totals(lid TEXT,kind TEXT,recipe INTEGER,n INTEGER,
          PRIMARY KEY(lid,kind,recipe)) WITHOUT ROWID;
        CREATE TABLE IF NOT EXISTS grammar_usage_labels(recipe INTEGER PRIMARY KEY,revision TEXT,labels TEXT);
        CREATE TABLE IF NOT EXISTS grammar_usage_recipe_dirty(recipe INTEGER PRIMARY KEY);
        CREATE TABLE IF NOT EXISTS grammar_usage_state(id INTEGER PRIMARY KEY CHECK(id=1),version TEXT,epoch BLOB);
        CREATE TABLE IF NOT EXISTS grammar_usage_registry(key BLOB PRIMARY KEY,data TEXT NOT NULL);
        CREATE TRIGGER IF NOT EXISTS grammar_usage_add AFTER INSERT ON grammar_usage_words BEGIN
          INSERT INTO grammar_usage_totals VALUES(NEW.lid,NEW.kind,NEW.recipe,NEW.n)
            ON CONFLICT(lid,kind,recipe) DO UPDATE SET n=n+NEW.n; END;
        CREATE TRIGGER IF NOT EXISTS grammar_usage_remove AFTER DELETE ON grammar_usage_words BEGIN
          UPDATE grammar_usage_totals SET n=n-OLD.n WHERE lid=OLD.lid AND kind=OLD.kind AND recipe=OLD.recipe;
          DELETE FROM grammar_usage_totals WHERE lid=OLD.lid AND kind=OLD.kind AND recipe=OLD.recipe AND n=0; END;
    ''')
    previous=db.execute('SELECT version FROM grammar_usage_state WHERE id=1').fetchone()
    if not had_recipes or not previous or previous[0]!=VERSION:
        # One migration scan, not a scan of an ever-growing completed prefix
        # for every batch and every subsequent registry request.
        where='' if previous and previous[0]!=VERSION else ' LEFT JOIN grammar_usage_labels l ON l.recipe=r.id WHERE l.revision IS NOT r.revision'
        db.execute('INSERT INTO grammar_usage_recipe_dirty SELECT r.id FROM gloss_search_recipes r'+where+
                   (' AND ' if ' WHERE ' in where else ' WHERE ')+
                   'NOT EXISTS(SELECT 1 FROM grammar_usage_recipe_dirty d WHERE d.recipe=r.id)')
        db.execute('INSERT INTO grammar_usage_state VALUES(1,?,randomblob(16)) ON CONFLICT(id) DO UPDATE SET version=excluded.version,epoch=excluded.epoch',(VERSION,))
    for event in ('INSERT','UPDATE','DELETE'):
        refs=('OLD','NEW') if event=='UPDATE' else ('OLD',) if event=='DELETE' else ('NEW',)
        when=' WHEN OLD.id IS NOT NEW.id OR OLD.output IS NOT NEW.output OR OLD.revision IS NOT NEW.revision' if event=='UPDATE' else ''
        body=''.join(f'INSERT INTO grammar_usage_recipe_dirty SELECT {ref}.id WHERE NOT EXISTS(SELECT 1 FROM grammar_usage_recipe_dirty WHERE recipe={ref}.id);' for ref in refs)
        db.execute(f'''CREATE TRIGGER IF NOT EXISTS grammar_usage_recipe_{event} AFTER {event} ON gloss_search_recipes{when}
          BEGIN {body} UPDATE grammar_usage_state SET epoch=randomblob(16) WHERE id=1; END''')
    db.execute('''CREATE TRIGGER IF NOT EXISTS grammar_usage_label_remove AFTER DELETE ON grammar_usage_labels BEGIN
      INSERT INTO grammar_usage_recipe_dirty SELECT OLD.recipe
        WHERE EXISTS(SELECT 1 FROM gloss_search_recipes WHERE id=OLD.recipe)
          AND NOT EXISTS(SELECT 1 FROM grammar_usage_recipe_dirty WHERE recipe=OLD.recipe);
      UPDATE grammar_usage_state SET epoch=randomblob(16) WHERE id=1; END''')
    install_owner_triggers(db)
    db.execute("""CREATE TRIGGER IF NOT EXISTS grammar_usage_text_language AFTER UPDATE OF language_id ON texts
        WHEN OLD.language_id IS NOT NEW.language_id BEGIN INSERT INTO grammar_usage_dirty
        SELECT 'corpus',e.id FROM entries e WHERE e.text_id=NEW.id AND NOT EXISTS(
          SELECT 1 FROM grammar_usage_dirty d WHERE d.kind='corpus' AND d.id=e.id); END""")
    if not existed:
        db.execute("INSERT INTO grammar_usage_dirty SELECT 'corpus',id FROM entries UNION ALL SELECT 'independent',id FROM dictionary_examples")
    if record_sources.native(db):initialize_direct(db)


def install_owner_triggers(db):
    for table,kind in (('gloss_search_words',None),('entries','corpus'),('dictionary_examples','independent')):
        for event in ('INSERT','UPDATE','DELETE'):
            body=''
            for ref in (('OLD','NEW') if event=='UPDATE' else ('OLD',) if event=='DELETE' else ('NEW',)):
                k=f"'{kind}'" if kind else ref+'.kind'
                rid=ref+('.id' if kind else '.owner_id')
                body+=f'INSERT INTO grammar_usage_dirty SELECT {k},{rid} WHERE NOT EXISTS(SELECT 1 FROM grammar_usage_dirty WHERE kind={k} AND id={rid});'
            # A native example's revision can change when only a dictionary
            # link changed. The gloss/override triggers cover actual word edits.
            when=''
            if event=='UPDATE' and table=='dictionary_examples' and record_sources.native(db):
                when=f' WHEN OLD.id IS NOT NEW.id OR OLD.language_id IS NOT NEW.language_id OR {record_sources.change_sql(db,table)}'
            record_sources.trigger(db,f'grammar_usage_{table}_{event}',f'AFTER {event} ON {table}{when} BEGIN '+body+' END')


def initialize_direct(db):
    record_sources.schema_sql(db,'''
      CREATE TABLE IF NOT EXISTS grammar_usage_source_dirty(kind TEXT,id TEXT,PRIMARY KEY(kind,id)) WITHOUT ROWID;
      CREATE TABLE IF NOT EXISTS grammar_usage_source_state(id INTEGER PRIMARY KEY CHECK(id=1),version TEXT,epoch BLOB);
      CREATE TABLE IF NOT EXISTS grammar_usage_cells(kind TEXT,id TEXT,lid TEXT,label TEXT,n INTEGER NOT NULL,
        PRIMARY KEY(kind,id,lid,label)) WITHOUT ROWID;
      CREATE TABLE IF NOT EXISTS grammar_usage_label_totals(lid TEXT,kind TEXT,label TEXT,n INTEGER NOT NULL,
        PRIMARY KEY(lid,kind,label)) WITHOUT ROWID;
    ''')
    enabled='EXISTS(SELECT 1 FROM grammar_usage_source_state WHERE id=1)'
    owners={
        'entries':("'corpus'",'id'),
        'dictionary_examples':("'independent'",'id'),
        'corpus_units':("'corpus'",'entry_id'),
        'independent_word_overrides':("'independent'",'example_id'),
        'gloss_bindings':(None,'owner_id'),
    }
    for table,(kind,identity) in owners.items():
        for event in ('INSERT','UPDATE','DELETE'):
            refs=('OLD','NEW') if event=='UPDATE' else ('OLD',) if event=='DELETE' else ('NEW',)
            sql=''
            for ref in refs:
                source=kind or ref+'.owner_kind'
                rid=f'{ref}.{identity}'
                sql+=f'''INSERT INTO grammar_usage_source_dirty SELECT {source},{rid} WHERE NOT EXISTS (
                    SELECT 1 FROM grammar_usage_source_dirty WHERE kind={source} AND id={rid});'''
            changed=''
            if event=='UPDATE' and table in ('entries','dictionary_examples'):
                scope='text_id' if table=='entries' else 'language_id'
                changed=f' AND (OLD.id IS NOT NEW.id OR OLD.{scope} IS NOT NEW.{scope} OR {record_sources.change_sql(db,table)})'
            record_sources.trigger(db,f'grammar_usage_direct_{table}_{event}',
                                   f'AFTER {event} ON {table} WHEN {enabled}{changed} BEGIN {sql} END')
    for event in ('INSERT','UPDATE','DELETE'):
        refs='OLD.id,NEW.id' if event=='UPDATE' else 'OLD.id' if event=='DELETE' else 'NEW.id'
        record_sources.trigger(db,f'grammar_usage_direct_meanings_{event}',f'''AFTER {event} ON gloss_meanings
          WHEN {enabled} BEGIN INSERT INTO grammar_usage_source_dirty
          SELECT DISTINCT b.owner_kind,b.owner_id FROM gloss_bindings b WHERE b.meaning_id IN ({refs})
          AND NOT EXISTS(SELECT 1 FROM grammar_usage_source_dirty d WHERE d.kind=b.owner_kind AND d.id=b.owner_id); END''')
    record_sources.trigger(db,'grammar_usage_direct_text_language',f'''AFTER UPDATE OF language_id ON texts
      WHEN OLD.language_id IS NOT NEW.language_id AND {enabled} BEGIN
      INSERT INTO grammar_usage_source_dirty SELECT 'corpus',e.id FROM entries e WHERE e.text_id=NEW.id
        AND NOT EXISTS(SELECT 1 FROM grammar_usage_source_dirty d WHERE d.kind='corpus' AND d.id=e.id); END''')


def direct_state(db):
    if not db.execute("SELECT 1 FROM sqlite_master WHERE name='grammar_usage_source_state'").fetchone():return None
    return db.execute('SELECT version,epoch FROM grammar_usage_source_state WHERE id=1').fetchone()


def direct_candidate(db):
    if not record_sources.native(db) or not db.execute(
        "SELECT 1 FROM sqlite_master WHERE name='grammar_usage_source_state'").fetchone():return False
    if db.execute('SELECT 1 FROM grammar_usage_words LIMIT 1').fetchone():return False
    return db.execute('SELECT 1 FROM gloss_search_dirty LIMIT 1 OFFSET ?',(COLD_OWNER_LIMIT,)).fetchone() is not None


def label_values(word):
    word=corpus.analyze(dict(ipa='',translation='',words=[word]))['words'][0]
    if word.get('unit_type') in ('phonological_boundary','punctuation'):return []
    labels=[]
    for morph in word['morphemes'] or [word]:
        label=morph.get('display_gloss',morph['gloss'])
        labels.append('<'+label+'>' if morph.get('kind')=='infix' else label)
    return labels


def source_owners(kind):
    if kind=='corpus':
        return """SELECT e.id,COALESCE(NULLIF(s.language_id,''),t.language_id) lid FROM entries e
          JOIN texts t ON t.id=e.text_id JOIN sentence_text_rows s ON s.kind='corpus' AND s.owner_id=e.id"""
    return """SELECT e.id,COALESCE(NULLIF(s.language_id,''),e.language_id) lid FROM dictionary_examples e
      JOIN sentence_text_rows s ON s.kind='independent' AND s.owner_id=e.id"""


def prepare_direct(db,lid,source):
    if direct_state(db) is None:
        db.execute('INSERT INTO grammar_usage_source_state VALUES(1,?,randomblob(16))',(DIRECT_VERSION,))
        db.execute("""INSERT INTO grammar_usage_source_dirty SELECT 'corpus',id FROM entries
                      UNION ALL SELECT 'independent',id FROM dictionary_examples""")
    @lru_cache(maxsize=1024)
    def slot_labels(form,value,extra,bindings):
        return Counter(label_values(gloss_search_index.effective_slot(form,value,extra,bindings)))

    changed=False
    for kind in ('corpus','independent'):
        if source not in ('all',kind):continue
        owners=source_owners(kind)
        query='SELECT d.id FROM grammar_usage_source_dirty d WHERE d.kind=?'
        params=(kind,)
        if lid!='all':
            query+=f''' AND (EXISTS(SELECT 1 FROM ({owners}) o WHERE o.id=d.id AND o.lid=?)
                OR EXISTS(SELECT 1 FROM grammar_usage_cells c WHERE c.kind=d.kind AND c.id=d.id AND c.lid=?))'''
            params+=(lid,lid)
        while batch:=db.execute(query+' LIMIT 200',params).fetchall():
            ids=[row[0] for row in batch];marks=','.join('?' for _ in ids)
            languages=dict(db.execute(owners+f' WHERE e.id IN ({marks})',ids))
            counts=defaultdict(Counter)
            for row,bindings in long_tasks.steps(gloss_search_index.effective_inputs(db,kind,list(languages))):
                form,value,extra=row['form'],row['gloss'],row['extra']
                labels=slot_labels if len(form)+len(value)+len(extra)<16384 else slot_labels.__wrapped__
                counts[row['owner_id']].update(labels(form,value,extra,bindings))
            scope=f' WHERE kind=? AND id IN ({marks})'
            delta=Counter({(row[0],row[1]):-row[2] for row in db.execute(
                'SELECT lid,label,SUM(n) FROM grammar_usage_cells'+scope+' GROUP BY lid,label',[kind,*ids])})
            rows=[]
            for rid,labels in counts.items():
                language=languages[rid]
                for label,n in labels.items():
                    rows.append((kind,rid,language,label,n))
                    delta[language,label]+=n
            db.execute('DELETE FROM grammar_usage_cells'+scope,[kind,*ids])
            db.executemany('INSERT INTO grammar_usage_cells VALUES(?,?,?,?,?)',rows)
            db.executemany('''INSERT INTO grammar_usage_label_totals VALUES(?,?,?,?)
                ON CONFLICT(lid,kind,label) DO UPDATE SET n=n+excluded.n''',
                ((language,kind,label,n) for (language,label),n in delta.items() if n))
            db.executemany('DELETE FROM grammar_usage_label_totals WHERE lid=? AND kind=? AND label=? AND n=0',
                           ((language,kind,label) for (language,label),n in delta.items() if n<0))
            db.execute('DELETE FROM grammar_usage_source_dirty'+scope,[kind,*ids])
            changed=True
            long_tasks.checkpoint(None,'正在汇总语法标签用量…')
    if changed:db.execute('UPDATE grammar_usage_source_state SET epoch=randomblob(16) WHERE id=1')


def pending(db):
    if direct_state(db) is not None:
        return db.execute('SELECT COUNT(*) FROM (SELECT 1 FROM grammar_usage_source_dirty LIMIT 201)').fetchone()[0]
    return db.execute('''SELECT count(*) FROM (
      SELECT 1 FROM grammar_usage_dirty UNION ALL SELECT 1 FROM grammar_usage_recipe_dirty
      UNION ALL SELECT 1 FROM gloss_search_dirty
      UNION ALL SELECT 1 FROM gloss_search_recipes WHERE dirty=1 LIMIT 201)''').fetchone()[0]


def prepare(db):
    with material_search_index.writing_cache(db):
        _prepare(db)


def _prepare(db):
    gloss_search_index.refresh(db,keys=False)
    native=record_sources.native(db)
    for kind in ('corpus','independent'):
        while batch:=db.execute('SELECT id FROM grammar_usage_dirty WHERE kind=? LIMIT 400',(kind,)).fetchall():
            ids=[r[0] for r in batch]
            marks=','.join('?' for _ in ids)
            source='entries' if kind=='corpus' else 'dictionary_examples'
            join=(f" JOIN sentence_text_rows s ON s.kind='{kind}' AND s.owner_id=e.id" if native else '')
            owner='t.language_id' if kind=='corpus' else 'e.language_id'
            if kind=='corpus':join+=' JOIN texts t ON t.id=e.text_id'
            language='s.language_id' if native else "json_extract(e.body,'$.language_id')"
            owners=f"SELECT e.id,COALESCE(NULLIF({language},''),{owner}) lid FROM {source} e{join}"
            db.execute(f'DELETE FROM grammar_usage_words WHERE kind=? AND id IN ({marks})',[kind,*ids])
            db.execute(f'''WITH owners AS MATERIALIZED ({owners} WHERE e.id IN ({marks}))
                INSERT INTO grammar_usage_words SELECT ?,o.id,o.lid,w.recipe_id,count(*) FROM owners o
                CROSS JOIN gloss_search_words w ON w.kind=? AND w.owner_id=o.id GROUP BY o.id,o.lid,w.recipe_id''', [*ids,kind,kind])
            db.execute(f'DELETE FROM grammar_usage_dirty WHERE kind=? AND id IN ({marks})',[kind,*ids])
            long_tasks.checkpoint()
    while batch:=db.execute('SELECT recipe FROM grammar_usage_recipe_dirty LIMIT 300').fetchall():
        ids=[row[0] for row in batch];marks=','.join('?' for _ in ids)
        rows=db.execute('SELECT id,output,revision FROM gloss_search_recipes WHERE id IN ('+marks+')',ids).fetchall()
        updates=[]
        for row in long_tasks.steps(rows):
            labels=label_values(json.loads(row['output']))
            updates.append((row['id'],row['revision'],json.dumps(labels,ensure_ascii=False)))
        db.executemany('''INSERT INTO grammar_usage_labels VALUES(?,?,?)
          ON CONFLICT(recipe) DO UPDATE SET revision=excluded.revision,labels=excluded.labels''',updates)
        db.execute('DELETE FROM grammar_usage_labels WHERE recipe IN ('+marks+') AND NOT EXISTS(SELECT 1 FROM gloss_search_recipes r WHERE r.id=recipe)',ids)
        db.execute('DELETE FROM grammar_usage_recipe_dirty WHERE recipe IN ('+marks+')',ids)


def library(db,q):
    import grammar, grammar_reference
    lid=q.get('language','all')
    source=q.get('source','all')
    if not db.in_transaction:db.execute('BEGIN')
    if db.execute("SELECT 1 FROM sqlite_master WHERE name='grammar_usage_dirty'").fetchone():
        try:
            direct=direct_state(db) is not None or direct_candidate(db)
            if direct:
                if direct_state(db) is None or pending(db):
                    with material_search_index.preparing(db),material_search_index.writing_cache(db):
                        prepare_direct(db,lid,source)
            elif pending(db):
                with material_search_index.preparing(db):prepare(db)
            source_stamp=read_views.token(db,'grammar_usage')
            state=direct_state(db) if direct else db.execute('SELECT version,epoch FROM grammar_usage_state WHERE id=1').fetchone()
            stamp=(source_stamp,*state) if source_stamp and state else None
        except material_search_index.Unavailable:
            pass
        else:
            tags=grammar.listing(db,lid)
            lookup=grammar.index(tags)
            policy_token=read_views.token(db,'own')
            policy_key=(policy_token,lid) if policy_token else None
            ignored=POLICIES.get(policy_key)
            if ignored is None:
                ignored={(r['id'],s) for r in db.execute("SELECT id,metadata FROM languages WHERE ?='all' OR id=?",(lid,lid))
                         for s in grammar.ignored_values(json.loads(r['metadata']))}
                POLICIES.put(policy_key,ignored,256+sum(128+4*(len(a)+len(b)) for a,b in ignored))
            registry=(stamp,lid,source,q.get('lower')=='true',tuple((t['id'],t['language_id'],t['symbol'],tuple(t['aliases'])) for t in tags),tuple(sorted(ignored))) if stamp else None
            def render(uses,unknown):
                return dict(tags=[dict(t,uses=uses[t['id']]) for t in tags],unknown=[
                    dict(language_id=lang,symbol=s,uses=n,reference=grammar_reference.find(s))
                    for (lang,s),n in sorted(unknown.items(),key=lambda pair:(-pair[1],pair[0]))],
                    ignored=[dict(language_id=lang,symbol=s) for lang,s in sorted(ignored)])
            previous=REGISTRIES.get(registry)
            if previous is not None:return render(*previous)
            # Only the compact classification result is persisted. Source,
            # recipe output, rules and exact tag/ignore definitions prove it.
            persistent_key=hashlib.sha256(json.dumps((source_stamp.hex(),state[0],state[1].hex(),
                grammar_reference.VERSION,lid,source,q.get('lower')=='true',registry[4:]),ensure_ascii=False).encode()).digest() if registry else None
            saved=db.execute('SELECT data FROM grammar_usage_registry WHERE key=?',(persistent_key,)).fetchone() if persistent_key else None
            if saved:
                try:
                    counts,candidates=json.loads(saved[0])
                    uses=Counter(dict(counts));unknown=Counter({(lang,s):n for lang,s,n in candidates})
                except (ValueError,TypeError):pass
                else:
                    REGISTRIES.put(registry,(uses,unknown),len(saved[0].encode('utf-8'))*4+512)
                    return render(uses,unknown)
            uses=Counter();unknown=Counter()
            if direct:
                sql="""SELECT lid,label,SUM(n) FROM grammar_usage_label_totals
                       WHERE (?='all' OR lid=?) AND (?='all' OR kind=?) GROUP BY lid,label"""
            else:
                sql='''SELECT t.lid,l.labels,sum(t.n) n FROM grammar_usage_totals t JOIN grammar_usage_labels l ON l.recipe=t.recipe
                       WHERE (?='all' OR t.lid=?) AND (?='all' OR t.kind=?) GROUP BY t.lid,l.labels'''
            key=(stamp,lid,source) if stamp else None
            weights=WEIGHTS.get(key)
            if weights is None:
                weights=list(db.execute(sql,(lid,lid,source,source)))
                WEIGHTS.put(key,weights,512+sum(256+4*(len(w[0])+len(w[1])) for w in weights))
            for lang,labels,n in long_tasks.steps(weights):
                for label in (labels,) if direct else json.loads(labels):
                    seen=set()
                    for token in grammar.tokens(label,lang,lookup,q.get('lower')=='true',candidates=True):
                        tag=lookup.get((lang,token.casefold()))
                        identity=tag['id'] if tag else token.casefold()
                        if identity in seen or not tag and (lang,token) in ignored:continue
                        seen.add(identity)
                        if tag:uses[tag['id']]+=n
                        else:unknown[lang,token]+=n
            cost=512+sum(256+4*(len(k[0])+len(k[1])) for k in unknown)+sum(256+len(t['id'])*4+len(t['symbol'])*4+sum(len(a)*4 for a in t['aliases']) for t in tags)
            REGISTRIES.put(registry,(uses,unknown),cost)
            if persistent_key and cost<=REGISTRIES.limit:
                data=json.dumps([list(uses.items()),[[lang,s,n] for (lang,s),n in unknown.items()]],ensure_ascii=False,separators=(',',':'))
                try:
                    with material_search_index.preparing(db):
                        db.execute('INSERT INTO grammar_usage_registry VALUES(?,?) ON CONFLICT(key) DO UPDATE SET data=excluded.data',(persistent_key,data))
                        db.execute('DELETE FROM grammar_usage_registry WHERE rowid NOT IN (SELECT rowid FROM grammar_usage_registry ORDER BY rowid DESC LIMIT 16)')
                except material_search_index.Unavailable:pass
            return render(uses,unknown)
    result=grammar.audit(db,{k:v for k,v in q.items() if k!='view'})
    return {k:result[k] for k in ('tags','unknown','ignored')}
