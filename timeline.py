"""Sentence alignment: media identity, tracks and intervals are independent of corpus text."""
import long_tasks
import hashlib
import json
import math
import uuid
import timeline_hierarchy as hierarchy
import timeline_colors
import timeline_text_order as text_order

TABLES=hierarchy.CATALOGS+('timeline_media','timeline_sessions','timeline_tracks','timeline_intervals')+text_order.TABLES

def initialize(db):
    db.executescript('''
    CREATE TABLE IF NOT EXISTS timeline_media(id TEXT PRIMARY KEY,language_id TEXT NOT NULL,name TEXT NOT NULL,path TEXT NOT NULL,storage TEXT NOT NULL,metadata TEXT NOT NULL,revision INTEGER NOT NULL DEFAULT 1);
    CREATE TABLE IF NOT EXISTS timeline_sessions(id TEXT PRIMARY KEY,language_id TEXT NOT NULL,name TEXT NOT NULL,media_id TEXT NOT NULL,revision INTEGER NOT NULL DEFAULT 1);
    CREATE TABLE IF NOT EXISTS timeline_tracks(id TEXT PRIMARY KEY,session_id TEXT NOT NULL,name TEXT NOT NULL,kind TEXT NOT NULL,position INTEGER NOT NULL,revision INTEGER NOT NULL DEFAULT 1);
    CREATE TABLE IF NOT EXISTS timeline_intervals(id TEXT PRIMARY KEY,session_id TEXT NOT NULL,track_id TEXT NOT NULL,entry_id TEXT,label TEXT NOT NULL DEFAULT '',status TEXT NOT NULL DEFAULT 'confirmed',start_ms INTEGER NOT NULL,end_ms INTEGER NOT NULL,revision INTEGER NOT NULL DEFAULT 1,CHECK(end_ms>start_ms));
    CREATE INDEX IF NOT EXISTS timeline_session_language ON timeline_sessions(language_id);
    CREATE INDEX IF NOT EXISTS timeline_track_session ON timeline_tracks(session_id,position);
    CREATE INDEX IF NOT EXISTS timeline_interval_time ON timeline_intervals(session_id,track_id,start_ms,end_ms);
    CREATE INDEX IF NOT EXISTS timeline_track_time ON timeline_intervals(track_id,start_ms);
    CREATE INDEX IF NOT EXISTS timeline_interval_entry ON timeline_intervals(session_id,entry_id);
    CREATE INDEX IF NOT EXISTS timeline_entry_audio ON timeline_intervals(entry_id);
    ''')
    hierarchy.initialize(db)
    initialize_order(db)


def initialize_order(db):
    if 'position' not in {r['name'] for r in db.execute('PRAGMA table_info(timeline_sessions)')}:
        db.execute('ALTER TABLE timeline_sessions ADD COLUMN position INTEGER')
    # Preserve the previous newest-first order once, including legacy restores.
    db.execute('UPDATE timeline_sessions SET position=-rowid WHERE position IS NULL')
    db.execute('CREATE INDEX IF NOT EXISTS timeline_session_order ON timeline_sessions(language_id,position)')


def first_position(db,lid):
    return db.execute('SELECT COALESCE(MIN(position),0)-1 FROM timeline_sessions WHERE language_id=?',(lid,)).fetchone()[0]

def uid():return str(uuid.uuid4())

def require(db,table,rid):
    if table not in TABLES:raise ValueError('无效时间轴对象')
    row=db.execute('SELECT * FROM '+table+' WHERE id=?',(rid,)).fetchone()
    if not row:raise ValueError('时间轴对象已不存在，请刷新')
    return dict(row)

def session(db,lid,sid):
    row=require(db,'timeline_sessions',sid)
    if lid!=row['language_id']:raise ValueError('请选择时间轴所属语言')
    return row

def number(value):
    try:n=float(value)
    except (ValueError,TypeError):raise ValueError('请填写有效时间')
    if not math.isfinite(n) or abs(n)>10**12:raise ValueError('时间超出支持范围')
    return round(n)

def media_view(db,mid):
    if not mid:return None
    row=require(db,'timeline_media',mid)
    row['metadata']=json.loads(row['metadata'])
    return row

