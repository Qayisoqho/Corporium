"""Previewed literal replacement with explicit slot correspondence and one undo step."""
import long_tasks
import copy
import hashlib
import json
import sentence_rows
import re
from collections import defaultdict
from functools import lru_cache
from itertools import groupby,islice,product
import corpus
import lexicon
import record_sources
import segmentation
import gloss_inheritance
import annotations
import replacement_preview

FIELDS=('ipa','form','gloss','translation','layer')
ASCII_CASE_EQUIVALENTS={'i':'iİı','s':'sſ','k':'kK'}

def settings(b):
    field=b.get('field');find=b.get('find');replacement=b.get('replacement','');mode=b.get('mode','contains')
    if field not in FIELDS or not isinstance(find,str) or not find or not isinstance(replacement,str):raise ValueError('请选择替换行并填写非空查找内容')
    if mode not in ('contains','exact','prefix','suffix') or type(b.get('case',True)) is not bool:raise ValueError('匹配选项无效')
    if len(find)>10000 or len(replacement)>10000:raise ValueError('查找或替换内容过长')
    owner=b.get('owner_kind','corpus')
    if owner not in ('corpus','independent'):raise ValueError('请选择文本语料或独立例句库')
    if owner=='independent' and b.get('text_id'):raise ValueError('独立例句替换不能限定文本')
    opt=dict(field=field,find=find,replacement=replacement,mode=mode,case=b.get('case',True),text_id=b.get('text_id',''),owner_kind=owner)
    if field=='layer':
        layer_id=b.get('layer_id','')
        if not isinstance(layer_id,str):raise ValueError('请选择当前语言的自定义标注层')
        opt['layer_id']=layer_id
    return opt


def layer_cells(db,data,opt,lid,*,narrowed=False):
    """Only live cells of this language; orphaned annotations stay untouched."""
    definitions=annotations.layers(db,lid)
    if opt['layer_id'] and not any(l['id']==opt['layer_id'] for l in definitions):raise ValueError('请选择当前语言的自定义标注层')
    selected={l['id']:l for l in definitions if not opt['layer_id'] or l['id']==opt['layer_id']}
    rows={r['id']:r for r in data}
    for row in data:
        row['_replace_cells']=[]
        if narrowed:
            row['_replace_language']=row['language_id'] or lid
            row['_replace_units']={}
        else:
            body=record_sources.body(row,mutable=False);row['_replace_language']=body.get('language_id') or lid
            row['_replace_units']={w.get('annotation_id',''):i for i,w in enumerate(body.get('words',[]))} if opt['owner_kind']=='independent' else {}
    if narrowed and opt['owner_kind']=='independent':
        ids=sorted(rows)
        for start in long_tasks.steps(range(0,len(ids),400)):
            for word in sentence_rows.word_rows(db,'independent',ids[start:start+400]):
                rows[word['owner_id']]['_replace_units'][word['annotation_id'] or '']=word['position']
    if opt['owner_kind']=='corpus':
        if narrowed:
            query="""SELECT u.entry_id,u.id,u.position FROM replacement_owners k
                     CROSS JOIN corpus_units u ON u.entry_id=k.id WHERE u.kind='word' AND u.active=1"""
            args=()
        else:
            query="""SELECT u.entry_id,u.id,u.position FROM corpus_units u JOIN entries e ON e.id=u.entry_id
                     JOIN texts t ON t.id=e.text_id WHERE t.language_id=? AND (?='' OR e.text_id=?) AND u.kind='word' AND u.active=1"""
            args=(lid,opt['text_id'],opt['text_id'])
        for unit in long_tasks.steps(db.execute(query,args)):
            if unit['entry_id'] in rows:rows[unit['entry_id']]['_replace_units'][unit['id']]=unit['position']
    source='replacement_owners k CROSS JOIN annotation_cells c ON c.record_id=k.id' if narrowed else 'annotation_cells c'
    query=f"""SELECT c.* FROM {source} JOIN annotation_layers l ON l.id=c.layer_id
             WHERE c.owner_kind=? AND l.language_id=? ORDER BY l.position,l.id,c.rowid"""
    for cell in long_tasks.steps(db.execute(query,(opt['owner_kind'],lid))):
        row=rows.get(cell['record_id']);definition=selected.get(cell['layer_id'])
        if row is None or definition is None:continue
        if row['_replace_language']!=lid:continue
        positions=row['_replace_units']
        if not annotations.valid_cell(cell,set(positions),[definition]):continue
        row['_replace_cells'].append(dict(cell,word=positions.get(cell['unit_id']),layer_name=definition['name']))
    return definitions


def cell_identity(change):return change.get('cell_id',change['word'])


def change_key(rid,cell,start,end,layer=False):
    return json.dumps([rid,'layer',cell,start,end],ensure_ascii=False,separators=(',',':')) if layer else f'{rid}:{cell}:{start}:{end}'

def pattern(opt):
    value=re.escape(opt['find'])
    if opt['mode'] in ('exact','prefix'):value=r'\A'+value
    if opt['mode'] in ('exact','suffix'):value+=r'\Z'
    return re.compile(value,0 if opt['case'] else re.IGNORECASE)

def literal_filter(db,column,opt,regex):
    """Use SQLite for binary matches and preserve Python's Unicode case rules."""
    value=opt['find']
    # ASCII punctuation/digits and these CJK ideographs have no case pairs.
    caseless=all(c.isascii() and not c.isalpha() or '\u3400'<=c<='\u9fff' for c in value)
    if (opt['case'] or caseless) and opt['mode']!='suffix':
        if opt['mode']=='exact':return f'{column} COLLATE BINARY = ?',(value,)
        return f'instr({column},?)'+('=1' if opt['mode']=='prefix' else '>0'),(value,)
    if not opt['case'] and opt['mode']=='exact' and value.isascii() and '\x00' not in value:
        # Include the non-ASCII equivalents of ASCII letters in Python re.I.
        escaped={'[':'[[]','*':'[*]','?':'[?]'}
        glob=''.join('['+c.upper()+ASCII_CASE_EQUIVALENTS.get(c.lower(),c.lower())+']' if c.isalpha()
                     else escaped.get(c,c) for c in value)
        return f'{column} GLOB ?',(glob,)
    db.create_function('literal_replace_match',1,lambda value:bool(value is not None and regex.search(value)),deterministic=True)
    return f'literal_replace_match({column})',()

def check_text_scope(db,opt,lid):
    if opt['text_id']:
        text=db.execute('SELECT language_id FROM texts WHERE id=?',(opt['text_id'],)).fetchone()
        if not text or text[0]!=lid:raise ValueError('文本不存在或不属于当前语言工作区')

