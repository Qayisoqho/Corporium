"""Small, bounded process caches identified by a transactional SQLite token."""
from collections import OrderedDict
from contextlib import contextmanager
from threading import RLock

STATISTICS_TABLES=('entries','dictionary_examples','texts','lexemes','morphemes','languages',
                   'corpus_units','lexical_links','morphology_analyses','component_links',
                   'morpheme_components','lexical_reviews','independent_links','independent_word_overrides')
ASSOCIATION_TABLES=('lexical_links','independent_links','gloss_bindings','morphology_analyses','dictionary_examples')
ASSOCIATION_DOMAINS=('home','content','basic_hits','word_hits','grammar_usage','dictionary','statistics')

class Cache:
    def __init__(self, limit):
        self.limit = limit
        self.size = 0
        self.items = OrderedDict()
        self.lock = RLock()

    def get(self, key):
        with self.lock:
            if key in self.items:
                self.items.move_to_end(key)
                return self.items[key][0]

    def put(self, key, value, cost):
        if key is None or cost > self.limit:
            return
        with self.lock:
            old = self.items.pop(key,None)
            if old:
                self.size -= old[1]
            while self.items and (self.size+cost > self.limit or len(self.items)>=512):
                self.size -= self.items.popitem(last=False)[1][1]
            self.items[key] = (value,cost)
            self.size += cost


def initialize(db):
    import journal
    import record_sources
    db.execute('CREATE TABLE IF NOT EXISTS read_view_tokens(domain TEXT PRIMARY KEY,token BLOB NOT NULL)')
    db.execute('CREATE TABLE IF NOT EXISTS read_view_association_batch(id INTEGER PRIMARY KEY CHECK(id=1))')
    domains = {
        'home': ('entries','texts','dictionary_examples','languages'),
        'content': ('lexemes','morphemes','category_classes','semantic_classes','grammar_tags','writing_types','timeline_speakers','annotation_layers','languages','object_media','timeline_media','entries','dictionary_examples','texts','text_info','corpus_units','unit_segments','lexical_links','morphology_analyses','component_links','morpheme_components','lexical_reviews','annotation_cells','gloss_bindings','gloss_meanings'),
        'basic_hits': ('entries','dictionary_examples','text_info'),
        'word_hits': ('entries','dictionary_examples','text_info','gloss_bindings','gloss_meanings','corpus_units','unit_segments','morphology_analyses','lexical_links'),
        'scope': ('entries','texts','dictionary_examples','code_sentence_index'),
        'homophones': ('lexemes','morphemes','morpheme_components'),
        'analysis': ('analysis_state','analysis_runs','analysis_saved'),
        'timeline_extent': ('timeline_intervals',),
        'grammar_usage': ('entries','dictionary_examples','texts','gloss_bindings','gloss_meanings','corpus_units','unit_segments'),
        'own': ('lexemes','morphemes','category_classes','semantic_classes','grammar_tags','writing_types','timeline_speakers','annotation_layers','languages'),
        'dictionary': (*journal.TABLES,'example_numbers','code_sentence_index'),
        'statistics': STATISTICS_TABLES,
    }
    for domain in ('home','content','word_hits','grammar_usage'):
        domains[domain]+= ('independent_links','independent_word_overrides')
    tables = {r[0] for r in db.execute("SELECT name FROM sqlite_master WHERE type='table'")}
    expected=set()
    for domain, dependencies in domains.items():
        db.execute('INSERT OR IGNORE INTO read_view_tokens VALUES(?,randomblob(16))',(domain,))
        for table in set(dependencies) & tables:
            for event in ('INSERT','UPDATE','DELETE'):
                name=f'read_view_{domain}_{table}_{event}'
                expected.add(name)
                when=''
                if event=='UPDATE' and domain=='timeline_extent':
                    when=' WHEN OLD.session_id IS NOT NEW.session_id OR OLD.start_ms IS NOT NEW.start_ms OR OLD.end_ms IS NOT NEW.end_ms'
                if event=='UPDATE' and domain=='scope' and table in ('entries','dictionary_examples'):
                    cols=('id','text_id','position') if table=='entries' else ('id','language_id')
                    changed=[f'OLD.{c} IS NOT NEW.{c}' for c in ('rowid',*cols)]
                    fields=[f"json_extract(OLD.body,'$.{k}') IS NOT json_extract(NEW.body,'$.{k}')" for k in ('language_id','grammaticality')]
                    changed.append(record_sources.change_sql(db,table,record_sources.SCOPE,' OR '.join(fields)))
                    when=' WHEN '+' OR '.join(changed)
                if event=='UPDATE' and table=='languages' and domain in ('own','content'):
                    when=""" WHEN OLD.id IS NOT NEW.id OR OLD.name IS NOT NEW.name OR
                         json_remove(OLD.metadata,'$.homophone_phonology') IS NOT json_remove(NEW.metadata,'$.homophone_phonology')"""
                if event=='UPDATE' and domain=='statistics' and table in ('entries','dictionary_examples','lexemes','morphemes'):
                    columns={'entries':('id','text_id','position'), 'dictionary_examples':('id','language_id'),
                             'lexemes':('id','language_id','headword'), 'morphemes':('id','language_id','form','number')}[table]
                    changed=[f'OLD.{column} IS NOT NEW.{column}' for column in ('rowid',*columns)]
                    fields="'$.notes','$.translation','$.ipa','$.language_notes'" if table in ('entries','dictionary_examples') else "'$.notes'"
                    changed.append(record_sources.change_sql(db,table,record_sources.STATISTICS,
                        f'CASE WHEN OLD.body IS NOT NEW.body THEN json_remove(OLD.body,{fields}) IS NOT json_remove(NEW.body,{fields}) ELSE 0 END'))
                    when=' WHEN '+' OR '.join(changed)
                    if table=='lexemes':
                        structure = record_sources.change_sql(db,table,record_sources.STRUCTURE,
                            "json_extract(OLD.body,'$.word_structure') IS NOT json_extract(NEW.body,'$.word_structure')")
                        when=f' WHEN OLD.id IS NOT NEW.id OR OLD.language_id IS NOT NEW.language_id OR {structure}'
                if event=='UPDATE' and domain=='statistics' and table=='languages':
                    when=""" WHEN OLD.id IS NOT NEW.id OR
                      json_extract(OLD.metadata,'$.grammaticality_types') IS NOT json_extract(NEW.metadata,'$.grammaticality_types')"""
                batchable=table in ASSOCIATION_TABLES and domain in ASSOCIATION_DOMAINS
                if batchable:
                    conditions='NOT EXISTS(SELECT 1 FROM read_view_association_batch WHERE id=1)'
                    when=' WHEN '+conditions+(' AND ('+when[6:]+')' if when else '')
                sql=f"""CREATE TRIGGER {name} AFTER {event} ON {table}{when} BEGIN
                    UPDATE read_view_tokens SET token=randomblob(16) WHERE domain='{domain}'; END"""
                prior=db.execute("SELECT sql FROM sqlite_master WHERE type='trigger' AND name=?",(name,)).fetchone()
                if prior and prior[0]==sql:continue
                if prior:db.execute('DROP TRIGGER '+name)
                db.execute(sql)
                db.execute('UPDATE read_view_tokens SET token=randomblob(16) WHERE domain=?',(domain,))
    for name, in db.execute("SELECT name FROM sqlite_master WHERE type='trigger' AND name GLOB 'read_view_*'").fetchall():
        if name not in expected:
            db.execute('DROP TRIGGER "'+name.replace('"','""')+'"')


