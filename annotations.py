"""Configurable word layers, attached to stable word identities."""
import json
import sentence_rows
import copy
import uuid
from collections import defaultdict
import font_catalog
import gloss_inheritance
import display_spacing

TABLES=('annotation_layers','annotation_cells')
# Inline edits keep the owner and all catalogs in place. The transaction can
# change its relations, inherited gloss and manually edited annotation cells.
INDEPENDENT_INLINE_TABLES=('dictionary_examples','independent_links','independent_word_overrides',
                           'annotation_cells','gloss_bindings','code_spans','code_time_links')
def initialize(db):
    db.executescript('''CREATE TABLE IF NOT EXISTS annotation_layers(id TEXT PRIMARY KEY,language_id TEXT NOT NULL,name TEXT NOT NULL,font TEXT NOT NULL,style TEXT NOT NULL DEFAULT 'normal',position INTEGER NOT NULL DEFAULT 0,visible INTEGER NOT NULL DEFAULT 1,searchable INTEGER NOT NULL DEFAULT 1,revision INTEGER NOT NULL DEFAULT 1);
    CREATE TABLE IF NOT EXISTS annotation_cells(id TEXT PRIMARY KEY,owner_kind TEXT NOT NULL,record_id TEXT NOT NULL,unit_id TEXT NOT NULL,layer_id TEXT NOT NULL,value TEXT NOT NULL,revision INTEGER NOT NULL DEFAULT 1);
    CREATE INDEX IF NOT EXISTS annotation_owner ON annotation_cells(owner_kind,record_id);
    CREATE UNIQUE INDEX IF NOT EXISTS annotation_identity ON annotation_cells(owner_kind,record_id,unit_id,layer_id);''')
    if 'size' not in {r[1] for r in db.execute('PRAGMA table_info(annotation_layers)')}:
        db.execute('ALTER TABLE annotation_layers ADD COLUMN size INTEGER NOT NULL DEFAULT 100')
    if 'anchor' not in {r[1] for r in db.execute('PRAGMA table_info(annotation_layers)')}:
        db.execute("ALTER TABLE annotation_layers ADD COLUMN anchor TEXT NOT NULL DEFAULT 'word'")
    display_spacing.initialize(db, 'annotation_layers')
    columns={r[1] for r in db.execute('PRAGMA table_info(annotation_layers)')}
    for name,definition in [('source',"TEXT NOT NULL DEFAULT 'manual'"),('dictionary_field',"TEXT NOT NULL DEFAULT ''")]:
        if name not in columns:db.execute('ALTER TABLE annotation_layers ADD COLUMN '+name+' '+definition)

SENTENCE='@sentence'

def valid_cell(cell,words,definitions):
    layer=next((l for l in definitions if l['id']==cell['layer_id']),None)
    return bool(layer and layer.get('source','manual')!='dictionary' and (cell['unit_id']==SENTENCE if layer.get('anchor','word')!='word' else cell['unit_id'] in words))

def attach(body,words,definitions,cells):
    values={(c['unit_id'],c['layer_id']):c['value'] for c in cells}
    for w,uid in zip(body.get('words',[]),words):
        w['extra_layers']=[dict(**l,value=values.get((uid,l['id']),'')) for l in definitions if l.get('anchor','word')=='word']
    body['sentence_layers']=[dict(**l,value=values.get((SENTENCE,l['id']),'')) for l in definitions if l.get('anchor','word')!='word']
    live=set(words)
    body['annotation_review_count']=sum(not valid_cell(c,live,definitions) for c in cells)

def layers(db,lid):return [dict(r) for r in db.execute('SELECT * FROM annotation_layers WHERE language_id=? ORDER BY position,id',(lid,))]

def owner_record(db,kind,rid):
    if kind=='corpus':
        row=db.execute('SELECT e.revision,t.language_id FROM entries e JOIN texts t ON t.id=e.text_id WHERE e.id=?',(rid,)).fetchone()
    elif kind=='independent':row=db.execute('SELECT revision,language_id FROM dictionary_examples WHERE id=?',(rid,)).fetchone()
    else:raise ValueError('例句来源不正确')
    if not row:raise ValueError('例句已不存在')
    return row

