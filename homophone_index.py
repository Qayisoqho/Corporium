"""Indexed live component occurrences. The dictionary retains all research data."""
from collections import defaultdict
import json
import record_sources
import unicodedata

import long_tasks
import phonology
import read_views

GROUPS=read_views.Cache(24*1024**2)
LABELS=read_views.Cache(4*1024**2)
import material_search_index

TABLES = ('hp_readings','hp_occurrences','hp_dirty')


def drop(db):
    for name, in db.execute("SELECT name FROM sqlite_master WHERE type='trigger' AND name GLOB 'hp_watch_*'").fetchall():
        db.execute('DROP TRIGGER "'+name.replace('"','""')+'"')
    for table in TABLES:
        db.execute('DROP TABLE IF EXISTS '+table)


def initialize(db):
    existed = db.execute("SELECT 1 FROM sqlite_master WHERE name='hp_dirty'").fetchone()
    db.executescript('''
      CREATE TABLE IF NOT EXISTS hp_dirty(id TEXT PRIMARY KEY) WITHOUT ROWID;
      CREATE TABLE IF NOT EXISTS hp_occurrences(
        n INTEGER PRIMARY KEY, owner TEXT, lid TEXT, stage INTEGER, sort_name TEXT, sort_num INTEGER, tie TEXT,
        owner_order INTEGER, seq INTEGER, identity TEXT, body TEXT, explicit INTEGER, fallback INTEGER,
        review INTEGER, text_explicit TEXT, text_fallback TEXT);
      CREATE INDEX IF NOT EXISTS hp_source ON hp_occurrences(owner);
      CREATE INDEX IF NOT EXISTS hp_identity ON hp_occurrences(identity,stage);
      CREATE INDEX IF NOT EXISTS hp_language ON hp_occurrences(lid,stage);
      CREATE TABLE IF NOT EXISTS hp_readings(n INTEGER, reading TEXT, folded TEXT, temporary INTEGER,
        PRIMARY KEY(n,reading)) WITHOUT ROWID;
      CREATE INDEX IF NOT EXISTS hp_by_reading ON hp_readings(reading,n);
    ''')
    def mark(sql):
        return 'INSERT INTO hp_dirty SELECT id FROM ('+sql+') v WHERE NOT EXISTS(SELECT 1 FROM hp_dirty d WHERE d.id=v.id);'
    for table in ('lexemes','morphemes','morpheme_components'):
        for event in ('INSERT','UPDATE','DELETE'):
            body = ''
            for ref in (('NEW','OLD') if event=='UPDATE' else ('OLD',) if event=='DELETE' else ('NEW',)):
                column = 'lexeme_id' if table=='morpheme_components' else 'id'
                body += mark(f'SELECT {ref}.{column} id')
                if table=='morphemes':
                    body += mark(f'SELECT DISTINCT lexeme_id id FROM morpheme_components WHERE morpheme_id={ref}.id')
            db.execute(f'CREATE TRIGGER IF NOT EXISTS hp_watch_{table}_{event} AFTER {event} ON {table} BEGIN '+body+' END')
    if not existed:
        db.execute('INSERT INTO hp_dirty SELECT id FROM lexemes UNION SELECT id FROM morphemes')


def prepare(db):
    while batch:=db.execute('SELECT id FROM hp_dirty LIMIT 256').fetchall():
        ids=[r[0] for r in batch]
        marks=','.join('?' for _ in ids)
        db.execute(f'DELETE FROM hp_readings WHERE n IN (SELECT n FROM hp_occurrences WHERE owner IN ({marks}))',ids)
        db.execute(f'DELETE FROM hp_occurrences WHERE owner IN ({marks})',ids)
        links={(r['lexeme_id'],r['analysis_id'],r['component_id']):r for r in db.execute(f'''SELECT c.*,m.form,m.number,m.language_id
            FROM morpheme_components c JOIN morphemes m ON m.id=c.morpheme_id WHERE c.lexeme_id IN ({marks})''',ids)}
        bodies=record_sources.read_many(db,'morphemes',list({r['morpheme_id'] for r in links.values()}))
        targets=[]
        for stage,table,form in ((0,'lexemes','headword'),(1,'morphemes','form')):
            number='number' if stage else 'NULL'
            rows=db.execute(f'SELECT id,language_id,{form} headword,{stage} stage,rowid,{number} num FROM {table} WHERE id IN ({marks})',ids)
            targets.extend(record_sources.with_bodies(db,table,rows))
        for target in long_tasks.steps(targets):
            native=target['body']
            if target['stage']==0:target['num']=native.get('homonym_number')
            owner=target['id']
            lid=target['language_id']
            seq=0
            for analysis in native.get('word_structure',{}).get('analyses',[]):
                for comp in analysis['components']:
                    key=(owner,analysis['id'],comp['id'])
                    link=links.get(key)
                    source=dict(lexeme_id=owner,headword=target['headword'],analysis_id=analysis['id'],component_id=comp['id'],analysis_title=analysis.get('title',''),form=comp.get('form',''))
                    if link and link['language_id']==lid:
                        data=dict(bodies[link['morpheme_id']])
                        for field in ('readings','writings'):
                            if comp.get(field):data[field]=comp[field]
                        store(db,target,seq,link['morpheme_id'],link['form'],data,[source],'已关联组分')
                    else:
                        store(db,target,seq,'component:'+':'.join(key),comp.get('form',''),comp,[source],'未整理组分')
                    seq+=1
            if target['stage']==1:
                store(db,target,seq,owner,target['headword'],native,[],'语素')
        db.executemany('DELETE FROM hp_dirty WHERE id=?',batch)


