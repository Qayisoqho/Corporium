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

def walk(value,old,new):
    if isinstance(value,dict):
        return {k:replace(v,old,new) if k in FIELDS and isinstance(v,str) else walk(v,old,new) if isinstance(v,(dict,list)) else v for k,v in value.items()}
    if isinstance(value,list):return [walk(v,old,new) for v in value]
    return value

def rename(db,old,new):
    import corpus
    import dictionary_gloss_sync
    import long_tasks
    lid=old['language_id'];old={**dict(old),'aliases':json.loads(old['aliases'])}
    for table in ('lexemes','morphemes'):
        for row in long_tasks.steps(db.execute('SELECT id,body FROM '+table+' WHERE language_id=?',(lid,)).fetchall()):
            body=json.loads(row['body']);updated=walk(body,old,new)
            if updated!=body:db.execute('UPDATE '+table+' SET body=?,revision=revision+1 WHERE id=?',(json.dumps(updated,ensure_ascii=False),row['id']))
    # A tag rename changes notation, not the identity or validity of an analysis.
    for table,query,bump in [
        ('component_links','SELECT c.id,c.body FROM component_links c JOIN lexical_links l ON l.id=c.id JOIN dictionary_targets x ON x.id=l.lexeme_id WHERE x.language_id=?',False),
        ('morpheme_components','SELECT c.id,c.body FROM morpheme_components c JOIN morphemes m ON m.id=c.morpheme_id WHERE m.language_id=?',True)]:
        for row in db.execute(query,(lid,)).fetchall():
            body=json.loads(row['body']);updated=walk(body,old,new)
            if updated!=body:db.execute('UPDATE '+table+' SET body=?'+(',revision=revision+1' if bump else '')+' WHERE id=?',(json.dumps(updated,ensure_ascii=False),row['id']))
    for kind,query in [('corpus','SELECT e.*,t.language_id FROM entries e JOIN texts t ON t.id=e.text_id'),('independent','SELECT * FROM dictionary_examples')]:
        for row in long_tasks.steps(db.execute(query).fetchall()):
            body=json.loads(row['body'])
            if (body.get('language_id') or row['language_id'])!=lid:continue
            analyzed=corpus.analyze(copy.deepcopy(body))
            rules={i:{} for i,w in enumerate(analyzed['words']) if walk(w,old,new)!=w}
            if rules:dictionary_gloss_sync.apply_record(db,kind,row,rules,transformer=lambda w,r:walk(copy.deepcopy(w),old,new),analyzed=analyzed)
    # Preserve local overrides and the literal portions surrounding inherited labels.
    for row in db.execute('SELECT * FROM gloss_bindings').fetchall():
        table='entries' if row['owner_kind']=='corpus' else 'dictionary_examples'
        if table=='entries':owner=db.execute('SELECT e.body,t.language_id FROM entries e JOIN texts t ON t.id=e.text_id WHERE e.id=?',(row['owner_id'],)).fetchone()
        else:owner=db.execute('SELECT body,language_id FROM dictionary_examples WHERE id=?',(row['owner_id'],)).fetchone()
        if not owner or (json.loads(owner['body']).get('language_id') or owner['language_id'])!=lid:continue
        override=replace(row['override_text'],old,new) if row['override_text'] is not None else None
        pattern=json.dumps([replace(p,old,new) if isinstance(p,str) else p for p in json.loads(row['pattern'])],ensure_ascii=False)
        if override!=row['override_text'] or json.loads(pattern)!=json.loads(row['pattern']):db.execute('UPDATE gloss_bindings SET override_text=?,pattern=?,revision=revision+1 WHERE id=?',(override,pattern,row['id']))
    row=db.execute('SELECT metadata FROM languages WHERE id=?',(lid,)).fetchone();meta=json.loads(row[0])
    templates=meta.get('paradigm_templates',[]);updated=walk(templates,old,new)
    if updated!=templates:
        meta['paradigm_templates']=updated;db.execute('UPDATE languages SET metadata=?,revision=revision+1 WHERE id=?',(json.dumps(meta,ensure_ascii=False),lid))
