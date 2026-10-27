import object_media
import json
import uuid
import journal
import annotations
import grammar
import morphology
import categories
import analysis_workspace
import timeline
import collaborators
import grammar_survey
import example_groups
import example_numbering
import fieldwork_notes
import code_switching
import dictionary_organization
import gloss_inheritance

TABLES = ('texts','entries','history','folders','text_info','undo_steps','undo_settings','languages','undo_scopes','corpus_units','lexemes','lexical_links','writing_types','dictionary_examples')+annotations.TABLES+grammar.TABLES+morphology.TABLES+categories.TABLES+analysis_workspace.TABLES+timeline.TABLES+collaborators.TABLES+grammar_survey.TABLES+fieldwork_notes.TABLES+object_media.TABLES+code_switching.TABLES


import morpheme_registry
import synonyms
import link_review
TABLES += link_review.TABLES
TABLES += example_groups.TABLES
TABLES += dictionary_organization.TABLES+morpheme_registry.TABLES+synonyms.TABLES+gloss_inheritance.TABLES
TABLES = example_numbering.TABLES + TABLES

def initialize(db):
    db.executescript('''CREATE TABLE IF NOT EXISTS folders(id TEXT PRIMARY KEY,name TEXT NOT NULL,position INTEGER,metadata TEXT NOT NULL DEFAULT '{}',revision INTEGER NOT NULL DEFAULT 1);
    CREATE TABLE IF NOT EXISTS text_info(text_id TEXT PRIMARY KEY,folder_id TEXT,metadata TEXT NOT NULL DEFAULT '{}',revision INTEGER NOT NULL DEFAULT 1);''')


