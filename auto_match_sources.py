"""SQLite inputs for automatic dictionary matching."""
from collections import defaultdict
from functools import lru_cache
from itertools import groupby,islice
import json

import corpus
import independent_annotations
import long_tasks
import record_sources


WORD_INPUTS = ('punctuation','punctuation_form','morph_groups','infix_confirmation','_legacy_tilde','analysis_form')
MATCH_FIELDS = {
    '': {'usages','senses','gloss','definition','gloss_addition','show_gloss_addition','features',
         'variants','paradigms','form_parts','entry_type','affix_position'},
    'usages': {'id','pos','senses','features'},
    'senses': {'id','short_gloss','gloss','definition','features','gloss_addition','show_gloss_addition'},
    'variants': {'id','form','features','form_parts'},
    'paradigms': {'title','usage_id','rows'},
    'rows': {'state','labels','realizations'},
    'realizations': {'form_id','meanings'},
    'meanings': {'id','base_sense_id','short_gloss','definition','gloss_mode','gloss_addition'},
    'form_parts': {'text','left','right'},
}
MATCH_SLOTS = sorted(set().union(*MATCH_FIELDS.values()))


def word_inputs(column):
    return 'json_array('+','.join(f"json_extract({column},'$.{name}')" for name in WORD_INPUTS)+')'


def override_inputs(db, image):
    if not independent_annotations.enabled(db):
        return word_inputs(image)

    def inputs(owner):
        if owner is None:return None
        from independent_links import override_images
        row=db.execute('SELECT * FROM independent_word_overrides WHERE id=?',(owner,)).fetchone()
        word=override_images(db,[row])[0]['word']
        return independent_annotations.encoded([word.get(key) for key in WORD_INPUTS])

    independent_annotations.register_projection(db,'independent_override_match_inputs',1,inputs)
    return 'independent_override_match_inputs(o.id)'


def analyze_word(form,gloss,inputs):
    extra={key:value for key,value in zip(WORD_INPUTS,json.loads(inputs)) if value is not None}
    if form.isalnum() and gloss.isalnum() and not extra.get('morph_groups'):
        # A plain unsegmented pair has one duplicate morpheme with the same label.
        # Its key still matters when the old project linked that representation.
        unit=dict(key='0:host',form=form,lookup_form=form,gloss=gloss)
        return dict(extra,form=form,gloss=gloss,analysis_form=form,punctuation=False,morphemes=[unit])
    word=dict(extra,form=form,gloss=gloss)
    return corpus.analyze(dict(ipa='',translation='',words=[word]))['words'][0]


def word_cache():
    cached=lru_cache(maxsize=512)(analyze_word)
    def read(form,gloss,inputs):
        operation=cached if len(form)+len(gloss)+len(inputs)<8192 else analyze_word
        return operation(form,gloss,inputs)
    return read


def corpus_scope(lid,text_id):
    query="""SELECT e.id,e.revision entry_revision,e.position sentence_position,t.id text_id,t.title,
        COALESCE(NULLIF(s.language_id,''),t.language_id) effective_language_id
        FROM texts t CROSS JOIN entries e ON e.text_id=t.id
        CROSS JOIN sentence_text_rows s ON s.kind='corpus' AND s.owner_id=e.id WHERE t.language_id=?"""
    return (query+' AND t.id=?',(lid,text_id)) if text_id else (query,(lid,))


def form_may_split(form):
    return not form.isalnum()


