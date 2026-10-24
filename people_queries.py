"""Shared attribution for research filters and time-ordered conversation reading."""
import json
from collections import Counter

def normalize(scope):
    out={}
    for key in ('speaker_ids','collaborator_ids'):
        v=scope.get(key,[])
        if not isinstance(v,list) or len(v)>200 or any(not isinstance(x,str) or not x or len(x)>200 for x in v):raise ValueError('人员筛选无效')
        out[key]=list(dict.fromkeys(v))
    for key,values,default in [('speaker_match',('any','all'),'any'),('collaborator_match',('any','all'),'any'),('speaker_state',('any','assigned','unassigned','conflict'),'any'),('source',('all','corpus','independent'),'corpus')]:
        out[key]=scope.get(key,default)
        if out[key] not in values:raise ValueError('人员或材料筛选方式无效')
    out['collaborator_role']=scope.get('collaborator_role','')
    if not isinstance(out['collaborator_role'],str) or len(out['collaborator_role'])>100:raise ValueError('参与角色无效')
    return out

def includes(actual,wanted,mode):
    return not wanted or (set(wanted)<=set(actual) if mode=='all' else bool(set(wanted)&set(actual)))

class Context:
    def __init__(self,db):
        self.people={r['id']:r['name'] for r in db.execute('SELECT id,name FROM timeline_speakers')}
        self.manual={};self.texts={};self.inherited={}
        for r in db.execute('SELECT kind,record_id,mode,people FROM collaborator_assignments'):
            refs=json.loads(r['people'])
            if r['kind']=='text':self.texts[r['record_id']]=refs
            elif r['mode']=='manual':self.manual[(r['kind'],r['record_id'])]=list(dict.fromkeys(p['person_id'] for p in refs))
        for r in db.execute("SELECT DISTINCT i.entry_id,t.speaker_id FROM timeline_intervals i JOIN timeline_tracks t ON t.id=i.track_id WHERE i.entry_id IS NOT NULL AND t.kind='sentence' AND t.speaker_id IS NOT NULL"):
            self.inherited.setdefault(r['entry_id'],set()).add(r['speaker_id'])

    def attribution(self,kind,rid,interval_speaker=None,local=False):
        manual=self.manual.get((kind,rid))
        if manual is not None:ids=manual
        elif local:ids=[interval_speaker] if interval_speaker else []
        elif kind in ('corpus','independent'):ids=sorted(self.inherited.get(('independent:' if kind=='independent' else '')+rid,()))
        else:ids=[]
        return dict(ids=ids,names=[self.people.get(p,'已删除合作者') for p in ids],mode='manual' if manual is not None else 'auto',conflict=not local and manual is None and len(ids)>1)

    def text_matches(self,tid,q):
        refs=[p for p in self.texts.get(tid,[]) if not q['collaborator_role'] or p['role']==q['collaborator_role']]
        return (not q['collaborator_role'] or bool(refs)) and includes([p['person_id'] for p in refs],q['collaborator_ids'],q['collaborator_match'])

    def sentence_matches(self,a,q):
        state='conflict' if a['conflict'] else 'assigned' if a['ids'] else 'unassigned'
        if q['speaker_state']!='any' and q['speaker_state']!=state:return False
        if q['speaker_ids'] and a['conflict']:return False
        return includes(a['ids'],q['speaker_ids'],q['speaker_match'])

def dialogue(db,lid,q):
    tid=q.get('text_id','');text=db.execute('SELECT * FROM texts WHERE id=?',(tid,)).fetchone()
    if not text or lid not in ('all',text['language_id']):raise ValueError('请选择当前语言的文本')
    sessions=[dict(r) for r in db.execute('''SELECT s.id,s.name,COUNT(i.id) aligned FROM timeline_sessions s LEFT JOIN timeline_intervals i ON i.session_id=s.id AND i.entry_id IN (SELECT id FROM entries WHERE text_id=?) WHERE s.language_id=? GROUP BY s.id ORDER BY s.rowid''',(tid,text['language_id']))]
    sid=q.get('session_id','')
    if not sid:return dict(sessions=sessions,items=[],total=0,page=1,pages=1)
    if sid not in {s['id'] for s in sessions}:raise ValueError('时间轴已不存在或属于另一语言，请重新选择')
    tracks=[dict(r) for r in db.execute('SELECT * FROM timeline_tracks WHERE session_id=? ORDER BY position,rowid',(sid,))]
    # Match TimelineTree.rows: roots grouped by first occurrence of speaker, then children.
    groups={};children={};order={}
    for t in tracks:
        (children if t['parent_id'] else groups).setdefault(t['parent_id'] or t['speaker_id'] or '',[]).append(t)
    def visit(t):
        order[t['id']]=len(order)
        for c in children.get(t['id'],[]):visit(c)
    for roots in groups.values():
        for t in roots:visit(t)
    ctx=Context(db)
    rows=[dict(r) for r in db.execute('''SELECT i.id interval_id,i.entry_id,i.start_ms,i.end_ms,i.track_id,t.name track_name,t.speaker_id,e.position FROM timeline_intervals i JOIN timeline_tracks t ON t.id=i.track_id JOIN entries e ON e.id=i.entry_id WHERE i.session_id=? AND e.text_id=? AND t.kind='sentence' ''',(sid,tid))]
    rows.sort(key=lambda r:(r['start_ms'],order[r['track_id']],r['position'],r['interval_id']))
    counts=Counter(r['entry_id'] for r in rows);component=-1;component_end=None;components={}
    for r in rows:
        if component_end is None or r['start_ms']>=component_end:component+=1;component_end=r['end_ms']
        else:component_end=max(component_end,r['end_ms'])
        r['overlap_group']=component;components.setdefault(component,[]).append(r)
        r['attribution']=ctx.attribution('corpus',r['entry_id'],r['speaker_id'],True);r['occurrences']=counts[r['entry_id']]
    for group in components.values():
        for r in group:r['overlap']=len(group)>1
    unaligned=[dict(r) for r in db.execute('SELECT id entry_id,position FROM entries WHERE text_id=? ORDER BY position',(tid,)) if r['entry_id'] not in counts]
    for r in unaligned:r.update(interval_id=None,attribution=ctx.attribution('corpus',r['entry_id']),occurrences=0)
    allrows=rows+unaligned;ids={p for r in allrows for p in r['attribution']['ids']};single=next(iter(ids)) if len(ids)==1 else None
    size=max(10,min(100,int(q.get('page_size',20))));pages=max(1,(len(allrows)+size-1)//size);page=max(1,min(pages,int(q.get('page',1))));chosen=allrows[(page-1)*size:page*size]
    import analysis_workspace
    records=analysis_workspace.materialize(db,[{'entry_id':r['entry_id']} for r in chosen])
    # Reuse the corpus display enrichment so dictionary links remain editable here.
    import corpus,lexicon
    bodies=[]
    for record in records.values():
        record['body']=corpus.analyze({**record['body'],'id':record['id'],'text_language_id':record['owner_language']})
        bodies.append(record['body'])
    lexicon.enrich(db,bodies)
    for r in chosen:r['record']=records[r['entry_id']]
    return dict(sessions=sessions,items=chosen,page=page,pages=pages,total=len(allrows),aligned=len(rows),unaligned=len(unaligned),sentences=len(counts)+len(unaligned),single_speaker=single,speaker_names=ctx.people,session_id=sid)
