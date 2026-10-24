"""Display-only, language-owned class trees and sibling ordering."""
import hashlib
import json
import categories
import dictionary_organization
import long_tasks

KINDS = dict(pos='词类及子类', semantic='语义分类', morph='形态类', form='形式类型', usage_tag='使用标签类型', grammar='语法标签分类')

def key(path):
    return json.dumps(path, ensure_ascii=False, separators=(',', ':'))

def config(db, lid):
    row = db.execute('SELECT metadata,revision FROM languages WHERE id=?', (lid,)).fetchone()
    if row is None:
        raise ValueError('请先选择一种语言')
    data = json.loads(row['metadata']).get('dictionary_layout', {})
    validate(data)
    return {'levels': data.get('levels', ['pos', 'semantic']), 'groups': data.get('groups', {}), 'entries': data.get('entries', {})}, row['revision']

def validate(data):
    if not isinstance(data,dict):raise ValueError('分类排序设置格式无效')
    levels=data.get('levels',['pos','semantic'])
    if not isinstance(levels,list) or not levels or len(levels)>len(KINDS) or any(k not in KINDS for k in levels) or len(set(levels))!=len(levels):raise ValueError('分类排序层级无效')
    for kind in ('groups','entries'):
        values=data.get(kind,{})
        if not isinstance(values,dict):raise ValueError('分类顺序格式无效')
        for path,ids in values.items():
            try:parts=json.loads(path)
            except (ValueError,TypeError):raise ValueError('分类路径无效') from None
            if not isinstance(parts,list) or any(not isinstance(p,str) for p in parts) or not isinstance(ids,list) or any(not isinstance(i,str) for i in ids) or len(set(ids))!=len(ids):raise ValueError('分类顺序包含无效或重复项')

def rank(config, parent, token, label):
    order = config['_ranks'].get(key(parent), {})
    return (order.get(token,len(order)), label.casefold(), token)

def sorted_rows(db, lid, rows):
    cfg, _ = config(db, lid)
    cfg['_ranks']={p:{v:i for i,v in enumerate(ids)} for p,ids in cfg['groups'].items()}
    entry_ranks={p:{v:i for i,v in enumerate(ids)} for p,ids in cfg['entries'].items()}
    catalog = categories.listing(db, lid)
    semantic = dictionary_organization.listing(db, lid)['classes']
    nodes = {r['id']: {**r, 'kind': 'semantic'} for r in semantic}
    nodes.update({r['id']: r for r in catalog})
    by_name = {(r['kind'], r['name'], r['parent_id']): r['id'] for r in catalog}
    tag_categories={r['id']:r['category'] for r in db.execute('SELECT id,category FROM grammar_tags WHERE language_id=?',(lid,))}
    def chain(xid):
        out, seen = [], set()
        while xid and xid in nodes and xid not in seen:
            seen.add(xid); node = nodes[xid]
            out.insert(0, dict(key=node['kind']+':'+xid, label=node['name']))
            xid = node['parent_id']
        return out
    def candidates(body, kind):
        ids = []
        if kind == 'semantic': ids = body.get('semantic_classes', [])
        elif kind == 'pos':
            for u in body.get('usages', []):
                parent = by_name.get(('pos', u.get('pos'), None))
                ids.append(by_name.get(('pos', u.get('subclass'), parent), parent) if u.get('subclass') else parent)
        elif kind == 'morph': ids = [m.get('class_id') for m in body.get('word_structure', {}).get('memberships', [])]
        elif kind == 'form': ids = [by_name.get(('form', categories.FORM_NAMES.get(v.get('kind'), v.get('kind')), None)) for v in body.get('variants', [])]
        elif kind == 'usage_tag': ids = [by_name.get(('usage_tag', categories.TAG_NAMES.get(t.get('type'), t.get('type')), None)) for t in categories.usage_tags(body)]
        elif kind == 'grammar':
            parts=[body,*body.get('variants',[]),*body.get('usages',[]),*(s for u in body.get('usages',[]) for s in u.get('senses',[]))]
            structure=body.get('word_structure',{})
            parts += [p for m in structure.get('memberships',[]) for p in m.get('parts',[])]+[c for a in structure.get('analyses',[]) for c in a.get('components',[])]
            ids=[by_name.get(('grammar',tag_categories.get(t),None)) for part in parts for t in part.get('features',[])]
        return [chain(i) for i in dict.fromkeys(ids) if i in nodes] or [[dict(key=kind+':@none', label='未指定'+KINDS[kind])]]
    def path_rank(path, parent=()):
        result = []; prefix = list(parent)
        for node in path:
            result.append(rank(cfg, prefix, node['key'], node['label'])); prefix.append(node['key'])
        return result
    for row in long_tasks.steps(rows):
        path = []
        for kind in cfg['levels']:
            variants = candidates(row['body'], kind)
            path += min(variants, key=lambda p: path_rank(p, [n['key'] for n in path]))
        row['sort_path'] = path
    def sortkey(row):
        path = row['sort_path']; order = entry_ranks.get(key([n['key'] for n in path]), {})
        return path_rank(path)+[(-1, '', ''), (order.get(row['id'],len(order)), row['headword'].casefold(), row['id'])]
    return sorted(rows, key=sortkey)

