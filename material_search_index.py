"""Shared record parts, dictionary evidence and custom sentence search keys.

Only dirty sources are expanded. Effective words refer to the gloss projection;
dictionary predicates join matching part IDs to current association identities.
No derived row belongs to business exports or undo history.
"""
import copy
import hashlib
import json
import record_sources
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
          'material_search_owners','material_search_dirty','material_search_options',
          'material_search_literal_records','material_search_literal_state','material_search_literal_positions',
          'material_search_literal_dirty','material_search_literal_dependencies',
          'material_search_manual_values','material_search_manual_dirty','material_search_manual_state',
          'material_search_literal_indexed','material_search_literal_fts')
CUSTOM_RECIPE_TRIGGER = 'material_search_custom_recipe_update'
LITERAL_DEPENDENCY_TOKEN = b'dependency-v1'
STALE_CUSTOM_RECIPES = '''FROM material_search_custom_deps d LEFT JOIN gloss_search_recipes r ON r.id=d.recipe_id
    WHERE (r.id IS NULL OR r.dirty=1 OR r.revision!=d.revision)'''


def available(db):
    return bool(db.execute("SELECT 1 FROM sqlite_master WHERE name='material_search_owners'").fetchone())


class Unavailable(Exception):
    """A read-only or pinned reader can use the original source matcher."""


@contextmanager
def writing_cache(db):
    """Use 32 MiB for bulk builds unless the connection already allows more."""
    previous = db.execute('PRAGMA cache_size').fetchone()[0]
    page_size = db.execute('PRAGMA page_size').fetchone()[0]
    size = -previous*1024 if previous<0 else previous*page_size
    changed = size<32*1024**2
    if changed:
        db.execute('PRAGMA cache_size=-32768')
    try:
        yield
    finally:
        if changed:
            db.execute('PRAGMA cache_size='+str(previous))


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
    import dictionary_option_catalog
    for row in db.execute("SELECT name FROM sqlite_master WHERE type='trigger' AND name LIKE 'material_search_%'").fetchall():
        db.execute('DROP TRIGGER "'+row[0].replace('"','""')+'"')
    for table in (*TABLES,*dictionary_option_catalog.TABLES):
        db.execute('DROP TABLE IF EXISTS '+table)


