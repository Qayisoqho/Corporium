"""One read interface for words and morphemes; identities stay in their own tables.

The legacy link column is called lexeme_id. It now denotes either target kind.
No shadow word or duplicated identity is created for a morpheme.
"""
import json

TYPES=('unspecified','root','stem','affix','clitic','connector','multipart','infix','circumfix')
FUNCTIONS=('unspecified','inflection','derivation','both')
POSITIONS=('unspecified','prefix','suffix','infix','circumfix')

# Identity-only joins use a narrow interface independent of the display view's
# derived JSON. Keep UNION ALL and language semantics.
IDENTITIES='(SELECT id,language_id FROM lexemes UNION ALL SELECT id,language_id FROM morphemes)'

def initialize(db):
    db.execute('DROP VIEW IF EXISTS dictionary_targets')
    db.execute('''CREATE VIEW dictionary_targets AS
    SELECT id,language_id,headword,body,revision,rowid rowid,'lexeme' target_kind FROM lexemes
    UNION ALL
    SELECT m.id,m.language_id,m.form,
    json_set(m.body,
      '$.homonym_number',CASE WHEN (SELECT count(*) FROM morphemes p WHERE p.language_id=m.language_id AND p.form=m.form)>1 THEN m.number ELSE NULL END,
      '$.usages',json(COALESCE(json_extract(m.body,'$.usages'),json_array(json_object(
        'id','@morpheme','pos','','features',json('[]'),'tags',json('[]'),'senses',
        json_insert(COALESCE((SELECT json_group_array(json_object('id',json_extract(s.value,'$.id'),
          'short_gloss',COALESCE(json_extract(s.value,'$.gloss'),''),
          'gloss_addition',COALESCE(json_extract(s.value,'$.gloss_addition'),''),
          'show_gloss_addition',json(COALESCE(s.value->'$.show_gloss_addition','true')),
          'definition',COALESCE(json_extract(s.value,'$.definition'),''),
          'features',json(COALESCE(json_extract(s.value,'$.features'),'[]')),
          'tags',json(COALESCE(json_extract(s.value,'$.tags'),'[]')))) FROM json_each(m.body,'$.senses') s),'[]'),
          '$[#]',json_object('id','@main','short_gloss',COALESCE(json_extract(m.body,'$.gloss'),''),
          'gloss_addition',COALESCE(json_extract(m.body,'$.gloss_addition'),''),
          'show_gloss_addition',json(COALESCE(m.body->'$.show_gloss_addition','true')),
          'definition',COALESCE(json_extract(m.body,'$.definition'),''),'features',json('[]'),'tags',json('[]'))))))),
      '$.orthographies',json(COALESCE(json_extract(m.body,'$.orthographies'),
        (SELECT json_group_array(json_object('id','@writing:'||w.key,'type_id',json_extract(w.value,'$.type_id'),
          'text',json_extract(w.value,'$.text'),'label',COALESCE(t.name,''),'font',COALESCE(t.font,'Junicode')))
        FROM json_each(m.body,'$.writings') w LEFT JOIN writing_types t ON t.id=json_extract(w.value,'$.type_id')),'[]')),
      '$.word_structure',json(COALESCE(json_extract(m.body,'$.word_structure'),'{}')),
      '$.variants',json(COALESCE(json_extract(m.body,'$.variants'),'[]'))),
    m.revision,m.rowid,'morpheme' FROM morphemes m''')

def common(db,mid):
    row=db.execute('SELECT body FROM dictionary_targets WHERE id=?',(mid,)).fetchone()
    if not row:raise ValueError('词典条目不存在')
    return json.loads(row[0])