def update(db, action, body):
    if not db.in_transaction: db.execute('BEGIN IMMEDIATE')
    if action=='organize-text':
        lid=journal.scope.get()
        rows=[dict(r) for r in db.execute("SELECT t.id,COALESCE(i.folder_id,'') folder_id,COALESCE(i.revision,0) revision,COALESCE(i.metadata,'{}') metadata FROM texts t LEFT JOIN text_info i ON i.text_id=t.id WHERE t.language_id=? ORDER BY COALESCE(json_extract(i.metadata,'$._sidebar_order'),t.rowid),t.rowid",(lid,))]
        snapshot=[{k:r[k] for k in ('id','folder_id','revision')} for r in rows]
        if body.get('snapshot')!=snapshot:raise ValueError('文本或文件夹归属已变化，请刷新侧栏后重新拖动')
        tid=body.get('id');folder=body.get('folder_id') or '';before=body.get('before_id')
        if tid not in [r['id'] for r in rows]:raise ValueError('文本不属于当前语言')
        if folder and not db.execute('SELECT 1 FROM folders WHERE id=? AND language_id=?',(folder,lid)).fetchone():raise ValueError('只能拖入当前语言的文本文件夹，不能拖入独立例句库')
        if before and not any(r['id']==before and r['folder_id']==folder for r in rows):raise ValueError('目标位置已变化，请刷新后重新拖动')
        if before==tid:return {'ok':True}
        moving=next(r for r in rows if r['id']==tid);old_folder=moving['folder_id'];moving['folder_id']=folder
        ordered=[r for r in rows if r['id']!=tid]
        at=next((i for i,r in enumerate(ordered) if r['id']==before),len(ordered)) if before else max((i+1 for i,r in enumerate(ordered) if r['folder_id']==folder),default=len(ordered))
        ordered.insert(at,moving)
        if [r['id'] for r in ordered]==[r['id'] for r in rows] and old_folder==folder:return {'ok':True}
        for position,r in enumerate(ordered,1):
            data=json.loads(r['metadata'])
            if data.get('_sidebar_order')==position and not (r['id']==tid and old_folder!=folder):continue
            data['_sidebar_order']=position
            db.execute('INSERT INTO text_info VALUES(?,?,?,?) ON CONFLICT(text_id) DO UPDATE SET folder_id=excluded.folder_id,metadata=excluded.metadata,revision=excluded.revision',(r['id'],r['folder_id'] or None,json.dumps(data,ensure_ascii=False),r['revision']+1))
        return {'ok':True}
    if action=='save-text-info':
        tid=body['id']
        if not db.execute('SELECT id FROM texts WHERE id=?',(tid,)).fetchone(): raise ValueError('文本不存在')
        old=db.execute('SELECT * FROM text_info WHERE text_id=?',(tid,)).fetchone()
        if body['revision']!=(old['revision'] if old else 0): raise ValueError('元信息已更新，请重新打开文本后编辑')
        title=body['title'].strip()
        if not title: raise ValueError('文本标题不能为空')
        folder=body.get('folder_id') or None
        if folder and not db.execute('SELECT f.id FROM folders f JOIN texts t ON t.language_id=f.language_id WHERE f.id=? AND t.id=?',(folder,tid)).fetchone(): raise ValueError('文件夹须属于文本所在的语言')
        if 'collaborators' in body:collaborators.save(db,{**body['collaborators'],'kind':'text','id':tid},journal.scope.get())
        data=body['metadata']
        if not isinstance(data,dict): raise ValueError('元信息格式不正确')
        # Retain provenance gathered by earlier merges even when editing fields.
        if old:
            previous=json.loads(old['metadata'])
            if 'merged_sources' in previous: data['merged_sources']=previous['merged_sources']
            if '_sidebar_order' in previous:data['_sidebar_order']=previous['_sidebar_order']
        db.execute('INSERT INTO text_info VALUES(?,?,?,?) ON CONFLICT(text_id) DO UPDATE SET folder_id=excluded.folder_id,metadata=excluded.metadata,revision=excluded.revision',(tid,folder,json.dumps(data,ensure_ascii=False),body['revision']+1))
        db.execute('UPDATE texts SET title=?,source=? WHERE id=?',(title,body.get('source',''),tid))
        return {'ok':True}
    if action=='save-folder':
        name=body['name'].strip()
        if not name: raise ValueError('文件夹名称不能为空')
        if not isinstance(body['metadata'],dict): raise ValueError('文件夹信息格式不正确')
        fid=body.get('id')
        if fid:
            old=db.execute('SELECT * FROM folders WHERE id=?',(fid,)).fetchone()
            if not old or old['revision']!=body['revision']: raise ValueError('文件夹已变化，请重新打开')
            db.execute('UPDATE folders SET name=?,metadata=?,revision=revision+1 WHERE id=?',(name,json.dumps(body['metadata'],ensure_ascii=False),fid))
        else:
            fid=str(uuid.uuid4())
            pos=db.execute('SELECT COALESCE(MAX(position),0)+1 FROM folders WHERE language_id=?',(journal.scope.get(),)).fetchone()[0]
            db.execute('INSERT INTO folders(id,name,position,metadata,language_id) VALUES(?,?,?,?,?)',(fid,name,pos,json.dumps(body['metadata'],ensure_ascii=False),journal.scope.get()))
        return {'ok':True,'id':fid}
    if action=='delete-folder':
        if body.get('confirmed') is not True: raise ValueError('请确认删除文件夹')
        row=db.execute('SELECT revision FROM folders WHERE id=?',(body['id'],)).fetchone()
        if not row or row['revision']!=body['revision']: raise ValueError('文件夹已变化，请重新打开')
        db.execute('UPDATE text_info SET folder_id=NULL,revision=revision+1 WHERE folder_id=?',(body['id'],))
        db.execute('DELETE FROM folders WHERE id=?',(body['id'],))
        return {'ok':True}
    if action=='order-folder':
        rows=list(db.execute('SELECT id FROM folders WHERE language_id=? ORDER BY position,id',(journal.scope.get(),)))
        ids=[r['id'] for r in rows]
        if body['id'] not in ids or body['direction'] not in (-1,1): raise ValueError('无效的排序操作')
        i=ids.index(body['id']); j=i+body['direction']
        if 0<=j<len(ids): ids[i],ids[j]=ids[j],ids[i]
        for n,fid in enumerate(ids): db.execute('UPDATE folders SET position=? WHERE id=?',(n+1,fid))
        return {'ok':True}
    raise ValueError('未知元信息操作')