def independent_forms(db,lid,word):
    """Scan the form index once and analyze only values that can split."""
    db.create_function('auto_form_may_split',1,form_may_split,deterministic=True)
    inputs=word_inputs('w.extra')
    form,gloss,_,image=independent_annotations.override_sql(db)
    source='sentence_word_rows w'
    if db.execute("SELECT 1 FROM sqlite_master WHERE name='sentence_word_form'").fetchone():
        source+=' INDEXED BY sentence_word_form'
    homogeneous=(not db.execute('SELECT 1 FROM dictionary_examples WHERE language_id<>? LIMIT 1',(lid,)).fetchone() and
                 not db.execute("SELECT 1 FROM sentence_text_rows WHERE kind='independent' AND language_id NOT IN ('',?) LIMIT 1",(lid,)).fetchone())
    if homogeneous:
        ordinary=f"SELECT DISTINCT w.form,? language FROM {source} WHERE w.kind='independent'"
    else:
        ordinary="""SELECT w.form,COALESCE(NULLIF(s.language_id,''),e.language_id) language
          FROM dictionary_examples e CROSS JOIN sentence_text_rows s ON s.kind='independent' AND s.owner_id=e.id
          CROSS JOIN sentence_word_rows w ON w.kind='independent' AND w.owner_id=e.id WHERE e.language_id=? GROUP BY w.form,language"""
    cursor=db.execute(f"""WITH complex AS MATERIALIZED (
      SELECT DISTINCT w.form FROM sentence_word_rows w
      WHERE w.kind='independent' AND auto_form_may_split(w.form)
    ), ordinary AS ({ordinary}) SELECT form,language,NULL gloss,NULL inputs FROM ordinary
      UNION ALL SELECT DISTINCT w.form,COALESCE(NULLIF(s.language_id,''),e.language_id),w.gloss,{inputs}
      FROM complex c CROSS JOIN {source}
        ON w.kind='independent' AND w.form COLLATE NOCASE=c.form
      JOIN dictionary_examples e ON e.id=w.owner_id AND e.language_id=?
      JOIN sentence_text_rows s ON s.kind='independent' AND s.owner_id=e.id
      UNION ALL SELECT DISTINCT {form},COALESCE(NULLIF(s.language_id,''),e.language_id),
        {gloss},{override_inputs(db,image)}
      FROM independent_word_overrides o JOIN dictionary_examples e ON e.id=o.example_id AND e.language_id=?
      JOIN sentence_text_rows s ON s.kind='independent' AND s.owner_id=e.id""",(lid,lid,lid))
    for form,language,gloss,inputs in long_tasks.steps(cursor):
        yield language,form
        if gloss is None:continue
        w=word(form,gloss,inputs)
        yield language,w.get('analysis_form',form)
        for morph in w.get('morphemes',()):yield language,morph.get('lookup_form',morph['form'])


def independent_inputs(db):
    form,gloss,_,image=independent_annotations.override_sql(db)
    word=f"CASE WHEN o.position IS NULL THEN w.form ELSE {form} END"
    gloss=f"CASE WHEN o.position IS NULL THEN w.gloss ELSE {gloss} END"
    inputs=f"CASE WHEN o.position IS NULL THEN {word_inputs('w.extra')} ELSE {override_inputs(db,image)} END"
    return word,gloss,inputs


def independent_words(db,lid,*,forms=None):
    word,gloss,inputs=independent_inputs(db)
    fields=f"{word} form,{gloss} gloss,{inputs} inputs,COALESCE(NULLIF(s.language_id,''),e.language_id) effective_language_id"
    scope='SELECT id,language_id,revision,row_number() OVER (ORDER BY rowid) sentence_position FROM dictionary_examples WHERE language_id=?'
    where=''
    if forms is not None:
        db.create_function('auto_match_whole_form',2,forms,deterministic=True)
        where=f"""WHERE auto_match_whole_form(COALESCE(NULLIF(s.language_id,''),e.language_id),{word})
          OR {word} GLOB '*[-=+~<#>]*' OR instr({word},char(92))"""
    return db.execute(f"""WITH owners AS ({scope}) SELECT e.*,w.position,{fields} FROM owners e
      CROSS JOIN sentence_text_rows s ON s.kind='independent' AND s.owner_id=e.id
      CROSS JOIN sentence_word_rows w ON w.kind='independent' AND w.owner_id=e.id
      LEFT JOIN independent_word_overrides o ON o.example_id=e.id AND o.position=w.position {where}
      ORDER BY e.sentence_position,w.position""",(lid,))


