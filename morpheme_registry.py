"""Language-local morpheme identities, separate from lexemes and their analyses."""
import long_tasks
import json
import record_sources
import uuid
import hashlib
import component_links

TABLES=('morphemes','morpheme_components')
STATES=('pending','confirmed','disputed')

def realization(morpheme,form_id=None):
    """Resolve an explicit shared form, never infer a variant from spelling."""
    import morphology,sense_gloss
    if form_id is not None and not isinstance(form_id,str):raise ValueError('请选择有效的语素形式')
    variant=morphology.form_selection(morpheme['body'],form_id)
    body=morpheme['body']
    return dict(form=variant['form'] if variant else morpheme['form'],
                readings=[variant['pronunciation']] if variant and variant.get('pronunciation') else body.get('readings',[]),
                gloss=sense_gloss.effective(body,'gloss'),writings=body.get('writings',[]))


def save_plan(db,lid,xid,body,assignments=None):
    """Preview only unassigned components; never guess identity from spelling."""
    items=[];selected={(a['analysis_id'],a['component_id']):a for a in assignments or []}
    for a in body.get('word_structure',{}).get('analyses',[]):
        for c in a['components']:
            form=c.get('form','').strip() or '…'.join(c.get('segments',[]))
            if not form:continue
            old=db.execute('SELECT * FROM morpheme_components WHERE lexeme_id=? AND analysis_id=? AND component_id=?',(xid,a['id'],c['id'])).fetchone() if xid else None
            explicit=selected.get((a['id'],c['id']))
            if old and explicit is None:continue
            target=get(db,explicit['morpheme_id'],lid) if explicit and explicit.get('morpheme_id') else None
            form_id=(explicit.get('form_id') or None) if explicit else None
            if target:realization(target,form_id)
            elif form_id:raise ValueError('请先选择语素，再选择其变体')
            peers=[get(db,r['id'],lid) for r in db.execute('SELECT id FROM morphemes WHERE language_id=? AND form=? ORDER BY number',(lid,form))]
            items.append(dict(analysis_id=a['id'],component_id=c['id'],form=form,component=c,peers=peers,manual=explicit is not None,target=target,form_id=form_id,link_revision=old['revision'] if old else 0))
    token=hashlib.sha256(json.dumps([lid,xid,items],ensure_ascii=False,sort_keys=True).encode()).hexdigest()
    return dict(items=items,token=token)

def project_save_plan(body,plan,choices):
    """Resolve explicit selected forms before the basic headword is validated."""
    selected={(c['analysis_id'],c['component_id']):c for c in choices}
    components={(a['id'],c['id']):c for a in body.get('word_structure',{}).get('analyses',[]) for c in a['components']}
    for item in plan['items']:
        key=(item['analysis_id'],item['component_id']);choice=selected.get(key)
        target=item['target']
        if target:
            form_id=item['form_id']
        elif choice and choice.get('morpheme_id') and 'form_id' in choice:
            target=next((p for p in item['peers'] if p['id']==choice['morpheme_id']),None)
            if target is None:raise ValueError('同形语素选择已失效，请重新选择')
            form_id=choice['form_id']
        else:
            continue
        shared=realization(target,form_id)
        for field in ('form','readings'):components[key][field]=shared[field]


def apply_save_plan(db,x,lid,plan,choices):
    choices={(c['analysis_id'],c['component_id']):c for c in choices}
    for item in plan['items']:
        key=(item['analysis_id'],item['component_id']);choice=choices.get(key)
        if item['peers'] and not choice and not item['manual']:raise ValueError('存在同形语素，请选择关联对象或新建独立语素')
        mid=item['target']['id'] if item['target'] else choice.get('morpheme_id') if choice else None
        if mid and not item['manual'] and mid not in {p['id'] for p in item['peers']}:raise ValueError('同形语素选择已失效，请重新选择')
        c=item['component'];data={k:c.get(k,[]) for k in ('writings','features','segments','readings')}
        data.update({k:c.get(k,'') for k in ('gloss','notes','source','role')})
        if not mid:
            mid=mutate(db,'morpheme-save',{'form':item['form'],'body':data},lid)['id']
        m=get(db,mid,lid)
        import lexicon
        current=lexicon.get_lexeme(db,x['id'])
        selected_form={'form_id':item['form_id']} if item['target'] else {'form_id':choice['form_id']} if choice and 'form_id' in choice else {}
        mutate(db,'morpheme-assign',dict(lexeme_id=x['id'],lexeme_revision=current['revision'],components=[dict(analysis_id=key[0],component_id=key[1],revision=item['link_revision'])],morpheme_id=mid,morpheme_revision=m['revision'],**selected_form),lid,defer_writings=True)

    sync_missing_writings(db,lid,x['id'])


