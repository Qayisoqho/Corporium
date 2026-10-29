"""Atomic category edits may rebase their own changes onto an open editor."""
import json

def before(db,b,lid):
    if not b.get('editor_target_id'):return None
    row=db.execute('SELECT id,revision FROM dictionary_targets WHERE id=? AND language_id=?',(b.get('editor_target_id'),lid)).fetchone()
    return dict(row) if row and row['revision']==b.get('editor_target_revision') else None

def finish(db,b,result,previous):
    if previous:
        row=db.execute('SELECT * FROM dictionary_targets WHERE id=?',(previous['id'],)).fetchone()
        if row:result={**result,'editor_before_revision':previous['revision'],'editor_target':{**dict(row),'body':json.loads(row['body'])}}
    return result

def order(db,table,lid,b,kind=None):
    rows=[dict(r) for r in db.execute('SELECT * FROM '+table+' WHERE language_id=?',(lid,))]
    rows=[r for r in rows if (kind is None or r['kind']==kind) and (r.get('parent_id') or '')==(b.get('parent_id') or '')]
    items=b.get('items')
    if not isinstance(items,list) or len(items)!=len(rows) or any(not isinstance(i,dict) or not isinstance(i.get('id'),str) for i in items):raise ValueError('分类顺序已变化，请刷新后重试')
    current={r['id']:r['revision'] for r in rows}
    if len({i.get('id') for i in items})!=len(items) or {i.get('id'):i.get('revision') for i in items}!=current:raise ValueError('分类顺序已变化，请刷新后重试')
    for position,item in enumerate(items):db.execute('UPDATE '+table+' SET position=?,revision=revision+1 WHERE id=?',(position,item['id']))
    return {'ok':True}