def normalize(db,lid,data,old=None):
    """Native compact fields plus stable meanings used by both association paths."""
    import lexicon,morphology,sense_gloss
    data=dict(data)
    sense_gloss.normalize(data,data)
    for field,choices in [('entry_type',TYPES),('affix_function',FUNCTIONS),('affix_position',POSITIONS)]:
        data[field]=morphology.choice(data.get(field,'unspecified'),choices,{'entry_type':'语素类型','affix_function':'构词功能','affix_position':'词缀位置'}[field])
    data['definition']=lexicon.text(data.get('definition',''))
    data['tags']=lexicon.tags(data.get('tags',[]))
    data['features']=morphology.check_features(db,lid,data.get('features',[]))
    # Typed spellings inherited from a converted word follow the native writing
    # editor. Unclassified legacy spellings retain their label, font and identity.
    if 'orthographies' in data:
        spellings={w['type_id']:w['text'] for w in data.get('writings',[])}
        data['orthographies']=[dict(o,text=spellings[o['type_id']]) if o.get('type_id') else o for o in data['orthographies'] if not o.get('type_id') or o['type_id'] in spellings]
        used={o.get('type_id') for o in data['orthographies']}
        for type_id,value in spellings.items():
            if type_id in used:continue
            row=db.execute('SELECT * FROM writing_types WHERE id=? AND language_id=?',(type_id,lid)).fetchone()
            if not row:raise ValueError('书写类型不属于当前语言')
            import uuid
            data['orthographies'].append(dict(id=str(uuid.uuid4()),type_id=type_id,label=row['name'],font=row['font'],text=value))
    for sense in data.get('senses',[]):
        sense_gloss.normalize(sense,sense)
        sense['tags']=lexicon.tags(sense.get('tags',[]))
        sense['features']=morphology.check_features(db,lid,sense.get('features',[]))
    # Converted words retain their full usage hierarchy. Native fields edit only
    # the explicitly identified compact usage; removing linked meanings is checked.
    usages=data.setdefault('usages',[])
    if data.get('primary_sense_id'):
        primary=data['primary_sense_id'];extra={s['id']:s for s in data.get('senses',[])};found=False
        for usage in usages:
            kept=[]
            for sense in usage.get('senses',[]):
                if sense['id']==primary:
                    sense.update(short_gloss=data.get('gloss',''),definition=data['definition'],**{k:data[k] for k in ('gloss_addition','show_gloss_addition') if k in data});found=True;kept.append(sense)
                elif sense['id'] in extra:
                    value=extra.pop(sense['id']);kept.append({**sense,**{k:v for k,v in value.items() if k!='gloss'},'short_gloss':value.get('gloss','')})
            usage['senses']=kept
        if not found:raise ValueError('转换记录的主要意义已不存在')
        if usages:usages[0]['senses'].extend(dict(s,short_gloss=s.get('gloss','')) for s in extra.values())
        return data
    # Native meanings are projected by the read view, rather than duplicated in
    # stored JSON. Converted and merged hierarchies above keep original IDs.
    data.pop('usages',None)
    return data

def write_body(db,row,body):
    table='morphemes' if row['target_kind']=='morpheme' else 'lexemes'
    db.execute('UPDATE '+table+' SET body=?,revision=revision+1 WHERE id=?',(json.dumps(body,ensure_ascii=False),row['id']))

def references(db,mid):
    return dict(corpus=db.execute('SELECT count(*) FROM lexical_links WHERE lexeme_id=?',(mid,)).fetchone()[0],
        independent=db.execute("SELECT count(*) FROM dictionary_examples e WHERE EXISTS(SELECT 1 FROM json_each(e.body,'$.targets') t WHERE json_extract(t.value,'$.lexeme_id')=?)",(mid,)).fetchone()[0])

def reference_state(db,mid,lid='all'):
    row=db.execute('SELECT id,language_id,target_kind,revision FROM dictionary_targets WHERE id=?',(mid,)).fetchone()
    if not row:raise ValueError('词条不存在，请刷新词典')
    if lid!='all' and row['language_id']!=lid:raise ValueError('词条或语言范围已变化，请重新打开')
    refs=references(db,mid)
    components=db.execute('SELECT count(*) FROM morpheme_components WHERE morpheme_id=?',(mid,)).fetchone()[0] if row['target_kind']=='morpheme' else 0
    return dict(id=mid,language_id=row['language_id'],target_kind=row['target_kind'],revision=row['revision'],references=refs,components=components,can_delete=not components and not any(refs.values()))
