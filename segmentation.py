"""Surface fragments and explicitly grouped, possibly discontinuous morphemes."""
import copy
import re
import uuid

TYPES=('circumfix','root','stem','unspecified')


def split_parts(text,tilde=True):
    parts=[];start=0;square=angle=0
    for i,c in enumerate(text):
        if c=='[':square+=1
        elif c==']':square=max(0,square-1)
        elif not square:
            if c=='<':angle+=1
            elif c=='>':angle=max(0,angle-1)
            elif c in ('-=+~' if tilde else '-=+') and not angle:
                parts.append((text[start:i],start,text[i]));start=i+1
    parts.append((text[start:],start,''))
    return parts


def angles(text,gloss=False):
    """Pairs are lexical delimiters; a > inside a gloss can instead be a relation."""
    groups=[];cursor=0;ambiguous=False
    while True:
        start=text.find('<',cursor)
        if start<0:break
        next_start=text.find('<',start+1)
        limit=len(text) if next_start<0 else next_start
        ends=[i for i in range(start+1,limit) if text[i]=='>']
        if not ends:raise ValueError('中缀尖括号未闭合或发生嵌套')
        if not gloss and len(ends)!=1:raise ValueError('形式行中缀尖括号不成对')
        end=ends[-1] if gloss else ends[0]
        if len(ends)>1:ambiguous=True
        if end==start+1:raise ValueError('中缀及其中缀标注不能为空')
        groups.append((start,end+1,text[start+1:end]));cursor=end+1
    remaining=''.join(text[a:b] for a,b in gaps(len(text),groups))
    if not gloss and '>' in remaining:raise ValueError('形式行含未配对的中缀闭括号')
    return groups,ambiguous


def gaps(length,groups):
    start=0
    for a,b,_ in groups:
        if start<a:yield start,a
        start=b
    if start<length:yield start,length


def parse_word(form,gloss,confirmed=False,legacy_tilde=False):
    fs=split_parts(form,False) if legacy_tilde else split_parts(form)
    gs=split_parts(gloss,False) if legacy_tilde else split_parts(gloss)
    if len(fs)!=len(gs) or [p[2] for p in fs]!=[p[2] for p in gs]:
        raise ValueError('语素数量或边界不一致，保留整词配对')
    units=[];ambiguous=False
    prefix='r:' if any(p[2]=='~' for p in fs) else ''
    for i,((f,offset,_),(g,gloss_offset,_)) in enumerate(zip(fs,gs)):
        fg,_=angles(f);gg,uncertain=angles(g,True)
        if len(fg)!=len(gg):raise ValueError('形式与标注的中缀数量不一致，请核对尖括号')
        ambiguous|=uncertain
        fragments=[dict(start=offset+a,end=offset+b,text=f[a:b]) for a,b in gaps(len(f),fg)]
        host_gloss=''.join(g[a:b] for a,b in gaps(len(g),gg))
        if fg and (not fragments or not host_gloss.strip()):raise ValueError('中缀缺少宿主形式或宿主标注')
        # Empty initial corpus slots remain valid.
        gloss_fragments=[dict(start=gloss_offset+a,end=gloss_offset+b,text=g[a:b]) for a,b in gaps(len(g),gg)]
        units.append(dict(key=f'{prefix}{i}:host',kind='host' if fg else 'simple',form='…'.join(x['text'] for x in fragments),lookup_form=''.join(x['text'] for x in fragments),gloss=host_gloss,fragments=fragments,gloss_fragments=gloss_fragments,boundary=fs[i-1][2] if i else ''))
        for j,((a,b,value),(_,_,label)) in enumerate(zip(fg,gg)):
            ga,gb,_=gg[j]
            units.append(dict(key=f'{prefix}{i}:infix:{j}',kind='infix',form=value,gloss=label,host=f'{prefix}{i}:host',fragments=[dict(start=offset+a+1,end=offset+b-1,text=value)],gloss_fragments=[dict(start=gloss_offset+ga+1,end=gloss_offset+gb-1,text=label)],boundary=''))
    return units,ambiguous and not confirmed