def records(db,opt,lid):
    kind=opt['owner_kind'];native=record_sources.native(db)
    if kind=='independent':
        table='dictionary_examples' if native else 'dictionary_examples_documents'
        rows=(dict(r,title='独立例句库',position=i) for i,r in enumerate(
            db.execute(f'SELECT * FROM {table} WHERE language_id=? ORDER BY rowid',(lid,)),1))
    else:
        check_text_scope(db,opt,lid)
        table='entries' if native else 'entries_documents'
        rows=db.execute(f"""SELECT e.*,t.title FROM {table} e JOIN texts t ON t.id=e.text_id
          WHERE t.language_id=? AND (?='' OR e.text_id=?) ORDER BY t.rowid,e.position""",(lid,opt['text_id'],opt['text_id']))
    return [dict(row,body=gloss_inheritance.load(db,kind,row['id'],row['body']))
            for row in long_tasks.steps(gloss_inheritance.iter_rows(db,rows,kind,relational=native))]

def source_scope(db,opt,lid):
    if opt['owner_kind']=='independent':
        count=db.execute('SELECT COUNT(*) FROM dictionary_examples WHERE language_id=?',(lid,)).fetchone()[0]
        return """SELECT id,revision,row_number() OVER (ORDER BY rowid) AS position,
          '独立例句库' AS title,0 AS text_order FROM dictionary_examples WHERE language_id=?""",(lid,),count
    check_text_scope(db,opt,lid)
    where='t.language_id=?'
    params=[lid]
    if opt['text_id']:
        where+=' AND e.text_id=?'
        params.append(opt['text_id'])
    scope=f'FROM entries e JOIN texts t ON t.id=e.text_id WHERE {where}'
    count=db.execute('''SELECT COALESCE(SUM((SELECT count(*) FROM entries e WHERE e.text_id=t.id)),0)
       FROM texts t WHERE t.language_id=?'''+(' AND t.id=?' if opt['text_id'] else ''),params).fetchone()[0]
    return 'SELECT e.id,e.revision,e.text_id,e.position,t.title,t.rowid AS text_order '+scope,params,count

def scalar_candidates(db,opt,lid,regex,source=None):
    field=opt['field'];kind=opt['owner_kind']
    predicate,args=literal_filter(db,'s.'+field,opt,regex)
    scope,params,count=source or source_scope(db,opt,lid)
    if source is None and kind=='corpus' and not opt['text_id']:
        rows=db.execute(f"""WITH hits AS MATERIALIZED (SELECT s.owner_id,s.{field} value FROM sentence_text_rows s
          WHERE s.kind=? AND {predicate}), scope AS ({scope})
          SELECT e.*,s.value FROM hits s JOIN scope e ON e.id=s.owner_id ORDER BY e.text_order,e.position""",(kind,*args,*params))
        return rows,count
    rows=db.execute(f"""WITH scope AS ({scope})
      SELECT e.*,s.{field} AS value FROM scope e
      CROSS JOIN sentence_text_rows s ON s.kind=? AND s.owner_id=e.id
      WHERE {predicate} ORDER BY e.text_order,e.position""",(*params,kind,*args))
    return rows,count

def scalar_token(db,opt,lid,rows,changes=()):
    """Sign matched source fields and their live associations, not the whole language."""
    kind=opt['owner_kind']
    digest=hashlib.sha256(json.dumps([lid,opt,rows,changes],ensure_ascii=False,sort_keys=True).encode())
    display=opt['field'] in ('ipa','translation')
    queries=[
        (True,"""SELECT g.*,m.revision,m.gloss FROM gloss_bindings g JOIN gloss_meanings m ON m.id=g.meaning_id
                 WHERE g.owner_kind=? AND g.owner_id IN ({ids}) ORDER BY g.owner_id,g.id""")]
    if not display:
        queries.append((True,"SELECT c.* FROM annotation_cells c WHERE c.owner_kind=? AND c.record_id IN ({ids}) ORDER BY c.record_id,c.id"))
    if kind=='corpus':
        if not display:
            queries.append((False,'SELECT u.* FROM corpus_units u WHERE u.entry_id IN ({ids}) ORDER BY u.entry_id,u.id'))
        queries.append((False,"""SELECT l.*,COALESCE(x.revision,m.revision),a.form_id,a.features FROM corpus_units u
               CROSS JOIN lexical_links l ON l.unit_id=u.id
               LEFT JOIN lexemes x ON x.id=l.lexeme_id LEFT JOIN morphemes m ON m.id=l.lexeme_id
               LEFT JOIN morphology_analyses a ON a.id=l.id
               WHERE u.entry_id IN ({ids}) ORDER BY u.entry_id,u.id"""))
    else:
        queries.extend([
            (False,"""SELECT l.*,COALESCE(x.revision,m.revision) FROM independent_links l
               LEFT JOIN lexemes x ON x.id=l.lexeme_id LEFT JOIN morphemes m ON m.id=l.lexeme_id
               WHERE l.example_id IN ({ids}) ORDER BY l.example_id,l.position"""),
            (False,'SELECT w.* FROM independent_word_overrides w WHERE w.example_id IN ({ids}) ORDER BY w.example_id,w.position')])
    owners=iter(row['id'] for row in rows)
    while batch:=list(islice(owners,200)):
        placeholders=','.join('?' for _ in batch)
        for scoped,query in queries:
            records=db.execute(query.format(ids=placeholders),[kind,*batch] if scoped else batch)
            while chunk:=records.fetchmany(400):
                long_tasks.checkpoint()
                digest.update(json.dumps([tuple(record) for record in chunk],ensure_ascii=False,separators=(',',':')).encode())
            digest.update(b'\n')
    return digest.hexdigest()

def scalar_edits(db,rows,opt,by_entry):
    kind=opt['owner_kind'];field=opt['field']
    for row in long_tasks.steps(gloss_inheritance.iter_rows(db,rows,kind,relational=True)):
        source=row['body']
        body=dict(source,words=list(source['words']))
        effective=gloss_inheritance.load(db,kind,row['id'],body,metadata=False,include_targets=False)
        value=replaced_value(source[field],opt['replacement'],by_entry[row['id']])
        effective.update({field:value,'edited':True})
        check_export(effective)
        yield row,{**source,field:value,'edited':True}

def effective_rows(db,rows,kind,*,preview=False):
    for row in long_tasks.steps(gloss_inheritance.iter_rows(db,rows,kind,relational=True)):
        source=row['body']
        if not preview:row['_stored_body']=source
        body=source if preview else dict(source,words=[dict(word) for word in source['words']])
        row['body']=gloss_inheritance.load(db,kind,row['id'],body,metadata=False,include_targets=not preview)
        yield row