def source_forms(db,lid,text_id,word,normalized):
    found={'corpus':defaultdict(set),'independent':defaultdict(set)}
    def add(kind,language,form):
        found[kind][language].add(normalized(form))

    if text_id!='@independent':
        scope,args=corpus_scope(lid,text_id)
        units=db.execute(f"""WITH scope AS ({scope})
             SELECT DISTINCT e.effective_language_id,u.form FROM scope e
             CROSS JOIN corpus_units u ON u.entry_id=e.id AND u.active=1""",args)
        for language,form in long_tasks.steps(units):
            add('corpus',language,form);add('corpus',language,corpus.clean(form))
        inputs=word_inputs('w.extra')
        for row in long_tasks.steps(db.execute(f"""WITH scope AS ({scope})
             SELECT DISTINCT e.effective_language_id,w.form,w.gloss,{inputs} inputs FROM scope e
             CROSS JOIN sentence_word_rows w ON w.kind='corpus' AND w.owner_id=e.id
             WHERE instr(w.form,'<') OR instr(w.form,'#') OR instr(w.gloss,'#')""",args)):
            for morph in word(row['form'],row['gloss'],row['inputs']).get('morphemes',()):
                add('corpus',row['effective_language_id'],morph.get('lookup_form',morph['form']))
    if text_id in ('','@independent'):
        for language,form in independent_forms(db,lid,word):
            add('independent',language,form);add('independent',language,corpus.clean(form))
    return found


def matching_bodies(db,targets):
    """Read only paths used by matching; retain the tree's stable order and keys."""
    import dictionary_rows
    records={}
    fields=','.join('?' for _ in MATCH_SLOTS)
    for kind in ('lexeme','morpheme'):
        ids=[r['id'] for r in targets if r['target_kind']==kind]
        if not ids:continue
        marks=','.join('?' for _ in ids)
        cursor=db.execute(f"""SELECT target_id,node,parent,slot,value_type,value FROM dictionary_value_rows
          WHERE target_kind=? AND target_id IN ({marks}) AND (node=0 OR typeof(slot)='integer' OR slot IN ({fields}))
          ORDER BY target_id,node""",(kind,*ids,*MATCH_SLOTS))
        for rid,nodes in groupby(cursor,key=lambda row:row['target_id']):
            paths={};selected=[]
            for row in nodes:
                parent,slot=row['parent'],row['slot']
                if parent is None:path=''
                elif parent not in paths:continue
                elif isinstance(slot,int):path=paths[parent]
                elif slot in MATCH_FIELDS.get(paths[parent],()):path=slot
                else:continue
                paths[row['node']]=path;selected.append(row)
            records[rid]=dictionary_rows._decode(selected)
    return records


