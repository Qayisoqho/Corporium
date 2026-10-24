"""Atomic corpus organization operations. Backups precede destructive changes."""
import long_tasks
import json
import uuid
from metadata import TABLES
from datetime import datetime, timezone
import backup_policy


def organize(db, action, body, backup_dir):
    if not db.in_transaction: db.execute('BEGIN IMMEDIATE')
    def text(tid):
        row = db.execute('SELECT * FROM texts WHERE id=?', (tid,)).fetchone()
        if row is None:
            raise ValueError('文本不存在，请刷新页面')
        return row
    def rows(tid):
        return list(db.execute('SELECT * FROM entries WHERE text_id=? ORDER BY position,id', (tid,)))
    def order(tid, records):
        for position, row in long_tasks.steps(enumerate(records, 1)):
            db.execute('UPDATE entries SET text_id=?,position=? WHERE id=?', (tid, position, row['id']))
    def provenance(row, source):
        data=json.loads(row['body'])
        if 'origin' not in data:
            data['origin']={'text_id':source['id'], 'title':source['title'], 'source':source['source']}
            db.execute('UPDATE entries SET body=? WHERE id=?',(json.dumps(data,ensure_ascii=False),row['id']))
    def backup():
        import streaming_json
        from pathlib import Path
        job=long_tasks.CURRENT.get()
        data={'format':'ordos-corpus-v1','created':datetime.now(timezone.utc).isoformat(), **{t:streaming_json.TableRows(db,t) for t in TABLES}}
        saved=backup_policy.write_json(backup_dir,data,stream=True,defer_prune=bool(job))
        if job:
            job['created'].append(Path(backup_dir)/saved)
            job.setdefault('backup_folders',set()).add(Path(backup_dir))
        return saved

    if action in ('delete-entry','delete-text'):
        if body.get('confirmed') is not True:
            raise ValueError('请再次确认删除')
        if action=='delete-entry':
            row=db.execute('SELECT * FROM entries WHERE id=?',(body['id'],)).fetchone()
            if row is None: raise ValueError('句子不存在，请刷新页面')
            if row['revision']!=body['revision'] or row['text_id']!=body['text_id']:
                raise ValueError('句子已发生变化，请刷新后再删除')
            records=[r for r in rows(row['text_id']) if r['id']!=row['id']]
            saved=backup()
            db.execute('DELETE FROM history WHERE entry_id=?',(row['id'],))
            db.execute('DELETE FROM entries WHERE id=?',(row['id'],))
            order(row['text_id'],records)
        else:
            text(body['id'])
            records=rows(body['id'])
            if len(records)!=body['count']: raise ValueError('文本句数已变化，请刷新后再次确认')
            saved=backup()
            db.execute('DELETE FROM history WHERE entry_id IN (SELECT id FROM entries WHERE text_id=?)',(body['id'],))
            db.execute('DELETE FROM entries WHERE text_id=?',(body['id'],))
            db.execute('DELETE FROM texts WHERE id=?',(body['id'],))
            db.execute('DELETE FROM text_info WHERE text_id=?',(body['id'],))
        return {'ok':True,'backup':saved}

    if action=='duplicate-entry':
        source=db.execute('SELECT * FROM entries WHERE id=?',(body.get('id'),)).fetchone()
        if not source or source['text_id']!=body.get('text_id') or source['revision']!=body.get('revision'):
            raise ValueError('原句已变化，请刷新后重新复制')
        records=rows(source['text_id'])
        if body.get('order')!=[r['id'] for r in records]:raise ValueError('句子顺序已变化，请重新选择插入位置')
        where=body.get('where')
        if where=='start':at=0
        elif where=='end':at=len(records)
        elif where in ('before','after'):
            anchor=next((i for i,r in enumerate(records) if r['id']==body.get('anchor_id')),None)
            if anchor is None:raise ValueError('目标句子已不存在，请重新选择')
            at=anchor+int(where=='after')
        else:raise ValueError('请选择插入位置')
        eid=str(uuid.uuid4())
        db.execute('INSERT INTO entries(id,text_id,position,body,revision) VALUES(?,?,?,?,1)',(eid,source['text_id'],at+1,source['body']))
        import collaborators
        collaborators.copy_sentence(db,source['id'],eid)
        # Copy active and retired evidence alike, with fresh globally unique identities.
        units=[dict(r) for r in db.execute('SELECT * FROM corpus_units WHERE entry_id=?',(source['id'],))]
        mapping={u['id']:str(uuid.uuid4()) for u in units}
        def remap(value):
            if isinstance(value,list):return [remap(v) for v in value]
            if isinstance(value,dict):return {k:mapping.get(v,v) if k in ('unit_id','parent_id','annotation_id') and isinstance(v,str) else remap(v) for k,v in value.items()}
            return value
        import reduplication
        db.execute('UPDATE entries SET body=? WHERE id=?',(json.dumps(reduplication.fork(remap(json.loads(source['body']))),ensure_ascii=False),eid))
        for u in long_tasks.steps(units):
            db.execute('INSERT INTO corpus_units(id,entry_id,kind,parent_id,position,form,gloss,active,revision) VALUES(?,?,?,?,?,?,?,?,1)',(mapping[u['id']],eid,u['kind'],mapping.get(u['parent_id']),u['position'],u['form'],u['gloss'],u['active']))
        # Bindings locate their owning word by its new identity. Establish all
        # words first: source rows may enumerate a morpheme before its parent.
        for u in long_tasks.steps(units):
            segment=db.execute('SELECT body FROM unit_segments WHERE id=?',(u['id'],)).fetchone()
            if segment:db.execute('INSERT INTO unit_segments VALUES(?,?)',(mapping[u['id']],json.dumps(remap(json.loads(segment['body'])),ensure_ascii=False)))
            link=db.execute('SELECT * FROM lexical_links WHERE unit_id=?',(u['id'],)).fetchone()
            if link:
                link_id=str(uuid.uuid4())
                db.execute('INSERT INTO lexical_links(id,unit_id,lexeme_id,usage_id,sense_id,notes,language_id,revision) VALUES(?,?,?,?,?,?,?,1)',(link_id,mapping[u['id']],link['lexeme_id'],link['usage_id'],link['sense_id'],link['notes'],link['language_id']))
                import gloss_inheritance
                prior=db.execute('SELECT unit_key FROM gloss_bindings WHERE id=?',(link['id'],)).fetchone()
                if prior:gloss_inheritance.copy_binding(db,link['id'],link_id,'corpus',eid,mapping[u['parent_id'] or u['id']],prior['unit_key'])
                import link_review
                link_review.copy(db,link['id'],link_id)
                component=db.execute('SELECT body FROM component_links WHERE id=?',(link['id'],)).fetchone()
                if component:db.execute('INSERT INTO component_links VALUES(?,?)',(link_id,component[0]))
                analysis=db.execute('SELECT * FROM morphology_analyses WHERE id=?',(link['id'],)).fetchone()
                if analysis:db.execute('INSERT INTO morphology_analyses VALUES(?,?,?)',(link_id,analysis['form_id'],analysis['features']))
        for cell in long_tasks.steps(list(db.execute("SELECT * FROM annotation_cells WHERE owner_kind='corpus' AND record_id=?",(source['id'],)))):
            uid=cell['unit_id']
            if uid!='@sentence':uid=mapping.setdefault(uid,str(uuid.uuid4()))
            db.execute('INSERT INTO annotation_cells VALUES(?,?,?,?,?,?,1)',(str(uuid.uuid4()),'corpus',eid,uid,cell['layer_id'],cell['value']))
        import code_switching
        for span in code_switching.rows(db,'corpus',source['id']):
            for unit_id in json.loads(span['word_ids']):mapping.setdefault(unit_id,str(uuid.uuid4()))
        code_switching.copy_spans(db,'corpus',source['id'],'corpus',eid,mapping)
        order(source['text_id'],records[:at]+[{'id':eid}]+records[at:])
        return {'ok':True,'id':eid,'text_id':source['text_id'],'position':at+1}

    if action=='reorder-entry':
        row=db.execute('SELECT * FROM entries WHERE id=?',(body.get('id'),)).fetchone()
        if not row or row['text_id']!=body.get('text_id') or row['revision']!=body.get('revision') or row['position']!=body.get('position'):raise ValueError('句子或顺序已变化，请刷新后重试')
        records=rows(row['text_id']);old=next(i for i,r in enumerate(records) if r['id']==row['id'])
        remaining=[r for r in records if r['id']!=row['id']];where=body.get('where')
        if where=='up':at=max(0,old-1)
        elif where=='down':at=min(len(remaining),old+1)
        elif where in ('before','after'):
            anchor=next((i for i,r in enumerate(remaining) if r['id']==body.get('anchor_id')),None)
            if anchor is None:raise ValueError('目标句子不存在或就是当前句子')
            at=anchor+int(where=='after')
        else:raise ValueError('无效的移动位置')
        order(row['text_id'],remaining[:at]+[row]+remaining[at:])
        return {'ok':True,'id':row['text_id'],'position':at+1}

    if action=='split':
        source=text(body['source_id'])
        title=body.get('title','').strip()
        if not title: raise ValueError('请填写新文本标题')
        ids=body.get('ids')
        if not isinstance(ids,list) or not ids or any(not isinstance(i,str) for i in ids) or len(ids)!=len(set(ids)):
            raise ValueError('请选择有效的句子')
        selected=set(ids);source_rows=rows(source['id'])
        picked=[r for r in source_rows if r['id'] in selected]
        if len(picked)!=len(ids): raise ValueError('所选句子已移动或删除，请刷新后重新选择')
        saved=backup();tid=str(uuid.uuid4())
        db.execute('INSERT INTO texts(id,title,source,original,digest,errors,language_id) VALUES(?,?,?,?,NULL,?,?)',(tid,title,source['source'],'','[]',source['language_id']))
        info=db.execute('SELECT * FROM text_info WHERE text_id=?',(source['id'],)).fetchone()
        if info:
            db.execute('INSERT INTO text_info(text_id,folder_id,metadata,revision) VALUES(?,?,?,1)',(tid,info['folder_id'],info['metadata']))
        import collaborators
        collaborators.combine_text(db,source['id'],tid)
        for r in long_tasks.steps(picked): provenance(r,source)
        order(source['id'],[r for r in source_rows if r['id'] not in selected])
        order(tid,picked)
        return {'ok':True,'id':tid,'count':len(picked),'backup':saved}

    if action in ('move','copy-entries'):
        source=text(body['source_id']); target=text(body['target_id'])
        if source['id']==target['id']: raise ValueError('请选择另一个目标文本')
        if source['language_id']!=target['language_id']:raise ValueError('句子复制或移动须在同一语言内进行')
        ids=body['ids']
        if not isinstance(ids,list) or not ids or len(ids)!=len(set(ids)): raise ValueError('请选择有效的句子')
        source_rows=rows(source['id']); target_rows=rows(target['id'])
        picked=[r for r in source_rows if r['id'] in set(ids)]
        if len(picked)!=len(ids): raise ValueError('所选句子已移动或删除，请刷新后重新选择')
        if body.get('source_order') is not None and body['source_order']!=[r['id'] for r in source_rows]:raise ValueError('来源句序已变化，请重新打开')
        if body.get('target_order') is not None and body['target_order']!=[r['id'] for r in target_rows]:raise ValueError('目标句序已变化，请重新打开')
        where=body['where']
        if where=='start': at=0
        elif where=='end': at=len(target_rows)
        elif where in ('before','after'):
            anchors=[i for i,r in enumerate(target_rows) if r['id']==body.get('before_id')]
            if not anchors: raise ValueError('目标位置已变化，请重新选择')
            at=anchors[0]+int(where=='after')
        else: raise ValueError('无效的插入位置')
        saved=backup()
        if action=='copy-entries':
            copies=[]
            for r in long_tasks.steps(picked):
                result=organize(db,'duplicate-entry',dict(id=r['id'],text_id=source['id'],revision=r['revision'],order=[v['id'] for v in rows(source['id'])],where='end'),backup_dir)
                copied=db.execute('SELECT * FROM entries WHERE id=?',(result['id'],)).fetchone()
                provenance(copied,source);copies.append(copied)
            order(source['id'],source_rows)
            order(target['id'],target_rows[:at]+copies+target_rows[at:])
            return {'ok':True,'id':target['id'],'position':at+1,'count':len(copies),'backup':saved}
        for r in long_tasks.steps(picked): provenance(r,source)
        order(source['id'],[r for r in source_rows if r['id'] not in set(ids)])
        order(target['id'],target_rows[:at]+picked+target_rows[at:])
        return {'ok':True,'id':target['id'],'position':at+1,'count':len(picked),'backup':saved}

    if action=='merge':
        first=text(body['first_id']); second=text(body['second_id'])
        if first['id']==second['id']: raise ValueError('请选择两个不同文本')
        title=body['title'].strip()
        if not title: raise ValueError('请填写合并后的标题')
        a,b=rows(first['id']),rows(second['id'])
        if [len(a),len(b)]!=body['counts']: raise ValueError('文本句数已变化，请重新打开合并窗口')
        saved=backup()
        for r in long_tasks.steps(a): provenance(r,first)
        for r in long_tasks.steps(b): provenance(r,second)
        order(first['id'],a+b)
        original=first['original']+'\n\n'+second['original']
        errors=[{'line':e.get('line'),'message':s['title']+'：'+e['message']} for s in (first,second) for e in json.loads(s['errors'])]
        db.execute('UPDATE texts SET title=?,source=?,original=?,digest=NULL,errors=? WHERE id=?',(title,first['source']+' / '+second['source'],original,json.dumps(errors,ensure_ascii=False),first['id']))
        info=db.execute('SELECT * FROM text_info WHERE text_id=?',(first['id'],)).fetchone()
        other=db.execute('SELECT * FROM text_info WHERE text_id=?',(second['id'],)).fetchone()
        data=json.loads(info['metadata']) if info else {}
        data.setdefault('merged_sources',[]).append({'title':second['title'],'source':second['source'],'folder_id':other['folder_id'] if other else None,'metadata':json.loads(other['metadata']) if other else {}})
        db.execute('INSERT INTO text_info VALUES(?,?,?,?) ON CONFLICT(text_id) DO UPDATE SET metadata=excluded.metadata,revision=excluded.revision',(first['id'],info['folder_id'] if info else None,json.dumps(data,ensure_ascii=False),(info['revision'] if info else 0)+1))
        import collaborators
        collaborators.combine_text(db,second['id'],first['id'])
        db.execute('DELETE FROM text_info WHERE text_id=?',(second['id'],))
        db.execute('DELETE FROM texts WHERE id=?',(second['id'],))
        return {'ok':True,'id':first['id'],'count':len(a)+len(b),'backup':saved}
    raise ValueError('未知管理操作')
