"""Same-language, exact-form homonym numbering and confirmation snapshots."""
import hashlib
import json

def number(value):
    if value in (None,''):return None
    if type(value) is not int or value<1:raise ValueError('同形词下标须为正整数')
    return value

def group(db,lid,form):
    rows=[{**dict(r),'body':json.loads(r['body'])} for r in db.execute('SELECT * FROM lexemes WHERE language_id=? AND headword=? ORDER BY rowid',(lid,form))]
    used={number(r['body'].get('homonym_number')) for r in rows}-{None}
    for r in rows:
        n=number(r['body'].get('homonym_number'))
        if n is None and len(rows)>1:
            n=1
            while n in used:n+=1
            used.add(n)
        r['number']=n
    return rows

def plan(db,lid,form,exclude=''):
    rows=[r for r in group(db,lid,form.strip()) if r['id']!=exclude]
    peers=[dict(id=r['id'],revision=r['revision'],number=r['number'],headword=r['headword']) for r in rows]
    token=hashlib.sha256(json.dumps([lid,form.strip(),exclude,peers],sort_keys=True).encode()).hexdigest()
    return dict(peers=peers,token=token)

def prepare(db,lid,form,data,old,confirmation):
    peers=[r for r in group(db,lid,form) if not old or r['id']!=old['id']]
    if peers and (not old or old['headword']!=form):
        if confirmation!=plan(db,lid,form,old['id'] if old else '')['token']:
            raise ValueError('存在相同词形，请重新确认同形词后保存')
    used={r['number'] for r in peers}-{None}
    chosen=number(data.get('homonym_number'))
    if old and old['headword']!=form:
        # A number identifies an occurrence within its old exact-form group.
        chosen=None
    if chosen in used:raise ValueError('此词形的下标已被占用，请选择其他下标')
    if peers:
        # Persist inferred legacy numbers and number the former unnumbered singleton.
        for r in peers:
            n=r['number']
            if n is None:
                n=1
                while n in used or n==chosen:n+=1
                used.add(n)
            if r['body'].get('homonym_number')!=n:
                r['body']['homonym_number']=n
                db.execute('UPDATE lexemes SET body=?,revision=revision+1 WHERE id=?',(json.dumps(r['body'],ensure_ascii=False),r['id']))
        if chosen is None:
            chosen=1
            while chosen in used:chosen+=1
    data['homonym_number']=chosen

def clear_singleton(db,lid,form):
    rows=group(db,lid,form)
    if len(rows)==1 and rows[0]['body'].get('homonym_number') is not None:
        r=rows[0];r['body']['homonym_number']=None
        db.execute('UPDATE lexemes SET body=?,revision=revision+1 WHERE id=?',(json.dumps(r['body'],ensure_ascii=False),r['id']))

def decorate(db,item):
    if item['body'].get('homonym_number') is None:
        item['body']['homonym_number']=next(r['number'] for r in group(db,item['language_id'],item['headword']) if r['id']==item['id'])
    return item

def decorate_many(db,items):
    """Resolve legacy numbers once per form, without parsing every peer's draft."""
    needed={(r['language_id'],r['headword']) for r in items if r['body'].get('homonym_number') is None}
    if not needed:return items
    groups={}
    # Bounded batches avoid SQLite's parameter limit, including the all-languages view.
    keys=list(needed)
    for start in range(0,len(keys),200):
        batch=keys[start:start+200]
        sql='SELECT id,language_id,headword,json_extract(body,\'$.homonym_number\') number FROM lexemes WHERE '+ ' OR '.join('(language_id=? AND headword=?)' for _ in batch)+' ORDER BY rowid'
        for r in db.execute(sql,[v for pair in batch for v in pair]):groups.setdefault((r['language_id'],r['headword']),[]).append(r)
    numbers={}
    for rows in groups.values():
        used={number(r['number']) for r in rows}-{None}
        for r in rows:
            n=number(r['number'])
            if n is None and len(rows)>1:
                n=1
                while n in used:n+=1
                used.add(n)
            numbers[r['id']]=n
    for r in items:
        if r['body'].get('homonym_number') is None:r['body']['homonym_number']=numbers[r['id']]
    return items

def validate(db):
    seen=set()
    for r in db.execute('SELECT language_id,headword,body FROM lexemes'):
        n=number(json.loads(r['body']).get('homonym_number'))
        if n is None:continue
        key=(r['language_id'],r['headword'],n)
        if key in seen:raise ValueError('同一词形不能使用重复的同形词下标')
        seen.add(key)
