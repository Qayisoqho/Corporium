"""Language-local sound inventories and explicit reading classifications.

Stored in language metadata so backups, undo and language exchange retain them.
The original pronunciation is never rewritten.
"""
import long_tasks
import hashlib
import json
import unicodedata
import languages

AXES=('initials','finals','tones')

def norm(text):
    return unicodedata.normalize('NFC',text.strip())

def digest(value):
    return hashlib.sha256(json.dumps(value,ensure_ascii=False,sort_keys=True).encode()).hexdigest()

def get(db,lid):
    meta=json.loads(languages.require(db,lid)['metadata'])
    data=meta.get('homophone_phonology',{})
    return {**{axis:data.get(axis,[]) for axis in AXES},'assignments':data.get('assignments',{}),'token':digest(data)}

def inventory(value):
    if not isinstance(value,dict):raise ValueError('音系清单格式无效')
    result={}
    for axis in AXES:
        rows=value.get(axis,[])
        if not isinstance(rows,list):raise ValueError('音系清单格式无效')
        seen=set();labels=set();out=[]
        for row in rows:
            if not isinstance(row,dict):raise ValueError('音系清单格式无效')
            key=row.get('id');label=row.get('label');aliases=row.get('matches')
            if not isinstance(key,str) or not key or key in seen:raise ValueError('音系项目身份缺失或重复')
            if not isinstance(label,str) or not label.strip() or label.strip() in labels:raise ValueError('同一清单内名称不能为空或重复')
            if not isinstance(aliases,list) or not aliases or any(not isinstance(a,str) for a in aliases):raise ValueError('每个项目至少填写一种匹配写法')
            aliases=list(dict.fromkeys(norm(a) for a in aliases))
            if axis=='finals' and '' in aliases:raise ValueError('韵母的匹配写法不能为空')
            seen.add(key);labels.add(label.strip());out.append(dict(id=key,label=label.strip(),matches=aliases))
        result[axis]=out
    return result

def validate_stored(value):
    result=inventory(value);assignments=value.get('assignments',{})
    if not isinstance(assignments,dict):raise ValueError('读音归类格式无效')
    for reading,choice in assignments.items():
        if not isinstance(reading,str) or not isinstance(choice,dict) or any(not isinstance(choice.get(a),str) for a in AXES) or not isinstance(choice.get('signature'),str):raise ValueError('读音归类格式无效')
    return {**result,'assignments':assignments}

def signature(config,choice):
    selected=[]
    for axis in AXES:
        row=next((r for r in config[axis] if r['id']==choice.get(axis)),None)
        if row is None:return None
        selected.append(row)
    return digest(selected)

def classify(reading,config):
    reading=norm(reading);saved=config['assignments'].get(reading)
    if saved:
        valid=signature(config,saved)==saved.get('signature') and saved.get('signature') is not None
        return dict(state='confirmed' if valid else 'stale',choice={axis:saved.get(axis) for axis in AXES},reason='' if valid else '音系项目已修改或删除，请重新核对',candidates=[])
    finals={}
    for row in config['finals']:
        for alias in row['matches']:finals.setdefault(alias,[]).append(row['id'])
    candidates=[];seen=set()
    for tone in config['tones']:
        for tail in tone['matches']:
            if tail and not reading.endswith(tail):continue
            core=reading[:-len(tail)] if tail else reading
            for initial in config['initials']:
                for prefix in initial['matches']:
                    if not core.startswith(prefix):continue
                    for final in finals.get(core[len(prefix):],[]):
                        key=(initial['id'],final,tone['id'])
                        if key not in seen:
                            seen.add(key);candidates.append(dict(zip(AXES,key)))
                            # Ambiguity needs human input, not an unbounded candidate product.
                            if len(candidates)>=20:return dict(state='ambiguous',choice=None,reason='存在多种划分（仅列前 20 项）',candidates=candidates)
    return dict(state='candidate' if len(candidates)==1 else 'ambiguous' if candidates else 'unmatched',choice=candidates[0] if len(candidates)==1 else None,reason='自动识别，尚未确认' if len(candidates)==1 else '存在多种划分' if candidates else '无法唯一识别，请手动归类',candidates=candidates)

