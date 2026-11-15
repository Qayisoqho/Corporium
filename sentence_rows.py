"""SQLite source rows for sentence text and ordered word cells."""
import json
import sqlite3
import record_sources


TABLES = {'corpus': 'entries', 'independent': 'dictionary_examples'}
FIELDS = ('original', 'ipa', 'translation', 'source', 'notes', 'language_id',
          'grammaticality', 'function', 'raw', 'line', 'edited', 'language_notes', 'text_notes')
DISPLAY_FIELDS = ('ipa','translation','notes','edited')


def _select_header(kind, table, condition):
    present = '+'.join(f"(json_type(e.body,'$.{key}') IS NOT NULL)*{1 << i}"
                       for i, key in enumerate(FIELDS))
    fields = ','.join(f"json_extract(e.body,'$.{key}')" for key in FIELDS)
    keys = (*FIELDS, 'words', 'targets') if kind=='independent' else (*FIELDS, 'words')
    removed = ','.join(f"'$.{key}'" for key in keys)
    return f"""SELECT '{kind}',e.id,{present},json_type(e.body,'$.edited'),
        {fields},json_remove(e.body,{removed}) FROM {table} e {condition}"""


def _select_words(kind, table, condition):
    return f"""SELECT '{kind}',e.id,CAST(w.key AS INTEGER),
        w.value->>'$.form',w.value->>'$.gloss',json_remove(w.value,'$.form','$.gloss')
        FROM {table} e,json_each(e.body,'$.words') w {condition}"""


def initialize(db):
    record_sources.initialize(db)
    _initialize_corpus_keys(db)
    columns = ','.join(key + (' INTEGER' if key in ('line','edited') else ' TEXT') for key in FIELDS)
    db.execute(f'''CREATE TABLE IF NOT EXISTS sentence_text_rows(
        kind TEXT NOT NULL,owner_id TEXT NOT NULL,present INTEGER NOT NULL,edited_type TEXT,
        {columns},extra TEXT NOT NULL,PRIMARY KEY(kind,owner_id)) WITHOUT ROWID''')
    db.execute('''CREATE TABLE IF NOT EXISTS sentence_word_rows(
        kind TEXT NOT NULL,owner_id TEXT NOT NULL,position INTEGER NOT NULL,
        form TEXT,gloss TEXT,extra TEXT NOT NULL,PRIMARY KEY(kind,owner_id,position)) WITHOUT ROWID''')
    db.execute('''CREATE INDEX IF NOT EXISTS sentence_word_form ON sentence_word_rows(kind,form COLLATE NOCASE,owner_id,position)''')
    for kind, table in TABLES.items():
        events = ('DELETE',) if record_sources.native(db) else ('INSERT','UPDATE OF body,id','DELETE')
        for event in events:
            suffix = event.split()[0].lower()
            ref = 'OLD' if suffix == 'delete' else 'NEW'
            ids = '(OLD.id,NEW.id)' if suffix == 'update' else f'({ref}.id)'
            remove = ''.join(f"DELETE FROM {t} WHERE kind='{kind}' AND owner_id IN {ids};"
                             for t in ('sentence_text_rows','sentence_word_rows'))
            when = ''
            if suffix != 'delete':
                when = ' WHEN NOT '+record_sources.is_native(table,'NEW.id')
                if suffix == 'update':
                    when += ' AND (OLD.body IS NOT NEW.body OR OLD.id IS NOT NEW.id)'
            name=f'sentence_rows_{table}_{suffix}'
            sql=f'CREATE TRIGGER {name} AFTER {event} ON {table}{when} BEGIN {remove} END'
            previous=db.execute("SELECT sql FROM sqlite_master WHERE type='trigger' AND name=?",(name,)).fetchone()
            if previous and previous[0]==sql:continue
            if previous:db.execute('DROP TRIGGER '+name)
            db.execute(sql)


