"""Shared writing types and dictionary-owned examples."""
import json
import uuid
import font_catalog
import annotations
import morphology
import segmentation
import gloss_inheritance
import display_spacing
import independent_links
import sentence_rows

TABLES=('writing_types','dictionary_examples')+independent_links.TABLES

def initialize(db):
    db.executescript('''CREATE TABLE IF NOT EXISTS writing_types(id TEXT PRIMARY KEY,language_id TEXT NOT NULL,name TEXT NOT NULL,font TEXT NOT NULL,position INTEGER NOT NULL DEFAULT 0,revision INTEGER NOT NULL DEFAULT 1);
    CREATE TABLE IF NOT EXISTS dictionary_examples(id TEXT PRIMARY KEY,language_id TEXT NOT NULL,body TEXT NOT NULL,revision INTEGER NOT NULL DEFAULT 1);
    CREATE INDEX IF NOT EXISTS writing_language ON writing_types(language_id);
    CREATE INDEX IF NOT EXISTS examples_language ON dictionary_examples(language_id);''')
    display_spacing.initialize(db, 'writing_types')

def types(db,lid,catalog_only=False):
    import record_sources
    items=[dict(r) for r in db.execute('SELECT * FROM writing_types WHERE language_id=? ORDER BY position,name,id',(lid,))]
    legacy={}
    if catalog_only:return dict(items=items,legacy=[])
    rows=record_sources.with_bodies(db,'lexemes',db.execute('SELECT id FROM lexemes WHERE language_id=?',(lid,)))
    for row in rows:
        for o in row['body'].get('orthographies',[]):
            if not o.get('type_id'):
                group=legacy.setdefault(o['label'],dict(name=o['label'],fonts=[],count=0))
                group['count']+=1
                if o['font'] not in group['fonts']:group['fonts'].append(o['font'])
    return dict(items=items,legacy=list(legacy.values()))

def resolve(db,body,catalog=None):
    positions={}
    for o in body.get('orthographies',[]):
        if o.get('type_id'):
            row=catalog.get(o['type_id']) if catalog is not None else db.execute('SELECT * FROM writing_types WHERE id=?',(o['type_id'],)).fetchone()
            if row:
                o.update(label=row['name'],font=row['font'],**display_spacing.values(dict(row)));positions[o['id']]=row['position']
    body['orthographies']=sorted(body.get('orthographies',[]),key=lambda o:positions.get(o['id'],10001))
    return body

def validate(db,targets=None):
    annotations.validate(db)
    if targets is None:targets={r['id']:{**dict(r),'body':json.loads(r['body'])} for r in db.execute('SELECT * FROM dictionary_targets')}
    for x in targets.values():validate_writings(db,x)
    independent_links.validate(db)


def validate_writings(db,entry):
    for writing in entry['body'].get('orthographies',[]):
        if writing.get('type_id'):
            row=db.execute('SELECT language_id FROM writing_types WHERE id=?',(writing['type_id'],)).fetchone()
            if not row or row[0]!=entry['language_id']:
                raise ValueError('书写类型仍被词条引用，不能删除或撤销；请先调整引用')


def examples(db,xid):
    if not db.in_transaction:db.execute('BEGIN')
    row=independent_links.identity(db,xid)
    if not row:raise ValueError('词条不存在')
    import evidence_owners
    scope,args=evidence_owners.independent_scope(db,xid,row['language_id'])
    result=[]
    cursor=db.execute('SELECT e.id,e.language_id,e.revision'+scope+' ORDER BY e.rowid',args)
    while batch:=cursor.fetchmany(100):result.extend(_example_cards(db,batch))
    return result


def _example_cards(db,rows):
    bodies=annotations.evidence_cards(db,'independent',rows)
    return [{**dict(row),'body':bodies[row['id']]} for row in rows]


def example_rows(db,entry,ids):
    if not ids:return []
    marks=','.join('?' for _ in ids)
    rows={row['id']:row for row in db.execute(f"""SELECT e.id,e.language_id,e.revision
        FROM dictionary_examples e WHERE e.id IN ({marks}) AND e.language_id=?
        AND EXISTS(SELECT 1 FROM independent_links l WHERE l.example_id=e.id AND l.lexeme_id=?)""",
        (*ids,entry['language_id'],entry['id']))}
    return _example_cards(db,[rows[xid] for xid in ids if xid in rows])