def catalog(db,source_keys,normalized,*,narrow=True):
    import dictionary_rows
    import homonyms

    if source_keys is None:
        cursor=db.execute('SELECT * FROM dictionary_targets ORDER BY id')
        while batch:=cursor.fetchmany(200):
            items=[{**dict(row),'body':json.loads(row['body'])} for row in batch]
            homonyms.decorate_many(db,[row for row in items if row['target_kind']=='lexeme'])
            yield from items
        return
    forms=defaultdict(set)
    for scope in source_keys.values():
        for language,keys in scope.items():forms[language].update(keys)
    if not forms:
        return
    def eligible(language,form):
        return bool(language in forms and normalized(form) in forms[language])
    db.create_function('auto_match_form',2,eligible,deterministic=True)
    variants=dictionary_rows.lookup_values(db)
    select=f"""WITH targets AS MATERIALIZED (
      SELECT id,language_id,headword,'lexeme' target_kind,revision,homonym_number FROM lexemes
      UNION ALL SELECT id,language_id,form,'morpheme',revision,number FROM morphemes
    ), values_to_check AS MATERIALIZED (
      SELECT v.target_id,v.target_kind,v.node,v.slot,v.value FROM {variants}
      WHERE {dictionary_rows.LOOKUP_VALUES} AND v.slot IN ('form','form_parts')
    ), selected AS (
      SELECT id FROM targets WHERE auto_match_form(language_id,headword) OR instr(headword,'…')
      UNION SELECT x.id FROM values_to_check v JOIN targets x ON x.id=v.target_id AND x.target_kind=v.target_kind
       WHERE (v.slot='form' AND typeof(v.value)='text' AND (auto_match_form(x.language_id,v.value) OR instr(v.value,'…')))
          OR (v.slot='form_parts' AND EXISTS (SELECT 1 FROM dictionary_value_rows p
              WHERE p.target_kind=v.target_kind AND p.target_id=v.target_id AND p.node=v.node+1 AND p.parent=v.node))
    ) """
    details="""SELECT t.id,t.language_id,t.headword,t.target_kind,t.revision,
      CASE WHEN t.target_kind='lexeme' OR EXISTS(SELECT 1 FROM morphemes p
       WHERE p.language_id=t.language_id AND p.form=t.headword AND p.id<>t.id) THEN t.homonym_number END homonym_number
      FROM selected s JOIN targets t ON t.id=s.id
      AND (t.target_kind='lexeme' OR NOT EXISTS(SELECT 1 FROM lexemes x WHERE x.id=t.id)) ORDER BY t.id"""
    cursor=db.execute(select+(details if narrow else 'SELECT id FROM selected ORDER BY id'))
    while batch:=cursor.fetchmany(400):
        records=matching_bodies(db,batch) if narrow else {}
        if len(records)!=len(batch):
            # Older projects with partially prepared rows keep the normal reader.
            fallback=dictionary_rows.targets(db,[row['id'] for row in batch],prepare=False)
            homonyms.decorate_many(db,[row for row in fallback.values() if row['target_kind']=='lexeme'])
            yield from (fallback[row['id']] for row in batch if row['id'] in fallback)
            continue
        items=[]
        for row in batch:
            body=records[row['id']];body['homonym_number']=row['homonym_number']
            if row['target_kind']=='morpheme':
                # The common adapter needs no writing display data for matching.
                body['orthographies']=[]
                dictionary_rows._morpheme_body(row,body,{})
            items.append(dict(row,body=body))
        homonyms.decorate_many(db,[row for row in items if row['target_kind']=='lexeme'])
        yield from items


def corpus_batches(db,lid,text_id,word,need_bodies,*,owners=None):
    import sentence_rows
    if owners is None:
        scope,args=corpus_scope(lid,text_id)
        cursor=db.execute(scope+' ORDER BY t.id,e.position',args)
    else:
        cursor=db.execute(f"""SELECT e.id,COALESCE(NULLIF(s.language_id,''),t.language_id) effective_language_id
          FROM entries e JOIN texts t ON t.id=e.text_id
          JOIN sentence_text_rows s ON s.kind='corpus' AND s.owner_id=e.id
          WHERE e.id IN ({','.join('?' for _ in owners)})""",owners)
    while batch:=cursor.fetchmany(200):
        ids=[entry['id'] for entry in batch]
        bodies=sentence_rows.read(db,'corpus',ids) if need_bodies else {}
        grouped=defaultdict(list);semantic={}
        inputs=word_inputs('w.extra')
        link='l.id' if owners is None else 'NULL'
        join='LEFT JOIN lexical_links l ON l.unit_id=u.id' if owners is None else ''
        for row in db.execute(f"""SELECT u.id,u.entry_id,u.revision,u.kind,u.parent_id,u.position,u.form,u.gloss,{link} link_id,
          json_extract(w.extra,'$.punctuation') punctuation,
          CASE WHEN instr(w.form,'<') OR instr(w.form,'#') OR instr(w.gloss,'#') THEN w.form END raw_form,
          w.gloss raw_gloss,CASE WHEN instr(w.form,'<') OR instr(w.form,'#') OR instr(w.gloss,'#') THEN {inputs} END inputs
          FROM corpus_units u {join}
          LEFT JOIN sentence_word_rows w ON u.kind='word' AND w.kind='corpus' AND w.owner_id=u.entry_id AND w.position=u.position
          WHERE u.active=1 AND u.entry_id IN ({','.join('?' for _ in ids)})
          ORDER BY u.entry_id,u.kind DESC,u.position,u.id""",ids):
            unit={k:row[k] for k in ('id','entry_id','revision','kind','parent_id','position','form','gloss','link_id','punctuation')}
            grouped[row['entry_id']].append(unit)
            if row['raw_form'] is not None:
                semantic[row['id']]=word(row['raw_form'],row['raw_gloss'],row['inputs']).get('morphemes',[])
        for entry in long_tasks.steps(batch):
            yield entry,bodies.get(entry['id']),grouped[entry['id']],semantic


