"""Literal dictionary replacement: preview, revalidate, one transactional undo step."""
import long_tasks
import copy
import hashlib
import json
from collections import Counter,defaultdict
import dictionary_read
import lexicon
import homonyms
import text_replace
import analysis_workspace
import journal
import morpheme_registry
import paradigms
import record_sources
import replacement_preview
from morpheme_search import MorphemeIndex

FIELDS={'all':'全部可替换文字','headword':'词形','variant':'变体形式','writing':'词条书写形式','short_gloss':'简短释义','definition':'详细释义','notes':'备注','tag_value':'使用标签值'}
SENSITIVE={'all','headword','variant','short_gloss'}
MORPHEME_FIELDS={'all':'全部可替换文字','form':'语素形式','variant':'变体形式','writing':'书写形式','short_gloss':'简短释义','definition':'详细释义','readings':'读音','conditions':'变体出现条件','notes':'备注','tag_value':'使用标签值'}
VALUE_SLOTS={'definition':('definition',),'notes':('notes','note','homonym_note'),
             'writing':('text',),'variant':('form',),'tag_value':('value',),
             'conditions':('conditions',),'short_gloss':('short_gloss','gloss')}

def settings(b):
    opt=text_replace.settings({**b,'field':'ipa'})
    opt['kind']=b.get('kind','lexeme')
    if opt['kind'] not in ('lexeme','morpheme'):raise ValueError('词典条目类型无效')
    if b.get('field') not in (MORPHEME_FIELDS if opt['kind']=='morpheme' else FIELDS):raise ValueError('请选择词典替换字段')
    opt['find_only']=b.get('find_only',False)
    if type(opt['find_only']) is not bool:raise ValueError('查找设置无效')
    opt['field']=b['field'];opt.pop('text_id')
    if opt['field']=='writing':
        opt['writing_type']=b.get('writing_type','')
        if not isinstance(opt['writing_type'],str):raise ValueError('请选择当前语言的书写类型')
    opt['scope']=b.get('scope','language');opt['lexeme_id']=b.get('morpheme_id','') if opt['kind']=='morpheme' else b.get('lexeme_id','');opt['query']=b.get('query','')
    if opt['scope'] not in ('language','current','search') or any(not isinstance(opt[k],str) for k in ('lexeme_id','query')):raise ValueError('词典替换范围无效')
    opt['search']=b.get('search',{})
    if not isinstance(opt['search'],dict):raise ValueError('词典搜索条件无效')
    opt['scope_ids']=b.get('scope_ids') if opt['scope']=='search' else None
    if opt['scope_ids'] is not None and (not isinstance(opt['scope_ids'],list) or len(opt['scope_ids'])>10000 or any(not isinstance(v,str) for v in opt['scope_ids'])):raise ValueError('搜索结果范围无效')
    if opt['scope']=='current' and not opt['lexeme_id']:raise ValueError('请先选择词条')
    return opt

def cells(row,field,kind='lexeme',writing_type=''):
    labels=MORPHEME_FIELDS if kind=='morpheme' else FIELDS
    if field=='all':
        for name in labels:
            if name!='all':yield from cells(row,name,kind)
        return
    if field in ('headword','form'):yield [field],row[field],labels[field];return
    def walk(value,path):
        if isinstance(value,dict):
            for key,v in value.items():
                p=path+[key]
                match=(field in ('short_gloss','definition') and (key==field and ('senses' in path or 'meanings' in path and 'paradigms' in path) or kind=='morpheme' and field=='short_gloss' and key=='gloss' and (path==['body'] or 'senses' in path))
                       or field=='notes' and key in ('notes','note','homonym_note')
                       or field=='tag_value' and key=='value' and 'tags' in path
                       or field=='variant' and key=='form' and path[:2]==['body','variants']
                       or field=='writing' and key=='text' and (path[:2]==['body','writings' if kind=='morpheme' else 'orthographies'] or path[:2]==['body','word_structure'] and path[-2]=='writings') and (not writing_type or value.get('type_id')==writing_type)
                       or field=='conditions' and key=='conditions' and path[:2]==['body','variants'])
                if kind=='morpheme' and key=='merged_records':continue
                if kind=='morpheme' and key=='usages':
                    # Meanings are edited through native fields; usage notes from
                    # converted words remain independently editable/searchable.
                    for i,usage in enumerate(v):
                        if field=='notes' and usage.get('notes'):yield p+[i,'notes'],usage['notes'],labels[field]+' · 原词类用法'
                    continue
                if field=='readings' and key=='readings' and path==['body']:
                    for i,reading in enumerate(v):yield p+[i],reading,labels[field]
                elif match and isinstance(v,str):yield p,v,labels[field]+' · '+'.'.join(str(x+1) if isinstance(x,int) else x for x in path[1:])
                elif isinstance(v,(dict,list)):yield from walk(v,p)
        elif isinstance(value,list):
            for i,v in enumerate(value):yield from walk(v,path+[i])
    # Ordinary additions belong to their own fields; replacements use free text.
    # Existing inherited table cells retain their explicit override behavior.
    yield from walk(paradigms.project(row['body'],ordinary=False),['body'])