def sync_components(db, old, form, body):
    """Follow shared values while retaining explicitly different local realizations.

    Stable analysis/component IDs select owners. Sentence meaning updates run in
    the transaction hook; all changed owners share the same undo step.
    """
    rows = db.execute('SELECT DISTINCT x.id,x.body,x.target_kind FROM dictionary_targets x JOIN morpheme_components c ON c.lexeme_id=x.id WHERE c.morpheme_id=?', (old['id'],)).fetchall()
    for row in long_tasks.steps(rows):
        value=json.loads(row['body']);changed=False
        keys={(r['analysis_id'],r['component_id']):json.loads(r['body']).get('form_id') for r in db.execute('SELECT analysis_id,component_id,body FROM morpheme_components WHERE lexeme_id=? AND morpheme_id=?',(row['id'],old['id']))}
        for analysis in value.get('word_structure',{}).get('analyses',[]):
            for component in analysis.get('components',[]):
                identity=(analysis['id'],component['id'])
                if identity not in keys:continue
                before=realization(old,keys[identity]);after=realization(dict(old,form=form,body=body),keys[identity])
                for key in ('form','gloss','readings','writings'):
                    previous,current=before[key],after[key]
                    default=[] if key in ('readings','writings') else ''
                    if component.get(key,default)==previous and previous!=current:
                        component[key]=current;changed=True
        if changed:
            from dictionary_targets import write_body
            write_body(db,row,value)


def sync_missing_writings(db,lid,xid=None):
    """Materialize inherited spellings; never replace a local realization."""
    from copy import deepcopy
    owners={};owner_kinds={};shared={};changed=set();count=0
    sql='''SELECT x.id,x.target_kind,c.analysis_id,c.component_id,m.id morpheme_id FROM morpheme_components c
    JOIN (SELECT id,language_id,'lexeme' target_kind FROM lexemes
          UNION ALL SELECT id,language_id,'morpheme' FROM morphemes) x ON x.id=c.lexeme_id
    JOIN morphemes m ON m.id=c.morpheme_id
    WHERE x.language_id=? AND m.language_id=x.language_id'''
    args=[lid]
    if xid:sql+=' AND x.id=?';args.append(xid)
    for row in db.execute(sql,args):
        mid=row['morpheme_id'];owner=row['id']
        if mid not in shared:shared[mid]=record_sources.read(db,'morphemes',mid).get('writings',[])
        writings=shared[mid]
        if not writings:continue
        if owner not in owners:
            owner_kinds[owner]=row['target_kind']
            table='lexemes' if row['target_kind']=='lexeme' else 'morphemes'
            owners[owner]=record_sources.read(db,table,owner)
        body=owners[owner]
        for a in body.get('word_structure',{}).get('analyses',[]):
            if a['id']!=row['analysis_id']:continue
            for c in a['components']:
                if c['id']==row['component_id'] and not c.get('writings'):
                    c['writings']=deepcopy(writings);count+=1;changed.add(owner)
    ids=[]
    from dictionary_targets import write_body
    for key,body in owners.items():
        if key in changed:
            write_body(db,dict(id=key,target_kind=owner_kinds[key]),body);ids.append(key)
    return dict(lexemes=len(ids),components=count,ids=ids)


def initialize(db):
    db.executescript('''CREATE TABLE IF NOT EXISTS morphemes(id TEXT PRIMARY KEY,language_id TEXT NOT NULL,form TEXT NOT NULL,number INTEGER NOT NULL,body TEXT NOT NULL,revision INTEGER NOT NULL);
    CREATE UNIQUE INDEX IF NOT EXISTS morphemes_language_form ON morphemes(language_id,form,number);
    CREATE TABLE IF NOT EXISTS morpheme_components(id TEXT PRIMARY KEY,lexeme_id TEXT NOT NULL,analysis_id TEXT NOT NULL,component_id TEXT NOT NULL,morpheme_id TEXT NOT NULL,body TEXT NOT NULL,revision INTEGER NOT NULL);
    CREATE UNIQUE INDEX IF NOT EXISTS morpheme_component_identity ON morpheme_components(lexeme_id,analysis_id,component_id);
    CREATE INDEX IF NOT EXISTS morpheme_component_target ON morpheme_components(morpheme_id);''')