def word_candidates(db,opt,lid,regex,source=None,*,preview=False):
    scope,params,count=source or source_scope(db,opt,lid)
    kind,field=opt['owner_kind'],opt['field']
    if opt['case'] and opt['find']==opt['replacement']:return (),count
    if field=='form' and source is None and not opt['text_id']:
        return form_candidates(db,opt,regex,scope,params,preview),count
    value='w.'+field;form='w.form';extra='w.extra';overrides=''
    gloss='w.gloss'
    if kind=='independent':
        from independent_annotations import override_sql, frozen_sql
        saved_form,saved_gloss,_,image=override_sql(db)
        overrides='LEFT JOIN independent_word_overrides o ON o.example_id=w.owner_id AND o.position=w.position'
        form=f"CASE WHEN o.position IS NULL THEN w.form ELSE {saved_form} END"
        gloss=f"CASE WHEN o.position IS NULL THEN w.gloss ELSE {saved_gloss} END"
        value=form if field=='form' else gloss
        extra=f"""CASE WHEN o.position IS NULL THEN json_remove({frozen_sql(db)},'$.annotation_id','$.unit_id')
              ELSE json_remove({image},'$.form','$.gloss','$.annotation_id','$.unit_id') END"""
    predicate,args=literal_filter(db,value,opt,regex)
    cte='WITH scope AS ('+scope+')'
    join='';columns='NULL AS bound_word,NULL AS extra,NULL AS form'
    if field=='gloss':
        stale_slots(db,kind,cte,params)
        join='LEFT JOIN temp.text_replace_stale_words b ON b.owner_id=e.id AND b.position=w.position'
        predicate=f'({predicate} OR b.word_id IS NOT NULL)'
        columns=f'b.word_id AS bound_word,CASE WHEN b.word_id IS NOT NULL THEN {extra} END AS extra,{form} AS form'
    if preview:
        columns+=f',{form} source_form,{gloss} source_gloss,{extra} source_extra'
    rows=db.execute(f"""{cte}
      SELECT e.*,w.position AS word,{value} AS value,{columns} FROM scope e
      CROSS JOIN sentence_word_rows w ON w.kind=? AND w.owner_id=e.id {overrides} {join}
      WHERE {predicate} ORDER BY text_order,e.position,e.id,word""",(*params,kind,*args))
    return rows,count


def form_candidates(db,opt,regex,scope,params,preview):
    kind=opt['owner_kind']
    predicate,args=literal_filter(db,'w.form',opt,regex)
    needle=opt['find']
    source='sentence_word_rows w'
    if opt['mode']=='exact' and needle.isascii() and '\x00' not in needle:
        special=sum(c in ASCII_CASE_EQUIVALENTS for c in needle.lower())
        if opt['case'] or special<=3:
            spellings=[needle] if opt['case'] else [''.join(v) for v in product(*(ASCII_CASE_EQUIVALENTS.get(c,c) for c in needle.lower()))]
            predicate='w.form COLLATE NOCASE IN ('+','.join('?' for _ in spellings)+')'
            args=spellings
            if db.execute("SELECT 1 FROM sqlite_master WHERE name='sentence_word_form'").fetchone():
                source+=' INDEXED BY sentence_word_form'
    columns=',w.form source_form,w.gloss source_gloss,w.extra source_extra' if preview else ''
    exclude=''
    overrides=''
    override_args=()
    if kind=='independent':
        from independent_annotations import override_sql, frozen_sql
        form,gloss,_,image=override_sql(db)
        if preview:
            columns=f',w.form source_form,w.gloss source_gloss,{frozen_sql(db)} source_extra'
        exclude="""AND NOT EXISTS (SELECT 1 FROM independent_word_overrides o
          WHERE o.example_id=w.owner_id AND o.position=w.position)"""
        predicate_override,override_args=literal_filter(db,form,opt,regex)
        extra=f",{form},{gloss},json_remove({image},'$.form','$.gloss')" if preview else ''
        overrides=f"""UNION ALL SELECT w.owner_id,w.position,{form} AS value{extra}
           FROM independent_word_overrides o CROSS JOIN sentence_word_rows w
             ON w.kind='independent' AND w.owner_id=o.example_id AND w.position=o.position
           WHERE {predicate_override}"""
    order='JOIN' if kind=='independent' else 'CROSS JOIN'
    return db.execute(f"""WITH hits AS MATERIALIZED (
       SELECT w.owner_id,w.position,w.form AS value{columns} FROM {source}
       WHERE w.kind=? AND {predicate} {exclude} {overrides}), scope AS ({scope})
       SELECT e.*,h.position AS word,h.value,NULL AS bound_word {',h.source_form,h.source_gloss,h.source_extra' if preview else ''}
       FROM hits h {order} scope e ON e.id=h.owner_id ORDER BY text_order,e.position,e.id,word""",(kind,*args,*override_args,*params))

def stale_slots(db,kind,cte,params):
    db.execute('''CREATE TEMP TABLE IF NOT EXISTS text_replace_stale_words(
      owner_id TEXT,position INTEGER,word_id TEXT,PRIMARY KEY(owner_id,position)) WITHOUT ROWID''')
    db.execute('DELETE FROM temp.text_replace_stale_words')
    if kind=='corpus':
        slots="""CROSS JOIN corpus_units u ON u.id=b.word_id AND u.active=1
                    AND u.kind='word' AND u.entry_id=b.owner_id"""
        linked=''
    else:
        from independent_annotations import override_sql
        _,_,identity,_=override_sql(db)
        slots="""CROSS JOIN sentence_word_rows u ON u.kind='independent' AND u.owner_id=b.owner_id
                 LEFT JOIN independent_word_overrides o ON o.example_id=u.owner_id AND o.position=u.position"""
        linked=f""" AND b.word_id=CASE WHEN o.position IS NULL THEN u.extra->>'$.annotation_id'
                                     ELSE {identity} END"""
    db.execute(f"""{cte}, changed AS MATERIALIZED (
       SELECT DISTINCT b.owner_id,b.word_id FROM scope e
       CROSS JOIN gloss_bindings b ON b.owner_kind=? AND b.owner_id=e.id
       CROSS JOIN gloss_meanings m ON m.id=b.meaning_id WHERE {gloss_inheritance.STALE_BINDING})
       INSERT OR IGNORE INTO temp.text_replace_stale_words
       SELECT b.owner_id,u.position,b.word_id FROM changed b {slots} WHERE 1=1{linked}""",(*params,kind))

