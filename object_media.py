"""Images and recordings attached to dictionary entries and independent examples."""
import base64
from functools import lru_cache
import json
import shutil
import uuid
from pathlib import Path
import media_engine
import record_sources
import timeline

TABLES=('object_media',)
OWNER_KINDS={'lexemes':'lexeme','morphemes':'morpheme','dictionary_examples':'independent'}
SOURCES=frozenset((*OWNER_KINDS,'object_media','timeline_media','timeline_speakers'))
IMAGE_EXT={'.jpg','.jpeg','.png','.webp','.gif','.bmp','.tif','.tiff'}
AUDIO_EXT=media_engine.EXTENSIONS- {'.mp4','.mov','.mkv','.avi','.webm','.wmv','.m4v','.3gp'}

def initialize(db):
    record_sources.schema_sql(db, '''CREATE TABLE IF NOT EXISTS object_media(id TEXT PRIMARY KEY,language_id TEXT NOT NULL,kind TEXT NOT NULL,record_id TEXT NOT NULL,asset_id TEXT NOT NULL,body TEXT NOT NULL,position INTEGER NOT NULL,revision INTEGER NOT NULL DEFAULT 1);
    CREATE INDEX IF NOT EXISTS object_media_owner ON object_media(kind,record_id,position);
    CREATE INDEX IF NOT EXISTS object_media_asset ON object_media(asset_id);''')
    install_validation(db)


def install_validation(db):
    existed=validation_available(db)
    db.execute('CREATE TABLE IF NOT EXISTS object_media_validation_dirty(id TEXT PRIMARY KEY) WITHOUT ROWID')
    if not existed:
        db.execute('INSERT INTO object_media_validation_dirty SELECT id FROM object_media')

    def queue(where):
        return ('INSERT INTO object_media_validation_dirty SELECT m.id FROM object_media m WHERE '+where+
                ' ON CONFLICT DO NOTHING;')

    def watch(table,event,body,when=''):
        record_sources.trigger(db,f'object_media_check_{table}_{event}',f'AFTER {event} ON {table}{when} BEGIN {body} END')

    for event in ('INSERT','UPDATE'):
        removed='DELETE FROM object_media_validation_dirty WHERE id=OLD.id AND OLD.id IS NOT NEW.id;' if event=='UPDATE' else ''
        fields=('id','language_id','kind','record_id','asset_id','body')
        when=' WHEN '+' OR '.join(f'OLD.{key} IS NOT NEW.{key}' for key in fields) if event=='UPDATE' else ''
        watch('object_media',event,removed+queue('m.id=NEW.id'),when)
    watch('object_media','DELETE','DELETE FROM object_media_validation_dirty WHERE id=OLD.id;')
    for table,kind in OWNER_KINDS.items():
        scope=f"m.kind='{kind}' AND m.record_id=OLD.id"
        changed='OLD.id IS NOT NEW.id OR OLD.language_id IS NOT NEW.language_id'
        if kind!='independent':changed+=' OR '+record_sources.change_sql(db,table)
        watch(table,'INSERT',queue(f"m.kind='{kind}' AND m.record_id=NEW.id"))
        watch(table,'UPDATE',queue(scope),f' WHEN {changed}')
        watch(table,'DELETE',queue(scope))
    # Direct changes to the value rows do not publish an owner revision.
    # The normal writer queues the owner after publishing the complete set.
    for event in ('INSERT','UPDATE','DELETE'):
        refs=('OLD','NEW') if event=='UPDATE' else ('OLD',) if event=='DELETE' else ('NEW',)
        body=''.join(queue(f"m.kind='{kind}' AND {ref}.target_kind='{kind}' AND m.record_id={ref}.target_id AND NOT "+
                           record_sources.is_native(table,ref+'.target_id'))
                     for ref in refs for table,kind in OWNER_KINDS.items() if kind!='independent')
        watch('dictionary_value_rows',event,body," WHEN EXISTS(SELECT 1 FROM object_media LIMIT 1)")
    watch('timeline_media','UPDATE',queue('m.asset_id=OLD.id'),
          ' WHEN OLD.id IS NOT NEW.id OR OLD.language_id IS NOT NEW.language_id OR OLD.metadata IS NOT NEW.metadata')
    watch('timeline_media','DELETE',queue('m.asset_id=OLD.id'))
    speaker=queue("EXISTS(SELECT 1 FROM json_each(m.body,'$.speakers') p WHERE p.value=OLD.id)")
    watch('timeline_speakers','UPDATE',speaker,' WHEN OLD.id IS NOT NEW.id')
    watch('timeline_speakers','DELETE',speaker)


def validation_available(db):
    return db.execute("SELECT 1 FROM sqlite_master WHERE name='object_media_validation_dirty'").fetchone() is not None


