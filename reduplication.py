"""Sentence-local reduplicant → base relations; spelling never implies a link.

Word identities travel with explicit slots. Endpoints carry form/segment snapshots,
so destructive edits leave reviewable evidence instead of retargeting by position.
These identities are local to a sentence (including a frozen/exported sentence).
"""
import copy
import json
import re
import uuid

KINDS={'partial':'部分重叠','full':'完全重叠','modified':'变形重叠','unspecified':'未细分'}
PREFIX='// corporium-reduplication-v1 '


def units(word):
    import segmentation
    from corpus import clean
    if word.get('unit_type') in ('punctuation','phonological_boundary') or not word.get('form','').strip():return []
    form=clean(word['form'])
    # Form-only options are available even before the gloss has been filled in.
    try:parts,_=segmentation.parse_word(form,form,True)
    except ValueError:parts=[]
    parsed={u['key']:u for u in parts}
    for u in word.get('morphemes',[]):parsed[u['key']]=u
    return [dict(key='@word',form=word['form'],fragments=[dict(start=0,end=len(form),text=form)])]+list(parsed.values())


def endpoint(word,key):
    unit=next((u for u in units(word) if u['key']==key),None)
    if not unit:raise ValueError('所选部分已变化，请重新选择')
    return dict(word_id=word['redup_id'],key=key,form=unit['form'],snapshot=word['form'],
                fragments=[{k:f[k] for k in ('start','end','text')} for f in unit['fragments']])


def locate(body,ref):
    found=[(i,w) for i,w in enumerate(body['words']) if w.get('redup_id')==ref.get('word_id')]
    if len(found)!=1:return None
    i,w=found[0]
    try:current=endpoint(w,ref['key'])
    except (ValueError,KeyError):return None
    return i if current==ref else None


def overlap(a,b):
    return a['word_id']==b['word_id'] and any(x['start']<y['end'] and y['start']<x['end'] for x in a['fragments'] for y in b['fragments'])


def check_relations(body,*,resolve=True):
    """Validate storage, including stale endpoints, without discarding old analysis."""
    words=body.get('words',[]);ids=[w['redup_id'] for w in words if 'redup_id' in w]
    if any(not isinstance(v,str) or not v or len(v)>100 for v in ids) or len(ids)!=len(set(ids)):raise ValueError('重叠词格身份重复或无效')
    rows=body.get('reduplications',[])
    if not isinstance(rows,list) or len(rows)>500:raise ValueError('重叠关系格式无效或过多')
    seen=set()
    for r in rows:
        if not isinstance(r,dict) or not isinstance(r.get('id'),str) or not r['id'] or r['id'] in seen:raise ValueError('重叠关系身份无效')
        seen.add(r['id'])
        if r.get('type') not in KINDS or not isinstance(r.get('notes',''),str):raise ValueError('重叠类型或备注无效')
        for name in ('source','base'):
            ref=r.get(name)
            if not isinstance(ref,dict) or set(ref)!={'word_id','key','form','snapshot','fragments'} or any(not isinstance(ref[k],str) for k in ('word_id','key','form','snapshot')):raise ValueError('重叠引用无效')
            fs=ref['fragments']
            if not isinstance(fs,list) or not fs or any(not isinstance(f,dict) or set(f)!={'start','end','text'} or type(f['start']) is not int or type(f['end']) is not int or not 0<=f['start']<f['end'] or not isinstance(f['text'],str) for f in fs):raise ValueError('重叠片段无效')
        if overlap(r['source'],r['base']):raise ValueError('重叠部分与基底不能指向相同或交叠的部分')
    if not resolve:return
    # A target may contain another source: detect cycles across spans, not labels.
    active=[r for r in rows if locate(body,r['source']) is not None and locate(body,r['base']) is not None]
    edges={i:[j for j,s in enumerate(active) if overlap(r['base'],s['source'])] for i,r in enumerate(active)}
    done=set();path=set()
    def visit(i):
        if i in path:raise ValueError('重叠基底关系不能形成循环')
        if i in done:return
        path.add(i)
        for j in edges[i]:visit(j)
        path.remove(i);done.add(i)
    for i in edges:visit(i)


def describe(body):
    rows=[];claimed=set()
    for r in body.get('reduplications',[]):
        source=locate(body,r['source']);base=locate(body,r['base'])
        review=source is None or base is None
        rows.append(dict(r,source_word=source,base_word=base,review=review))
        if not review:claimed.add((source,r['source']['key']))
    candidates=[]
    import segmentation
    for i,w in enumerate(body.get('words',[])):
        if '~' not in w['form'] or w.get('unit_type') in ('punctuation','phonological_boundary'):continue
        parts=segmentation.split_parts(w['form'])
        for n,p in enumerate(parts[:-1]):
            if p[2]!='~':continue
            keys=[f'r:{n}:host',f'r:{n+1}:host']
            if any((i,k) in claimed for k in keys):continue
            candidates.append(dict(word=i,keys=keys,forms=[p[0],parts[n+1][0]]))
    return dict(relations=rows,candidates=candidates)


def decorate(body,warnings):
    # Display overlays are generated only by the read-side color enrichment.
    for word in body['words']:word.pop('redup_colors',None)
    if body.get('reduplications') or any('~' in w['form'] for w in body['words']):
        info=describe(body);body['reduplication_info']=info
        if any(r['review'] for r in info['relations']):warnings.append('有重叠关系待核对，请打开“分段与组合核对”；原关系已保留')
    else:body.pop('reduplication_info',None)


def options(body):
    return [dict(word=i,key=u['key'],form=u['form'],label=f"{i+1}. {u['form']}"+('（整词）' if u['key']=='@word' else '')) for i,w in enumerate(body['words']) for u in units(w)]