def owner(db,kind,rid):
    row=owner_record(db,kind,rid)
    body=gloss_inheritance.load(db,kind,rid,sentence_rows.one(db,kind,rid));lid=body.get('language_id') or row['language_id']
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
    result=dict(kind=kind,id=rid,body=body,language_id=lid,owner_language=scope,revision=revision,words=words,layers=defs,cells=cells,orphaned=[c for c in cells if not valid_cell(c,live,defs)])
    if any(l.get('source')=='dictionary' for l in defs):
        import dictionary_layers,corpus
        projected=dictionary_layers.project(db,corpus.analyze(copy.deepcopy(body)),kind,rid,lid,defs)
        result['dictionary_layers']={w['id']:[{**l,'unit_id':w['id']} for l in projected['words'][i].get('extra_layers',[]) if l.get('derived')] for i,w in enumerate(words)}
    if kind=='independent':
        import example_numbering
        result['library_number']=example_numbering.number(db,lid,rid)
    return result

def inline_save(db,b,lid):
    """Save fixed word slots and their layers as one undoable transaction."""
    import lexicon
    from corpus import analyze,parse,export_entry,normalize_edited_pair
    gloss_inheritance.check_revision(db,b['kind'],b['id'],b)
    if 'slot_ids' in b:return inline_slots_save(db,b,lid)
    d=get(db,b['kind'],b['id']);new=b['body']
    if len(new['words'])!=len(d['words']):raise ValueError('原位编辑不能增删词格；请使用完整编辑器调整词数')
    if any(not lexicon.text(w.get('form','')).strip() and not lexicon.text(w.get('gloss','')).strip() for w in new['words']):
        return inline_slots_save(db,{**b,'slot_ids':[w['id'] for w in d['words']]},lid)
    # Validate optimistic snapshots and layer cells before changing any core data.
    mutate(db,'annotation-save',b,lid,snapshot=d)
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
            form,value=normalize_edited_pair(form,value)
        old.update(form=form,gloss=value)
    import punctuation
    punctuation.recognize_inline(body,d,b.get('slot_ids',[w['id'] for w in d['words']]),b.get('cells',[]))
    analyze(body)
    import auto_reduplication
    auto_reduplication.on_save(db,b['kind'],b['id'],body,d['language_id'],previous=d['body'],word_ids=[w['id'] for w in d['words']])
    if b['kind']=='corpus':
        body['edited']=True
        checked,errors=parse(export_entry(body))
        if errors or len(checked)!=1 or any(checked[0][k]!=body[k] for k in ('ipa','translation')) or [(w['form'],w['gloss']) for w in checked[0]['words']]!=[(w['form'],w['gloss']) for w in body['words']]:raise ValueError('文本包含未配对括号或未转义引号，请修正后保存')
        gloss_inheritance.clear_metadata(body)
        sentence_rows.write(db,'corpus',b['id'],body)
        lexicon.sync_entry(db,b['id'],analyzed_body=body,stored_body=body)
        fresh=units(db,'corpus',b['id'],body)
        mapping={a['id']:z['id'] for a,z in zip(d['words'],fresh)}
        # Explicit fixed-slot editing supplies correspondence even when both fields change.
        affected=[dict(r) for r in db.execute("SELECT * FROM annotation_cells WHERE owner_kind='corpus' AND record_id=?",(b['id'],)) if r['unit_id'] in mapping]
        for c in affected:db.execute('DELETE FROM annotation_cells WHERE id=?',(c['id'],))
        for c in affected:db.execute('INSERT INTO annotation_cells VALUES(?,?,?,?,?,?,?)',(c['id'],c['owner_kind'],c['record_id'],mapping[c['unit_id']],c['layer_id'],c['value'],c['revision']+int(mapping[c['unit_id']]!=c['unit_id'])))
    else:
        gloss_inheritance.clear_metadata(body)
        from independent_links import write_body
        write_body(db,b['id'],body)
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
        sentence_rows.write(db,'corpus',rid,empty,columns=dict(text_id=b['text_id'],position=position),insert=True)
    elif kind=='independent':
        result=dictionary_data.mutate(db,'example-save',{'body':{'targets':b.get('targets',[]),'words':[]}},lid)
        rid=result['id']
    else:raise ValueError('例句来源无效')
    d=get(db,kind,rid)
    inline_slots_save(db,{**b,'id':rid,'revision':d['revision'],'before':[]},lid)
    if b.get('survey_node'):
        if kind!='independent':raise ValueError('调查新例句必须是独立例句')
        grammar_survey.mutate(db,lid,'evidence',dict(node_id=b['survey_node'],version=b.get('survey_version'),kind=kind,record_id=rid,body={}))
    if b.get('example_group'):
        import example_groups
        if kind!='independent':raise ValueError('只有独立例句可加入例句组')
        group=example_groups.detail(db,lid,b['example_group'],False)
        example_groups.mutate(db,lid,'save',dict(id=group['id'],token=b.get('example_group_token'),body=group['body'],members=[dict(example_id=m['example_id'],role=m['role']) for m in group['members']]+[dict(example_id=rid,role='')]))
    return dict(ok=True,id=rid,kind=kind,position=position,text_id=b.get('text_id'))

