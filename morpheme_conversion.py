"""Explicit, journalled conversion without changing the sentence text or identity."""
import hashlib
import json
import uuid
import dictionary_targets

def encoded(value):return json.dumps(value,ensure_ascii=False,sort_keys=True)

def preview(db,lid,b):
    import lexicon,morpheme_registry
    source=lexicon.get_lexeme(db,b.get('id'))
    if source['target_kind']!='lexeme' or source['language_id']!=lid:raise ValueError('请选择当前语言的词条')
    morpheme_registry.check_revision(source,b.get('revision'))
    peers=[morpheme_registry.get(db,r[0]) for r in db.execute('SELECT id FROM morphemes WHERE language_id=? AND form=? ORDER BY number',(lid,source['headword']))]
    refs=dictionary_targets.references(db,source['id'])
    refs['components']=db.execute('SELECT count(*) FROM morpheme_components WHERE lexeme_id=?',(source['id'],)).fetchone()[0]
    # Data version catches changes to references and target metadata between preview
    # and apply, including writes from other windows, without mutating the database.
    fingerprint=[source,peers,refs,[tuple(r) for r in db.execute('SELECT id,revision FROM lexical_links ORDER BY id')],
        [tuple(r) for r in db.execute('SELECT id,revision FROM dictionary_examples ORDER BY id')],
        [tuple(r) for r in db.execute('SELECT id,revision FROM object_media ORDER BY id')]]
    token=hashlib.sha256(encoded(fingerprint).encode()).hexdigest()
    return dict(source=source,peers=peers,references=refs,token=token)

def converted(source):
    body=json.loads(encoded(source['body']));senses=[s for u in body.get('usages',[]) for s in u.get('senses',[])]
    main=senses[0] if senses else {}
    if main:body['primary_sense_id']=main['id']
    body['gloss']=main.get('short_gloss','');body['definition']=main.get('definition','')
    body.update({k:main[k] for k in ('gloss_addition','show_gloss_addition') if k in main})
    body['senses']=[dict(s,gloss=s.get('short_gloss','')) for s in senses[1:]]
    body['readings']=body.get('readings',[])
    body['writings']=[dict(type_id=o['type_id'],text=o['text']) for o in body.get('orthographies',[]) if o.get('type_id')]
    kind=body.get('entry_type','unspecified')
    body['affix_function']=body.get('affix_function','unspecified');body['affix_position']=body.get('affix_position','unspecified')
    if kind in ('infix','circumfix'):body['entry_type']='affix';body['affix_position']=kind
    elif kind not in dictionary_targets.TYPES:body['entry_type']='unspecified'
    body['converted_from']=dict(id=source['id'],headword=source['headword'])
    return body

def convert(db,lid,b):
    import morpheme_registry
    plan=preview(db,lid,b)
    if plan['token']!=b.get('token'):raise ValueError('词条或关联已变化，请重新预览转换')
    choice=b.get('target_id')
    if not choice:raise ValueError('请选择新建独立语素或并入已有语素')
    if choice!='@new' and choice not in {r['id'] for r in plan['peers']}:raise ValueError('请重新选择同形语素')
    source=plan['source'];body=converted(source)
    for key in ('entry_type','affix_function','affix_position'):
        if key in b:body[key]=b[key]
    body=dictionary_targets.normalize(db,lid,body)
    mid=source['id'];number=db.execute('SELECT COALESCE(MAX(number),0)+1 FROM morphemes WHERE language_id=? AND form=?',(lid,source['headword'])).fetchone()[0]
    db.execute('INSERT INTO morphemes VALUES(?,?,?,?,?,?)',(mid,lid,source['headword'],number,encoded(body),source['revision']+1))
    db.execute('DELETE FROM lexemes WHERE id=?',(mid,))
    db.execute("UPDATE object_media SET kind='morpheme',revision=revision+1 WHERE kind='lexeme' AND record_id=?",(mid,))
    _synonyms(db,mid,mid,{s['id']:s['id'] for u in source['body'].get('usages',[]) for s in u.get('senses',[])},'lexeme')
    if choice!='@new':
        return merge(db,lid,morpheme_registry.get(db,mid),morpheme_registry.get(db,choice))
    return morpheme_registry.get(db,mid)