def tree(db, lid, path=None, page=1):
    if lid == 'all': raise ValueError('分类排序请先选择一种语言')
    path = path or []
    if not isinstance(path, list) or any(not isinstance(x, str) for x in path): raise ValueError('分类路径无效')
    cfg, revision = config(db, lid)
    rows = sorted_rows(db, lid, [{**dict(r), 'body': json.loads(r['body'])} for r in db.execute('SELECT id,headword,body,revision FROM lexemes WHERE language_id=?', (lid,))])
    catalog=categories.listing(db,lid)+[{**r,'kind':'semantic'} for r in dictionary_organization.listing(db,lid)['classes']]
    signature = key([[[r['id'], r['revision'], r['sort_path']] for r in rows],[[r['id'],r['revision'],r['name'],r['parent_id']] for r in catalog]])
    token = hashlib.sha256(signature.encode()).hexdigest()
    groups = {}; entries = []
    for row in rows:
        nodes = row['sort_path']; tokens = [n['key'] for n in nodes]
        if tokens[:len(path)] != path: continue
        if len(tokens) == len(path): entries.append(dict(id=row['id'], headword=row['headword']))
        else:
            node = nodes[len(path)]
            groups.setdefault(node['key'], {**node, 'count': 0})['count'] += 1
    # Include unused classes in the manager so users can prepare their order.
    roots=[]
    if not path:roots=[cfg['levels'][0]]
    else:
        kind,_,xid=path[-1].partition(':')
        for r in catalog:
            if r['kind']==kind and r['parent_id']==xid:groups.setdefault(kind+':'+r['id'],dict(key=kind+':'+r['id'],label=r['name'],count=0))
        if kind in cfg['levels'] and cfg['levels'].index(kind)+1<len(cfg['levels']):roots=[cfg['levels'][cfg['levels'].index(kind)+1]]
    for r in catalog:
        if r['kind'] in roots and not r['parent_id']:groups.setdefault(r['kind']+':'+r['id'],dict(key=r['kind']+':'+r['id'],label=r['name'],count=0))
    order={v:i for i,v in enumerate(cfg['groups'].get(key(path),[]))}
    group_rows=sorted(groups.values(),key=lambda g:(order.get(g['key'],len(order)),g['label'].casefold(),g['key']))
    page = max(1, min(int(page), max(1, (len(entries)+39)//40)))
    return dict(config=cfg, revision=revision, token=token, kinds=KINDS, path=path, groups=group_rows, items=entries[(page-1)*40:page*40], page=page, pages=max(1, (len(entries)+39)//40), total=len(entries))

def mutate(db, lid, action, body):
    cfg, revision = config(db, lid)
    if body.get('revision') != revision: raise ValueError('排序设置已变化，请刷新后重试')
    if action == 'layout-save':
        levels = body.get('levels')
        if not isinstance(levels, list) or not levels or len(levels) != len(set(levels)) or any(k not in KINDS for k in levels): raise ValueError('请选择不重复的分类层级')
        cfg['levels'] = levels
    elif action == 'layout-move':
        current = tree(db, lid, body.get('path'))
        if current['token'] != body.get('token'): raise ValueError('词条或分类已变化，请刷新后重新拖动')
        kind = body.get('kind'); xid = body.get('id'); before = body.get('before')
        if kind == 'groups': ids = [r['key'] for r in current['groups']]
        elif kind == 'entries':
            rows = sorted_rows(db, lid, [{**dict(r), 'body': json.loads(r['body'])} for r in db.execute('SELECT id,headword,body,revision FROM lexemes WHERE language_id=?', (lid,))])
            ids = [r['id'] for r in rows if [n['key'] for n in r['sort_path']] == current['path']]
        else: raise ValueError('拖动类型无效')
        if xid not in ids or before is not None and before not in ids: raise ValueError('只能调整当前类内的同级顺序')
        if xid == before: return {'ok': True}
        ids.remove(xid); ids.insert(ids.index(before)+(1 if body.get('after') else 0) if before else len(ids), xid)
        cfg[kind][key(current['path'])] = ids
    else: raise ValueError('未知分类排序操作')
    row = db.execute('SELECT metadata FROM languages WHERE id=?', (lid,)).fetchone(); meta = json.loads(row['metadata'])
    meta['dictionary_layout'] = cfg
    db.execute('UPDATE languages SET metadata=?,revision=revision+1 WHERE id=?', (json.dumps(meta, ensure_ascii=False), lid))
    return {'ok': True}

def remap_import(db, layouts, semantic_map, class_map, lexeme_map):
    mapping = {**semantic_map, **class_map}
    def token(t):
        kind, _, xid = t.partition(':')
        return kind+':'+mapping.get(xid, xid)
    for lid,source in layouts.items():
        row = db.execute('SELECT metadata FROM languages WHERE id=?', (lid,)).fetchone(); meta = json.loads(row['metadata']); cfg = json.loads(json.dumps(source))
        validate(cfg)
        cfg['groups'] = {key([token(t) for t in json.loads(p)]): [token(t) for t in ids] for p, ids in cfg.get('groups', {}).items()}
        cfg['entries'] = {key([token(t) for t in json.loads(p)]): [lexeme_map[i] for i in ids if i in lexeme_map] for p, ids in cfg.get('entries', {}).items()}
        meta['dictionary_layout']=cfg
        db.execute('UPDATE languages SET metadata=? WHERE id=?', (json.dumps(meta, ensure_ascii=False), lid))
