"""Independent text copies, with fresh evidence and recording alignment identities."""
import hashlib
import json
import uuid
import journal
import long_tasks


def uid():return str(uuid.uuid4())


def source(db,tid,lid='all'):
    row=db.execute('SELECT rowid,* FROM texts WHERE id=?',(tid,)).fetchone()
    if not row or lid not in ('all',row['language_id']):raise ValueError('请选择当前语言的一篇文本')
    return row


def token(db,tid):
    return hashlib.sha256((tid+':'+journal.workspace_revision(db)).encode()).hexdigest()


def preview(db,tid,lid):
    if not db.in_transaction:db.execute('BEGIN')
    row=source(db,tid,lid)
    return dict(id=tid,title=row['title'],language_id=row['language_id'],count=db.execute('SELECT COUNT(*) FROM entries WHERE text_id=?',(tid,)).fetchone()[0],token=token(db,tid))


def insert(db,table,row):
    keys=','.join(row);db.execute('INSERT INTO '+table+'('+keys+') VALUES('+','.join('?' for _ in row)+')',list(row.values()))


def alignments(db,entries,spans,title):
    """Copy only this text's intervals and their hierarchy into separate sessions.

    Media files and participant/code catalogs are shared; editing a copied
    interval never changes its original. Unrelated sentences are not copied.
    """
    sessions={r[0] for eid in entries for r in db.execute('SELECT session_id FROM timeline_intervals WHERE entry_id=?',(eid,))}
    copied_sessions={}
    for sid in long_tasks.steps(sorted(sessions)):
        rows={r['id']:dict(r) for r in db.execute('SELECT * FROM timeline_intervals WHERE session_id=?',(sid,))}
        keep={rid for rid,r in rows.items() if r['entry_id'] in entries}
        # Retain dependent annotations underneath copied sentences and ancestors.
        changed=True
        while changed:
            changed=False
            for rid,r in rows.items():
                if rid in keep or (r['parent_id'] in keep and not r['entry_id']):
                    for related in (rid,r['parent_id']):
                        if related in rows and related not in keep:keep.add(related);changed=True
        session=dict(db.execute('SELECT * FROM timeline_sessions WHERE id=?',(sid,)).fetchone())
        session.update(id=uid(),name=title+' · '+session['name'],revision=1)
        session['position']=db.execute('SELECT COALESCE(MAX(position),-1)+1 FROM timeline_sessions WHERE language_id=?',(session['language_id'],)).fetchone()[0]
        copied_sessions[sid]=session['id'];insert(db,'timeline_sessions',session)
        tracks=[dict(r) for r in db.execute('SELECT * FROM timeline_tracks WHERE session_id=?',(sid,))]
        tmap={r['id']:uid() for r in tracks};imap={rid:uid() for rid in keep}
        for track in tracks:
            track.update(id=tmap[track['id']],session_id=session['id'],parent_id=tmap.get(track['parent_id']),revision=1);insert(db,'timeline_tracks',track)
        for rid in long_tasks.steps(sorted(keep)):
            r=rows[rid];r.update(id=imap[rid],session_id=session['id'],track_id=tmap[r['track_id']],parent_id=imap.get(r['parent_id']),entry_id=entries.get(r['entry_id']),revision=1);insert(db,'timeline_intervals',r)
            for link in db.execute('SELECT * FROM code_time_links WHERE interval_id=?',(rid,)).fetchall():
                if link['span_id'] in spans:db.execute('INSERT INTO code_time_links VALUES(?,?,?,1)',(uid(),spans[link['span_id']],imap[rid]))
    return copied_sessions


def copy(db,body):
    row=source(db,body.get('id'))
    if body.get('token')!=token(db,row['id']):raise ValueError('项目内容已变化，请重新打开复制文本窗口')
    title=body.get('title')
    if not isinstance(title,str) or not title.strip():raise ValueError('请填写新文本标题')
    title=title.strip();tid=uid()
    insert(db,'texts',dict(id=tid,title=title,source=row['source'],original=row['original'],digest=None,errors=row['errors'],language_id=row['language_id']))
    info=db.execute('SELECT * FROM text_info WHERE text_id=?',(row['id'],)).fetchone()
    metadata=json.loads(info['metadata']) if info else {}
    metadata.setdefault('_sidebar_order',row['rowid'])
    insert(db,'text_info',dict(text_id=tid,folder_id=info['folder_id'] if info else None,metadata=json.dumps(metadata,ensure_ascii=False),revision=1))
    # Preserve manual/inherited attribution rather than freezing inherited people.
    attribution=db.execute("SELECT * FROM collaborator_assignments WHERE kind='text' AND record_id=?",(row['id'],)).fetchone()
    if attribution:
        r=dict(attribution);r.update(id=uid(),record_id=tid,revision=1);insert(db,'collaborator_assignments',r)
    from operations import copy_entry
    mapping={};spans={}
    for position,entry in long_tasks.steps(enumerate(list(db.execute('SELECT * FROM entries WHERE text_id=? ORDER BY position,id',(row['id'],))),1)):
        eid=copy_entry(db,entry,tid,position,spans);mapping[entry['id']]=eid
        # copy_entry intentionally freezes effective people when moving a sentence;
        # a whole text copy instead retains the original inheritance mode.
        db.execute("DELETE FROM collaborator_assignments WHERE kind='corpus' AND record_id=?",(eid,))
        attribution=db.execute("SELECT * FROM collaborator_assignments WHERE kind='corpus' AND record_id=?",(entry['id'],)).fetchone()
        if attribution:
            r=dict(attribution);r.update(id=uid(),record_id=eid,revision=1);insert(db,'collaborator_assignments',r)
    sessions=alignments(db,mapping,spans,title)
    ordering=db.execute('SELECT * FROM timeline_text_orders WHERE id=?',(row['id'],)).fetchone()
    if ordering and ordering['session_id'] in sessions:db.execute('INSERT INTO timeline_text_orders VALUES(?,?,1)',(tid,sessions[ordering['session_id']]))
    return dict(ok=True,id=tid,count=len(mapping),language_id=row['language_id'],timelines=len(sessions))
