"""Previewed literal replacement with explicit slot correspondence and one undo step."""
import long_tasks
import copy
import hashlib
import json
import re
from collections import defaultdict
import corpus
import lexicon
import segmentation
import gloss_inheritance

FIELDS=('ipa','form','gloss','translation')

def settings(b):
    field=b.get('field');find=b.get('find');replacement=b.get('replacement','');mode=b.get('mode','contains')
    if field not in FIELDS or not isinstance(find,str) or not find or not isinstance(replacement,str):raise ValueError('请选择替换行并填写非空查找内容')
    if mode not in ('contains','exact','prefix','suffix') or type(b.get('case',True)) is not bool:raise ValueError('匹配选项无效')
    if len(find)>10000 or len(replacement)>10000:raise ValueError('查找或替换内容过长')
    owner=b.get('owner_kind','corpus')
    if owner not in ('corpus','independent'):raise ValueError('请选择文本语料或独立例句库')
    if owner=='independent' and b.get('text_id'):raise ValueError('独立例句替换不能限定文本')
    return dict(field=field,find=find,replacement=replacement,mode=mode,case=b.get('case',True),text_id=b.get('text_id',''),owner_kind=owner)

def pattern(opt):
    value=re.escape(opt['find'])
    if opt['mode'] in ('exact','prefix'):value=r'\A'+value
    if opt['mode'] in ('exact','suffix'):value+=r'\Z'
    return re.compile(value,0 if opt['case'] else re.IGNORECASE)

def records(db,opt,lid):
    if opt['owner_kind']=='independent':
        rows=[dict(r,title='独立例句库',position=i) for i,r in enumerate(db.execute('SELECT * FROM dictionary_examples WHERE language_id=? ORDER BY rowid',(lid,)),1)]
        for r in gloss_inheritance.iter_rows(db,rows,'independent'):r['body']=json.dumps(gloss_inheritance.load(db,'independent',r['id'],r['body']),ensure_ascii=False)
        return rows
    if opt['text_id']:
        t=db.execute('SELECT language_id FROM texts WHERE id=?',(opt['text_id'],)).fetchone()
        if not t or t[0]!=lid:raise ValueError('文本不存在或不属于当前语言工作区')
    rows=[dict(r) for r in db.execute("SELECT e.*,t.title FROM entries e JOIN texts t ON t.id=e.text_id WHERE t.language_id=? AND (?='' OR e.text_id=?) ORDER BY t.rowid,e.position",(lid,opt['text_id'],opt['text_id']))]
    for r in gloss_inheritance.iter_rows(db,rows,'corpus'):r['body']=json.dumps(gloss_inheritance.load(db,'corpus',r['id'],r['body']),ensure_ascii=False)
    return rows

def transform_word(old,new):
    """Retain confirmed groups only when their structural correspondence is certain."""
    if (old['form'],old['gloss'])==(new['form'],new['gloss']):return ''
    reasons=[]
    old_snapshot={k:old[k] for k in ('form','gloss')};new_snapshot={k:new[k] for k in ('form','gloss')}
    try:
        a,uncertain_a=segmentation.parse_word(corpus.clean(old['form']),corpus.clean(old['gloss']),old.get('infix_confirmation')==old_snapshot)
        z,uncertain_z=segmentation.parse_word(corpus.clean(new['form']),corpus.clean(new['gloss']),old.get('infix_confirmation')==old_snapshot)
        structure=lambda units:[(u['key'],u['kind'],u.get('host'),u.get('boundary'),len(u['fragments']),bool(u['form'].strip())) for u in units]
        if structure(a)!=structure(z):reasons.append('语素切分或空成分发生变化')
        if uncertain_a or uncertain_z:reasons.append('中缀结构存在歧义')
    except ValueError:reasons.append('语素边界或中缀结构无法可靠对应')
    if corpus.boundary_count(old['form'])!=corpus.boundary_count(new['form']):reasons.append('音系边界改变')
    if old.get('punctuation') and old.get('punctuation_form')==old['form']:reasons.append('已确认的标点内容改变')
    for group in old.get('morph_groups',[]):
        if group.get('snapshot')!=old_snapshot:reasons.append('存在尚未核对的多部分语素组合')
        elif old['gloss']!=new['gloss']:reasons.append('组合成员的标注改变，请核对组合释义')
    if not reasons:
        for group in new.get('morph_groups',[]):group['snapshot']=new_snapshot.copy()
        if old.get('infix_confirmation')==old_snapshot:new['infix_confirmation']=new_snapshot.copy()
    return '；'.join(dict.fromkeys(reasons))