def association_batch_ready(db):
    return db.execute("SELECT 1 FROM sqlite_master WHERE name='read_view_association_batch'").fetchone() is not None


def upgrade(db):
    if association_batch_ready(db):return
    import save_validation
    prior=save_validation.snapshot(db)
    initialize(db)
    save_validation.initialize(db,prior)


@contextmanager
def association_batch(db):
    """Publish token changes once per bounded, single-writer association batch."""
    if not association_batch_ready(db):
        yield
        return
    db.execute('SAVEPOINT read_view_batch')
    try:
        db.execute('INSERT INTO read_view_association_batch VALUES(1)')
        yield
        db.execute('DELETE FROM read_view_association_batch WHERE id=1')
        db.execute('UPDATE read_view_tokens SET token=randomblob(16) WHERE domain IN ('+
                   ','.join('?' for _ in ASSOCIATION_DOMAINS)+')',ASSOCIATION_DOMAINS)
    except BaseException:
        # The enclosing connection rolls back on cancellation, including this
        # marker. In ordinary exceptions clear it even if the caller catches one.
        if db.in_transaction:
            import long_tasks
            if long_tasks.CURRENT.get() is not None:db.set_progress_handler(None,0)
            db.execute('ROLLBACK TO read_view_batch')
            db.execute('RELEASE read_view_batch')
        raise
    db.execute('RELEASE read_view_batch')


def token(db, domain):
    if not db.in_transaction:
        db.execute('BEGIN')
    import sqlite3
    try:
        row = db.execute('SELECT token FROM read_view_tokens WHERE domain=?',(domain,)).fetchone()
    except sqlite3.OperationalError as exc:
        if 'no such table' not in str(exc):raise
        return None
    return row[0] if row else None


def preserve_sentence_statistics(db, prior, changes):
    """Final-row proof for normal sentence editors and captured undo/redo rows.

    Their validation can temporarily drop and restore derived display fields.
    Capture includes physical rowids. External SQL, net insert/delete, moved
    rowids and structural edits keep normal invalidation.
    The caller owns an IMMEDIATE transaction throughout the proof and commit.
    """
    if prior is None:return
    import record_sources
    ignored=('notes','translation','ipa','language_notes')
    for (table,_),(before,after) in changes.items():
        if table not in STATISTICS_TABLES or before==after:continue
        if table not in ('entries','dictionary_examples') or before is None or after is None:return
        if {k:v for k,v in before.items() if k!='revision'}=={k:v for k,v in after.items() if k!='revision'}:continue
        def source(value):
            value={k:v for k,v in value.items() if k!='revision'}
            body=dict(record_sources.body(value,mutable=False))
            for field in ignored:body.pop(field,None)
            value['body']=body
            return value
        if source(before)!=source(after):return
    db.execute("UPDATE read_view_tokens SET token=? WHERE domain='statistics' AND token IS NOT ?",(prior,prior))


def drop(db):
    for name, in db.execute("SELECT name FROM sqlite_master WHERE type='trigger' AND name GLOB 'read_view_*'").fetchall():
        db.execute('DROP TRIGGER "'+name.replace('"','""')+'"')
    db.execute('DROP TABLE IF EXISTS read_view_tokens')
    db.execute('DROP TABLE IF EXISTS read_view_association_batch')
