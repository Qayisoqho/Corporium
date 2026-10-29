"""Dictionary morphology: explicit class membership, principal parts and analyses."""
import copy
import json
import uuid

TABLES=('morph_class_templates',)

def initialize(db):
    db.execute("CREATE TABLE IF NOT EXISTS morph_class_templates(id TEXT PRIMARY KEY,body TEXT NOT NULL)")

def obj(v):
    if not isinstance(v,dict):raise ValueError('形态分析须为对象')
    return v

def rows(v):
    if not isinstance(v,list) or len(v)>500 or any(not isinstance(x,dict) for x in v):raise ValueError('形态分析列表格式错误或条目过多')
    return v

def text(v):
    if not isinstance(v,str):raise ValueError('形态分析字段须为文本')
    return v

def fields(v,names):return {k:text(v.get(k,'')) for k in names.split()}

def identity(v,seen):
    value=text(v.get('id') or str(uuid.uuid4()))
    if value in seen:raise ValueError('形态分析中存在重复标识')
    seen.add(value);return value

def features(v):
    v=v.get('features',[])
    if not isinstance(v,list) or any(not isinstance(x,str) or not x for x in v):raise ValueError('请选择语法标签')
    return list(dict.fromkeys(v))

def writings(v):
    result=[];seen=set()
    for w in rows(v.get('writings',[])):
        w=fields(w,'type_id text')
        if not w['type_id'] or not w['text'].strip() or w['type_id'] in seen:raise ValueError('请填写书写内容，且同一组分不能重复使用书写类型')
        seen.add(w['type_id']);result.append(w)
    return result

def template(v):
    v=obj(v);seen=set();result={'title':text(v.get('title','主要部分')),'slots':[]}
    for s in rows(v.get('slots',[])):
        s={**fields(s,'label notes'),'id':identity(s,seen)}
        if not s['label'].strip():raise ValueError('主要部分模板各项须有名称')
        result['slots'].append(s)
    return result

def normalize(v):
    from manual_status import clean
    v=clean(obj(v));seen=set();result={'memberships':[],'analyses':[]}
    for m in rows(v.get('memberships',[])):
        if not has_content(m):continue
        out={**fields(m,'class_id usage_id title notes'),'id':identity(m,seen),'parts':[]}
        for p in rows(m.get('parts',[])):
            out['parts'].append({**fields(p,'label form variant_id notes'),'id':identity(p,seen),'writings':writings(p),'features':features(p)})
        result['memberships'].append(out)
    for a in rows(v.get('analyses',[])):
        if not has_content(a):continue
        out={**fields(a,'title notes source'),'id':identity(a,seen),'level':a.get('level','unspecified'),'default':a.get('default',False),'components':[]}
        if out['level'] not in ('synchronic','diachronic','unspecified') or type(out['default']) is not bool:raise ValueError('请选择分析层面')
        for c in rows(a.get('components',[])):
            if not has_content(c):continue
            item={**fields(c,'parent_id role form gloss lexeme_id usage_id sense_id form_id notes source'),'id':identity(c,seen),'writings':writings(c),'features':features(c),'segments':c.get('segments',[])}
            from homophones import readings
            pronunciation=readings(c.get('readings',[]))
            if pronunciation:item['readings']=pronunciation
            if not isinstance(item['segments'],list) or any(not isinstance(s,str) or not s.strip() for s in item['segments']):raise ValueError('不连续片段须逐项填写')
            if not any((item['form'].strip(),item['writings'],item['segments'],item['lexeme_id'])):raise ValueError('请填写组分形式或关联词条')
            out['components'].append(item)
        parents={c['id']:c['parent_id'] for c in out['components']}
        for cid in parents:
            visited=set();p=cid
            while p:
                if p not in parents:raise ValueError('组分的上级分组不存在')
                if p in visited:raise ValueError('组分分组不能形成循环')
                visited.add(p);p=parents[p]
                if len(visited)>32:raise ValueError('组分层级不能超过 32 层')
        result['analyses'].append(out)
    if sum(a['default'] for a in result['analyses'])>1:raise ValueError('只能选择一份默认分析')
    if result['analyses'] and not any(a['default'] for a in result['analyses']):result['analyses'][0]['default']=True
    return result