def initialize(db):
    import dictionary_option_catalog
    record_sources.schema_sql(db, '''
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
      CREATE TABLE IF NOT EXISTS material_search_literal_records(context TEXT,kind TEXT,owner_id TEXT,
        value TEXT,folded TEXT,PRIMARY KEY(context,kind,owner_id)) WITHOUT ROWID;
      CREATE INDEX IF NOT EXISTS material_search_literal_owner ON material_search_literal_records(kind,owner_id);
      CREATE TABLE IF NOT EXISTS material_search_literal_state(context TEXT PRIMARY KEY,token BLOB,generation BLOB);
      CREATE TABLE IF NOT EXISTS material_search_literal_dirty(context TEXT,kind TEXT,owner_id TEXT,
        PRIMARY KEY(context,kind,owner_id)) WITHOUT ROWID;
      CREATE TABLE IF NOT EXISTS material_search_literal_dependencies(context TEXT,key TEXT,kind TEXT,owner_id TEXT,
        PRIMARY KEY(context,key,kind,owner_id)) WITHOUT ROWID;
      CREATE INDEX IF NOT EXISTS material_search_literal_record_dependencies ON
        material_search_literal_dependencies(context,kind,owner_id);
      CREATE TABLE IF NOT EXISTS material_search_manual_values(id TEXT PRIMARY KEY,value_id INTEGER) WITHOUT ROWID;
      CREATE INDEX IF NOT EXISTS material_search_manual_by_value ON material_search_manual_values(value_id);
      CREATE TABLE IF NOT EXISTS material_search_manual_dirty(id TEXT PRIMARY KEY) WITHOUT ROWID;
      CREATE TABLE IF NOT EXISTS material_search_manual_state(id INTEGER PRIMARY KEY CHECK(id=1));
    ''')
    if 'display' not in {r[1] for r in db.execute('PRAGMA table_info(material_search_custom)')}:
        db.execute('ALTER TABLE material_search_custom ADD COLUMN display TEXT')
        db.execute('UPDATE material_search_dirty SET custom=1')
    if 'classes' not in {r[1] for r in db.execute('PRAGMA table_info(material_search_documents)')}:
        db.execute("ALTER TABLE material_search_documents ADD COLUMN classes TEXT NOT NULL DEFAULT '[]'")
        db.execute('UPDATE material_search_documents SET dirty=1')
    recipe_queue = has_custom_recipe_queue(db)
    for row in db.execute("SELECT name FROM sqlite_master WHERE type='trigger' AND name LIKE 'material_search_%'").fetchall():
        db.execute('DROP TRIGGER "'+row[0].replace('"','""')+'"')

    if not recipe_queue:
        queue_custom_recipes(db,'SELECT DISTINCT d.kind,d.owner_id '+STALE_CUSTOM_RECIPES)
    recipe_owners='SELECT kind,owner_id FROM material_search_custom_deps WHERE recipe_id=OLD.id'
    for suffix,event in (('update','AFTER UPDATE OF dirty,revision ON gloss_search_recipes '
                                   'WHEN (NEW.dirty=1 AND OLD.dirty!=1) OR NEW.revision IS NOT OLD.revision'),
                         ('delete','AFTER DELETE ON gloss_search_recipes')):
        db.execute(f'CREATE TRIGGER material_search_custom_recipe_{suffix} {event} BEGIN '+
                   custom_recipe_sql(recipe_owners)+'; END')

    def queue(kind, rid, basic=0, *, literal=False):
        sql=f'''INSERT INTO material_search_dirty SELECT {kind},{rid},{basic},1 WHERE NOT EXISTS(
            SELECT 1 FROM material_search_dirty WHERE kind={kind} AND owner_id={rid});
          UPDATE material_search_dirty SET custom=1,basic=max(basic,{basic}) WHERE kind={kind} AND owner_id={rid};'''
        if literal:sql+=f'DELETE FROM material_search_literal_records WHERE kind={kind} AND owner_id={rid};'
        return sql

    for table, kind in (('entries','corpus'),('dictionary_examples','independent')):
        for event in ('INSERT','UPDATE','DELETE'):
            refs=('OLD','NEW') if event=='UPDATE' else ('OLD',) if event=='DELETE' else ('NEW',)
            body=''.join(queue("'"+kind+"'",ref+'.id',1,literal=True) for ref in refs)
            when=f' WHEN {record_sources.change_sql(db,table)} OR OLD.id IS NOT NEW.id' if event=='UPDATE' else ''
            db.execute(f'CREATE TRIGGER material_search_{table}_{event} AFTER {event} ON {table}{when} BEGIN '+body+' END')
        db.execute(f'''INSERT OR IGNORE INTO material_search_dirty SELECT ?,s.id,1,1 FROM {table} s
          WHERE NOT EXISTS(SELECT 1 FROM material_search_owners o WHERE o.kind=? AND o.owner_id=s.id)''',(kind,kind))
    for table in ('annotation_cells','gloss_bindings','corpus_units','lexical_links','independent_links','independent_word_overrides'):
        for event in ('INSERT','UPDATE','DELETE'):
            refs=('OLD','NEW') if event=='UPDATE' else ('OLD',) if event=='DELETE' else ('NEW',)
            statements=[]
            for ref in refs:
                if table=='annotation_cells':statements.append(queue(ref+'.owner_kind',ref+'.record_id'))
                elif table=='gloss_bindings':statements.append(queue(ref+'.owner_kind',ref+'.owner_id',literal=True))
                elif table=='corpus_units':statements.append(queue("'corpus'",ref+'.entry_id',literal=True))
                elif table in ('independent_links','independent_word_overrides'):
                    statements.append(queue("'independent'",ref+'.example_id',literal=table=='independent_word_overrides'))
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
                corpus_keys = 'corpus_sentence_keys' if record_sources.native(db) else 'entries'
                language = 'e.language_id' if record_sources.native(db) else "json_extract(e.body,'$.language_id')"
                affected=f'''(o.kind='corpus' AND EXISTS(SELECT 1 FROM {corpus_keys} e JOIN texts t ON t.id=e.text_id WHERE e.id=o.owner_id
                  AND COALESCE(NULLIF({language},''),t.language_id) IN ({lids})) OR o.kind='independent' AND EXISTS(
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
            legacy = ' OR '.join(f"json_extract(OLD.body,'$.{key}') IS NOT json_extract(NEW.body,'$.{key}')"
                                 for key in ('orthographies','writings','word_structure'))
            changed = record_sources.change_sql(db,table,record_sources.WRITING,legacy)
            when=f''' WHEN OLD.id IS NOT NEW.id OR OLD.language_id IS NOT NEW.language_id
              OR {changed} OR EXISTS(SELECT 1 FROM annotation_layers WHERE source='dictionary')''' if event=='UPDATE' else ''
            if record_sources.native(db):
                # A definition may acquire its first writing after the linked
                # sentences were prepared using only manual annotations.
                statements+=''.join(f'''INSERT INTO material_search_dirty
                    SELECT 'corpus',u.entry_id,0,1 FROM lexical_links l
                    CROSS JOIN corpus_units u ON u.id=l.unit_id WHERE l.lexeme_id={ref}.id
                    ON CONFLICT(kind,owner_id) DO UPDATE SET custom=1;
                    INSERT INTO material_search_dirty
                    SELECT 'independent',l.example_id,0,1 FROM independent_links l WHERE l.lexeme_id={ref}.id
                    ON CONFLICT(kind,owner_id) DO UPDATE SET custom=1;''' for ref in refs)
            db.execute(f'CREATE TRIGGER material_search_{table}_{event} AFTER {event} ON {table}{when} BEGIN '+statements+' END')
    for event in ('INSERT','UPDATE','DELETE'):
        refs='OLD.id,NEW.id' if event=='UPDATE' else 'OLD.id' if event=='DELETE' else 'NEW.id'
        db.execute(f'''CREATE TRIGGER material_search_literal_meaning_{event} AFTER {event} ON gloss_meanings BEGIN
          DELETE FROM material_search_literal_records WHERE (kind,owner_id) IN (
            SELECT DISTINCT owner_kind,owner_id FROM gloss_bindings WHERE meaning_id IN ({refs})); END''')
    dependency_token="X'"+LITERAL_DEPENDENCY_TOKEN.hex()+"'"
    db.execute(f'''CREATE TRIGGER material_search_literal_removed AFTER DELETE ON material_search_literal_records
        BEGIN
          INSERT INTO material_search_literal_dirty SELECT OLD.context,OLD.kind,OLD.owner_id
            WHERE EXISTS(SELECT 1 FROM material_search_literal_state WHERE context=OLD.context AND token={dependency_token})
            ON CONFLICT DO NOTHING;
          DELETE FROM material_search_literal_dependencies WHERE context=OLD.context AND kind=OLD.kind AND owner_id=OLD.owner_id;
          UPDATE material_search_literal_state SET generation=NULL WHERE context=OLD.context AND generation IS NOT NULL;
        END''')
    membership={'independent_links':('independent','example_id',('example_id','lexeme_id')),
                'lexical_links':('corpus','unit_id',('unit_id','lexeme_id')),
                'corpus_units':('corpus','entry_id',('entry_id','id')),
                'dictionary_examples':('independent','id',('id','language_id'))}
    for table,(kind,owner,fields) in membership.items():
        events=('UPDATE',) if table=='dictionary_examples' else ('INSERT','UPDATE','DELETE')
        for event in events:
            refs=('OLD','NEW') if event=='UPDATE' else ('OLD',) if event=='DELETE' else ('NEW',)
            when=f' WHEN EXISTS(SELECT 1 FROM material_search_literal_state WHERE token={dependency_token})'
            if event=='UPDATE':when+=' AND ('+' OR '.join(f'OLD.{key} IS NOT NEW.{key}' for key in fields)+')'
            sql=''
            for ref in refs:
                source=f'SELECT {ref}.{owner} id'
                if table=='lexical_links':source=f'SELECT entry_id id FROM corpus_units WHERE id={ref}.unit_id'
                sql+=f'''INSERT INTO material_search_literal_dirty SELECT context,'{kind}',s.id
                    FROM material_search_literal_state CROSS JOIN ({source}) s
                    WHERE token={dependency_token} AND s.id IS NOT NULL ON CONFLICT DO NOTHING;'''
            db.execute(f'CREATE TRIGGER material_search_literal_owners_{table}_{event} AFTER {event} ON {table}{when} BEGIN {sql} END')
    if record_sources.native(db):
        for event in ('INSERT','UPDATE','DELETE'):
            refs=('OLD','NEW') if event=='UPDATE' else ('OLD',) if event=='DELETE' else ('NEW',)
            when=' WHEN OLD.id IS NOT NEW.id OR OLD.value IS NOT NEW.value' if event=='UPDATE' else ''
            sql=''.join(f'''INSERT INTO material_search_manual_dirty SELECT {ref}.id FROM material_search_manual_state WHERE id=1
                       ON CONFLICT DO NOTHING;''' for ref in refs)
            record_sources.trigger(db,f'material_search_manual_{event}',f'AFTER {event} ON annotation_cells{when} BEGIN {sql} END')
        for table,kind in (('lexemes','lexeme'),('morphemes','morpheme')):
            for event in ('INSERT','UPDATE','DELETE'):
                refs=('OLD','NEW') if event=='UPDATE' else ('OLD',) if event=='DELETE' else ('NEW',)
                when=f' WHEN EXISTS(SELECT 1 FROM material_search_literal_state WHERE token={dependency_token})'
                if event=='UPDATE':when+=' AND (OLD.id IS NOT NEW.id OR OLD.language_id IS NOT NEW.language_id)'
                sql=''.join(f'''INSERT INTO material_search_literal_dirty SELECT st.context,p.kind,p.id
                   FROM material_search_literal_state st CROSS JOIN (
                       SELECT 'corpus' kind,u.entry_id id FROM lexical_links l JOIN corpus_units u ON u.id=l.unit_id WHERE l.lexeme_id={ref}.id
                       UNION SELECT 'independent',example_id FROM independent_links WHERE lexeme_id={ref}.id
                   ) p WHERE st.token={dependency_token} ON CONFLICT DO NOTHING;''' for ref in refs)
                record_sources.trigger(db,f'material_search_literal_targets_{kind}_{event}',f'AFTER {event} ON {table}{when} BEGIN {sql} END')
        for table in ('sentence_text_rows','sentence_word_rows','independent_frozen_values','independent_override_values'):
            if db.execute("SELECT 1 FROM sqlite_master WHERE name=?",(table,)).fetchone():
                install_literal_source_triggers(db,table)
    initialize_literal_fts(db)
    dictionary_option_catalog.initialize(db)
    for table in (() if record_sources.native(db) else
                  ('lexemes','morphemes','category_classes','semantic_classes','grammar_tags','writing_types','annotation_layers')):
        for event in ('INSERT','UPDATE','DELETE'):
            where=''
            if table in ('lexemes','morphemes'):
                # Keep both kinds in case their catalog uses another target's
                # metadata. Shared definitions still invalidate every scope.
                languages="'all',"+','.join(('OLD.language_id','NEW.language_id') if event=='UPDATE' else
                                           ('OLD.language_id',) if event=='DELETE' else ('NEW.language_id',))
                where=f' WHERE language_id IN ({languages})'
            db.execute(f'CREATE TRIGGER material_search_options_{table}_{event} AFTER {event} ON {table} BEGIN DELETE FROM material_search_options{where}; END')


def install_literal_source_triggers(db,table):
    def owner(ref):
        if table=='independent_override_values':
            return (f"SELECT 'independent',example_id FROM independent_word_overrides WHERE id={ref}.parent_id "
                    f"AND snapshot={ref}.snapshot")
        return f'''SELECT {ref}.kind,{ref}.owner_id WHERE NOT EXISTS(
            SELECT 1 FROM record_source_writes WHERE owner_id={ref}.owner_id
              AND source=CASE {ref}.kind WHEN 'corpus' THEN 'entries' ELSE 'dictionary_examples' END)'''

    for event in ('INSERT','UPDATE','DELETE'):
        refs=('OLD','NEW') if event=='UPDATE' else ('OLD',) if event=='DELETE' else ('NEW',)
        owners=' UNION ALL '.join(owner(ref) for ref in refs)
        record_sources.trigger(db,f'material_search_literal_external_{table}_{event}',f'''AFTER {event} ON {table}
          WHEN EXISTS({owners}) BEGIN
            DELETE FROM material_search_literal_records WHERE (kind,owner_id) IN ({owners});
            UPDATE read_view_tokens SET token=randomblob(16) WHERE domain IN ('content','dictionary');
          END''')


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


def initialize_literal_fts(db):
    if not record_sources.native(db):
        return
    try:
        db.execute("""CREATE VIRTUAL TABLE IF NOT EXISTS material_search_literal_fts
            USING fts5(folded,content='',contentless_delete=1,tokenize='trigram case_sensitive 1',detail=none)""")
    except sqlite3.OperationalError as exc:
        if any(reason in str(exc).lower() for reason in ('no such module','tokenizer','unrecognized option')):
            return
        raise
    record_sources.schema_sql(db, '''
      CREATE TABLE IF NOT EXISTS material_search_literal_positions(
        id INTEGER PRIMARY KEY,context TEXT,kind TEXT,owner_id TEXT,UNIQUE(context,kind,owner_id));
      CREATE TABLE IF NOT EXISTS material_search_literal_indexed(context TEXT PRIMARY KEY) WITHOUT ROWID;
    ''')
    db.execute('''CREATE TRIGGER material_search_literal_post_insert AFTER INSERT ON material_search_literal_records
      WHEN EXISTS(SELECT 1 FROM material_search_literal_indexed WHERE context=NEW.context)
      BEGIN
        INSERT INTO material_search_literal_positions(context,kind,owner_id) VALUES(NEW.context,NEW.kind,NEW.owner_id);
        INSERT INTO material_search_literal_fts(rowid,folded) VALUES(last_insert_rowid(),NEW.folded);
      END''')
    db.execute('''CREATE TRIGGER material_search_literal_post_delete AFTER DELETE ON material_search_literal_records
      WHEN EXISTS(SELECT 1 FROM material_search_literal_indexed WHERE context=OLD.context)
      BEGIN
        DELETE FROM material_search_literal_fts WHERE rowid=(
          SELECT id FROM material_search_literal_positions WHERE context=OLD.context AND kind=OLD.kind AND owner_id=OLD.owner_id);
        DELETE FROM material_search_literal_positions WHERE context=OLD.context AND kind=OLD.kind AND owner_id=OLD.owner_id;
      END''')


def literal_hits(db,context,needle,case):
    """Use folded trigrams for candidates and verify the exact original predicate."""
    column='value' if case else 'folded'
    folded=needle.casefold()
    if len(folded)<3 or not db.execute("SELECT 1 FROM sqlite_master WHERE name='material_search_literal_fts'").fetchone():
        return f'SELECT kind,owner_id AS id FROM material_search_literal_records WHERE context=? AND instr({column},?)>0',[context,needle]
    if not db.execute('SELECT 1 FROM material_search_literal_indexed WHERE context=?',(context,)).fetchone():
        db.execute('''INSERT INTO material_search_literal_positions(context,kind,owner_id)
          SELECT context,kind,owner_id FROM material_search_literal_records WHERE context=?''',(context,))
        db.execute('''INSERT INTO material_search_literal_fts(rowid,folded)
          SELECT p.id,r.folded FROM material_search_literal_positions p
          CROSS JOIN material_search_literal_records r USING(context,kind,owner_id) WHERE p.context=?''',(context,))
        db.execute('INSERT INTO material_search_literal_indexed VALUES(?)',(context,))
    sql=f"""SELECT r.kind,r.owner_id AS id FROM material_search_literal_fts f
      CROSS JOIN material_search_literal_positions p ON p.id=f.rowid
      CROSS JOIN material_search_literal_records r USING(context,kind,owner_id)
      WHERE material_search_literal_fts MATCH ? AND p.context=? AND instr(r.{column},?)>0"""
    return sql,['"'+folded[:3].replace('"','""')+'"',context,needle]


def pending(db):
    if not available(db):return 0
    source='SELECT 1 FROM material_search_dirty WHERE custom=1'
    if not has_custom_recipe_queue(db):source+=' UNION ALL SELECT 1 '+STALE_CUSTOM_RECIPES
    return db.execute('SELECT count(*) FROM ('+source+' LIMIT 201)').fetchone()[0]


def has_custom_recipe_queue(db):
    return db.execute("SELECT 1 FROM sqlite_master WHERE type='trigger' AND name=?",(CUSTOM_RECIPE_TRIGGER,)).fetchone() is not None


def custom_recipe_sql(owners):
    return '''INSERT INTO material_search_dirty SELECT kind,owner_id,0,1 FROM ('''+owners+''') WHERE 1
        ON CONFLICT(kind,owner_id) DO UPDATE SET custom=1 WHERE custom!=1'''


def queue_custom_recipes(db,owners):
    db.execute(custom_recipe_sql(owners))


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


def refresh_manual_cells(db,scope,values):
    """Index manual annotations in bulk and leave owners with writings queued."""
    import annotations
    batch='material_manual_'+uuid.uuid4().hex
    db.execute(f'CREATE TEMP TABLE {batch}(kind TEXT,owner_id TEXT,PRIMARY KEY(kind,owner_id)) WITHOUT ROWID')
    try:
        db.execute(f'''WITH writing_targets AS MATERIALIZED (
            SELECT DISTINCT v.target_id FROM dictionary_value_rows v
            JOIN writing_types w ON w.id=v.value WHERE v.slot='type_id' AND v.value_type='text'
        ), writing_owners(kind,owner_id) AS MATERIALIZED (
            SELECT 'corpus',u.entry_id FROM writing_targets x
            CROSS JOIN lexical_links l ON l.lexeme_id=x.target_id CROSS JOIN corpus_units u ON u.id=l.unit_id
            UNION ALL SELECT 'independent',l.example_id FROM writing_targets x
            CROSS JOIN independent_links l ON l.lexeme_id=x.target_id
        ) INSERT INTO {batch} SELECT d.kind,d.owner_id FROM material_search_dirty d
            WHERE d.custom=1{scope} AND (d.kind,d.owner_id) NOT IN (SELECT * FROM writing_owners)''')
        chosen=f' WHERE (kind,owner_id) IN (SELECT kind,owner_id FROM {batch})'
        old={r[0] for r in db.execute('SELECT DISTINCT value_id FROM material_search_custom'+chosen)}
        for table in ('material_search_custom','material_search_custom_deps','material_search_targets'):
            db.execute('DELETE FROM '+table+chosen)
        for kind in ('corpus','independent'):
            if kind=='corpus':
                owners="""CROSS JOIN corpus_sentence_keys e ON e.id=c.record_id CROSS JOIN texts t ON t.id=e.text_id"""
                language="COALESCE(NULLIF(e.language_id,''),t.language_id)"
                word="""LEFT JOIN corpus_units w ON w.id=c.unit_id AND w.entry_id=c.record_id
                    AND w.kind='word' AND w.active=1"""
                identity='w.id'
            else:
                owners='CROSS JOIN dictionary_examples e ON e.id=c.record_id'
                language='e.language_id'
                word='LEFT JOIN independent_words w ON w.example_id=c.record_id AND w.word_id=c.unit_id'
                identity='w.word_id'
            cells=db.execute(f'''SELECT c.record_id,'layer:'||c.layer_id field,
                    CASE WHEN l.anchor='word' THEN w.position ELSE -1 END word,c.value
                FROM {batch} d CROSS JOIN annotation_cells c ON c.owner_kind=d.kind AND c.record_id=d.owner_id
                {owners} JOIN annotation_layers l ON l.id=c.layer_id AND l.language_id={language}
                {word} WHERE d.kind=? AND l.source IS NOT 'dictionary' AND c.value<>''
                  AND ((l.anchor='word' AND {identity} IS NOT NULL) OR (l.anchor IS NOT 'word' AND c.unit_id=?))''',
                (kind,annotations.SENTENCE))
            def rows():
                for r in long_tasks.steps(cells):
                    vid=values.intern(r['value'])
                    old.discard(vid)
                    yield (kind,r['record_id'],r['field'],r['word'],vid,r['value'])
            db.executemany("INSERT OR IGNORE INTO material_search_custom VALUES(?,?,?,?,'cell',?,?)",rows())
        db.execute('DELETE FROM material_search_dirty'+chosen+' AND basic=0')
        db.execute('UPDATE material_search_dirty SET custom=0'+chosen)
        values.release(old)
    finally:
        db.execute(f'DROP TABLE IF EXISTS temp.{batch}')


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
    if not has_custom_recipe_queue(db):
        queue_custom_recipes(db,'SELECT DISTINCT d.kind,d.owner_id '+STALE_CUSTOM_RECIPES+scope)
    if not db.execute('SELECT 1 FROM material_search_dirty d WHERE custom=1'+scope+' LIMIT 1').fetchone():return
    derived_languages={r[0] for r in db.execute("SELECT DISTINCT language_id FROM annotation_layers WHERE source='dictionary'")}
    writing_languages={r[0] for r in db.execute('SELECT DISTINCT language_id FROM writing_types')}
    values=Values(db);cache=OrderedDict()
    if (record_sources.native(db) and not derived_languages and
            db.execute('SELECT 1 FROM material_search_dirty d WHERE custom=1'+scope+' LIMIT 1 OFFSET 199').fetchone()):
        refresh_manual_cells(db,scope,values)
    while batch:=db.execute('SELECT kind,owner_id FROM material_search_dirty d WHERE custom=1'+scope+' LIMIT 100').fetchall():
        bodies = {kind:record_sources.read_many(db,table,[row['owner_id'] for row in batch if row['kind']==kind])
                  for kind,table in (('corpus','entries'),('independent','dictionary_examples'))}
        for row in long_tasks.steps(batch):
            kind,rid=row['kind'],row['owner_id']
            source=db.execute('SELECT t.language_id FROM entries e JOIN texts t ON t.id=e.text_id WHERE e.id=?' if kind=='corpus' else 'SELECT language_id FROM dictionary_examples WHERE id=?',(rid,)).fetchone()
            old=[r[0] for r in db.execute('SELECT value_id FROM material_search_custom WHERE kind=? AND owner_id=?',(kind,rid))]
            for table in ('material_search_custom','material_search_custom_deps','material_search_targets'):
                db.execute('DELETE FROM '+table+' WHERE kind=? AND owner_id=?',(kind,rid))
            if source:
                body=bodies[kind][rid]
                language=(body.get('language_id') if kind=='corpus' else None) or source['language_id']
                dependent=language in derived_languages or kind=='independent' and language in writing_languages
                if dependent:body=gloss.load(db,kind,rid,body,metadata=False)
                if kind=='independent' and not dependent:
                    from independent_links import source_body
                    source_body(db,rid,body)
                entries,targets=custom_values(db,kind,rid,body,language,cache)
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


def custom_hits(db,field,query,case,mode,lid,details=False,*,blocks=False):
    import annotations
    if field.startswith(('layer:','writing:')) and field not in {f['id'] for f in annotations.search_catalog(db,lid)['fields']}:
        raise ValueError('自定义检索字段已删除或不属于当前语言，请重新选择')
    sql,args=Values(db).query(query,case,mode)
    columns='kind,owner_id id,word,field,value_id,display' if details else 'kind,owner_id id,word'
    table='material_search_custom'
    if blocks:
        table='sentence_hit_bits'
        columns='block,word,mask'
    if not query.strip():return 'SELECT '+columns+' FROM '+table+' WHERE 0',[]
    clauses=['value_id IN ('+sql+')']
    if blocks:clauses.append("family='custom'")
    if field.startswith(('layer:','writing:')):
        clauses.append('field=?');args.append(field)
    elif field=='layers':clauses.append("field LIKE 'layer:%'")
    elif field=='writings':clauses.append("field LIKE 'writing:%'")
    if not field.startswith('layer:'):
        clauses.append("(field NOT LIKE 'layer:%' OR substr(field,7) IN (SELECT id FROM annotation_layers WHERE searchable=1))")
    if lid!='all':
        clauses.append("(field LIKE 'layer:%' AND substr(field,7) IN (SELECT id FROM annotation_layers WHERE language_id=?) OR field LIKE 'writing:%' AND substr(field,9) IN (SELECT id FROM writing_types WHERE language_id=?))")
        args.extend([lid,lid])
    return 'SELECT '+columns+' FROM '+table+' WHERE '+' AND '.join(clauses),args


class Tracked:
    """Track referenced keys without copying the complete project catalog per document."""
    def __init__(self,source,prefix,seen):
        self.source=source
        self.prefix=prefix
        self.seen=seen

    def get(self,key,default=None):
        self.seen.add(self.prefix+str(key))
        return self.source.get(key,default)

    def __getitem__(self,key):
        self.seen.add(self.prefix+str(key))
        return self.source[key]

    def __contains__(self,key):
        self.seen.add(self.prefix+str(key))
        return key in self.source


def target_scope(kinds,lid):
    tables={'lexeme':'lexemes','morpheme':'morphemes'}
    where='' if lid=='all' else ' WHERE language_id=?'
    return ' UNION ALL '.join(f"SELECT '{kind}' kind,id FROM {tables[kind]}{where}" for kind in kinds), (
        () if lid=='all' else (lid,)*len(kinds))


def live_pairs(lid,kinds):
    targets,args=target_scope(kinds,lid)
    return f"""WITH targets AS MATERIALIZED ({targets})
      SELECT DISTINCT 'corpus',u.entry_id,l.lexeme_id FROM targets t
      CROSS JOIN lexical_links l ON l.lexeme_id=t.id CROSS JOIN corpus_units u ON u.id=l.unit_id
      UNION ALL SELECT DISTINCT 'independent',l.example_id,l.lexeme_id FROM targets t
      CROSS JOIN independent_links l ON l.lexeme_id=t.id JOIN dictionary_examples e ON e.id=l.example_id
      WHERE (?='all' OR e.language_id=?)""",(*args,lid,lid)

def linked_scope(db,lid,kinds):
    """Only build the reverse-pair projection for a scope with evidence."""
    targets,args=target_scope(kinds,lid)
    linked=db.execute(f"""WITH targets AS MATERIALIZED ({targets})
      SELECT 1 FROM targets t CROSS JOIN lexical_links l ON l.lexeme_id=t.id
      UNION ALL SELECT 1 FROM targets t CROSS JOIN independent_links l ON l.lexeme_id=t.id
      JOIN dictionary_examples e ON e.id=l.example_id WHERE (?='all' OR e.language_id=?) LIMIT 1""",(*args,lid,lid)).fetchone()
    if not linked:return 'SELECT NULL,NULL,NULL WHERE 0',()
    if not db.execute("SELECT 1 FROM sqlite_master WHERE name='evidence_owner_pairs'").fetchone():
        return live_pairs(lid,kinds)
    import evidence_owners
    evidence_owners.refresh(db)
    return f"""WITH targets AS MATERIALIZED ({targets})
      SELECT p.* FROM targets t CROSS JOIN evidence_owner_pairs p ON p.target_id=t.id
      WHERE p.kind='corpus' OR ?='all' OR EXISTS(
        SELECT 1 FROM dictionary_examples e WHERE e.id=p.id AND e.language_id=?)""",(*args,lid,lid)


def matching_targets(hits,args,lid,kinds,*,db=None):
    tables={'lexeme':'lexemes','morpheme':'morphemes'}
    queries=[];params=list(args)
    pairs=db is not None and db.execute("SELECT 1 FROM sqlite_master WHERE name='evidence_owner_pairs'").fetchone()
    if pairs:
        import evidence_owners
        evidence_owners.refresh(db)
    for kind in kinds:
        table=tables[kind]
        scope='' if lid=='all' else ' AND t.language_id=?'
        if pairs:
            queries.append(f"""SELECT DISTINCT '{kind}',t.id FROM hits h
                CROSS JOIN evidence_owner_pairs p ON p.kind=h.kind AND p.id=h.id
                CROSS JOIN {table} t ON t.id=p.target_id WHERE 1=1{scope}"""+
                (""" AND (p.kind='corpus' OR EXISTS(SELECT 1 FROM dictionary_examples e
                     WHERE e.id=p.id AND e.language_id=?))""" if lid!='all' else ''))
            if lid!='all':params.extend((lid,lid))
            continue
        queries.append(f"""SELECT '{kind}',t.id FROM hits h CROSS JOIN corpus_units u ON u.entry_id=h.id
          CROSS JOIN lexical_links l ON l.unit_id=u.id CROSS JOIN {table} t ON t.id=l.lexeme_id
          WHERE h.kind='corpus'{scope}""")
        queries.append(f"""SELECT '{kind}',t.id FROM hits h CROSS JOIN independent_links l ON l.example_id=h.id
          CROSS JOIN dictionary_examples e ON e.id=l.example_id CROSS JOIN {table} t ON t.id=l.lexeme_id
          WHERE h.kind='independent'{scope}"""+(' AND e.language_id=?' if lid!='all' else ''))
        if lid!='all':params.extend((lid,lid,lid))
    return f'WITH hits AS MATERIALIZED ({hits}) '+' UNION '.join(queries),params


class Evidence:
    def __init__(self,db,index,lid):
        self.db=db;self.index=weakref.proxy(index);self.context=getattr(index,'evidence_context',None) or type(index).__name__+':'+lid;self.values=Values(db);self.matches={}
        token=uuid.uuid4().hex
        self.owners_table='dictionary_query_owners_'+token
        self.docs_table='dictionary_query_docs_'+token
        self.records_table='dictionary_query_records_'+token
        if not db.in_transaction:db.execute('BEGIN')
        self.execute('CREATE TEMP TABLE dictionary_query_owners(kind TEXT,id TEXT,target_id TEXT,PRIMARY KEY(kind,id,target_id)) WITHOUT ROWID')
        self.execute('CREATE TEMP TABLE dictionary_query_records(kind TEXT,id TEXT,PRIMARY KEY(kind,id)) WITHOUT ROWID')
        kinds=getattr(index,'evidence_kinds',None)
        native=record_sources.native(db)
        if native and kinds:
            sql,args=linked_scope(db,lid,kinds)
            self.execute('INSERT INTO dictionary_query_owners '+sql,args)
        elif db.execute("SELECT 1 FROM sqlite_master WHERE name='evidence_owner_pairs'").fetchone():
            import evidence_owners
            evidence_owners.refresh(db)
            self.execute("""INSERT INTO dictionary_query_owners SELECT p.* FROM evidence_owner_pairs p
                WHERE p.kind='corpus' AND p.target_id IN (SELECT id FROM """+dictionary_targets.IDENTITIES+""" WHERE ?='all' OR language_id=?)
                UNION ALL SELECT p.* FROM evidence_owner_pairs p WHERE p.kind='independent'
                AND p.id IN (SELECT id FROM dictionary_examples WHERE ?='all' OR language_id=?)""",(lid,lid,lid,lid))
        else:
            self.execute('''INSERT OR IGNORE INTO dictionary_query_owners SELECT 'corpus',u.entry_id,l.lexeme_id FROM lexical_links l
              JOIN corpus_units u ON u.id=l.unit_id JOIN '''+dictionary_targets.IDENTITIES+''' t ON t.id=l.lexeme_id
              WHERE (?='all' OR t.language_id=?)''',(lid,lid))
            self.execute('''INSERT OR IGNORE INTO dictionary_query_owners SELECT 'independent',e.id,l.lexeme_id
              FROM independent_links l JOIN dictionary_examples e ON e.id=l.example_id WHERE (?='all' OR e.language_id=?)''',(lid,lid))
        self.execute('INSERT INTO dictionary_query_records SELECT DISTINCT kind,id FROM dictionary_query_owners')
        self.has_owners=bool(self.execute('SELECT 1 FROM dictionary_query_records LIMIT 1').fetchone())
        if self.has_owners:
            if native:
                with writing_cache(db):
                    words.refresh(db,owner_table=self.records_table,keys=False)
                    refresh_sources(db,owner_table=self.records_table)
                    self.sync_catalog()
                    self.prepare()
            else:
                refresh_custom(db,owner_table=self.records_table)
                self.sync_catalog()
                self.prepare()

    def execute(self, sql, params=()):
        sql=sql.replace('dictionary_query_owners',self.owners_table).replace('dictionary_query_docs',self.docs_table).replace('dictionary_query_records',self.records_table)
        return self.db.execute(sql,params)

    def sync_catalog(self):
        current={prefix+str(k):words.encode(v) for prefix,name in (('names:','names'),('tags:','tags'),('types:','types'),('people:','people')) for k,v in getattr(self.index,name).items()}
        previous={r['identifier']:r['value'] for r in self.execute('SELECT identifier,value FROM material_search_catalog WHERE context=?',(self.context,))}
        if current!=previous and self.db.execute("SELECT 1 FROM sqlite_master WHERE name='dictionary_catalog_tokens'").fetchone():
            self.db.execute('INSERT OR REPLACE INTO dictionary_catalog_tokens VALUES(?,randomblob(16))',(self.context,))
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
        cursor=('','')
        native=record_sources.native(self.db)
        while batch:=self.execute('''SELECT q.kind,q.id FROM dictionary_query_records q
          WHERE (q.kind,q.id)>(?,?) AND NOT EXISTS(SELECT 1 FROM material_search_records r WHERE r.context=? AND r.kind=q.kind AND r.owner_id=q.id) ORDER BY q.kind,q.id LIMIT 200''',(*cursor,self.context)).fetchall():
            cursor=tuple(batch[-1])
            if native:
                import sentence_rows
                headers={kind:sentence_rows.headers(self.db,kind,[row['id'] for row in batch if row['kind']==kind])
                         for kind in ('corpus','independent')}
            for row in long_tasks.steps(batch):
                table='entries' if row['kind']=='corpus' else 'dictionary_examples'
                body=headers[row['kind']].get(row['id']) if native else record_sources.read(self.db,table,row['id'])
                if body is not None:
                    body.pop('words',None)
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
                literal=getattr(self.index,'literal_projection',False)
                for name in ('names','tags','types','people'):
                    previous[name]=getattr(self.index,name);setattr(self.index,name,Tracked(previous[name],name+':',seen))
                try:
                    doc=self.index.document(dict(id='',headword='',body=json.loads(row['source'])),include_extra=False,
                        prefix=tuple(row['prefix'].split('.')),all_only=literal,field_catalog=None if literal else fields,
                        project=row['prefix']=='examples')
                finally:
                    for name,value in previous.items():setattr(self.index,name,value)
                old=[r[0] for r in self.execute('SELECT value_id FROM material_search_keys WHERE doc_id=?',(row['id'],))]
                self.execute('DELETE FROM material_search_keys WHERE doc_id=?',(row['id'],))
                keys=(('all',doc.get('all',())),) if literal else doc.items()
                self.db.executemany('INSERT OR IGNORE INTO material_search_keys VALUES(?,?,?)',[(row['id'],field,self.values.intern(text)) for field,texts in keys for text in texts if isinstance(text,str) and text.strip()])
                self.execute('DELETE FROM material_search_dependencies WHERE doc_id=?',(row['id'],))
                self.db.executemany('INSERT INTO material_search_dependencies VALUES(?,?,?)',[(self.context,key,row['id']) for key in seen])
                self.execute('UPDATE material_search_documents SET fields=?,classes=?,dirty=0 WHERE id=?',(words.encode(fields),words.encode(doc.get('_grammar_classes',[])),row['id']))
                self.values.release(old)
                long_tasks.checkpoint(None,'正在更新词典关联例证检索索引…')
        if not getattr(self.index,'literal_projection',False):
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
        hits,params=matching_records(self.values,self.context,field,op,value,case)
        query='SELECT DISTINCT q.target_id FROM ('+hits+') h JOIN dictionary_query_owners q ON q.kind=h.kind AND q.id=h.id'
        found={r[0] for r in self.execute(query,params)}
        self.matches[key]=found
        return found


def prepare_manual_values(db):
    """Index the text once. Layer and word-identity validity are checked live."""
    ready=db.execute('SELECT 1 FROM material_search_manual_state WHERE id=1').fetchone()
    if ready and not db.execute('SELECT 1 FROM material_search_manual_dirty LIMIT 1').fetchone():return
    values=Values(db)
    if not ready:
        rows=db.execute('SELECT id,value FROM annotation_cells ORDER BY rowid')
        db.executemany('INSERT INTO material_search_manual_values VALUES(?,?)',
                       ((key,values.intern(text)) for key,text in long_tasks.steps(rows) if text.strip()))
        db.execute('INSERT INTO material_search_manual_state VALUES(1)')
        return
    from itertools import islice
    pending=db.execute('''SELECT d.id,c.value,m.value_id FROM material_search_manual_dirty d
      LEFT JOIN annotation_cells c ON c.id=d.id LEFT JOIN material_search_manual_values m ON m.id=d.id''')
    released=set()
    while batch:=list(islice(pending,400)):
        inserts=[];deletes=[]
        for key,text,old in long_tasks.steps(batch):
            vid=values.intern(text) if text and text.strip() else None
            if vid==old:continue
            if old is not None:released.add(old)
            if vid is None:deletes.append((key,))
            else:inserts.append((key,vid))
        db.executemany('DELETE FROM material_search_manual_values WHERE id=?',deletes)
        db.executemany('INSERT OR REPLACE INTO material_search_manual_values VALUES(?,?)',inserts)
    db.execute('DELETE FROM material_search_manual_dirty')
    values.release(released)


def manual_hits(db,field,op,value,case,*,prepare=True):
    import annotations
    indexed=op in ('contains','exact','prefix','suffix','present') and record_sources.native(db)
    if (indexed and available(db)
            and not db.execute('SELECT 1 FROM material_search_dirty WHERE custom=1 LIMIT 1').fetchone()):
        sql,args=Values(db).query(value,case,op)
        scope=' AND p.field=?' if field.startswith('layer:') else ''
        return (f'''SELECT p.kind,p.owner_id FROM ({sql}) v JOIN projection_search_values pv ON pv.id=v.id
            CROSS JOIN material_search_custom p ON p.value_id=v.id WHERE pv.nonblank=1 AND p.origin='cell'{scope}''',
                [*args,*([field] if scope else [])])
    scope=' AND c.layer_id=?' if field.startswith('layer:') else ''
    args=(field.removeprefix('layer:'),) if scope else ()
    prefix=''
    if (prepare and indexed and db.execute("SELECT 1 FROM sqlite_master WHERE name='material_search_manual_state'").fetchone()):
        try:
            with preparing(db):
                prepare_manual_values(db)
            sql,parameters=Values(db).query(value,case,op)
            prefix=f'''WITH cells AS MATERIALIZED (SELECT c.* FROM ({sql}) v
              CROSS JOIN material_search_manual_values m ON m.value_id=v.id CROSS JOIN annotation_cells c ON c.id=m.id) '''
            common=f"FROM cells c JOIN annotation_layers l ON l.id=c.layer_id WHERE l.source IS NOT 'dictionary'{scope}"
        except Unavailable:
            prefix=''
    if not prefix:
        needle=corpus.normalize(value,case)
        def matches(text):
            if not text or not text.strip():return False
            text=corpus.normalize(text,case)
            if op=='present':return True
            if op=='exact':return text==needle
            if op=='prefix':return text.startswith(needle)
            if op=='suffix':return text.endswith(needle)
            return needle in text
        db.create_function('dictionary_layer_matches',1,matches,deterministic=True)
        common=f"""FROM annotation_cells c JOIN annotation_layers l ON l.id=c.layer_id
            WHERE l.source IS NOT 'dictionary' AND dictionary_layer_matches(c.value){scope}"""
        if not prepare and db.execute("SELECT 1 FROM sqlite_master WHERE name='annotation_source_value'").fetchone():
            prefix='''WITH source_values AS MATERIALIZED (SELECT DISTINCT value FROM annotation_cells INDEXED BY annotation_source_value),
                matched_values AS MATERIALIZED (SELECT value FROM source_values WHERE dictionary_layer_matches(value)), cells AS MATERIALIZED (SELECT c.* FROM matched_values v
                CROSS JOIN annotation_cells c INDEXED BY annotation_source_value ON c.value=v.value) '''
            parameters=[]
            common=f"FROM cells c JOIN annotation_layers l ON l.id=c.layer_id WHERE l.source IS NOT 'dictionary'{scope}"
    from independent_annotations import override_sql
    _,_,identity,_=override_sql(db)
    sql=f"""SELECT c.owner_kind,c.record_id {common}
       AND c.owner_kind='corpus' AND l.language_id=(
         SELECT COALESCE(NULLIF(s.language_id,''),t.language_id) FROM entries e JOIN texts t ON t.id=e.text_id
         JOIN sentence_text_rows s ON s.kind='corpus' AND s.owner_id=e.id WHERE e.id=c.record_id)
       AND ((l.anchor IS NOT 'word' AND c.unit_id=?) OR (l.anchor='word' AND EXISTS (
         SELECT 1 FROM corpus_units u WHERE u.id=c.unit_id AND u.entry_id=c.record_id AND u.kind='word' AND u.active=1)))
      UNION ALL SELECT c.owner_kind,c.record_id {common}
       AND c.owner_kind='independent' AND l.language_id=(SELECT language_id FROM dictionary_examples WHERE id=c.record_id)
       AND ((l.anchor IS NOT 'word' AND c.unit_id=?) OR (l.anchor='word' AND EXISTS (
         SELECT 1 FROM sentence_word_rows w LEFT JOIN independent_word_overrides o
            ON o.example_id=w.owner_id AND o.position=w.position WHERE w.kind='independent' AND w.owner_id=c.record_id
            AND c.unit_id=CASE WHEN o.position IS NULL THEN w.extra->>'$.annotation_id' ELSE {identity} END)))"""
    if prefix:
        return prefix+sql,[*parameters,*args,annotations.SENTENCE,*args,annotations.SENTENCE]
    return sql,[*args,annotations.SENTENCE,*args,annotations.SENTENCE]


def literal_values(index,body,prefix,project):
    values=index.document(dict(id='',headword='',body=body),include_extra=False,
                          prefix=prefix,project=project,all_only=True).get('all',())
    return tuple(corpus.normalize(value,True) for value in values if value.strip())


def invalidate_literal_dependencies(db,context,keys):
    for key in long_tasks.steps(keys):
        db.execute('''DELETE FROM material_search_literal_records WHERE context=? AND (kind,owner_id) IN (
            SELECT kind,owner_id FROM material_search_literal_dependencies WHERE context=? AND key=?)''',(context,context,key))


def literal_records(db,build_index,context,lid,kinds,catalog,generation):
    """Build only missing literal evidence rows, independently of field indexes."""
    from functools import lru_cache
    from itertools import islice
    import sentence_rows

    prior=db.execute('SELECT token,generation FROM material_search_literal_state WHERE context=?',(context,)).fetchone()
    incremental=catalog==LITERAL_DEPENDENCY_TOKEN
    if not incremental and prior and tuple(prior)==(catalog,generation):return
    dirty=incremental and prior and prior[0]==catalog
    if dirty:
        if not db.execute('SELECT 1 FROM material_search_literal_dirty WHERE context=? LIMIT 1',(context,)).fetchone():return
        owners=iter(dirty_literal_owners(db,context,lid,kinds))
    else:
        if prior and prior[0]!=catalog:
            db.execute('DELETE FROM material_search_literal_records WHERE context=?',(context,))
        sql,args=linked_scope(db,lid,kinds)
        owners=iter(db.execute(f'''WITH q(kind,id,target_id) AS ({sql}) SELECT DISTINCT q.kind,q.id FROM q
            WHERE NOT EXISTS (SELECT 1 FROM material_search_literal_records r
                WHERE r.context=? AND r.kind=q.kind AND r.owner_id=q.id) ORDER BY q.kind,q.id''',(*args,context)))
    first=next(owners,None)
    if first is None:
        db.execute('INSERT OR REPLACE INTO material_search_literal_state VALUES(?,?,?)',(context,catalog,generation))
        if incremental:db.execute('DELETE FROM material_search_literal_dirty WHERE context=?',(context,))
        return
    index=build_index()
    seen=set()
    if incremental:
        for name in ('names','tags','types','people'):
            setattr(index,name,Tracked(getattr(index,name),name+':',seen))

    def pieces(body,prefix,project):
        seen.clear()
        values=literal_values(index,body,prefix,project)
        return values,frozenset(seen)

    @lru_cache(maxsize=512)
    def slot_values(form,value,extra,bindings):
        return pieces(words.effective_slot(form,value,extra,bindings),('examples','words'),False)

    from itertools import chain,groupby
    for kind,group in groupby(chain((first,),owners),key=lambda row:row[0]):
        ids=(row[1] for row in group)
        while batch:=list(islice(ids,200)):
            headers=sentence_rows.headers(db,kind,batch)
            values={};dependencies={}
            for rid,body in headers.items():
                found,keys=pieces(body,('examples',),True)
                values[rid]=set(found)
                if keys:dependencies[rid]=set(keys)
            for row,bindings in long_tasks.steps(words.effective_inputs(db,kind,list(values))):
                form,value,extra=row['form'],row['gloss'],row['extra']
                get=slot_values if len(form)+len(value)+len(extra)<16384 else slot_values.__wrapped__
                found,keys=get(form,value,extra,bindings)
                values[row['owner_id']].update(found)
                if keys:dependencies.setdefault(row['owner_id'],set()).update(keys)
            joined={rid:'\0'.join(sorted(terms)) for rid,terms in values.items()}
            db.executemany('INSERT INTO material_search_literal_records VALUES(?,?,?,?,?)',
                           ((context,kind,rid,text,text.casefold()) for rid,text in joined.items()))
            if incremental:
                db.executemany('INSERT OR IGNORE INTO material_search_literal_dependencies VALUES(?,?,?,?)',
                               ((context,key,kind,rid) for rid,keys in dependencies.items() for key in keys))
            long_tasks.checkpoint(None,'正在更新词典例证检索值…')
    db.execute('INSERT OR REPLACE INTO material_search_literal_state VALUES(?,?,?)',(context,catalog,generation))
    if incremental:db.execute('DELETE FROM material_search_literal_dirty WHERE context=?',(context,))


def dirty_literal_owners(db,context,lid,kinds):
    # Look up only dirty source identities. Joins start at the owner key,
    # including a sentence with a newly added association and no old posting.
    scope='' if lid=='all' else ' WHERE t.language_id=?'
    wanted=' UNION ALL '.join(f'SELECT 1 FROM links l CROSS JOIN {table} t ON t.id=l.lexeme_id'+scope
                             for target,table in (('lexeme','lexemes'),('morpheme','morphemes')) if target in kinds)
    params=() if lid=='all' else (lid,)*len(kinds)
    for kind in ('corpus','independent'):
        if kind=='corpus':
            source='''SELECT l.lexeme_id FROM corpus_units u CROSS JOIN lexical_links l ON l.unit_id=u.id
                      WHERE u.entry_id=d.owner_id'''
            args=()
        else:
            source='''SELECT l.lexeme_id FROM dictionary_examples e CROSS JOIN independent_links l ON l.example_id=e.id
                      WHERE e.id=d.owner_id'''
            args=() if lid=='all' else (lid,)
            if args:source+=' AND e.language_id=?'
        yield from db.execute(f'''SELECT d.kind,d.owner_id FROM material_search_literal_dirty d
            WHERE d.context=? AND d.kind=? AND NOT EXISTS(SELECT 1 FROM material_search_literal_records r
              WHERE r.context=d.context AND r.kind=d.kind AND r.owner_id=d.owner_id)
            AND EXISTS(WITH links AS MATERIALIZED ({source}) {wanted}) ORDER BY d.owner_id''',(context,kind,*args,*params))


def literal_targets(db,index,lid,kinds,query,case):
    """Evaluate ordinary all-field evidence against native headers and word slots."""
    from functools import lru_cache
    from itertools import islice
    import sentence_rows

    needle=corpus.normalize(query,case)
    def matches(body,prefix,project):
        values=index.document(dict(id='',headword='',body=body),include_extra=False,
                              prefix=prefix,project=project,all_only=True).get('all',())
        return any(text.strip() and needle in corpus.normalize(text,case) for text in values)

    @lru_cache(maxsize=512)
    def word_matches(form,gloss_value,extra,bindings):
        word=words.effective_slot(form,gloss_value,extra,bindings)
        return matches(word,('examples','words'),False)

    scope='dictionary_literal_owners_'+uuid.uuid4().hex
    hits='dictionary_literal_records_'+uuid.uuid4().hex
    db.execute(f'CREATE TEMP TABLE {scope}(kind TEXT,id TEXT,target_id TEXT,PRIMARY KEY(kind,id,target_id)) WITHOUT ROWID')
    db.execute(f'CREATE TEMP TABLE {hits}(kind TEXT,id TEXT,PRIMARY KEY(kind,id)) WITHOUT ROWID')
    try:
        sql,args=linked_scope(db,lid,kinds)
        db.execute(f'INSERT INTO {scope} '+sql,args)
        if not db.execute(f'SELECT 1 FROM {scope} LIMIT 1').fetchone():return set()
        layers,params=manual_hits(db,'all','contains',query,case)
        db.execute(f'''INSERT OR IGNORE INTO {hits} SELECT c.owner_kind,c.record_id FROM ({layers}) c
          WHERE EXISTS (SELECT 1 FROM {scope} q WHERE q.kind=c.owner_kind AND q.id=c.record_id)''',params)
        for kind in ('corpus','independent'):
            ids=(r[0] for r in db.execute(f'''SELECT DISTINCT q.id FROM {scope} q
              WHERE q.kind=? AND NOT EXISTS (SELECT 1 FROM {hits} h WHERE h.kind=q.kind AND h.id=q.id)
              ORDER BY q.id''',(kind,)))
            while batch:=list(islice(ids,200)):
                headers=sentence_rows.headers(db,kind,batch)
                found={rid for rid,body in headers.items() if matches(body,('examples',),True)}
                remaining=[rid for rid in batch if rid in headers and rid not in found]
                if remaining:
                    for row,bindings in long_tasks.steps(words.effective_inputs(db,kind,remaining)):
                        rid=row['owner_id']
                        if rid in found:continue
                        form,value,extra=row['form'],row['gloss'],row['extra']
                        match=word_matches if len(form)+len(value)+len(extra)<16384 else word_matches.__wrapped__
                        if match(form,value,extra,bindings):found.add(rid)
                db.executemany(f'INSERT INTO {hits} VALUES(?,?)',((kind,rid) for rid in found))
                long_tasks.checkpoint(None,'正在查找匹配的词典例证…')
        targets,args=target_scope(kinds,lid)
        return {tuple(row) for row in db.execute(f'''WITH targets AS MATERIALIZED ({targets})
            SELECT DISTINCT t.kind,t.id FROM {hits} h CROSS JOIN {scope} q ON q.kind=h.kind AND q.id=h.id
            JOIN targets t ON t.id=q.target_id''',args)}
    finally:
        db.execute(f'DROP TABLE IF EXISTS {hits}')
        db.execute(f'DROP TABLE IF EXISTS {scope}')


def matching_records(values,context,field,op,value,case):
    sql,args=values.query(value,case,op)
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
    params.extend([context,context])
    if field in ('all','examples') or field.startswith('layer:'):
        if record_sources.native(values.db):
            layer_query,layer_args=manual_hits(values.db,field,op,value,case)
            query+=' UNION SELECT * FROM ('+layer_query+')';params.extend(layer_args)
        else:
            query+=''' UNION SELECT c.kind,c.owner_id id FROM material_search_custom c
              WHERE c.origin='cell' AND c.value_id IN ('''+sql+')'
            params+=args
            if field.startswith('layer:'):query+=' AND c.field=?';params.append(field)
    return query+' ) SELECT kind,id FROM hits',params
