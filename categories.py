"""Per-language class catalogue; legacy names remain compatible with old exports."""
import json
import uuid
import word_structure

TABLES=('category_classes',)
def needed(db):return bool(db.execute("SELECT 1 FROM sqlite_master WHERE name='category_classes'").fetchone()) and 'position' not in {r[1] for r in db.execute('PRAGMA table_info(category_classes)')}
TAG_NAMES=dict(register='语域',region='地域',period='使用状态',generation='使用人群',domain='领域',other='其他')

def usage_tags(body):
    yield from body.get('tags',[])
    for s in body.get('senses',[]):yield from s.get('tags',[])
    for v in body.get('variants',[]):yield from v.get('tags',[])
    for u in body.get('usages',[]):
        yield from u.get('tags',[])
        for sense in u.get('senses',[]):yield from sense.get('tags',[])

FORM_NAMES=dict(base='基本形式',allomorph='语素变体',inflected='屈折形式',derived='派生形式',stem='词干形式',spelling='书写变体',pronunciation='读音变体',other='其他形式')

def initialize_forms(db,lid):
    if not db.execute("SELECT 1 FROM category_classes WHERE language_id=? AND kind='_seed' AND name='form-types-v1'",(lid,)).fetchone():
        for name in FORM_NAMES.values():ensure(db,lid,'form',name)
        ensure(db,lid,'_seed','form-types-v1')
    if not db.execute("SELECT 1 FROM category_classes WHERE language_id=? AND kind='_seed' AND name='usage-tag-types-v1'",(lid,)).fetchone():
        for name in TAG_NAMES.values():ensure(db,lid,'usage_tag',name)
        ensure(db,lid,'_seed','usage-tag-types-v1')

def initialize(db):
    db.execute("CREATE TABLE IF NOT EXISTS category_classes(id TEXT PRIMARY KEY,language_id TEXT NOT NULL,kind TEXT NOT NULL,name TEXT NOT NULL,parent_id TEXT,notes TEXT NOT NULL DEFAULT '',revision INTEGER NOT NULL DEFAULT 1)")
    if needed(db):
        db.execute('ALTER TABLE category_classes ADD COLUMN position INTEGER NOT NULL DEFAULT 0')
        for n,r in enumerate(db.execute('SELECT id FROM category_classes ORDER BY name,id').fetchall()):db.execute('UPDATE category_classes SET position=? WHERE id=?',(n,r['id']))
    for r in db.execute('SELECT id FROM languages').fetchall():initialize_forms(db,r['id'])
    for r in db.execute('SELECT id,language_id,body FROM lexemes').fetchall():
        b=json.loads(r['body'])
        register_usages(db,r['language_id'],b)
    for r in db.execute('SELECT language_id,category FROM grammar_tags').fetchall():ensure(db,r['language_id'],'grammar',r['category'])

def listing(db,lid='all'):
    templates={r['id']:json.loads(r['body']) for r in db.execute('SELECT * FROM morph_class_templates')}
    return [{**dict(r),'template':templates.get(r['id'],{'title':'主要部分','slots':[]})} for r in db.execute("SELECT * FROM category_classes WHERE kind!='_seed' AND (?='all' OR language_id=?) ORDER BY position,name,id",(lid,lid))]

def ensure(db,lid,kind,name,parent=None):
    name=name.strip()
    if not name:return None
    if kind=='grammar' and parent is None:
        found=db.execute("SELECT id FROM category_classes WHERE language_id=? AND kind='grammar' AND name=?",(lid,name)).fetchone()
        if found:return found['id']
    old=db.execute('SELECT * FROM category_classes WHERE language_id=? AND kind=? AND name=? AND parent_id IS ?',(lid,kind,name,parent)).fetchone()
    if old:return old['id']
    xid=str(uuid.uuid4());position=db.execute('SELECT COALESCE(MAX(position),-1)+1 FROM category_classes WHERE language_id=? AND kind=? AND parent_id IS ?',(lid,kind,parent)).fetchone()[0];db.execute('INSERT INTO category_classes VALUES(?,?,?,?,?,?,1,?)',(xid,lid,kind,name,parent,'',position));return xid

def register_usages(db,lid,body,strict=False):
    for t in usage_tags(body):
        name=TAG_NAMES.get(t['type'],t['type'])
        if strict and not db.execute("SELECT 1 FROM category_classes WHERE language_id=? AND kind='usage_tag' AND name=?",(lid,name)).fetchone():raise ValueError('使用标签类型不存在，请先在类管理中建立')
        ensure(db,lid,'usage_tag',name)
    for v in body.get('variants',[]):
        if not v.get('kind'):continue
        name=FORM_NAMES.get(v.get('kind','other'),v.get('kind','其他形式'))
        if strict and not db.execute("SELECT 1 FROM category_classes WHERE language_id=? AND kind='form' AND name=?",(lid,name)).fetchone():raise ValueError('形式类型不存在，请先在类管理中建立')
        ensure(db,lid,'form',name)
    for u in body.get('usages',[]):
        root=ensure(db,lid,'pos',u.get('pos',''))
        if u.get('subclass') and not root and strict:raise ValueError('请先指定词类，再指定子类')
        if root:ensure(db,lid,'pos',u.get('subclass',''),root)