def has_content(value):
    if isinstance(value,dict):
        return any(has_content(v) for k,v in value.items() if k not in ('id','default') and not (k=='level' and v=='unspecified'))
    if isinstance(value,list):return any(has_content(v) for v in value)
    return bool(value.strip()) if isinstance(value,str) else bool(value)

def writing_rows(body):
    data=body.get('word_structure',{})
    for m in data.get('memberships',[]):
        for p in m.get('parts',[]):yield from p.get('writings',[])
    for a in data.get('analyses',[]):
        for c in a.get('components',[]):yield from c.get('writings',[])

def references(body):
    return {c['lexeme_id'] for a in body.get('word_structure',{}).get('analyses',[]) for c in a.get('components',[]) if c.get('lexeme_id')}

def validate(db,entries):
    import morphology,lexicon
    classes={r['id']:dict(r) for r in db.execute("SELECT * FROM category_classes WHERE kind='morph' ")}
    types={r['id']:r['language_id'] for r in db.execute('SELECT id,language_id FROM writing_types')}
    edges={}
    for xid,x in entries.items():
        b=x['body'];data=normalize(b.get('word_structure',{}));lid=x['language_id'];members=set()
        for w in writing_rows(b):
            if types.get(w['type_id'])!=lid:raise ValueError('形态分析引用的书写类型不存在或语言不一致，请先调整引用')
        for m in data['memberships']:
            cls=classes.get(m['class_id'])
            if m['class_id'] and (not cls or cls['language_id']!=lid):raise ValueError('形态类不存在或不属于本语言，请先调整引用')
            key=(m['class_id'],m['usage_id'])
            if m['class_id'] and key in members:raise ValueError('同一词类用法不能重复关联相同形态类')
            members.add(key);lexicon.selection(b,m['usage_id'],None)
            for p in m['parts']:
                morphology.form_selection(b,p['variant_id']);morphology.check_features(db,lid,p['features'])
        for a in data['analyses']:
            for c in a['components']:
                morphology.check_features(db,lid,c['features'])
                if c['lexeme_id']:
                    target=entries.get(c['lexeme_id'])
                    if not target or target['language_id']!=lid:raise ValueError('组分关联词条不存在或语言不一致，请先解除关联')
                    lexicon.selection(target['body'],c['usage_id'],c['sense_id']);morphology.form_selection(target['body'],c['form_id'])
                    import paradigms
                    paradigms.validate_selection(target['body'],c['usage_id'],c['sense_id'],c['form_id'])
                elif c['usage_id'] or c['sense_id'] or c['form_id']:raise ValueError('请先关联组分的词条')
        edges[xid]=references(b)
    # No recursive containment, even across dictionary entries.
    done=set()
    for start in edges:
        active=set();stack=[(start,False)]
        while stack:
            node,finish=stack.pop()
            if finish:active.remove(node);done.add(node);continue
            if node in active:raise ValueError('词条的组分关联不能形成循环包含')
            if node in done:continue
            active.add(node);stack.append((node,True));stack.extend((n,False) for n in edges.get(node,[]))
    for r in db.execute('SELECT id,body FROM morph_class_templates'):
        if r['id'] not in classes:raise ValueError('主要部分模板缺少所属形态类')
        template(json.loads(r['body']))

def remap(data,owner,xmap,submap,classmap,typemap,tagmap):
    data=copy.deepcopy(data)
    def sub(x,key):return submap[(x,key)] if key else ''
    def common(p):
        p['features']=[tagmap[f] for f in p.get('features',[])]
        for w in p.get('writings',[]):w['type_id']=typemap[w['type_id']]
    try:
        for m in data.get('memberships',[]):
            m['class_id']=classmap[m['class_id']] if m['class_id'] else '';m['usage_id']=sub(owner,m.get('usage_id'))
            for p in m.get('parts',[]):p['variant_id']=sub(owner,p.get('variant_id'));common(p)
        for a in data.get('analyses',[]):
            for c in a.get('components',[]):
                common(c);target=c.get('lexeme_id')
                if target:
                    for k in ('usage_id','sense_id','form_id'):c[k]=sub(target,c.get(k))
                    c['lexeme_id']=xmap[target]
    except KeyError:raise ValueError('形态分析导入缺少引用定义')
    return data
