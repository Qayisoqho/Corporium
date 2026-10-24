"""Language-owned judgments for independent examples only. Empty means grammatical."""
import json
import uuid
from functools import lru_cache

KEY='grammaticality_types'
FIELD='grammaticality'
CORPUS_FIELDS=(FIELD,'grammaticality_definition','grammaticality_display')
DEFAULTS=(dict(id='ungrammatical',name='不合语法',symbol='*',description='',enabled=True),
          dict(id='questionable',name='合法性存疑',symbol='?',description='',enabled=True))


def clean(rows):
    if not isinstance(rows,list) or len(rows)>200:raise ValueError('合法性类型格式错误，每种语言最多 200 项')
    result=[];ids=set();names=set();symbols=set()
    for row in rows:
        if not isinstance(row,dict):raise ValueError('合法性类型格式错误')
        item={k:row.get(k,'') for k in ('id','name','symbol','description')}
        if any(not isinstance(v,str) for v in item.values()):raise ValueError('合法性名称和符号须为文字')
        for k in ('id','name','symbol'):item[k]=item[k].strip()
        if not item['id'] or len(item['id'])>100 or '/' in item['id'] or item['id']=='legal' or not item['name'] or item['name']=='合法' or len(item['name'])>80 or not item['symbol'] or len(item['symbol'])>12 or len(item['description'])>2000 or any(c in item['symbol'] for c in '\r\n\t'):raise ValueError('请填写合法性名称与符号（符号最多 12 字）；默认合法项固定为空')
        if item['id'] in ids or item['name'] in names or item['symbol'] in symbols:raise ValueError('合法性类型的名称、符号或编号重复')
        item['enabled']=row.get('enabled',True)
        if not isinstance(item['enabled'],bool):raise ValueError('启用状态格式错误')
        ids.add(item['id']);names.add(item['name']);symbols.add(item['symbol']);result.append(item)
    return result


@lru_cache(maxsize=128)
def definitions(metadata):
    meta=json.loads(metadata) if isinstance(metadata,str) else {}
    return tuple(clean(meta.get(KEY,[dict(r) for r in DEFAULTS])))


def catalog(db,lid):
    row=db.execute('SELECT metadata,revision FROM languages WHERE id=?',(lid,)).fetchone()
    if not row:raise ValueError('语言不存在')
    return dict(language_id=lid,revision=row['revision'],items=[dict(r) for r in definitions(row['metadata'])])


def selected(value,rows):
    if value in (None,''):return dict(id='',name='合法',symbol='',description='',enabled=True)
    if not isinstance(value,str):raise ValueError('合法性值格式错误')
    item=next((r for r in rows if r['id']==value),None)
    if not item:raise ValueError('合法性类型不存在或不属于例句语言，请重新选择')
    return item


def check(db,body,lid):
    return selected(body.get(FIELD,''),catalog(db,lid)['items'])


def strip_corpus(body):
    for key in CORPUS_FIELDS:body.pop(key,None)
    return body


def corpus_rows_needed(db):
    if not db.execute("SELECT 1 FROM sqlite_master WHERE name='entries'").fetchone():return False
    return bool(db.execute("SELECT 1 FROM entries WHERE "+' OR '.join("json_type(body,'$."+key+"') IS NOT NULL" for key in CORPUS_FIELDS)+" LIMIT 1").fetchone())


def migrate_corpus(db):
    """The caller backs up old projects first; preserve every other sentence field."""
    if not corpus_rows_needed(db):return False
    db.execute("UPDATE entries SET body=json_remove(body,"+','.join("'$."+key+"'" for key in CORPUS_FIELDS)+"),revision=revision+1 WHERE "+' OR '.join("json_type(body,'$."+key+"') IS NOT NULL" for key in CORPUS_FIELDS))
    return True


def normalize_rows(db,changes):
    # Also applies to imported data and old row images restored through undo.
    for (table,rowid),(_,after) in list(changes.items()):
        if table!='entries' or not after:continue
        # Reuse the journal's current row image: no extra SELECT or JSON parse
        # for normal text edits, including large imports and replacements.
        raw=after['body']
        if not any('"'+key+'"' in raw for key in CORPUS_FIELDS):continue
        body=json.loads(raw)
        if not any(key in body for key in CORPUS_FIELDS):continue
        db.execute('UPDATE entries SET body=? WHERE rowid=?',(json.dumps(strip_corpus(body),ensure_ascii=False),rowid))


def copy_value(old,new,source,kind='independent'):
    if kind!='independent':strip_corpus(new);return
    # Omitted by older editors means preserve, explicit empty clears the mark.
    if FIELD in source:
        if source[FIELD] is not None and not isinstance(source[FIELD],str):raise ValueError('合法性值格式错误')
        new[FIELD]=source[FIELD] or ''
    elif FIELD in old:new[FIELD]=old[FIELD]


def references(db,lid):
    return db.execute("SELECT id,COALESCE(json_extract(body,'$.grammaticality'),'') value FROM dictionary_examples WHERE language_id=?",(lid,))