def drop_validation(db):
    for name, in db.execute("SELECT name FROM sqlite_master WHERE type='trigger' AND name GLOB 'object_media_check_*'").fetchall():
        db.execute('DROP TRIGGER '+name)
    db.execute('DROP TABLE IF EXISTS object_media_validation_dirty')

def owner(db,kind,rid):
    table={'lexeme':'lexemes','morpheme':'morphemes','independent':'dictionary_examples'}.get(kind)
    if not table:raise ValueError('请选择词条、语素或独立例句')
    row=db.execute('SELECT * FROM '+table+' WHERE id=?',(rid,)).fetchone()
    if not row:raise ValueError('请先保存条目或例句，再添加媒体')
    result=dict(row)
    if kind in ('lexeme','morpheme'):result['body']=record_sources.read(db,table,rid)
    return result

def targets(row,kind):
    if kind not in ('lexeme','morpheme'):return []
    body=record_sources.body(row,mutable=False);out=[dict(id=v['id'],label=v['form'] or '未填写变体') for v in body.get('variants',[])]
    out.extend(dict(id=p['id'],label=p.get('label','主要部分')+'：'+p.get('form','')) for m in body.get('word_structure',{}).get('memberships',[]) for p in m.get('parts',[]))
    return out

def listing(db,kind,rid):
    row=owner(db,kind,rid);items=[];assets={}
    root=media_engine.cache_root(Path(db.execute('PRAGMA database_list').fetchone()[2]),create=False)
    for r in db.execute('SELECT * FROM object_media WHERE kind=? AND record_id=? ORDER BY position,id',(kind,rid)):
        items.append(media_item(db,r,root,assets))
    return dict(language_id=row['language_id'],items=items,targets=targets(row,kind))


def media_item(db,row,root,assets):
    item=dict(row);item['body']=json.loads(item['body'])
    key=item['asset_id']
    if key not in assets:
        asset=timeline.media_view(db,key)
        if asset is None:raise ValueError('关联的媒体文件已不存在')
        assets[key]={**asset,'proxy':(root/(media_engine.cache_key(asset)+'.mp4')).is_file()}
    item['asset']=assets[key]
    return item


def independent_listings(db,ids):
    ids=list(dict.fromkeys(ids))
    if len(ids)>100:raise ValueError('例句数量超出范围')
    if not ids:return {}
    marks=','.join('?' for _ in ids)
    results={r['id']:dict(language_id=r['language_id'],items=[],targets=[]) for r in
             db.execute(f'SELECT id,language_id FROM dictionary_examples WHERE id IN ({marks})',ids)}
    assets={}
    root=media_engine.cache_root(Path(db.execute('PRAGMA database_list').fetchone()[2]),create=False)
    for row in db.execute(f'''SELECT * FROM object_media WHERE kind='independent' AND record_id IN ({marks})
                              ORDER BY record_id,position,id''',ids):
        if row['record_id'] not in results:continue
        try:
            results[row['record_id']]['items'].append(media_item(db,row,root,assets))
        except (ValueError,TypeError,OSError):
            # Keep unrelated visible examples usable if an attachment is damaged.
            results.pop(row['record_id'])
    return results


def validate_body(db,body,asset,row,kind):
    if not isinstance(body,dict):raise ValueError('媒体信息无效')
    b={k:str(body.get(k,'')).strip() for k in ('caption','creator','source','target_id')}
    if any(len(v)>10000 for v in b.values()):raise ValueError('媒体说明过长')
    people=body.get('speakers',[])
    if not isinstance(people,list) or len(people)>100 or any(not isinstance(v,str) for v in people):raise ValueError('发言人列表无效')
    b['speakers']=list(dict.fromkeys(people))
    for pid in b['speakers']:
        if not db.execute('SELECT 1 FROM timeline_speakers WHERE id=?',(pid,)).fetchone():raise ValueError('发言人已不存在，请重新选择')
    if b['target_id'] and b['target_id'] not in {t['id'] for t in targets(row,kind)}:raise ValueError('媒体引用的具体词形已不存在，请先在管理媒体中调整对应词形')
    if asset['metadata'].get('kind')=='image':
        if kind not in ('lexeme','morpheme'):raise ValueError('独立例句暂只支持录音')
        b.update(start_ms=0,end_ms=0,speakers=[])
    else:
        if not any(s.get('type')=='audio' for s in asset['metadata'].get('streams',[])):raise ValueError('媒体没有音轨')
        b['start_ms']=timeline.number(body.get('start_ms',0));b['end_ms']=timeline.number(body.get('end_ms',asset['metadata']['duration_ms']))
        if not 0<=b['start_ms']<b['end_ms']<=asset['metadata']['duration_ms']:raise ValueError('起止时间须在录音时长内，结束时间须晚于起点')
    return b