def mutate(db,lid,body):
    if not db.in_transaction:db.execute('BEGIN IMMEDIATE')
    current=get(db,lid)
    if body.get('token')!=current['token']:raise ValueError('音系设置或归类已变化，请重新打开后再保存')
    data={k:current[k] for k in (*AXES,'assignments')}
    if body.get('action')=='settings':
        data.update(inventory(body))
    elif body.get('action')=='classify':
        reading=body.get('reading')
        if not isinstance(reading,str) or not norm(reading):raise ValueError('请选择有效读音')
        reading=norm(reading)
        if body.get('reset'):data['assignments'].pop(reading,None)
        else:
            choice={axis:body.get(axis) for axis in AXES};sig=signature(data,choice)
            if sig is None:raise ValueError('请完整选择声母、韵母和声调')
            data['assignments'][reading]={**choice,'signature':sig}
    elif body.get('action')=='confirm_unique':
        import homophones
        groups=homophones.table(db,lid,{'_collect':True})
        unique={g['reading']:c['choice'] for g in groups if (c:=classify(g['reading'],current))['state']=='candidate'}
        selected=body.get('readings') if not body.get('all') else list(unique)
        if not isinstance(selected,list) or not selected or any(not isinstance(r,str) or r not in unique for r in selected):raise ValueError('请选择当前仍为唯一匹配的实际读音；歧义、待核对和临时代用形式不能批量确认')
        for reading in long_tasks.steps(set(selected)):
            choice=unique[reading];data['assignments'][reading]={**choice,'signature':signature(data,choice)}
    else:raise ValueError('未知音系操作')
    row=languages.require(db,lid);meta=json.loads(row['metadata']);meta['homophone_phonology']=data
    db.execute('UPDATE languages SET metadata=?,revision=revision+1 WHERE id=?',(json.dumps(meta,ensure_ascii=False),lid))
    return get(db,lid)

def arrange(result,config,q):
    buckets={};pending=[]
    for group in result:
        classification=classify(group['reading'],config)
        group['classification']=classification
        if classification['state']=='confirmed':
            choice=classification['choice'];buckets.setdefault(choice['finals'],{}).setdefault(choice['initials'],{}).setdefault(choice['tones'],[]).append(group)
        else:pending.append(group)
    show_empty=q.get('empty')=='true'
    finals=[f for f in config['finals'] if show_empty or f['id'] in buckets]
    page_size=str(q.get('page_size','10'))
    if page_size not in ('10','20','50','all'):raise ValueError('每页韵母分组数请选择 10、20、50 或全部')
    size=max(1,len(finals)) if page_size=='all' else int(page_size)
    pages=max(1,(len(finals)+size-1)//size)
    page=max(1,min(int(q.get('page',1)),pages))
    blocks=[]
    for final in finals[(page-1)*size:page*size]:
        rows=[];bucket=buckets.get(final['id'],{})
        for initial in config['initials']:
            if not show_empty and initial['id'] not in bucket:continue
            cells=[dict(tone=t,groups=bucket.get(initial['id'],{}).get(t['id'],[])) for t in config['tones'] if show_empty or t['id'] in bucket.get(initial['id'],{})]
            rows.append(dict(initial=initial,cells=cells))
        blocks.append(dict(final=final,rows=rows))
    pp=max(1,min(int(q.get('pending_page',1)),max(1,(len(pending)+39)//40)))
    return dict(blocks=blocks,page=page,pages=pages,page_size='all' if page_size=='all' else size,final_total=len(finals),pending=pending[(pp-1)*40:pp*40],pending_total=len(pending),pending_page=pp,pending_pages=max(1,(len(pending)+39)//40))