def used(db,c):
    if c['kind']=='usage_tag':return any(TAG_NAMES.get(t['type'],t['type'])==c['name'] for r in db.execute('SELECT body FROM lexemes WHERE language_id=? UNION ALL SELECT body FROM morphemes WHERE language_id=?',(c['language_id'],c['language_id'])) for t in usage_tags(json.loads(r['body'])))
    if c['kind']=='morph':return any(m.get('class_id')==c['id'] for r in db.execute('SELECT body FROM dictionary_targets WHERE language_id=?',(c['language_id'],)) for m in json.loads(r['body']).get('word_structure',{}).get('memberships',[]))
    if c['kind']=='form':return any(FORM_NAMES.get(v.get('kind','other'),v.get('kind'))==c['name'] for r in db.execute('SELECT body FROM lexemes WHERE language_id=? UNION ALL SELECT body FROM morphemes WHERE language_id=?',(c['language_id'],c['language_id'])) for v in json.loads(r['body']).get('variants',[]))
    if c['kind']=='grammar':return bool(db.execute('SELECT 1 FROM grammar_tags WHERE language_id=? AND category=?',(c['language_id'],c['name'])).fetchone())
    parent=db.execute('SELECT name FROM category_classes WHERE id=?',(c['parent_id'],)).fetchone() if c['parent_id'] else None
    for r in db.execute('SELECT body FROM dictionary_targets WHERE language_id=?',(c['language_id'],)):
        for u in json.loads(r['body']).get('usages',[]):
            if (u.get('pos')==parent['name'] and u.get('subclass')==c['name']) if parent else u.get('pos')==c['name']:return True
    return False

def mutate(db,action,b,lid):
    import class_changes
    previous=class_changes.before(db,b,lid)
    return class_changes.finish(db,b,_mutate(db,action,b,lid),previous)