def listing(db,lid):
    return [dict(r) for r in db.execute('SELECT s.*,m.name media_name FROM timeline_sessions s LEFT JOIN timeline_media m ON m.id=s.media_id WHERE s.language_id=? ORDER BY s.position,s.rowid DESC',(lid,))]

def sentence_clips(db,ids):
    """One batch for visible sentence references; no snapshot copies of media paths."""
    ids=list(dict.fromkeys(ids))
    if len(ids)>200:raise ValueError('一次最多查询 200 个句子')
    result={key:[] for key in ids}
    if not ids:return result
    rows=db.execute('''SELECT i.id,i.entry_id,i.start_ms,i.end_ms,s.id session_id,s.name session_name,
        m.id asset,m.name media_name,m.metadata FROM timeline_intervals i
        JOIN timeline_sessions s ON s.id=i.session_id
        JOIN timeline_media m ON m.id=s.media_id
        WHERE (EXISTS(SELECT 1 FROM entries e WHERE e.id=i.entry_id) OR EXISTS(SELECT 1 FROM dictionary_examples d WHERE 'independent:'||d.id=i.entry_id)) AND i.entry_id IN ('''+','.join('?' for _ in ids)+') ORDER BY s.rowid,i.start_ms,i.id',ids)
    for row in rows:
        item=dict(row);meta=json.loads(item.pop('metadata'))
        if not any(s.get('type')=='audio' for s in meta.get('streams',[])):continue
        duration=meta.get('duration_ms',0)
        item['play_start_ms']=max(0,item['start_ms']);item['play_end_ms']=min(duration,item['end_ms'])
        if item['play_end_ms']<=item['play_start_ms']:continue
        item['clipped']=item['play_start_ms']!=item['start_ms'] or item['play_end_ms']!=item['end_ms']
        result[item.pop('entry_id')].append(item)
    return result

def detail(db,lid,b):
    s=session(db,lid,b['id']);media=media_view(db,s['media_id'])
    complete=str(b.get('complete',''))=='1'
    start=number(b.get('start',0));end=number(b.get('end',60000))
    if end<=start:raise ValueError('时间窗口无效')
    rows=db.execute('''SELECT i.*,
      json_extract(COALESCE(e.body,d.body),'$.ipa') sentence_ipa,
      json_extract(COALESCE(e.body,d.body),'$.translation') sentence_translation,
      json_extract(COALESCE(e.body,d.body),'$.language_id') sentence_language,
      COALESCE(e.revision,d.revision) entry_revision,CASE WHEN d.id IS NOT NULL THEN '@independent' ELSE e.text_id END text_id,e.position,t.title,
      (SELECT COUNT(*) FROM timeline_intervals child WHERE child.parent_id=i.id) child_count,
      (SELECT p.end_ms FROM timeline_intervals p WHERE p.track_id=i.track_id AND p.start_ms<i.start_ms ORDER BY p.start_ms DESC LIMIT 1) previous_ms,
      (SELECT n.start_ms FROM timeline_intervals n WHERE n.track_id=i.track_id AND n.start_ms>i.start_ms ORDER BY n.start_ms LIMIT 1) next_ms FROM timeline_intervals i
      LEFT JOIN entries e ON e.id=i.entry_id LEFT JOIN dictionary_examples d ON d.id=CASE WHEN substr(i.entry_id,1,12)='independent:' THEN substr(i.entry_id,13) END LEFT JOIN texts t ON t.id=e.text_id
      WHERE i.session_id=? AND (? OR (i.end_ms>=? AND i.start_ms<=?) OR i.id=?) ORDER BY CASE WHEN i.id=? THEN 0 ELSE 1 END,i.start_ms LIMIT ?''',(s['id'],complete,start,end,b.get('selected_interval',''),b.get('selected_interval',''),-1 if complete else 2002)).fetchall()
    items=[];catalogs=hierarchy.catalog(db)
    code_links={r['interval_id']:r['span_id'] for r in db.execute('SELECT l.* FROM code_time_links l JOIN timeline_intervals i ON i.id=l.interval_id WHERE i.session_id=?',(s['id'],))}
    for row in rows:
        item=dict(row);ipa=item.pop('sentence_ipa');translation=item.pop('sentence_translation');language=item.pop('sentence_language');item['code_span_id']=code_links.get(item['id'])
        item['text']=next((c['name'] for c in catalogs['codes'] if c['id']==item['code_id']),None) if item['code_id'] else None
        item['text']=item['text'] or item['label'] or ipa or translation or '未填写句子'
        item['language_id']=language or lid
        item['missing_entry']=bool(item['entry_id'] and not item['text_id']);items.append(item)
    selected=next((i for i in items if i['id']==b.get('selected_interval')),None)
    if not complete:items=[i for i in items if i['end_ms']>=start and i['start_ms']<=end]
    ext=db.execute('SELECT MIN(start_ms),MAX(end_ms),COUNT(*) FROM timeline_intervals WHERE session_id=?',(s['id'],)).fetchone()
    import journal
    return dict(session=s,media=media,gloss_revision=journal.workspace_revision(db),**catalogs,auto_order_texts=[r[0] for r in db.execute('SELECT id FROM timeline_text_orders WHERE session_id=?',(s['id'],))],tracks=[dict(r) for r in db.execute('SELECT * FROM timeline_tracks WHERE session_id=? ORDER BY position,rowid',(s['id'],))],intervals=items if complete else items[:2000],selected_interval=selected,complete=complete,
        extent=[min(0,ext[0] or 0),max(media['metadata']['duration_ms'] if media else 0,ext[1] or 0)],count=ext[2],truncated=not complete and len(items)>2000)

