"""Retire editorial status flags without losing explicit research reservations.

Only dictionary/annotation records are affected. Phonology adoption, timeline
alignment and survey workflows deliberately retain their own state machines.
"""
import json
import undo_codec

MARKER='manual-status-retired-v1'
BODY_TABLES={'lexemes','morphemes','morpheme_components','component_links',
             'entries','dictionary_examples','unit_segments','history'}
COLUMN_TABLES={'lexical_links','morpheme_components'}
DISPUTED_NOTE='旧记录标记：有争议。'

def clean(value):
    if isinstance(value,list):return [clean(v) for v in value]
    if not isinstance(value,dict):return value
    result={k:clean(v) for k,v in value.items() if k!='status'}
    if value.get('status')=='disputed':
        notes=result.get('notes','')
        if DISPUTED_NOTE not in notes:result['notes']=(notes+'\n'+DISPUTED_NOTE).strip()
    return result

def row(table,value):
    if value is None:return None
    value=dict(value)
    if table in BODY_TABLES and value.get('body'):
        original=json.loads(value['body']);updated=clean(original)
        if table in COLUMN_TABLES and value.get('status')=='disputed':
            updated=clean({**updated,'status':'disputed'})
        if updated!=original:value['body']=json.dumps(updated,ensure_ascii=False)
    if table=='lexical_links' and value.get('status')=='disputed':
        notes=value.get('notes','')
        if DISPUTED_NOTE not in notes:value['notes']=(notes+'\n'+DISPUTED_NOTE).strip()
    if table in COLUMN_TABLES and 'status' in value:value['status']='confirmed'
    return value

def normalize_rows(db,keys):
    # Called on touched rows only during ordinary edits/imports, never a full scan.
    for table,rid in list(keys):
        if table not in BODY_TABLES|COLUMN_TABLES:continue
        old=db.execute('SELECT * FROM '+table+' WHERE rowid=?',(rid,)).fetchone()
        if old is None:continue
        old=dict(old);new=row(table,old)
        fields=[k for k in old if old[k]!=new[k]]
        if fields:db.execute('UPDATE '+table+' SET '+','.join(k+'=?' for k in fields)+' WHERE rowid=?',(*[new[k] for k in fields],rid))

def needed(db):
    return not db.execute("SELECT 1 FROM sqlite_master WHERE name='editorial_migrations'").fetchone() or not db.execute('SELECT 1 FROM editorial_migrations WHERE id=?',(MARKER,)).fetchone()

def migrate(db):
    if not needed(db):return
    tables={r[0] for r in db.execute("SELECT name FROM sqlite_master WHERE type='table'")}
    for table in (BODY_TABLES|COLUMN_TABLES)&tables:
        normalize_rows(db,[(table,r[0]) for r in db.execute('SELECT rowid FROM '+table)])
    if 'undo_steps' in tables:
        for record in db.execute('SELECT id,changes FROM undo_steps').fetchall():
            changes=undo_codec.decode(record['changes'])
            for change in changes:
                for side in ('before','after'):change[side]=row(change['table'],change[side])
            db.execute('UPDATE undo_steps SET changes=? WHERE id=?',(undo_codec.encode(changes),record['id']))
    db.execute('CREATE TABLE IF NOT EXISTS editorial_migrations(id TEXT PRIMARY KEY)')
    db.execute('INSERT INTO editorial_migrations VALUES(?)',(MARKER,))


def comparable(value):
    value=clean(value)
    if isinstance(value,list):return [comparable(v) for v in value]
    if isinstance(value,dict):return {k:(v.replace(DISPUTED_NOTE,'').strip() if k=='notes' and isinstance(v,str) else comparable(v)) for k,v in value.items()}
    return value
