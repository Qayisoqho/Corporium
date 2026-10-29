"""Live template structure; entry forms and surviving meaning identities stay local."""
import copy
import hashlib
import json
import uuid
import long_tasks
import paradigms


def synchronize(tables,old,new):
    old={t['id']:t for t in old};new={t['id']:t for t in new}
    result=[];removed=[]
    for original in tables:
        tid=original.get('template_id');prior=old.get(tid);current=new.get(tid)
        if not prior or prior==current:result.append(copy.deepcopy(original));continue
        table=copy.deepcopy(original);previous={r['id']:r for r in prior['rows']}
        # Old copies had fresh IDs without provenance. Match their original
        # categories once, in occurrence order; unmatched custom rows stay local.
        candidates={}
        for r in prior['rows']:candidates.setdefault(tuple(r['labels']),[]).append(r['id'])
        linked={};local=[]
        explicit={r.get('template_row_id') for r in table['rows'] if r.get('template_row_id')}
        for row in table['rows']:
            key=row.get('template_row_id')
            if not key:
                options=candidates.get(tuple(row['labels']),[])
                key=next((k for k in options if k not in linked and k not in explicit),None)
            if key in previous and key not in linked:linked[key]=row
            else:local.append(row)
        def populated(row,template=None):
            return bool(row.get('realizations') or row.get('state','unfilled')!='unfilled' or row.get('gloss_addition','')!=(template or {}).get('gloss_addition',''))
        if current is None:
            if table.get('notes') or any(populated(r,previous.get(k)) for k,r in linked.items()) or local:
                removed.append(dict(table=table.get('title',''),labels=[],whole_table=True))
            continue
        keep={r['id'] for r in current['rows']}
        for key,row in linked.items():
            if key not in keep and populated(row,previous[key]):removed.append(dict(table=table.get('title',''),labels=row['labels'],whole_table=False))
        rows=[]
        for template in current['rows']:
            key=template['id'];row=linked.get(key)
            if row is None:
                row=dict(id=str(uuid.uuid4()),state='unfilled',realizations=[],gloss_addition=template.get('gloss_addition',''))
            elif row.get('gloss_addition','')==previous[key].get('gloss_addition',''):
                row['gloss_addition']=template.get('gloss_addition','')
            row.update(template_row_id=key,labels=copy.deepcopy(template['labels']));rows.append(row)
        for row in local:
            if table['dimensions']!=current['dimensions']:
                values=dict(zip(table['dimensions'],row['labels']));row['labels']=[values.get(d,'') for d in current['dimensions']]
        table.update(dimensions=copy.deepcopy(current['dimensions']),rows=rows+local)
        if table['title']==prior['title']:table['title']=current['title']
        result.append(table)
    return result,removed


def plan(db,body):
    import languages,journal
    if not db.in_transaction:db.execute('BEGIN')
    language=languages.require(db,body.get('id'))
    if body.get('revision')!=language['revision']:raise ValueError('语言信息已更新，请重新打开')
    metadata=body.get('metadata',{})
    if not isinstance(metadata,dict):raise ValueError('语言信息格式不正确')
    new=paradigms.templates(metadata.get('paradigm_templates',[]))
    old=json.loads(language['metadata']).get('paradigm_templates',[])
    updates=[];deletions=[]
    entries=list(db.execute('SELECT * FROM lexemes WHERE language_id=?',(language['id'],))) if old!=new else []
    for entry in long_tasks.steps(entries):
        data=json.loads(entry['body']);tables,removed=synchronize(data.get('paradigms',[]),old,new)
        if tables!=data.get('paradigms',[]):
            data['paradigms']=tables;updates.append(dict(entry=dict(entry),body=data))
        deletions.extend(dict(**r,entry_id=entry['id'],headword=entry['headword'],draft=False) for r in removed)
    editor=None
    if 'editor_paradigms' in body:
        if not isinstance(body['editor_paradigms'],list):raise ValueError('变形表格式不正确')
        if body.get('editor_target_id'):
            target=db.execute('SELECT * FROM lexemes WHERE id=? AND language_id=?',(body['editor_target_id'],language['id'])).fetchone()
            if not target or target['revision']!=body.get('editor_target_revision'):raise ValueError('词条已修改，请重新打开后编辑')
        editor,removed=synchronize(body['editor_paradigms'],old,new)
        deletions.extend(dict(**r,entry_id=body.get('editor_target_id',''),headword=body.get('editor_headword',''),draft=True) for r in removed)
    # A confirmation describes this proposal and every related record in one
    # snapshot, so later edits cannot be deleted under an earlier confirmation.
    payload={k:v for k,v in body.items() if k not in ('template_sync_token','template_sync_confirmed','_language')}
    payload['metadata']={**metadata,'paradigm_templates':new}
    token=hashlib.sha256(json.dumps([payload,journal.workspace_revision(db)],sort_keys=True,ensure_ascii=False).encode()).hexdigest()
    return dict(token=token,updates=updates,deletions=deletions,editor=editor)


def preview(db,body):
    value=plan(db,body)
    return dict(token=value['token'],deletions=value['deletions'],updated_entries=len(value['updates']))


def apply(db,body):
    value=plan(db,body)
    if body.get('template_sync_token') and body['template_sync_token']!=value['token']:raise ValueError('模板或相关词条已变化，请重新预览后确认')
    if value['deletions'] and (body.get('template_sync_confirmed') is not True or body.get('template_sync_token')!=value['token']):raise ValueError('删除的模板项含有词条内容，请先预览并确认删除')
    for update in long_tasks.steps(value['updates']):
        entry=update['entry'];data=update['body'];before=json.loads(entry['body'])
        import dictionary_link_changes,lexicon
        current=lexicon.get_lexeme(db,entry['id'])
        dictionary_link_changes.detach(db,dictionary_link_changes.collect(db,current,data))
        data=paradigms.normalize(data,{**data})
        db.execute('UPDATE lexemes SET body=?,revision=revision+1 WHERE id=?',(json.dumps(data,ensure_ascii=False),entry['id']))
    result=dict(template_sync_count=len(value['updates']))
    if value['editor'] is not None:result['editor_paradigms']=value['editor']
    if body.get('editor_target_id'):
        row=db.execute('SELECT id,revision FROM lexemes WHERE id=?',(body['editor_target_id'],)).fetchone()
        if row:result.update(editor_target_id=row['id'],editor_target_revision=row['revision'])
    return result