def analyze_word(word,form,gloss):
    snapshot={k:word[k] for k in ('form','gloss')}
    units,ambiguous=parse_word(form,gloss,word.get('infix_confirmation')==snapshot,word.get('_legacy_tilde',False))
    if re.search(r'#(?:sub|sup|super)\[',word['gloss']):
        display,_=parse_word(form,re.sub(r'\\([\\"\[\]#~?])',r'\1',word['gloss']).strip(),True,word.get('_legacy_tilde',False))
        labels={u['key']:u['gloss'] for u in display}
        for u in units:u['display_gloss']=labels.get(u['key'],u['gloss'])
    word['analysis_form']=form;word['segments']=units;word['group_reviews']=[]
    word['infix_ambiguous']=ambiguous
    if ambiguous:
        word['morphemes']=[]
        return '中缀标注中有多个 >，请在形态分析中确认括号与关系符号'
    by_key={u['key']:u for u in units};used=set();groups=[]
    for group in word.get('morph_groups',[]):
        members=group.get('members',[])
        if group.get('snapshot')!=snapshot or any(k not in by_key or k in used for k in members):
            word['group_reviews'].append(group);continue
        used.update(members)
        fragments=sorted([f for k in members for f in by_key[k]['fragments']],key=lambda f:f['start'])
        gloss_fragments=sorted([f for k in members for f in by_key[k]['gloss_fragments']],key=lambda f:f['start'])
        groups.append(dict(key='group:'+group['id'],kind=group['type'],group_id=group['id'],form='…'.join(f['text'] for f in fragments),gloss=group['gloss'],fragments=fragments,gloss_fragments=gloss_fragments,members=members,notes=group.get('notes',''),boundary=''))
    word['morphemes']=sorted([u for u in units if u['key'] not in used]+groups,key=lambda u:u['fragments'][0]['start'] if u['fragments'] else -1)
    if word['group_reviews']:return '多部分语素的原文已变化，请在形态分析中核对旧组合'
    return None


def preserve(old,new):
    """Whole-editor saves must not erase analyses; unmatched analyses remain reviewable."""
    before=old.get('words',[]);after=new.get('words',[]);used=set()
    orphans=copy.deepcopy(old.get('orphaned_morphology',[]))
    for n,w in enumerate(after):
        matches=[i for i,v in enumerate(before) if i not in used and (v['form'],v['gloss'])==(w['form'],w['gloss'])]
        i=matches[0] if len(matches)==1 else n if len(before)==len(after) and n not in used else None
        if i is None:continue
        used.add(i)
        for key in ('morph_groups','infix_confirmation','punctuation','punctuation_form','gloss_frozen'):
            if key in before[i]:w[key]=copy.deepcopy(before[i][key])
    for i,w in enumerate(before):
        if i not in used and (w.get('morph_groups') or w.get('infix_confirmation')):
            orphans.append({k:copy.deepcopy(w[k]) for k in ('form','gloss','morph_groups','infix_confirmation') if k in w})
    if orphans:new['orphaned_morphology']=orphans
    import reduplication
    reduplication.preserve(old,new)


def get(db,kind,rid):
    import annotations
    from corpus import analyze
    result=annotations.get(db,kind,rid);analyze(result['body'])
    if kind=='corpus':
        import lexicon
        item={**result['body'],'id':rid};lexicon.enrich(db,[item]);result['body']=item
    else:annotations.enrich(db,result['body'],kind,rid)
    return result


def reference(word,index,unit):
    return dict(word=index,key=unit['key'],form=word['form'],gloss=word['gloss'],unit_form=unit['form'],unit_gloss=unit['gloss'],fragments=unit['fragments'])


def validate_ref(ref):
    if not isinstance(ref,dict) or not isinstance(ref.get('word'),int) or ref['word']<0 or any(not isinstance(ref.get(k),str) for k in ('key','form','gloss','unit_form','unit_gloss')) or not isinstance(ref.get('fragments'),list):raise ValueError('例句语素引用无效')


def decorate_refs(body):
    for target in body.get('targets',[]):
        ref=target.get('segmentation_ref')
        if not ref:continue
        target['segmentation_review']=True
        if ref.get('detached'):continue
        if 0<=ref['word']<len(body['words']):
            w=body['words'][ref['word']]
            unit=dict(key='@word',form=w['form'],gloss=w['gloss'],fragments=[]) if ref['key']=='@word' else next((m for m in w.get('morphemes',[]) if m['key']==ref['key']),None)
            target['segmentation_review']=not unit or reference(w,ref['word'],unit)!=ref