def pending(db,lid,b):
    session(db,lid,b['id']);page=max(1,int(b.get('page',1)));tid=b.get('text_id','')
    where='t.language_id=? AND NOT EXISTS(SELECT 1 FROM timeline_intervals i WHERE i.session_id=? AND i.entry_id=e.id)'
    args=[lid,b['id']]
    if tid=='@independent':
        where="e.language_id=? AND NOT EXISTS(SELECT 1 FROM timeline_intervals i WHERE i.session_id=? AND i.entry_id='independent:'||e.id)"
        total=db.execute('SELECT COUNT(*) FROM dictionary_examples e WHERE '+where,args).fetchone()[0]
        page=min(page,max(1,math.ceil(total/40)));items=[]
        for r in db.execute('SELECT e.id,e.body FROM dictionary_examples e WHERE '+where+' ORDER BY e.rowid LIMIT 40 OFFSET ?',[*args,(page-1)*40]):
            body=json.loads(r['body']);items.append(dict(id='independent:'+r['id'],position='',title='独立例句',language_id=lid,text=body.get('ipa') or body.get('original') or body.get('translation') or '未填写句子'))
        return dict(items=items,total=total,page=page,pages=max(1,math.ceil(total/40)))
    if tid:where+=' AND e.text_id=?';args.append(tid)
    total=db.execute('SELECT COUNT(*) FROM entries e JOIN texts t ON t.id=e.text_id WHERE '+where,args).fetchone()[0]
    page=min(page,max(1,math.ceil(total/40)));items=[]
    for r in db.execute('SELECT e.id,e.position,e.body,t.title FROM entries e JOIN texts t ON t.id=e.text_id WHERE '+where+' ORDER BY t.rowid,e.position LIMIT 40 OFFSET ?',[*args,(page-1)*40]):
        body=json.loads(r['body']);items.append(dict(id=r['id'],position=r['position'],title=r['title'],language_id=body.get('language_id') or lid,text=body.get('ipa') or body.get('translation') or '未填写句子'))
    return dict(items=items,total=total,page=page,pages=max(1,math.ceil(total/40)))

def check_revision(s,b):
    if s['revision']!=b.get('revision'):raise ValueError('时间轴已更新，请刷新后再操作')

def register(db,lid,asset):
    # The descriptor is produced by media_engine, never supplied as raw client metadata.
    mid=uid();db.execute('INSERT INTO timeline_media VALUES(?,?,?,?,?,?,1)',(mid,lid,asset['name'],asset['path'],asset['storage'],json.dumps(asset['metadata'])))
    return mid