def scope_rows(db,opt,lid,regex):
    morph=opt['kind']=='morpheme';table='morphemes' if morph else 'lexemes'
    form='form' if morph else 'headword'
    scope=opt['scope'];fixed=opt['scope_ids']
    simple=(not opt['query'].strip() and opt['search'].get('conditions',[])==[]
            and dictionary_read.predicate(db,lid,opt['search'],field=form) is not None)
    where=f'FROM {table} WHERE language_id=?'
    broad=scope in ('language','search') and fixed is None and simple
    if broad and opt['field']==form:
        count=db.execute('SELECT COUNT(*) '+where,(lid,)).fetchone()[0]
        predicate,args=text_replace.literal_filter(db,form,opt,regex)
        source=db.execute(f'SELECT * {where} AND {predicate} ORDER BY rowid',(lid,*args))
        return list(record_sources.with_bodies(db,table,source)),count
    if broad and record_sources.native(db):
        candidates=value_candidates(db,opt,lid,regex,table,form)
        if candidates is not None:
            count=db.execute('SELECT COUNT(*) '+where,(lid,)).fetchone()[0]
            return list(record_sources.with_bodies(db,table,candidates)),count
    ids=None
    if scope=='current':
        if not db.execute(f'SELECT 1 {where} AND id=?',(lid,opt['lexeme_id'])).fetchone():
            raise ValueError('词条已不存在或不属于当前语言')
        ids={opt['lexeme_id']}
    elif fixed is not None:
        ids=set(fixed)
    if fixed is None and not simple and not morph:
        matches=set(lexicon.list_lexemes(db,lid,opt['query'],ids_only=True,search=opt['search']))
        ids=matches if ids is None else ids & matches
    if ids is None:
        source=db.execute('SELECT * '+where+' ORDER BY rowid',(lid,))
    else:
        keys=list(ids);source=[]
        for start in range(0,len(keys),400):
            batch=keys[start:start+400];marks=','.join('?' for _ in batch)
            source.extend(dict(row) for row in db.execute(
                f'SELECT rowid AS source_order,* {where} AND id IN ({marks})',(lid,*batch)))
        if fixed is not None and len(source)!=len(ids):
            raise ValueError('原搜索范围中的词条已删除或移动，请重新打开替换')
        source.sort(key=lambda row:row['source_order'])
        for row in source:row.pop('source_order')
    rows=list(record_sources.with_bodies(db,table,source))
    if fixed is None and not simple and morph:
        index=MorphemeIndex(db,lid,rows).prepare(opt['search'])
        rows=[r for r in rows if index.matches(r,opt['query'])]
    return rows,len(rows)


def value_candidates(db,opt,lid,regex,table,form):
    """Coarse SQLite filtering; cells() still checks the exact paths and text."""
    from dictionary_rows import LOOKUP_VALUES,lookup_values
    field,kind=opt['field'],opt['kind']
    all_fields=field=='all' and kind=='lexeme' and not opt['find_only']
    slots=tuple(dict.fromkeys(slot for group in VALUE_SLOTS.values() for slot in group)) if all_fields else VALUE_SLOTS.get(field)
    if not slots:return None
    marks=','.join('?' for _ in slots)
    predicate,args=text_replace.literal_filter(db,'v.value',opt,regex)
    lookup=f"(v.slot IN ({marks}) AND {predicate})"
    if all_fields or field=='short_gloss':
        # An inherited paradigm meaning is composed at read time.
        lookup+=" OR (v.slot='gloss_mode' AND v.value='inherit')"
    sql=f"""WITH candidates AS MATERIALIZED (
        SELECT v.target_id FROM {lookup_values(db)}
        WHERE {LOOKUP_VALUES} AND v.target_kind=? AND ({lookup})
        GROUP BY v.target_id"""
    params=[kind,*slots,*args]
    if all_fields:
        predicate,args=text_replace.literal_filter(db,'d.'+form,opt,regex)
        sql+=f' UNION SELECT d.id FROM {table} d WHERE d.language_id=? AND {predicate}'
        params.extend([lid,*args])
    return db.execute(sql+f""" ) SELECT d.* FROM candidates c CROSS JOIN {table} d ON d.id=c.target_id
       WHERE d.language_id=? ORDER BY d.rowid""",[*params,lid])


