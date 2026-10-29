"""Literal dictionary replacement: preview, revalidate, one transactional undo step."""
import long_tasks
import copy
import hashlib
import json
from collections import defaultdict
import lexicon
import homonyms
import text_replace
import analysis_workspace
import journal
import morpheme_registry
import paradigms
from morpheme_search import MorphemeIndex

FIELDS={'all':'全部可替换文字','headword':'词形','variant':'变体形式','writing':'词条书写形式','short_gloss':'简短释义','definition':'详细释义','notes':'备注','tag_value':'使用标签值'}
SENSITIVE={'all','headword','variant','short_gloss'}
MORPHEME_FIELDS={'all':'全部可替换文字','form':'语素形式','variant':'变体形式','writing':'书写形式','short_gloss':'简短释义','definition':'详细释义','readings':'读音','conditions':'变体出现条件','notes':'备注','tag_value':'使用标签值'}

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

def plan(db,b,lid):
    if lid=='all':raise ValueError('请先选择一个语言工作区')
    opt=settings(b)
    if opt.get('writing_type') and not db.execute('SELECT 1 FROM writing_types WHERE id=? AND language_id=?',(opt['writing_type'],lid)).fetchone():raise ValueError('请选择当前语言的书写类型')
    morph=opt['kind']=='morpheme';table='morphemes' if morph else 'lexemes'
    rows=[{**dict(r),'body':json.loads(r['body'])} for r in db.execute('SELECT * FROM '+table+' WHERE language_id=? ORDER BY rowid',(lid,))]
    if opt['scope']=='current':
        rows=[r for r in rows if r['id']==opt['lexeme_id']]
        if not rows:raise ValueError('词条已不存在或不属于当前语言')
    if opt['scope']=='search' and opt['scope_ids'] is not None:
        ids=set(opt['scope_ids'])
        if not ids<={r['id'] for r in rows}:raise ValueError('原搜索范围中的词条已删除或移动，请重新打开替换')
        rows=[r for r in rows if r['id'] in ids]
    else:
        if morph:
            index=MorphemeIndex(db,lid,rows).prepare(opt['search'])
            rows=[r for r in rows if index.matches(r,opt['query'])]
        else:
            ids=set(lexicon.list_lexemes(db,lid,opt['query'],ids_only=True,search=opt['search']))
            rows=[r for r in rows if r['id'] in ids]
    if opt['scope']=='search':
        ids={r['id'] for r in rows}
        opt['scope_ids']=sorted(ids)
    regex=text_replace.pattern(opt);changes=[]
    for row in long_tasks.steps(rows):
        for path,value,label in long_tasks.steps(cells(row,opt['field'],opt['kind'],opt.get('writing_type',''))):
            for m in long_tasks.steps(regex.finditer(value)):
                if not opt['find_only'] and m.group()==opt['replacement']:continue
                key=json.dumps([row['id'],path,m.start(),m.end()],ensure_ascii=False,separators=(',',':'))
                changes.append(dict(key=key,id=row['id'],path=path,start=m.start(),end=m.end(),before=value,after=value if opt['find_only'] else value[:m.start()]+opt['replacement']+value[m.end():],title=row['form' if morph else 'headword'],label=label))
                if len(changes)>10000:raise ValueError('超过 10000 处匹配，请缩小范围')
    token=hashlib.sha256(json.dumps([lid,opt,rows,analysis_workspace.version(db)],ensure_ascii=False,sort_keys=True).encode()).hexdigest()
    return dict(token=token,changes=changes,records=len(rows),scope_ids=opt['scope_ids']),rows,opt

def transform(rows,changes,opt):
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
        try:
            form='form' if opt['kind']=='morpheme' else 'headword'
            if new[form]!=new[form].strip() or any(v['form']!=v['form'].strip() for v in new['body'].get('variants',[])):raise ValueError('替换后词形或变体出现首尾空白，请调整替换内容')
            if not new[form]:raise ValueError('词形不能为空')
            import multipart_forms
            new['body']=multipart_forms.align_spellings(new['body'],new[form],row,form)
            if opt['kind']=='lexeme':new['body']=lexicon.normalize(new['body'])
            forms=[v['form'] for v in new['body'].get('variants',[])]
            old_forms=[v['form'] for v in row['body'].get('variants',[])]
            if len(set(forms))<len(forms) and len(set(forms))<len(set(old_forms)):raise ValueError('替换使不同变体具有相同形式，请先手动整理变体及关联')
            result.append(new)
        except ValueError as e:blocked.append(dict(id=row['id'],title=row.get('headword',row.get('form','')),reason=str(e)))
    return result,blocked