def _initialize_corpus_keys(db):
    exists = db.execute("SELECT 1 FROM sqlite_master WHERE name='corpus_sentence_keys'").fetchone()
    native = record_sources.native(db)
    project = ("SELECT e.id,e.text_id,e.position,NULLIF(s.language_id,'') FROM entries e "
               "JOIN sentence_text_rows s ON s.kind='corpus' AND s.owner_id=e.id" if native else
               "SELECT e.id,e.text_id,e.position,NULLIF(json_extract(e.body,'$.language_id'),'') FROM entries e")
    if not exists:
        db.execute('''CREATE TABLE corpus_sentence_keys(
            id TEXT PRIMARY KEY,text_id TEXT,position INTEGER,language_id TEXT) WITHOUT ROWID''')
        # The search scope already holds the narrow fields in prepared projects.
        # Do not read every old sentence at startup just to prepare evidence.
        if native:
            db.execute('INSERT INTO corpus_sentence_keys '+project)
        elif db.execute("SELECT count(*) FROM sqlite_master WHERE name IN ('sentence_scope_records','sentence_scope_dirty')").fetchone()[0]==2:
            db.execute("""INSERT INTO corpus_sentence_keys
                SELECT r.id,r.text_id,r.position,NULLIF(json_extract(r.body,'$.language_id'),'')
                FROM sentence_scope_records r WHERE r.kind='corpus' AND NOT EXISTS
                (SELECT 1 FROM sentence_scope_dirty d WHERE d.kind=r.kind AND d.id=r.id)""")
    for event in ('INSERT','UPDATE' if native else 'UPDATE OF body,id,text_id,position','DELETE'):
        suffix = event.split()[0].lower()
        remove = 'DELETE FROM corpus_sentence_keys WHERE id=OLD.id;' if suffix!='insert' else ''
        insert = ('INSERT INTO corpus_sentence_keys '+project+' WHERE e.id=NEW.id '
                  'ON CONFLICT(id) DO UPDATE SET text_id=excluded.text_id,position=excluded.position,language_id=excluded.language_id;'
                  if suffix!='delete' else '')
        change = record_sources.change_sql(db,'entries',record_sources.SCOPE)
        when = (f' WHEN OLD.id IS NOT NEW.id OR {change} OR OLD.text_id IS NOT NEW.text_id '
                'OR OLD.position IS NOT NEW.position' if suffix=='update' else '')
        record_sources.trigger(db,f'sentence_rows_corpus_keys_{suffix}',f'AFTER {event} ON entries{when} BEGIN {remove}{insert} END')


def corpus_keys(db, target):
    """Use the narrow order and language keys for a single dictionary target."""
    if record_sources.native(db):
        return 'corpus_sentence_keys'
    import material_search_index
    if not db.in_transaction:
        db.execute('BEGIN')
    complete = db.execute('SELECT (SELECT count(*) FROM corpus_sentence_keys)='
                          '(SELECT count(*) FROM entries)').fetchone()[0]
    if complete:
        return 'corpus_sentence_keys'
    missing = """FROM lexical_links l JOIN corpus_units u ON u.id=l.unit_id
        LEFT JOIN corpus_sentence_keys k ON k.id=u.entry_id
        WHERE l.lexeme_id=? AND k.id IS NULL"""
    live = ' AND EXISTS(SELECT 1 FROM entries e WHERE e.id=u.entry_id)'
    if db.execute('SELECT 1 '+missing+live+' LIMIT 1',(target,)).fetchone():
        try:
            with material_search_index.preparing(db):
                db.execute("""INSERT INTO corpus_sentence_keys
                    SELECT e.id,e.text_id,e.position,NULLIF(json_extract(e.body,'$.language_id'),'')
                    FROM (SELECT DISTINCT u.entry_id """+missing+') m JOIN entries e ON e.id=m.entry_id',(target,))
        except material_search_index.Unavailable:
            return "(SELECT id,text_id,position,NULLIF(json_extract(body,'$.language_id'),'') language_id FROM entries)"
    return 'corpus_sentence_keys'


def drop_backup_indexes(db):
    for kind, table in TABLES.items():
        for suffix in ('insert','update','delete'):
            db.execute(f'DROP TRIGGER IF EXISTS sentence_rows_{table}_{suffix}')
    for suffix in ('insert','update','delete'):
        db.execute(f'DROP TRIGGER IF EXISTS sentence_rows_corpus_keys_{suffix}')
    db.execute('DROP TABLE IF EXISTS corpus_sentence_keys')