def matches(rows,opt,regex,wanted=None):
    changes=[]
    for row in long_tasks.steps(rows):
        for path,value,label in long_tasks.steps(cells(row,opt['field'],opt['kind'],opt.get('writing_type',''))):
            for m in long_tasks.steps(regex.finditer(value)):
                if not opt['find_only'] and m.group()==opt['replacement']:continue
                key=json.dumps([row['id'],path,m.start(),m.end()],ensure_ascii=False,separators=(',',':'))
                if wanted is not None and key not in wanted:continue
                changes.append(dict(key=key,id=row['id'],path=path,start=m.start(),end=m.end(),before=value,
                    after=value if opt['find_only'] else value[:m.start()]+opt['replacement']+value[m.end():],
                    title=row['form' if opt['kind']=='morpheme' else 'headword'],label=label))
                if len(changes)>10000:raise ValueError('超过 10000 处匹配，请缩小范围')
    return changes


def plan(db,b,lid):
    if not db.in_transaction:db.execute('BEGIN')
    if lid=='all':raise ValueError('请先选择一个语言工作区')
    opt=settings(b)
    if opt.get('writing_type') and not db.execute('SELECT 1 FROM writing_types WHERE id=? AND language_id=?',(opt['writing_type'],lid)).fetchone():raise ValueError('请选择当前语言的书写类型')
    regex=text_replace.pattern(opt)
    rows,count=scope_rows(db,opt,lid,regex)
    if opt['scope']=='search' and count==len(rows) and count<=10000:
        opt['scope_ids']=sorted(row['id'] for row in rows)
    changes=matches(rows,opt,regex)
    token=hashlib.sha256(json.dumps([lid,opt,rows,analysis_workspace.version(db)],ensure_ascii=False,sort_keys=True).encode()).hexdigest()
    return dict(token=token,changes=changes,records=count,scope_ids=opt['scope_ids']),rows,opt

def plain_notes(db,opt,changes):
    import save_validation
    return (opt['kind']=='lexeme' and bool(changes) and all(c['path']==['body','notes'] for c in changes)
            and record_sources.native(db) and save_validation.snapshot(db) is not None)


def transform(rows,changes,opt,*,notes=False):
    grouped=defaultdict(list)
    for c in changes:grouped[c['id']].append(c)
    result=[];blocked=[]
    for row in rows:
        if row['id'] not in grouped:continue
        new=copy.deepcopy(row)
        for c in sorted(grouped[row['id']],key=lambda c:c['start'],reverse=True):
            owner=new
            for part in c['path'][:-1]:owner=owner[part]
            k=c['path'][-1]
            if k=='short_gloss' and 'paradigms' in c['path'] and owner.get('gloss_mode')=='inherit':
                # Replacing a displayed composed gloss is an explicit per-form override.
                owner['short_gloss']=c['before'];owner.pop('gloss_mode',None);owner.pop('gloss_addition',None)
            owner[k]=owner[k][:c['start']]+opt['replacement']+owner[k][c['end']:]
        if notes:
            result.append(new)
            continue
        try:
            form='form' if opt['kind']=='morpheme' else 'headword'
            if new[form]!=new[form].strip() or any(v['form']!=v['form'].strip() for v in new['body'].get('variants',[])):raise ValueError('替换后词形或变体出现首尾空白，请调整替换内容')
            if not new[form]:raise ValueError('词形不能为空')
            import multipart_forms
            new['body']=multipart_forms.align_spellings(new['body'],new[form],row,form)
            if opt['kind']=='lexeme':
                new['body']=lexicon.normalize(new['body'])
                import chinese_mode
                generated=chinese_mode.realization(new['body'])
                if generated is not None:
                    if any(c['path']==['headword'] for c in grouped[row['id']]) and new['headword']!=generated:
                        raise ValueError('词形由语素生成，请编辑来源组分或替换关联语素的形式，也可先切换为独立词形。')
                    new['headword']=generated
            forms=[v['form'] for v in new['body'].get('variants',[])]
            old_forms=[v['form'] for v in row['body'].get('variants',[])]
            if len(set(forms))<len(forms) and len(set(forms))<len(set(old_forms)):raise ValueError('替换使不同变体具有相同形式，请先手动整理变体及关联')
            result.append(new)
        except ValueError as e:blocked.append(dict(id=row['id'],title=row.get('headword',row.get('form','')),reason=str(e)))
    return result,blocked

