"""Configurable word layers, attached to stable word identities."""
import json
import copy
import uuid
import font_catalog
import gloss_inheritance

TABLES=('annotation_layers','annotation_cells')
def initialize(db):
    db.executescript('''CREATE TABLE IF NOT EXISTS annotation_layers(id TEXT PRIMARY KEY,language_id TEXT NOT NULL,name TEXT NOT NULL,font TEXT NOT NULL,style TEXT NOT NULL DEFAULT 'normal',position INTEGER NOT NULL DEFAULT 0,visible INTEGER NOT NULL DEFAULT 1,searchable INTEGER NOT NULL DEFAULT 1,revision INTEGER NOT NULL DEFAULT 1);
    CREATE TABLE IF NOT EXISTS annotation_cells(id TEXT PRIMARY KEY,owner_kind TEXT NOT NULL,record_id TEXT NOT NULL,unit_id TEXT NOT NULL,layer_id TEXT NOT NULL,value TEXT NOT NULL,revision INTEGER NOT NULL DEFAULT 1);
    CREATE INDEX IF NOT EXISTS annotation_owner ON annotation_cells(owner_kind,record_id);
    CREATE UNIQUE INDEX IF NOT EXISTS annotation_identity ON annotation_cells(owner_kind,record_id,unit_id,layer_id);''')
    if 'size' not in {r[1] for r in db.execute('PRAGMA table_info(annotation_layers)')}:
        db.execute('ALTER TABLE annotation_layers ADD COLUMN size INTEGER NOT NULL DEFAULT 100')
    if 'anchor' not in {r[1] for r in db.execute('PRAGMA table_info(annotation_layers)')}:
        db.execute("ALTER TABLE annotation_layers ADD COLUMN anchor TEXT NOT NULL DEFAULT 'word'")

SENTENCE='@sentence'

def valid_cell(cell,words,definitions):
    layer=next((l for l in definitions if l['id']==cell['layer_id']),None)
    return bool(layer and (cell['unit_id']==SENTENCE if layer.get('anchor','word')!='word' else cell['unit_id'] in words))

def attach(body,words,definitions,cells):
    values={(c['unit_id'],c['layer_id']):c['value'] for c in cells}
    for w,uid in zip(body.get('words',[]),words):
        w['extra_layers']=[dict(**l,value=values.get((uid,l['id']),'')) for l in definitions if l.get('anchor','word')=='word']
    body['sentence_layers']=[dict(**l,value=values.get((SENTENCE,l['id']),'')) for l in definitions if l.get('anchor','word')!='word']
    body['annotation_review_count']=sum(not valid_cell(c,set(words),definitions) for c in cells)

def layers(db,lid):return [dict(r) for r in db.execute('SELECT * FROM annotation_layers WHERE language_id=? ORDER BY position,id',(lid,))]

def owner(db,kind,rid):
    if kind=='corpus':
        row=db.execute('SELECT e.body,e.revision,t.language_id FROM entries e JOIN texts t ON t.id=e.text_id WHERE e.id=?',(rid,)).fetchone()
    elif kind=='independent':row=db.execute('SELECT body,revision,language_id FROM dictionary_examples WHERE id=?',(rid,)).fetchone()
    else:raise ValueError('例句来源不正确')
    if not row:raise ValueError('例句已不存在')
    body=gloss_inheritance.load(db,kind,rid,row['body']);lid=body.get('language_id') or row['language_id']
    return body,lid,row['language_id'],row['revision']

def units(db,kind,rid,body):
    if kind=='corpus':return [dict(r,gloss=body['words'][r['position']]['gloss']) for r in db.execute("SELECT id,form,gloss,position FROM corpus_units WHERE entry_id=? AND kind='word' AND active=1 ORDER BY position",(rid,))]
    return [dict(id=w.get('annotation_id',''),form=w['form'],gloss=w['gloss'],position=i) for i,w in enumerate(body.get('words',[]))]