def enrich(db,body,kind,rid,*,snapshot=None):
    from corpus import analyze
    if kind=='independent':
        import independent_links
        independent_links.source_body(db,rid,body)
    gloss_inheritance.resolve(db,kind,rid,body)
    if kind!='independent' and any('morphemes' not in w or any('gloss_fragments' not in m for m in w.get('morphemes',[])) for w in body.get('words',[])):
        if body.get('effective_language_id'):
            import languages
            languages.annotate(body,body.get('text_language_id'),{r['id']:dict(r) for r in db.execute('SELECT * FROM languages')})
        else:analyze(body)
    try:data=snapshot if snapshot is not None else get(db,kind,rid)
    except ValueError:return analyze(body) if kind=='independent' else body
    if kind=='independent':
        import languages
        lid=data['language_id'];language=dict(db.execute('SELECT * FROM languages WHERE id=?',(lid,)).fetchone())
        body['library_number']=data['library_number']
        languages.annotate(body,lid,{lid:language})
    attach(body,[w['id'] for w in data['words']],data['layers'],data['cells'])
    for w,unit in zip(body.get('words',[]),data['words']):
        derived={l['id']:l for l in data.get('dictionary_layers',{}).get(unit['id'],[])}
        w['extra_layers']=[derived.get(l['id'],l) for l in w.get('extra_layers',[])]
    import morpheme_colors
    morpheme_colors.attach(db,body,kind,rid,data['language_id'])
    import code_switching
    code_switching.attach(db,body,kind,rid,data)
    return body


def independent_card(db,rid):
    from corpus import analyze
    data=get(db,'independent',rid)
    return enrich(db,analyze(data['body']),'independent',rid,snapshot=data)


def evidence_cards(db,kind,records):
    """Read one page's bodies, tier values and display dependencies in batches."""
    import code_switching
    import dictionary_layers
    import grammaticality
    import independent_links
    import languages
    import morpheme_colors
    import sentence_rows
    from corpus import analyze

    if not records:return {}
    owners={r['id']:r['language_id'] for r in records if r['id'] is not None}
    ids=list(owners)
    bodies=sentence_rows.read(db,kind,ids)
    if not bodies:return {}
    marks=','.join('?' for _ in ids)
    cells=defaultdict(list)
    for row in db.execute('SELECT * FROM annotation_cells WHERE owner_kind=? AND record_id IN ('+marks+')',[kind,*ids]):
        cells[row['record_id']].append(row)
    spans=defaultdict(list)
    for row in db.execute('SELECT * FROM code_spans WHERE owner_kind=? AND record_id IN ('+marks+') ORDER BY rowid',[kind,*ids]):
        spans[row['record_id']].append(row)
    codes={r['id']:r for r in code_switching.catalog(db)} if spans else {}
    word_ids=defaultdict(list)
    numbers={}
    if kind=='independent':
        for body in bodies.values():body['targets']=[]
        links=independent_links.images(db,db.execute('SELECT * FROM independent_links WHERE example_id IN ('+
                                      marks+') ORDER BY example_id,position',ids).fetchall())
        target_ids=set()
        for row in links:
            target=independent_links.target(row)
            bodies[row['example_id']]['targets'].append(target)
            if row['word_position'] is not None:target_ids.add(row['lexeme_id'])
        for row in independent_links.overrides(db,ids):
            words=bodies[row['example_id']]['words']
            if row['position']<len(words):words[row['position']]=independent_links.word_value(row['word'])
        for row in db.execute('SELECT id,language_id,number FROM example_numbers WHERE id IN ('+marks+')',ids):
            numbers[row['language_id'],row['id']]=row['number']
        prepared_colors={'catalog':morpheme_colors.target_types(db,target_ids)}
    else:
        for row in db.execute("SELECT entry_id,id FROM corpus_units WHERE kind='word' AND active=1 AND entry_id IN ("+marks+') ORDER BY entry_id,position',ids):
            word_ids[row['entry_id']].append(row['id'])
        prepared_colors=morpheme_colors.prepare(db,ids)
        for body in bodies.values():grammaticality.strip_corpus(body)
    effective={rid:body.get('language_id') or owners[rid] for rid,body in bodies.items()}
    defs={lid:layers(db,lid) for lid in set(effective.values())}
    catalog={};settings={}
    if kind=='independent':
        for lid in defs:
            lang=dict(db.execute('SELECT * FROM languages WHERE id=?',(lid,)).fetchone())
            catalog[lid]=lang
            settings[lid]=json.loads(lang['metadata'])
    gloss_inheritance.prefetch(db,kind,list(bodies))
    layer_targets={}
    for rid,body in bodies.items():
        lid=effective[rid]
        gloss_inheritance.resolve(db,kind,rid,body)
        if kind=='independent':
            body['library_number']=numbers.get((lid,rid))
            languages.annotate(body,lid,catalog,settings=settings)
            uids=[w.get('annotation_id','') for w in body['words']]
        else:
            analyze(body)
            uids=word_ids[rid]
        attach(body,uids,defs[lid],cells[rid])
        dictionary_layers.project(db,body,kind,rid,lid,defs[lid],target_cache=layer_targets,unit_ids=uids)
        morpheme_colors.attach(db,body,kind,rid,lid,prepared_colors)
        if spans.get(rid):
            data=dict(kind=kind,id=rid,body=body,language_id=lid,owner_language=owners[rid],
                      words=[dict(id=uid,position=i) for i,uid in enumerate(uids)])
            code_switching.attach(db,body,kind,rid,data,spans=spans[rid],codes=codes)
        else:
            code_switching.attach(db,body,kind,rid,spans=[])
    return bodies