def apply(body,b):
    rid=b.get('relation_id');old=body.get('reduplications',[])
    if rid and not any(r['id']==rid for r in old):raise ValueError('重叠关系已变化，请重新打开')
    if b.get('action')=='redup-delete':
        if not rid:raise ValueError('请选择重叠关系')
        body['reduplications']=[r for r in old if r['id']!=rid];prune_ids(body);return
    refs=[]
    for name in ('source','base'):
        v=b.get(name,{})
        if type(v.get('word')) is not int or not 0<=v['word']<len(body['words']):raise ValueError('请选择本句中的词格或语素')
        word=body['words'][v['word']]
        word.setdefault('redup_id',str(uuid.uuid4()))
        refs.append(endpoint(word,v.get('key')))
    if any(r['id']!=rid and r['source']==refs[0] for r in old):raise ValueError('这个部分已有重叠基底，请编辑已有关系')
    row=dict(id=rid or str(uuid.uuid4()),source=refs[0],base=refs[1],type=b.get('type','unspecified'),notes=b.get('notes',''))
    body['reduplications']=[r for r in old if r['id']!=rid]+[row]
    check_relations(body)
    prune_ids(body)


def prune_ids(body):
    used={r[name]['word_id'] for r in body.get('reduplications',[]) for name in ('source','base')}
    for w in body['words']:
        if w.get('redup_id') not in used:w.pop('redup_id',None)


def accept(old,new,incoming):
    """Accept explicit inline draft edits, retaining stale pre-existing relations."""
    if 'reduplications' not in incoming:return
    new['reduplications']=copy.deepcopy(incoming['reduplications']);check_relations(new)
    previous={r['id']:r for r in old.get('reduplications',[])}
    for r in new['reduplications']:
        if r!=previous.get(r['id']) and (locate(new,r['source']) is None or locate(new,r['base']) is None):raise ValueError('新建或修改的重叠关系与当前词形不一致，请重新选择')
    prune_ids(new)


def preserve(old,new):
    if not old.get('reduplications'):return
    new['reduplications']=copy.deepcopy(old['reduplications'])
    # Whole-text editors offer no slot identity. Match only provably unambiguous
    # words; changed/repeated words retain their old endpoints as review records.
    before=old['words'];after=new['words']
    for w in after:w.pop('redup_id',None)
    if [(w['form'],w['gloss']) for w in before]==[(w['form'],w['gloss']) for w in after]:pairs=zip(before,after)
    else:
        pairs=[]
        for w in before:
            if sum(v['form']==w['form'] for v in before)==1 and sum(v['form']==w['form'] for v in after)==1:pairs.append((w,next(v for v in after if v['form']==w['form'])))
    for a,b in pairs:
        if a.get('redup_id'):b['redup_id']=a['redup_id']


def fork(body):
    """Remap all live and retired identities when copying a whole sentence."""
    mapping={}
    def fresh(v):return mapping.setdefault(v,str(uuid.uuid4()))
    for w in body['words']:
        if w.get('redup_id'):w['redup_id']=fresh(w['redup_id'])
    for r in body.get('reduplications',[]):
        r['id']=str(uuid.uuid4())
        for name in ('source','base'):r[name]['word_id']=fresh(r[name]['word_id'])
    body.pop('reduplication_info',None)
    return body


def transfer(source,words,target):
    selected={w.get('redup_id') for w in words};rows=[copy.deepcopy(r) for r in source.get('reduplications',[]) if r['source']['word_id'] in selected or r['base']['word_id'] in selected]
    if not rows:return
    copied=dict(words=words,reduplications=rows);fork(copied)
    target.setdefault('reduplications',[]).extend(copied['reduplications'])


def values(body,position):
    return index(body).get(position,[])


def index(body):
    result={}
    for r in body.get('reduplications',[]):
        source=locate(body,r['source']);base=locate(body,r['base'])
        if source is not None and base is not None:result.setdefault(source,[]).append(r['base']['form'])
    return result


def portable(body):
    return dict(words=[{k:w[k] for k in ('redup_id','morph_groups','infix_confirmation') if k in w} for w in body['words']],reduplications=body.get('reduplications',[]))


def export_prefix(body):
    return PREFIX+json.dumps(portable(body),ensure_ascii=False,separators=(',',':'))+'\n' if body.get('reduplications') else ''


def import_prefix(source,start,body):
    end=start
    while end and source[end-1].isspace():end-=1
    line=source[source.rfind('\n',0,end)+1:end]
    if not line.startswith(PREFIX):return
    data=json.loads(line[len(PREFIX):])
    if not isinstance(data,dict) or not isinstance(data.get('words'),list) or len(data['words'])!=len(body['words']):raise ValueError('重叠关系附注与词格数量不一致')
    for word,fields in zip(body['words'],data['words']):
        for key in ('redup_id','morph_groups','infix_confirmation'):
            if key in fields:word[key]=fields[key]
    body['reduplications']=data.get('reduplications',[]);check_relations(body)


def preview(b):
    from corpus import analyze
    body=copy.deepcopy(b.get('body',{}))
    if not isinstance(body,dict) or not isinstance(body.get('words'),list) or len(body['words'])>5000:raise ValueError('例句格式无效或过长')
    for w in body['words']:
        if not isinstance(w,dict) or any(not isinstance(w.get(k),str) for k in ('form','gloss')):raise ValueError('词格格式无效')
    check_relations(body,resolve=False)
    body.setdefault('ipa','');body.setdefault('translation','');analyze(body);check_relations(body)
    if b.get('action') in ('redup-save','redup-delete'):apply(body,b);analyze(body)
    return dict(body=body,options=options(body),info=describe(body))