def _synonyms(db,old,new,partmap,kind='morpheme'):
    import synonyms
    for row in list(db.execute('SELECT * FROM synonym_links')):
        ends=json.loads(row['body']);changed=False
        for ref in ends:
            if ref['kind']==kind and ref['id']==old:
                ref.update(kind='morpheme',id=new,sense=partmap.get(ref['sense'],ref['sense']));changed=True
        if changed:
            ends.sort(key=synonyms.key);a,c=map(synonyms.key,ends)
            if a==c:db.execute('DELETE FROM synonym_links WHERE id=?',(row['id'],));continue
            peer=db.execute('SELECT id FROM synonym_links WHERE language_id=? AND a=? AND b=? AND id!=?',(row['language_id'],a,c,row['id'])).fetchone()
            if peer:db.execute('DELETE FROM synonym_links WHERE id=?',(row['id'],))
            else:db.execute('UPDATE synonym_links SET a=?,b=?,body=? WHERE id=?',(a,c,encoded(ends),row['id']))

def merge(db,lid,source,target):
    """Keep distinct meanings and forms; never infer their equivalence."""
    import morpheme_registry
    sid=source['id'];tid=target['id'];sb=dictionary_targets.common(db,sid);tb=dictionary_targets.common(db,tid)
    target['body'].setdefault('merged_records',[]).append({k:source[k] for k in ('id','form','number','body')})
    # Remap every subordinate identity before copying, even if spelling is equal.
    mapping={}
    def identities(value):
        if isinstance(value,dict):
            if isinstance(value.get('id'),str):yield value['id']
            for key,child in value.items():
                if key!='merged_records':yield from identities(child)
        elif isinstance(value,list):
            for child in value:yield from identities(child)
    used=set(identities(tb))
    def remap_rows(rows):
        result=[]
        for row in rows:
            row=dict(row)
            if 'id' in row:
                original=row['id'];row['id']=mapping.setdefault(original,str(uuid.uuid4()) if original in used else original);used.add(row['id'])
            if 'senses' in row:row['senses']=remap_rows(row['senses'])
            if 'components' in row:row['components']=remap_rows(row['components'])
            if 'parts' in row:row['parts']=remap_rows(row['parts'])
            for field in ('rows','realizations','meanings'):
                if field in row:row[field]=remap_rows(row[field])
            result.append(row)
        return result
    for field in ('usages','variants','orthographies'):
        tb.setdefault(field,[]).extend(remap_rows(sb.get(field,[])))
    copies=remap_rows(sb.get('paradigms',[]))
    if copies:
        _remap_ref(copies,mapping,sid,tid)
        tb.setdefault('paradigms',[]).extend(copies)
    for field in ('analyses','memberships'):
        copies=remap_rows(sb.get('word_structure',{}).get(field,[]))
        _remap_ref(copies,mapping,sid,tid)
        tb.setdefault('word_structure',{}).setdefault(field,[]).extend(copies)
    target['body'].update({k:tb[k] for k in ('usages','variants','orthographies','word_structure')})
    if tb.get('paradigms'):target['body']['paradigms']=tb['paradigms']
    # Native senses expose copied meanings in the compact editor and synonym API.
    target['body'].setdefault('senses',[]).extend(dict(s,id=mapping[s['id']],gloss=s.get('short_gloss','')) for u in sb.get('usages',[]) for s in u.get('senses',[]))
    target['body']['primary_sense_id']=target['body'].get('primary_sense_id','@main')
    for field in ('writings','readings','tags','features','semantic_classes'):
        dest=target['body'].setdefault(field,[])
        for value in source['body'].get(field,[]):
            if value not in dest:dest.append(value)
    for row in list(db.execute('SELECT * FROM lexical_links WHERE lexeme_id=?',(sid,))):
        db.execute('UPDATE lexical_links SET lexeme_id=?,usage_id=?,sense_id=?,revision=revision+1 WHERE id=?',(tid,mapping.get(row['usage_id'],row['usage_id']),mapping.get(row['sense_id'],row['sense_id']),row['id']))
        db.execute('UPDATE morphology_analyses SET form_id=? WHERE id=?',(mapping.get((db.execute('SELECT form_id FROM morphology_analyses WHERE id=?',(row['id'],)).fetchone() or [None])[0]),row['id']))
        ref=db.execute('SELECT body FROM component_links WHERE id=?',(row['id'],)).fetchone()
        if ref:
            value=json.loads(ref[0]);_remap_ref(value,mapping,sid,tid)
            db.execute('UPDATE component_links SET body=? WHERE id=?',(encoded(value),row['id']))
    for row in list(db.execute('SELECT * FROM dictionary_examples')):
        value=json.loads(row['body']);changed=False
        for ref in value.get('targets',[]):
            if ref['lexeme_id']==sid:
                ref['lexeme_id']=tid
                for key in ('usage_id','sense_id','form_id'):ref[key]=mapping.get(ref.get(key),ref.get(key))
                if ref.get('component_ref'):_remap_ref(ref['component_ref'],mapping,sid,tid)
                changed=True
        if changed:db.execute('UPDATE dictionary_examples SET body=?,revision=revision+1 WHERE id=?',(encoded(value),row['id']))
    # Both links TO this morpheme and analyses OWNED by it survive.
    for row in list(db.execute('SELECT id,body FROM morpheme_components WHERE morpheme_id=?',(sid,))):
        value=json.loads(row['body'])
        if value.get('form_id'):value['form_id']=mapping[value['form_id']]
        db.execute('UPDATE morpheme_components SET morpheme_id=?,body=?,revision=revision+1 WHERE id=?',(tid,encoded(value),row['id']))
    for row in list(db.execute('SELECT * FROM morpheme_components WHERE lexeme_id=?',(sid,))):
        value=json.loads(row['body']);selected_form=value.pop('form_id',None);_remap_ref(value,mapping,sid,tid)
        if selected_form:value['form_id']=selected_form
        db.execute('UPDATE morpheme_components SET lexeme_id=?,analysis_id=?,component_id=?,body=?,revision=revision+1 WHERE id=?',(tid,mapping.get(row['analysis_id'],row['analysis_id']),mapping.get(row['component_id'],row['component_id']),encoded(value),row['id']))
    # Retarget base relations and explicit component dictionary references.
    for row in list(db.execute('SELECT * FROM dictionary_targets')):
        if row['id'] in (sid,tid):continue
        value=json.loads(row['body']);changed=False
        relation=value.get('relation')
        if relation and relation['base_id']==sid:relation['base_id']=tid;changed=True
        for a in value.get('word_structure',{}).get('analyses',[]):
            for c in a.get('components',[]):
                if c.get('lexeme_id')==sid:
                    c['lexeme_id']=tid
                    for field in ('usage_id','sense_id','form_id'):c[field]=mapping.get(c.get(field),c.get(field))
                    changed=True
        if changed:dictionary_targets.write_body(db,row,value)
    _synonyms(db,sid,tid,mapping)
    offset=db.execute("SELECT COALESCE(MAX(position),-1)+1 FROM object_media WHERE kind='morpheme' AND record_id=?",(tid,)).fetchone()[0]
    for i,row in enumerate(list(db.execute("SELECT * FROM object_media WHERE kind='morpheme' AND record_id=? ORDER BY position,id",(sid,)))):
        value=json.loads(row['body'])
        if value.get('target_id'):value['target_id']=mapping[value['target_id']]
        db.execute('UPDATE object_media SET record_id=?,position=?,body=?,revision=revision+1 WHERE id=?',(tid,offset+i,encoded(value),row['id']))
    db.execute('UPDATE morphemes SET body=?,revision=revision+1 WHERE id=?',(encoded(target['body']),tid))
    # Merging relocates the same meanings, rather than choosing a different
    # meaning for each example. Retain its inheritance pattern or local override
    # before the normal reconciliation observes the retargeted associations.
    import gloss_inheritance
    saved=dict(db.execute('SELECT * FROM morphemes WHERE id=?',(tid,)).fetchone())
    gloss_inheritance.sync_meanings(db,{('morphemes',tid):(None,saved)})
    for meaning in db.execute('SELECT * FROM gloss_meanings WHERE target_id=?',(sid,)).fetchall():
        new=gloss_inheritance.meaning_id(tid,mapping.get(meaning['usage_id'],meaning['usage_id']),mapping.get(meaning['sense_id'],meaning['sense_id']))
        if not db.execute('SELECT 1 FROM gloss_meanings WHERE id=?',(new,)).fetchone():raise ValueError('归并后的意义引用不完整，请重新核对')
        db.execute('UPDATE gloss_bindings SET meaning_id=?,revision=revision+1,source_binding_revision=NULL,source_meaning_revision=NULL WHERE meaning_id=?',(new,meaning['id']))
    db.execute('DELETE FROM morphemes WHERE id=?',(sid,))
    return morpheme_registry.get(db,tid)

def _remap_ref(value,mapping,old,new):
    if isinstance(value,dict):
        for key,item in list(value.items()):
            if key in ('analysis_id','component_id','id','usage_id','sense_id','form_id','variant_id','base_sense_id') and isinstance(item,str):value[key]=mapping.get(item,item)
            elif key=='lexeme_id' and item==old:value[key]=new
            else:_remap_ref(item,mapping,old,new)
    elif isinstance(value,list):
        for item in value:_remap_ref(item,mapping,old,new)
