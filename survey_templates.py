"""Portable survey outlines stored beside the project database."""
import json
import os
import threading
import uuid
from pathlib import Path
import grammar_survey as survey

_lock = threading.RLock()


def path(folder, ident):
    try: ident = str(uuid.UUID(str(ident)))
    except (ValueError, TypeError): raise ValueError('模板标识无效')
    return Path(folder) / (ident + '.json')


def read(folder, ident):
    p = path(folder, ident)
    if not p.is_file(): raise ValueError('模板已不存在，请刷新模板列表')
    return json.loads(p.read_text(encoding='utf-8'))


def write(folder, value):
    p = path(folder, value['id']); p.parent.mkdir(parents=True, exist_ok=True)
    tmp = p.with_suffix('.tmp')
    tmp.write_text(json.dumps(value, ensure_ascii=False, indent=2), encoding='utf-8')
    os.replace(tmp, p)


def listing(folder):
    with _lock:
        rows=[]
        for p in sorted(Path(folder).glob('*.json')):
            try:
                d=read(folder,p.stem)
                rows.append(dict(id=d['id'],name=d['name'],count=len(d['nodes'])))
            except (ValueError, KeyError, OSError): continue
        return dict(folder=str(Path(folder).resolve()),items=rows)


def mutate(db,lid,folder,b):
    with _lock:
        action=b.get('action')
        if action=='save':
            selected=b.get('node_ids') if 'node_ids' in b else [b.get('node_id')]
            if not isinstance(selected,list) or not selected or len(selected)>10000:raise ValueError('请选择要保存的提纲条目')
            for ident in selected:survey.require(db,lid,ident)
            if b.get('version')!=survey.version(db,lid):raise ValueError('提纲已更新，请刷新后重新保存模板')
            all_rows=list(db.execute('SELECT * FROM survey_nodes WHERE language_id=? ORDER BY position,rowid',(lid,)))
            ids=set(selected)
            while True:
                grown=ids | {r['id'] for r in all_rows if r['parent_id'] in ids}
                if grown==ids:break
                ids=grown
            # Forest order is independent of click order; overlapping subtrees appear once.
            rows=[];children={}
            for r in all_rows:children.setdefault(r['parent_id'],[]).append(r)
            stack=list(reversed(children.get(None,[])))
            while stack:
                r=stack.pop()
                if r['id'] in ids:rows.append(r)
                stack.extend(reversed(children.get(r['id'],[])))
            if len(rows)>10000:raise ValueError('模板最多包含10000个条目')
            types=set(); nodes=[]
            for r in rows:
                body=json.loads(r['body']);content=body.get('content',[])
                types.update(run['type_id'] for run in content if run.get('type_id'))
                nodes.append(dict(id=r['id'],parent_id=r['parent_id'] if r['parent_id'] in ids else None,kind=r['kind'],title=r['title'],position=r['position'],content=content))
            root_position=0
            for node in nodes:
                if node['parent_id'] is None:
                    node['position']=root_position;root_position+=1
            d=dict(format='corporium-survey-template',version=1,id=survey.uid(),name='',nodes=nodes,
                   writing_types=[dict(r) for r in db.execute('SELECT id,name,font FROM writing_types WHERE language_id=?',(lid,)) if r['id'] in types])
        else:d=read(folder,b.get('id'))
        if action in ('save','rename','copy'):
            name=str(b.get('name','')).strip()
            if not name or len(name)>200:raise ValueError('模板名称须为1–200字')
            d['name']=name
            if action=='copy':d['id']=survey.uid()
            write(folder,d);return dict(id=d['id'])
        if action=='delete':
            if not b.get('confirmed'):raise ValueError('请确认删除模板')
            trash=Path(folder)/'deleted';trash.mkdir(parents=True,exist_ok=True)
            os.replace(path(folder,d['id']),path(trash,d['id']))
            return dict(deleted=True)
        if action=='import':
            if b.get('version')!=survey.version(db,lid):raise ValueError('提纲已更新，请刷新后重新导入')
            if d.get('format')!='corporium-survey-template' or d.get('version')!=1:raise ValueError('不支持的模板格式')
            rows=d['nodes']
            if not rows or len(rows)>10000:raise ValueError('模板条目数量无效')
            type_map={}
            for t in d.get('writing_types',[]):
                old=db.execute('SELECT id FROM writing_types WHERE language_id=? AND name=? AND font=?',(lid,t['name'],t['font'])).fetchone()
                tid=old[0] if old else survey.uid()
                if not old:db.execute('INSERT INTO writing_types VALUES(?,?,?,?,0,1)',(tid,lid,t['name'],t['font']))
                type_map[t['id']]=tid
            mapping={};root=None;remaining=list(rows)
            while remaining:
                ready=[r for r in remaining if not r.get('parent_id') or r['parent_id'] in mapping]
                if not ready:raise ValueError('模板存在循环或缺失的父条目')
                for r in sorted(ready,key=lambda r:r.get('position',0)):
                    if r['id'] in mapping or r['kind'] not in ('section','question') or not str(r['title']).strip():raise ValueError('模板条目无效')
                    content=[dict(run) for run in r.get('content',[])]
                    for run in content:
                        if run.get('type_id'):run['type_id']=type_map[run['type_id']]
                    body=survey.clean_body(db,dict(content=content,template=d['name'] if not r.get('parent_id') else ''),lid)
                    nid=survey.insert_node(db,lid,mapping.get(r.get('parent_id')),r['kind'],r['title'],body)
                    mapping[r['id']]=nid;root=root or nid;remaining.remove(r)
            survey.validate(db)
            return dict(id=root)
        raise ValueError('不支持的模板操作')