def link(db,b,lid):
    import json
    import lexicon
    import morphology
    d=get(db,b['kind'],b['id']);body=d['body']
    if b.get('revision')!=d['revision']:raise ValueError('例句已修改，请重新打开形态分析')
    if b['kind']=='independent' and b.get('remove_target') is not None:
        i=b['remove_target']
        if not isinstance(i,int) or not 0<=i<len(body['targets']) or not body['targets'][i].get('segmentation_ref'):raise ValueError('语素关联已变化')
        body['targets'].pop(i)
    else:
        i=b.get('word')
        if not isinstance(i,int) or not 0<=i<len(body['words']):raise ValueError('请选择当前词')
        w=body['words'][i];unit=next((m for m in w.get('morphemes',[]) if m['key']==b.get('key')),None)
        if b.get('key')=='@word':
            if w.get('unit_type') in ('phonological_boundary','punctuation'):raise ValueError('标点或音系边界不能关联词典')
            if b.get('component_selection'):raise ValueError('只有语素可以关联词条形态组分')
            unit=dict(key='@word',form=w['form'],gloss=w['gloss'],fragments=[],unit_id=w.get('unit_id'))
        if not unit:raise ValueError('语素已变化，请重新选择')
        x=lexicon.get_lexeme(db,b['lexeme_id'])
        if x['language_id']!=d['language_id'] or x['revision']!=b.get('lexeme_revision'):raise ValueError('词条已修改或语言不一致，请重新选择')
        if b['kind']=='corpus':
            u=lexicon.unit_info(db,unit['unit_id'])
            if b.get('link_revision',0)!=u['link'].get('revision',0):raise ValueError('语素的词典关联已变化，请重新打开关联窗口')
            return lexicon.mutate(db,'lexeme-link',{**b,'unit_id':u['id'],'unit_revision':u['revision'],'entry_revision':u['entry_revision'],'revision':u['link'].get('revision',0),'status':b.get('status','pending')},lid)
        usage,sense=lexicon.selection(x['body'],b.get('usage_id') or None,b.get('sense_id') or None)
        morphology.form_selection(x['body'],b.get('form_id'))
        import paradigms
        paradigms.validate_selection(x['body'],b.get('usage_id'),b.get('sense_id'),b.get('form_id'))
        features=morphology.check_features(db,d['language_id'],b.get('features',[]))
        ref=reference(w,i,unit)
        target=dict(lexeme_id=x['id'],usage_id=usage['id'] if usage else None,sense_id=sense['id'] if sense else None,form_id=b.get('form_id') or None,features=features,segmentation_ref=ref)
        target.update(notes=str(b.get('notes','')))
        matches=[j for j,t in enumerate(body['targets']) if t.get('segmentation_ref')==ref]
        if 'component_selection' in b:target['component_ref']=morphology.component_links.choose(x['body'],b['component_selection'])
        elif len(matches)==1 and body['targets'][matches[0]]['lexeme_id']==x['id']:target['component_ref']=body['targets'][matches[0]].get('component_ref')
        if len(matches)==1:body['targets'][matches[0]]=target
        elif matches:raise ValueError('此语素存在多个关联，请先在独立例句编辑器中核对')
        else:body['targets'].append(target)
    db.execute('UPDATE dictionary_examples SET body=?,revision=revision+1 WHERE id=?',(json.dumps(body,ensure_ascii=False),b['id']))
    return {'ok':True}


def save(db,b,lid):
    from corpus import analyze
    import json
    d=get(db,b['kind'],b['id'])
    if b.get('revision')!=d['revision']:raise ValueError('例句已修改，请重新打开形态分析')
    body=d['body'];action=b.get('action');index=b.get('word')
    if action in ('redup-save','redup-delete'):
        import reduplication
        reduplication.apply(body,b)
    elif action=='discard-orphan':
        n=b.get('orphan')
        if not isinstance(n,int) or not 0<=n<len(body.get('orphaned_morphology',[])):raise ValueError('旧分析已变化')
        body['orphaned_morphology'].pop(n)
    else:
        if not isinstance(index,int) or not 0<=index<len(body['words']):raise ValueError('请选择一个词')
        w=body['words'][index]
        if w.get('unit_type')=='phonological_boundary' and action!='delete':raise ValueError('音系边界不是语素')
        if action=='confirm-infix':w['infix_confirmation']={k:w[k] for k in ('form','gloss')}
        elif action=='delete':
            groups=w.get('morph_groups',[])
            if not any(g['id']==b.get('group_id') for g in groups):raise ValueError('组合已不存在')
            w['morph_groups']=[g for g in groups if g['id']!=b['group_id']]
        elif action=='save':
            if w.get('infix_ambiguous'):raise ValueError('请先确认中缀括号的解析')
            members=b.get('members',[]);valid={u['key']:u for u in w.get('segments',[])}
            if not isinstance(members,list) or any(not isinstance(k,str) for k in members) or len(set(members))<2 or len(set(members))!=len(members) or any(k not in valid for k in members):raise ValueError('请选择至少两个不同的语素片段')
            if b.get('type') not in TYPES:raise ValueError('组合类型无效')
            if not isinstance(b.get('gloss'),str) or not b['gloss'].strip():raise ValueError('请填写共同标注')
            groups=w.get('morph_groups',[]);gid=b.get('group_id')
            if gid and not any(g['id']==gid for g in groups):raise ValueError('待修改组合已不存在')
            for g in groups:
                if g['id']!=gid and g not in w.get('group_reviews',[]) and set(g['members'])&set(members):raise ValueError('片段已属于另一个组合，请先调整或解除该组合')
            if not isinstance(b.get('notes',''),str):raise ValueError('说明必须是文本')
            group=dict(id=gid or str(uuid.uuid4()),members=members,type=b['type'],gloss=b['gloss'].strip(),notes=b.get('notes',''),snapshot={k:w[k] for k in ('form','gloss')})
            from manual_status import clean
            group=clean({**group,'status':b.get('status')})
            w['morph_groups']=[g for g in groups if g['id']!=gid]+[group]
        else:raise ValueError('未知形态分析操作')
    analyze(body)
    table='entries' if b['kind']=='corpus' else 'dictionary_examples'
    # Source text and raw Typst stay untouched: this operation only adds analysis.
    db.execute('UPDATE '+table+' SET body=?,revision=revision+1 WHERE id=?',(json.dumps(body,ensure_ascii=False),b['id']))
    return {'ok':True}
