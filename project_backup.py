"""Versioned SQLite snapshot packages. Restores only to a new database."""
import hashlib
import json
import shutil
import sqlite3
import tempfile
import uuid
import zipfile
from contextlib import closing
from datetime import datetime,timezone
from pathlib import Path
import media_engine
import object_media
import undo_codec

FORMAT='corporium-sqlite-backup-v2'
LEGACY_FORMAT='corporium-sqlite-backup-v1'
MAX_PACKAGE=20*1024**3

def assets(db):
    result={r['id']:dict(r) for r in db.execute('SELECT * FROM timeline_media')}
    for step in db.execute('SELECT changes FROM undo_steps'):
        for change in undo_codec.decode(step[0]):
            if change['table']=='timeline_media':
                for key in ('before','after'):
                    row=change.get(key)
                    if row:result.setdefault(row['id'],row)
    return result

def copy_stream(source,destination,update,message):
    digest=hashlib.sha256()
    while chunk:=source.read(1024*1024):
        update(None,message);destination.write(chunk);digest.update(chunk)
    return digest.hexdigest()

def prepare(db,dbpath,include_media=False,update=lambda *a:None):
    import language_exchange
    dbpath=Path(dbpath)
    with tempfile.TemporaryDirectory(prefix='corporium-snapshot-',dir=language_exchange.STAGING.name) as folder:
        snapshot=Path(folder)/'project.sqlite3'
        update(0,'正在生成一致性数据库快照…')
        with closing(sqlite3.connect(snapshot)) as target:
            db.backup(target,pages=512,progress=lambda status,left,total:update(100*(total-left)/max(total,1),'正在生成数据库快照…'))
            target.row_factory=sqlite3.Row
            # This derived read interface is rebuilt from trusted application code,
            # so snapshots retain the existing rejection of supplied SQL views.
            target.execute('DROP VIEW IF EXISTS dictionary_targets');target.commit()
            import record_sources
            record_sources.drop_views(target)
            import analysis_workspace
            analysis_workspace.drop_backup_views(target)
            import word_analysis_memory
            word_analysis_memory.drop_triggers(target);target.commit()
            import independent_links
            independent_links.drop_triggers(target)
            import sentence_rows
            sentence_rows.drop_backup_indexes(target)
            import dictionary_rows
            dictionary_rows.drop_triggers(target)
            import sentence_search_index
            sentence_search_index.drop(target)
            import auto_match_index
            auto_match_index.drop(target)
            if not record_sources.native(db):
                import journal
                for row in target.execute('SELECT id,changes FROM undo_steps'):
                    portable=journal.portable_step(row)
                    if portable['changes']!=row['changes']:
                        target.execute('UPDATE undo_steps SET changes=? WHERE id=?',(portable['changes'],row['id']))
            target.commit()
        with closing(sqlite3.connect(snapshot)) as source:
            source.row_factory=sqlite3.Row
            all_assets=assets(source);required=set(object_media.backup_assets(source))
        media={}
        for mid,asset in all_assets.items():
            if asset['storage']!='missing' and (include_media or asset['storage']=='copy' or mid in required):
                media[mid]=(media_engine.resolve(dbpath,asset),asset)
        if snapshot.stat().st_size+sum(p.stat().st_size for p,_ in media.values())>MAX_PACKAGE-16*1024**2:
            raise ValueError('备份超过 20 GB，请保留外部媒体链接或分别导出语言')
        format_name=FORMAT if record_sources.native(db) else LEGACY_FORMAT
        manifest=dict(format=format_name,created=datetime.now(timezone.utc).isoformat(),media={},external_links=sum(a['storage']!='missing' and mid not in media for mid,a in all_assets.items()))
        with tempfile.NamedTemporaryFile(suffix='.corporium-backup',dir=language_exchange.STAGING.name,delete=False) as f:output=Path(f.name)
        try:
            with zipfile.ZipFile(output,'w',compression=zipfile.ZIP_STORED,allowZip64=True) as package:
                with snapshot.open('rb') as src,package.open('project.sqlite3','w',force_zip64=True) as dest:
                    manifest['database_sha256']=copy_stream(src,dest,update,'正在打包数据库快照…')
                for i,(mid,(path,asset)) in enumerate(media.items()):
                    name='media/'+str(i)+path.suffix.lower()
                    with path.open('rb') as src,package.open(name,'w',force_zip64=True) as dest:
                        digest=copy_stream(src,dest,update,'正在打包媒体：'+path.name)
                    media_engine.resolve(dbpath,asset) # Detect source changes during the copy.
                    manifest['media'][mid]=dict(file=name,sha256=digest)
                package.writestr('manifest.json',json.dumps(manifest,ensure_ascii=False))
            update(None,'备份文件已生成')
            return dict(token=language_exchange.stage(dbpath,output,'project-backup'),name='Corporium-'+datetime.now().strftime('%Y%m%d-%H%M%S')+'.corporium-backup',size=output.stat().st_size,media=len(media),external_links=manifest['external_links'])
        except BaseException:output.unlink(missing_ok=True);raise

