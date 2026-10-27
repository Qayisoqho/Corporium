"""Project participants and dependent timeline annotations. No corpus text is copied."""
import json
import uuid
import collaborators
import timeline_colors
import timeline_text_order

CATALOGS=('timeline_speakers','timeline_codes')

def initialize(db):
    for table in CATALOGS:
        db.execute(f"CREATE TABLE IF NOT EXISTS {table}(id TEXT PRIMARY KEY,name TEXT NOT NULL,metadata TEXT NOT NULL DEFAULT '{{}}',revision INTEGER NOT NULL DEFAULT 1)")
    for table,fields in [('timeline_tracks',['parent_id','speaker_id']),('timeline_intervals',['parent_id','code_id'])]:
        columns={r['name'] for r in db.execute('PRAGMA table_info('+table+')')}
        for field in fields:
            if field not in columns:db.execute(f'ALTER TABLE {table} ADD COLUMN {field} TEXT')
            db.execute(f'CREATE INDEX IF NOT EXISTS {table}_{field} ON {table}({field})')
    timeline_colors.initialize(db)
    timeline_text_order.initialize(db)

def catalog(db):
    return {table.removeprefix('timeline_'):[dict(r) for r in db.execute('SELECT * FROM '+table+' ORDER BY name,id')] for table in CATALOGS}

def catalog_mutate(db,action,b):
    table='timeline_speakers' if action.startswith('speaker-') else 'timeline_codes'
    row=db.execute('SELECT * FROM '+table+' WHERE id=?',(b.get('record_id'),)).fetchone()
    if b.get('record_id') and (not row or row['revision']!=b.get('revision')):raise ValueError('信息已更新，请重新打开后再保存')
    if action.endswith('-delete'):
        if not row or b.get('confirmed') is not True:raise ValueError('请确认删除')
        if table=='timeline_speakers' and collaborators.referenced(db,row['id']):raise ValueError('此合作者仍被文本或例句引用，请先解除关联')
        target,field=('timeline_tracks','speaker_id') if table=='timeline_speakers' else ('timeline_intervals','code_id')
        if db.execute(f'SELECT 1 FROM {target} WHERE {field}=? LIMIT 1',(row['id'],)).fetchone():raise ValueError('此记录仍被时间轴引用，请先解除引用；不会删除相关轨道或标注')
        db.execute('DELETE FROM '+table+' WHERE id=?',(row['id'],));return {'ok':True}
    name=str(b.get('name','')).strip()[:200]
    if not name:raise ValueError('请填写显示名称')
    meta=b.get('metadata',{})
    if not isinstance(meta,dict) or len(json.dumps(meta))>20000:raise ValueError('附加信息格式不正确或过长')
    if table=='timeline_speakers':collaborators.validate_profile(db,meta)
    rid=row['id'] if row else str(uuid.uuid4())
    db.execute('INSERT INTO '+table+'(id,name,metadata) VALUES(?,?,?) ON CONFLICT(id) DO UPDATE SET name=excluded.name,metadata=excluded.metadata,revision='+table+'.revision+1',(rid,name,json.dumps(meta,ensure_ascii=False)))
    return {'id':rid,'ok':True}

def subtree(db,table,rid):
    return [dict(r) for r in db.execute(f'''WITH RECURSIVE children(id) AS (
      SELECT id FROM {table} WHERE parent_id=? UNION SELECT t.id FROM {table} t JOIN children c ON t.parent_id=c.id)
      SELECT t.* FROM {table} t JOIN children c ON t.id=c.id''',(rid,))]

def track_save(db,sid,b,require):
    old=require(db,'timeline_tracks',b['track_id']) if b.get('track_id') else None
    if old and old['session_id']!=sid:raise ValueError('轨道不属于此时间轴')
    kind=b.get('kind',old['kind'] if old else 'sentence');name=str(b.get('name','')).strip()[:200]
    if not name or kind not in ('sentence','event','language'):raise ValueError('请填写轨道名称并选择类型')
    parent=b.get('parent_id',old['parent_id'] if old else None) or None
    speaker=b.get('speaker_id',old['speaker_id'] if old else None) or None
    rid=old['id'] if old else str(uuid.uuid4())
    if old and kind!=old['kind'] and (db.execute('SELECT 1 FROM timeline_intervals WHERE track_id=?',(rid,)).fetchone() or db.execute('SELECT 1 FROM timeline_tracks WHERE parent_id=?',(rid,)).fetchone()):raise ValueError('有标注或子轨道的轨道不能直接更改类型')
    if parent:
        p=require(db,'timeline_tracks',parent)
        if p['session_id']!=sid or parent==rid or (old and parent in {t['id'] for t in subtree(db,'timeline_tracks',rid)}):raise ValueError('父轨道无效：不能跨时间轴或形成循环')
        if kind=='sentence' or p['kind']=='language' or (kind=='language' and p['kind']!='sentence'):raise ValueError('句子使用顶层轨道；语言片段必须直接依附句子，语言片段下不能再建子轨道')
        speaker=None
    elif kind=='language':raise ValueError('语言片段需要选择句子父轨道')
    if speaker:require(db,'timeline_speakers',speaker)
    if old and parent!=old['parent_id'] and db.execute('SELECT 1 FROM timeline_intervals WHERE track_id=?',(rid,)).fetchone():raise ValueError('轨道已有标注，请先处理其区间，再更改父轨道')
    color=timeline_colors.clean(b.get('color',old['color'] if old else None))
    if not parent and color is None:color=timeline_colors.next_color(db,sid)
    db.execute('''INSERT INTO timeline_tracks(id,session_id,name,kind,position,parent_id,speaker_id,color) VALUES(?,?,?,?,?,?,?,?)
      ON CONFLICT(id) DO UPDATE SET name=excluded.name,kind=excluded.kind,parent_id=excluded.parent_id,speaker_id=excluded.speaker_id,color=excluded.color,revision=timeline_tracks.revision+1''',
      (rid,sid,name,kind,old['position'] if old else db.execute('SELECT COALESCE(MAX(position),0)+1 FROM timeline_tracks WHERE session_id=?',(sid,)).fetchone()[0],parent,speaker,color))
    return rid