def mutate(db,lid,b,asset=None):
    kind=b.get('kind');rid=b.get('record_id');row=owner(db,kind,rid)
    if row['language_id']!=lid:raise ValueError('请选择材料所属语言')
    current=listing(db,kind,rid)['items']
    if b.get('snapshot')!=[[r['id'],r['revision']] for r in current]:raise ValueError('媒体列表已改变，请重新打开管理媒体')
    action=b.get('action','save');existing=next((r for r in current if r['id']==b.get('id')),None)
    if action in ('delete','up','down','default'):
        if not existing:raise ValueError('媒体关联已不存在')
        if action=='delete':db.execute('DELETE FROM object_media WHERE id=?',(existing['id'],))
        else:
            ids=[r['id'] for r in current];at=ids.index(existing['id']);to=0 if action=='default' else max(0,min(len(ids)-1,at+(-1 if action=='up' else 1)))
            ids.insert(to,ids.pop(at))
            for pos,key in enumerate(ids):db.execute('UPDATE object_media SET position=?,revision=revision+1 WHERE id=?',(pos,key))
        return {'ok':True}
    if action!='save':raise ValueError('未知媒体操作')
    if b.get('id') and not existing:raise ValueError('媒体关联已不存在')
    if asset:
        asset={**asset,'id':str(uuid.uuid4()),'language_id':lid}
    else:
        asset=timeline.media_view(db,b.get('asset_id') or (existing or {}).get('asset_id'))
        if not asset or asset['language_id']!=lid:raise ValueError('请选择本语言媒体')
    data=validate_body(db,b.get('body',{}),asset,row,kind)
    if not db.execute('SELECT 1 FROM timeline_media WHERE id=?',(asset['id'],)).fetchone():
        db.execute('INSERT INTO timeline_media VALUES(?,?,?,?,?,?,1)',(asset['id'],lid,asset['name'],asset['path'],asset['storage'],json.dumps(asset['metadata'],ensure_ascii=False)))
    key=existing['id'] if existing else str(uuid.uuid4())
    if existing:db.execute('UPDATE object_media SET asset_id=?,body=?,revision=revision+1 WHERE id=?',(asset['id'],json.dumps(data,ensure_ascii=False),key))
    else:db.execute('INSERT INTO object_media VALUES(?,?,?,?,?,?,?,1)',(key,lid,kind,rid,asset['id'],json.dumps(data,ensure_ascii=False),max([r['position'] for r in current],default=-1)+1))
    return {'ok':True,'id':key}

def ingest(dbpath,path,name):
    import av
    ext=Path(name).suffix.lower();root=Path(dbpath).parent/'media';root.mkdir(parents=True,exist_ok=True)
    target=root/(str(uuid.uuid4())+ext)
    try:
        if ext in IMAGE_EXT:
            with av.open(str(path)) as container:
                frame=next(container.decode(video=0))
                if frame.width*frame.height>40_000_000:raise ValueError('图片超过四千万像素，请先缩小')
                meta=dict(kind='image',width=frame.width,height=frame.height,streams=[],duration_ms=0)
                if ext in {'.bmp','.tif','.tiff'}:
                    target=target.with_suffix('.png')
                    with av.open(str(target),'w',format='image2') as output:
                        stream=output.add_stream('png');stream.width=frame.width;stream.height=frame.height;stream.pix_fmt='rgba'
                        for packet in stream.encode(frame.reformat(format='rgba')):output.mux(packet)
                        for packet in stream.encode():output.mux(packet)
                else:shutil.copyfile(path,target)
        elif ext in AUDIO_EXT:
            meta=media_engine.probe(path)
            if not any(s['type']=='audio' for s in meta['streams']):raise ValueError('文件没有音轨')
            if meta['duration_ms']>3600*1000:raise ValueError('单段录音最多一小时；长录音请使用时间轴媒体片段')
            shutil.copyfile(path,target);meta['kind']='audio'
        else:raise ValueError('请选择 JPEG、PNG、WebP、GIF、BMP、TIFF 图片或音频文件；HEIC/HEIF 请先转为 JPEG/PNG，暂不导入视频')
        meta.update(fingerprint=media_engine.fingerprint(target),object_media=True)
        return dict(name=Path(name).name,path=str(target.relative_to(Path(dbpath).parent)),storage='copy',metadata=meta)
    except Exception:
        target.unlink(missing_ok=True);raise