def word_plan(db,opt,lid,regex,check,source=None,wanted=None,*,review=False):
    from gloss_search_index import EFFECTIVE_FIELDS,effective_slot
    candidates,count=word_candidates(db,opt,lid,regex,source,preview=check)
    groups=(list(rows) for _,rows in groupby(long_tasks.steps(candidates),key=lambda row:row['id']))
    kind=opt['owner_kind'];field=opt['field']
    rows=[];changes=[];values=[];by_entry=defaultdict(list);slots={}
    effective={};incompatible=set()
    @lru_cache(maxsize=256)
    def rendered(form,value,extra,bindings):
        return effective_slot(form,value,extra,bindings)

    while batch:=list(islice(groups,100)):
        stale=[group[0]['id'] for group in batch if any(row['bound_word'] is not None for row in group)]
        if stale:gloss_inheritance.prefetch(db,kind,stale,changed_only=True)
        for group in batch:
            first=group[0];rid=first['id']
            bindings=defaultdict(list)
            if rid in stale:
                for row in gloss_inheritance.bindings(db,kind,rid,changed_only=True):
                    bindings[row['word_id']].append(tuple(row[key] for key in EFFECTIVE_FIELDS))
            for row in group:
                index,value=row['word'],row['value']
                word=None
                if row['bound_word'] in bindings:
                    extras=row['extra'];form=row['form'];active=tuple(bindings[row['bound_word']])
                    lookup=rendered if len(form)+len(value)+len(extras)<16384 else rendered.__wrapped__
                    word=lookup(form,value,extras,active)
                    value=word['gloss']
                    if check and not all(export_field(word[k],word.get(k+'_kind')) for k in ('form','gloss')):
                        incompatible.add(rid)
                previous=len(changes)
                for match in regex.finditer(value):
                    if match.group()==opt['replacement']:continue
                    start,end=match.span()
                    key=change_key(rid,index,start,end)
                    if wanted is not None and key not in wanted:continue
                    change=dict(key=key,id=rid,word=index,start=start,end=end,
                                before=value,after=value[:start]+opt['replacement']+value[end:],
                                title=first['title'],position=first['position'])
                    changes.append(change);by_entry[rid].append(change)
                    if len(changes)>10000:raise ValueError('超过 10000 处匹配，请缩小查找范围')
                if len(changes)>previous:
                    values.append((rid,index,value))
                    if check:slots[rid,index]=(row['source_form'],row['source_gloss'],row['source_extra'])
                    if check and word is not None:effective[rid,index]=word
            if rid in by_entry:rows.append({key:first[key] for key in ('id','revision','position','title','text_order')})
    conflicts=[];blocked=[]
    if check:
        conflicts,blocked=word_preview_checks(db,rows,opt,by_entry,slots,
            resolved=(effective,incompatible) if field=='gloss' else None)
    p=dict(token=None,changes=changes,conflicts=conflicts,blocked=blocked,records=count)
    if wanted is None and not (review and replacement_preview.remember(db,__name__,lid,p,rows,opt)):
        p['token']=scalar_token(db,opt,lid,rows,values)
    return p,rows,opt

def scalar_plan(db,opt,lid,regex,check,source=None,wanted=None,*,review=False):
    candidates,count=scalar_candidates(db,opt,lid,regex,source)
    rows=[];changes=[];by_entry=defaultdict(list)
    for row in long_tasks.steps(candidates):
        rid=row['id'];value=row['value']
        for match in regex.finditer(value):
            if match.group()==opt['replacement']:continue
            start,end=match.span()
            key=change_key(rid,None,start,end)
            if wanted is not None and key not in wanted:continue
            change=dict(key=key,id=rid,word=None,start=start,end=end,before=value,
                        after=value[:start]+opt['replacement']+value[end:],title=row['title'],position=row['position'])
            changes.append(change)
            by_entry[rid].append(change)
            if len(changes)>10000:raise ValueError('超过 10000 处匹配，请缩小查找范围')
        if rid in by_entry:rows.append(dict(row))
    blocked=[]
    if check:
        ready,_=preview_exports(db,opt['owner_kind'],rows)
        field=opt['field']
        pending=(row for row in rows if row['id'] not in ready or not export_field(
            replaced_value(row['value'],opt['replacement'],by_entry[row['id']])))
        for batch in long_tasks.steps(gloss_inheritance.iter_rows(db,pending,opt['owner_kind'],relational=True)):
            try:
                body=gloss_inheritance.load(db,opt['owner_kind'],batch['id'],batch['body'],metadata=False,include_targets=False)
                field=opt['field']
                body.update({field:replaced_value(body[field],opt['replacement'],by_entry[batch['id']]),'edited':True})
                check_export(body)
            except ValueError as e:
                blocked.append(dict(id=batch['id'],title=batch['title'],position=batch['position'],reason=str(e)))
    p=dict(token=None,changes=changes,conflicts=[],blocked=blocked,records=count)
    if wanted is None and not (review and replacement_preview.remember(db,__name__,lid,p,rows,opt)):
        p['token']=scalar_token(db,opt,lid,rows)
    return p,rows,opt

@lru_cache(maxsize=512)
def word_structure(form,gloss,confirmed):
    units,uncertain=segmentation.parse_word(corpus.clean(form),corpus.clean(gloss),confirmed)
    return [(u['key'],u['kind'],u.get('host'),u.get('boundary'),len(u['fragments']),bool(u['form'].strip()))
            for u in units],uncertain


def transform_word(old,new,*,rebase=True):
    """Retain confirmed groups only when their structural correspondence is certain."""
    if (old['form'],old['gloss'])==(new['form'],new['gloss']):return ''
    reasons=[]
    old_snapshot={k:old[k] for k in ('form','gloss')};new_snapshot={k:new[k] for k in ('form','gloss')}
    try:
        confirmed=old.get('infix_confirmation')==old_snapshot
        parse=word_structure if sum(map(len,(*old_snapshot.values(),*new_snapshot.values())))<8192 else word_structure.__wrapped__
        a,uncertain_a=parse(old['form'],old['gloss'],confirmed)
        z,uncertain_z=parse(new['form'],new['gloss'],confirmed)
        if a!=z:reasons.append('语素切分或空成分发生变化')
        if uncertain_a or uncertain_z:reasons.append('中缀结构存在歧义')
    except ValueError:reasons.append('语素边界或中缀结构无法可靠对应')
    if corpus.boundary_count(old['form'])!=corpus.boundary_count(new['form']):reasons.append('音系边界改变')
    if old.get('punctuation') and old.get('punctuation_form')==old['form']:reasons.append('已确认的标点内容改变')
    for group in old.get('morph_groups',[]):
        if group.get('snapshot')!=old_snapshot:reasons.append('存在尚未核对的多部分语素组合')
        elif old['gloss']!=new['gloss']:reasons.append('组合成员的标注改变，请核对组合释义')
    if not reasons and rebase:
        for group in new.get('morph_groups',[]):group['snapshot']=new_snapshot.copy()
        if old.get('infix_confirmation')==old_snapshot:new['infix_confirmation']=new_snapshot.copy()
    return '；'.join(dict.fromkeys(reasons))

