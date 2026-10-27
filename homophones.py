"""Read-only, language-local grouping of explicitly recorded pronunciations."""
import long_tasks
import json
import unicodedata
import phonology
import morpheme_registry

def readings(value):
    if not isinstance(value,list) or any(not isinstance(v,str) for v in value):raise ValueError('读音须逐行填写')
    return list(dict.fromkeys(v.strip() for v in value if v.strip()))

def table(db,lid,q):
    if lid=='all':raise ValueError('请先选择一种语言，再生成同音语素表')
    fallback=q.get('fallback')=='true';query=q.get('q','').casefold();writing=q.get('writing','')
    types=[dict(r) for r in db.execute('SELECT * FROM writing_types WHERE language_id=?',(lid,))]
    if writing and writing not in {t['id'] for t in types}:raise ValueError('书写类型不属于当前语言')
    morphs={r['id']:{**dict(r),'body':json.loads(r['body'])} for r in db.execute('SELECT * FROM morphemes WHERE language_id=?',(lid,))}
    from collections import Counter
    form_counts=Counter(m['form'] for m in morphs.values())
    for m in long_tasks.steps(morphs.values()):
        if form_counts[m['form']]<2:m['number']=None
    links={(r['lexeme_id'],r['analysis_id'],r['component_id']):dict(r) for r in db.execute('SELECT c.* FROM morpheme_components c JOIN dictionary_targets x ON x.id=c.lexeme_id WHERE x.language_id=?',(lid,))}
    occurrences=[];used=set();review=[]
    def record(identity,form,number,body,sources,reason='',origin='语素'):
        values=list(dict.fromkeys(unicodedata.normalize('NFC',v) for v in readings(body.get('readings',[]))));provisional=False
        if not values and fallback and form.strip():values=[form.strip()];provisional=True
        row=dict(identity=identity,form=form,number=number,gloss=body.get('gloss',''),writings=body.get('writings',[]),readings=values,sources=sources,reason=reason,origin=origin,provisional=provisional)
        if not values:review.append({**row,'reason':'缺少读音'+('；'+reason if reason else '')});return
        if len(values)>1:reason='多音；'+reason;row['reason']=reason.rstrip('；')
        if reason:review.append(row)
        for value in values:occurrences.append((unicodedata.normalize('NFC',value),row))
    for x in long_tasks.steps(db.execute('SELECT id,headword,body FROM dictionary_targets WHERE language_id=?',(lid,))):
        body=json.loads(x['body'])
        for a in long_tasks.steps(body.get('word_structure',{}).get('analyses',[])):
            for c in long_tasks.steps(a['components']):
                key=(x['id'],a['id'],c['id']);link=links.get(key);m=morphs.get(link['morpheme_id']) if link else None
                source=dict(lexeme_id=x['id'],headword=x['headword'],analysis_id=a['id'],component_id=c['id'],analysis_title=a.get('title',''),form=c.get('form',''))
                reason=''
                if m:
                    used.add(m['id']);data={**m['body']}
                    if c.get('readings'):data['readings']=c['readings']
                    if c.get('writings'):data['writings']=c['writings']
                    # A table cell names the shared identity; the source retains
                    # its own realization, including deliberate local variants.
                    record(m['id'],m['form'],m['number'],data,[source],reason,'已关联组分')
                else:record('component:'+':'.join(key),c.get('form',''),None,c,[source],reason or '未整理组分','未整理组分')
    for mid,m in long_tasks.steps(morphs.items()):
        if mid not in used or m['body'].get('readings'):record(mid,m['form'],m['number'],m['body'],[],'')
    # Historical component links remain recoverable in the dictionary/undo log.
    # This live analysis only uses components that still exist; no manual review.
    def matches(row):return not query or query in ' '.join([row['form'],row['gloss'],*row.get('readings',[]),*(w['text'] for w in row['writings']),*(s['headword'] for s in row['sources'])]).casefold()
    groups={}
    for reading,row in long_tasks.steps(occurrences):
        if not matches(row) and query not in reading.casefold():continue
        bucket=groups.setdefault(reading,{})
        if row['identity'] not in bucket:bucket[row['identity']]={**row,'sources':list(row['sources']),'writings':list(row['writings']),'forms':[row['form']]}
        else:
            target=bucket[row['identity']]
            for field in long_tasks.steps(('sources','writings')):
                for value in long_tasks.steps(row[field]):
                    if value not in target[field]:target[field].append(value)
            if row['form'] not in target['forms']:target['forms'].append(row['form'])
            target['reason']='；'.join(dict.fromkeys(filter(None,(target['reason']+'；'+row['reason']).split('；'))))
            target['provisional']|=row['provisional']
    result=[dict(reading=k,items=list(v.values())) for k,v in sorted(groups.items()) if q.get('only_multiple')!='true' or len(v)>1]
    if q.get('_collect') is True:return result
    def displayed(row):return {**row,'writings':[w for w in row['writings'] if not writing or w['type_id']==writing]}
    total=len(result)
    page_size=str(q.get('page_size','40')) if q.get('view')!='phonology' else '40'
    if page_size not in ('10','20','50','all','40') or 'page_size' in q and q.get('view')!='phonology' and page_size=='40':raise ValueError('每页读音分组数请选择 10、20、50 或全部')
    size=max(1,total) if page_size=='all' else int(page_size)
    page=max(1,min(int(q.get('page',1)),max(1,(total+size-1)//size)))
    reviews=[displayed(r) for r in review if matches(r)];rp=max(1,min(int(q.get('review_page',1)),max(1,(len(reviews)+39)//40)))
    config=phonology.get(db,lid)
    output=dict(groups=[{**g,'items':[displayed(r) for r in g['items']], 'classification':phonology.classify(g['reading'],config)} for g in result[(page-1)*size:page*size]],total=total,page=page,pages=max(1,(total+size-1)//size),page_size='all' if page_size=='all' else size,review=reviews[(rp-1)*40:rp*40],review_total=len(reviews),review_page=rp,review_pages=max(1,(len(reviews)+39)//40),writing_types=types,phonology=config)
    # Clients need the inventory and concurrency token, not the complete saved
    # classification map on every paginated result.
    output['phonology']={k:v for k,v in config.items() if k!='assignments'}
    if q.get('view')=='phonology':output.update(phonology.arrange([{**g,'items':[displayed(r) for r in g['items']]} for g in result],config,q))
    return output

def source_words(db,lid,identity,page=1):
    """Source summaries without loading examples or whole dictionary records."""
    import languages
    languages.require(db,lid)
    if identity.startswith('component:'):
        parts=identity.split(':')
        if len(parts)!=4:raise ValueError('组分身份无效')
        where='x.id=? AND x.language_id=?';args=(parts[1],lid)
    else:
        import morpheme_registry
        morpheme_registry.get(db,identity,lid)
        where="x.language_id=? AND EXISTS (SELECT 1 FROM morpheme_components c,json_each(x.body,'$.word_structure.analyses') a,json_each(a.value,'$.components') part WHERE c.lexeme_id=x.id AND c.morpheme_id=? AND c.analysis_id=json_extract(a.value,'$.id') AND c.component_id=json_extract(part.value,'$.id'))";args=(lid,identity)
    total=db.execute('SELECT count(*) FROM dictionary_targets x WHERE '+where,args).fetchone()[0]
    pages=max(1,(total+39)//40);page=max(1,min(int(page),pages))
    words=[]
    for row in long_tasks.steps(db.execute('SELECT x.id,x.headword,x.body,x.target_kind FROM dictionary_targets x WHERE '+where+' ORDER BY x.headword COLLATE NOCASE,x.id LIMIT 40 OFFSET ?',(*args,(page-1)*40))):
        body=json.loads(row['body']);words.append(dict(id=row['id'],headword=row['headword'],target_kind=row['target_kind'],usages=[dict(pos=u.get('pos',''),senses=[dict(short_gloss=s.get('short_gloss',''),definition=s.get('definition','')) for s in u.get('senses',[])]) for u in body.get('usages',[])]))
    return dict(words=words,page=page,pages=pages,total=total)