def decode_header(row):
    body = json.loads(row['extra']) if row['extra']!='{}' else {}
    for i, key in enumerate(FIELDS):
        if row['present'] & (1 << i):
            body[key] = bool(row[key]) if key=='edited' and row['edited_type'] in ('true','false') else row[key]
    return body


def headers(db,kind,ids):
    if not ids:return {}
    marks=','.join('?' for _ in ids)
    return {row['owner_id']:decode_header(row) for row in db.execute(
        f'SELECT * FROM sentence_text_rows WHERE kind=? AND owner_id IN ({marks})',[kind,*ids])}


def decode_word(row):
    word = json.loads(row['extra']) if row['extra']!='{}' else {}
    word.update(form=row['form'],gloss=row['gloss'])
    return word


def word_rows(db,kind,ids):
    """Read the effective source slots without sentence headers or target drafts."""
    marks=','.join('?' for _ in ids)
    scope=f'WHERE w.kind=? AND w.owner_id IN ({marks}) ORDER BY w.owner_id,w.position'
    if kind=='corpus':
        query="""SELECT w.owner_id,w.position,w.form,w.gloss,w.extra,w.extra->>'$.annotation_id' annotation_id
                 FROM sentence_word_rows w """
    else:
        import independent_annotations
        form,gloss,identity,override=independent_annotations.override_sql(db)
        extra=independent_annotations.frozen_sql(db)
        query=f"""SELECT w.owner_id,w.position,
            CASE WHEN o.position IS NULL THEN w.form ELSE {form} END form,
            CASE WHEN o.position IS NULL THEN w.gloss ELSE {gloss} END gloss,
            CASE WHEN o.position IS NULL THEN json_remove({extra},'$.annotation_id','$.unit_id')
                ELSE json_remove({override},'$.form','$.gloss','$.annotation_id','$.unit_id') END extra,
            CASE WHEN o.position IS NULL THEN w.extra->>'$.annotation_id' ELSE {identity} END annotation_id
            FROM sentence_word_rows w LEFT JOIN independent_word_overrides o ON o.example_id=w.owner_id AND o.position=w.position """
    return db.execute(query+scope,[kind,*ids])


def read(db, kind, ids):
    """Load only the requested owners, using SQL expansion to prepare old rows."""
    if not ids:
        return {}
    import material_search_index
    if not db.in_transaction:
        db.execute('BEGIN')
    table = TABLES[kind]
    ids = list(dict.fromkeys(ids))
    marks = ','.join('?' for _ in ids)
    scope = f'WHERE kind=? AND owner_id IN ({marks})'
    try:
        headers = list(db.execute('SELECT * FROM sentence_text_rows '+scope,[kind,*ids]))
    except sqlite3.OperationalError as exc:
        if 'no such table: sentence_text_rows' not in str(exc):
            raise
        # The oldest schema's unit migration runs before the sentence tables exist.
        return {r['id']:json.loads(r['body']) for r in db.execute(
            f'SELECT id,body FROM {table} WHERE id IN ({marks}) AND body IS NOT NULL',ids)}
    missing = set(ids) - {r['owner_id'] for r in headers}
    fallback = []
    if missing and not record_sources.native(db):
        condition = 'WHERE e.id IN ('+','.join('?' for _ in missing)+') AND e.body IS NOT NULL'
        header = _select_header(kind,table,condition)
        words = _select_words(kind,table,condition)
        try:
            with material_search_index.preparing(db):
                db.execute('INSERT INTO sentence_text_rows '+header,list(missing))
                db.execute('INSERT INTO sentence_word_rows '+words,list(missing))
            headers.extend(db.execute('SELECT * FROM sentence_text_rows WHERE kind=? AND owner_id IN ('+
                                      ','.join('?' for _ in missing)+')',[kind,*missing]))
        except material_search_index.Unavailable:
            names = ('kind','owner_id','present','edited_type',*FIELDS,'extra')
            headers.extend(dict(zip(names,r)) for r in db.execute(header,list(missing)))
            fallback = [dict(zip(('kind','owner_id','position','form','gloss','extra'),r))
                        for r in db.execute(words+' ORDER BY e.id,CAST(w.key AS INTEGER)',list(missing))]
    result = {}
    for row in headers:
        body = decode_header(row)
        body['words'] = []
        result[row['owner_id']] = body
    word_rows = db.execute('SELECT * FROM sentence_word_rows '+scope+' ORDER BY owner_id,position',[kind,*ids])
    for rows in (word_rows,fallback):
        for row in rows:
            result[row['owner_id']]['words'].append(decode_word(row))
    if kind=='independent':
        import independent_annotations
        for (owner,position),value in independent_annotations.frozen_for_owners(db,ids).items():
            result[owner]['words'][position]['gloss_frozen']=value
    return result


