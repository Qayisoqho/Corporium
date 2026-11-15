"""Filter stored text first; expand linguistic analyses only for visible rows."""
import json
import corpus
import languages
import lexicon
import code_switching
import gloss_inheritance
import sentence_search_index
import read_views
import record_sources
import sentence_rows
import sentence_scope_index

CARDS = read_views.Cache(24*1024**2)
CORPUS_COLUMNS = "SELECT e.id,e.text_id,e.position,e.body,e.revision,t.title,t.language_id text_language_id,COALESCE(i.metadata,'{}') text_metadata,'corpus' kind,t.rowid ordering,0 source_order"
CORPUS_SOURCE = ' FROM entries e JOIN texts t ON e.text_id=t.id LEFT JOIN text_info i ON i.text_id=t.id'


def _card(db,row,entry,hits,catalogue):
    if entry is None:
        raw=row['body'] if 'body' in row.keys() else sentence_rows.one(db,row['kind'],row['id'])
        entry=gloss_inheritance.load(db,row['kind'],row['id'],raw)
    languages.annotate(entry,row['text_language_id'],catalogue)
    entry['text_notes']=json.loads(row['text_metadata']).get('notes','')
    return {**entry,**{key:row[key] for key in ('id','text_id','position','revision','title','kind')},'hits':hits}


def saved_card(db,eid):
    return next(iter(saved_cards(db,[eid])),None)


def saved_cards(db,ids,*,batched=False):
    if not ids:return []
    native=record_sources.native(db)
    columns=CORPUS_COLUMNS.replace('e.body,','') if native else CORPUS_COLUMNS
    rows=db.execute(columns+CORPUS_SOURCE+' WHERE e.id IN ('+','.join('?' for _ in ids)+')',ids).fetchall()
    if batched and native:
        import annotations
        bodies=annotations.evidence_cards(db,'corpus',[dict(id=r['id'],language_id=r['text_language_id']) for r in rows])
        catalogue={r['id']:dict(r) for r in db.execute('SELECT * FROM languages')}
        items=[_card(db,row,bodies[row['id']],[],catalogue) for row in rows]
        lexicon.attach_units(db,items)
        return items
    bodies=sentence_rows.read(db,'corpus',[r['id'] for r in rows]) if native else {r['id']:r['body'] for r in rows}
    gloss_inheritance.prefetch(db,'corpus',[r['id'] for r in rows])
    catalogue={r['id']:dict(r) for r in db.execute('SELECT * FROM languages')}
    items=[_card(db,row,gloss_inheritance.load(db,'corpus',row['id'],bodies[row['id']]),[],catalogue) for row in rows]
    lexicon.enrich(db,items)
    return items