def replacement(db,lid,b,asset):
    s=session(db,lid,b['id']);check_revision(s,b)
    offset=number(b.get('offset_ms',0));old=media_view(db,s['media_id']);duration=asset['metadata']['duration_ms']
    rows=[dict(r) for r in db.execute('SELECT * FROM timeline_intervals WHERE session_id=? ORDER BY id',(s['id'],))]
    warnings=[]
    old_duration=old['metadata']['duration_ms'] if old else 0
    if old and old_duration!=duration:warnings.append('新旧媒体时长不同，仍可继续；区间不会截断。')
    outside=sum(r['start_ms']+offset<0 or r['end_ms']+offset>duration for r in rows)
    if outside:warnings.append(f'{outside} 个区间将超出新媒体范围，仍保留在时间轴上。')
    payload=json.dumps([s,rows,asset,offset],sort_keys=True,ensure_ascii=False)
    return dict(token=hashlib.sha256(payload.encode()).hexdigest(),old_duration_ms=old_duration,new_duration_ms=duration,offset_ms=offset,count=len(rows),outside=outside,warnings=warnings)

def mutate(db,lid,action,b,asset=None):
    if action in ('speaker-save','speaker-delete','code-save','code-delete'):
        return hierarchy.catalog_mutate(db,action,b)
    if action=='reorder':
        rows=listing(db,lid)
        snapshot=[dict(id=r['id'],revision=r['revision']) for r in rows]
        if b.get('snapshot')!=snapshot:raise ValueError('时间轴列表已变化，请重新打开后排序')
        order=b.get('order')
        if not isinstance(order,list) or any(not isinstance(r,str) for r in order) or len(order)!=len(rows) or set(order)!={r['id'] for r in rows}:
            raise ValueError('请提交当前语言的完整时间轴顺序，不得重复或跨语言')
        if order!=[r['id'] for r in rows]:
            for position,rid in enumerate(order):
                db.execute('UPDATE timeline_sessions SET position=?,revision=revision+1 WHERE id=?',(position,rid))
        return {'ok':True,'sessions':listing(db,lid)}
    if action=='create':
        mid=register(db,lid,asset) if asset else '';sid=uid();name=str(b.get('name') or (asset['name'] if asset else '未命名时间轴')).strip()[:200] or '未命名时间轴'
        db.execute('INSERT INTO timeline_sessions(id,language_id,name,media_id,position,revision) VALUES(?,?,?,?,?,1)',(sid,lid,name,mid,first_position(db,lid)))
        db.execute('INSERT INTO timeline_tracks(id,session_id,name,kind,position,color,revision) VALUES(?,?,?,?,?,?,1)',(uid(),sid,'句子','sentence',0,timeline_colors.PALETTE[0]))
        return {'id':sid}
    s=session(db,lid,b['id']);check_revision(s,b);sid=s['id']
    if action=='duplicate':
        new_id=uid();name=str(b.get('name') or s['name']+' · 副本').strip()[:200]
        db.execute('INSERT INTO timeline_sessions(id,language_id,name,media_id,position,revision) VALUES(?,?,?,?,?,1)',(new_id,lid,name,s['media_id'],first_position(db,lid)))
        tracks={t['id']:uid() for t in db.execute('SELECT id FROM timeline_tracks WHERE session_id=?',(sid,))}
        intervals={i['id']:uid() for i in db.execute('SELECT id FROM timeline_intervals WHERE session_id=?',(sid,))}
        for t in db.execute('SELECT * FROM timeline_tracks WHERE session_id=?',(sid,)).fetchall():
            db.execute('INSERT INTO timeline_tracks(id,session_id,name,kind,position,parent_id,speaker_id,color) VALUES(?,?,?,?,?,?,?,?)',(tracks[t['id']],new_id,t['name'],t['kind'],t['position'],tracks.get(t['parent_id']),t['speaker_id'],t['color']))
        for i in db.execute('SELECT * FROM timeline_intervals WHERE session_id=?',(sid,)).fetchall():
            db.execute('INSERT INTO timeline_intervals(id,session_id,track_id,entry_id,label,status,start_ms,end_ms,parent_id,code_id) VALUES(?,?,?,?,?,?,?,?,?,?)',(intervals[i['id']],new_id,tracks[i['track_id']],i['entry_id'],i['label'],i['status'],i['start_ms'],i['end_ms'],intervals.get(i['parent_id']),i['code_id']))
        for link in db.execute('SELECT l.* FROM code_time_links l JOIN timeline_intervals i ON i.id=l.interval_id WHERE i.session_id=?',(sid,)).fetchall():
            db.execute('INSERT INTO code_time_links VALUES(?,?,?,1)',(uid(),link['span_id'],intervals[link['interval_id']]))
        return {'id':new_id}
    if action=='delete':
        if b.get('confirmed') is not True:raise ValueError('请确认删除时间轴；原句和媒体文件会保留')
        for table in ('timeline_intervals','timeline_tracks'):
            db.execute('DELETE FROM '+table+' WHERE session_id=?',(sid,))
        db.execute('DELETE FROM timeline_text_orders WHERE session_id=?',(sid,))
        db.execute('DELETE FROM timeline_sessions WHERE id=?',(sid,))
        return {'id':sid,'ok':True}
    order_result=None
    if action=='text-order':
        order_result=text_order.set_enabled(db,lid,sid,b)
    elif action=='rename':
        name=str(b.get('name','')).strip()[:200]
        if not name:raise ValueError('请填写时间轴名称')
        db.execute('UPDATE timeline_sessions SET name=? WHERE id=?',(name,sid))
    elif action=='replace-preview':return replacement(db,lid,b,asset)
    elif action=='replace':
        plan=replacement(db,lid,b,asset)
        if b.get('confirmed') is not True or b.get('token')!=plan['token']:raise ValueError('请重新预览并确认换源')
        mid=register(db,lid,asset)
        db.execute('UPDATE timeline_sessions SET media_id=? WHERE id=?',(mid,sid))
        if s['name']=='未命名时间轴' or (s['media_id'] and s['name']==media_view(db,s['media_id'])['name']):
            db.execute('UPDATE timeline_sessions SET name=? WHERE id=?',(asset['name'][:200],sid))
        db.execute('UPDATE timeline_intervals SET start_ms=start_ms+?,end_ms=end_ms+?,revision=revision+1 WHERE session_id=?',(plan['offset_ms'],plan['offset_ms'],sid))
    elif action=='track':
        hierarchy.track_save(db,sid,b,require)
    elif action=='delete-track':
        track=require(db,'timeline_tracks',b.get('track_id'))
        if track['session_id']!=sid:raise ValueError('轨道不属于此时间轴')
        if b.get('confirmed') is not True:raise ValueError('请确认删除空轨道')
        if db.execute('SELECT 1 FROM timeline_tracks WHERE parent_id=?',(track['id'],)).fetchone() or db.execute('SELECT 1 FROM timeline_intervals WHERE track_id=?',(track['id'],)).fetchone():raise ValueError('请先处理子轨道与标注区间，才能删除空轨道')
        db.execute('DELETE FROM timeline_tracks WHERE id=?',(track['id'],))
    elif action in ('interval','delete-interval','split','merge'):
        existing=require(db,'timeline_intervals',b['interval_id']) if b.get('interval_id') else None
        if existing and existing['session_id']!=sid:raise ValueError('区间不属于此时间轴')
        if action=='delete-interval':
            if not existing or b.get('confirmed') is not True:raise ValueError('请确认仅删除时间区间')
            children=hierarchy.subtree(db,'timeline_intervals',existing['id'])
            if children and b.get('include_children') is not True:raise ValueError('此区间包含子标注，请确认一并删除所有子区间；原句仍保留')
            for child in children:db.execute('DELETE FROM timeline_intervals WHERE id=?',(child['id'],))
            db.execute('DELETE FROM timeline_intervals WHERE id=?',(existing['id'],))
        elif action=='split':
            if not existing:raise ValueError('请选择区间')
            at=number(b.get('at_ms'))
            if not existing['start_ms']<at<existing['end_ms']:raise ValueError('播放头必须位于区间内部')
            children=[dict(r) for r in db.execute('SELECT * FROM timeline_intervals WHERE parent_id=?',(existing['id'],))]
            if any(c['start_ms']<at<c['end_ms'] for c in children):raise ValueError('拆分点穿过子区间，请先调整或拆分子标注')
            new_interval=uid()
            db.execute('UPDATE timeline_intervals SET end_ms=?,revision=revision+1 WHERE id=?',(at,existing['id']))
            db.execute('INSERT INTO timeline_intervals(id,session_id,track_id,entry_id,label,status,start_ms,end_ms,revision) VALUES(?,?,?,?,?,?,?,?,1)',(new_interval,sid,existing['track_id'],existing['entry_id'],existing['label'],existing['status'],at,existing['end_ms']))
            db.execute('UPDATE timeline_intervals SET parent_id=?,code_id=? WHERE id=?',(existing['parent_id'],existing['code_id'],new_interval))
            db.execute('DELETE FROM code_time_links WHERE interval_id=?',(existing['id'],))
            for child in children:
                if child['start_ms']>=at:db.execute('UPDATE timeline_intervals SET parent_id=?,revision=revision+1 WHERE id=?',(new_interval,child['id']))
        elif action=='merge':
            other=require(db,'timeline_intervals',b.get('other_id'))
            if not existing or other['id']==existing['id'] or any(other[k]!=existing[k] for k in ('session_id','track_id','entry_id','status','parent_id','code_id')) or (other['label']!=existing['label'] and not existing['code_id']):raise ValueError('只能合并同轨道、同一句子或同一事件及状态的区间')
            start=min(existing['start_ms'],other['start_ms']);end=max(existing['end_ms'],other['end_ms'])
            collision(db,sid,existing['track_id'],start,end,[existing['id'],other['id']])
            code_links=[db.execute('SELECT span_id FROM code_time_links WHERE interval_id=?',(iid,)).fetchone() for iid in (existing['id'],other['id'])]
            if (code_links[0][0] if code_links[0] else None)!=(code_links[1][0] if code_links[1] else None):
                db.execute('DELETE FROM code_time_links WHERE interval_id IN (?,?)',(existing['id'],other['id']))
            db.execute('UPDATE timeline_intervals SET parent_id=?,revision=revision+1 WHERE parent_id=?',(existing['id'],other['id']))
            db.execute('DELETE FROM timeline_intervals WHERE id=?',(other['id'],))
            db.execute('UPDATE timeline_intervals SET start_ms=?,end_ms=?,revision=revision+1 WHERE id=?',(start,end,existing['id']))
        else:
            track=require(db,'timeline_tracks',b.get('track_id'))
            if track['session_id']!=sid:raise ValueError('轨道不属于此时间轴')
            start=number(b.get('start_ms'));end=number(b.get('end_ms'))
            if end<=start:raise ValueError('结束时间须晚于开始时间')
            entry=b.get('entry_id') or None;label=str(b.get('label','')).strip()[:2000];status=b.get('status','confirmed')
            if status not in ('confirmed','review'):raise ValueError('无效确认状态')
            if track['kind']=='sentence':
                e=db.execute('SELECT t.language_id FROM entries e JOIN texts t ON t.id=e.text_id WHERE e.id=?',(entry,)).fetchone()
                if isinstance(entry,str) and entry.startswith('independent:'):e=db.execute('SELECT language_id FROM dictionary_examples WHERE id=?',(entry.removeprefix('independent:'),)).fetchone()
                if not e or e[0]!=lid:raise ValueError('请选择本语言的一条现存句子')
                label=''
            elif track['kind']=='language':
                if entry:raise ValueError('语言片段通过父句关联正文，不重复关联句子')
                code=b.get('code_id',existing['code_id'] if existing else None) or None
                label=require(db,'timeline_codes',code)['name'] if code else '未确定'
            elif not label or entry:raise ValueError('事件轨道请填写标签，不关联语料句子')
            code=code if track['kind']=='language' else None
            parent=hierarchy.parent_for(db,track,start,end,b.get('parent_id',existing['parent_id'] if existing else None))
            if existing:hierarchy.prepare_children(db,existing,start,end,track['id'],entry,collision)
            collision(db,sid,track['id'],start,end,[existing['id']] if existing else [])
            if existing:db.execute('UPDATE timeline_intervals SET track_id=?,entry_id=?,label=?,status=?,start_ms=?,end_ms=?,revision=revision+1 WHERE id=?',(track['id'],entry,label,status,start,end,existing['id']))
            else:
                existing={'id':uid()}
                db.execute('INSERT INTO timeline_intervals(id,session_id,track_id,entry_id,label,status,start_ms,end_ms,revision) VALUES(?,?,?,?,?,?,?,?,1)',(existing['id'],sid,track['id'],entry,label,status,start,end))
            db.execute('UPDATE timeline_intervals SET parent_id=?,code_id=? WHERE id=?',(parent,code,existing['id']))
    else:raise ValueError('未知时间轴操作')
    hierarchy.validate(db,sid)
    renumbered=order_result['renumbered'] if order_result else text_order.sync_session(db,sid) if action in ('interval','delete-interval','split','merge','replace') else 0
    db.execute('UPDATE timeline_sessions SET revision=revision+1 WHERE id=?',(sid,))
    return {'id':sid,'ok':True,'renumbered':renumbered,**({'text_order':order_result} if order_result else {})}