def independent_ids(old,new):
    import lexicon
    previous=[dict(id=w.get('annotation_id') or str(uuid.uuid4()),form=w['form'],gloss=w['gloss']) for w in old.get('words',[])]
    for word,uid in zip(new['words'],lexicon.match_units(previous,new['words'])):word['annotation_id']=uid

def get(db,kind,rid):
    body,lid,scope,revision=owner(db,kind,rid);words=units(db,kind,rid,body);defs=layers(db,lid)
    cells=[dict(r) for r in db.execute('SELECT * FROM annotation_cells WHERE owner_kind=? AND record_id=?',(kind,rid))]
    protected=set()
    if kind=='corpus':
        for r in db.execute('SELECT u.id,u.parent_id FROM corpus_units u JOIN lexical_links l ON l.unit_id=u.id WHERE u.entry_id=?',(rid,)):protected.add(r['parent_id'] or r['id'])
    else:
        for t in body.get('targets',[]):
            ref=t.get('segmentation_ref')
            if ref and not ref.get('detached') and 0<=ref.get('word',-1)<len(words):protected.add(words[ref['word']]['id'])
    for span in db.execute('SELECT word_ids FROM code_spans WHERE owner_kind=? AND record_id=?',(kind,rid)):
        protected.update(json.loads(span[0]))
    for i,w in enumerate(words):w['protected']=w['id'] in protected or bool(body['words'][i].get('redup_id') or body['words'][i].get('morph_groups') or body['words'][i].get('infix_confirmation'))
    live={w['id'] for w in words};allowed={l['id'] for l in defs}
    return dict(kind=kind,id=rid,body=body,language_id=lid,owner_language=scope,revision=revision,words=words,layers=defs,cells=cells,orphaned=[c for c in cells if not valid_cell(c,live,defs)])

def inline_save(db,b,lid):
    """Save fixed word slots and their layers as one undoable transaction."""
    import lexicon
    from corpus import analyze,parse,export_entry,compact_gloss,compact_empty_pairs
    gloss_inheritance.check_revision(db,b['kind'],b['id'],b)
    if 'slot_ids' in b:return inline_slots_save(db,b,lid)
    d=get(db,b['kind'],b['id']);new=b['body']
    if len(new['words'])!=len(d['words']):raise ValueError('原位编辑不能增删词格；请使用完整编辑器调整词数')
    if any(not lexicon.text(w.get('form','')).strip() and not lexicon.text(w.get('gloss','')).strip() for w in new['words']):
        return inline_slots_save(db,{**b,'slot_ids':[w['id'] for w in d['words']]},lid)
    # Validate optimistic snapshots and layer cells before changing any core data.
    mutate(db,'annotation-save',b,lid)
    body=d['body']
    import grammaticality
    grammaticality.copy_value(d['body'],body,new,b['kind'])
    for key in ('ipa','translation','notes'):
        body[key]=lexicon.text(new.get(key,''))
    if b['kind']=='independent':
        body['original']=lexicon.text(new.get('original',body.get('original','')))
        if not any(body[k].strip() for k in ('original','ipa','translation')):raise ValueError('请填写例句原文、IPA 或翻译')
    for old,w in zip(body['words'],new['words']):
        form=lexicon.text(w['form']);value=lexicon.text(w['gloss'])
        if (form,value)!=(old['form'],old['gloss']):
            form,value=compact_empty_pairs(form,value);value=compact_gloss(value)
        old.update(form=form,gloss=value)
    import punctuation
    punctuation.recognize_inline(body,d,b.get('slot_ids',[w['id'] for w in d['words']]),b.get('cells',[]))
    analyze(body)
    if b['kind']=='corpus':
        body['edited']=True
        checked,errors=parse(export_entry(body))
        if errors or len(checked)!=1 or any(checked[0][k]!=body[k] for k in ('ipa','translation')) or [(w['form'],w['gloss']) for w in checked[0]['words']]!=[(w['form'],w['gloss']) for w in body['words']]:raise ValueError('文本包含未配对括号或未转义引号，请修正后保存')
        gloss_inheritance.clear_metadata(body)
        db.execute('UPDATE entries SET body=?,revision=revision+1 WHERE id=?',(json.dumps(body,ensure_ascii=False),b['id']))
        lexicon.sync_entry(db,b['id'])
        fresh=units(db,'corpus',b['id'],body)
        mapping={a['id']:z['id'] for a,z in zip(d['words'],fresh)}
        # Explicit fixed-slot editing supplies correspondence even when both fields change.
        affected=[dict(r) for r in db.execute("SELECT * FROM annotation_cells WHERE owner_kind='corpus' AND record_id=?",(b['id'],)) if r['unit_id'] in mapping]
        for c in affected:db.execute('DELETE FROM annotation_cells WHERE id=?',(c['id'],))
        for c in affected:db.execute('INSERT INTO annotation_cells VALUES(?,?,?,?,?,?,?)',(c['id'],c['owner_kind'],c['record_id'],mapping[c['unit_id']],c['layer_id'],c['value'],c['revision']+int(mapping[c['unit_id']]!=c['unit_id'])))
    else:
        gloss_inheritance.clear_metadata(body)
        db.execute('UPDATE dictionary_examples SET body=?,revision=revision+1 WHERE id=?',(json.dumps(body,ensure_ascii=False),b['id']))
    return {'ok':True}