def preserve_independent_refs(old,body,indices,unsafe,*,analyzed=False):
    """Rebase only current references whose fixed-slot structure survived."""
    before=old if analyzed else corpus.analyze(copy.deepcopy(old))
    def unit(word,key):
        return dict(key='@word',form=word['form'],gloss=word['gloss'],fragments=[]) if key=='@word' else next((m for m in word.get('morphemes',[]) if m['key']==key),None)
    for target in body.get('targets',[]):
        ref=target.get('segmentation_ref')
        if not ref or ref.get('detached') or ref['word'] not in indices or ref['word'] in unsafe:continue
        index=ref['word'];a=before['words'][index];z=body['words'][index]
        previous=unit(a,ref['key']);current=unit(z,ref['key'])
        if previous and current and segmentation.reference(a,index,previous)==ref:
            target['segmentation_ref']=segmentation.reference(z,index,current)
            target.pop('segmentation_review',None)

def replaced_value(value,replacement,changes):
    for c in sorted(changes,key=lambda c:c['start'],reverse=True):
        value=value[:c['start']]+replacement+value[c['end']:]
    return value


_CONTENT_MARKS = re.compile(r'[\[\]\\]')
_STRING_MARKS = re.compile(r'["\\]')


@lru_cache(maxsize=512)
def plain_export_word(form,gloss,extra):
    # Most cells have neither Typst delimiters nor string fields. Read the
    # extension metadata only when the delimiters make the distinction matter.
    if not isinstance(form,str) or not isinstance(gloss,str):return False
    if not (_CONTENT_MARKS.search(form) or _CONTENT_MARKS.search(gloss) or '"' in form or '"' in gloss):
        return True
    kinds=json.loads(extra)
    return export_field(form,kinds.get('form_kind')) and export_field(gloss,kinds.get('gloss_kind'))


@lru_cache(maxsize=1024)
def _export_field(value,kind):
    if kind=='string':
        if not _STRING_MARKS.search(value):return True
        source='"'+value+'"'
    else:
        if not _CONTENT_MARKS.search(value):return True
        source='['+value+']'
    parser=corpus.Parser(source)
    try:
        return parser.value()['text']==value and parser.i==len(source)
    except corpus.ParseError:
        return False


def export_field(value,kind='content'):
    return (_export_field if len(value)<4096 else _export_field.__wrapped__)(value,kind)


def plain_exports(db,kind,rows):
    """Prove unchanged fields use the simple, independently checked Typst format."""
    def check_word(form,gloss,extra):
        if not isinstance(form,str) or not isinstance(gloss,str):return False
        operation=plain_export_word if len(form)+len(gloss)+len(extra)<8192 else plain_export_word.__wrapped__
        return operation(form,gloss,extra)
    db.create_function('plain_export_word',3,check_word,deterministic=True)
    db.create_function('preview_export_content',1,lambda value:isinstance(value,str) and export_field(value),deterministic=True)
    def plain_content(column):
        return f"""typeof({column})='text' AND CASE WHEN instr({column},'[') OR instr({column},']') OR instr({column},char(92))
                    THEN preview_export_content({column}) ELSE 1 END"""
    function=1<<sentence_rows.FIELDS.index('function')
    overrides=''
    if kind=='independent':
        from independent_annotations import override_sql
        form,gloss,_,image=override_sql(db)
        overrides=f"""AND NOT EXISTS (SELECT 1 FROM independent_word_overrides o WHERE o.example_id=s.owner_id
           AND NOT plain_export_word({form},{gloss},{image}))"""
    ordinary=lambda field:f"instr(w.{field},'[') OR instr(w.{field},']') OR instr(w.{field},char(92)) OR instr(w.{field},char(34))"
    ready=set()
    owners=sorted(row['id'] for row in rows)
    for start in long_tasks.steps(range(0,len(owners),400)):
        ids=owners[start:start+400]
        marks=','.join('?' for _ in ids)
        query=f"""SELECT s.owner_id FROM sentence_text_rows s WHERE s.kind=? AND s.owner_id IN ({marks})
          AND (s.function IN ('pass','gloss') OR (s.present & {function})=0)
          AND (json_type(s.extra,'$.reduplications') IS NULL OR
               (json_type(s.extra,'$.reduplications')='array' AND json_array_length(s.extra,'$.reduplications')=0))
          AND {plain_content('s.ipa')} AND {plain_content('s.translation')}
          AND NOT EXISTS (SELECT 1 FROM sentence_word_rows w WHERE w.kind=s.kind AND w.owner_id=s.owner_id
            AND (typeof(w.form)<>'text' OR typeof(w.gloss)<>'text' OR CASE WHEN {ordinary('form')} OR {ordinary('gloss')}
                 THEN NOT plain_export_word(w.form,w.gloss,w.extra) ELSE 0 END))
          {overrides}"""
        ready.update(row[0] for row in db.execute(query,[kind,*ids]))
    return ready


def preview_exports(db,kind,rows,slots=None):
    from gloss_search_index import effective_inputs,effective_slot

    ready=plain_exports(db,kind,rows)
    ids=sorted(ready);effective={}
    cached=lru_cache(maxsize=256)(effective_slot)
    for start in long_tasks.steps(range(0,len(ids),300)):
        owners=ids[start:start+300]
        for row,bindings in long_tasks.steps(effective_inputs(db,kind,owners,only_bound=True)):
            rid=row['owner_id'];key=(rid,row['position'])
            form,value,extra=row['form'],row['gloss'],row['extra']
            operation=cached if len(form)+len(value)+len(extra)<8192 and len(bindings)<=32 else effective_slot
            word=operation(form,value,extra,bindings)
            if not all(export_field(word[k],word.get(k+'_kind')) for k in ('form','gloss')):ready.discard(rid)
            elif slots is not None and key in slots:effective[key]=word
    return ready,effective