def mutate(db,action,b,lid,*,snapshot=None):
    if action=='layer-order':
        current=layers(db,lid)
        snapshot=[dict(id=l['id'],revision=l['revision']) for l in current]
        order=b.get('order')
        if b.get('snapshot')!=snapshot:raise ValueError('标注层已变化，请重新打开')
        if not isinstance(order,list) or any(not isinstance(x,str) for x in order) or len(order)!=len(current) or set(order)!={l['id'] for l in current}:raise ValueError('标注层排序必须包含本语言的全部层，且不能重复')
        if order==[l['id'] for l in current]:return {'ok':True,'layers':current}
        for position,xid in enumerate(order):
            db.execute('UPDATE annotation_layers SET position=?,revision=revision+1 WHERE id=? AND language_id=?',(position,xid,lid))
        return {'ok':True,'layers':layers(db,lid)}
    if action in ('layer-save','layer-delete'):
        old=db.execute('SELECT * FROM annotation_layers WHERE id=?',(b.get('id'),)).fetchone()
        if b.get('id') and (not old or old['language_id']!=lid or old['revision']!=b.get('revision')):raise ValueError('标注层已变化，请重新打开')
        if action=='layer-delete':
            if b.get('confirmed') is not True:raise ValueError('删除标注层及其内容需要确认')
            db.execute('DELETE FROM annotation_cells WHERE layer_id=?',(b['id'],));db.execute('DELETE FROM annotation_layers WHERE id=?',(b['id'],));return {'ok':True}
        name=b.get('name','').strip();font=b.get('font','Junicode');style=b.get('style','normal');position=b.get('position',0)
        if not name or not font_catalog.valid_row_font(font) or style not in ('normal','italic','bold','bolditalic','small-caps') or not isinstance(position,int):raise ValueError('请检查标注层名称、字体、样式及顺序')
        anchor=b.get('anchor',old['anchor'] if old else 'word')
        if anchor not in ('word','ipa','translation'):raise ValueError('附加行位置无效')
        if old and old['anchor']!=anchor and db.execute('SELECT 1 FROM annotation_cells WHERE layer_id=?',(old['id'],)).fetchone():raise ValueError('已有内容的层不能改换对应单位；请新建附加行')
        import dictionary_layers
        source,field=dictionary_layers.configuration(db,b,old,lid,anchor)
        xid=b.get('id') or str(uuid.uuid4())
        size=b.get('size',100)
        if not isinstance(size,int) or not 50<=size<=200:raise ValueError('字号比例须在 50% 到 200% 之间')
        spacing=display_spacing.values(b,old,internal=True)
        db.execute('INSERT INTO annotation_layers(id,language_id,name,font,style,position,visible,searchable,revision,size) VALUES(?,?,?,?,?,?,?,?,1,?) ON CONFLICT(id) DO UPDATE SET name=excluded.name,font=excluded.font,style=excluded.style,position=excluded.position,visible=excluded.visible,searchable=excluded.searchable,size=excluded.size,revision=annotation_layers.revision+1',(xid,lid,name,font,style,position,int(bool(b.get('visible',True))),int(bool(b.get('searchable',True))),size))
        db.execute('UPDATE annotation_layers SET anchor=?,space_before=?,space_after=?,line_spacing=? WHERE id=?',(anchor,spacing['space_before'],spacing['space_after'],spacing['line_spacing'],xid))
        db.execute('UPDATE annotation_layers SET source=?,dictionary_field=? WHERE id=?',(source,field,xid))
        return {'ok':True,'id':xid}
    data=snapshot if snapshot is not None else get(db,b['kind'],b['id'])
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