def create_sentence(db,b,lid):
    """Commit a local empty-sentence draft and its layers atomically."""
    import dictionary_data
    import grammar_survey
    from corpus import analyze
    kind=b.get('kind');rid=str(uuid.uuid4());position=None
    if kind=='corpus':
        text=db.execute('SELECT language_id FROM texts WHERE id=?',(b.get('text_id'),)).fetchone()
        if not text or text[0]!=lid:raise ValueError('目标文本不存在或语言不一致')
        position=db.execute('SELECT COALESCE(MAX(position),0)+1 FROM entries WHERE text_id=?',(b['text_id'],)).fetchone()[0]
        empty=analyze(dict(function='pass',ipa='',translation='',notes='',words=[],raw='',line=None,edited=True))
        db.execute('INSERT INTO entries(id,text_id,position,body) VALUES(?,?,?,?)',(rid,b['text_id'],position,json.dumps(empty)))
    elif kind=='independent':
        result=dictionary_data.mutate(db,'example-save',{'body':{'targets':b.get('targets',[]),'words':[]}},lid)
        rid=result['id']
    else:raise ValueError('例句来源无效')
    d=get(db,kind,rid)
    inline_slots_save(db,{**b,'id':rid,'revision':d['revision'],'before':[]},lid)
    if b.get('survey_node'):
        if kind!='independent':raise ValueError('调查新例句必须是独立例句')
        grammar_survey.mutate(db,lid,'evidence',dict(node_id=b['survey_node'],version=b.get('survey_version'),kind=kind,record_id=rid,body={}))
    return dict(ok=True,id=rid,kind=kind,position=position,text_id=b.get('text_id'))

def enrich(db,body,kind,rid):
    from corpus import analyze
    gloss_inheritance.resolve(db,kind,rid,body)
    if kind!='independent' and any('morphemes' not in w or any('gloss_fragments' not in m for m in w.get('morphemes',[])) for w in body.get('words',[])):
        if body.get('effective_language_id'):
            import languages
            languages.annotate(body,body.get('text_language_id'),{r['id']:dict(r) for r in db.execute('SELECT * FROM languages')})
        else:analyze(body)
    try:data=get(db,kind,rid)
    except ValueError:return analyze(body) if kind=='independent' else body
    if kind=='independent':
        import languages
        lid=data['language_id'];language=dict(db.execute('SELECT * FROM languages WHERE id=?',(lid,)).fetchone())
        languages.annotate(body,lid,{lid:language})
    attach(body,[w['id'] for w in data['words']],data['layers'],data['cells'])
    import morpheme_colors
    morpheme_colors.attach(db,body,kind,rid,data['language_id'])
    import code_switching
    code_switching.attach(db,body,kind,rid,data)
    return body