def word_preview_checks(db,rows,opt,by_entry,slots,*,resolved=None):
    kind=opt['owner_kind'];field=opt['field'];replacement=opt['replacement']
    if resolved is None:
        ready,effective=preview_exports(db,kind,rows,slots)
    else:
        effective,incompatible=resolved
        ready=plain_exports(db,kind,rows)-incompatible
    warnings={};fallback=[];blocked=[]
    @lru_cache(maxsize=512)
    def check(form,gloss,extra,new):
        word=dict(json.loads(extra),form=form,gloss=gloss)
        return transform_word(word,{**word,field:new},rebase=False) if export_field(new,word.get(field+'_kind')) else None

    for row in long_tasks.steps(rows):
        rid=row['id']
        if rid not in ready:
            fallback.append(row)
            continue
        chosen=defaultdict(list)
        for change in by_entry[rid]:chosen[change['word']].append(change)
        issues=[]
        for pos,changes in chosen.items():
            word=effective.get((rid,pos))
            if word is None:
                form,gloss,extra=slots[rid,pos]
                old=form if field=='form' else gloss
            else:
                old=word[field]
            if old!=changes[0]['before']:
                fallback.append(row)
                break
            new=replaced_value(old,replacement,changes)
            if word is None:
                operation=check if len(form)+len(gloss)+len(extra)+len(new)<16384 else check.__wrapped__
                reason=operation(form,gloss,extra,new)
            else:
                reason=transform_word(word,{**word,field:new},rebase=False) if export_field(new,word.get(field+'_kind')) else None
            if reason is None:
                fallback.append(row)
                break
            if reason:issues.append(dict(id=rid,word=pos,title=row['title'],position=row['position'],reason=reason))
        else:
            if issues:warnings[rid]=issues

    analysis=corpus.WordAnalysisCache()
    for row in effective_rows(db,fallback,kind,preview=True):
        try:
            _,issues,_=edits_for(row,opt,by_entry[row['id']],analysis=analysis,preview=True)
            if issues:warnings[row['id']]=issues
        except ValueError as e:
            blocked.append(dict(id=row['id'],title=row['title'],position=row['position'],reason=str(e)))
    return [issue for row in rows for issue in warnings.get(row['id'],())],blocked


def check_export(body):
    # With balanced independent fields the exported call has fixed tuple
    # syntax. Special relation prefixes and unusual inputs keep the full check.
    function=body.get('function','pass')
    if (function in ('gloss','pass') and not body.get('reduplications')
            and export_field(body['ipa']) and export_field(body['translation'])
            and all(export_field(w['form'],w.get('form_kind')) and export_field(w['gloss'],w.get('gloss_kind')) for w in body['words'])):
        return
    checked,errors=corpus.parse(corpus.export_entry({**body,'function':function}),analyze_entries=False)
    if errors or len(checked)!=1 or any(checked[0][k]!=body[k] for k in ('ipa','translation')) or [(w['form'],w['gloss']) for w in checked[0]['words']]!=[(w['form'],w['gloss']) for w in body['words']]:
        raise ValueError('替换后存在未配对括号或无法安全导出的内容，请修改替换条件')


def edits_for(row,opt,selected,*,analysis=None,preview=False):
    old=record_sources.body(row,mutable=False);body=copy.deepcopy(old);by_cell={}
    for c in selected:by_cell.setdefault(c['word'],[]).append(c)
    conflicts=[];changed_words=[]
    for index,changes in by_cell.items():
        target=body if index is None else body['words'][index]
        target[opt['field']]=replaced_value(target[opt['field']],opt['replacement'],changes)
        if index is not None:
            reason=transform_word(old['words'][index],target)
            if reason:conflicts.append(dict(id=row['id'],word=index,title=row['title'],position=row['position'],reason=reason))
            changed_words.append(index)
    body['edited']=True
    if changed_words and (not preview or body.get('reduplications')):corpus.analyze(body,cache=analysis)
    if not preview and opt['owner_kind']=='independent' and changed_words:preserve_independent_refs(old,body,changed_words,{c['word'] for c in conflicts})
    check_export(body)
    return body,conflicts,changed_words

def document_matches(data,opt,regex,wanted=None):
    layer=opt['field']=='layer'
    changes=[]
    for row in long_tasks.steps(data):
        if layer:
            cells=[(c['word'],c['value'],dict(cell_id=c['id'],layer_id=c['layer_id'],layer_name=c['layer_name'])) for c in row['_replace_cells']]
        else:
            body=record_sources.body(row,mutable=False)
            cells=[(None,body[opt['field']],{})] if opt['field'] in ('ipa','translation') else [(i,w[opt['field']],{}) for i,w in enumerate(body['words'])]
        for index,value,extra in long_tasks.steps(cells):
            for m in long_tasks.steps(regex.finditer(value)):
                if m.group()==opt['replacement']:continue
                key=change_key(row['id'],extra.get('cell_id',index),m.start(),m.end(),layer)
                if wanted is not None and key not in wanted:continue
                changes.append(dict(key=key,id=row['id'],word=index,start=m.start(),end=m.end(),before=value,after=value[:m.start()]+opt['replacement']+value[m.end():],title=row['title'],position=row['position'],**extra))
                if len(changes)>10000:raise ValueError('超过 10000 处匹配，请缩小查找范围')
    return changes


def plan(db,b,lid,check=True,*,review=False):
    opt=settings(b);regex=pattern(opt)
    if opt['field'] in ('ipa','translation') and record_sources.native(db):
        return scalar_plan(db,opt,lid,regex,check,review=review)
    if opt['field'] in ('form','gloss') and record_sources.native(db):
        return word_plan(db,opt,lid,regex,check,review=review)
    data=records(db,opt,lid)
    definitions=layer_cells(db,data,opt,lid) if opt['field']=='layer' else None
    changes=document_matches(data,opt,regex)
    # Include current associations and layer content, not only entry revisions.
    digest=hashlib.sha256(json.dumps([lid,opt,data,definitions],ensure_ascii=False,sort_keys=True).encode())
    scope=" JOIN entries e ON e.id=u.entry_id JOIN texts t ON t.id=e.text_id WHERE t.language_id=? AND (?='' OR e.text_id=?)"
    queries=[
        'SELECT u.* FROM corpus_units u'+scope+' ORDER BY u.rowid',
        'SELECT l.*,x.revision,a.form_id,a.features FROM lexical_links l JOIN corpus_units u ON u.id=l.unit_id JOIN dictionary_targets x ON x.id=l.lexeme_id LEFT JOIN morphology_analyses a ON a.id=l.id'+scope+' ORDER BY l.rowid',
        "SELECT c.* FROM annotation_cells c JOIN entries_documents e ON e.id=c.record_id JOIN texts t ON t.id=e.text_id WHERE c.owner_kind='corpus' AND t.language_id=? AND (?='' OR e.text_id=?) ORDER BY c.rowid"]
    if opt['owner_kind']=='independent':
        queries=["SELECT c.* FROM annotation_cells c JOIN dictionary_examples_documents e ON e.id=c.record_id WHERE c.owner_kind='independent' AND e.language_id=? ORDER BY c.rowid",
            "SELECT x.id,x.revision,x.body FROM dictionary_targets x WHERE x.id IN (SELECT l.lexeme_id FROM independent_links l JOIN dictionary_examples_documents e ON e.id=l.example_id WHERE e.language_id=?) ORDER BY x.id"]
    for query in long_tasks.steps(queries):
        cursor=db.execute(query,(lid,) if opt['owner_kind']=='independent' else (lid,opt['text_id'],opt['text_id']))
        digest.update(b'\nTABLE\n')
        while rows:=cursor.fetchmany(1000):
            digest.update(json.dumps([tuple(r) for r in rows],ensure_ascii=False,separators=(',',':')).encode())
    by_entry=defaultdict(list)
    for c in long_tasks.steps(changes):by_entry[c['id']].append(c)
    conflicts=[];blocked=[]
    for row in long_tasks.steps(data if check and definitions is None else []):
        chosen=by_entry[row['id']]
        if not chosen:continue
        try:
            _,issues,_=edits_for(row,opt,chosen);conflicts.extend(issues)
        except ValueError as e:blocked.append(dict(id=row['id'],title=row['title'],position=row['position'],reason=str(e)))
    token=digest.hexdigest()
    return dict(token=token,changes=changes,conflicts=conflicts,blocked=blocked,records=len(data)),data,opt