def _mutate(db,action,b,lid):
    if action=='class-order':
        import class_changes
        if b.get('kind') not in ('pos','grammar','form','morph','usage_tag'):raise ValueError('分类类型无效')
        return class_changes.order(db,'category_classes',lid,b,b['kind'])
    old=db.execute('SELECT * FROM category_classes WHERE id=?',(b.get('id'),)).fetchone()
    if b.get('id') and (not old or old['language_id']!=lid or old['revision']!=b.get('revision')):raise ValueError('分类已变化，请重新打开')
    if action=='class-delete':
        if not old:raise ValueError('分类不存在')
        deleted=[dict(old),*[dict(r) for r in db.execute('SELECT * FROM category_classes WHERE parent_id=?',(old['id'],))]]
        ids={r['id'] for r in deleted};names={r['name'] for r in deleted}
        parent=db.execute('SELECT name FROM category_classes WHERE id=?',(old['parent_id'],)).fetchone() if old['parent_id'] else None
        if old['kind']=='grammar':db.executemany("UPDATE grammar_tags SET category='',revision=revision+1 WHERE language_id=? AND category=?",[(lid,n) for n in names])
        for table in ('lexemes','morphemes'):
            for r in db.execute('SELECT id,body FROM '+table+' WHERE language_id=?',(lid,)).fetchall():
                body=json.loads(r['body']);encoded=json.dumps(body,ensure_ascii=False)
                if old['kind']=='pos':
                    for u in body.get('usages',[]):
                        if parent and u.get('pos')==parent['name'] and u.get('subclass') in names:u['subclass']=''
                        elif not parent and u.get('pos')==old['name']:u['pos']='';u['subclass']=''
                elif old['kind']=='form':
                    for v in body.get('variants',[]):
                        if FORM_NAMES.get(v.get('kind'),v.get('kind')) in names:v['kind']=''
                elif old['kind']=='morph':
                    ws=body.get('word_structure',{})
                    for m in ws.get('memberships',[]):
                        if m['class_id'] in ids:m['class_id']=''
                elif old['kind']=='usage_tag':
                    owners=[body,*body.get('variants',[]),*body.get('senses',[])]
                    for u in body.get('usages',[]):owners.extend([u,*u.get('senses',[])])
                    for owner in owners:
                        if 'tags' in owner:owner['tags']=[t for t in owner['tags'] if TAG_NAMES.get(t['type'],t['type']) not in names]
                after=json.dumps(body,ensure_ascii=False)
                if after!=encoded:db.execute('UPDATE '+table+' SET body=?,revision=revision+1 WHERE id=?',(after,r['id']))
        for cid in ids:
            db.execute('DELETE FROM morph_class_templates WHERE id=?',(cid,));db.execute('DELETE FROM category_classes WHERE id=?',(cid,))
        return {'ok':True,'deleted_classes':deleted}
    kind=b.get('kind');name=b.get('name','');notes=b.get('notes','');parent_id=b.get('parent_id') or None
    if kind not in ('pos','grammar','form','morph','usage_tag') or not isinstance(name,str) or not name.strip() or not isinstance(notes,str):raise ValueError('请填写有效的类名、类型和备注')
    name=name.strip()
    parent=db.execute('SELECT * FROM category_classes WHERE id=?',(parent_id,)).fetchone() if parent_id else None
    if parent_id and (not parent or parent['language_id']!=lid or parent['kind']!=kind or parent['id']==b.get('id') or parent['parent_id']):raise ValueError('请选择同语言、同类型的顶层类作为父类')
    if old and (old['kind']!=kind or old['parent_id']!=parent_id):raise ValueError('已有类的类型和父类不能直接修改，请新建类后调整引用')
    peers=listing(db,lid)
    if any(c['id']!=b.get('id') and c['kind']==kind and c['name'].casefold()==name.casefold() and (kind in ('grammar','form','usage_tag') or c['parent_id']==parent_id) for c in peers):raise ValueError('同一范围已有这个类名')
    xid=old['id'] if old else str(uuid.uuid4())
    position=old['position'] if old else b.get('position',db.execute('SELECT COALESCE(MAX(position),-1)+1 FROM category_classes WHERE language_id=? AND kind=? AND parent_id IS ?',(lid,kind,parent_id)).fetchone()[0])
    if type(position) is not int:raise ValueError('分类顺序无效')
    db.execute('INSERT INTO category_classes VALUES(?,?,?,?,?,?,1,?) ON CONFLICT(id) DO UPDATE SET name=excluded.name,notes=excluded.notes,revision=category_classes.revision+1',(xid,lid,kind,name,parent_id,notes,position))
    if kind=='morph' and ('template' in b or not old):
        value=word_structure.template(b.get('template',{}))
        db.execute('INSERT INTO morph_class_templates VALUES(?,?) ON CONFLICT(id) DO UPDATE SET body=excluded.body',(xid,json.dumps(value,ensure_ascii=False)))
    if old and old['name']!=name:
        if kind=='grammar':db.execute('UPDATE grammar_tags SET category=?,revision=revision+1 WHERE language_id=? AND category=?',(name,lid,old['name']))
        elif kind!='morph':
            for table in ('lexemes','morphemes'):
                for r in db.execute('SELECT id,body FROM '+table+' WHERE language_id=?',(lid,)).fetchall():
                    body=json.loads(r['body']);changed=False
                    if kind=='usage_tag':
                        for t in usage_tags(body):
                            if TAG_NAMES.get(t['type'],t['type'])==old['name']:t['type']=name;changed=True
                    if kind=='form':
                        for v in body.get('variants',[]):
                            if FORM_NAMES.get(v.get('kind','other'),v.get('kind'))==old['name']:v['kind']=name;changed=True
                    for u in body.get('usages',[]):
                        if kind in ('form','usage_tag'):continue
                        if not parent_id and u.get('pos')==old['name']:u['pos']=name;changed=True
                        elif parent_id and u.get('pos')==parent['name'] and u.get('subclass')==old['name']:u['subclass']=name;changed=True
                    if changed:db.execute('UPDATE '+table+' SET body=?,revision=revision+1 WHERE id=?',(json.dumps(body,ensure_ascii=False),r['id']))
    return {'ok':True,'id':xid}

def import_bundle(db,bundle,mapping):
    rows=bundle.get('category_classes',[]);remap={}
    for r in sorted(rows,key=lambda r:bool(r.get('parent_id'))):
        parent=remap.get(r.get('parent_id'))
        if r.get('parent_id') and not parent:raise ValueError('分类缺少父类')
        lid=mapping[r['language_id']]
        existing=next((c for c in listing(db,lid) if c['kind']==r['kind'] and c['name']==r['name'] and c['parent_id']==parent),None)
        if existing and r['kind']=='morph':
            # Do not silently adopt a different template merely because names match.
            def comparable(t):return {'title':t.get('title','主要部分'),'slots':[{'label':s.get('label',''),'notes':s.get('notes','')} for s in t.get('slots',[])]}
            if comparable(existing['template'])!=comparable(r.get('template',{})) or existing['notes']!=r.get('notes',''):
                name=r['name'];n=2
                while any(c['kind']=='morph' and c['name']==f'{name}（导入 {n}）' and c['parent_id']==parent for c in listing(db,lid)):n+=1
                r={**r,'name':f'{name}（导入 {n}）'};existing=None
        if existing:remap[r['id']]=existing['id']
        else:remap[r['id']]=mutate(db,'class-save',{**r,'id':None,'parent_id':parent},lid)['id']
    return remap