def text(v):
    if not isinstance(v,str):raise ValueError('语素字段须为文本')
    return v

def state(v):
    # Legacy SQL column retained for backup compatibility; it has no semantics.
    return 'confirmed'

def get(db,mid,lid=None,*,relational=True):
    fields='id,language_id,form,number,revision' if relational else '*'
    source='morphemes' if relational else 'morphemes_documents'
    r=db.execute('SELECT '+fields+' FROM '+source+' WHERE id=?',(mid,)).fetchone()
    if not r or lid is not None and r['language_id']!=lid:raise ValueError('语素不存在或不属于当前语言')
    r=dict(r)
    if relational:
        from dictionary_rows import raw_bodies
        r['body']=raw_bodies(db,'morpheme',[mid])[mid]
    else:r['body']=json.loads(r['body']);r.pop('rowid',None)
    r['display_number']=r['number'] if db.execute('SELECT count(*) FROM morphemes WHERE language_id=? AND form=?',(r['language_id'],r['form'])).fetchone()[0]>1 else None
    return r

def check_revision(row,value):
    if row['revision']!=value:raise ValueError('记录已变化，请刷新后重试')

def listing(db,lid,q='',page=1,status='',search=None,page_size=30,order='',*,ids_only=False,focus=''):
    if focus and not ids_only:
        from dictionary_paging import focused_page
        ids=listing(db,lid,q,1,status,search,page_size,order,ids_only=True)
        target=focused_page(ids,focus,page_size)
        result=listing(db,lid,q,target or page,status,search,page_size,order)
        return dict(result,focus_found=target is not None)
    if not db.in_transaction:db.execute('BEGIN')
    import entry_dates
    if order and order not in entry_dates.ORDERS:raise ValueError('语素排序方式无效')
    date=entry_dates.relational_date('m','morpheme') if record_sources.native(db) else None
    ordering=entry_dates.sql_order(order,'m',date=date) if order else 'm.form COLLATE NOCASE,m.number,m.id'
    from morpheme_search import MorphemeIndex
    from dictionary_paging import paginate
    paginate([],1,page_size)
    try:spec=json.loads(search) if isinstance(search,str) else search
    except ValueError:raise ValueError('搜索条件格式不正确')
    if spec is not None and not isinstance(spec,dict):raise ValueError('搜索条件格式不正确')
    import dictionary_read
    predicate=dictionary_read.predicate(db,lid,spec,q,field='form',kinds=('morpheme',))
    if predicate is None:
        import dictionary_own_index
        if record_sources.native(db) and (spec or {}).get('scope','all')=='all':
            predicate=dictionary_own_index.predicate(db,lid,spec,q,False,morphemes=True)
    if predicate is not None:
        where='' if lid=='all' else ' WHERE m.language_id=?';params=() if lid=='all' else (lid,)
        source='morphemes m'
        if predicate[0]:
            source="(SELECT record_id FROM ("+predicate[0]+") WHERE kind='morpheme') k CROSS JOIN morphemes m ON m.id=k.record_id";params=tuple(predicate[1])+params
        if ids_only:return [r[0] for r in db.execute('SELECT m.id FROM '+source+where+' ORDER BY '+ordering,params)]
        total=db.execute('SELECT count(*) FROM '+source+where,params).fetchone()[0]
        size=max(1,total) if str(page_size)=='all' else int(page_size);pages=max(1,(total+size-1)//size);page=max(1,min(int(page),pages))
        selected=db.execute('SELECT m.id,m.language_id,m.form,m.number,m.revision,(SELECT count(*) FROM morpheme_components c WHERE c.morpheme_id=m.id) component_count,(SELECT count(*) FROM morphemes peer WHERE peer.language_id=m.language_id AND peer.form=m.form) peers FROM '+source+where+' ORDER BY '+ordering+' LIMIT ? OFFSET ?',params+(size,(page-1)*size))
        rows=list(record_sources.with_bodies(db,'morphemes',selected))
        for r in rows:r['display_number']=r['number'] if r.pop('peers')>1 else None
        return dict(items=rows,total=total,page=page,pages=pages)
    selected=db.execute("SELECT m.id,m.language_id,m.form,m.number,m.revision, (SELECT count(*) FROM morpheme_components c WHERE c.morpheme_id=m.id) component_count FROM morphemes m WHERE ?='all' OR m.language_id=? ORDER BY m.form COLLATE NOCASE,m.number,m.id",(lid,lid))
    rows=list(record_sources.with_bodies(db,'morphemes',selected))
    counts={}
    for r in rows:counts[(r['language_id'],r['form'])]=counts.get((r['language_id'],r['form']),0)+1
    index=MorphemeIndex(db,lid,rows,search_spec=spec or {},query=q).prepare(spec or {})
    hits=[r for r in rows if index.matches(r,q)]
    if order:hits=entry_dates.sort_rows(hits,order)
    if ids_only:return [r['id'] for r in hits]
    from dictionary_paging import paginate
    result=paginate(hits,page,page_size)
    for r in result['items']:r['display_number']=r['number'] if counts[(r['language_id'],r['form'])]>1 else None
    return result


def current_component_ref(body,ref):
    """Read the live component by stable identity; preserve deleted evidence."""
    try:return {**ref,'snapshot':component_links.snapshot(body,ref['analysis_id'],ref['component_id'])},False
    except (ValueError,KeyError,TypeError):return ref,True


def components(db,xid,lid):
    import lexicon
    x=lexicon.get_lexeme(db,xid)
    if lid!='all' and x['language_id']!=lid:raise ValueError('请在词条所属语言中整理语素')
    links={(r['analysis_id'],r['component_id']):dict(r) for r in db.execute("SELECT *, 'confirmed' status FROM morpheme_components WHERE lexeme_id=?",(xid,))}
    items=[]
    for a in x['body'].get('word_structure',{}).get('analyses',[]):
        for c in a['components']:
            link=links.get((a['id'],c['id']))
            if link:
                link['review']=False
                _,link['source_missing']=current_component_ref(x['body'],json.loads(link['body']))
                link['morpheme']=get(db,link['morpheme_id'],x['language_id'])
                link['form_id']=json.loads(link['body']).get('form_id')
            items.append(dict(analysis_id=a['id'],analysis_title=a['title'],component=c,link=link))
    return dict(lexeme=x,items=items)

def detail(db,mid,lid):
    from dictionary_rows import targets
    if not db.in_transaction:db.execute('BEGIN')
    m=get(db,mid,None if lid=='all' else lid,relational=True);items=[]
    rows=db.execute('SELECT c.*,x.headword FROM morpheme_components c LEFT JOIN dictionary_targets x ON x.id=c.lexeme_id WHERE c.morpheme_id=? ORDER BY x.headword,c.id',(mid,)).fetchall()
    definitions=targets(db,[r['lexeme_id'] for r in rows])
    for r in rows:
        r=dict(r);r['body'],r['source_missing']=current_component_ref(definitions.get(r['lexeme_id'],{}).get('body',{}),json.loads(r['body']));r['review']=False;items.append(r)
    import dictionary_targets
    return {**m,'components':items,'references':dictionary_targets.references(db,mid),'dictionary_body':dictionary_targets.common(db,mid)}

def prepare_body(db,lid,b,old=None):
    form=text(b.get('form','')).strip()
    if not form:raise ValueError('请填写语素形式')
    data=b.get('body',{})
    if not isinstance(data,dict):raise ValueError('语素内容格式错误')
    data={**(old['body'] if old else {}),**data,**{k:text(data.get(k,'')) for k in ('gloss','notes')},'status':state(data.get('status','pending'))}
    from manual_status import clean
    data=clean({**data,'status':b.get('body',{}).get('status')})
    from homophones import readings
    import word_structure
    data['readings']=readings(data.get('readings',[]))
    data['writings']=word_structure.writings(data)
    seen=set();sense_rows=[]
    for s in long_tasks.steps(word_structure.rows(data.get('senses',[]))):
        sid=word_structure.identity(s,seen)
        sense_rows.append({**s,'id':sid,'gloss':text(s.get('gloss','')),'definition':text(s.get('definition',''))})
    data['senses']=sense_rows
    import dictionary_targets
    import multipart_forms
    data=multipart_forms.align_spellings(data,form,old,'form')
    data=dictionary_targets.normalize(db,lid,data,old)
    form,parts=multipart_forms.realization(form,data,require_circumfix=not old or 'form_parts' in b.get('body',{}) or not multipart_forms.circumfix(old['body']))
    if parts:data['form_parts']=parts
    data['variants']=clean_variants(db,lid,data)
    if multipart_forms.circumfix(data):
        for v in data['variants']:
            v['form'],v['form_parts']=multipart_forms.realization(v['form'],{**v,'entry_type':'circumfix'},require_circumfix=True)
    return form,data


def mutate(db,action,b,lid,*,defer_writings=False):
    import lexicon,languages
    languages.require(db,lid)
    if not db.in_transaction:db.execute('BEGIN IMMEDIATE')
    if action=='morpheme-sync-writings':return sync_missing_writings(db,lid)
    if action=='morpheme-save':
        old=get(db,b['id'],lid) if b.get('id') else None
        if old:check_revision(old,b.get('revision'))
        import dictionary_link_changes,lexicon
        common=lexicon.get_lexeme(db,old['id']) if old else None
        fingerprint=dictionary_link_changes.token(db,common,b) if common and b.get('link_change_token') else None
        form,data=prepare_body(db,lid,b,old)
        import categories
        categories.register_usages(db,lid,data,strict=True)
        import entry_dates
        entry_dates.stamp(data,old['body'] if old else None)
        allowed={r['id'] for r in db.execute('SELECT id FROM writing_types WHERE language_id=?',(lid,))}
        if any(w['type_id'] not in allowed for w in data['writings']):raise ValueError('语素书写类型不属于当前语言')
        number=old['number'] if old and old['form']==form else db.execute('SELECT COALESCE(MAX(number),0)+1 FROM morphemes WHERE language_id=? AND form=?',(lid,form)).fetchone()[0]
        mid=old['id'] if old else str(uuid.uuid4())
        if common:dictionary_link_changes.apply(db,common,data,b,fingerprint)
        import dictionary_rows
        columns=dict(form=form,number=number)
        if not old:columns.update(language_id=lid,revision=1)
        dictionary_rows.write(db,'morpheme',mid,data,columns=columns,insert=not old)
        if old:sync_components(db,old,form,data)
        return get(db,mid,lid)
    if action=='morpheme-assign':
        x=lexicon.get_lexeme(db,b.get('lexeme_id'))
        if x['language_id']!=lid:raise ValueError('不能跨语言整理组分')
        check_revision(x,b.get('lexeme_revision'))
        selected=b.get('components')
        if not isinstance(selected,list) or not selected or len(selected)>500:raise ValueError('请选择需要整理的组分')
        # Validate every selection before changing anything; the transaction also covers creation.
        planned=[];seen=set()
        for c in long_tasks.steps(selected):
            ref=component_links.choose(x['body'],c)
            if not ref:raise ValueError('请选择具体组分')
            key=(ref['analysis_id'],ref['component_id'])
            if key in seen:raise ValueError('组分不可重复选择')
            seen.add(key)
            old=db.execute('SELECT * FROM morpheme_components WHERE lexeme_id=? AND analysis_id=? AND component_id=?',(x['id'],*key)).fetchone()
            if (old['revision'] if old else 0)!=c.get('revision',0):raise ValueError('组分整理结果已变化，请刷新后重试')
            planned.append((ref,old))
        mid=b.get('morpheme_id')
        if b.get('create'):
            if mid:raise ValueError('不能同时新建和选择已有语素')
            mid=mutate(db,'morpheme-save',b['create'],lid)['id']
        if mid:
            m=get(db,mid,lid)
            if not b.get('create'):check_revision(m,b.get('morpheme_revision'))
            form_id=b.get('form_id') or None
            shared=realization(m,form_id)
            # Explicit form selection also materializes its spelling and reading.
            # Legacy assignment requests retain their local realization.
            if 'form_id' in b:
                changed=False
                for ref,_ in planned:
                    for analysis in x['body'].get('word_structure',{}).get('analyses',[]):
                        if analysis['id']!=ref['analysis_id']:continue
                        for component in analysis['components']:
                            if component['id']!=ref['component_id']:continue
                            for key in ('form','readings'):
                                if component.get(key,[] if key=='readings' else '')!=shared[key]:
                                    component[key]=shared[key];changed=True
                if changed:
                    from dictionary_targets import write_body
                    write_body(db,x,x['body'])
                for ref,_ in planned:ref['snapshot']=component_links.snapshot(x['body'],ref['analysis_id'],ref['component_id'])
        elif b.get('form_id'):raise ValueError('请先选择语素，再选择其变体')
        affected={mid} if mid else set()
        affected.update(old['morpheme_id'] for _,old in planned if old)
        for ref,old in long_tasks.steps(planned):
            from manual_status import clean
            ref=clean({**ref,'status':b.get('status')})
            if mid:ref['form_id']=form_id
            if not mid:
                if old:db.execute('DELETE FROM morpheme_components WHERE id=?',(old['id'],))
            else:
                db.execute('INSERT INTO morpheme_components(id,lexeme_id,analysis_id,component_id,morpheme_id,body,revision) VALUES(?,?,?,?,?,?,?) ON CONFLICT(id) DO UPDATE SET morpheme_id=excluded.morpheme_id,body=excluded.body,revision=excluded.revision',(old['id'] if old else str(uuid.uuid4()),x['id'],ref['analysis_id'],ref['component_id'],mid,json.dumps(ref,ensure_ascii=False),(old['revision'] if old else 0)+1))
        for affected_id in long_tasks.steps(affected):db.execute('UPDATE morphemes SET revision=revision+1 WHERE id=?',(affected_id,))
        if not defer_writings:sync_missing_writings(db,lid,x['id'])
        return dict(ok=True,morpheme_id=mid,count=len(planned))
    if action=='morpheme-merge':
        source=get(db,b.get('id'),lid);target=get(db,b.get('target_id'),lid)
        if source['id']==target['id']:raise ValueError('请选择另一个语素')
        check_revision(source,b.get('revision'));check_revision(target,b.get('target_revision'))
        if b.get('confirmed') is not True:raise ValueError('请确认归并目标及保留内容')
        from morpheme_conversion import merge
        return merge(db,lid,source,target)
    if action=='morpheme-unassign':
        r=db.execute('SELECT * FROM morpheme_components WHERE id=?',(b.get('id'),)).fetchone()
        if not r:raise ValueError('关联已不存在')
        get(db,r['morpheme_id'],lid);check_revision(r,b.get('revision'))
        db.execute('DELETE FROM morpheme_components WHERE id=?',(r['id'],))
        db.execute('UPDATE morphemes SET revision=revision+1 WHERE id=?',(r['morpheme_id'],));return {'ok':True}
    if action=='morpheme-delete':
        old=get(db,b.get('id'),lid);check_revision(old,b.get('revision'))
        import dictionary_targets
        if any(dictionary_targets.references(db,old['id']).values()):raise ValueError('此语素仍有关联例句，请先解除关联或归并到另一语素')
        if db.execute('SELECT 1 FROM morpheme_components WHERE morpheme_id=?',(old['id'],)).fetchone():raise ValueError('此语素仍有关联组分，请先解除关联或归并到另一语素')
        db.execute('DELETE FROM morphemes WHERE id=?',(old['id'],));return {'ok':True}
    raise ValueError('未知语素操作')

def export_bundle(db,languages,lexemes):
    rows=record_sources.with_bodies(db,'morphemes',(r for r in db.execute('SELECT id,language_id,form,number,revision FROM morphemes') if r['language_id'] in languages))
    return {'morphemes':[record_sources.portable_row(r) for r in rows], 'morpheme_components':[dict(r) for r in db.execute("SELECT *, 'confirmed' status FROM morpheme_components") if r['lexeme_id'] in lexemes]}

def import_bundle(db,bundle,language_map,xmap,submap,classmap,type_map,tagmap,include_components=True,semantic_map=None):
    mapping={}
    for r in long_tasks.steps(bundle.get('morphemes',[])):
        data=json.loads(r['body'])
        if semantic_map is not None:data['semantic_classes']=[semantic_map[v] for v in data.get('semantic_classes',[])]
        for fixed in ('@morpheme','@main'):submap[(r['id'],fixed)]=fixed
        def remap_metadata(body,top=True):
            body['features']=[tagmap.get(v,v) for v in body.get('features',[])]
            parts=[*body.get('variants',[]),*body.get('orthographies',[]),*body.get('usages',[]),*body.get('senses',[]),*(s for u in body.get('usages',[]) for s in u.get('senses',[]))]
            for v in parts:
                if 'id' in v:
                    old_id=v['id']
                    if top:v['id']=submap.setdefault((r['id'],old_id),old_id if old_id in ('@morpheme','@main') else str(uuid.uuid4()))
                v['features']=[tagmap.get(f,f) for f in v.get('features',[])]
                if v.get('type_id'):v['type_id']=type_map[v['type_id']]
            if body.get('primary_sense_id') and top:body['primary_sense_id']=submap[(r['id'],body['primary_sense_id'])]
            for w in long_tasks.steps(body.get('writings',[])):w['type_id']=type_map.get(w['type_id'],w['type_id'])
            for old in long_tasks.steps(body.get('merged_records',[])):remap_metadata(old['body'],False)
        remap_metadata(data)
        import paradigms
        paradigms.remap(data,r['id'],submap)
        new=mutate(db,'morpheme-save',{'form':r['form'],'body':data},language_map[r['language_id']]);mapping[r['id']]=new['id']
        import entry_dates
        entry_dates.imported(db,'morphemes',new['id'],json.loads(r['body']))
        if type(r.get('number')) is not int or r['number']<1:raise ValueError('语素同形编号须为正整数')
        if not db.execute('SELECT 1 FROM morphemes WHERE language_id=? AND form=? AND number=? AND id!=?',(new['language_id'],new['form'],r['number'],new['id'])).fetchone():
            db.execute('UPDATE morphemes SET number=? WHERE id=?',(r['number'],new['id']))
        body=data
        if body.get('merged_records'):
            new['body']['merged_records']=body['merged_records']
            if body.get('created_at') is None:new['body'].pop('created_at',None)
            else:new['body']['created_at']=entry_dates.parse(body['created_at'])
            import dictionary_rows
            dictionary_rows.write(db,'morpheme',new['id'],new['body'],bump=False)
    if include_components:import_components(db,bundle,xmap,mapping,submap,classmap,type_map,tagmap)
    return mapping

def import_components(db,bundle,xmap,mapping,submap,classmap,type_map,tagmap):
    for r in long_tasks.steps(bundle.get('morpheme_components',[])):
        if r['lexeme_id'] not in xmap or r['morpheme_id'] not in mapping:raise ValueError('语素整理记录缺少所属词条或语素')
        ref=component_links.remap(json.loads(r['body']),r['lexeme_id'],xmap,submap,classmap,type_map,tagmap)
        if ref.get('form_id'):
            key=(r['morpheme_id'],ref['form_id'])
            if key not in submap:raise ValueError('语素组分关联缺少具体变体记录')
            ref['form_id']=submap[key]
        from manual_status import clean
        ref=clean({**ref,'status':r.get('status')})
        if (r['analysis_id'],r['component_id'])!=(ref['analysis_id'],ref['component_id']):raise ValueError('语素整理记录的组分身份不一致')
        db.execute('INSERT INTO morpheme_components(id,lexeme_id,analysis_id,component_id,morpheme_id,body,revision) VALUES(?,?,?,?,?,?,1)',(str(uuid.uuid4()),xmap[r['lexeme_id']],r['analysis_id'],r['component_id'],mapping[r['morpheme_id']],json.dumps(ref,ensure_ascii=False)))

def validate(db,targets=None):
    if targets is None:
        import dictionary_rows
        ids=[r[0] for r in db.execute('SELECT id FROM morphemes')]
        targets=dictionary_rows.targets(db,ids,prepare=False)
    forms={}
    for row in long_tasks.steps(targets.values()):
        if row['target_kind']=='morpheme':
            forms[row['id']]={v['id'] for v in clean_variants(db,row['language_id'],row['body'])}
    if db.execute('SELECT 1 FROM morpheme_components c LEFT JOIN morphemes m ON m.id=c.morpheme_id LEFT JOIN dictionary_targets x ON x.id=c.lexeme_id WHERE m.id IS NULL OR x.id IS NULL OR x.language_id!=m.language_id LIMIT 1').fetchone():raise ValueError('语素整理关联的词条和语素须存在且属于同一语言；删除词条前请先解除组分的语素整理关联')
    for row in long_tasks.steps(db.execute('SELECT morpheme_id,body FROM morpheme_components')):
        validate_component_form(json.loads(row['body']),forms[row['morpheme_id']])

def validate_component_form(value,variants):
    ref=component_links.validate(value)
    if ref.get('form_id') and ref['form_id'] not in variants:raise ValueError('关联的语素变体仍在使用，请先调整组分关联再删除变体')

def clean_variants(db,lid,body):
    import morphology,categories,lexicon
    variants=lexicon.normalize(dict(variants=body.get('variants',[])))['variants']
    for v in variants:morphology.check_features(db,lid,v.get('features',[]))
    categories.register_usages(db,lid,dict(variants=variants),strict=True)
    return variants