def validate(db,changes=None):
    if changes is None:
        for r in db.execute('SELECT id,metadata FROM languages'):
            rows=definitions(r['metadata'])
            for ref in references(db,r['id']):selected(ref['value'],rows)
        return
    catalogs={}
    def rows(lid):
        if lid not in catalogs:catalogs[lid]=catalog(db,lid)['items']
        return catalogs[lid]
    for (table,_),(before,after) in changes.items():
        if before==after or not after:continue
        if table=='languages':
            new=definitions(after['metadata']);old=definitions(before['metadata']) if before else ()
            if {r['id'] for r in old}-{r['id'] for r in new}:
                for ref in references(db,after['id']):selected(ref['value'],new)
        elif table=='dictionary_examples':
            b=json.loads(after['body'])
            if FIELD not in b:continue
            lid=after['language_id']
            selected(b[FIELD],rows(lid))


def mutate_type(db,action,b,lid):
    data=catalog(db,lid)
    if b.get('revision')!=data['revision']:raise ValueError('合法性类型已更新，请重新打开')
    rows=data['items'];rid=b.get('id');old=next((r for r in rows if r['id']==rid),None)
    if rid and not old:raise ValueError('合法性类型不存在')
    if action=='delete':
        if not old or b.get('confirmed') is not True:raise ValueError('请确认删除合法性类型')
        if any(r['value']==rid for r in references(db,lid)):raise ValueError('该类型仍被例句使用，请先修改例句，或将类型停用以保留已有记录')
        rows=[r for r in rows if r['id']!=rid]
    else:
        item={k:b.get(k,'' if k!='enabled' else True) for k in ('name','symbol','description','enabled')}
        item['id']=rid or str(uuid.uuid4())
        rows=[item if r['id']==rid else r for r in rows] if old else [*rows,item]
        if 'position' in b:
            position=b['position']
            if type(position) is not int or not 1<=position<=len(rows):raise ValueError('显示顺序超出类型数量')
            rows=[r for r in rows if r['id']!=item['id']];rows.insert(position-1,item)
    rows=clean(rows)
    row=db.execute('SELECT metadata FROM languages WHERE id=?',(lid,)).fetchone();meta=json.loads(row[0]);meta[KEY]=rows
    db.execute('UPDATE languages SET metadata=?,revision=revision+1 WHERE id=?',(json.dumps(meta,ensure_ascii=False),lid))
    return dict(ok=True,id=rid or item['id'])


def save(db,b,lid):
    import annotations
    if b.get('kind')!='independent':raise ValueError('只有独立例句库的句子可以设置合法性')
    data=annotations.get(db,b['kind'],b['id'])
    if data['owner_language']!=lid or b.get('revision')!=data['revision']:raise ValueError('例句已修改，请重新打开')
    value=b.get(FIELD,'')
    if not isinstance(value,str):raise ValueError('合法性值格式错误')
    item=selected(value,catalog(db,data['language_id'])['items'])
    if not item['enabled'] and value!=data['body'].get(FIELD,''):raise ValueError('该合法性类型已停用')
    table='dictionary_examples'
    # Use stored body: resolved glosses and display metadata must not be written.
    row=db.execute('SELECT body FROM '+table+' WHERE id=?',(b['id'],)).fetchone();body=json.loads(row[0])
    if body.get(FIELD,'')!=value:
        body[FIELD]=value
        db.execute('UPDATE '+table+' SET body=?,revision=revision+1 WHERE id=?',(json.dumps(body,ensure_ascii=False),b['id']))
    return dict(ok=True)


def filter_sql(q,body='e.body',language=None):
    value=q.get(FIELD,'')
    if not value:return '',[]
    if not isinstance(value,str) or len(value)>220:raise ValueError('合法性筛选无效')
    lid,sep,rid=value.partition('/')
    rid=rid if sep else value
    sql=" AND COALESCE(json_extract("+body+",'$.grammaticality'),'')=?";args=['' if rid=='legal' else rid]
    if sep and language:sql+=' AND '+language+'=?';args.append(lid)
    return sql,args


def export_language(row):
    result=dict(row);meta=json.loads(result['metadata']);meta[KEY]=[dict(r) for r in definitions(result['metadata'])];result['metadata']=json.dumps(meta,ensure_ascii=False)
    return result


def merge_catalog(db,lid,source_meta):
    """Import definitions without changing an established target definition."""
    # Older exchange files predate sentence judgments and carry no inventory.
    if KEY not in source_meta:return
    incoming=definitions(json.dumps(source_meta,ensure_ascii=False));current=catalog(db,lid)['items'];known={r['id']:r for r in current}
    for item in incoming:
        old=known.get(item['id'])
        if old:
            if any(old[k]!=item[k] for k in ('name','symbol','description')):raise ValueError('导入合法性类型与目标语言冲突：'+item['name']+'；请先核对定义，或导入到新语言')
        else:current.append(dict(item));known[item['id']]=item
    current=clean(current)
    meta=json.loads(db.execute('SELECT metadata FROM languages WHERE id=?',(lid,)).fetchone()[0])
    if current!=catalog(db,lid)['items']:
        meta[KEY]=current;db.execute('UPDATE languages SET metadata=?,revision=revision+1 WHERE id=?',(json.dumps(meta,ensure_ascii=False),lid))