def preserve_independent_refs(old,body,indices,unsafe,*,analyzed=False):
    """Rebase only current references whose fixed-slot structure survived."""
    before=old if analyzed else corpus.analyze(copy.deepcopy(old))
    def unit(word,key):
        return dict(key='@word',form=word['form'],gloss=word['gloss'],fragments=[]) if key=='@word' else next((m for m in word.get('morphemes',[]) if m['key']==key),None)
    for target in body.get('targets',[]):
        ref=target.get('segmentation_ref')
        if not ref or ref.get('detached') or ref['word'] not in indices or ref['word'] in unsafe:continue
        index=ref['word'];a=before['words'][index];z=body['words'][index]
        previous=unit(a,ref['key']);current=unit(z,ref['key'])
        if previous and current and segmentation.reference(a,index,previous)==ref:
            target['segmentation_ref']=segmentation.reference(z,index,current)
            target.pop('segmentation_review',None)

def edits_for(row,opt,selected):
    old=json.loads(row['body']);body=copy.deepcopy(old);by_cell={}
    for c in selected:by_cell.setdefault(c['word'],[]).append(c)
    conflicts=[];changed_words=[]
    for index,changes in by_cell.items():
        target=body if index is None else body['words'][index]
        value=target[opt['field']]
        for c in sorted(changes,key=lambda c:c['start'],reverse=True):value=value[:c['start']]+opt['replacement']+value[c['end']:]
        target[opt['field']]=value
        if index is not None:
            reason=transform_word(old['words'][index],target)
            if reason:conflicts.append(dict(id=row['id'],word=index,title=row['title'],position=row['position'],reason=reason))
            changed_words.append(index)
    body['edited']=True
    if changed_words:corpus.analyze(body)
    if opt['owner_kind']=='independent' and changed_words:preserve_independent_refs(old,body,changed_words,{c['word'] for c in conflicts})
    checked,errors=corpus.parse(corpus.export_entry({**body,'function':body.get('function','pass')}),analyze_entries=False)
    if errors or len(checked)!=1 or any(checked[0][k]!=body[k] for k in ('ipa','translation')) or [(w['form'],w['gloss']) for w in checked[0]['words']]!=[(w['form'],w['gloss']) for w in body['words']]:raise ValueError('替换后存在未配对括号或无法安全导出的内容，请修改替换条件')
    return body,conflicts,changed_words

def plan(db,b,lid,check=True):
    opt=settings(b);data=records(db,opt,lid);regex=pattern(opt);changes=[]
    for row in long_tasks.steps(data):
        body=json.loads(row['body'])
        cells=[(None,body[opt['field']])] if opt['field'] in ('ipa','translation') else [(i,w[opt['field']]) for i,w in enumerate(body['words'])]
        for index,value in long_tasks.steps(cells):
            for m in long_tasks.steps(regex.finditer(value)):
                if m.group()==opt['replacement']:continue
                changes.append(dict(key=f"{row['id']}:{index}:{m.start()}:{m.end()}",id=row['id'],word=index,start=m.start(),end=m.end(),before=value,after=value[:m.start()]+opt['replacement']+value[m.end():],title=row['title'],position=row['position']))
                if len(changes)>10000:raise ValueError('超过 10000 处匹配，请缩小查找范围')
    # Include current associations and layer content, not only entry revisions.
    digest=hashlib.sha256(json.dumps([opt,data],ensure_ascii=False,sort_keys=True).encode())
    scope=" JOIN entries e ON e.id=u.entry_id JOIN texts t ON t.id=e.text_id WHERE t.language_id=? AND (?='' OR e.text_id=?)"
    queries=[
        'SELECT u.* FROM corpus_units u'+scope+' ORDER BY u.rowid',
        'SELECT l.*,x.revision,a.form_id,a.features FROM lexical_links l JOIN corpus_units u ON u.id=l.unit_id JOIN dictionary_targets x ON x.id=l.lexeme_id LEFT JOIN morphology_analyses a ON a.id=l.id'+scope+' ORDER BY l.rowid',
        "SELECT c.* FROM annotation_cells c JOIN entries e ON e.id=c.record_id JOIN texts t ON t.id=e.text_id WHERE c.owner_kind='corpus' AND t.language_id=? AND (?='' OR e.text_id=?) ORDER BY c.rowid"]
    if opt['owner_kind']=='independent':
        queries=["SELECT c.* FROM annotation_cells c JOIN dictionary_examples e ON e.id=c.record_id WHERE c.owner_kind='independent' AND e.language_id=? ORDER BY c.rowid",
            "SELECT x.id,x.revision,x.body FROM dictionary_targets x WHERE x.id IN (SELECT json_extract(t.value,'$.lexeme_id') FROM dictionary_examples e,json_each(e.body,'$.targets') t WHERE e.language_id=?) ORDER BY x.id"]
    for query in long_tasks.steps(queries):
        cursor=db.execute(query,(lid,) if opt['owner_kind']=='independent' else (lid,opt['text_id'],opt['text_id']))
        digest.update(b'\nTABLE\n')
        while rows:=cursor.fetchmany(1000):
            digest.update(json.dumps([tuple(r) for r in rows],ensure_ascii=False,separators=(',',':')).encode())
    by_entry=defaultdict(list)
    for c in long_tasks.steps(changes):by_entry[c['id']].append(c)
    conflicts=[];blocked=[]
    for row in long_tasks.steps(data if check else []):
        chosen=by_entry[row['id']]
        if not chosen:continue
        try:
            _,issues,_=edits_for(row,opt,chosen);conflicts.extend(issues)
        except ValueError as e:blocked.append(dict(id=row['id'],title=row['title'],position=row['position'],reason=str(e)))
    token=digest.hexdigest()
    return dict(token=token,changes=changes,conflicts=conflicts,blocked=blocked,records=len(data)),data,opt