def collisions(db,pending,original,lid,table,field):
    edits=[row for row in pending if row[field]!=original[row['id']][field]]
    forms={row[field] for row in edits};counts=Counter(row[field] for row in edits)
    for row in edits:
        old=original[row['id']][field]
        if old in forms:counts[old]-=1
    for form in forms:
        counts[form]+=db.execute(f'SELECT COUNT(*) FROM {table} WHERE language_id=? AND {field}=?',(lid,form)).fetchone()[0]
    return counts

def conflicts(db,pending,opt,lid):
    if not pending:return []
    if opt['kind']=='morpheme':
        issues=[];original={r['id']:morpheme_registry.get(db,r['id'],lid) for r in pending}
        groups=collisions(db,pending,original,lid,'morphemes','form')
        for r in pending:
            reasons=[];old=original[r['id']]
            if r['form']!=old['form'] and groups[r['form']]>1:reasons.append('替换后出现同形语素；保留独立记录并分配下标，不合并')
            if opt['field'] in ('all','form','variant','short_gloss'):
                count=db.execute('SELECT count(*) FROM morpheme_components WHERE morpheme_id=?',(r['id'],)).fetchone()[0]
                if count:reasons.append(f'{count} 个关联组分保留现有身份并同步适用的形式及标注')
            if reasons:issues.append(dict(id=r['id'],title=old['form'],reason='；'.join(reasons)))
        return issues
    original={r['id']:lexicon.get_lexeme(db,r['id']) for r in pending}
    groups=collisions(db,pending,original,lid,'lexemes','headword');issues=[]
    inbound=component_references(db,original,lid) if opt['field'] in SENSITIVE else Counter()
    for r in pending:
        old=original[r['id']]
        reasons=[]
        if r['headword']!=old['headword'] and groups[r['headword']]>1:reasons.append('替换后出现同形词；确认后保留独立词条并分配下标，不合并')
        if opt['field'] in SENSITIVE:
            links=db.execute('SELECT COUNT(*) FROM lexical_links WHERE lexeme_id=?',(r['id'],)).fetchone()[0]
            if links:reasons.append(f'{links} 条语料关联保留；按实际关联形式及义项同步可可靠对应的语素行和标注')
            if old['body'].get('word_structure',{}).get('analyses'):reasons.append('已有语素分析保留')
            # Independent examples and inbound component references have no shared link-status flag.
            independent=db.execute("""SELECT COUNT(DISTINCT l.example_id) FROM independent_links l
                JOIN dictionary_examples e ON e.id=l.example_id WHERE l.lexeme_id=? AND e.language_id=?""",(r['id'],lid)).fetchone()[0]
            if independent:reasons.append(f"{independent} 条独立例句引用保留；明确定位的形式及义项同步，句级引用不猜测位置")
            if inbound[r['id']]:reasons.append(f"{inbound[r['id']]} 个词条的组分引用需要手动核对；组分内容不自动改写")
        if reasons:issues.append(dict(id=r['id'],title=old['headword'],reason='；'.join(reasons)))
    return issues

def component_references(db,targets,lid):
    from word_structure import references
    if record_sources.native(db):
        from dictionary_relations import component_edges
        import save_validation
        scope='EXISTS (SELECT 1 FROM lexemes x WHERE x.id=link.target_id AND x.language_id=?)'
        if 0<len(targets)<=400:
            marks=','.join('?' for _ in targets)
            return Counter(target for _,target in component_edges(
                db,'lexeme',scope+' AND link.value IN ('+marks+')',[lid,*targets],by_target=True))
        has_index=db.execute("SELECT 1 FROM sqlite_master WHERE name='dictionary_relation_dirty'").fetchone()
        if has_index and save_validation.snapshot(db) and not db.execute('SELECT 1 FROM dictionary_relation_dirty LIMIT 1').fetchone():
            counts=Counter();ids=list(targets)
            for start in range(0,len(ids),400):
                batch=ids[start:start+400];marks=','.join('?' for _ in batch)
                edges=f'link.target_id IN (SELECT owner FROM dictionary_relation_edges WHERE target IN ({marks}))'
                rows=component_edges(db,'lexeme',scope+' AND '+edges+' AND link.value IN ('+marks+')',
                                     [lid,*batch,*batch])
                counts.update(target for _,target in long_tasks.steps(rows))
            return counts
        # Scan typed keys once even when checking thousands of target IDs.
        rows=component_edges(db,'lexeme',scope,(lid,),by_target=True)
        return Counter(target for _,target in long_tasks.steps(rows) if target in targets)
    return Counter(target for row in long_tasks.steps(db.execute('SELECT body FROM lexemes_documents WHERE language_id=?',(lid,)))
                   for target in references(json.loads(row['body'])) if target in targets)

