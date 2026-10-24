"""Editable fieldwork outlines and references to live sentences (never sentence copies)."""
import long_tasks
import hashlib
import json
import uuid

TABLES = ('survey_nodes', 'survey_evidence')
TEMPLATE = [
    ('构词、构形手段', ['名词', '数词、量词', '动词', '形容词、状态词', '拟声词']),
    ('名词短语', ['名词及相关范畴', '数量结构与量化表达', '人称代词', '指示代词及相关指称表达', '疑问代词与不定代词', '领属结构、关系从句等定中结构', '并列结构、同位语结构']),
    ('动词短语', ['动补结构', '介宾结构', '副词等其他状语', '体貌', '否定', '情态、示证', '致使']),
    ('句型、句式', ['基本句子结构', '话题、焦点', '比较句', '处置句与被动句', '领有句、存在句、处所句', '连动句、兼语句', '主从关系', '并列关系和主次关系']),
    ('句类', ['是非问句', '特指问句', '选择问句', '祈使句', '感叹句、语气词、叹词']),
]


def initialize(db):
    db.executescript('''
    CREATE TABLE IF NOT EXISTS survey_nodes(id TEXT PRIMARY KEY,language_id TEXT NOT NULL,parent_id TEXT,kind TEXT NOT NULL,title TEXT NOT NULL,position INTEGER NOT NULL,body TEXT NOT NULL,revision INTEGER NOT NULL DEFAULT 1);
    CREATE INDEX IF NOT EXISTS survey_parent ON survey_nodes(language_id,parent_id,position);
    CREATE TABLE IF NOT EXISTS survey_evidence(id TEXT PRIMARY KEY,language_id TEXT NOT NULL,node_id TEXT NOT NULL,kind TEXT NOT NULL,record_id TEXT NOT NULL,position INTEGER NOT NULL,body TEXT NOT NULL,revision INTEGER NOT NULL DEFAULT 1);
    CREATE INDEX IF NOT EXISTS survey_reference ON survey_evidence(kind,record_id);
    CREATE INDEX IF NOT EXISTS survey_question ON survey_evidence(node_id,position);
    ''')


def dump(value):return json.dumps(value, ensure_ascii=False)
def uid():return str(uuid.uuid4())


def rich(db, value, lid):
    if not isinstance(value, list) or len(value)>10000:raise ValueError('笔记格式无效或过长')
    out=[]
    for run in value:
        if not isinstance(run,dict) or not isinstance(run.get('text'),str):raise ValueError('文字片段格式无效')
        item={'text':run['text']}
        if len(item['text'])>100000:raise ValueError('文字片段过长')
        for key in ('bold','italic','highlight'):
            if run.get(key):item[key]=True
        if run.get('type_id'):
            if not db.execute('SELECT 1 FROM writing_types WHERE id=? AND language_id=?',(run['type_id'],lid)).fetchone():raise ValueError('书写类型不存在或不属于本语言')
            item['type_id']=run['type_id']
        out.append(item)
    if sum(len(r['text']) for r in out)>200000:raise ValueError('笔记过长')
    return out


def clean_body(db,b,lid,evidence=False):
    if not isinstance(b,dict):raise ValueError('调查内容格式无效')
    result={k:rich(db,b.get(k,[]),lid) for k in (('notes','context') if evidence else ('content','notes'))}
    if evidence:
        result['judgment']=str(b.get('judgment',''))[:200]
        result['judges']=list(dict.fromkeys(b.get('judges',[])))
        if len(result['judges'])>200 or any(not db.execute('SELECT 1 FROM timeline_speakers WHERE id=?',(p,)).fetchone() for p in result['judges']):raise ValueError('判断者已不存在')
    else:
        result['status']=b.get('status','unasked')
        if result['status'] not in ('unasked','followup','evidence','done'):raise ValueError('调查进度无效')
        result['template']=str(b.get('template',''))[:200]
    return result


def version(db,lid):
    rows=[list(r) for t in TABLES for r in db.execute('SELECT id,revision FROM '+t+' WHERE language_id=? ORDER BY id',(lid,))]
    return hashlib.sha256(dump(rows).encode()).hexdigest()


def listing(db,lid):
    nodes=[{**dict(r),'body':json.loads(r['body'])} for r in db.execute('SELECT n.*,(SELECT COUNT(*) FROM survey_evidence e WHERE e.node_id=n.id) evidence_count FROM survey_nodes n WHERE language_id=? ORDER BY position,rowid',(lid,))]
    return dict(nodes=nodes,version=version(db,lid),writing_types=[dict(r) for r in db.execute('SELECT * FROM writing_types WHERE language_id=? ORDER BY position,name',(lid,))],people=[dict(r) for r in db.execute('SELECT id,name FROM timeline_speakers ORDER BY name')])


