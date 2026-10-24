"""Previewed class edits. Meaning/form identities stay intact throughout a batch."""
import copy
import hashlib
import json
import uuid
import categories
import dictionary_organization
import lexicon
import long_tasks
import morphology

FIELDS=dict(pos='词类及子类',semantic_classes='语义分类',morph_classes='形态类',
            entry_type='条目类型',tags='整个词条的使用标签',features='条目固有语法特征')


def combine(old, value, mode):
    if mode=='replace':return copy.deepcopy(value)
    if mode=='remove':return [v for v in old if v not in value]
    return old+[copy.deepcopy(v) for v in value if v not in old]


def combine_tags(old,value,mode):
    if mode=='replace':return copy.deepcopy(value)
    key=lambda t:(categories.TAG_NAMES.get(t['type'],t['type']),t['value'])
    if mode=='remove':return [t for t in old if key(t) not in {key(v) for v in value}]
    out=list(old);known={key(t) for t in old}
    for tag in value:
        if key(tag) not in known:out.append(copy.deepcopy(tag));known.add(key(tag))
    return out


def plan(db,lid,b):
    if lid=='all':raise ValueError('请先选择一种语言')
    items=b.get('items');operations=b.get('operations')
    if not isinstance(items,list) or not 1<=len(items)<=2000:raise ValueError('请选择1—2000个词条')
    if not isinstance(operations,list) or not 1<=len(operations)<=len(FIELDS):raise ValueError('请选择批量操作项目')
    classes={r['id']:r for r in categories.listing(db,lid)};seen=set();ops=[]
    for op in operations:
        if not isinstance(op,dict):raise ValueError('批量操作无效')
        key=op.get('field');mode=op.get('mode','replace');value=op.get('value')
        if key not in FIELDS or key in seen or mode not in ('add','remove','replace'):raise ValueError('批量操作字段或方式无效')
        seen.add(key)
        if key=='pos':
            if mode!='replace' or not isinstance(value,dict):raise ValueError('请选择词类')
            if not isinstance(value.get('pos'),str) or not isinstance(value.get('subclass',''),str):raise ValueError('词类选择无效')
            cls=classes.get(value.get('pos'));sub=classes.get(value.get('subclass'))
            if not cls or cls['kind']!='pos' or cls['parent_id']:raise ValueError('请选择本语言的顶层词类')
            if value.get('subclass') and (not sub or sub['parent_id']!=cls['id']):raise ValueError('子类不属于所选词类')
            value=dict(pos=cls['name'],subclass=sub['name'] if sub else '')
        elif key=='semantic_classes':value=dictionary_organization.validate_ids(db,lid,value)
        elif key=='morph_classes':
            if not isinstance(value,list) or any(not isinstance(v,str) for v in value) or len(set(value))!=len(value) or any(v not in classes or classes[v]['kind']!='morph' for v in value):raise ValueError('请选择本语言的形态类')
        elif key=='entry_type':
            if mode!='replace':raise ValueError('条目类型只能指定一个值')
            value=morphology.choice(value,morphology.ENTRY_TYPES,'条目类型')
        elif key=='tags':
            value=lexicon.tags(value);categories.register_usages(db,lid,dict(tags=value),strict=True)
        elif key=='features':
            value=morphology.ids(value);morphology.check_features(db,lid,value)
        ops.append(dict(field=key,mode=mode,value=value))
    planned=[];seen=set()
    for item in long_tasks.steps(items):
        if not isinstance(item,dict) or not isinstance(item.get('id'),str) or item.get('id') in seen:raise ValueError('词条选择重复或无效')
        row=db.execute('SELECT * FROM lexemes WHERE id=? AND language_id=?',(item.get('id'),lid)).fetchone()
        if not row or row['revision']!=item.get('revision'):raise ValueError('所选词条已改变，请清空选择并重新勾选')
        seen.add(row['id']);before=json.loads(row['body']);after=copy.deepcopy(before);conflicts=[]
        for op in ops:
            key,mode,value=op['field'],op['mode'],op['value']
            if key=='pos':
                usages=after.setdefault('usages',[])
                old=[dict(pos=u.get('pos',''),subclass=u.get('subclass','')) for u in usages]
                if any((v['pos'] or v['subclass']) and v!=value for v in old):conflicts.append(FIELDS[key])
                if not usages:usages.append(dict(id=str(uuid.uuid4()),pos='',subclass='',senses=[],tags=[],features=[],notes=''))
                for u in usages:u.update(value)
            elif key=='morph_classes':
                structure=after.setdefault('word_structure',dict(analyses=[],memberships=[]));old=structure.setdefault('memberships',[])
                if mode=='replace' and any(m['class_id'] not in value for m in old):conflicts.append(FIELDS[key]+'（含主要部分）')
                kept=[m for m in old if m['class_id'] not in value] if mode=='remove' else [m for m in old if m['class_id'] in value] if mode=='replace' else list(old)
                if mode!='remove':
                    for cid in value:
                        if not any(m['class_id']==cid for m in kept):kept.append(dict(id=str(uuid.uuid4()),class_id=cid,usage_id='',title='',notes='',parts=[]))
                structure['memberships']=kept
            else:
                old=after.get(key,'unspecified' if key=='entry_type' else [])
                new=value if key=='entry_type' else combine_tags(old,value,mode) if key=='tags' else combine(old,value,mode)
                if mode=='replace' and old and old!='unspecified' and old!=new:conflicts.append(FIELDS[key])
                after[key]=new
        planned.append(dict(id=row['id'],revision=row['revision'],headword=row['headword'],before=before,after=after,conflicts=conflicts))
    # Generated identities do not participate in the confirmation fingerprint.
    token=hashlib.sha256(json.dumps(dict(language=lid,items=[dict(id=p['id'],revision=p['revision'],body=p['before']) for p in planned],operations=ops),ensure_ascii=False,sort_keys=True).encode()).hexdigest()
    return planned,token


def preview(db,lid,b):
    rows,token=plan(db,lid,b)
    return dict(token=token,total=len(rows),changed=sum(p['before']!=p['after'] for p in rows),
                conflicts=[dict(id=p['id'],headword=p['headword'],fields=p['conflicts']) for p in rows if p['conflicts']])


def apply(db,lid,b):
    if not db.in_transaction:db.execute('BEGIN IMMEDIATE')
    rows,token=plan(db,lid,b)
    if b.get('token')!=token:raise ValueError('批量预览已失效，请重新预览')
    if any(p['conflicts'] for p in rows) and b.get('overwrite') is not True:raise ValueError('部分词条已有内容，请检查预览后确认覆盖，或放弃操作')
    count=0
    for p in long_tasks.steps(rows):
        if p['before']==p['after']:continue
        db.execute('UPDATE lexemes SET body=?,revision=revision+1 WHERE id=?',(json.dumps(p['after'],ensure_ascii=False),p['id']));count+=1
    lexicon.validate_links(db)
    return dict(ok=True,changed=count)