def audio_playable(dbpath,asset):
    """Keep original recordings intact; derive a portable player copy in the disposable cache."""
    import av
    source=media_engine.resolve(dbpath,asset)
    target=media_engine.cache_root(dbpath)/(media_engine.cache_key(asset)+'.wav')
    if target.is_file():return target
    temp=target.with_name(str(uuid.uuid4())+'.wav')
    try:
        with av.open(str(source)) as input_file,av.open(str(temp),'w') as output:
            stream=output.add_stream('pcm_s16le',rate=48000);stream.layout='stereo'
            resampler=av.AudioResampler(format='s16',layout='stereo',rate=48000)
            for frame in input_file.decode(audio=0):
                for converted in resampler.resample(frame):
                    converted.pts=None
                    for packet in stream.encode(converted):output.mux(packet)
            for converted in resampler.resample(None):
                converted.pts=None
                for packet in stream.encode(converted):output.mux(packet)
            for packet in stream.encode():output.mux(packet)
        media_engine.resolve(dbpath,asset);temp.replace(target)
    finally:temp.unlink(missing_ok=True)
    return target

def cleanup(db,changes):
    for (table,_),(before,after) in list(changes.items()):
        kind=OWNER_KINDS.get(table)
        if kind and before and not after:db.execute('DELETE FROM object_media WHERE kind=? AND record_id=?',(kind,before['id']))

def backup_assets(db):
    assets={r['id']:dict(r) for r in db.execute('SELECT * FROM timeline_media')}
    linked={r[0] for r in db.execute('SELECT asset_id FROM object_media')}
    for step in db.execute('SELECT changes FROM undo_steps'):
        import undo_codec
        for change in undo_codec.decode(step[0]):
            for key in ('before','after'):
                row=change.get(key)
                if not row:continue
                if change['table']=='timeline_media':assets.setdefault(row['id'],row)
                if change['table']=='object_media':linked.add(row['asset_id'])
    return {mid:asset for mid,asset in assets.items() if (mid in linked or json.loads(asset['metadata']).get('object_media')) and asset['storage']!='missing'}

def backup_files(db,dbpath):
    return {mid:base64.b64encode(media_engine.resolve(dbpath,asset).read_bytes()).decode('ascii') for mid,asset in backup_assets(db).items()}

def restore_files(db,dbpath,files,created):
    if not files:return
    root=Path(dbpath).parent/'media';root.mkdir(parents=True,exist_ok=True)
    assets=backup_assets(db);replacements={}
    for mid,content in files.items():
        if mid not in assets:raise ValueError('备份媒体没有对应的媒体记录')
        asset=assets[mid];path=root/(str(uuid.uuid4())+Path(asset['path']).suffix)
        raw=base64.b64decode(content,validate=True);created.append(path);path.write_bytes(raw)
        relative=str(path.relative_to(Path(dbpath).parent));fingerprint=media_engine.fingerprint(path)
        replacements[mid]=(relative,fingerprint)
        meta=json.loads(asset['metadata']);meta['fingerprint']=fingerprint
        db.execute("UPDATE timeline_media SET path=?,storage='copy',metadata=? WHERE id=?",(relative,json.dumps(meta),mid))
    # Restored undo/redo must refer to the restored files, including currently undone imports.
    for step in db.execute('SELECT id,changes FROM undo_steps').fetchall():
        import undo_codec
        changes=undo_codec.decode(step['changes']);changed=False
        for c in changes:
            if c['table']!='timeline_media':continue
            for key in ('before','after'):
                row=c.get(key)
                if row and row['id'] in replacements:
                    relative,fingerprint=replacements[row['id']];meta=json.loads(row['metadata']);meta['fingerprint']=fingerprint
                    row.update(path=relative,storage='copy',metadata=json.dumps(meta));changed=True
        if changed:db.execute('UPDATE undo_steps SET changes=? WHERE id=?',(undo_codec.encode(changes),step['id']))


def validate(db):
    validate_rows(db,db.execute('SELECT * FROM object_media'))


def validate_pending(db,*,full=False):
    """Check affected relationships in the source transaction before publication."""
    if not validation_available(db):
        validate(db)
        return
    if full:
        validate(db)
    else:
        if not db.execute('SELECT 1 FROM object_media_validation_dirty LIMIT 1').fetchone():return
        validate_rows(db,db.execute('''SELECT m.* FROM object_media_validation_dirty d
            CROSS JOIN object_media m ON m.id=d.id'''))
    db.execute('DELETE FROM object_media_validation_dirty')


def validate_rows(db,records):
    import long_tasks

    @lru_cache(maxsize=128)
    def owner_row(kind,key):return owner(db,kind,key)

    @lru_cache(maxsize=128)
    def asset_row(key):return timeline.media_view(db,key)

    for record in long_tasks.steps(records):
        row=owner_row(record['kind'],record['record_id']);asset=asset_row(record['asset_id'])
        if asset is None:raise ValueError('关联的媒体文件已不存在')
        if row['language_id']!=record['language_id'] or asset['language_id']!=record['language_id']:raise ValueError('媒体关联与材料所属语言不一致，请先移除或调整媒体关联')
        validate_body(db,json.loads(record['body']),asset,row,record['kind'])