def one(db, kind, owner):
    return read(db,kind,[owner]).get(owner)


def backup_json(db,kind):
    """Encode ordered native sentences in the established portable row format."""
    table=TABLES[kind]
    columns=record_sources.META[table]
    fields=[]
    absent=[]
    for i,key in enumerate(FIELDS):
        value='s.'+key
        if key=='edited':
            value="CASE WHEN s.edited_type IN ('true','false') THEN json(CASE WHEN s.edited THEN 'true' ELSE 'false' END) ELSE s.edited END"
        fields.append(f"'$.{key}',{value}")
        # The array-append path cannot address a member of this object.
        absent.append(f"CASE WHEN s.present & {1 << i} THEN '$[#]' ELSE '$.{key}' END")
    words="""(SELECT json_group_array(json(word)) FROM (
          SELECT json_set(w.extra,'$.form',w.form,'$.gloss',w.gloss) word
          FROM sentence_word_rows w WHERE w.kind=s.kind AND w.owner_id=s.owner_id ORDER BY w.position))"""
    body=f"json_remove(json_set(s.extra,{','.join(fields)},'$.words',json({words})),{','.join(absent)})"
    metadata=','.join(f"'{name}',e.{name}" for name in columns)
    # Non-JSON extensions and rare SQLite real values keep the Python path so
    # the backup never normalizes or rounds a stored value accidentally.
    frozen=''
    if kind=='independent':
        import independent_annotations
        if independent_annotations.enabled(db):
            frozen=f'AND NOT EXISTS(SELECT 1 FROM {independent_annotations.FROZEN_VALUES} f WHERE f.owner_id=e.id)'
    query=f'''SELECT e.rowid,e.id,CASE WHEN s.owner_id IS NOT NULL AND json_valid(s.extra) {frozen}
          AND typeof(s.line)!='real' AND typeof(s.edited)!='real' AND NOT EXISTS(
              SELECT 1 FROM sentence_word_rows w WHERE w.kind=s.kind AND w.owner_id=s.owner_id
                  AND NOT json_valid(w.extra))
          THEN json_object('rowid',e.rowid,{metadata},'body',{body}||'') END encoded
        FROM {table} e LEFT JOIN sentence_text_rows s ON s.kind=? AND s.owner_id=e.id ORDER BY e.rowid'''
    for rowid,owner,encoded in db.execute(query,(kind,)):
        if encoded is not None:
            yield encoded
            continue
        source=one(db,kind,owner)
        if source is None:raise ValueError('备份时未找到句子正文')
        row=db.execute('SELECT rowid,'+','.join(columns)+' FROM '+table+' WHERE rowid=?',(rowid,)).fetchone()
        yield json.dumps(record_sources.portable_row(dict(row,body=source)),ensure_ascii=False)


