"""Filter stored text first; expand linguistic analyses only for visible rows."""
import json
import corpus
import languages
import lexicon
import code_switching
import gloss_inheritance


def search(db, q, lid):
    try:
        size = int(q.get('page_size', 20))
        page = max(1, int(q.get('page', 1)))
    except ValueError:
        raise ValueError('页码和每页条数必须为整数')
    if size not in (10, 20, 50, 100):
        raise ValueError('每页条数请选择 10、20、50 或 100')
    source = " FROM entries e JOIN texts t ON e.text_id=t.id LEFT JOIN text_info i ON i.text_id=t.id WHERE (?='all' OR t.language_id=?)"
    args = [lid, lid]
    import grammaticality
    # Legality is an independent-example attribute; text sentences have no value.
    if q.get(grammaticality.FIELD):source+=' AND 0'
    extra,values=code_switching.filter_sql(q,"'corpus'",'e.id');source+=extra;args.extend(values)
    if q.get('text'):
        source += ' AND e.text_id=?'
        args.append(q['text'])
    if q.get('sentence_language'):
        source += " AND COALESCE(NULLIF(json_extract(e.body,'$.language_id'),''),t.language_id)=?"
        args.append(q['sentence_language'])
    select = "SELECT e.id,e.text_id,e.position,e.body,e.revision,t.title,t.language_id text_language_id,COALESCE(i.metadata,'{}') text_metadata,'corpus' kind,t.rowid ordering,0 source_order"
    if not q.get('text') and q.get('include_independent')=='true':
        union=select+source+" UNION ALL SELECT e.id,NULL,e.rowid,e.body,e.revision,'独立例句库',e.language_id,'{}','independent',e.rowid,1 FROM dictionary_examples e WHERE (?='all' OR e.language_id=?)"
        args.extend([lid,lid])
        extra,values=grammaticality.filter_sql(q,language='e.language_id');union+=extra;args.extend(values)
        if q.get('sentence_language'):
            union+=' AND e.language_id=?';args.append(q['sentence_language'])
        extra,values=code_switching.filter_sql(q,"'independent'",'e.id');union+=extra;args.extend(values)
        source=' FROM ('+union+')';select='SELECT *'
    order = ' ORDER BY source_order,ordering,position'
    catalogue = {r['id']: dict(r) for r in db.execute('SELECT * FROM languages')}
    tokens = 0
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
        visible = [(r, gloss_inheritance.load(db,r['kind'],r['id'],r['body']), []) for r in gloss_inheritance.iter_rows(db,rows)]
    else:
        matches = []
        matcher=corpus.QueryMatcher(q.get('q',''),q.get('field','all'),q.get('exact')=='true',q.get('case')=='true',q.get('mode'))
        # These fields cannot depend on an inherited dictionary gloss. Resolve
        # meanings only for the visible results, rather than for the whole scan.
        raw_only=q.get('field') in ('form','ipa','translation','notes') and q.get('warnings')!='true'
        rows=db.execute(select + source + order,args)
        if not raw_only:rows=gloss_inheritance.iter_rows(db,rows,lightweight=q.get('warnings')!='true')
        for row in rows:
            entry = json.loads(row['body']) if raw_only else gloss_inheritance.load(db,row['kind'],row['id'],row['body'],metadata=False,lightweight=q.get('warnings')!='true')
            entry['text_notes'] = json.loads(row['text_metadata']).get('notes', '')
            hits, ok = matcher(entry)
            if not ok:
                continue
            if q.get('warnings') == 'true':
                languages.annotate(entry, row['text_language_id'], catalogue)
                if not entry['warnings']:
                    continue
            tokens += len(hits)
            matches.append((row, None, hits))
        total = len(matches)
        page = min(page, max(1, (total + size - 1) // size))
        visible = matches[(page-1)*size:page*size]
        if raw_only:
            for kind in ('corpus','independent'):
                ids=[r['id'] for r,_,_ in visible if r['kind']==kind]
                if ids:gloss_inheritance.prefetch(db,kind,ids)
    items = []
    for row, entry, hits in visible:
        if entry is None:entry=gloss_inheritance.load(db,row['kind'],row['id'],row['body'])
        languages.annotate(entry, row['text_language_id'], catalogue)
        entry['text_notes'] = json.loads(row['text_metadata']).get('notes', '')
        items.append({**entry, **{k: row[k] for k in ('id','text_id','position','revision','title','kind')}, 'hits': hits})
    lexicon.enrich(db, [e for e in items if e['kind']=='corpus'])
    import annotations
    for e in items:
        if e['kind']=='independent':annotations.enrich(db,e,'independent',e['id'])
    filtered=q.get('field')=='reduplication' or bool(corpus.normalize(q.get('q',''),q.get('case')=='true')) or q.get('warnings')=='true'
    stats=code_switching.summary(db,select+source,args,{(r['kind'],r['id']) for r,_,_ in matches} if filtered else None)
    return dict(total=total, tokens=tokens, page=page, page_size=size, items=items,code_summary=stats)