def preview(db,b,lid):
    if not db.in_transaction:db.execute('BEGIN')
    review=b.get('reuse_preview') is True
    if review and b.get('field')=='layer' and replacement_preview.snapshot(db):
        opt=settings(b);regex=pattern(opt)
        scope,args,count=source_scope(db,opt,lid)
        predicate,values=literal_filter(db,'c.value',opt,regex)
        prepare_layer_owners(db)
        db.execute(f"""WITH hits AS MATERIALIZED (
           SELECT DISTINCT c.record_id FROM annotation_cells c JOIN annotation_layers l ON l.id=c.layer_id
           WHERE c.owner_kind=? AND l.language_id=? AND (?='' OR l.id=?) AND l.source<>'dictionary' AND {predicate}
        ), scope AS ({scope}) INSERT INTO replacement_owners
           SELECT e.id,e.position FROM hits h JOIN scope e ON e.id=h.record_id""",
           (opt['owner_kind'],lid,opt['layer_id'],opt['layer_id'],*values,*args))
        selected=f'SELECT e.* FROM replacement_owners k JOIN ({scope}) e ON e.id=k.id'
        p,rows=typed_layer_plan(db,opt,lid,regex,selected,args,count)
        if replacement_preview.remember(db,__name__,lid,p,rows,opt):return p
    p,rows,opt=plan(db,b,lid,review=review)
    if review and not p['token'].startswith(replacement_preview.REVIEWED):
        replacement_preview.remember(db,__name__,lid,p,rows,opt)
    return p


def prepare_layer_owners(db):
    db.execute('CREATE TEMP TABLE IF NOT EXISTS replacement_owners(id TEXT PRIMARY KEY,position INTEGER) WITHOUT ROWID')
    db.execute('DELETE FROM replacement_owners')


def typed_layer_plan(db,opt,lid,regex,scope,args,count,wanted=None):
    kind=opt['owner_kind']
    source=db.execute(f"""SELECT e.*,s.language_id FROM ({scope}) e CROSS JOIN sentence_text_rows s
                         ON s.kind=? AND s.owner_id=e.id ORDER BY e.text_order,e.position""",(*args,kind))
    rows=[dict(row) for row in source]
    layer_cells(db,rows,opt,lid,narrowed=True)
    changes=document_matches(rows,opt,regex,wanted)
    return dict(token=None,changes=changes,conflicts=[],blocked=[],records=count),rows


def remaining_preview(db,lid,previous,rows,opt,wanted,*,local=None):
    keys=set(wanted)
    prepare_layer_owners(db)
    db.executemany('INSERT INTO replacement_owners VALUES(?,?)',((row['id'],row['position']) for row in rows if local is None or row['id']==local))
    if opt['owner_kind']=='independent':
        scope="""SELECT e.id,e.revision,k.position,'独立例句库' AS title,0 AS text_order
                 FROM replacement_owners k CROSS JOIN dictionary_examples e ON e.id=k.id WHERE e.language_id=?"""
        args=(lid,)
    else:
        scope="""SELECT e.id,e.revision,e.text_id,e.position,t.title,t.rowid AS text_order
                 FROM replacement_owners k CROSS JOIN entries e ON e.id=k.id
                 JOIN texts t ON t.id=e.text_id WHERE t.language_id=? AND (?='' OR e.text_id=?)"""
        args=(lid,opt['text_id'],opt['text_id'])
    regex=pattern(opt)
    if opt['field']=='layer':
        p,current=typed_layer_plan(db,opt,lid,regex,scope,args,previous['records'],keys)
    else:
        prepare=scalar_plan if opt['field'] in ('ipa','translation') else word_plan
        p,current,opt=prepare(db,opt,lid,regex,True,(scope,args,previous['records']),keys)
    if local is not None:
        # The committed receipt proves that other owners' values, links and
        # export checks still agree with the reviewed snapshot.
        matches={match['key']:match for match in previous['changes'] if match['id']!=local}
        matches.update((match['key'],match) for match in p['changes'])
        p['changes']=[matches[key] for key in wanted if key in matches]
        for field in ('conflicts','blocked'):
            p[field].extend(item for item in previous[field] if item['id']!=local)
        touched={row['id']:row for row in current}
        ids={match['id'] for match in p['changes']}
        current=[touched.get(row['id'],row) for row in rows if row['id'] in ids]
    return p,current,opt


def write_fixed_corpus(db,pending,*,rebase_form=False):
    """Batch fixed-slot writes with the selected unit snapshots in memory."""
    eligible=[item for item in pending if item[3] and not item[2]]
    completed=set()
    for start in long_tasks.steps(range(0,len(eligible),100)):
        batch=eligible[start:start+100]
        positions={row['id']:set(indices) for row,_,_,indices in batch}
        states=lexicon.prepare_sync(db,list(positions),positions)
        writes=[]
        analyzed={}
        for row,body,_,indices in batch:
            rid=row['id']
            units,_=states[rid]
            words=[u for u in units if u['kind']=='word']
            sizes=defaultdict(int)
            for unit in units:
                if unit['kind']=='morpheme':sizes[unit['parent_id']]+=1
            if (len(words)!=len(body['words']) or
                    any(sizes[words[i]['id']]!=len(body['words'][i]['morphemes']) for i in indices)):
                continue
            gloss_inheritance.clear_metadata(body)
            previous=row['_stored_body']
            stored=dict(body,words=list(body['words']))
            gloss_inheritance.preserve_unchanged_words(stored['words'],previous['words'],edited=positions[rid])
            writes.append((rid,previous,stored,row['revision']))
            analyzed[rid]=body
        if not writes:
            continue
        sentence_rows.write_corpus_batch(db,writes)
        for rid,_,body,_ in long_tasks.steps(writes):
            lexicon.sync_entry(db,rid,preserve_complex=True,analyzed_body=analyzed[rid],preserve_slots=True,
                               word_positions=positions[rid],stored_body=body,source=body,unit_state=states[rid])
            completed.add(rid)
        if rebase_form:
            gloss_inheritance.rebase_form_slots(db,writes,positions,states)
    return completed