def audit_inputs(db,kind,ids):
    """Read fields used by the tag audit, omitting transcripts and translations."""
    marks=','.join('?' for _ in ids)
    result={}
    cursor=db.cursor()
    cursor.row_factory=None
    for owner,language,source,extra in cursor.execute(
            f'SELECT owner_id,language_id,source,extra FROM sentence_text_rows WHERE kind=? AND owner_id IN ({marks})',
            (kind,*ids)):
        detail=json.loads(extra) if extra!='{}' else {}
        body={key:detail[key] for key in ('reduplications','orphaned_morphology','gloss_revision',
                                         '_gloss_active_bindings') if key in detail}
        result[owner]=dict(body,language_id=language,source=source,ipa='',translation='',words=[])
    common={}
    for owner,form,gloss,extra in cursor.execute(
            f'''SELECT owner_id,form,gloss,extra FROM sentence_word_rows WHERE kind=? AND owner_id IN ({marks})
                ORDER BY owner_id,position''',(kind,*ids)):
        fields=common.get(extra)
        if fields is None:
            fields=json.loads(extra) if extra!='{}' else {}
            if len(common)<128 and len(extra)<=256 and all(type(value) in (str,int,float,bool,type(None))
                                                             for value in fields.values()):
                common[extra]=fields
        result[owner]['words'].append(dict(fields,form=form,gloss=gloss))
    if kind=='independent':
        import independent_annotations
        for (owner,position),value in independent_annotations.frozen_for_owners(db,ids).items():
            result[owner]['words'][position]['gloss_frozen']=value
    return result


SEARCH_FIELDS = ('ipa', 'translation', 'notes', 'language_notes', 'text_notes', 'original')


def search_values(db, kind, ids):
    """Read the scalar search fields and word forms without expanding analyses."""
    if not ids:
        return {}
    scope = 'WHERE s.kind=? AND s.owner_id IN ('+','.join('?' for _ in ids)+')'
    fields = ','.join(SEARCH_FIELDS)
    result = {}
    for row in db.execute('SELECT owner_id,present,'+fields+' FROM sentence_text_rows s '+scope,[kind,*ids]):
        result[row['owner_id']] = {key:row[key] for key in SEARCH_FIELDS if row['present'] & (1 << FIELDS.index(key))}
        result[row['owner_id']]['words'] = []
    independent = kind == 'independent'
    word_id = 'w.word_id' if independent else "s.extra->>'$.annotation_id'"
    join = ('LEFT JOIN independent_words w ON w.example_id=s.owner_id AND w.position=s.position ' if independent else '')
    for row in db.execute('SELECT s.owner_id,s.position,s.form,'+word_id+' annotation_id FROM sentence_word_rows s '
                          +join+scope+' ORDER BY s.owner_id,s.position',[kind,*ids]):
        result[row['owner_id']]['words'].append(dict(form=row['form'],annotation_id=row['annotation_id']))
    return result


def _header(body):
    present = sum(1 << i for i,key in enumerate(FIELDS) if key in body)
    edited = body.get('edited')
    edited_type = ('true' if edited else 'false') if isinstance(edited,bool) else None
    extra = {key:value for key,value in body.items() if key not in (*FIELDS,'words')}
    return (present,edited_type,*(body.get(key) for key in FIELDS),
            json.dumps(extra,ensure_ascii=False,separators=(',',':')))


def _write_rows(db, kind, owner, body, previous):
    columns = ('present','edited_type',*FIELDS,'extra')
    header = _header(body)
    if previous is None or header != _header(previous):
        names = ','.join(columns)
        db.execute(f'''INSERT INTO sentence_text_rows(kind,owner_id,{names}) VALUES(
            {','.join('?' for _ in range(len(columns)+2))}) ON CONFLICT(kind,owner_id) DO UPDATE SET
            {','.join(f'{key}=excluded.{key}' for key in columns)}''',(kind,owner,*header))
    old_words = previous.get('words',[]) if previous else []
    new_words = body.get('words',[])
    changed = [(i,w) for i,w in enumerate(new_words) if i>=len(old_words) or old_words[i]!=w]
    import independent_annotations
    typed = kind=='independent' and independent_annotations.enabled(db)
    excluded = ('form','gloss','gloss_frozen') if typed else ('form','gloss')
    db.executemany('''INSERT INTO sentence_word_rows VALUES(?,?,?,?,?,?)
        ON CONFLICT(kind,owner_id,position) DO UPDATE SET form=excluded.form,gloss=excluded.gloss,extra=excluded.extra''',
        [(kind,owner,i,w['form'],w['gloss'],json.dumps(
            {k:v for k,v in w.items() if k not in excluded},
            ensure_ascii=False,separators=(',',':'))) for i,w in changed])
    if typed:
        from source_schema import same_value
        for i,w in changed:
            prior=old_words[i] if i<len(old_words) else {}
            if ('gloss_frozen' in w or 'gloss_frozen' in prior) and (
                    ('gloss_frozen' in w)!=('gloss_frozen' in prior) or
                    not same_value(w.get('gloss_frozen'),prior.get('gloss_frozen'))):
                independent_annotations.write_frozen(db,owner,i,w,prior)
    if len(new_words)<len(old_words):
        db.execute('DELETE FROM sentence_word_rows WHERE kind=? AND owner_id=? AND position>=?',
                   (kind,owner,len(new_words)))
    if kind=='independent' and (changed or len(new_words)<len(old_words)):
        _update_independent_slots(db,owner,changed,old_words,len(new_words))