def example_page(db,xid,page=1,form_id='all',focus=None):
    if not db.in_transaction:db.execute('BEGIN')
    row=independent_links.identity(db,xid)
    if not row:raise ValueError('词条不存在')
    import evidence_owners
    scope,args=evidence_owners.independent_scope(db,xid,row['language_id'],form_id=form_id)
    total=db.execute('SELECT count(*)'+scope,args).fetchone()[0]
    pages=max(1,(total+19)//20)
    found=None
    if focus is not None:
        target=db.execute('SELECT e.rowid'+scope+' AND e.id=?',args+[focus]).fetchone()
        found=target is not None
        if found:page=1+db.execute('SELECT count(*)'+scope+' AND e.rowid<?',args+[target[0]]).fetchone()[0]//20
    page=max(1,min(int(page),pages))
    # Sort only narrow identities; expand annotation and media data for this page.
    rows=db.execute('SELECT e.id,e.language_id,e.revision'+scope+' ORDER BY e.rowid LIMIT 20 OFFSET ?',args+[(page-1)*20]).fetchall()
    items=_example_cards(db,rows)
    return dict(items=items,total=total,page=page,pages=pages,focus_found=found)

def mutate(db,action,b,lid,*,sentence_edit=False):
    import lexicon
    table='writing_types' if action.startswith('writing-') else 'dictionary_examples'
    columns='*' if table=='writing_types' else 'id,language_id,revision'
    old=db.execute('SELECT '+columns+' FROM '+table+' WHERE id=?',(b.get('id'),)).fetchone()
    if b.get('id') and (not old or old['revision']!=b.get('revision')):raise ValueError('内容已变化，请重新打开')
    xid=b.get('id') or str(uuid.uuid4())
    if action=='writing-delete':
        if b.get('confirmed') is not True:raise ValueError('请确认删除书写类型')
        replacement=b.get('replacement_id')
        if replacement:
            target=db.execute('SELECT * FROM writing_types WHERE id=? AND language_id=?',(replacement,lid)).fetchone()
            if not target or replacement==xid:raise ValueError('请选择同语言的其他书写类型')
            for x in db.execute('SELECT * FROM dictionary_targets WHERE language_id=?',(lid,)).fetchall():
                body=json.loads(x['body']);changed=False
                for o in body.get('orthographies',[]):
                    if o.get('type_id')==xid:o.update(type_id=replacement,label=target['name'],font=target['font']);changed=True
                for w in morphology.word_structure.writing_rows(body):
                    if w['type_id']==xid:w['type_id']=replacement;changed=True
                if changed:
                    from dictionary_targets import write_body
                    write_body(db,x,body)
        if replacement:
            for p in db.execute('SELECT id,metadata FROM timeline_speakers').fetchall():
                m=json.loads(p['metadata']);changed=False
                for f in m.get('fields',[]):
                    if f.get('type_id')==xid:f['type_id']=replacement;changed=True
                if changed:db.execute('UPDATE timeline_speakers SET metadata=?,revision=revision+1 WHERE id=?',(json.dumps(m,ensure_ascii=False),p['id']))
        import grammar_survey
        grammar_survey.writing_replace(db,xid,replacement)
        import fieldwork_notes
        fieldwork_notes.writing_replace(db,xid,replacement)
        for m in db.execute('SELECT id,body FROM morphemes_documents WHERE language_id=?',(lid,)).fetchall():
            data=json.loads(m['body']);changed=False
            for w in data.get('writings',[]):
                if w['type_id']==xid:
                    if not replacement:raise ValueError('语素仍使用此书写类型，请先选择替换类型或清除语素书写')
                    w['type_id']=replacement;changed=True
            if changed:
                morphology.word_structure.writings(data)
                import dictionary_rows
                dictionary_rows.write(db,'morpheme',m['id'],data)
        if replacement:db.execute("UPDATE annotation_layers SET dictionary_field=?,revision=revision+1 WHERE source='dictionary' AND dictionary_field=? AND language_id=?",('writing:'+replacement,'writing:'+xid,lid))
        import quick_edit
        quick_edit.writing_replace(db,xid,replacement)
        db.execute('DELETE FROM writing_types WHERE id=?',(xid,));validate(db)
        import collaborators
        collaborators.validate(db)
        return {'ok':True}
    if action=='writing-save':
        name=lexicon.text(b.get('name','')).strip();font=b.get('font','Junicode')
        if not name or not font_catalog.valid_font(font):raise ValueError('请填写名称并选择字体')
        position=b.get('position',0)
        if not isinstance(position,int) or not 0<=position<=10000:raise ValueError('显示顺序须为 0–10000 的整数')
        if db.execute('SELECT 1 FROM writing_types WHERE language_id=? AND name=? AND id<>?',(lid,name,xid)).fetchone():raise ValueError('该书写类型名称已存在')
        spacing=display_spacing.values(b,old)
        db.execute('INSERT INTO writing_types(id,language_id,name,font,position,revision,space_before,space_after) VALUES(?,?,?,?,?,1,?,?) ON CONFLICT(id) DO UPDATE SET name=excluded.name,font=excluded.font,position=excluded.position,space_before=excluded.space_before,space_after=excluded.space_after,revision=writing_types.revision+1',(xid,lid,name,font,position,spacing['space_before'],spacing['space_after']))
        if b.get('adopt'):
            for x in db.execute('SELECT * FROM dictionary_targets WHERE language_id=?',(lid,)).fetchall():
                body=json.loads(x['body']);changed=False
                for o in body.get('orthographies',[]):
                    if not o.get('type_id') and o['label']==name:o.update(type_id=xid,font=font);changed=True
                if changed:
                    from dictionary_targets import write_body
                    write_body(db,x,body)
        return dict(db.execute('SELECT * FROM writing_types WHERE id=?',(xid,)).fetchone())
    if action=='example-delete':
        if b.get('confirmed') is not True:raise ValueError('请确认删除独立例句')
        db.execute('DELETE FROM dictionary_examples WHERE id=?',(xid,));return {'ok':True}
    if action=='example-save':
        data=b.get('body',{})
        if old:gloss_inheritance.check_revision(db,'independent',xid,b)
        if not isinstance(data,dict):raise ValueError('例句格式错误')
        result={k:lexicon.text(data.get(k,'')) for k in ('original','ipa','translation','source','notes')}
        words=data.get('words',[])
        if not isinstance(words,list):raise ValueError('标注格式错误')
        result['words']=[dict(form=lexicon.text(w['form']),gloss=lexicon.text(w['gloss'])) for w in words]
        from corpus import compact_edited_pairs
        previous=gloss_inheritance.load(db,'independent',xid,sentence_rows.one(db,'independent',xid)) if old else {}
        import grammaticality
        grammaticality.copy_value(previous,result,data)
        result['words'],positions=compact_edited_pairs(result['words'],previous.get('words',[]))
        segmentation.preserve(previous if old else data,result)
        if not old:
            import reduplication
            reduplication.fork(result)
        annotations.independent_ids(previous,result)
        targets=data['targets'] if 'targets' in data else independent_links.targets(db,xid) if old else []
        if not isinstance(targets,list):raise ValueError('词条例证关联格式无效')
        result['targets']=[];seen=set()
        for t in targets:
            if not isinstance(t,dict):raise ValueError('词条引用格式错误')
            x=independent_links.identity(db,t['lexeme_id'])
            if not x or x['language_id']!=lid:raise ValueError('例句只能关联同语言词条')
            form_id=t.get('form_id') or None
            features=morphology.check_features(db,lid,t.get('features',[]))
            ref=t.get('segmentation_ref')
            if ref is not None:
                segmentation.validate_ref(ref);ref=dict(ref)
                if not ref.get('detached'):
                    if ref['word'] in positions:ref['word']=positions[ref['word']]
                    else:ref['detached']=True
            key=(x['id'],t.get('usage_id') or None,t.get('sense_id') or None,form_id,json.dumps(ref,sort_keys=True))
            if key in seen:raise ValueError('例句引用重复')
            seen.add(key);independent_links.validate_selection(db,x['id'],key[1],key[2],form_id)
            result['targets'].append(dict(lexeme_id=key[0],usage_id=key[1],sense_id=key[2],form_id=form_id,features=features))
            if ref:result['targets'][-1]['segmentation_ref']=ref
            if t.get('gloss_binding_id'):
                binding=db.execute('SELECT owner_kind,owner_id FROM gloss_bindings WHERE id=?',(t['gloss_binding_id'],)).fetchone()
                if binding and binding['owner_kind']=='independent' and binding['owner_id']==xid:result['targets'][-1]['gloss_binding_id']=t['gloss_binding_id']
            if t.get('gloss_mode') in ('inherit','override'):result['targets'][-1]['gloss_mode']=t['gloss_mode']
            if isinstance(t.get('notes'),str):result['targets'][-1]['notes']=t['notes']
            if t.get('component_ref'):
                import component_links
                result['targets'][-1]['component_ref']=component_links.validate(t['component_ref'])
            if 'notes' in t:result['targets'][-1]['notes']=lexicon.text(t['notes'])
            if t.get('review_reason'):result['targets'][-1]['review_reason']=lexicon.text(t['review_reason'])
        if sentence_edit:
            import auto_reduplication
            auto_reduplication.on_save(db,'independent',xid,result,lid,previous=previous)
        if result.get('reduplications'):
            from corpus import analyze
            import reduplication
            analyze(result);reduplication.check_relations(result)
        independent_links.write_body(db,xid,result,language=lid)
        import example_numbering
        number=example_numbering.assign(db,lid,xid)
        return dict(id=xid,language_id=lid,body=result,library_number=number,revision=(old['revision'] if old else 0)+1)
    raise ValueError('未知词典管理操作')