def write(db,pending,opt,lid,*,notes=False):
    for row in long_tasks.steps(pending):
        if notes:
            # Preserve the raw peer numbers. A note has no effect on homonym identity.
            record_sources.write(db,'lexemes',row['id'],row['body'])
            continue
        if opt['kind']=='morpheme':
            old=morpheme_registry.get(db,row['id'],lid)
            morpheme_registry.mutate(db,'morpheme-save',dict(id=row['id'],revision=old['revision'],form=row['form'],body=row['body']),lid)
            continue
        old=lexicon.get_lexeme(db,row['id']);body=copy.deepcopy(row['body'])
        # Earlier writes may have renumbered a peer in the same homonym group.
        body['homonym_number']=old['body'].get('homonym_number')
        lexicon.mutate(db,'lexeme-save',dict(id=row['id'],revision=old['revision'],headword=row['headword'],body=body,homonym_confirmation=homonyms.plan(db,lid,row['headword'],row['id'])['token']),lid)

def check(db,pending,opt,lid,*,notes=False):
    import save_validation
    scoped=bool(save_validation.snapshot(db) and not db.execute(
        "SELECT 1 FROM sqlite_temp_master WHERE name='audit_lexemes_UPDATE'").fetchone())
    db.execute('SAVEPOINT dictionary_replace_check')
    token=journal.previewing.set(not scoped)
    validation=None
    try:
        if scoped:validation=save_validation.begin(db)
        changes=journal.watch(db) if scoped else None
        write(db,pending,opt,lid,notes=notes)
        if scoped:lexicon.validate_changes(db,changes)
        else:lexicon.validate_links(db)
    finally:
        try:
            db.execute('ROLLBACK TO dictionary_replace_check');db.execute('RELEASE dictionary_replace_check')
        finally:
            if validation is not None:save_validation.CURRENT.reset(validation)
            journal.previewing.reset(token)

def preview(db,b,lid):
    p,rows,opt=plan(db,b,lid)
    if opt['find_only']:
        # Search can also hit class names, evidence or other text that cannot be
        # replaced here. Keep those hits visible without offering a write path.
        if opt['field']=='all':
            from dictionary_search import SearchIndex
            index=(MorphemeIndex if opt['kind']=='morpheme' else SearchIndex)(db,lid,rows)
            regex=text_replace.pattern(opt)
            seen={(c['id'],c['before'],c['start'],c['end']) for c in p['changes']}
            for row in long_tasks.steps(rows):
                doc=index.documents[row['id']]
                for field in sorted(doc,key=lambda f:-f.count('.')):
                    if field=='all' or field.startswith('_'):continue
                    for value in doc[field]:
                        for m in regex.finditer(value):
                            key=(row['id'],value,m.start(),m.end())
                            if key in seen:continue
                            seen.add(key)
                            p['changes'].append(dict(key=json.dumps(['readonly',*key],ensure_ascii=False),id=row['id'],path=[],start=m.start(),end=m.end(),before=value,after=value,title=row.get('headword',row.get('form','')),label=index.fields.get(field,field),read_only=True))
                            if len(p['changes'])>10000:raise ValueError('超过 10000 处匹配，请缩小范围')
        return dict(p,conflicts=[],blocked=[],find_only=True)
    p=validate_preview(db,p,rows,opt,lid)
    if b.get('reuse_preview') is True:
        replacement_preview.remember(db,__name__,lid,p,rows,opt)
    return p


