"""Incremental membership of dictionary examples and corpus references."""
import long_tasks

TABLES=('evidence_owner_pairs','evidence_owner_dirty')


def drop(db):
    for name, in db.execute("SELECT name FROM sqlite_master WHERE type='trigger' AND name GLOB 'evidence_owner_watch_*'").fetchall():
        db.execute('DROP TRIGGER "'+name.replace('"','""')+'"')
    for table in TABLES:db.execute('DROP TABLE IF EXISTS '+table)


def initialize(db):
    existed=db.execute("SELECT 1 FROM sqlite_master WHERE name='evidence_owner_pairs'").fetchone()
    db.executescript('''
        CREATE TABLE IF NOT EXISTS evidence_owner_pairs(kind TEXT,id TEXT,target_id TEXT,
          PRIMARY KEY(kind,id,target_id)) WITHOUT ROWID;
        CREATE INDEX IF NOT EXISTS evidence_target_records ON evidence_owner_pairs(target_id,kind,id);
        CREATE TABLE IF NOT EXISTS evidence_owner_dirty(kind TEXT,id TEXT,PRIMARY KEY(kind,id)) WITHOUT ROWID;
    ''')
    for event in ('INSERT','UPDATE','DELETE'):
        db.execute(f'DROP TRIGGER IF EXISTS evidence_owner_watch_dictionary_examples_{event}')
    for table in ('lexical_links','corpus_units','independent_links'):
        for event in ('INSERT','UPDATE','DELETE'):
            fields={'lexical_links':('unit_id','lexeme_id'),'corpus_units':('id','entry_id'),'independent_links':('example_id','lexeme_id')}[table]
            when=(' WHEN '+' OR '.join('OLD.'+k+' IS NOT NEW.'+k for k in fields)) if event=='UPDATE' else ''
            body=''
            for ref in (('OLD','NEW') if event=='UPDATE' else ('OLD',) if event=='DELETE' else ('NEW',)):
                kind='independent' if table=='independent_links' else 'corpus'
                src=(f'SELECT entry_id id FROM corpus_units WHERE id={ref}.unit_id' if table=='lexical_links' else
                     f'SELECT {ref}.entry_id id' if table=='corpus_units' else f'SELECT {ref}.example_id id')
                body+=f"""INSERT INTO evidence_owner_dirty SELECT '{kind}',s.id FROM ({src}) s
                    WHERE NOT EXISTS(SELECT 1 FROM evidence_owner_dirty d WHERE d.kind='{kind}' AND d.id=s.id);"""
            db.execute(f'CREATE TRIGGER IF NOT EXISTS evidence_owner_watch_{table}_{event} AFTER {event} ON {table}{when} BEGIN '+body+' END')
    if not existed:
        db.execute("INSERT INTO evidence_owner_dirty SELECT 'corpus',id FROM entries UNION ALL SELECT 'independent',id FROM dictionary_examples")


def refresh(db,kinds=('corpus','independent')):
    for kind in kinds:
        while batch:=db.execute('SELECT id FROM evidence_owner_dirty WHERE kind=? LIMIT 400',(kind,)).fetchall():
            ids=[r[0] for r in batch];marks=','.join('?' for _ in ids)
            db.execute(f'DELETE FROM evidence_owner_pairs WHERE kind=? AND id IN ({marks})',[kind,*ids])
            if kind=='corpus':
                sql=f"""SELECT DISTINCT 'corpus',u.entry_id,l.lexeme_id FROM corpus_units u
                        CROSS JOIN lexical_links l ON l.unit_id=u.id WHERE u.entry_id IN ({marks})"""
            else:
                sql=f"""SELECT DISTINCT 'independent',example_id,lexeme_id
                        FROM independent_links WHERE example_id IN ({marks})"""
            db.execute('INSERT INTO evidence_owner_pairs '+sql,ids)
            db.execute(f'DELETE FROM evidence_owner_dirty WHERE kind=? AND id IN ({marks})',[kind,*ids])
            long_tasks.checkpoint()


def independent_scope(db,target,lid=None,*,form_id='all'):
    predicate='lexeme_id=?';args=[target]
    if form_id=='unassigned':
        predicate+=' AND form_id IS NULL'
    elif form_id!='all':
        predicate+=' AND form_id=?';args.append(form_id)
    source=f' FROM (SELECT DISTINCT example_id FROM independent_links WHERE {predicate}) p CROSS JOIN dictionary_examples e ON e.id=p.example_id'
    where='1'
    if lid is not None:where+=' AND e.language_id=?';args.append(lid)
    return source+' WHERE '+where,args


def independent_ids(db,targets):
    """Resolve all affected owners in the current transaction, including dirty rows."""
    if not targets:return set()
    import lexicon
    rows=lexicon.scoped_rows(db,'SELECT DISTINCT example_id FROM independent_links',[('lexeme_id',targets)])
    return {row[0] for row in rows}