def collision(db,sid,track,start,end,excluded):
    rows=db.execute('SELECT id FROM timeline_intervals WHERE session_id=? AND track_id=? AND start_ms<? AND end_ms>?',(sid,track,end,start))
    if any(r[0] not in excluded for r in rows):raise ValueError('同轨道区间不能重叠；请调整边界或使用另一条轨道')

def export_bundle(db,lid):
    sessions=listing(db,lid);ids=[s['id'] for s in sessions]
    for s in sessions:s.pop('media_name',None)
    links=[dict(r) for r in db.execute('SELECT * FROM object_media WHERE language_id=?',(lid,))]
    media_ids={s['media_id'] for s in sessions}|{r['asset_id'] for r in links}
    return {'timeline_text_orders':[dict(r) for r in db.execute('SELECT o.* FROM timeline_text_orders o JOIN texts t ON t.id=o.id WHERE t.language_id=?',(lid,))],'object_media':links,**{'timeline_speakers':[dict(r) for r in db.execute('SELECT * FROM timeline_speakers WHERE id IN (SELECT speaker_id FROM timeline_tracks WHERE session_id IN (SELECT id FROM timeline_sessions WHERE language_id=?))',(lid,))],'timeline_codes':[dict(r) for r in db.execute('SELECT * FROM timeline_codes WHERE id IN (SELECT code_id FROM timeline_intervals WHERE session_id IN (SELECT id FROM timeline_sessions WHERE language_id=?))',(lid,))]},'timeline_sessions':sessions,'timeline_media':[dict(r) for r in db.execute('SELECT * FROM timeline_media WHERE language_id=?',(lid,)) if r['id'] in media_ids],**{t:[dict(r) for r in db.execute('SELECT * FROM '+t) if r['session_id'] in ids] for t in ('timeline_tracks','timeline_intervals')}}

