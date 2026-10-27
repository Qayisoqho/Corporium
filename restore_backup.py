"""Restore a downloaded JSON backup into a NEW SQLite file, never overwrite."""
import argparse
import json
import zipfile
from pathlib import Path
import server
import timeline_colors


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
                    columns = [c for c in row if c in allowed]
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
            server.categories.initialize(db)
            server.lexicon.validate_links(db)
            server.timeline.hierarchy.validate(db)
            server.grammar_survey.validate(db)
            server.example_groups.validate(db)
            server.example_numbering.reconcile(db)
            server.fieldwork_notes.validate(db)
            server.code_switching.validate(db)
            server.code_switching.rebuild(db)
            server.object_media.validate(db)
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
