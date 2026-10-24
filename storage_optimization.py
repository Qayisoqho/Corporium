"""One-time physical cleanup. Historical row images remain undoable."""
import undo_codec

MARKER='compact-storage-v1'
RETIRED={'lexical_links':{'status'},'morpheme_components':{'status'},'gloss_bindings':{'form'}}


def compatible_row(table,row):
    if row is None:return None
    import manual_status
    row=manual_status.row(table,row)
    if table=='entries' and row.get('body'):
        import json,grammaticality
        body=json.loads(row['body'])
        if any(k in body for k in grammaticality.CORPUS_FIELDS):
            row={**row,'body':json.dumps(grammaticality.strip_corpus(body),ensure_ascii=False)}
    return {k:v for k,v in row.items() if k not in RETIRED.get(table,())}


def needed(db):
    return not db.execute("SELECT 1 FROM sqlite_master WHERE name='storage_migrations'").fetchone() or not db.execute('SELECT 1 FROM storage_migrations WHERE id=?',(MARKER,)).fetchone()


def migrate(db,force=False):
    if not force and not needed(db):return
    if not db.in_transaction:db.execute('BEGIN IMMEDIATE')
    # Call after manual_status.migrate, which preserves old disputed notes.
    for table,columns in RETIRED.items():
        existing={r[1] for r in db.execute('PRAGMA table_info('+table+')')}
        if 'status' in columns&existing:
            import manual_status
            manual_status.normalize_rows(db,[(table,r[0]) for r in db.execute("SELECT rowid FROM "+table+" WHERE status='disputed'")])
        for column in columns&existing:db.execute('ALTER TABLE '+table+' DROP COLUMN '+column)
    db.execute('DROP INDEX IF EXISTS entries_text_position')
    for row in db.execute('SELECT id,changes FROM undo_steps').fetchall():
        encoded=undo_codec.compress_legacy(row['changes'])
        if encoded!=row['changes']:db.execute('UPDATE undo_steps SET changes=? WHERE id=?',(encoded,row['id']))
    db.execute('CREATE TABLE IF NOT EXISTS storage_migrations(id TEXT PRIMARY KEY)')
    db.execute('INSERT OR IGNORE INTO storage_migrations VALUES(?)',(MARKER,))
