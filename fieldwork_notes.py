"""Language-wide lexical fieldwork notes, sharing the survey's rich-text format."""
import json
import uuid
import long_tasks
from grammar_survey import rich

TABLES=('fieldwork_notes',)
COLUMNS='id,language_id,position,title,preview,revision'


def initialize(db):
    db.executescript('''CREATE TABLE IF NOT EXISTS fieldwork_notes(
        id TEXT PRIMARY KEY,language_id TEXT NOT NULL,position INTEGER NOT NULL,
        title TEXT NOT NULL,body TEXT NOT NULL,preview TEXT NOT NULL,revision INTEGER NOT NULL DEFAULT 1);
        CREATE INDEX IF NOT EXISTS fieldwork_note_order ON fieldwork_notes(language_id,position);''')


def listing(db,lid):
    return dict(items=[dict(r) for r in db.execute('SELECT '+COLUMNS+' FROM fieldwork_notes WHERE language_id=? ORDER BY position,rowid',(lid,))],
                writing_types=[dict(r) for r in db.execute('SELECT * FROM writing_types WHERE language_id=? ORDER BY position,name',(lid,))])


def search(db,lid,q):
    from survey_search import normalize,rich_text,excerpt
    if lid=='all':raise ValueError('请先选择一种语言')
    query=q.get('q','')
    if not isinstance(query,str) or len(query)>200:raise ValueError('检索文字限200字')
    query=query.strip();term=normalize(query);matches=[];total=0;page=max(1,int(q.get('page',1)));size=20
    if not term:return dict(items=[],total=0,page=1,pages=1,q=query)
    for row in long_tasks.steps(db.execute('SELECT * FROM fieldwork_notes WHERE language_id=? ORDER BY position,rowid',(lid,))):
        fields=[]
        for key,label,text in [('title','标题',row['title']),('body','内容',rich_text(json.loads(row['body'])))]:
            if term in normalize(text):fields.append(dict(field=key,label=label,snippet=excerpt(text,query)))
        if fields:
            if (page-1)*size<=total<page*size:matches.append(dict(id=row['id'],title=row['title'],preview=row['preview'],fields=fields))
            total+=1
    pages=max(1,(total+size-1)//size)
    if page>pages:return search(db,lid,dict(q=query,page=pages))
    return dict(items=matches,total=total,page=page,pages=pages,q=query)


def require(db,lid,nid):
    row=db.execute('SELECT * FROM fieldwork_notes WHERE id=? AND language_id=?',(nid,lid)).fetchone()
    if not row:raise ValueError('调查笔记已不存在或不属于当前语言，请重新打开笔记')
    return dict(row)


def detail(db,lid,nid):
    row=require(db,lid,nid);row['body']=json.loads(row['body']);return row


def clean(db,lid,b):
    title=b.get('title','')
    if not isinstance(title,str) or len(title)>500:raise ValueError('笔记标题限500字')
    runs=rich(db,b.get('body',[]),lid)
    preview=''.join(r['text'] for r in runs).strip()[:180]
    return title.strip(),json.dumps(runs,ensure_ascii=False),preview


def check(row,b):
    if row['revision']!=b.get('revision'):raise ValueError('调查笔记已在其他操作中更新，当前草稿已保留；请另存为副本或重新打开')


def mutate(db,lid,action,b):
    if action=='reorder':
        rows=listing(db,lid)['items'];ids=[r['id'] for r in rows]
        if b.get('snapshot')!=[dict(id=r['id'],revision=r['revision']) for r in rows]:raise ValueError('笔记列表已变化，请重新打开面板后排序')
        order=b.get('order')
        if not isinstance(order,list) or any(not isinstance(i,str) for i in order) or len(order)!=len(ids) or len(set(order))!=len(order) or set(order)!=set(ids):raise ValueError('请提交本语言完整且不重复的笔记顺序')
        if order!=ids:
            positions={r['id']:r['position'] for r in rows}
            for p,nid in long_tasks.steps(enumerate(order)):
                if positions[nid]!=p:db.execute('UPDATE fieldwork_notes SET position=?,revision=revision+1 WHERE id=?',(p,nid))
        return listing(db,lid)
    if action=='create':
        title,body,preview=clean(db,lid,b);nid=str(uuid.uuid4())
        p=db.execute('SELECT COALESCE(MAX(position),-1)+1 FROM fieldwork_notes WHERE language_id=?',(lid,)).fetchone()[0]
        db.execute('INSERT INTO fieldwork_notes(id,language_id,position,title,body,preview) VALUES(?,?,?,?,?,?)',(nid,lid,p,title,body,preview))
        return detail(db,lid,nid)
    row=require(db,lid,b.get('id'));check(row,b)
    if action=='save':
        title,body,preview=clean(db,lid,b)
        if (title,body,preview)!=(row['title'],row['body'],row['preview']):
            db.execute('UPDATE fieldwork_notes SET title=?,body=?,preview=?,revision=revision+1 WHERE id=?',(title,body,preview,row['id']))
        return detail(db,lid,row['id'])
    if action=='copy':
        title=(row['title'] or row['preview'].split('\n')[0] or '未命名笔记')[:480]+' · 副本'
        return mutate(db,lid,'create',dict(title=title,body=json.loads(row['body'])))
    if action=='delete':
        if b.get('confirmed') is not True:raise ValueError('请确认删除调查笔记，可用撤销恢复')
        db.execute('DELETE FROM fieldwork_notes WHERE id=?',(row['id'],));return dict(ok=True)
    raise ValueError('未知调查笔记操作')


def validate(db):
    for row in long_tasks.steps(db.execute('SELECT n.*,l.id owner FROM fieldwork_notes n LEFT JOIN languages l ON l.id=n.language_id')):
        if not row['owner']:raise ValueError('调查笔记缺少所属语言')
        title,body,preview=clean(db,row['language_id'],dict(title=row['title'],body=json.loads(row['body'])))
        if not isinstance(row['position'],int) or row['title']!=title or row['preview']!=preview:raise ValueError('调查笔记内容或顺序格式无效')


def writing_replace(db,old,new):
    for row in long_tasks.steps(db.execute('SELECT id,body FROM fieldwork_notes')):
        body=json.loads(row['body']);changed=False
        for run in body:
            if run.get('type_id')==old:
                if not new:raise ValueError('调查笔记仍使用此书写类型，请选择替换类型')
                run['type_id']=new;changed=True
        if changed:db.execute('UPDATE fieldwork_notes SET body=?,revision=revision+1 WHERE id=?',(json.dumps(body,ensure_ascii=False),row['id']))


def export_bundle(db,lid,stream=False):
    query='SELECT * FROM fieldwork_notes WHERE language_id=? ORDER BY position,rowid'
    if stream:
        from streaming_json import Rows
        return {'fieldwork_notes':Rows(db,query,(lid,))}
    return {'fieldwork_notes':[dict(r) for r in db.execute(query,(lid,))]}


def import_bundle(db,bundle,lid,types):
    for row in long_tasks.steps(bundle.get('fieldwork_notes',[])):
        runs=json.loads(row['body'])
        for run in long_tasks.steps(runs):
            if run.get('type_id'):
                if run['type_id'] not in types:raise ValueError('调查笔记缺少引用的书写类型')
                run['type_id']=types[run['type_id']]
        title,body,preview=clean(db,lid,dict(title=row['title'],body=runs))
        position=row['position']
        if isinstance(position,bool) or not isinstance(position,int) or abs(position)>10**12:raise ValueError('调查笔记顺序格式无效')
        db.execute('INSERT INTO fieldwork_notes(id,language_id,position,title,body,preview) VALUES(?,?,?,?,?,?)',(str(uuid.uuid4()),lid,position,title,body,preview))
    validate(db)