def require(db,lid,nid):
    r=db.execute('SELECT * FROM survey_nodes WHERE id=? AND language_id=?',(nid,lid)).fetchone()
    if not r:raise ValueError('调查条目已不存在或语言不一致')
    return dict(r)

def saved_node(db,lid,nid):
    node=require(db,lid,nid);node['body']=json.loads(node['body'])
    node['evidence_count']=db.execute('SELECT COUNT(*) FROM survey_evidence WHERE node_id=?',(nid,)).fetchone()[0]
    return dict(id=nid,node=node,version=version(db,lid))


def descendants(db,lid,nid):
    rows=[dict(r) for r in db.execute('SELECT * FROM survey_nodes WHERE language_id=?',(lid,))]
    found={nid}
    while True:
        more={r['id'] for r in rows if r['parent_id'] in found}-found
        if not more:break
        found.update(more)
    return [r for r in rows if r['id'] in found]


def reference(db,kind,rid,lid):
    import annotations
    d=annotations.get(db,kind,rid)
    if d['language_id']!=lid:raise ValueError('请选择同语言的例句')
    from corpus import analyze
    d['body']=annotations.enrich(db,analyze(d['body']),kind,rid)
    return d


def detail(db,lid,nid,page=1):
    require(db,lid,nid)
    total=db.execute('SELECT COUNT(*) FROM survey_evidence WHERE node_id=?',(nid,)).fetchone()[0]
    pages=max(1,(total+19)//20);page=max(1,min(pages,int(page)));items=[]
    for r in db.execute('SELECT * FROM survey_evidence WHERE node_id=? ORDER BY position,rowid LIMIT 20 OFFSET ?',(nid,(page-1)*20)):
        item={**dict(r),'body':json.loads(r['body'])}
        try:
            d=reference(db,r['kind'],r['record_id'],lid)
            item['record']={'body':d['body'],'language_id':d['language_id'],'owner_language':d['owner_language']}
        except ValueError:item['record']=None
        items.append(item)
    return dict(items=items,page=page,pages=pages,total=total)


def insert_node(db,lid,parent,kind,title,body):
    nid=uid();position=db.execute('SELECT COALESCE(MAX(position),0)+1 FROM survey_nodes WHERE language_id=? AND parent_id IS ?',(lid,parent)).fetchone()[0]
    db.execute('INSERT INTO survey_nodes VALUES(?,?,?,?,?,?,?,1)',(nid,lid,parent,kind,title,position,dump(body)))
    return nid


def mutate(db,lid,action,b):
    if b.get('version')!=version(db,lid):raise ValueError('调查提纲已在其他窗口更新，请刷新后重试；当前草稿仍保留')
    if action=='move':
        ids=b.get('ids',[])
        if not isinstance(ids,list) or not ids or len(ids)>10000 or any(not isinstance(i,str) for i in ids):raise ValueError('请选择需要移动的条目')
        selected=set(ids)
        rows=[dict(r) for r in db.execute('SELECT * FROM survey_nodes WHERE language_id=? ORDER BY position,rowid',(lid,))]
        lookup={r['id']:r for r in rows}
        if not selected<=lookup.keys():raise ValueError('条目已不存在或不属于本语言')
        # Selected descendants travel with their selected ancestor, never flatten the subtree.
        roots=[]
        def visit(parent):
            for r in rows:
                if r['parent_id']!=parent:continue
                if r['id'] in selected:roots.append(r['id'])
                else:visit(r['id'])
        visit(None)
        forbidden={r['id'] for rid in roots for r in descendants(db,lid,rid)}
        parent=b.get('parent_id') or None;anchor=b.get('anchor_id') or None;placement=b.get('placement','end')
        if parent:
            p=require(db,lid,parent)
            if p['kind']!='section':raise ValueError('问题不能作为父条目')
            if parent in forbidden:raise ValueError('不能移入自身或自己的下级')
        if placement not in ('end','before','after'):raise ValueError('移动位置无效')
        siblings=[r['id'] for r in rows if r['parent_id']==parent and r['id'] not in roots]
        if placement!='end':
            if anchor not in siblings or anchor in forbidden:raise ValueError('目标位置无效')
            index=siblings.index(anchor)+(placement=='after')
        else:index=len(siblings)
        siblings[index:index]=roots
        for rid in roots:db.execute('UPDATE survey_nodes SET parent_id=?,revision=revision+1 WHERE id=?',(parent,rid))
        for pos,rid in enumerate(siblings):db.execute('UPDATE survey_nodes SET position=?,revision=revision+1 WHERE id=?',(pos,rid))
        return {'id':roots[0],'moved_ids':roots}
    if action=='notes':
        node=require(db,lid,b.get('id'));body=json.loads(node['body']);body['notes']=rich(db,b.get('notes',[]),lid)
        db.execute('UPDATE survey_nodes SET body=?,revision=revision+1 WHERE id=?',(dump(body),node['id']))
        return {'id':node['id']}
    if action=='template':
        roots=[]
        for name,children in TEMPLATE:
            parent=insert_node(db,lid,None,'section',name,clean_body(db,{'template':'汉语语法调查粗纲 · 用户提供 · v2'},lid));roots.append(parent)
            for title in children:insert_node(db,lid,parent,'section',title,clean_body(db,{},lid))
        return {'id':roots[0],'ids':roots}
    if action=='save':
        old=require(db,lid,b['id']) if b.get('id') else None
        parent=b.get('parent_id') or None;kind=b.get('kind','section');title=str(b.get('title','')).strip()
        if kind not in ('section','question') or not title or len(title)>500:raise ValueError('请填写 1–500 字的标题并选择有效条目类型')
        if old and kind!=old['kind']:raise ValueError('条目类型不可更改')
        if parent:
            p=require(db,lid,parent)
            if p['kind']=='question':raise ValueError('问题不能作为其他条目的父层')
        if old and parent in {n['id'] for n in descendants(db,lid,old['id'])}:raise ValueError('不能移到自身或下级条目中')
        body=clean_body(db,b.get('body',{}),lid)
        if old:
            pos=old['position'] if parent==old['parent_id'] else db.execute('SELECT COALESCE(MAX(position),0)+1 FROM survey_nodes WHERE parent_id IS ? AND language_id=?',(parent,lid)).fetchone()[0]
            db.execute('UPDATE survey_nodes SET parent_id=?,title=?,body=?,position=?,revision=revision+1 WHERE id=?',(parent,title,dump(body),pos,old['id']))
            return saved_node(db,lid,old['id'])
        return saved_node(db,lid,insert_node(db,lid,parent,kind,title,body))
    node=require(db,lid,b.get('node_id') or b.get('id'))
    if action in ('delete','copy'):
        rows=descendants(db,lid,node['id']);mapping={r['id']:uid() for r in rows}
        if action=='delete':
            if b.get('confirmed') is not True:raise ValueError('请确认删除提纲及其研究笔记；语料原句保留')
            for r in rows:
                db.execute('DELETE FROM survey_evidence WHERE node_id=?',(r['id'],));db.execute('DELETE FROM survey_nodes WHERE id=?',(r['id'],))
            return {'id':node['parent_id']}
        last=db.execute('SELECT COALESCE(MAX(position),0)+1 FROM survey_nodes WHERE language_id=? AND parent_id IS ?',(lid,node['parent_id'])).fetchone()[0]
        for r in rows:
            body=json.loads(r['body'])
            if not b.get('include_evidence'):body.update(notes=[],status='unasked')
            db.execute('INSERT INTO survey_nodes VALUES(?,?,?,?,?,?,?,1)',(mapping[r['id']],lid,mapping.get(r['parent_id'],r['parent_id']),r['kind'],r['title']+(' · 副本' if r['id']==node['id'] else ''),last if r['id']==node['id'] else r['position'],dump(body)))
            if b.get('include_evidence'):
                for e in db.execute('SELECT * FROM survey_evidence WHERE node_id=?',(r['id'],)).fetchall():db.execute('INSERT INTO survey_evidence VALUES(?,?,?,?,?,?,?,1)',(uid(),lid,mapping[r['id']],e['kind'],e['record_id'],e['position'],e['body'],))
        return {'id':mapping[node['id']]}
    if action=='order':
        rows=list(db.execute('SELECT id FROM survey_nodes WHERE language_id=? AND parent_id IS ? ORDER BY position,rowid',(lid,node['parent_id'])))
        ids=[r[0] for r in rows];at=ids.index(node['id']);to=at+(-1 if b.get('direction')=='up' else 1)
        if 0<=to<len(ids):
            ids[at],ids[to]=ids[to],ids[at]
            for i,rid in enumerate(ids):db.execute('UPDATE survey_nodes SET position=?,revision=revision+1 WHERE id=?',(i,rid))
        return {'id':node['id']}
    if action in ('evidence','new-example'):
        eid=b.get('evidence_id');old=db.execute('SELECT * FROM survey_evidence WHERE id=? AND node_id=?',(eid,node['id'])).fetchone() if eid else None
        if eid and not old:raise ValueError('例证引用已不存在')
        if action=='new-example':
            import dictionary_data
            record=dictionary_data.mutate(db,'example-save',{'body':b.get('example',{})},lid)
            kind,rid='independent',record['id']
        else:kind,rid=b.get('kind'),b.get('record_id')
        if old:
            if kind!=old['kind'] or rid!=old['record_id']:raise ValueError('不能在编辑笔记时更换例句引用')
        else:
            source=reference(db,kind,rid,lid)
            if source['owner_language']!=lid:raise ValueError('该句所属文本在另一语言下，请在所属语言的调查中引用，以保证语言导出完整')
        body=clean_body(db,b.get('body',{}),lid,True)
        if old:
            db.execute('UPDATE survey_evidence SET body=?,revision=revision+1 WHERE id=?',(dump(body),eid))
        else:
            eid=uid();pos=db.execute('SELECT COALESCE(MAX(position),0)+1 FROM survey_evidence WHERE node_id=?',(node['id'],)).fetchone()[0]
            db.execute('INSERT INTO survey_evidence VALUES(?,?,?,?,?,?,?,1)',(eid,lid,node['id'],kind,rid,pos,dump(body)))
        evidence=dict(db.execute('SELECT * FROM survey_evidence WHERE id=?',(eid,)).fetchone());evidence['body']=json.loads(evidence['body'])
        return {**saved_node(db,lid,node['id']),'record_id':rid,'evidence_id':eid,'evidence':evidence}
    if action=='unlink':
        db.execute('DELETE FROM survey_evidence WHERE id=? AND node_id=?',(b.get('evidence_id'),node['id']))
        return {'id':node['id']}
    raise ValueError('未知调查操作')


def validate(db):
    nodes={r['id']:dict(r) for r in db.execute('SELECT * FROM survey_nodes')}
    for n in nodes.values():
        if n['kind'] not in ('section','question') or not str(n['title']).strip():raise ValueError('调查条目无效')
        clean_body(db,json.loads(n['body']),n['language_id']);seen={n['id']};p=n['parent_id']
        while p:
            if p in seen or p not in nodes or nodes[p]['language_id']!=n['language_id'] or nodes[p]['kind']=='question':raise ValueError('调查提纲层级无效')
            seen.add(p);p=nodes[p]['parent_id']
    for e in db.execute('SELECT * FROM survey_evidence'):
        if e['node_id'] not in nodes or nodes[e['node_id']]['language_id']!=e['language_id']:raise ValueError('调查例证的所属条目无效')
        if e['kind'] not in ('corpus','independent'):raise ValueError('调查例证来源无效')
        clean_body(db,json.loads(e['body']),e['language_id'],True)
    # Deleted sentences remain explicit missing references, recoverable by undo.


def writing_replace(db,old,new):
    for table in TABLES:
        for row in db.execute('SELECT id,body FROM '+table).fetchall():
            b=json.loads(row['body']);changed=False
            for key in ('content','notes','context'):
                for run in b.get(key,[]):
                    if run.get('type_id')==old:
                        if not new:raise ValueError('书写类型被语法调查引用，请选择替换类型')
                        run['type_id']=new;changed=True
            if changed:db.execute('UPDATE '+table+' SET body=?,revision=revision+1 WHERE id=?',(dump(b),row['id']))


def export_bundle(db,lid):
    return {t:[dict(r) for r in db.execute('SELECT * FROM '+t+' WHERE language_id=?',(lid,))] for t in TABLES}


def import_bundle(db,bundle,lid,entries,examples,types,people):
    nodes={r['id']:uid() for r in bundle.get('survey_nodes',[])}
    for table in long_tasks.steps(TABLES):
        for r in long_tasks.steps(bundle.get(table,[])):
            row=dict(r);row.pop('rowid',None);row.update(id=nodes[r['id']] if table=='survey_nodes' else uid(),language_id=lid,revision=1)
            b=json.loads(row['body'])
            for key in long_tasks.steps(('content','notes','context')):
                for run in long_tasks.steps(b.get(key,[])):
                    if run.get('type_id'):run['type_id']=types[run['type_id']]
            if table=='survey_nodes':row['parent_id']=nodes[row['parent_id']] if row.get('parent_id') else None
            else:
                row['node_id']=nodes[row['node_id']]
                row['record_id']=(entries if row['kind']=='corpus' else examples).get(row['record_id'],'missing:'+uid())
                b['judges']=[people[p] for p in b.get('judges',[])]
            row['body']=dump(b)
            db.execute('INSERT INTO '+table+' ('+','.join(row)+') VALUES ('+','.join('?' for _ in row)+')',list(row.values()))
    validate(db)