def parent_for(db,track,start,end,parent_id):
    if not track['parent_id']:
        if parent_id:raise ValueError('顶层轨道的区间不能指定父区间')
        return None
    args=[track['parent_id'],start,end]
    where='track_id=? AND start_ms<=? AND end_ms>=?'
    if parent_id:where+=' AND id=?';args.append(parent_id)
    rows=db.execute('SELECT id FROM timeline_intervals WHERE '+where,args).fetchall()
    if len(rows)!=1:raise ValueError('请选择父区间内部的时间范围；子区间不能跨越父区间边界')
    return rows[0][0]

def prepare_children(db,existing,start,end,track_id,entry_id,collision):
    children=subtree(db,'timeline_intervals',existing['id'])
    if not children:return
    if track_id!=existing['track_id'] or entry_id!=existing['entry_id']:raise ValueError('区间已有子标注，不能直接换轨道或换句子')
    offset=start-existing['start_ms'] if end-start==existing['end_ms']-existing['start_ms'] else 0
    ids=[r['id'] for r in children]
    for r in children:
        a,z=r['start_ms']+offset,r['end_ms']+offset
        if a<start or z>end:raise ValueError('调整后子标注将越界，请先调整子区间；原区间未修改')
        collision(db,r['session_id'],r['track_id'],a,z,ids)
    if offset:
        for r in children:db.execute('UPDATE timeline_intervals SET start_ms=start_ms+?,end_ms=end_ms+?,revision=revision+1 WHERE id=?',(offset,offset,r['id']))

def validate(db,session_id=None):
    timeline_text_order.validate(db)
    if session_id is None:collaborators.validate(db)
    tracks={r['id']:dict(r) for r in db.execute('SELECT * FROM timeline_tracks')}
    sessions={r[0] for r in db.execute('SELECT id FROM timeline_sessions')}
    speakers={r[0] for r in db.execute('SELECT id FROM timeline_speakers')}
    for table in CATALOGS:
        for r in db.execute('SELECT name,metadata FROM '+table):
            try:meta=json.loads(r['metadata'])
            except (ValueError,TypeError):raise ValueError('说话人或语言标记附加信息无效')
            if not r['name'].strip() or not isinstance(meta,dict):raise ValueError('说话人或语言标记信息无效')
    for t in tracks.values():
        timeline_colors.clean(t.get('color'))
        if t['session_id'] not in sessions:raise ValueError('轨道所属时间轴已不存在')
        p=tracks.get(t['parent_id'])
        if t['speaker_id'] and t['speaker_id'] not in speakers:raise ValueError('说话人仍被引用，不能撤销或删除其创建记录')
        if t['parent_id'] and (not p or p['session_id']!=t['session_id'] or t['speaker_id'] or t['kind']=='sentence' or p['kind']=='language'):raise ValueError('父轨道或继承的说话人信息无效')
        if t['kind']=='language' and (not p or p['kind']!='sentence'):raise ValueError('语言片段必须依附句子轨道')
        seen=set();node=t
        while node:
            if node['id'] in seen or len(seen)>32:raise ValueError('轨道层级存在循环或超过 32 层')
            seen.add(node['id']);node=tracks.get(node['parent_id'])
    query='''SELECT i.id FROM timeline_intervals i LEFT JOIN timeline_tracks t ON t.id=i.track_id
      LEFT JOIN timeline_intervals p ON p.id=i.parent_id LEFT JOIN timeline_codes c ON c.id=i.code_id
      WHERE '''+('i.session_id=? AND ' if session_id else '')+'''(t.id IS NULL OR t.session_id!=i.session_id OR
      (t.parent_id IS NULL AND i.parent_id IS NOT NULL) OR
      (t.parent_id IS NOT NULL AND (p.id IS NULL OR p.track_id!=t.parent_id OR p.session_id!=i.session_id OR i.start_ms<p.start_ms OR i.end_ms>p.end_ms)) OR
      (i.code_id IS NOT NULL AND (c.id IS NULL OR t.kind!='language'))) LIMIT 1'''
    bad=db.execute(query,(session_id,) if session_id else ()).fetchone()
    if bad:raise ValueError('子区间引用或时间范围无效，操作未应用')