def store(db,target,seq,identity,form,data,sources,origin):
    from homophones import readings
    values=list(dict.fromkeys(unicodedata.normalize('NFC',v) for v in readings(data.get('readings',[]))))
    provisional=form.strip() if not values else ''
    reason='未整理组分' if origin=='未整理组分' else ''
    if len(values)>1:reason=('多音；'+reason).rstrip('；')
    row=dict(identity=identity,form=form,number=None,gloss=data.get('gloss',''),writings=data.get('writings',[]),
             readings=values,sources=sources,reason=reason,origin=origin,provisional=False)
    tail=[*(w['text'] for w in row['writings']),*(s['headword'] for s in sources)]
    def text(rs):return ' '.join([form,row['gloss'],*rs,*tail]).casefold()
    stage=2 if origin=='语素' else target['stage']
    tie=target['id'] if target['stage']==1 else ''
    n=db.execute('INSERT INTO hp_occurrences VALUES(NULL,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)',
        (target['id'],target['language_id'],stage,target['headword'],target['num'],tie,target['rowid'],seq,identity,
         json.dumps(row,ensure_ascii=False,separators=(',',':')),bool(values),bool(provisional),bool(reason),
         text(values),text([provisional]) if provisional else text(values))).lastrowid
    terms=values or ([unicodedata.normalize('NFC',provisional)] if provisional else [])
    db.executemany('INSERT INTO hp_readings VALUES(?,?,?,?)',((n,v,v.casefold(),not values) for v in terms))