def restore(source,destination):
    destination=Path(destination)
    if destination.exists():raise ValueError('目标已存在；请使用新的文件名，避免覆盖数据')
    destination.parent.mkdir(parents=True,exist_ok=True)
    created=[]
    with tempfile.TemporaryDirectory(prefix='.corporium-restore-',dir=destination.parent) as folder:
        temp=Path(folder)/'project.sqlite3'
        try:
            with zipfile.ZipFile(source) as package:
                entries=package.infolist();names={i.filename for i in entries}
                if len(entries)>100000 or len(names)!=len(entries) or sum(i.file_size for i in entries)>MAX_PACKAGE:raise ValueError('备份包内容无效或过大')
                if package.getinfo('manifest.json').file_size>16*1024**2:raise ValueError('备份清单过大')
                manifest=json.loads(package.read('manifest.json'))
                if manifest.get('format') not in (FORMAT,LEGACY_FORMAT):raise ValueError('不支持的备份版本')
                with package.open('project.sqlite3') as src,temp.open('xb') as dest:digest=copy_stream(src,dest,lambda *a:None,'')
                if digest!=manifest.get('database_sha256'):raise ValueError('备份数据库校验失败')
                with closing(sqlite3.connect(temp)) as db:
                    db.row_factory=sqlite3.Row
                    db.execute('PRAGMA foreign_keys=ON')
                    if db.execute('PRAGMA quick_check').fetchone()[0]!='ok':raise ValueError('备份数据库完整性检查失败')
                    if db.execute("SELECT 1 FROM sqlite_master WHERE type IN ('trigger','view')").fetchone():raise ValueError('备份含不支持的数据库对象')
                    import record_sources
                    relational=record_sources.native(db)
                    if manifest['format']==FORMAT and not relational:raise ValueError('备份缺少关系正文格式')
                    if relational:
                        import source_schema
                        source_schema.validate_relations(db)
                    known=assets(db);replacements={}
                    for mid,item in manifest.get('media',{}).items():
                        name=item['file']
                        if mid not in known or not isinstance(name,str) or len(Path(name).parts)!=2 or Path(name).parts[0]!='media' or '\\' in name or '..' in Path(name).parts:raise ValueError('备份媒体路径或关联无效')
                        target=destination.parent/'media'/(uuid.uuid4().hex+Path(name).suffix)
                        target.parent.mkdir(exist_ok=True)
                        with target.open('xb') as dest:
                            created.append(target)
                            with package.open(name) as src:digest=copy_stream(src,dest,lambda *a:None,'')
                        if digest!=item['sha256']:raise ValueError('备份媒体校验失败')
                        replacements[mid]=(str(target.relative_to(destination.parent)),media_engine.fingerprint(target))
                    remap_media(db,replacements)
                    record_sources.configure(db)
                    import dictionary_targets
                    dictionary_targets.initialize(db)
                    import independent_links
                    independent_links.migrate_word_source(db)
                    independent_links.initialize(db)
                    import sentence_rows
                    sentence_rows.initialize(db)
                    import dictionary_rows
                    dictionary_rows.initialize(db)
                    import independent_annotations
                    independent_annotations.migrate(db)
                    if db.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='analysis_runs'").fetchone():
                        import analysis_workspace
                        analysis_workspace.initialize_payloads(db)
                    db.commit()
            # Publish only after validation and all attachment writes succeed.
            with destination.open('xb') as dest:
                created.append(destination)
                with temp.open('rb') as src:shutil.copyfileobj(src,dest,1024*1024)
        except BaseException:
            for path in created:path.unlink(missing_ok=True)
            raise

def remap_media(db,replacements):
    def patch(row):
        relative,fingerprint=replacements[row['id']];meta=json.loads(row['metadata']);meta['fingerprint']=fingerprint
        return dict(row,path=relative,storage='copy',metadata=json.dumps(meta,ensure_ascii=False))
    for row in db.execute('SELECT * FROM timeline_media'):
        if row['id'] in replacements:
            r=patch(dict(row));db.execute('UPDATE timeline_media SET path=?,storage=?,metadata=? WHERE id=?',(r['path'],r['storage'],r['metadata'],r['id']))
    for row in db.execute('SELECT id,changes FROM undo_steps'):
        changes=undo_codec.decode(row['changes']);changed=False
        for c in changes:
            if c['table']=='timeline_media':
                for key in ('before','after'):
                    if c.get(key) and c[key]['id'] in replacements:c[key]=patch(c[key]);changed=True
        if changed:db.execute('UPDATE undo_steps SET changes=? WHERE id=?',(undo_codec.encode(changes),row['id']))
