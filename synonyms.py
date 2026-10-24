"""Explicit, symmetric sense-to-sense links; never inferred from spelling."""
import json
import uuid

TABLES=('synonym_links',)

def initialize(db):
    db.executescript('''CREATE TABLE IF NOT EXISTS synonym_links(id TEXT PRIMARY KEY,language_id TEXT NOT NULL,a TEXT NOT NULL,b TEXT NOT NULL,body TEXT NOT NULL);
    CREATE UNIQUE INDEX IF NOT EXISTS synonym_pair ON synonym_links(language_id,a,b);
    CREATE INDEX IF NOT EXISTS synonym_reverse ON synonym_links(language_id,b);''')

def key(ref):return ':'.join(ref[k] for k in ('kind','id','sense'))

def senses(db,lid,kind,rid):
    if kind not in ('lexeme','morpheme'):raise ValueError('条目类型无效')
    row=db.execute('SELECT * FROM '+('lexemes' if kind=='lexeme' else 'morphemes')+' WHERE id=? AND language_id=?',(rid,lid)).fetchone()
    if not row:raise ValueError('条目已删除或不属于当前语言')
    body=json.loads(row['body']);form=row['headword'] if kind=='lexeme' else row['form']
    if kind=='lexeme':items=[dict(sense=s['id'],label=(u.get('pos') or '词类待定')+' · '+(s.get('short_gloss') or s.get('definition') or '义项未填写')) for u in body.get('usages',[]) for s in u.get('senses',[])]
    else:items=[dict(sense=body.get('primary_sense_id','@main'),label=body.get('gloss') or '主要释义')]+[dict(sense=s['id'],label=s.get('gloss') or s.get('definition') or '义项未填写') for s in body.get('senses',[])]
    return [dict(kind=kind,id=rid,form=form,**s) for s in items]

def resolve(db,lid,ref):
    for item in senses(db,lid,ref.get('kind'),ref.get('id')):
        if item['sense']==ref.get('sense'):return item
    raise ValueError('义项已删除，请重新选择')

def list_links(db,lid,kind,rid):
    if lid=='all' and kind in ('lexeme','morpheme'):
        row=db.execute('SELECT language_id FROM '+('lexemes' if kind=='lexeme' else 'morphemes')+' WHERE id=?',(rid,)).fetchone()
        if row:lid=row[0]
    source=senses(db,lid,kind,rid);prefix=kind+':'+rid+':'
    records=[]
    for row in db.execute('SELECT * FROM synonym_links WHERE language_id=? AND (a LIKE ? OR b LIKE ?)',(lid,prefix+'%',prefix+'%')):
        data=json.loads(row['body']);endpoints=[]
        for ref in data:
            try:endpoints.append({**resolve(db,lid,ref),'missing':False})
            except ValueError:endpoints.append({**ref,'missing':True})
        records.append(dict(id=row['id'],ends=endpoints))
    return dict(senses=source,links=records,language_id=lid)

def search(db,lid,q):
    import languages
    languages.require(db,lid);kind=q.get('kind','lexeme')
    if kind not in ('lexeme','morpheme'):raise ValueError('条目类型无效')
    table='lexemes' if kind=='lexeme' else 'morphemes';field='headword' if kind=='lexeme' else 'form';query=q.get('q','').lower()
    rows=db.execute(f'SELECT id FROM {table} WHERE language_id=? AND instr(lower({field}||body),?)>0 ORDER BY {field} COLLATE NOCASE LIMIT 40',(lid,query))
    return dict(items=[s for row in rows for s in senses(db,lid,kind,row['id'])],limited=True)

def mutate(db,lid,b):
    import languages
    languages.require(db,lid)
    if b.get('delete'):
        row=db.execute('SELECT id FROM synonym_links WHERE id=? AND language_id=?',(b.get('id'),lid)).fetchone()
        if not row:raise ValueError('同义关系已不存在')
        db.execute('DELETE FROM synonym_links WHERE id=?',(row['id'],));return dict(ok=True)
    refs=[resolve(db,lid,b.get(k,{})) for k in ('source','target')]
    refs.sort(key=key);a,c=map(key,refs)
    if a==c:raise ValueError('不能把一个义项与自身关联')
    db.execute('INSERT OR IGNORE INTO synonym_links VALUES(?,?,?,?,?)',(str(uuid.uuid4()),lid,a,c,json.dumps(refs,ensure_ascii=False)))
    return dict(ok=True)

def export_bundle(db,languages):
    return [dict(r) for r in db.execute('SELECT * FROM synonym_links') if r['language_id'] in languages]

def merge_morpheme(db,lid,source,target):
    """Preserve distinct source senses instead of guessing which meanings coincide."""
    refs=senses(db,lid,'morpheme',source['id'])
    used={r['sense'] for r in refs if db.execute('SELECT 1 FROM synonym_links WHERE language_id=? AND (a=? OR b=?)',(lid,key(r),key(r))).fetchone()}
    mapping={sid:str(uuid.uuid4()) for sid in used}
    for ref in refs:
        if ref['sense'] in used:
            original=next((s for s in source['body'].get('senses',[]) if s['id']==ref['sense']),{})
            target['body'].setdefault('senses',[]).append({**original,'id':mapping[ref['sense']],'gloss':ref['label']})
    for row in list(db.execute('SELECT * FROM synonym_links WHERE language_id=?',(lid,))):
        ends=json.loads(row['body']);changed=False
        for ref in ends:
            if ref['kind']=='morpheme' and ref['id']==source['id'] and ref['sense'] in mapping:
                ref.update(id=target['id'],sense=mapping[ref['sense']],form=target['form']);changed=True
        if changed:
            ends.sort(key=key)
            db.execute('UPDATE synonym_links SET a=?,b=?,body=? WHERE id=?',(key(ends[0]),key(ends[1]),json.dumps(ends,ensure_ascii=False),row['id']))

def import_bundle(db,bundle,lmap,xmap,mmap,submap):
    for row in bundle.get('synonym_links',[]):
        refs=json.loads(row['body']);out=[]
        for r in refs:
            mapping=xmap if r['kind']=='lexeme' else mmap;old=r['id']
            # Retain deleted-target evidence without accidentally linking a live ID.
            r={**r,'id':mapping.get(old,str(uuid.uuid4()))}
            r['sense']=submap.get((old,r['sense']),r['sense'] if r['kind']=='morpheme' else str(uuid.uuid4()))
            out.append(r)
        out.sort(key=key)
        db.execute('INSERT INTO synonym_links VALUES(?,?,?,?,?)',(str(uuid.uuid4()),lmap[row['language_id']],key(out[0]),key(out[1]),json.dumps(out,ensure_ascii=False)))
