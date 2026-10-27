"""Reusable people and role-bearing references. Timeline attribution is derived, never copied."""
import long_tasks
import json
import uuid
import annotations

TABLES=('collaborator_assignments',)
LEGACY={'speakers':'发言人','speaker_home':'发言人籍贯／常住地','recorder':'调查人／记录人','transcriber':'转写／翻译／标注人','reviewer':'校对人'}

def initialize(db):
    db.execute("CREATE TABLE IF NOT EXISTS collaborator_assignments(id TEXT PRIMARY KEY,kind TEXT NOT NULL,record_id TEXT NOT NULL,people TEXT NOT NULL DEFAULT '[]',mode TEXT NOT NULL DEFAULT 'auto',revision INTEGER NOT NULL DEFAULT 1,UNIQUE(kind,record_id))")
    for row in db.execute('SELECT * FROM text_info').fetchall():
        m=json.loads(row['metadata']);old={k:m.pop(k) for k in LEGACY if k in m}
        if old:
            legacy=m.setdefault('legacy_people',{})
            for k,v in old.items():
                if v:legacy[k]=v
            db.execute('UPDATE text_info SET metadata=?,revision=revision+1 WHERE text_id=?',(json.dumps(m,ensure_ascii=False),row['text_id']))

def owner(db,kind,rid):
    if kind=='text':
        row=db.execute('SELECT language_id FROM texts WHERE id=?',(rid,)).fetchone()
        if not row:raise ValueError('文本已不存在')
        return row[0]
    return annotations.owner(db,kind,rid)[2]

def validate_people(db,people):
    if not isinstance(people,list) or len(people)>200:raise ValueError('合作者列表无效或过长')
    seen=set()
    for p in people:
        if not isinstance(p,dict) or not isinstance(p.get('role'),str) or not p['role'].strip() or len(p['role'])>100:raise ValueError('请填写参与角色')
        if not isinstance(p.get('person_id'),str) or not db.execute('SELECT 1 FROM timeline_speakers WHERE id=?',(p['person_id'],)).fetchone():raise ValueError('合作者已不存在，请重新选择')
        key=(p['person_id'],p['role'])
        if key in seen:raise ValueError('同一个合作者和角色不能重复')
        seen.add(key)

def save(db,b,lid):
    kind,rid=b['kind'],b['id']
    if owner(db,kind,rid)!=lid:raise ValueError('材料语言范围已变化')
    row=db.execute('SELECT * FROM collaborator_assignments WHERE kind=? AND record_id=?',(kind,rid)).fetchone()
    if b.get('revision')!=(row['revision'] if row else 0):raise ValueError('合作者关联已变化，请重新打开')
    people=b.get('people',[])
    mode=b.get('mode','manual')
    if mode not in ('auto','manual'):raise ValueError('发言人指定方式无效')
    if kind!='text' and mode=='auto':people=[]
    validate_people(db,people)
    if kind!='text' and any(p['role']!='发言人' for p in people):raise ValueError('逐句关联请选择发言人')
    key=row['id'] if row else str(uuid.uuid4())
    db.execute('INSERT INTO collaborator_assignments(id,kind,record_id,people,mode) VALUES(?,?,?,?,?) ON CONFLICT(kind,record_id) DO UPDATE SET people=excluded.people,mode=excluded.mode,revision=collaborator_assignments.revision+1',(key,kind,rid,json.dumps(people,ensure_ascii=False),mode))
    return {'ok':True}

def batch(db,kind,ids):
    if kind not in ('text','corpus','independent') or len(ids)>200:raise ValueError('关联查询范围无效')
    ids=list(dict.fromkeys(ids));result={i:dict(revision=0,mode='auto',people=[],inherited=[],conflict=False) for i in ids}
    if not ids:return result
    marks=','.join('?' for _ in ids)
    for r in db.execute(f'SELECT * FROM collaborator_assignments WHERE kind=? AND record_id IN ({marks})',[kind,*ids]):
        result[r['record_id']].update(revision=r['revision'],mode=r['mode'],people=json.loads(r['people']))
    if kind in ('corpus','independent'):
        alignment_ids=['independent:'+rid if kind=='independent' else rid for rid in ids]
        # Sentence tracks are top-level; no per-sentence catalogue scan or corpus rewrites.
        for r in db.execute(f'''SELECT DISTINCT i.entry_id,t.speaker_id FROM timeline_intervals i JOIN timeline_tracks t ON t.id=i.track_id WHERE i.entry_id IN ({marks}) AND t.kind='sentence' AND t.speaker_id IS NOT NULL''',alignment_ids):
            result[r['entry_id'].removeprefix('independent:') if kind=='independent' else r['entry_id']]['inherited'].append({'person_id':r['speaker_id'],'role':'发言人'})
    for r in result.values():
        r['effective']=r['people'] if kind=='text' or r['mode']=='manual' else r['inherited']
        r['conflict']=len(r['inherited'])>1 and r['mode']=='auto'
    return result

def referenced(db,pid):
    if db.execute("SELECT 1 FROM survey_evidence e,json_each(e.body,'$.member_notes') n,json_each(n.value,'$.judges') p WHERE p.value=? LIMIT 1",(pid,)).fetchone():return True
    if db.execute("SELECT 1 FROM object_media m,json_each(m.body,'$.speakers') p WHERE p.value=? LIMIT 1",(pid,)).fetchone():return True
    if db.execute("SELECT 1 FROM survey_evidence e,json_each(e.body,'$.judges') p WHERE p.value=? LIMIT 1",(pid,)).fetchone():return True
    return db.execute("SELECT 1 FROM collaborator_assignments a,json_each(a.people) p WHERE json_extract(p.value,'$.person_id')=? LIMIT 1",(pid,)).fetchone() is not None

