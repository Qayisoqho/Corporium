"""Language-owned semantic trees and explicit lexical collation schemes."""
import long_tasks
import json
import unicodedata
import uuid

TABLES=('semantic_classes','dictionary_orders')

def initialize(db):
    db.executescript('''
    CREATE TABLE IF NOT EXISTS semantic_classes(id TEXT PRIMARY KEY,language_id TEXT NOT NULL,name TEXT NOT NULL,parent_id TEXT,position INTEGER NOT NULL DEFAULT 0,revision INTEGER NOT NULL DEFAULT 1);
    CREATE TABLE IF NOT EXISTS dictionary_orders(id TEXT PRIMARY KEY,language_id TEXT NOT NULL,name TEXT NOT NULL,alphabet TEXT NOT NULL,case_sensitive INTEGER NOT NULL DEFAULT 0,revision INTEGER NOT NULL DEFAULT 1);
    CREATE INDEX IF NOT EXISTS semantic_language ON semantic_classes(language_id,parent_id);
    ''')

def listing(db,lid):
    return {k:[dict(r) for r in db.execute('SELECT * FROM '+table+' WHERE language_id=? ORDER BY '+order,(lid,))] for k,table,order in [('classes','semantic_classes','position,name,id'),('orders','dictionary_orders','name,id')]}

def normalized(s,sensitive=False):
    return unicodedata.normalize('NFC',s if sensitive else s.casefold())

def alphabet(value,sensitive=False):
    if not isinstance(value,str):raise ValueError('字母顺序须为文本')
    units=[normalized(v,sensitive) for v in value.split()]
    if not units:raise ValueError('请填写字母顺序，以空格或换行分隔')
    if len(units)!=len(set(units)):raise ValueError('字母顺序有重复单位（请检查大小写和组合字符）')
    return units

def sort_key(value,sensitive=False):
    trie={}
    for rank,unit in enumerate(alphabet(value,sensitive)):
        node=trie
        for char in unit:node=node.setdefault(char,{})
        node[None]=rank
    def key(word):
        word=normalized(word,sensitive);out=[];i=0
        while i<len(word):
            node=trie;j=i;found=None
            while j<len(word) and word[j] in node:
                node=node[word[j]];j+=1
                if None in node:found=(node[None],j)
            if found:out.append((0,found[0]));i=found[1]
            else:out.append((1,ord(word[i])));i+=1
        return out
    return key

def descendants(rows,root):
    children={}
    for r in rows:children.setdefault(r['parent_id'],[]).append(r['id'])
    found=set();todo=[root]
    while todo:
        item=todo.pop()
        if item in found:continue
        found.add(item);todo.extend(children.get(item,[]))
    return found

def validate_ids(db,lid,ids):
    if not isinstance(ids,list) or any(not isinstance(i,str) for i in ids) or len(ids)!=len(set(ids)):raise ValueError('语义分类选择无效')
    valid={r[0] for r in db.execute('SELECT id FROM semantic_classes WHERE language_id=?',(lid,))}
    if not set(ids)<=valid:raise ValueError('语义分类已删除或属于其他语言，请重新选择')
    return ids

def validate(db):
    rows=[dict(r) for r in db.execute('SELECT * FROM semantic_classes')];byid={r['id']:r for r in rows}
    for r in rows:
        seen={r['id']};parent=r['parent_id']
        while parent:
            if parent in seen or parent not in byid or byid[parent]['language_id']!=r['language_id']:raise ValueError('语义分类层级无效')
            seen.add(parent);parent=byid[parent]['parent_id']
    for r in db.execute('SELECT language_id,body FROM dictionary_targets'):
        validate_ids(db,r['language_id'],json.loads(r['body']).get('semantic_classes',[]))

def filter_sort(db,lid,rows,category='',order=''):
    config=listing(db,lid)
    if category=='@unclassified':rows=[r for r in rows if not r['body'].get('semantic_classes')]
    elif category:
        if not any(c['id']==category for c in config['classes']):raise ValueError('语义分类已不存在，请清空筛选')
        ids=descendants(config['classes'],category)
        rows=[r for r in rows if ids.intersection(r['body'].get('semantic_classes',[]))]
    import entry_dates
    if order in entry_dates.ORDERS:return entry_dates.sort_rows(rows,order)
    if order=='@classes':
        import dictionary_layout
        return dictionary_layout.sorted_rows(db,lid,rows)
    if order:
        scheme=next((r for r in config['orders'] if r['id']==order),None)
        if not scheme:raise ValueError('排序方案已不存在或属于其他语言，请恢复默认排序')
        key=sort_key(scheme['alphabet'],scheme['case_sensitive'])
        rows.sort(key=lambda r:key(r['headword']))
    return rows

