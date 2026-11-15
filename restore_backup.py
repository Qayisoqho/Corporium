"""Restore a downloaded JSON backup into a NEW SQLite file, never overwrite."""
import argparse
import json
import zipfile
from pathlib import Path
import independent_links
import server
import timeline_colors
import record_sources


def restore(source, destination):
    destination = Path(destination)
    if destination.exists():
        raise ValueError('目标已存在；请使用新的文件名，避免覆盖数据')
    if zipfile.is_zipfile(source):
        from project_backup import restore as restore_package
        return restore_package(source,destination)
    data = json.loads(Path(source).read_text(encoding='utf-8-sig'))
    if data.get('format') != 'ordos-corpus-v1':
        raise ValueError('不支持的备份格式')
    created=[]
    old = server.DB
    try:
        server.DB = destination
        server.init()
        with server.connect() as db:
            for table in server.metadata.TABLES:
                allowed={r['name'] for r in db.execute('PRAGMA table_info('+table+')')} | {'rowid'}
                if table in data: db.execute('DELETE FROM '+table)
                for row in data.get(table,[]):
                    import storage_optimization
                    row=storage_optimization.compatible_row(table,row)
                    if table in independent_links.TABLES:
                        # A legacy example can also supply targets in its body.
                        db.execute('DELETE FROM '+table+' WHERE id=?',(row['id'],))
                        independent_links.restore_row(db,table,row)
                        continue
                    columns = [c for c in row if c in allowed]
                    if table in record_sources.TABLES:
                        record_sources.write(db,table,row['id'],record_sources.body(row,mutable=False),
                                             columns={c:row[c] for c in columns if c not in ('id','body')},insert=True)
                        continue
                    db.execute('INSERT OR REPLACE INTO '+table+' ('+','.join(columns)+') VALUES ('+','.join('?' for _ in columns)+')',[row[c] for c in columns])
            if 'undo_scopes' not in data:
                db.execute('DELETE FROM undo_scopes')
                server.languages.initialize(db)
            if 'grammar_tags' not in data:
                for row in db.execute('SELECT id,metadata FROM languages').fetchall():
                    server.grammar.sync_legacy(db,row['id'],{},json.loads(row['metadata']).get('glossary',{}))
            db.execute('DELETE FROM editorial_migrations')
            timeline_colors.initialize(db)
            server.timeline.initialize_order(db)
            server.manual_status.migrate(db)
            server.script_tags.recover(db)
            for row in db.execute('SELECT id FROM entries').fetchall():
                server.lexicon.sync_entry(db,row['id'])
            if 'gloss_bindings' not in data:
                import gloss_inheritance
                db.execute('DELETE FROM gloss_migrations')
                gloss_inheritance.migrate(db)
            server.object_media.restore_files(db,destination,data.get('object_media_files',{}),created)
            storage_optimization.migrate(db,force=True)
            server.categories.initialize(db,repair=True)
            server.lexicon.validate_links(db)
            server.timeline.hierarchy.validate(db)
            server.grammar_survey.validate(db)
            server.example_groups.validate(db)
            server.example_numbering.reconcile(db)
            server.fieldwork_notes.validate(db)
            server.code_switching.validate(db)
            server.code_switching.rebuild(db)
            server.object_media.validate_pending(db,full=True)
            server.analysis_workspace.invalidate(db)
            server.analysis_workspace.trim(db)
    except Exception:
        for p in created:p.unlink(missing_ok=True)
        raise
    finally:
        server.DB = old


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('backup')
    parser.add_argument('new_database')
    args=parser.parse_args()
    restore(args.backup,args.new_database)
    print('Restored:',args.new_database)
