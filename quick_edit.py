"""Language-local required writing columns for the dictionary's quick editor."""
import json
import languages

def configuration(meta):
    value=meta.get('lexeme_quick_edit',{})
    if not isinstance(value,dict):raise ValueError('快捷编辑设置须为对象')
    ids=value.get('writing_types',[])
    if not isinstance(ids,list) or any(not isinstance(v,str) or not v for v in ids) or len(set(ids))!=len(ids):raise ValueError('快捷编辑书写类型设置无效')
    return ids

def get(db,lid):
    row=languages.require(db,lid)
    types=[dict(r) for r in db.execute('SELECT * FROM writing_types WHERE language_id=? ORDER BY position,name,id',(lid,))]
    raw=configuration(json.loads(row['metadata']))
    return dict(revision=row['revision'],writing_types=types,selected=[t['id'] for t in types if t['id'] in raw])

def save(db,lid,body):
    row=languages.require(db,lid)
    if row['revision']!=body.get('revision'):raise ValueError('语言设置已变化，请重新打开后保存')
    ids=body.get('writing_types',[])
    if not isinstance(ids,list) or any(not isinstance(v,str) for v in ids) or len(set(ids))!=len(ids):raise ValueError('请选择书写类型')
    valid={r['id'] for r in db.execute('SELECT id FROM writing_types WHERE language_id=?',(lid,))}
    if any(v not in valid for v in ids):raise ValueError('书写类型不存在或不属于当前语言')
    meta=json.loads(row['metadata']);meta['lexeme_quick_edit']={'writing_types':ids}
    db.execute('UPDATE languages SET metadata=?,revision=revision+1 WHERE id=?',(json.dumps(meta,ensure_ascii=False),lid))
    return get(db,lid)

def writing_replace(db,old,new):
    for row in db.execute('SELECT id,metadata FROM languages').fetchall():
        meta=json.loads(row['metadata']);settings=meta.get('lexeme_quick_edit',{})
        ids=configuration(meta)
        if old not in ids:continue
        settings['writing_types']=list(dict.fromkeys(new if v==old else v for v in ids if v!=old or new))
        db.execute('UPDATE languages SET metadata=?,revision=revision+1 WHERE id=?',(json.dumps(meta,ensure_ascii=False),row['id']))

def import_settings(db,bundle,lid,mapping):
    row=languages.require(db,lid);meta=json.loads(row['metadata'])
    if get(db,lid)['selected'] or meta.get('lexeme_quick_edit')=={'writing_types':[]}:return
    source=bundle['language'].get('metadata','{}');source=json.loads(source) if isinstance(source,str) else source
    settings=source.get('lexeme_quick_edit')
    if not settings:return
    meta['lexeme_quick_edit']={'writing_types':list(dict.fromkeys(mapping[v] for v in configuration(source) if v in mapping))}
    db.execute('UPDATE languages SET metadata=?,revision=revision+1 WHERE id=?',(json.dumps(meta,ensure_ascii=False),lid))