def corpus_slots(units,semantic,body=None):
    """The duplicate of an unsegmented word shares its existing association."""
    def labels(unit):
        if unit['kind']=='word':
            return corpus.clean(unit['form']),unit['gloss'],unit['form']
        morphs=semantic.get(unit['parent_id'],())
        live=morphs[unit['position']] if unit['kind']=='morpheme' and unit['position']<len(morphs) else {}
        return (live.get('lookup_form',unit['form']),live.get('display_gloss',unit['gloss']),
                live.get('display_form',unit['form']))

    parents={u['id']:labels(u) for u in units if u['kind']=='word'}
    meanings=[parents[u['id']] if u['kind']=='word' else labels(u) for u in units]
    duplicates={u['parent_id']:u for u,meaning in zip(units,meanings) if u['kind']=='morpheme'
                and u['parent_id'] in parents and meaning[:2]==parents[u['parent_id']][:2]}
    for unit,meaning in zip(units,meanings):
        if unit['kind']=='word':
            punctuation=(body['words'][unit['position']].get('punctuation') if body is not None
                         else unit['punctuation'])
            if punctuation:continue
        elif unit['parent_id'] in duplicates:continue
        yield unit,duplicates.get(unit['id']),meaning


def independent_slots(word):
    if word.get('punctuation') or corpus.boundary_count(word['form']):return
    lookup_form=word.get('analysis_form',word['form'])
    whole=dict(key='@word',form=word['form'],lookup_form=lookup_form,gloss=word['gloss'],fragments=[])
    aliases=[];units=[]
    if not word.get('infix_ambiguous') and not word.get('group_reviews'):
        for unit in word.get('morphemes',()):
            pair=(unit.get('lookup_form',unit['form']),unit.get('display_gloss',unit['gloss']))
            if pair==(lookup_form,word['gloss']):aliases.append(unit['key'])
            else:units.append(unit)
    yield whole,aliases
    for unit in units:yield unit,()


def independent_bodies(db,lid):
    import independent_links
    import sentence_rows
    cursor=db.execute('SELECT id,revision FROM dictionary_examples WHERE language_id=? ORDER BY rowid',(lid,))
    while batch:=list(islice(cursor,200)):
        bodies=sentence_rows.read(db,'independent',[row['id'] for row in batch])
        independent_links.source_bodies(db,bodies)
        for row in batch:
            yield row,bodies[row['id']]


def independent_batches(db,lid,word,forms=None):
    groups=(list(rows) for _,rows in groupby(independent_words(db,lid,forms=forms),key=lambda row:row['id']))
    while batch:=list(islice(groups,200)):
        refs=defaultdict(set)
        ids=[rows[0]['id'] for rows in batch]
        for row in db.execute(f"""SELECT example_id,word_position,unit_key FROM independent_links
          WHERE example_id IN ({','.join('?' for _ in ids)}) AND word_position IS NOT NULL
          AND NOT COALESCE({independent_annotations.detached_sql(db)},0)""",ids):
            refs[row['example_id']].add((row['word_position'],row['unit_key']))
        for rows in long_tasks.steps(batch):
            for row in rows:
                yield row,word(row['form'],row['gloss'],row['inputs']),refs[row['id']]