def table(db,lid,q):
    if not db.execute("SELECT 1 FROM sqlite_master WHERE name='hp_dirty'").fetchone():return None
    if not db.in_transaction:db.execute('BEGIN')
    try:
        with material_search_index.preparing(db):prepare(db)
    except material_search_index.Unavailable:
        return None
    if lid=='all':raise ValueError('请先选择一种语言，再生成同音语素表')
    fallback=q.get('fallback')=='true'
    writing=q.get('writing','')
    types=[dict(r) for r in db.execute('SELECT * FROM writing_types WHERE language_id=?',(lid,))]
    if writing and writing not in {t['id'] for t in types}:raise ValueError('书写类型不属于当前语言')
    active="""o.lid=:lid AND (o.stage<2 OR o.explicit OR NOT EXISTS(
        SELECT 1 FROM hp_occurrences c WHERE c.identity=o.identity AND c.stage<2 AND c.lid=o.lid))"""
    text='o.text_fallback' if fallback else 'o.text_explicit'
    term=q.get('q','').casefold()
    args=dict(lid=lid,q=term,fb=int(fallback))
    where=' FROM hp_readings k JOIN hp_occurrences o ON o.n=k.n WHERE '+active+' AND k.temporary<=:fb'
    if term:where+=' AND (instr('+text+',:q)>0 OR instr(k.folded,:q)>0)'
    group_sql='SELECT k.reading'+where+' GROUP BY k.reading'
    if q.get('only_multiple')=='true':group_sql+=' HAVING count(DISTINCT o.identity)>1'
    stamp=read_views.token(db,'homophones')
    scope=(stamp,lid,term,fallback,q.get('only_multiple')=='true') if stamp else None
    labels=LABELS.get(scope)
    if labels is None:
        labels=tuple(r[0] for r in db.execute(group_sql+' ORDER BY k.reading',args))
        LABELS.put(scope,labels,256+sum(64+4*len(s) for s in labels))
    if q.get('_labels') is True:return list(labels)
    structured=q.get('view')=='phonology'
    raw_size='40' if structured else str(q.get('page_size','40'))
    if raw_size not in ('10','20','40','50','all') or not structured and 'page_size' in q and raw_size=='40':
        raise ValueError('每页读音分组数请选择 10、20、50 或全部')
    size=max(1,len(labels)) if raw_size=='all' else int(raw_size)
    pages=max(1,(len(labels)+size-1)//size)
    page=max(1,min(int(q.get('page',1)),pages))
    config=phonology.get(db,lid)
    objects={s:dict(reading=s,items=[]) for s in labels}
    regular=[objects[s] for s in labels[(page-1)*size:page*size]]
    layout={}
    if structured:
        layout=phonology.arrange(list(objects.values()),config,q)
        if q.get('view_only')=='1':regular=[]
    wanted={g['reading'] for g in regular}
    wanted.update(g['reading'] for g in layout.get('pending',[]))
    for block in layout.get('blocks',[]):
        for row in block['rows']:
            for cell in row['cells']:wanted.update(g['reading'] for g in cell['groups'])
    collect=q.get('_collect') is True
    material_version=None
    if structured and q.get('view_only')=='1' and stamp and not collect:
        import hashlib
        material_version=hashlib.sha256(stamp+json.dumps([lid,term,fallback,writing,q.get('only_multiple')=='true'],ensure_ascii=False).encode()).hexdigest()
        known=q.get('known','')
        if material_version==q.get('material_version') and isinstance(known,str) and len(known)<=4096:
            try:previous=json.loads(known) if known else []
            except ValueError:previous=[]
            if isinstance(previous,list) and len(previous)<=128 and all(isinstance(s,str) for s in previous):
                for reading in wanted.intersection(previous):
                    objects[reading]['reuse_items']=True
                    wanted.remove(reading)
    if collect:wanted=set(labels)
    order='o.stage,o.sort_name COLLATE NOCASE,o.sort_num,o.tie,o.owner_order,o.seq'
    number="""CASE WHEN (SELECT count(*) FROM morphemes p WHERE p.language_id=m.language_id AND p.form=m.form)>1 THEN m.number END number"""
    def unpack(record):
        row=json.loads(record['body'])
        row['number']=record['number']
        if not row['readings']:
            if fallback and row['form'].strip():
                row['readings']=[row['form'].strip()];row['provisional']=True
            else:
                row['reason']='缺少读音'+('；'+row['reason'] if row['reason'] else '')
        return row
    labels_wanted=[]
    for reading in sorted(wanted):
        saved=GROUPS.get((scope,writing,reading)) if scope and not collect else None
        if saved is not None:objects[reading]['items']=json.loads(saved)
        else:labels_wanted.append(reading)
    for start in range(0,len(labels_wanted),200):
        batch=labels_wanted[start:start+200]
        params={**args,**{'r'+str(i):v for i,v in enumerate(batch)}}
        marks=','.join(':r'+str(i) for i in range(len(batch)))
        joined=where.replace(' WHERE ',' LEFT JOIN morphemes m ON m.id=o.identity WHERE ',1)
        sql='SELECT k.reading,o.body,'+number+joined+' AND k.reading IN ('+marks+') ORDER BY k.reading,'+order
        groups=defaultdict(dict)
        seen=defaultdict(set)
        for record in long_tasks.steps(db.execute(sql,params)):
            reading=record['reading'];row=unpack(record);identity=row['identity']
            bucket=groups[reading]
            if identity not in bucket:
                bucket[identity]={**row,'sources':[],'writings':[],'forms':[]}
            item=bucket[identity]
            for field,values in (('sources',row['sources']),('writings',row['writings']),('forms',[row['form']])):
                keys=seen[reading,identity,field]
                for v in values:
                    key=json.dumps(v,sort_keys=True,ensure_ascii=False) if isinstance(v,dict) else v
                    if key not in keys:
                        keys.add(key);item[field].append(v)
            item['reason']='；'.join(dict.fromkeys(filter(None,(item['reason']+'；'+row['reason']).split('；'))))
            item['provisional']|=row['provisional']
        for reading,bucket in groups.items():
            objects[reading]['items']=list(bucket.values())
            if writing and not collect:
                for row in bucket.values():row['writings']=[w for w in row['writings'] if w['type_id']==writing]
            if scope and not collect:
                encoded=json.dumps(objects[reading]['items'],ensure_ascii=False,separators=(',',':')).encode()
                GROUPS.put((scope,writing,reading),encoded,len(encoded)+256)
    if collect:return list(objects.values())
    if not structured:
        classify_one=phonology.classifier(config)
        for group in regular:group['classification']=classify_one(group['reading'])
    reviews=' FROM hp_occurrences o WHERE '+active+' AND (o.review OR (o.explicit=0 AND (:fb=0 OR o.fallback=0)))'
    if term:reviews+=' AND instr('+text+',:q)>0'
    count=db.execute('SELECT count(*)'+reviews,args).fetchone()[0]
    rp=max(1,min(int(q.get('review_page',1)),max(1,(count+39)//40)))
    details=reviews.replace(' WHERE ',' LEFT JOIN morphemes m ON m.id=o.identity WHERE ',1)
    review=[]
    for record in db.execute('SELECT o.body,'+number+details+' ORDER BY '+order+' LIMIT 40 OFFSET :off',{**args,'off':(rp-1)*40}):
        row=unpack(record)
        if writing:row['writings']=[w for w in row['writings'] if w['type_id']==writing]
        review.append(row)
    if material_version:
        # Source lists and full spelling alternatives remain in the inspector
        # endpoint. The grid uses only these fields for its buttons and tooltips.
        for reading in wanted:
            g=objects[reading]
            g['items']=[{k:r[k] for k in ('identity','form','number','gloss','writings','origin','reason','provisional')} for r in g['items']]
        layout['material_version']=material_version
    return dict(groups=regular,total=len(labels),page=page,pages=pages,page_size='all' if raw_size=='all' else size,
                review=review,review_total=count,review_page=rp,review_pages=max(1,(count+39)//40),
                writing_types=types,phonology={k:v for k,v in config.items() if k!='assignments'})|layout
