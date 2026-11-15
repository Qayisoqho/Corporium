"""Rebuildable reverse dictionary relations, maintained for changed owners."""
import long_tasks
import material_search_index
import record_sources


def drop(db):
    for name, in db.execute("SELECT name FROM sqlite_master WHERE type='trigger' AND name GLOB 'dictionary_relation_*'").fetchall():
        db.execute('DROP TRIGGER "'+name.replace('"','""')+'"')
    db.execute('DROP TABLE IF EXISTS dictionary_relation_edges')
    db.execute('DROP TABLE IF EXISTS dictionary_relation_dirty')


def initialize(db):
    exists = db.execute("SELECT 1 FROM sqlite_master WHERE name='dictionary_relation_dirty'").fetchone()
    record_sources.schema_sql(db, '''
        CREATE TABLE IF NOT EXISTS dictionary_relation_edges(
          owner TEXT,target TEXT,PRIMARY KEY(owner,target)) WITHOUT ROWID;
        CREATE INDEX IF NOT EXISTS dictionary_relation_targets ON dictionary_relation_edges(target,owner);
        CREATE TABLE IF NOT EXISTS dictionary_relation_dirty(id TEXT PRIMARY KEY) WITHOUT ROWID;
    ''')
    for table in ('lexemes', 'morphemes'):
        for event in ('INSERT', 'UPDATE', 'DELETE'):
            references = ('OLD', 'NEW') if event=='UPDATE' else ('OLD',) if event=='DELETE' else ('NEW',)
            body = ''.join(f'''INSERT INTO dictionary_relation_dirty SELECT {ref}.id
              WHERE NOT EXISTS(SELECT 1 FROM dictionary_relation_dirty WHERE id={ref}.id);''' for ref in references)
            when = f' WHEN OLD.id IS NOT NEW.id OR {record_sources.change_sql(db,table)}' if event=='UPDATE' else ''
            record_sources.trigger(db,f'dictionary_relation_{table}_{event}',f'AFTER {event} ON {table}{when} BEGIN {body} END')
    if not exists:
        db.execute('INSERT INTO dictionary_relation_dirty SELECT id FROM lexemes UNION SELECT id FROM morphemes')


def component_edges(db,kind,condition,args,*,by_target=False):
    """Read owner/target pairs from the ordered component path."""
    # Reverse lookups must start at the indexed reference. Each parent is then one primary-key read.
    index=' INDEXED BY dictionary_component_reference' if by_target else ''
    join='CROSS JOIN' if by_target else 'JOIN'
    return db.execute(f"""SELECT DISTINCT link.target_id,link.value FROM dictionary_value_rows link{index}
      {join} dictionary_value_rows component ON component.target_kind=link.target_kind
        AND component.target_id=link.target_id AND component.node=link.parent AND component.value_type='object'
      {join} dictionary_value_rows parts ON parts.target_kind=link.target_kind AND parts.target_id=link.target_id
        AND parts.node=component.parent AND parts.slot='components' AND parts.value_type='array'
      {join} dictionary_value_rows analysis ON analysis.target_kind=link.target_kind AND analysis.target_id=link.target_id
        AND analysis.node=parts.parent AND analysis.value_type='object'
      {join} dictionary_value_rows analyses ON analyses.target_kind=link.target_kind AND analyses.target_id=link.target_id
        AND analyses.node=analysis.parent AND analyses.slot='analyses' AND analyses.value_type='array'
      {join} dictionary_value_rows structure ON structure.target_kind=link.target_kind AND structure.target_id=link.target_id
        AND structure.node=analyses.parent AND structure.slot='word_structure' AND structure.parent=0
        AND structure.value_type='object'
      WHERE link.target_kind=? AND link.slot='lexeme_id' AND link.value_type='text' AND link.value<>'' AND """+condition,
        (kind,*args))


def native_edges(db,kind,ids,marks):
    components=component_edges(db,kind,'link.target_id IN ('+marks+')',ids)
    base=db.execute("""SELECT link.target_id,link.value FROM dictionary_value_rows link
      JOIN dictionary_value_rows relation ON relation.target_kind=link.target_kind AND relation.target_id=link.target_id
        AND relation.node=link.parent AND relation.slot='relation' AND relation.parent=0 AND relation.value_type='object'
      WHERE link.target_kind=? AND link.slot='base_id' AND link.value_type='text' AND link.value<>''
        AND link.target_id IN ("""+marks+')',(kind,*ids))
    return {tuple(row) for source in (components,base) for row in source}


def component_owners(db,targets):
    """Find incoming component selections in the current write transaction."""
    owners=set()
    targets=list(targets)
    for start in range(0,len(targets),400):
        batch=targets[start:start+400]
        marks=','.join('?' for _ in batch)
        for kind in ('lexeme','morpheme'):
            owners.update(row[0] for row in component_edges(db,kind,'link.value IN ('+marks+')',batch))
    return owners


def refresh(db):
    import dictionary_rows
    while rows := db.execute('SELECT id FROM dictionary_relation_dirty LIMIT 400').fetchall():
        ids = [row[0] for row in rows]
        marks = ','.join('?' for _ in ids)
        db.execute('DELETE FROM dictionary_relation_edges WHERE owner IN ('+marks+')', ids)
        links = set()
        for kind in ('lexeme','morpheme'):
            if record_sources.native(db):
                links.update(native_edges(db,kind,ids,marks))
                continue
            for owner, body in dictionary_rows.raw_bodies(db,kind,ids).items():
                relation = body.get('relation')
                relation = relation.get('base_id') if isinstance(relation,dict) else None
                if isinstance(relation,str) and relation:
                    links.add((owner,relation))
                structure=body.get('word_structure')
                analyses=structure.get('analyses') if isinstance(structure,dict) else None
                for analysis in analyses if isinstance(analyses,list) else ():
                    components=analysis.get('components') if isinstance(analysis,dict) else None
                    for component in components if isinstance(components,list) else ():
                        target=component.get('lexeme_id') if isinstance(component,dict) else None
                        if isinstance(target,str) and target:
                            links.add((owner,target))
        db.executemany('INSERT INTO dictionary_relation_edges VALUES(?,?)',sorted(links))
        db.execute('DELETE FROM dictionary_relation_dirty WHERE id IN ('+marks+')', ids)
        long_tasks.checkpoint()


def ready(db):
    if not db.execute("SELECT 1 FROM sqlite_master WHERE name='dictionary_relation_dirty'").fetchone():
        return False
    try:
        with material_search_index.preparing(db):
            refresh(db)
        return True
    except material_search_index.Unavailable:
        return False