def search(db, q, lid):
    if not db.in_transaction:db.execute('BEGIN')
    try:
        size = int(q.get('page_size', 20))
        page = max(1, int(q.get('page', 1)))
    except ValueError:
        raise ValueError('页码和每页条数必须为整数')
    if size not in (10, 20, 50, 100):
        raise ValueError('每页条数请选择 10、20、50 或 100')
    native=record_sources.native(db)
    joined=sentence_scope_index.source_join('corpus') if native and q.get('sentence_language') else ''
    source = CORPUS_SOURCE+joined+" WHERE (?='all' OR t.language_id=?)"
    args = [lid, lid]
    import grammaticality
    # Legality is an independent-example attribute; text sentences have no value.
    if q.get(grammaticality.FIELD):source+=' AND 0'
    extra,values=code_switching.filter_sql(q,"'corpus'",'e.id');source+=extra;args.extend(values)
    if q.get('text'):
        source += ' AND e.text_id=?'
        args.append(q['text'])
    if q.get('sentence_language'):
        field = 's.language_id' if native else "json_extract(e.body,'$.language_id')"
        source += f" AND COALESCE(NULLIF({field},''),t.language_id)=?"
        args.append(q['sentence_language'])
    select = CORPUS_COLUMNS.replace('e.body,','') if native else CORPUS_COLUMNS
    if not q.get('text') and q.get('include_independent')=='true':
        columns = '' if native else 'e.body,'
        joined = sentence_scope_index.source_join('independent') if native and q.get(grammaticality.FIELD) else ''
        union=select+source+f" UNION ALL SELECT e.id,NULL,e.rowid,{columns}e.revision,'独立例句库',e.language_id,'{{}}','independent',e.rowid,1 FROM dictionary_examples e{joined} WHERE (?='all' OR e.language_id=?)"
        args.extend([lid,lid])
        extra,values=grammaticality.filter_sql(q,language='e.language_id',field='s.grammaticality' if native else None);union+=extra;args.extend(values)
        if q.get('sentence_language'):
            union+=' AND e.language_id=?';args.append(q['sentence_language'])
        extra,values=code_switching.filter_sql(q,"'independent'",'e.id');union+=extra;args.extend(values)
        source=' FROM ('+union+')';select='SELECT *'
    order = ' ORDER BY source_order,ordering,position'
    catalogue = {r['id']: dict(r) for r in db.execute('SELECT * FROM languages')}
    tokens = 0
    indexed = None
    if not corpus.normalize(q.get('q', ''), q.get('case') == 'true') and q.get('warnings') != 'true' and q.get('field')!='reduplication':
        total = db.execute('SELECT COUNT(*) FROM (' + select + source + ')', args).fetchone()[0]
        page = min(page, max(1, (total + size - 1) // size))
        # Paginate identities first. Sorting wide sentence JSON up to a deep
        # page otherwise copies the whole corpus into SQLite's temporary sort.
        union=select=='SELECT *'
        keys=db.execute(('SELECT id,kind,ordering,source_order,position' if union else "SELECT e.id,'corpus' kind,t.rowid ordering,0 source_order,e.position")+source+order+' LIMIT ? OFFSET ?',args+[size,(page-1)*size]).fetchall()
        if keys:
            ids=list(dict.fromkeys(r['id'] for r in keys))
            where=(' WHERE id' if union else ' AND e.id')+' IN ('+','.join('?' for _ in ids)+')'
            found={(r['kind'],r['id']):r for r in db.execute(select+source+where,args+ids)}
            rows=[found[(r['kind'],r['id'])] for r in keys]
        else:rows=[]
        visible = [(r, gloss_inheritance.load(db,r['kind'],r['id'],r['body']), []) for r in gloss_inheritance.iter_rows(db,rows,relational=native)]
    elif q.get('warnings') != 'true' and (indexed := sentence_search_index.search(
            db, select+source, args, q.get('field','all'), q.get('q',''),
            q.get('case')=='true', q.get('mode') or ('exact' if q.get('exact')=='true' else 'contains'),
            page, size, text_notes=True,custom_language='all' if q.get('field','all') in ('all','layers','writings') else lid)) is not None:
        total,tokens,page=indexed['total'],indexed['tokens'],indexed['page']
        keys=indexed['keys'];visible=[]
        if keys:
            ids=list(dict.fromkeys(r['id'] for r in keys))
            where=(' WHERE id' if select=='SELECT *' else ' AND e.id')+' IN ('+','.join('?' for _ in ids)+')'
            rows=db.execute(select+source+where,args+ids)
            found={(r['kind'],r['id']):r for r in gloss_inheritance.iter_rows(db,rows,relational=native)}
            visible=[(found[(r['kind'],r['id'])],None,indexed['positions'].get((r['kind'],r['id']),[])) for r in keys]
    else:
        matches = []
        matcher=corpus.QueryMatcher(q.get('q',''),q.get('field','all'),q.get('exact')=='true',q.get('case')=='true',q.get('mode'))
        import annotations
        # The outer text scope still owns the result set. A sentence inside that
        # text may use another language's layers and dictionary spellings.
        custom=annotations.SearchFields(db,'all' if q.get('field','all') in ('all','layers','writings') else lid,q)
        # These fields cannot depend on an inherited dictionary gloss. Resolve
        # meanings only for the visible results, rather than for the whole scan.
        raw_only=q.get('field') in ('form','ipa','translation','notes') and q.get('warnings')!='true'
        scan=select+source
        scalar=raw_only and q.get('field') in ('ipa','translation','notes')
        if scalar:
            # Scalar searches need neither the word array nor its stored analyses.
            # Sort and decode only these fields, then fetch the actual visible
            # records below in the same read snapshot.
            fields=('notes','language_notes') if q['field']=='notes' else (q['field'],)
            if native:
                values = ','.join('s.'+field for field in fields)
                scan=f'SELECT r.*,{values} FROM ({scan}) r JOIN sentence_text_rows s ON s.kind=r.kind AND s.owner_id=r.id'
            else:
                values=','.join("'"+field+"',CASE WHEN json_type(r.body,'$."+field+"') IS NULL THEN '' ELSE json_extract(r.body,'$."+field+"') END" for field in fields)
                scan="SELECT r.id,r.text_id,r.position,json_object("+values+") body,r.revision,r.title,r.text_language_id,r.text_metadata,r.kind,r.ordering,r.source_order FROM ("+scan+") r"
        rows=db.execute(scan+order,args)
        if not raw_only or (native and not scalar):
            rows=gloss_inheritance.iter_rows(db,rows,lightweight=q.get('warnings')!='true',relational=native)
        for row in rows:
            if native and scalar:
                entry = {field:row[field] or '' for field in fields}
            elif raw_only:
                entry = record_sources.body(row,mutable=False)
            else:
                entry = gloss_inheritance.load(db,row['kind'],row['id'],row['body'],metadata=False,lightweight=q.get('warnings')!='true' and not (row['kind']=='independent' and custom.full_references))
            entry['text_notes'] = json.loads(row['text_metadata']).get('notes', '')
            hits, ok = matcher(entry)
            extra=custom.values(row['kind'],row['id'],entry,entry.get('language_id') or row['text_language_id'])
            hits=sorted(set(hits)|{v['word'] for v in extra if v.get('word') is not None})
            ok=ok or bool(extra)
            if not ok:
                continue
            if q.get('warnings') == 'true':
                languages.annotate(entry, row['text_language_id'], catalogue)
                if not entry['warnings']:
                    continue
            tokens += len(hits)
            # A full-corpus match list must not retain every sentence's JSON.
            matches.append(({'kind':row['kind'],'id':row['id']}, None, hits))
        total = len(matches)
        page = min(page, max(1, (total + size - 1) // size))
        visible = matches[(page-1)*size:page*size]
        if visible:
            ids=list(dict.fromkeys(r['id'] for r,_,_ in visible))
            where=(' WHERE id' if select=='SELECT *' else ' AND e.id')+' IN ('+','.join('?' for _ in ids)+')'
            rows=db.execute(select+source+where,args+ids)
            found={(r['kind'],r['id']):r for r in gloss_inheritance.iter_rows(db,rows,relational=native)}
            visible=[(found[(r['kind'],r['id'])],None,hits) for r,_,hits in visible]
    stamp = read_views.token(db,'dictionary')
    items = []
    fresh = []
    for row, entry, hits in visible:
        key = (stamp,row['kind'],row['id']) if stamp else None
        cached = CARDS.get(key)
        if cached is not None:
            item=json.loads(cached)
            item['hits']=hits
        else:
            item=_card(db,row,entry,hits,catalogue)
            fresh.append((key,item))
        items.append(item)
    lexicon.enrich(db,[item for _,item in fresh if item['kind']=='corpus'])
    import annotations
    for key,item in fresh:
        if item['kind']=='independent':annotations.enrich(db,item,'independent',item['id'])
        if key:
            encoded=json.dumps(item,ensure_ascii=False,separators=(',',':')).encode('utf8')
            CARDS.put(key,encoded,len(encoded)+256)
    filtered=q.get('field')=='reduplication' or bool(corpus.normalize(q.get('q',''),q.get('case')=='true')) or q.get('warnings')=='true'
    stats=indexed['code_summary'] if indexed is not None else code_switching.summary(db,select+source,args,{(r['kind'],r['id']) for r,_,_ in matches} if filtered else None)
    return dict(total=total, tokens=tokens, page=page, page_size=size, items=items,code_summary=stats)