def mutate(db,action,b,lid):
    if action in ('layer-save','layer-delete'):
        old=db.execute('SELECT * FROM annotation_layers WHERE id=?',(b.get('id'),)).fetchone()
        if b.get('id') and (not old or old['revision']!=b.get('revision')):raise ValueError('标注层已变化，请重新打开')
        if action=='layer-delete':
            if b.get('confirmed') is not True:raise ValueError('删除标注层及其内容需要确认')
            db.execute('DELETE FROM annotation_cells WHERE layer_id=?',(b['id'],));db.execute('DELETE FROM annotation_layers WHERE id=?',(b['id'],));return {'ok':True}
        name=b.get('name','').strip();font=b.get('font','Junicode');style=b.get('style','normal');position=b.get('position',0)
        if not name or not font_catalog.valid_font(font) or style not in ('normal','italic','bold','bolditalic','small-caps') or not isinstance(position,int):raise ValueError('请检查标注层名称、字体、样式及顺序')
        anchor=b.get('anchor',old['anchor'] if old else 'word')
        if anchor not in ('word','ipa','translation'):raise ValueError('附加行位置无效')
        if old and old['anchor']!=anchor and db.execute('SELECT 1 FROM annotation_cells WHERE layer_id=?',(old['id'],)).fetchone():raise ValueError('已有内容的层不能改换对应单位；请新建附加行')
        xid=b.get('id') or str(uuid.uuid4())
        size=b.get('size',100)
        if not isinstance(size,int) or not 50<=size<=200:raise ValueError('字号比例须在 50% 到 200% 之间')
        db.execute('INSERT INTO annotation_layers(id,language_id,name,font,style,position,visible,searchable,revision,size) VALUES(?,?,?,?,?,?,?,?,1,?) ON CONFLICT(id) DO UPDATE SET name=excluded.name,font=excluded.font,style=excluded.style,position=excluded.position,visible=excluded.visible,searchable=excluded.searchable,size=excluded.size,revision=annotation_layers.revision+1',(xid,lid,name,font,style,position,int(bool(b.get('visible',True))),int(bool(b.get('searchable',True))),size))
        db.execute('UPDATE annotation_layers SET anchor=? WHERE id=?',(anchor,xid))
        return {'ok':True,'id':xid}
    data=get(db,b['kind'],b['id'])
    if data['revision']!=b.get('revision'):raise ValueError('例句已修改，请重新打开标注层编辑器')
    # Full snapshot detects concurrent edits without modifying the sentence itself.
    if data['cells']!=b.get('before'):raise ValueError('附加标注已修改，请重新打开')
    if data['layers']!=b.get('layers'):raise ValueError('标注层设置已变化，请重新打开')
    valid_units={w['id'] for w in data['words']};valid_layers={l['id'] for l in data['layers']}
    orphan_ids={c['id'] for c in data['orphaned']}
    for cid in b.get('discard',[]):
        if cid not in orphan_ids:raise ValueError('只能清除待核对的旧标注')
        db.execute('DELETE FROM annotation_cells WHERE id=?',(cid,))
    for c in b.get('cells',[]):
        if not valid_cell(c,valid_units,data['layers']) or not isinstance(c['value'],str):raise ValueError('附加标注的对应关系不正确')
        old=db.execute('SELECT * FROM annotation_cells WHERE owner_kind=? AND record_id=? AND unit_id=? AND layer_id=?',(b['kind'],b['id'],c['unit_id'],c['layer_id'])).fetchone()
        if not c['value']:
            if old:db.execute('DELETE FROM annotation_cells WHERE id=?',(old['id'],))
        elif not old or old['value']!=c['value']:
            db.execute('INSERT INTO annotation_cells VALUES(?,?,?,?,?,?,1) ON CONFLICT(id) DO UPDATE SET value=excluded.value,revision=annotation_cells.revision+1',(old['id'] if old else str(uuid.uuid4()),b['kind'],b['id'],c['unit_id'],c['layer_id'],c['value']))
    return {'ok':True}