def validate(db,cell_ids=None):
    sql='SELECT 1 FROM annotation_cells c LEFT JOIN annotation_layers l ON l.id=c.layer_id'
    if cell_ids is None:
        rows=db.execute(sql+' WHERE l.id IS NULL LIMIT 1')
    else:
        import lexicon
        rows=lexicon.scoped_rows(db,sql,[('c.id',cell_ids)],' AND l.id IS NULL LIMIT 1')
    if next(iter(rows),None):raise ValueError('仍有标注引用此层，请先撤销标注内容或删除该层')

def search_catalog(db,lid):
    fields=[]
    for r in db.execute("SELECT id,name FROM annotation_layers WHERE ?='all' OR language_id=? ORDER BY position,id",(lid,lid)):
        fields.append(dict(id='layer:'+r['id'],name=r['name'],group='layer'))
    for r in db.execute("SELECT id,name FROM writing_types WHERE ?='all' OR language_id=? ORDER BY rowid",(lid,lid)):
        fields.append(dict(id='writing:'+r['id'],name=r['name'],group='writing'))
    return dict(fields=fields)


class SearchFields:
    """Query-local custom values shared by sentence and survey searches."""
    def __init__(self,db,lid,q):
        if not db.in_transaction:db.execute('BEGIN')
        import corpus,long_tasks
        from collections import defaultdict
        self.db=db;self.field=q.get('field','all');self.query=q.get('q','');self.case=q.get('case')=='true';self.mode=q.get('mode') or ('exact' if q.get('exact')=='true' else 'contains')
        self.cells=defaultdict(list);self.links=defaultdict(set);self.targets={};self.types={};self.defs={}
        self.analysis_cache=None
        self.cached_table=None
        self.full_references=False
        if not self.query.strip() or self.field not in ('all','layers','writings') and not self.field.startswith(('layer:','writing:')):return
        catalog=search_catalog(db,lid)
        if self.field.startswith(('layer:','writing:')) and self.field not in {f['id'] for f in catalog['fields']}:raise ValueError('自定义检索字段已删除或不属于当前语言，请重新选择')
        import material_search_index,sentence_search_index
        if material_search_index.available(db) and sentence_search_index.available(db):
            try:
                with material_search_index.preparing(db):
                    material_search_index.refresh_custom(db)
                    sql,args=material_search_index.custom_hits(db,self.field,self.query,self.case,self.mode,lid,details=True)
                    self.cached_table='custom_query_'+uuid.uuid4().hex
                    self.cached_labels={f['id']:f['name'] for f in catalog['fields']}
                    db.execute('CREATE TEMP TABLE '+self.cached_table+' AS '+sql,args)
                    db.execute('CREATE INDEX '+self.cached_table+'_owners ON '+self.cached_table+'(kind,id)')
                return
            except material_search_index.Unavailable:
                self.cached_table=None
        if self.field in ('all','layers') or self.field.startswith('layer:'):
            self.defs={r['id']:dict(r) for r in db.execute("SELECT * FROM annotation_layers WHERE ?='all' OR language_id=?",(lid,lid)) if (self.field.startswith('layer:') or r['searchable']) and (not self.field.startswith('layer:') or r['id']==self.field[6:])}
            for c in long_tasks.steps(db.execute("SELECT c.* FROM annotation_cells c JOIN annotation_layers l ON l.id=c.layer_id WHERE ?='all' OR l.language_id=?",(lid,lid))) if self.defs else ():
                if c['layer_id'] in self.defs and self.hit(c['value']):self.cells[(c['owner_kind'],c['record_id'])].append(dict(c))
        if self.field in ('all','writings') or self.field.startswith('writing:'):
            self.types={r['id']:dict(r) for r in db.execute("SELECT * FROM writing_types WHERE ?='all' OR language_id=?",(lid,lid)) if not self.field.startswith('writing:') or r['id']==self.field[8:]}
            import word_structure
            import record_sources
            rows=(r for table in ('lexemes','morphemes') for r in record_sources.with_bodies(
                db,table,db.execute("SELECT id,language_id FROM "+table+" WHERE ?='all' OR language_id=?",(lid,lid))))
            for r in long_tasks.steps(rows) if self.types else ():
                body=r['body'];values=[]
                for w in [*body.get('orthographies',[]),*body.get('writings',[]),*word_structure.writing_rows(body)]:
                    if w.get('type_id') in self.types and self.types[w['type_id']]['language_id']==r['language_id'] and self.hit(w.get('text','')):
                        values.append(dict(field='writing:'+w['type_id'],label=self.types[w['type_id']]['name'],text=w['text']))
                if values:self.targets[r['id']]=(r['language_id'],values)
            if self.targets:
                for r in long_tasks.steps(db.execute('SELECT u.entry_id,l.lexeme_id,COALESCE(p.position,u.position) word_position FROM lexical_links l JOIN corpus_units u ON u.id=l.unit_id LEFT JOIN corpus_units p ON p.id=u.parent_id WHERE u.active=1')):
                    if r['lexeme_id'] in self.targets:self.links[r['entry_id']].add((r['lexeme_id'],r['word_position']))
        self.full_references=bool(self.targets or any(d.get('source')=='dictionary' for d in self.defs.values()))

    def hit(self,value):
        from corpus import normalize
        a,b=normalize(value,self.case),normalize(self.query,self.case)
        return a==b if self.mode=='exact' else a.startswith(b) if self.mode=='prefix' else a.endswith(b) if self.mode=='suffix' else b in a

    def values(self,kind,rid,body,lid):
        if self.cached_table is not None:
            found=[dict(field=r['field'],label=self.cached_labels[r['field']],text=r['display'],word=r['word'] if r['word']>=0 else None)
              for r in self.db.execute('SELECT field,word,display FROM '+self.cached_table+' WHERE kind=? AND id=?',(kind,rid))]
            return list({(v['field'],v['text'],v.get('word')):v for v in found}.values())
        found=[];cells=self.cells.get((kind,rid),[])
        if cells:
            definitions=[v for v in self.defs.values() if v['language_id']==lid]
            live={w['id']:w['position'] for w in units(self.db,kind,rid,body)}
            for c in cells:
                if valid_cell(c,live,definitions):found.append(dict(field='layer:'+c['layer_id'],label=self.defs[c['layer_id']]['name'],text=c['value'],word=live.get(c['unit_id'])))
        targets=self.links.get(rid,()) if kind=='corpus' else set()
        if kind=='independent' and self.targets and any(t.get('lexeme_id') in self.targets for t in body.get('targets',[])):
            from corpus import analyze
            from segmentation import decorate_refs
            if self.analysis_cache is None:
                from corpus import WordAnalysisCache
                self.analysis_cache=WordAnalysisCache()
            analyzed=analyze(copy.deepcopy(body),cache=self.analysis_cache);decorate_refs(analyzed)
            targets={(t.get('lexeme_id'),(t.get('segmentation_ref') or {}).get('word')) for t in analyzed.get('targets',[]) if not t.get('segmentation_review')}
        for xid,position in targets:
            if xid in self.targets and self.targets[xid][0]==lid:found.extend(dict(v,word=position) for v in self.targets[xid][1])
        derived=[v for v in self.defs.values() if v.get('source')=='dictionary' and v['language_id']==lid]
        if derived:
            import dictionary_layers,corpus
            if self.analysis_cache is None:self.analysis_cache=corpus.WordAnalysisCache()
            projected=dictionary_layers.project(self.db,corpus.analyze(copy.deepcopy(body),cache=self.analysis_cache),kind,rid,lid,derived,linked_only=True)
            for i,w in enumerate(projected.get('words',[])):
                for layer in w.get('extra_layers',[]):
                    if layer.get('derived') and any(s['values'] for s in layer['segments']):
                        text=dictionary_layers.text(layer);english=dictionary_layers.text(layer,'en')
                        if self.hit(text) or self.hit(english):found.append(dict(field='layer:'+layer['id'],label=layer['name'],text=text,word=i))
        return list({(v['field'],v['text'],v.get('word')):v for v in found}.values())