def mutate(db,lid,action,b):
    if lid=='all':raise ValueError('请先选择一种语言')
    if action.startswith('layout-'):
        import dictionary_layout
        return dictionary_layout.mutate(db,lid,action,b)
    if action=='preview':
        key=sort_key(b.get('alphabet',''),bool(b.get('case_sensitive')))
        rows=[dict(r) for r in db.execute('SELECT id,headword FROM lexemes WHERE language_id=? ORDER BY headword COLLATE NOCASE,rowid',(lid,))]
        rows.sort(key=lambda r:key(r['headword']))
        return {'items':rows[:50],'total':len(rows)}
    if action=='assign':
        ids=validate_ids(db,lid,b.get('classes',[]));mode=b.get('mode','add')
        if mode not in ('add','remove','replace'):raise ValueError('分类操作无效')
        items=b.get('items',[])
        if not isinstance(items,list) or not items:raise ValueError('请选择词条')
        for item in long_tasks.steps(items):
            row=db.execute('SELECT * FROM lexemes WHERE id=? AND language_id=?',(item['id'],lid)).fetchone()
            if not row or row['revision']!=item.get('revision'):raise ValueError('词条已变化，请刷新后重试')
            data=json.loads(row['body']);old=data.get('semantic_classes',[])
            data['semantic_classes']=list(dict.fromkeys(old+ids)) if mode=='add' else [i for i in old if i not in ids] if mode=='remove' else ids
            db.execute('UPDATE lexemes SET body=?,revision=revision+1 WHERE id=?',(json.dumps(data,ensure_ascii=False),row['id']))
        return {'ok':True}
    isclass=action.startswith('class-');table='semantic_classes' if isclass else 'dictionary_orders'
    if action not in ('class-save','class-delete','order-save','order-delete','order-copy'):raise ValueError('未知词典组织操作')
    old=None
    if b.get('id'):
        old=db.execute('SELECT * FROM '+table+' WHERE id=? AND language_id=?',(b['id'],lid)).fetchone()
        if not old or old['revision']!=b.get('revision'):raise ValueError('记录已变化，请刷新后重试')
    if action.endswith('-delete'):
        if not old:raise ValueError('记录不存在')
        if isclass:
            rows=listing(db,lid)['classes'];ids=descendants(rows,old['id']);mode=b.get('children','promote')
            if mode not in ('promote','subtree'):raise ValueError('请选择子类的处理方式')
            if mode=='promote':
                db.execute('UPDATE semantic_classes SET parent_id=?,revision=revision+1 WHERE parent_id=?',(old['parent_id'],old['id']));ids={old['id']}
            for r in long_tasks.steps(db.execute('SELECT id,body,target_kind FROM dictionary_targets WHERE language_id=?',(lid,)).fetchall()):
                data=json.loads(r['body']);before=data.get('semantic_classes',[])
                if ids.intersection(before):
                    data['semantic_classes']=[i for i in before if i not in ids]
                    from dictionary_targets import write_body
                    write_body(db,r,data)
            db.executemany('DELETE FROM semantic_classes WHERE id=?',[(i,) for i in ids])
        else:db.execute('DELETE FROM dictionary_orders WHERE id=?',(old['id'],))
        return {'ok':True}
    name=b.get('name','').strip()
    if not name:raise ValueError('请填写名称')
    if action=='order-copy':
        if not old:raise ValueError('排序方案不存在')
        b={**dict(old),**b};old=None
    xid=old['id'] if old else str(uuid.uuid4())
    if isclass:
        parent=b.get('parent_id') or None;rows=listing(db,lid)['classes']
        if parent and (parent not in {r['id'] for r in rows} or parent in descendants(rows,xid)):raise ValueError('不能移入自己、后代或其他语言的分类')
        if any(r['id']!=xid and r['parent_id']==parent and r['name']==name for r in rows):raise ValueError('同级分类名称重复')
        position=int(b.get('position',old['position'] if old else len(rows)))
        db.execute('INSERT INTO semantic_classes VALUES(?,?,?,?,?,1) ON CONFLICT(id) DO UPDATE SET name=excluded.name,parent_id=excluded.parent_id,position=excluded.position,revision=semantic_classes.revision+1',(xid,lid,name,parent,position))
    else:
        sensitive=bool(b.get('case_sensitive'));value=b.get('alphabet','');alphabet(value,sensitive)
        if db.execute('SELECT 1 FROM dictionary_orders WHERE language_id=? AND name=? AND id<>?',(lid,name,xid)).fetchone():raise ValueError('排序方案名称重复')
        db.execute('INSERT INTO dictionary_orders VALUES(?,?,?,?,?,1) ON CONFLICT(id) DO UPDATE SET name=excluded.name,alphabet=excluded.alphabet,case_sensitive=excluded.case_sensitive,revision=dictionary_orders.revision+1',(xid,lid,name,value,int(sensitive)))
    return dict(db.execute('SELECT * FROM '+table+' WHERE id=?',(xid,)).fetchone())

def import_bundle(db,bundle,language_map):
    mapping={};pending=list(bundle.get('semantic_classes',[]))
    while pending:
        ready=[r for r in pending if not r.get('parent_id') or r['parent_id'] in mapping]
        if not ready:raise ValueError('语义分类包含循环或缺失父类')
        for r in long_tasks.steps(ready):
            lid=language_map[r['language_id']];parent=mapping.get(r.get('parent_id'));name=r['name'];n=1
            while db.execute('SELECT 1 FROM semantic_classes WHERE language_id=? AND parent_id IS ? AND name=?',(lid,parent,name)).fetchone():n+=1;name=r['name']+'（导入 '+str(n)+'）'
            new=mutate(db,lid,'class-save',dict(name=name,parent_id=parent,position=r.get('position',0)));mapping[r['id']]=new['id'];pending.remove(r)
    for r in long_tasks.steps(bundle.get('dictionary_orders',[])):
        lid=language_map[r['language_id']];name=r['name'];n=1
        while db.execute('SELECT 1 FROM dictionary_orders WHERE language_id=? AND name=?',(lid,name)).fetchone():n+=1;name=r['name']+'（导入 '+str(n)+'）'
        mutate(db,lid,'order-save',dict(name=name,alphabet=r['alphabet'],case_sensitive=r.get('case_sensitive',False)))
    return mapping
