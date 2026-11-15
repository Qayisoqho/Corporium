"""Rename formally recognized tag atoms without replacing lexical text."""
import copy
import json
import re

FIELDS={'gloss','short_gloss','gloss_addition','unit_gloss','source_gloss','meaning_gloss','display_gloss'}
ATOM=re.compile(r"#(?:sub|super|sup)\[[^\[\]]*\]|[^\s.\-=:+~/;\\,!?，。；：！？\[\](){}<>«»“”\"'#]+")
SCRIPT=re.compile(r'#(?:sub|super|sup)\[[^\[\]]*\]')

def replace(value,old,new):
    import grammar
    lookup=grammar.index([old]);lid=old['language_id']
    # Keep a base and its script runs as a single atom, like the display parser.
    matches=list(ATOM.finditer(value));groups=[]
    for m in matches:
        if groups and groups[-1][1]==m.start() and (SCRIPT.fullmatch(m[0]) or SCRIPT.search(groups[-1][2])):
            a,_,text=groups[-1];groups[-1]=(a,m.end(),text+m[0])
        else:groups.append((m.start(),m.end(),m[0]))
    edits=[]
    for a,z,token in groups:
        prefix=SCRIPT.sub('',value[:a]);explicit=prefix.count('[')>prefix.count(']') or prefix.rfind('<')>prefix.rfind('>')
        result=token
        if grammar.recognized(token,lid,lookup,explicit):result=new
        elif person:=re.fullmatch(r'([123])([A-Za-z]+)',token):
            result=''.join(new if grammar.recognized(p,lid,lookup,explicit) else p for p in person.groups())
        elif SCRIPT.fullmatch(token):
            payload=token[token.index('[')+1:-1]
            result=token[:token.index('[')+1]+replace(payload,old,new)+']'
        if result!=token:edits.append((a,z,result))
    for a,z,result in reversed(edits):value=value[:a]+result+value[z:]
    return value

def walk(value,old,new,transform=None):
    if transform is None:transform=lambda s:replace(s,old,new)
    if isinstance(value,dict):
        return {k:transform(v) if k in FIELDS and isinstance(v,str) else walk(v,old,new,transform) if isinstance(v,(dict,list)) else v for k,v in value.items()}
    if isinstance(value,list):return [walk(v,old,new,transform) for v in value]
    return value

def affected_rows(db,table,lid,*,definitions=False):
    import record_sources
    import sentence_rows

    kind=record_sources.KINDS[table]
    fields=','.join('?' for _ in FIELDS)
    if definitions:
        sql=f"""SELECT d.id FROM {table} d WHERE d.language_id=? AND EXISTS(
            SELECT 1 FROM dictionary_value_rows v WHERE v.target_kind=? AND v.target_id=d.id
            AND v.value_type='text' AND v.slot IN ({fields}) AND grammar_rename_value(v.value))"""
    else:
        if kind=='corpus':
            owner='corpus_sentence_keys e JOIN texts t ON t.id=e.text_id'
            language="COALESCE(NULLIF(e.language_id,''),t.language_id)"
        else:
            owner="dictionary_examples e JOIN sentence_text_rows s ON s.kind='independent' AND s.owner_id=e.id"
            language="COALESCE(NULLIF(s.language_id,''),e.language_id)"
        sql=f"""SELECT e.id FROM {owner} WHERE {language}=? AND EXISTS(
            SELECT 1 FROM sentence_word_rows w WHERE w.kind=? AND w.owner_id=e.id
            AND (grammar_rename_possible(w.gloss) OR w.extra<>'{{}}' AND EXISTS(
              SELECT 1 FROM json_tree(w.extra) j WHERE j.type='text'
              AND j.key IN ({fields}) AND grammar_rename_value(j.atom))))"""
    # Fix the set before writes change which fields meet the predicate.
    selected=[r[0] for r in db.execute(sql,(lid,kind,*sorted(FIELDS)))]
    for start in range(0,len(selected),200):
        batch=selected[start:start+200]
        bodies=(record_sources.read_many(db,table,batch) if definitions else sentence_rows.read(db,kind,batch))
        yield from (dict(id=rid,body=bodies[rid]) for rid in batch)