def search(db,q,*,ids_only=False):
    """Paginate empty searches in SQL; analyze only visible hits in filtered searches."""
    if not db.in_transaction:db.execute('BEGIN')
    from corpus import analyze,QueryMatcher,normalize
    import sentence_search_index
    import record_sources
    import sentence_scope_index
    source=q.get('source','all');lid=q.get('language','all');query=q.get('q','');field=q.get('field','all');mode=q.get('mode','contains');case=q.get('case')=='true'
    if source not in ('all','corpus','independent'):raise ValueError('例句来源无效')
    branches=[];args=[]
    native = record_sources.native(db)
    simple_page=not normalize(query,case) and field!='reduplication'
    if source in ('all','corpus'):
        language = ('e.language_id' if simple_page else 's.language_id') if native else "json_extract(e.body,'$.language_id')"
        value = 'COALESCE(NULLIF('+language+",''),t.language_id)"
        body = 'NULL grammaticality' if native else 'e.body'
        entries = 'corpus_sentence_keys' if native and simple_page else 'entries'
        join = sentence_scope_index.source_join('corpus') if native and not simple_page else ''
        scope = '1=1' if lid=='all' else f'{value}=?'
        branches.append(f"SELECT 'corpus' kind,e.id,{body},{value} language_id,t.language_id owner_language,t.title,e.text_id,e.position,t.rowid ordering,0 source_order FROM {entries} e JOIN texts t ON t.id=e.text_id{join} WHERE {scope}")
        if lid!='all':args.append(lid)
    if source in ('all','independent'):
        title = 'NULL' if native else "COALESCE(NULLIF(json_extract(e.body,'$.source'),''),'独立例句')"
        marked = native and q.get('grammaticality')
        body = ('s.grammaticality' if marked else 'NULL grammaticality') if native else 'e.body'
        join = " JOIN sentence_text_rows s ON s.kind='independent' AND s.owner_id=e.id" if marked else ''
        scope = '1=1' if lid=='all' else 'e.language_id=?'
        branches.append(f"SELECT 'independent' kind,e.id,{body},e.language_id,e.language_id owner_language,{title} title,NULL text_id,NULL position,e.rowid ordering,1 source_order FROM dictionary_examples e{join} WHERE {scope}")
        if lid!='all':args.append(lid)
    sql=' UNION ALL '.join(branches)
    if q.get('text_id'):
        sql='SELECT * FROM ('+sql+') WHERE text_id=?';args.append(q['text_id'])
    import code_switching
    extra,values=code_switching.filter_sql(q,'q.kind','q.id')
    sql='SELECT * FROM ('+sql+') q WHERE 1=1'+extra;args.extend(values)
    import grammaticality
    extra,values=grammaticality.filter_sql(q,'q.body','q.language_id',field='q.grammaticality' if native else None);sql+=extra+(" AND q.kind='independent'" if extra else '');args.extend(values)
    page=max(1,int(q.get('page',1)))
    indexed=None
    if simple_page:
        if ids_only:return sentence_search_index.collected_ids(ids_only,(r[0] for r in db.execute('SELECT id FROM ('+sql+')',args)))
        total=db.execute('SELECT COUNT(*) FROM ('+sql+')',args).fetchone()[0];pages=max(1,(total+19)//20);page=min(page,pages)
        visible=list(db.execute('SELECT * FROM ('+sql+') ORDER BY source_order,ordering,position LIMIT 20 OFFSET ?',[*args,(page-1)*20]))
    elif (indexed := sentence_search_index.search(db,sql,args,field,query,case,mode,page,20,ids_only=ids_only,custom_language=lid,include_original=True)) is not None:
        if ids_only:return indexed
        total=indexed['total'];page=indexed['page'];pages=max(1,(total+19)//20)
        keys=indexed['keys']
        if keys:
            marks=','.join('(?,?)' for _ in keys);pairs=[v for r in keys for v in (r['kind'],r['id'])]
            found={(r['kind'],r['id']):r for r in db.execute('SELECT * FROM ('+sql+') WHERE (kind,id) IN ('+marks+')',args+pairs)}
            visible=[found[(r['kind'],r['id'])] for r in keys]
        else:visible=[]
    else:
        custom=SearchFields(db,lid,q)
        def hit(value):
            a=normalize(value,case);b=normalize(query,case)
            return a==b if mode=='exact' else a.startswith(b) if mode=='prefix' else a.endswith(b) if mode=='suffix' else b in a
        matches=[]
        matcher=QueryMatcher(query,field,mode=mode,case=case)
        for r in gloss_inheritance.iter_rows(db,db.execute('SELECT * FROM ('+sql+') ORDER BY source_order,ordering,position',args),lightweight=True,relational=native):
            # Dictionary values need current independent target references as
            # well as effective gloss text. The lightweight text-only resolver
            # intentionally does not retarget those references.
            b=gloss_inheritance.load(db,r['kind'],r['id'],r['body'],metadata=False,lightweight=not (r['kind']=='independent' and custom.full_references));_,found=matcher(b)
            if field in ('all','original'):found=found or hit(b.get('original',''))
            if not found:found=bool(custom.values(r['kind'],r['id'],b,r['language_id']))
            if found:matches.append(r)
        if ids_only:return sentence_search_index.collected_ids(ids_only,(r['id'] for r in matches))
        total=len(matches);pages=max(1,(total+19)//20);page=min(page,pages);visible=matches[(page-1)*20:page*20]
    items=[]
    for r in gloss_inheritance.iter_rows(db,visible,relational=native):
        b=enrich(db,analyze(record_sources.body(r,mutable=False)),r['kind'],r['id'])
        item={k:r[k] for k in ('kind','id','language_id','owner_language','title','text_id','position')};item['body']=b
        if r['kind']=='independent':
            if native:item['title']=b.get('source') or '独立例句'
            item['lexeme_id']=b['targets'][0]['lexeme_id'] if b.get('targets') else None
        items.append(item)
    stats=indexed['code_summary'] if indexed is not None else code_switching.summary(db,sql,args,None if simple_page else {(r['kind'],r['id']) for r in matches})
    return dict(items=items,total=total,page=page,pages=pages,code_summary=stats)


def inline_slots_save(db,b,lid):
    """Explicit word identities permit insertion, merging and movement without re-matching."""
    import lexicon
    from corpus import analyze,parse,export_entry,normalize_edited_pair
    d=get(db,b['kind'],b['id'])
    if d['owner_language']!=lid:raise ValueError('例句不属于当前语言')
    # Validate concurrency and layer configuration before any mutation.
    mutate(db,'annotation-save',{**b,'cells':[],'discard':[]},lid,snapshot=d)
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
    body=copy.deepcopy({key:value for key,value in d['body'].items() if key!='words'})
    updated=[];changed=[];kept=[];emptied=set()
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
            form,gloss=normalize_edited_pair(form,gloss)
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
    import auto_reduplication
    auto_reduplication.on_save(db,b['kind'],b['id'],body,d['language_id'],previous=d['body'],word_ids=[ids[s] for s in slots])
    if b['kind']=='corpus':
        body['edited']=True;checked,errors=parse(export_entry(body))
        if errors or len(checked)!=1 or any(checked[0][k]!=body[k] for k in ('ipa','translation')) or [(w['form'],w['gloss']) for w in checked[0]['words']]!=[(w['form'],w['gloss']) for w in body['words']]:raise ValueError('文本包含未配对括号或未转义引号，请修正后保存')
    import save_validation
    same_words=False
    native_before=None
    if save_validation.trusted(db) and not changed and slots==[w['id'] for w in d['words']]:
        # The editor carries effective/analysed words. A translation-only edit
        # should not materialise them over the native source or its bindings.
        prior=analyze(copy.deepcopy(d['body']))
        defaults={'grammaticality':''}
        if b['kind']=='independent':defaults['original']=''
        exempt={'notes','translation','edited','warnings'}
        same_words=all(prior.get(k,defaults.get(k))==body.get(k,defaults.get(k)) for k in prior.keys()|body.keys() if k not in exempt)
        if same_words:
            native_before=sentence_rows.one(db,b['kind'],b['id'])
            native={**native_before,'words':[dict(word) for word in native_before['words']]}
            for key in ('notes','translation'):
                if prior.get(key,'')!=body.get(key,''):native[key]=body[key]
            if b['kind']=='corpus':native['edited']=True
            body=native
    gloss_inheritance.clear_metadata(body)
    if b['kind']=='independent':
        from independent_links import write_body
        write_body(db,b['id'],body)
    else:
        sentence_rows.write(db,'corpus',b['id'],body,previous=native_before)
    if b['kind']=='corpus' and not same_words:
        lexicon.sync_entry(db,b['id'],[ids[s] for s in slots],analyzed_body=body,stored_body=body)
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
    if cells:
        fresh=d if same_words and b['kind']=='corpus' else get(db,b['kind'],b['id'])
        mutate(db,'annotation-save',{**b,'revision':fresh['revision'],'before':fresh['cells'],'layers':fresh['layers'],'cells':cells,'discard':[]},lid,snapshot=fresh)
    return {'ok':True}
