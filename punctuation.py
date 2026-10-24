"""Explicit, previewed punctuation splitting with stable lexical slots."""
import long_tasks
import copy
import hashlib
import json
import re
import uuid
import annotations
import lexicon
from corpus import analyze,parse,export_entry

DEFAULTS=['……','...','…','。','，','、','；','：','？','！','.',',',';',':','?','!','«','»','“','”','‘','’','"',"'",'（','）','(',')','【','】','[',']']

def settings(db,lid):
    row=db.execute('SELECT metadata FROM languages WHERE id=?',(lid,)).fetchone()
    if not row:raise ValueError('语言不存在')
    return json.loads(row[0]).get('punctuation_settings',{'symbols':DEFAULTS,'internal':False})

def options(b):
    symbols=b.get('symbols',DEFAULTS)
    if not isinstance(symbols,list) or len(symbols)>100 or any(not isinstance(s,str) or not s or len(s)>16 or any(c.isspace() or c.isalnum() for c in s) for s in symbols):raise ValueError('每行一个标点，不可含字母、数字或空白；最多 100 项，每项最多 16 个字符')
    if not isinstance(b.get('internal',False),bool):raise ValueError('内部标点选项无效')
    return {'symbols':list(dict.fromkeys(symbols)),'internal':b.get('internal',False)}

def split(value,opt):
    symbols=sorted(opt['symbols'],key=len,reverse=True)
    if not symbols:return [(value,False)]
    if opt['internal']:
        pattern='('+ '|'.join(re.escape(s) for s in symbols)+')'
        return [(p if p in symbols else p.strip(),p in symbols) for p in re.split(pattern,value) if p and (p in symbols or p.strip())]
    left=[];right=[];core=value
    while True:
        core=core.strip();p=next((s for s in symbols if core.startswith(s)),None)
        if not p:break
        left.append((p,True));core=core[len(p):]
    while True:
        core=core.strip();p=next((s for s in symbols if core.endswith(s)),None)
        if not p:break
        right.insert(0,(p,True));core=core[:-len(p)]
    if not left and not right:return [(value,False)]
    return left+([(core,False)] if core else [])+right

def records(db,b,lid):
    if b.get('text_id'):
        t=db.execute('SELECT * FROM texts WHERE id=?',(b['text_id'],)).fetchone()
        if not t or t['language_id']!=lid:raise ValueError('请选择当前语言的文本')
        refs=[{'kind':'corpus','id':r[0]} for r in db.execute('SELECT id FROM entries WHERE text_id=? ORDER BY position',(t['id'],))]
    else:
        refs=b.get('records',[])
        if not isinstance(refs,list) or not refs or len(refs)>20000:raise ValueError('请选择需要处理的例句')
    seen=set();result=[]
    for ref in long_tasks.steps(refs):
        if not isinstance(ref,dict) or ref.get('kind') not in ('corpus','independent') or not isinstance(ref.get('id'),str):raise ValueError('例句范围无效')
        key=(ref['kind'],ref['id'])
        if key in seen:continue
        seen.add(key);d=annotations.get(db,*key)
        if d['owner_language']!=lid:raise ValueError('一次只能处理同一语言工作区的例句')
        if d['language_id']!=lid:raise ValueError('范围内含其他语言的句子，请单独选择这些句子处理')
        if key[0]=='corpus':
            r=db.execute('SELECT t.title,e.position FROM entries e JOIN texts t ON t.id=e.text_id WHERE e.id=?',(key[1],)).fetchone();d['title']=f"{r['title']} · 第 {r['position']} 句"
            d['links']=[dict(r) for r in db.execute('SELECT l.* FROM lexical_links l JOIN corpus_units u ON u.id=l.unit_id WHERE u.entry_id=?',(key[1],))]
        else:d['title']=d['body'].get('source') or '独立例句'
        result.append(d)
    return result

def preview(db,b,lid):
    opt=options(b);data=records(db,b,lid)
    has_bang=any('!' in w['form'] for d in data for w in d['body']['words'])
    if has_bang and b.get('bang_confirmed') is not True:return {'needs_bang_confirmation':True,'message':'请确认当前文本的感叹号 ! 不是搭嘴音符号'}
    changes=[];blocked=[]
    for d in long_tasks.steps(data):
        for i,w in long_tasks.steps(enumerate(d['body']['words'])):
            if w.get('punctuation_form')==w['form'] and w.get('punctuation'):continue
            pieces=split(w['form'],opt)
            if not any(p for _,p in pieces):continue
            lexical=[s for s,p in pieces if not p]
            why=''
            if len(lexical)>1 or any(re.search(r'\s',s) for s in lexical):why='拆分后包含多个词，无法分配原标注'
            elif w.get('morph_groups') or w.get('infix_confirmation') or '<' in w['form'] or '>' in w['form'] or '#' in w['form'] or '\\' in w['form']:why='含形态分析或特殊记号，请人工核对'
            elif not lexical and (w.get('gloss') or any(c['unit_id']==d['words'][i]['id'] and c['value'] for c in d['cells']) or any(l['unit_id']==d['words'][i]['id'] or db.execute('SELECT 1 FROM corpus_units WHERE id=? AND parent_id=?',(l['unit_id'],d['words'][i]['id'])).fetchone() for l in d.get('links',[]))):why='纯标点格仍有标注或关联，请人工核对'
            item={'kind':d['kind'],'id':d['id'],'title':d['title'],'word':i,'before':w['form'],'gloss':w['gloss'],'pieces':[{'form':s,'punctuation':p} for s,p in pieces]}
            if not why and d['kind']=='corpus':
                trial={'function':'pass','ipa':'','translation':'','edited':True,'words':[dict(form=s,gloss='' if p else w['gloss'],form_kind=('string' if any(c in s for c in '[]') else 'content') if p else w.get('form_kind','content'),gloss_kind=w.get('gloss_kind','content')) for s,p in pieces]}
                checked,errors=parse(export_entry(trial))
                if errors or len(checked)!=1 or [(v['form'],v['gloss']) for v in checked[0]['words']]!=[(v['form'],v['gloss']) for v in trial['words']]:why='拆分后无法安全导出 Typst，请人工核对转义与括号'
            if why:blocked.append({**item,'reason':why})
            else:changes.append(item)
    payload={'changes':changes,'blocked':blocked,'settings':opt,'has_bang':has_bang,'record_count':len(data)}
    payload['token']=hashlib.sha256(json.dumps([payload,data],sort_keys=True,ensure_ascii=False).encode()).hexdigest()
    return payload