def rename(db,old,new):
    import corpus
    import dictionary_gloss_sync
    import long_tasks
    import record_sources
    lid=old['language_id'];old={**dict(old),'aliases':json.loads(old['aliases'])}
    from functools import lru_cache
    @lru_cache(maxsize=4096)
    def short(value):return replace(value,old,new)
    def atom(value):return short(value) if len(value)<=512 else replace(value,old,new)
    def transformed(value):return walk(value,old,new,atom)
    native=record_sources.native(db)
    if native:
        names=tuple(corpus.plain(name).casefold() for name in (old['symbol'],*old['aliases']))

        @lru_cache(maxsize=4096)
        def possible(value):
            if atom(value)!=value:
                return True
            # Removing an infix or a Typst escape may expose a tag whose
            # letters were separated in the source. Keep those candidates.
            folded=value.casefold()
            for name in names:
                letters=iter(folded)
                if all(c in letters for c in name):
                    return True
            return False

        db.create_function('grammar_rename_value',1,lambda value:isinstance(value,str) and atom(value)!=value,deterministic=True)
        db.create_function('grammar_rename_possible',1,lambda value:bool(value and
            (possible(value) if len(value)<=512 else possible.__wrapped__(value))),deterministic=True)
    for table in ('lexemes','morphemes'):
        rows=(affected_rows(db,table,lid,definitions=True) if native else
              record_sources.with_bodies(db,table,db.execute('SELECT id FROM '+table+' WHERE language_id=?',(lid,))))
        for row in long_tasks.steps(rows):
            body=row['body'];updated=transformed(body)
            if updated!=body:record_sources.write(db,table,row['id'],updated)
    # A tag rename changes notation, not the identity or validity of an analysis.
    from dictionary_targets import IDENTITIES
    for table,query,bump in [
        ('component_links','SELECT c.id,c.body FROM component_links c JOIN lexical_links l ON l.id=c.id JOIN '+IDENTITIES+' x ON x.id=l.lexeme_id WHERE x.language_id=?',False),
        ('morpheme_components','SELECT c.id,c.body FROM morpheme_components c JOIN morphemes m ON m.id=c.morpheme_id WHERE m.language_id=?',True)]:
        for row in db.execute(query,(lid,)).fetchall():
            body=json.loads(row['body']);updated=transformed(body)
            if updated!=body:db.execute('UPDATE '+table+' SET body=?'+(',revision=revision+1' if bump else '')+' WHERE id=?',(json.dumps(updated,ensure_ascii=False),row['id']))
    for kind,query in [('corpus','SELECT e.*,t.language_id FROM entries_documents e JOIN texts t ON t.id=e.text_id'),('independent','SELECT * FROM dictionary_examples_documents')]:
        table='entries' if kind=='corpus' else 'dictionary_examples'
        rows=affected_rows(db,table,lid) if native else db.execute(query).fetchall()
        for row in long_tasks.steps(rows):
            body=record_sources.body(row,mutable=False)
            if not native and (body.get('language_id') or row['language_id'])!=lid:continue
            analyzed=corpus.analyze(copy.deepcopy(body))
            rules={i:{} for i,w in enumerate(analyzed['words']) if transformed(w)!=w}
            if rules:dictionary_gloss_sync.apply_record(db,kind,row,rules,transformer=lambda w,r:transformed(w),analyzed=analyzed)
    # Preserve local overrides and the literal portions surrounding inherited labels.
    owners="""SELECT b.* FROM gloss_bindings b JOIN entries_documents e ON e.id=b.owner_id JOIN texts t ON t.id=e.text_id
        WHERE b.owner_kind='corpus' AND COALESCE(NULLIF(json_extract(e.body,'$.language_id'),''),t.language_id)=?
        AND (b.override_text IS NOT NULL OR b.pattern<>'[]')
        UNION ALL SELECT b.* FROM gloss_bindings b JOIN dictionary_examples_documents e ON e.id=b.owner_id
        WHERE b.owner_kind='independent' AND COALESCE(NULLIF(json_extract(e.body,'$.language_id'),''),e.language_id)=?
        AND (b.override_text IS NOT NULL OR b.pattern<>'[]')"""
    if native:
        owners="""SELECT b.* FROM gloss_bindings b
          JOIN corpus_sentence_keys e ON e.id=b.owner_id JOIN texts t ON t.id=e.text_id
          WHERE b.owner_kind='corpus' AND COALESCE(NULLIF(e.language_id,''),t.language_id)=?
            AND (b.override_text IS NOT NULL OR b.pattern<>'[]')
          UNION ALL SELECT b.* FROM gloss_bindings b JOIN dictionary_examples e ON e.id=b.owner_id
          JOIN sentence_text_rows s ON s.kind='independent' AND s.owner_id=e.id
          WHERE b.owner_kind='independent' AND COALESCE(NULLIF(s.language_id,''),e.language_id)=?
            AND (b.override_text IS NOT NULL OR b.pattern<>'[]')"""
    for row in long_tasks.steps(db.execute(owners,(lid,lid)).fetchall()):
        override=atom(row['override_text']) if row['override_text'] is not None else None
        pattern=json.dumps([atom(p) if isinstance(p,str) else p for p in json.loads(row['pattern'])],ensure_ascii=False)
        if override!=row['override_text'] or json.loads(pattern)!=json.loads(row['pattern']):db.execute('UPDATE gloss_bindings SET override_text=?,pattern=?,revision=revision+1 WHERE id=?',(override,pattern,row['id']))
    row=db.execute('SELECT metadata FROM languages WHERE id=?',(lid,)).fetchone();meta=json.loads(row[0])
    templates=meta.get('paradigm_templates',[]);updated=transformed(templates)
    if updated!=templates:
        meta['paradigm_templates']=updated;db.execute('UPDATE languages SET metadata=?,revision=revision+1 WHERE id=?',(json.dumps(meta,ensure_ascii=False),lid))