def import_bundle(db,bundle,lid,entries,writing_map=None,language_map=None,media_files=None,object_maps=None):
    maps={t:{r['id']:uid() for r in bundle.get(t,[])} for t in TABLES};orphans={}
    writing_map=dict(writing_map or {})
    for w in long_tasks.steps(bundle.get('collaborator_writing_types',[])):
        if w['id'] not in writing_map:
            import dictionary_data
            name=w['name'];n=1
            while db.execute('SELECT 1 FROM writing_types WHERE language_id=? AND name=?',(lid,name)).fetchone():
                n+=1;name=w['name']+'（合作者导入 '+str(n)+'）'
            writing_map[w['id']]=dictionary_data.mutate(db,'writing-save',dict(name=name,font=w['font'],position=w.get('position',0)),lid)['id']
    session_positions={r['id']:i for i,r in enumerate(bundle.get('timeline_sessions',[]))}
    for table in long_tasks.steps(TABLES):
        for original in long_tasks.steps(bundle.get(table,[])):
            row={k:v for k,v in original.items() if k in {c['name'] for c in db.execute('PRAGMA table_info('+table+')')}}
            row['id']=maps[table][original['id']];row['revision']=1
            if table=='timeline_text_orders':
                row['id']=(object_maps or {}).get('texts',{}).get(original['id'])
                if not row['id']:raise ValueError('自动排序设置缺少所属文本')
                text_order.text(db,lid,row['id'])
            if table=='timeline_speakers':
                meta=json.loads(row['metadata'])
                if 'language_ids' in meta:meta['language_ids']=list(dict.fromkeys((language_map or {bundle.get('language',{}).get('id'):lid}).get(x,x) for x in meta['language_ids']))
                for f in long_tasks.steps(meta.get('fields',[])):
                    if f.get('type_id'):
                        if f['type_id'] not in writing_map:raise ValueError('合作者交换数据缺少书写类型')
                        f['type_id']=writing_map[f['type_id']]
                row['metadata']=json.dumps(meta,ensure_ascii=False)
            if table=='timeline_codes':
                meta=json.loads(row['metadata'])
                if meta.get('workspace_language_id'):
                    if meta['workspace_language_id'] not in (language_map or {}):raise ValueError('语言标记缺少对应工作区信息')
                    meta['workspace_language_id']=language_map[meta['workspace_language_id']]
                row['metadata']=json.dumps(meta,ensure_ascii=False)
            if 'language_id' in row:row['language_id']=lid
            if table=='timeline_sessions':
                position=row.get('position',session_positions[original['id']])
                if isinstance(position,bool) or not isinstance(position,int) or abs(position)>10**12:raise ValueError('时间轴顺序格式无效')
                row['position']=position
            for field,target in long_tasks.steps([('media_id','timeline_media'),('session_id','timeline_sessions'),('track_id','timeline_tracks'),('speaker_id','timeline_speakers'),('code_id','timeline_codes'),('parent_id','timeline_tracks' if table=='timeline_tracks' else 'timeline_intervals')]):
                if field in row:
                    if not row[field]:continue
                    if row[field] not in maps[target]:raise ValueError('时间轴交换数据缺少引用对象')
                    row[field]=maps[target][row[field]]
            if table=='timeline_intervals':
                if row.get('entry_id'):
                    old=row['entry_id']
                    row['entry_id']=entries.get(old) or orphans.setdefault(old,uid())
                if number(row['end_ms'])<=number(row['start_ms']):raise ValueError('无效时间区间')
                collision(db,row['session_id'],row['track_id'],row['start_ms'],row['end_ms'],[])
            if table=='timeline_tracks':
                row['color']=timeline_colors.clean(row.get('color'))
                if not row.get('parent_id') and row['color'] is None:row['color']=timeline_colors.next_color(db,row['session_id'])
            if table=='timeline_media':
                # Imported paths are inert until the user explicitly locates the media.
                row['storage']='copy' if original['id'] in (media_files or {}) else 'missing';row['path']=(media_files or {}).get(original['id'],{}).get('path','')
                if row['storage']=='copy':
                    meta=json.loads(row['metadata']);meta['fingerprint']=media_files[original['id']]['fingerprint'];row['metadata']=json.dumps(meta,ensure_ascii=False)
            db.execute('INSERT INTO '+table+' ('+','.join(row)+') VALUES ('+','.join('?' for _ in row)+')',list(row.values()))

    for original in long_tasks.steps(bundle.get('object_media',[])):
        import object_media
        kind=original['kind'];target_map=(object_maps or {}).get({'lexeme':'lexemes','morpheme':'morphemes','independent':'examples'}.get(kind,''),{})
        try:
            rid=target_map[original['record_id']];asset_id=maps['timeline_media'][original['asset_id']]
            body=json.loads(original['body']);body['speakers']=[maps['timeline_speakers'][p] for p in body.get('speakers',[])]
            if body.get('target_id'):body['target_id']=object_maps['subparts'].get((original['record_id'],body['target_id']),body['target_id'])
        except KeyError:raise ValueError('媒体关联缺少目标、形式或发言人')
        row=object_media.owner(db,kind,rid);asset=media_view(db,asset_id)
        body=object_media.validate_body(db,body,asset,row,kind)
        db.execute('INSERT INTO object_media VALUES(?,?,?,?,?,?,?,1)',(uid(),row['language_id'],kind,rid,asset_id,json.dumps(body,ensure_ascii=False),original['position']))
    hierarchy.validate(db)
    if object_maps is not None:object_maps['timeline_maps']=maps
    return maps['timeline_speakers']