def apply(db,b,lid):
    if not db.in_transaction:db.execute('BEGIN IMMEDIATE')
    cached=replacement_preview.reuse(db,__name__,lid,b,settings(b))
    p,data,opt=cached if cached is not None else plan(db,b,lid,check=False)
    if p['token']!=b.get('token'):raise ValueError('文本、分析或词典关联已变化，请重新预览')
    keys=b.get('keys');known={c['key'] for c in p['changes']}
    if not isinstance(keys,list) or not keys or any(not isinstance(k,str) for k in keys) or len(set(keys))!=len(keys) or not set(keys)<=known:raise ValueError('请选择当前预览中的替换项')
    pending_keys=b.get('pending_keys',list(known))
    if not isinstance(pending_keys,list) or any(not isinstance(k,str) for k in pending_keys) or not set(pending_keys)<=known or not set(keys)<=set(pending_keys):raise ValueError('待替换列表已变化，请重新预览')
    keyset=set(keys);pending_keyset=set(pending_keys)
    chosen=[c for c in p['changes'] if c['key'] in keyset];pending=[];conflicts=[]
    by_entry=defaultdict(list);by_cell=defaultdict(list)
    for c in long_tasks.steps(chosen):
        by_entry[c['id']].append(c);by_cell[(c['id'],cell_identity(c))].append(c)
    scalar=opt['field'] in ('ipa','translation') and record_sources.native(db)
    selected_rows=(row for row in data if row['id'] in by_entry)
    if scalar:
        selected=sorted(selected_rows,key=lambda row:row['id'])
        pending.extend((row,body,[],[]) for row,body in scalar_edits(db,selected,opt,by_entry))
    elif opt['field'] in ('form','gloss') and record_sources.native(db):
        selected_rows=effective_rows(db,sorted(selected_rows,key=lambda row:row['id']),opt['owner_kind'])
    for row in long_tasks.steps(selected_rows if not scalar else ()):
        selected=by_entry[row['id']]
        if not selected:continue
        if opt['field']=='layer':
            pending.append((row,None,[],[]));continue
        body,issues,indices=edits_for(row,opt,selected);conflicts.extend(issues);pending.append((row,body,issues,indices))
    if replacement_preview.needs_confirmation(b,cached,p,conflicts):
        order={row['id']:i for i,row in enumerate(data)}
        conflicts.sort(key=lambda conflict:(order[conflict['id']],conflict['word']))
        return dict(needs_confirmation=True,conflicts=conflicts)
    replacement_preview.track_owner(db,b,opt['owner_kind'],by_entry)
    display_batch=scalar and record_sources.mode(db) in ('single','drop')
    fixed=set()
    if opt['field'] in ('form','gloss') and opt['owner_kind']=='corpus' and record_sources.mode(db) in ('single','drop'):
        fixed=write_fixed_corpus(db,pending,rebase_form=opt['field']=='form')
    if display_batch:
        for start in long_tasks.steps(range(0,len(pending),200)):
            sentence_rows.write_display_batch(db,opt['owner_kind'],
                [(row['id'],row['body'],body,row['revision']) for row,body,_,_ in pending[start:start+200]])
    for row,body,issues,indices in long_tasks.steps(() if display_batch else pending):
        if row['id'] in fixed:continue
        if opt['field']=='layer':
            for cell in row['_replace_cells']:
                changes=by_cell[(row['id'],cell['id'])]
                if not changes:continue
                value=cell['value']
                for c in sorted(changes,key=lambda c:c['start'],reverse=True):value=value[:c['start']]+opt['replacement']+value[c['end']:]
                if value:db.execute('UPDATE annotation_cells SET value=?,revision=revision+1 WHERE id=?',(value,cell['id']))
                else:db.execute('DELETE FROM annotation_cells WHERE id=?',(cell['id'],))
            continue
        if scalar:
            sentence_rows.write(db,opt['owner_kind'],row['id'],body,previous=row['body'])
            continue
        if opt['owner_kind']=='independent':
            # Literal replacement supplies a fixed-slot correspondence. Preserve
            # annotation IDs, language spans, media and dictionary targets. Old
            # segmentation snapshots continue to expose a real structural change.
            from independent_links import write_body
            write_body(db,row['id'],body)
            continue
        if not indices:
            sentence_rows.write(db,'corpus',row['id'],body)
            continue
        gloss_inheritance.clear_metadata(body)
        saved=sentence_rows.write(db,'corpus',row['id'],body,previous=row.get('_stored_body'))
        words=[dict(r) for r in db.execute("SELECT * FROM corpus_units WHERE entry_id=? AND kind='word' AND active=1 ORDER BY position",(row['id'],))]
        unsafe={c['word'] for c in issues};morph_ids={}
        for i in long_tasks.steps(indices):
            uid=words[i]['id']
            old_morphs=[dict(r) for r in db.execute("SELECT * FROM corpus_units WHERE parent_id=? AND active=1 ORDER BY position",(uid,))]
            if i not in unsafe and len(old_morphs)==len(body['words'][i]['morphemes']):morph_ids[uid]=[m['id'] for m in old_morphs]
            if i in unsafe:
                import link_review
                link_review.mark(db,'unit_id IN (SELECT id FROM corpus_units WHERE id=? OR parent_id=?)',(uid,uid),'批量替换改变了语素切分，请核对关联')
        lexicon.sync_entry(db,row['id'],[w['id'] for w in words],morph_ids,
                           preserve_complex=True,analyzed_body=body,stored_body=body,source=saved)
    remaining=[]
    for c in long_tasks.steps(p['changes']):
        if c['key'] not in pending_keyset or c['key'] in keyset:continue
        shift=sum(len(opt['replacement'])-(v['end']-v['start']) for v in by_cell[(c['id'],cell_identity(c))] if v['end']<=c['start'])
        remaining.append(change_key(c['id'],cell_identity(c),c['start']+shift,c['end']+shift,opt['field']=='layer'))
    result=dict(ok=True,sentences=len(pending),replacements=len(chosen),conflicts=len(conflicts),remaining_keys=remaining)
    replacement_preview.schedule(db,b,p,data,opt,pending_keyset-keyset,reviewed=cached is not None and pending_keyset==known)
    return result