def conflicts(db,pending,opt,lid):
    if opt['kind']=='morpheme':
        issues=[];changed={r['id']:r for r in pending};groups=defaultdict(list)
        for r in db.execute('SELECT id,form FROM morphemes WHERE language_id=?',(lid,)):groups[changed.get(r['id'],r)['form']].append(r['id'])
        for r in pending:
            reasons=[];old=morpheme_registry.get(db,r['id'],lid)
            if r['form']!=old['form'] and len(groups[r['form']])>1:reasons.append('替换后出现同形语素；保留独立记录并分配下标，不合并')
            count=db.execute('SELECT count(*) FROM morpheme_components WHERE morpheme_id=?',(r['id'],)).fetchone()[0]
            if count and opt['field'] in ('all','form','variant','short_gloss'):reasons.append(f'{count} 个关联组分保留现有身份并同步适用的形式及标注')
            if reasons:issues.append(dict(id=r['id'],title=old['form'],reason='；'.join(reasons)))
        return issues
    changed={r['id']:r for r in pending};groups=defaultdict(list);issues=[];inbound=defaultdict(set);independent=defaultdict(set)
    for e in db.execute('SELECT id,body FROM dictionary_examples WHERE language_id=?',(lid,)):
        for t in json.loads(e['body']).get('targets',[]):independent[t['lexeme_id']].add(e['id'])
    for r in db.execute('SELECT id,headword,body FROM lexemes WHERE language_id=?',(lid,)):
        groups[changed.get(r['id'],r)['headword']].append(r['id'])
        for a in json.loads(r['body']).get('word_structure',{}).get('analyses',[]):
            for c in a.get('components',[]):
                if c.get('lexeme_id'):inbound[c['lexeme_id']].add(r['id'])
    for r in pending:
        old=lexicon.get_lexeme(db,r['id'])
        reasons=[]
        if r['headword']!=old['headword'] and len(groups[r['headword']])>1:reasons.append('替换后出现同形词；确认后保留独立词条并分配下标，不合并')
        if opt['field'] in SENSITIVE:
            links=db.execute('SELECT COUNT(*) FROM lexical_links WHERE lexeme_id=?',(r['id'],)).fetchone()[0]
            if links:reasons.append(f'{links} 条语料关联保留；按实际关联形式及义项同步可可靠对应的语素行和标注')
            if old['body'].get('word_structure',{}).get('analyses'):reasons.append('已有语素分析保留')
            # Independent examples and inbound component references have no shared link-status flag.
            if independent[r['id']]:reasons.append(f"{len(independent[r['id']])} 条独立例句引用保留；明确定位的形式及义项同步，句级引用不猜测位置")
            if inbound[r['id']]:reasons.append(f"{len(inbound[r['id']])} 个词条的组分引用需要手动核对；组分内容不自动改写")
        if reasons:issues.append(dict(id=r['id'],title=old['headword'],reason='；'.join(reasons)))
    return issues

def write(db,pending,opt,lid):
    for row in long_tasks.steps(pending):
        if opt['kind']=='morpheme':
            old=morpheme_registry.get(db,row['id'],lid)
            morpheme_registry.mutate(db,'morpheme-save',dict(id=row['id'],revision=old['revision'],form=row['form'],body=row['body']),lid)
            continue
        old=lexicon.get_lexeme(db,row['id']);body=copy.deepcopy(row['body'])
        # Earlier writes may have renumbered a peer in the same homonym group.
        body['homonym_number']=old['body'].get('homonym_number')
        lexicon.mutate(db,'lexeme-save',dict(id=row['id'],revision=old['revision'],headword=row['headword'],body=body,homonym_confirmation=homonyms.plan(db,lid,row['headword'],row['id'])['token']),lid)
    lexicon.validate_links(db)
    if opt['kind']=='morpheme':morpheme_registry.validate(db)

def check(db,pending,opt,lid):
    db.execute('SAVEPOINT dictionary_replace_check')
    token=journal.previewing.set(True)
    try:write(db,pending,opt,lid)
    finally:
        try:
            db.execute('ROLLBACK TO dictionary_replace_check');db.execute('RELEASE dictionary_replace_check')
        finally:journal.previewing.reset(token)

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
    pending,blocked=transform(rows,p['changes'],opt)
    if pending and not blocked:
        try:check(db,pending,opt,lid)
        except ValueError as e:blocked.append(dict(id='',title='本次替换',reason=str(e)))
    return dict(p,conflicts=conflicts(db,pending,opt,lid),blocked=blocked)

def apply(db,b,lid):
    p,rows,opt=plan(db,b,lid)
    if opt['find_only']:raise ValueError('当前为查找结果，请先预览替换')
    if p['token']!=b.get('token'):raise ValueError('词典、关联或材料已变化，请重新预览')
    keys=b.get('keys');known={c['key'] for c in p['changes']}
    if not isinstance(keys,list) or not keys or any(not isinstance(k,str) for k in keys) or len(keys)!=len(set(keys)) or not set(keys)<=known:raise ValueError('请选择当前预览中的替换项')
    keyset=set(keys);selected=[c for c in p['changes'] if c['key'] in keyset];pending,blocked=transform(rows,selected,opt)
    if blocked:raise ValueError('；'.join(r['title']+'：'+r['reason'] for r in blocked))
    check(db,pending,opt,lid);issues=conflicts(db,pending,opt,lid)
    if issues and b.get('confirm_conflicts') is not True:return dict(needs_confirmation=True,conflicts=issues)
    pending_keys=b.get('pending_keys',list(known))
    if not isinstance(pending_keys,list) or any(not isinstance(k,str) for k in pending_keys) or not set(keys)<=set(pending_keys)<=known:raise ValueError('待替换列表已变化，请重新预览')
    remaining=[];pending_set=set(pending_keys);by_cell=defaultdict(list)
    for c in long_tasks.steps(selected):by_cell[(c['id'],tuple(c['path']))].append(c)
    for c in long_tasks.steps(p['changes']):
        if c['key'] not in pending_set or c['key'] in keyset:continue
        shift=sum(len(opt['replacement'])-(v['end']-v['start']) for v in by_cell[(c['id'],tuple(c['path']))] if v['end']<=c['start'])
        remaining.append(json.dumps([c['id'],c['path'],c['start']+shift,c['end']+shift],ensure_ascii=False,separators=(',',':')))
    write(db,pending,opt,lid)
    return dict(ok=True,replacements=len(selected),lexemes=len(pending),records=len(pending),kind=opt['kind'],conflicts=len(issues),remaining_keys=remaining)