def apply(db,b,lid):
    plan=preview(db,b,lid)
    if plan.get('needs_bang_confirmation'):raise ValueError(plan['message'])
    if b.get('token')!=plan['token']:raise ValueError('语料或关联已变化，请重新预览')
    data=records(db,b,lid);changed=0
    for d in long_tasks.steps(data):
        edits={c['word']:c for c in plan['changes'] if c['id']==d['id'] and c['kind']==d['kind']}
        if not edits:continue
        body=copy.deepcopy(d['body']);new=[];ids=[];mapping={};morph_ids={}
        for i,w in long_tasks.steps(enumerate(body['words'])):
            old_id=d['words'][i]['id']
            if i not in edits:mapping[i]=len(new);new.append(w);ids.append(old_id);continue
            for p in long_tasks.steps(edits[i]['pieces']):
                if p['punctuation']:
                    nw={'form':p['form'],'gloss':'','form_kind':'string' if any(c in p['form'] for c in '[]') else 'content','gloss_kind':'content','punctuation':True,'punctuation_form':p['form']};uid=str(uuid.uuid4())
                else:
                    nw=copy.deepcopy(w);nw['form']=p['form'];nw.pop('punctuation',None);nw.pop('punctuation_form',None);uid=old_id;mapping[i]=len(new)
                    if d['kind']=='corpus':
                        old_m=[dict(r) for r in db.execute("SELECT * FROM corpus_units WHERE parent_id=? AND active=1 ORDER BY position",(old_id,))]
                        fresh=analyze({'ipa':'','translation':'','words':[copy.deepcopy(nw)]})['words'][0]['morphemes']
                        if len(old_m)==len(fresh) and all(a['gloss']==z['gloss'] for a,z in zip(old_m,fresh)):morph_ids[uid]=[m['id'] for m in old_m]
                if d['kind']=='independent':nw['annotation_id']=uid
                new.append(nw);ids.append(uid)
        body['words']=new;body['edited']=True
        # References to unchanged words move with their slots, not their old positions.
        for t in long_tasks.steps(body.get('targets',[])):
            ref=t.get('segmentation_ref')
            if ref and ref.get('word') in mapping:
                old_index=ref['word'];ref['word']=mapping[old_index]
                if old_index in edits:ref['form']=new[ref['word']]['form']
        analyze(body)
        table='entries' if d['kind']=='corpus' else 'dictionary_examples'
        db.execute('UPDATE '+table+' SET body=?,revision=revision+1 WHERE id=?',(json.dumps(body,ensure_ascii=False),d['id']))
        if d['kind']=='corpus':lexicon.sync_entry(db,d['id'],ids,morph_ids)
        changed+=1
    row=db.execute('SELECT metadata FROM languages WHERE id=?',(lid,)).fetchone();meta=json.loads(row[0])
    if meta.get('punctuation_settings')!=plan['settings']:
        meta['punctuation_settings']=plan['settings'];db.execute('UPDATE languages SET metadata=?,revision=revision+1 WHERE id=?',(json.dumps(meta,ensure_ascii=False),lid))
    return {'ok':True,'sentences':changed,'cells':len(plan['changes']),'skipped':len(plan['blocked'])}


def recognize_inline(body, data, slot_ids, cells):
    """Only unambiguous, unannotated standalone punctuation is automatic."""
    safe=set('。 ， 、 ； ： ？ ！ . , ; : ? … « » “ ” ‘ ’ （ ） ( ) 【 】 [ ]'.split())
    protected={w['id'] for w in data['words'] if w.get('protected')}
    for w,uid in zip(body['words'],slot_ids):
        form=w['form'].strip()
        if not form or w['gloss'].strip():continue
        if uid in protected or w.get('morph_groups') or w.get('infix_confirmation') or any(c['unit_id']==uid and c.get('value','').strip() for c in cells):continue
        if all(c in safe for c in form):
            w.update(punctuation=True,punctuation_form=w['form'])
            if any(c in form for c in '[]'):w['form_kind']='string'