def _update_independent_slots(db, owner, changed, previous, count):
    from source_schema import same_value
    import independent_links

    # Stable slot identities do not need a write when only the label changes.
    identities=[(owner,i,w.get('annotation_id')) for i,w in changed
                if i>=len(previous) or previous[i].get('annotation_id')!=w.get('annotation_id')]
    if identities:
        db.executemany('''INSERT INTO independent_words(example_id,position,word_id) VALUES(?,?,?)
            ON CONFLICT(example_id,position) DO UPDATE SET word_id=excluded.word_id
            WHERE word_id IS NOT excluded.word_id''',identities)
    # Only actual overlays carry a source snapshot. Compare its values when
    # replaying a word edit, so object key order cannot retire an overlay.
    if changed:
        words=dict(changed)
        overlays=independent_links.overrides(db,[owner],list(words))
        stale=[(row['id'],) for row in overlays
               if not same_value(words[row['position']],independent_links.word_value(row['source']))]
        if stale:db.executemany('DELETE FROM independent_word_overrides WHERE id=?',stale)
    if count<len(previous):
        for table in ('independent_words','independent_word_overrides'):
            db.execute(f'DELETE FROM {table} WHERE example_id=? AND position>=?',(owner,count))


def write(db, kind, owner, body, *, columns=None, insert=False, bump=True, only_changed=False, previous=None):
    """Write changed sentence fields and word rows in the caller's transaction."""
    table = TABLES[kind]
    source = {key:value for key,value in body.items() if key!='targets'} if kind=='independent' else body
    if not insert and previous is None:
        previous = one(db,kind,owner)
    if only_changed and previous==source and not columns:
        return source
    record_sources.publish(db,table,owner,source,previous,columns or {},
                           apply_rows=lambda: _write_rows(db,kind,owner,source,previous),
                           insert=insert,bump=bump)
    return source


def write_display_batch(db,kind,changes):
    """Write prevalidated display fields and keep the ordinary journal images."""
    assert record_sources.mode(db) in ('single','drop')
    table = TABLES[kind]
    bits = {key:1 << FIELDS.index(key) for key in DISPLAY_FIELDS}
    mask = sum(bits.values())
    columns = ','.join(key+'=?' for key in DISPLAY_FIELDS)
    with record_sources.writing_batch(db,table,{owner:(before,after) for owner,before,after,_ in changes}):
        def headers():
            for owner,_,body,_ in changes:
                edited = body.get('edited')
                edited_type = ('true' if edited else 'false') if type(edited) is bool else None
                present = sum(bit for key,bit in bits.items() if key in body)
                yield (mask,present,*(body.get(key) for key in DISPLAY_FIELDS),edited_type,kind,owner)

        db.executemany(f'''UPDATE sentence_text_rows SET present=(present & ~?) | ?,{columns},edited_type=?
                            WHERE kind=? AND owner_id=?''',headers())
        db.executemany(f'UPDATE {table} SET revision=max(revision,?)+1 WHERE id=?',
                       ((revision,owner) for owner,_,_,revision in changes))


def write_corpus_batch(db,changes):
    """Apply validated sentence updates whose identity and text placement stay fixed."""
    assert record_sources.mode(db) in ('single','drop')
    with record_sources.writing_batch(db,'entries',{owner:(before,after) for owner,before,after,_ in changes}):
        for owner,before,after,_ in changes:
            _write_rows(db,'corpus',owner,after,before)
        db.executemany('UPDATE entries SET revision=max(revision,?)+1 WHERE id=?',
                       ((revision,owner) for owner,_,_,revision in changes))