def validate(db):
    if db.execute('SELECT 1 FROM annotation_cells c LEFT JOIN annotation_layers l ON l.id=c.layer_id WHERE l.id IS NULL').fetchone():raise ValueError('仍有标注引用此层，请先撤销标注内容或删除该层')

def search(db,q):
    """Paginate empty searches in SQL; analyze only visible hits in filtered searches."""
    from corpus import analyze,QueryMatcher,normalize
    source=q.get('source','all');lid=q.get('language','all');query=q.get('q','');field=q.get('field','all');mode=q.get('mode','contains');case=q.get('case')=='true'
    if source not in ('all','corpus','independent'):raise ValueError('例句来源无效')
    branches=[];args=[]
    if source in ('all','corpus'):
        branches.append("SELECT 'corpus' kind,e.id,e.body,COALESCE(NULLIF(json_extract(e.body,'$.language_id'),''),t.language_id) language_id,t.language_id owner_language,t.title,e.text_id,e.position,t.rowid ordering,0 source_order FROM entries e JOIN texts t ON t.id=e.text_id WHERE (?='all' OR COALESCE(NULLIF(json_extract(e.body,'$.language_id'),''),t.language_id)=?)")
        args.extend([lid,lid])
    if source in ('all','independent'):
        branches.append("SELECT 'independent' kind,e.id,e.body,e.language_id,e.language_id owner_language,COALESCE(NULLIF(json_extract(e.body,'$.source'),''),'独立例句') title,NULL text_id,NULL position,e.rowid ordering,1 source_order FROM dictionary_examples e WHERE (?='all' OR e.language_id=?)")
        args.extend([lid,lid])
    sql=' UNION ALL '.join(branches)
    if q.get('text_id'):
        sql='SELECT * FROM ('+sql+') WHERE text_id=?';args.append(q['text_id'])
    import code_switching
    extra,values=code_switching.filter_sql(q,'q.kind','q.id')
    sql='SELECT * FROM ('+sql+') q WHERE 1=1'+extra;args.extend(values)
    import grammaticality
    extra,values=grammaticality.filter_sql(q,'q.body','q.language_id');sql+=extra+(" AND q.kind='independent'" if extra else '');args.extend(values)
    page=max(1,int(q.get('page',1)))
    if not normalize(query,case) and field!='reduplication':
        total=db.execute('SELECT COUNT(*) FROM ('+sql+')',args).fetchone()[0];pages=max(1,(total+19)//20);page=min(page,pages)
        visible=list(db.execute('SELECT * FROM ('+sql+') ORDER BY source_order,ordering,position LIMIT 20 OFFSET ?',[*args,(page-1)*20]))
    else:
        layer_hits={};defs={r['id']:dict(r) for r in db.execute('SELECT * FROM annotation_layers WHERE searchable=1')}
        def hit(value):
            a=normalize(value,case);b=normalize(query,case)
            return a==b if mode=='exact' else a.startswith(b) if mode=='prefix' else a.endswith(b) if mode=='suffix' else b in a
        if field in ('all','layers'):
            for c in db.execute('SELECT * FROM annotation_cells'):
                if c['layer_id'] in defs and hit(c['value']):layer_hits.setdefault((c['owner_kind'],c['record_id']),[]).append(dict(c))
        matches=[]
        matcher=QueryMatcher(query,field,mode=mode,case=case)
        for r in gloss_inheritance.iter_rows(db,db.execute('SELECT * FROM ('+sql+') ORDER BY source_order,ordering,position',args),lightweight=True):
            b=gloss_inheritance.load(db,r['kind'],r['id'],r['body'],metadata=False,lightweight=True);_,found=matcher(b)
            if field in ('all','original'):found=found or hit(b.get('original',''))
            if not found and (r['kind'],r['id']) in layer_hits:
                live={w['id'] for w in units(db,r['kind'],r['id'],b)};layers_for_language=[v for v in defs.values() if v['language_id']==r['language_id']]
                found=any(valid_cell(c,live,layers_for_language) for c in layer_hits[(r['kind'],r['id'])])
            if found:matches.append(r)
        total=len(matches);pages=max(1,(total+19)//20);page=min(page,pages);visible=matches[(page-1)*20:page*20]
    items=[]
    for r in visible:
        b=enrich(db,analyze(json.loads(r['body'])),r['kind'],r['id'])
        item={k:r[k] for k in ('kind','id','language_id','owner_language','title','text_id','position')};item['body']=b
        if r['kind']=='independent':item['lexeme_id']=b['targets'][0]['lexeme_id'] if b.get('targets') else None
        items.append(item)
    stats=code_switching.summary(db,sql,args,None if not normalize(query,case) and field!='reduplication' else {(r['kind'],r['id']) for r in matches})
    return dict(items=items,total=total,page=page,pages=pages,code_summary=stats)


def inline_slots_save(db,b,lid):
    """Explicit word identities permit insertion, merging and movement without re-matching."""
    import lexicon
    from corpus import analyze,parse,export_entry,compact_gloss,compact_empty_pairs
    d=get(db,b['kind'],b['id'])
    if d['owner_language']!=lid:raise ValueError('例句不属于当前语言')
    # Validate concurrency and layer configuration before any mutation.
    mutate(db,'annotation-save',{**b,'cells':[],'discard':[]},lid)
    slots=b.get('slot_ids');new=b.get('body',{});words=new.get('words')
    if not isinstance(slots,list) or not isinstance(words,list) or len(slots)!=len(words) or len(slots)>10000 or any(not isinstance(s,str) for s in slots) or len(set(slots))!=len(slots):raise ValueError('词格对应关系无效')
    old={w['id']:(i,d['body']['words'][i]) for i,w in enumerate(d['words'])}
    ids={}
    for s in slots:
        if s in old:ids[s]=s
        elif s.startswith('new:') and len(s)<=80:ids[s]=str(uuid.uuid4())
        else:raise ValueError('词格已变化或不属于本句，请重新打开')
    removed=set(old)-set(slots)
    def content(uid):
        w=old[uid][1]
        return any(str(w.get(k,'')).strip() for k in ('form','gloss')) or next(v for v in d['words'] if v['id']==uid)['protected'] or any(c['unit_id']==uid and c['value'].strip() for c in d['cells'])
    if any(content(uid) for uid in removed) and b.get('delete_confirmed') is not True:raise ValueError('删除有内容或关联的词格需要确认')
    body=copy.deepcopy(d['body']);updated=[];changed=[];kept=[];emptied=set()
    # Deleted/merged slots keep their manual analyses available for review.
    # Dictionary references and extra-layer cells already retain retired IDs.
    for uid in sorted(removed,key=lambda uid:old[uid][0]):
        previous=old[uid][1]
        if previous.get('morph_groups') or previous.get('infix_confirmation'):
            body.setdefault('orphaned_morphology',[]).append({k:copy.deepcopy(previous[k]) for k in ('form','gloss','morph_groups','infix_confirmation') if k in previous})
    import grammaticality
    grammaticality.copy_value(d['body'],body,new,b['kind'])
    for s,w in zip(slots,words):
        if not isinstance(w,dict):raise ValueError('词格格式错误')
        item=copy.deepcopy(old[s][1]) if s in old else {'form_kind':'content','gloss_kind':'content'}
        form=lexicon.text(w.get('form',''));gloss=lexicon.text(w.get('gloss',''))
        if s not in old or (form,gloss)!=(item['form'],item['gloss']):
            form,gloss=compact_empty_pairs(form,gloss)
            gloss=compact_gloss(gloss)
        if not form.strip() and not gloss.strip():
            emptied.add(s)
            if item.get('morph_groups') or item.get('infix_confirmation'):
                body.setdefault('orphaned_morphology',[]).append({k:copy.deepcopy(item[k]) for k in ('form','gloss','morph_groups','infix_confirmation') if k in item})
            continue
        if s in old and (item['form'],item['gloss'])!=(form,gloss):changed.append(s)
        item.update(form=form,gloss=gloss)
        if b['kind']=='independent':item['annotation_id']=ids[s]
        if w.get('redup_id'):
            if item.get('redup_id') and item['redup_id']!=w['redup_id']:raise ValueError('重叠词格身份已变化，请重新打开')
            item['redup_id']=w['redup_id']
        updated.append(item)
        kept.append(s)
    slots=kept
    body['words']=updated
    import reduplication
    reduplication.accept(d['body'],body,new)
    for key in ('ipa','translation','notes'):
        body[key]=lexicon.text(new.get(key,''))
    if b['kind']=='independent':
        body['original']=lexicon.text(new.get('original',body.get('original','')))
        positions={old[s][0]:i for i,s in enumerate(slots) if s in old}
        for target in body.get('targets',[]):
            ref=target.get('segmentation_ref')
            if ref and not ref.get('detached'):
                if ref['word'] in positions:ref['word']=positions[ref['word']]
                else:ref['detached']=True
    import punctuation
    punctuation.recognize_inline(body,d,slots,b.get('cells',[]))
    analyze(body)
    if b['kind']=='corpus':
        body['edited']=True;checked,errors=parse(export_entry(body))
        if errors or len(checked)!=1 or any(checked[0][k]!=body[k] for k in ('ipa','translation')) or [(w['form'],w['gloss']) for w in checked[0]['words']]!=[(w['form'],w['gloss']) for w in body['words']]:raise ValueError('文本包含未配对括号或未转义引号，请修正后保存')
    table='entries' if b['kind']=='corpus' else 'dictionary_examples'
    gloss_inheritance.clear_metadata(body)
    db.execute('UPDATE '+table+' SET body=?,revision=revision+1 WHERE id=?',(json.dumps(body,ensure_ascii=False),b['id']))
    if b['kind']=='corpus':
        lexicon.sync_entry(db,b['id'],[ids[s] for s in slots])
        import link_review
        for uid in changed:link_review.mark(db,'unit_id=?',(uid,),'原词格的形式或标注已修改，请核对关联')
    cells=[]
    for c in b.get('cells',[]):
        uid=c.get('unit_id')
        if uid!='@sentence' and uid not in ids:raise ValueError('附加层指向已删除或未知词格')
        if not valid_cell(c,set(ids),d['layers']) or not isinstance(c.get('value'),str):raise ValueError('附加标注的对应关系不正确')
        if uid in emptied:
            # Keep typed layer content as a recoverable orphan of the removed slot.
            old_cell=db.execute('SELECT id,value FROM annotation_cells WHERE owner_kind=? AND record_id=? AND unit_id=? AND layer_id=?',(b['kind'],b['id'],ids[uid],c['layer_id'])).fetchone()
            if not c['value']:
                if old_cell:db.execute('DELETE FROM annotation_cells WHERE id=?',(old_cell['id'],))
            elif not old_cell or old_cell['value']!=c['value']:
                db.execute('INSERT INTO annotation_cells VALUES(?,?,?,?,?,?,1) ON CONFLICT(id) DO UPDATE SET value=excluded.value,revision=annotation_cells.revision+1',(old_cell['id'] if old_cell else str(uuid.uuid4()),b['kind'],b['id'],ids[uid],c['layer_id'],c['value']))
            continue
        cells.append({**c,'unit_id':ids.get(uid,uid)})
    fresh=get(db,b['kind'],b['id'])
    mutate(db,'annotation-save',{**b,'revision':fresh['revision'],'before':fresh['cells'],'layers':fresh['layers'],'cells':cells,'discard':[]},lid)
    return {'ok':True}