def validate_preview(db,p,rows,opt,lid):
    notes=plain_notes(db,opt,p['changes'])
    if notes:
        # Only an existing string value changes in a checked native project.
        # The commit still runs the ordinary transactional validation.
        return dict(p,conflicts=[],blocked=[])
    pending,blocked=transform(rows,p['changes'],opt,notes=notes)
    if pending and not blocked:
        try:check(db,pending,opt,lid,notes=notes)
        except ValueError as e:blocked.append(dict(id='',title='本次替换',reason=str(e)))
    return dict(p,conflicts=[] if notes else conflicts(db,pending,opt,lid),blocked=blocked)


def remaining_preview(db,lid,previous,rows,opt,wanted):
    regex=text_replace.pattern(opt)
    count=previous['records']
    if opt['scope_ids'] is not None or (
            not opt['query'].strip() and dictionary_read.predicate(db,lid,opt['search'],
                field='form' if opt['kind']=='morpheme' else 'headword')==('', [])):
        # The original identities are sufficient for a fixed scope. Their
        # revisions and editable values are still read from the new snapshot.
        narrowed={**opt,'scope':'search','scope_ids':[row['id'] for row in rows]}
        current,_=scope_rows(db,narrowed,lid,regex)
    else:
        current,count=scope_rows(db,opt,lid,regex)
        owners={row['id'] for row in rows}
        current=[row for row in current if row['id'] in owners]
    changes=matches(current,opt,regex,wanted)
    p=dict(changes=changes,records=count,scope_ids=opt['scope_ids'])
    return validate_preview(db,p,current,opt,lid),current,opt


def apply(db,b,lid):
    if not db.in_transaction:db.execute('BEGIN IMMEDIATE')
    cached=replacement_preview.reuse(db,__name__,lid,b,settings(b))
    p,rows,opt=cached if cached is not None else plan(db,b,lid)
    if opt['find_only']:raise ValueError('当前为查找结果，请先预览替换')
    if p['token']!=b.get('token'):raise ValueError('词典、关联或材料已变化，请重新预览')
    keys=b.get('keys');known={c['key'] for c in p['changes']}
    if not isinstance(keys,list) or not keys or any(not isinstance(k,str) for k in keys) or len(keys)!=len(set(keys)) or not set(keys)<=known:raise ValueError('请选择当前预览中的替换项')
    keyset=set(keys);selected=[c for c in p['changes'] if c['key'] in keyset]
    notes=plain_notes(db,opt,selected)
    pending,blocked=transform(rows,selected,opt,notes=notes)
    if blocked:raise ValueError('；'.join(r['title']+'：'+r['reason'] for r in blocked))
    issues=[] if notes else conflicts(db,pending,opt,lid)
    if replacement_preview.needs_confirmation(b,cached,p,issues):return dict(needs_confirmation=True,conflicts=issues)
    pending_keys=b.get('pending_keys',list(known))
    if not isinstance(pending_keys,list) or any(not isinstance(k,str) for k in pending_keys) or not set(keys)<=set(pending_keys)<=known:raise ValueError('待替换列表已变化，请重新预览')
    remaining=[];pending_set=set(pending_keys);by_cell=defaultdict(list)
    for c in long_tasks.steps(selected):by_cell[(c['id'],tuple(c['path']))].append(c)
    for c in long_tasks.steps(p['changes']):
        if c['key'] not in pending_set or c['key'] in keyset:continue
        shift=sum(len(opt['replacement'])-(v['end']-v['start']) for v in by_cell[(c['id'],tuple(c['path']))] if v['end']<=c['start'])
        remaining.append(json.dumps([c['id'],c['path'],c['start']+shift,c['end']+shift],ensure_ascii=False,separators=(',',':')))
    # The normal API transaction validates the actual changes before committing.
    # Keep the same atomic validation when this function is called directly.
    replacement_preview.track_owner(db,b,opt['kind'],{row['id'] for row in pending})
    import gloss_inheritance
    if gloss_inheritance.CHANGES.get() is not None:
        write(db,pending,opt,lid,notes=notes)
    else:
        db.execute('SAVEPOINT dictionary_replace_write')
        try:
            write(db,pending,opt,lid,notes=notes)
            lexicon.validate_links(db)
        except BaseException:
            db.execute('ROLLBACK TO dictionary_replace_write')
            raise
        finally:db.execute('RELEASE dictionary_replace_write')
    result=dict(ok=True,replacements=len(selected),lexemes=len(pending),records=len(pending),kind=opt['kind'],conflicts=len(issues),remaining_keys=remaining)
    replacement_preview.schedule(db,b,p,rows,opt,pending_set-keyset)
    return result