def preview(db,b,lid):
    if not db.in_transaction:db.execute('BEGIN')
    return plan(db,b,lid)[0]

def apply(db,b,lid):
    p,data,opt=plan(db,b,lid,check=False)
    if p['token']!=b.get('token'):raise ValueError('文本、分析或词典关联已变化，请重新预览')
    keys=b.get('keys');known={c['key'] for c in p['changes']}
    if not isinstance(keys,list) or not keys or any(not isinstance(k,str) for k in keys) or len(set(keys))!=len(keys) or not set(keys)<=known:raise ValueError('请选择当前预览中的替换项')
    pending_keys=b.get('pending_keys',list(known))
    if not isinstance(pending_keys,list) or any(not isinstance(k,str) for k in pending_keys) or not set(pending_keys)<=known or not set(keys)<=set(pending_keys):raise ValueError('待替换列表已变化，请重新预览')
    keyset=set(keys);pending_keyset=set(pending_keys)
    chosen=[c for c in p['changes'] if c['key'] in keyset];pending=[];conflicts=[]
    by_entry=defaultdict(list);by_cell=defaultdict(list)
    for c in long_tasks.steps(chosen):
        by_entry[c['id']].append(c);by_cell[(c['id'],c['word'])].append(c)
    for row in long_tasks.steps(data):
        selected=by_entry[row['id']]
        if not selected:continue
        body,issues,indices=edits_for(row,opt,selected);conflicts.extend(issues);pending.append((row,body,issues,indices))
    if conflicts and b.get('confirm_conflicts') is not True:return dict(needs_confirmation=True,conflicts=conflicts)
    for row,body,issues,indices in long_tasks.steps(pending):
        if opt['owner_kind']=='independent':
            # Literal replacement supplies a fixed-slot correspondence. Preserve
            # annotation IDs, language spans, media and dictionary targets. Old
            # segmentation snapshots continue to expose a real structural change.
            db.execute('UPDATE dictionary_examples SET body=?,revision=revision+1 WHERE id=?',(json.dumps(body,ensure_ascii=False),row['id']))
            continue
        if not indices:
            db.execute('UPDATE entries SET body=?,revision=revision+1 WHERE id=?',(json.dumps(body,ensure_ascii=False),row['id']))
            continue
        words=[dict(r) for r in db.execute("SELECT * FROM corpus_units WHERE entry_id=? AND kind='word' AND active=1 ORDER BY position",(row['id'],))]
        unsafe={c['word'] for c in issues};morph_ids={}
        for i in long_tasks.steps(indices):
            uid=words[i]['id']
            old_morphs=[dict(r) for r in db.execute("SELECT * FROM corpus_units WHERE parent_id=? AND active=1 ORDER BY position",(uid,))]
            if i not in unsafe and len(old_morphs)==len(body['words'][i]['morphemes']):morph_ids[uid]=[m['id'] for m in old_morphs]
            if i in unsafe:
                import link_review
                link_review.mark(db,'unit_id IN (SELECT id FROM corpus_units WHERE id=? OR parent_id=?)',(uid,uid),'批量替换改变了语素切分，请核对关联')
        db.execute('UPDATE entries SET body=?,revision=revision+1 WHERE id=?',(json.dumps(body,ensure_ascii=False),row['id']))
        lexicon.sync_entry(db,row['id'],[w['id'] for w in words],morph_ids,preserve_complex=True)
    remaining=[]
    for c in long_tasks.steps(p['changes']):
        if c['key'] not in pending_keyset or c['key'] in keyset:continue
        shift=sum(len(opt['replacement'])-(v['end']-v['start']) for v in by_cell[(c['id'],c['word'])] if v['end']<=c['start'])
        remaining.append(f"{c['id']}:{c['word']}:{c['start']+shift}:{c['end']+shift}")
    return dict(ok=True,sentences=len(pending),replacements=len(chosen),conflicts=len(conflicts),remaining_keys=remaining)
