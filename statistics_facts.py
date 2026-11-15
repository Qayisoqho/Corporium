"""Source-local vocabulary facts and active-reference totals for corpus counts."""
import json
import record_sources
from collections import defaultdict
from contextlib import nullcontext

import long_tasks
import material_search_index


VERSION = 2
TABLES = ('statistics_fact_dependencies','statistics_reference_links','statistics_reference_totals',
          'statistics_record_facts','statistics_fact_dirty','statistics_fact_state')


def drop(db):
    for name, in db.execute("SELECT name FROM sqlite_master WHERE type='trigger' AND name GLOB 'statistics_fact_*'").fetchall():
        db.execute('DROP TRIGGER "'+name.replace('"','""')+'"')
    for table in TABLES:
        db.execute('DROP TABLE IF EXISTS '+table)


def initialize(db):
    exists = db.execute("SELECT 1 FROM sqlite_master WHERE name='statistics_fact_state'").fetchone()
    if exists and db.execute('SELECT version FROM statistics_fact_state').fetchone()[0] != VERSION:
        drop(db)
        exists = False
    record_sources.schema_sql(db, '''
        CREATE TABLE IF NOT EXISTS statistics_fact_state(version INTEGER);
        CREATE TABLE IF NOT EXISTS statistics_fact_dirty(kind TEXT,id TEXT,PRIMARY KEY(kind,id)) WITHOUT ROWID;
        CREATE TABLE IF NOT EXISTS statistics_record_facts(
          kind TEXT,id TEXT,text_id TEXT,owner_language TEXT,position INTEGER,source_rowid INTEGER,data TEXT,
          PRIMARY KEY(kind,id)) WITHOUT ROWID;
        CREATE INDEX IF NOT EXISTS statistics_fact_text ON statistics_record_facts(kind,text_id,position,id);
        CREATE INDEX IF NOT EXISTS statistics_fact_language ON statistics_record_facts(kind,owner_language,source_rowid,id);
        CREATE TABLE IF NOT EXISTS statistics_fact_dependencies(
          kind TEXT,id TEXT,target TEXT,PRIMARY KEY(kind,id,target)) WITHOUT ROWID;
        CREATE INDEX IF NOT EXISTS statistics_fact_targets ON statistics_fact_dependencies(target,kind,id);
        CREATE TABLE IF NOT EXISTS statistics_reference_links(id TEXT PRIMARY KEY,entry_id TEXT,language_id TEXT);
        CREATE INDEX IF NOT EXISTS statistics_fact_reference_owner ON statistics_reference_links(entry_id,id);
        CREATE TABLE IF NOT EXISTS statistics_reference_totals(
          entry_id TEXT,language_id TEXT,n INTEGER,PRIMARY KEY(entry_id,language_id)) WITHOUT ROWID;
        CREATE TRIGGER IF NOT EXISTS statistics_fact_reference_add AFTER INSERT ON statistics_reference_links BEGIN
          INSERT INTO statistics_reference_totals VALUES(NEW.entry_id,NEW.language_id,1)
            ON CONFLICT(entry_id,language_id) DO UPDATE SET n=n+1;
        END;
        CREATE TRIGGER IF NOT EXISTS statistics_fact_reference_remove AFTER DELETE ON statistics_reference_links BEGIN
          UPDATE statistics_reference_totals SET n=n-1 WHERE entry_id=OLD.entry_id AND language_id=OLD.language_id;
          DELETE FROM statistics_reference_totals WHERE entry_id=OLD.entry_id AND language_id=OLD.language_id AND n=0;
        END;
    ''')
    def dirty(select):
        return '''INSERT INTO statistics_fact_dirty SELECT s.kind,s.id FROM ('''+select+''') s
          WHERE NOT EXISTS(SELECT 1 FROM statistics_fact_dirty d WHERE d.kind=s.kind AND d.id=s.id);'''
    for table in ('entries','dictionary_examples','corpus_units','lexical_links','component_links',
                  'morphology_analyses','lexical_reviews','lexemes','morphemes','morpheme_components','texts',
                  'independent_links','independent_word_overrides'):
        for event in ('INSERT','UPDATE','DELETE'):
            body = ''
            refs = ('OLD','NEW') if event=='UPDATE' else ('OLD',) if event=='DELETE' else ('NEW',)
            for ref in refs:
                if table in ('entries','dictionary_examples'):
                    kind = 'corpus' if table=='entries' else 'independent'
                    select = f"SELECT '{kind}' kind,{ref}.id id"
                elif table in ('independent_links','independent_word_overrides'):
                    select = f"SELECT 'independent' kind,{ref}.example_id id"
                elif table=='corpus_units':
                    select = f"SELECT 'corpus' kind,{ref}.entry_id id"
                elif table=='lexical_links':
                    select = f"SELECT 'corpus' kind,entry_id id FROM corpus_units WHERE id={ref}.unit_id"
                elif table in ('component_links','morphology_analyses','lexical_reviews'):
                    select = f"SELECT 'corpus' kind,u.entry_id id FROM lexical_links l JOIN corpus_units u ON u.id=l.unit_id WHERE l.id={ref}.id"
                elif table=='texts':
                    select = f"SELECT 'corpus' kind,id FROM entries WHERE text_id={ref}.id"
                else:
                    target = ref+'.lexeme_id' if table=='morpheme_components' else ref+'.id'
                    select = 'SELECT kind,id FROM statistics_fact_dependencies WHERE target='+target
                body += dirty(select)
            when = ''
            if event=='UPDATE' and table in ('entries','dictionary_examples','lexemes','morphemes'):
                fields = {'entries':('id','text_id','position'), 'dictionary_examples':('id','language_id'),
                          'lexemes':('id','language_id','headword'), 'morphemes':('id','language_id','form','number')}[table]
                changed = [f'OLD.{field} IS NOT NEW.{field}' for field in ('rowid',*fields)]
                omitted = "'$.notes','$.translation','$.ipa','$.language_notes'" if table in ('entries','dictionary_examples') else "'$.notes'"
                changed.append(record_sources.change_sql(db,table,record_sources.STATISTICS,
                    f'CASE WHEN OLD.body IS NOT NEW.body THEN json_remove(OLD.body,{omitted}) IS NOT json_remove(NEW.body,{omitted}) ELSE 0 END'))
                when = ' WHEN '+' OR '.join(changed)
                if table=='lexemes':
                    structure = record_sources.change_sql(db,table,record_sources.STRUCTURE,
                        "json_extract(OLD.body,'$.word_structure') IS NOT json_extract(NEW.body,'$.word_structure')")
                    when=f' WHEN OLD.id IS NOT NEW.id OR OLD.language_id IS NOT NEW.language_id OR {structure}'
            if event=='UPDATE' and table=='texts':
                when = ' WHEN OLD.id IS NOT NEW.id OR OLD.language_id IS NOT NEW.language_id'
            name = f'statistics_fact_{table}_{event}'
            sql = f'CREATE TRIGGER {name} AFTER {event} ON {table}{when} BEGIN {body} END'
            previous = db.execute("SELECT sql FROM sqlite_master WHERE type='trigger' AND name=?",(name,)).fetchone()
            if previous and previous[0]!=sql:
                db.execute('DROP TRIGGER '+name)
            if not previous or previous[0]!=sql:
                db.execute(sql)
    if not exists:
        db.execute('INSERT INTO statistics_fact_state VALUES(?)',(VERSION,))
        db.execute("INSERT INTO statistics_fact_dirty SELECT 'corpus',id FROM entries UNION ALL SELECT 'independent',id FROM dictionary_examples")