def validate_profile(db,m):
    language_ids=m.get('language_ids',[])
    if not isinstance(language_ids,list) or len(language_ids)>500 or any(not isinstance(v,str) or not v or len(v)>200 for v in language_ids):raise ValueError('参与语言列表无效')
    if not isinstance(m.get('classes',[]),list) or any(not isinstance(v,str) or not v.strip() or len(v)>100 for v in m.get('classes',[])):raise ValueError('合作者类别无效')
    fields=m.get('fields',[])
    if not isinstance(fields,list) or len(fields)>200:raise ValueError('自定义字段无效或过多')
    for f in fields:
        if not isinstance(f,dict) or not isinstance(f.get('name'),str) or not f['name'].strip() or not isinstance(f.get('value'),str):raise ValueError('请填写字段名称及内容')
        if f.get('type_id') and not db.execute('SELECT 1 FROM writing_types WHERE id=?',(f['type_id'],)).fetchone():raise ValueError('合作者引用的书写类型不存在，请先调整引用')

def validate(db):
    if not db.execute("SELECT 1 FROM sqlite_master WHERE name='collaborator_assignments'").fetchone():return
    for r in db.execute('SELECT people FROM collaborator_assignments'):validate_people(db,json.loads(r[0]))
    for r in db.execute('SELECT metadata FROM timeline_speakers'):validate_profile(db,json.loads(r[0]))

def export_bundle(db,lid):
    links=[dict(r) for r in db.execute('''SELECT a.* FROM collaborator_assignments a WHERE
      (kind='text' AND record_id IN (SELECT id FROM texts WHERE language_id=?)) OR
      (kind='corpus' AND record_id IN (SELECT e.id FROM entries e JOIN texts t ON t.id=e.text_id WHERE t.language_id=?)) OR
      (kind='independent' AND record_id IN (SELECT id FROM dictionary_examples WHERE language_id=?))''',(lid,lid,lid))]
    pids={p['person_id'] for a in links for p in json.loads(a['people'])}
    pids.update(p for r in db.execute('SELECT body FROM survey_evidence WHERE language_id=?',(lid,)) for p in json.loads(r[0]).get('judges',[]))
    pids.update(p for r in db.execute('SELECT body FROM survey_evidence WHERE language_id=?',(lid,)) for n in json.loads(r[0]).get('member_notes',{}).values() for p in n.get('judges',[]))
    pids.update(r[0] for r in db.execute('SELECT t.speaker_id FROM timeline_tracks t JOIN timeline_sessions s ON s.id=t.session_id WHERE s.language_id=? AND t.speaker_id IS NOT NULL',(lid,)))
    pids.update(p for r in db.execute('SELECT body FROM object_media WHERE language_id=?',(lid,)) for p in json.loads(r[0]).get('speakers',[]))
    people=[dict(r) for r in db.execute('SELECT * FROM timeline_speakers') if r['id'] in pids]
    tids={f['type_id'] for p in people for f in json.loads(p['metadata']).get('fields',[]) if f.get('type_id')}
    return dict(collaborator_assignments=links,timeline_speakers=people,collaborator_writing_types=[dict(r) for r in db.execute('SELECT * FROM writing_types') if r['id'] in tids])

def import_links(db,bundle,maps,people):
    for row in long_tasks.steps(bundle.get('collaborator_assignments',[])):
        try:
            rid=maps[row['kind']][row['record_id']]
            refs=[{**p,'person_id':people[p['person_id']]} for p in json.loads(row['people'])]
        except (KeyError,TypeError):raise ValueError('合作者交换数据缺少关联对象')
        save(db,dict(kind=row['kind'],id=rid,revision=0,people=refs,mode=row['mode']),owner(db,row['kind'],rid))

def copy_sentence(db,source,target):
    r=batch(db,'corpus',[source])[source]
    if r['effective']:
        save(db,dict(kind='corpus',id=target,revision=0,people=r['effective'],mode='manual'),owner(db,'corpus',target))

def text_names(db):
    out={}
    for r in db.execute("SELECT a.record_id,p.name FROM collaborator_assignments a,json_each(a.people) j JOIN timeline_speakers p ON p.id=json_extract(j.value,'$.person_id') WHERE a.kind='text' AND json_extract(j.value,'$.role')='发言人'"):
        out.setdefault(r[0],[]).append(r[1])
    return {k:'、'.join(v) for k,v in out.items()}

def cleanup(db,changes):
    for (table,_),(before,after) in list(changes.items()):
        kind={'texts':'text','entries':'corpus','dictionary_examples':'independent'}.get(table)
        if kind and before and not after:
            db.execute('DELETE FROM collaborator_assignments WHERE kind=? AND record_id=?',(kind,before['id']))

def combine_text(db,source,target):
    a=batch(db,'text',[source])[source];b=batch(db,'text',[target])[target]
    people=b['people'][:]
    for p in a['people']:
        if p not in people:people.append(p)
    if people:save(db,dict(kind='text',id=target,revision=b['revision'],people=people,mode='manual'),owner(db,'text',target))

def validate_changes(db,changes):
    for (table,_),(before,after) in changes.items():
        if table=='collaborator_assignments' and after:validate_people(db,json.loads(after['people']))
        if table=='timeline_speakers':
            if after:validate_profile(db,json.loads(after['metadata']))
            elif before and referenced(db,before['id']):raise ValueError('合作者仍被材料引用，不能删除')