def ready(db):
    if not db.execute("SELECT 1 FROM sqlite_master WHERE name='statistics_fact_state'").fetchone():
        return False
    try:
        with material_search_index.preparing(db):
            prepare(db)
        return True
    except material_search_index.Unavailable:
        return False
    except (ValueError,KeyError,TypeError):
        # The original scope reader owns diagnostics for malformed legacy
        # records; a damaged page elsewhere must not block a smaller scope.
        return False


def prepare(db):
    pending=db.execute('SELECT count(*) FROM (SELECT 1 FROM statistics_fact_dirty LIMIT 401)').fetchone()[0]
    if not pending:
        return
    with material_search_index.writing_cache(db) if pending>400 else nullcontext():
        _prepare(db)


def _prepare(db):
    from vocabulary_statistics import Collector
    from corpus_statistics import WordCounter
    import mpw_statistics
    collector = Collector(db)
    counter = WordCounter()
    mpw = mpw_statistics.Counter(counter)
    for kind, table in (('corpus','entries'), ('independent','dictionary_examples')):
        sequential = not db.execute('SELECT 1 FROM statistics_record_facts WHERE kind=? LIMIT 1',(kind,)).fetchone()
        last_row = None
        while True:
            if sequential:
                where = '' if last_row is None else ' WHERE rowid>?'
                params = () if last_row is None else (last_row,)
                batch = db.execute(f'SELECT id,rowid FROM {table}'+where+' ORDER BY rowid LIMIT 400',params).fetchall()
                if not batch:
                    sequential = False
                    continue
                last_row = batch[-1]['rowid']
            else:
                batch = db.execute('SELECT id FROM statistics_fact_dirty WHERE kind=? LIMIT 400',(kind,)).fetchall()
            if not batch:
                break
            ids = [row[0] for row in batch]
            marks = ','.join('?' for _ in ids)
            db.execute('DELETE FROM statistics_record_facts WHERE kind=? AND id IN ('+marks+')',[kind,*ids])
            db.execute('DELETE FROM statistics_fact_dependencies WHERE kind=? AND id IN ('+marks+')',[kind,*ids])
            if kind=='corpus':
                dependencies=defaultdict(set)
                for link in db.execute('''SELECT u.entry_id,l.lexeme_id FROM corpus_units u
                  CROSS JOIN lexical_links l ON l.unit_id=u.id WHERE u.entry_id IN ('''+marks+')',ids):
                    dependencies[link['entry_id']].add(link['lexeme_id'])
                db.execute('DELETE FROM statistics_reference_links WHERE entry_id IN ('+marks+')',ids)
                db.execute('''INSERT INTO statistics_reference_links SELECT l.id,u.entry_id,x.language_id
                  FROM corpus_units u CROSS JOIN lexical_links l ON l.unit_id=u.id
                  JOIN lexemes x ON x.id=l.lexeme_id JOIN entries e ON e.id=u.entry_id
                  WHERE u.active=1 AND u.entry_id IN ('''+marks+')',ids)
                collector.load_batch(ids)
                sql = '''SELECT e.id,e.text_id,e.position,e.rowid source_rowid,t.language_id
                  FROM entries e JOIN texts t ON t.id=e.text_id WHERE e.id IN ('''+marks+')'
            else:
                sql = 'SELECT id,NULL text_id,rowid position,rowid source_rowid,language_id FROM dictionary_examples WHERE id IN ('+marks+')'
            records=record_sources.with_bodies(db,'entries' if kind=='corpus' else 'dictionary_examples',db.execute(sql,ids))
            for row in long_tasks.steps(records):
                body = row['body']
                if kind=='independent':
                    from independent_links import source_body
                    source_body(db,row['id'],body)
                language = body.get('language_id') or row['language_id']
                rid = 'independent:'+row['id'] if kind=='independent' else row['id']
                collector.hits.clear();collector.forms.clear();collector.morphemes.clear()
                collector.row_types.clear();collector.morpheme_words.clear();collector.root_words.clear()
                count = collector.record(rid,body,language,row['text_id'],counter)
                morphemes = [{**{k:r[k] for k in ('key','id','form','gloss','kind','count')},'indices':sorted(r['indices'])}
                             for r in collector.morphemes.values()]
                values = mpw.record(body.get('words',[]))
                facts = dict(words=[[h['word'],h['form']] for h in collector.hits],morphemes=morphemes,
                             excluded=len(body.get('words',[]))-count,language_id=language,
                             grammaticality=body.get('grammaticality',''),targets=bool(body.get('targets')),
                             mpw=[values[k] for k in ('morphemes','word_slots','clitic_words')])
                db.execute('INSERT INTO statistics_record_facts VALUES(?,?,?,?,?,?,?)',
                           (kind,row['id'],row['text_id'],row['language_id'],row['position'],row['source_rowid'],
                            json.dumps(facts,ensure_ascii=False,separators=(',',':'))))
                targets = {r['id'] for r in morphemes}
                if kind=='corpus':targets.update(dependencies[row['id']])
                else:targets.update(link.get('lexeme_id') for link in body.get('targets',[]))
                db.executemany('INSERT INTO statistics_fact_dependencies VALUES(?,?,?)',
                               ((kind,row['id'],target) for target in targets if target))
            db.execute('DELETE FROM statistics_fact_dirty WHERE kind=? AND id IN ('+marks+')',[kind,*ids])
