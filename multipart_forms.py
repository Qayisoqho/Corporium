"""Ordered dictionary realizations and read-only proposals for sentence groups."""
from collections import defaultdict
import hashlib
import json
import unicodedata

BOUNDARIES='-=+'
MAX_PARTS=12


def part(value):
    if isinstance(value,str):
        value=value.strip();left=value[0] if value[:1] in BOUNDARIES and value else ''
        right=value[-1] if value[-1:] in BOUNDARIES and value else ''
        text=value[len(left):len(value)-len(right) if right else None].strip()
    elif isinstance(value,dict):
        text=value.get('text','');left=value.get('left','');right=value.get('right','')
    else:raise ValueError('多部分形式的各部分须为文本')
    if not isinstance(text,str) or not text.strip() or '…' in text or any(c.isspace() for c in text.strip()):
        raise ValueError('请填写各部分的形式，部分内部不能含省略号或空白')
    if left not in ('','-','=','+') or right not in ('','-','=','+'):
        raise ValueError('形式的连接位置无效')
    return dict(text=text.strip(),left=left,right=right)


def circumfix(body):
    return body.get('entry_type')=='circumfix' or body.get('entry_type')=='affix' and body.get('affix_position')=='circumfix'


def normalize(value):
    if value is None:return []
    if not isinstance(value,list) or value and not 2<=len(value)<=MAX_PARTS:
        raise ValueError('不连续多部分形式须填写 2–12 个部分')
    return [part(p) for p in value]


def display(parts):return '…'.join(p['left']+p['text']+p['right'] for p in parts)
def lookup(parts):return '…'.join(p['text'] for p in parts)


def normalize_body(source,result):
    if 'form_parts' in source:result['form_parts']=normalize(source['form_parts'])
    for old,new in zip(source.get('variants',[]),result.get('variants',[])):
        if 'form_parts' in old:
            new['form_parts']=normalize(old['form_parts'])
            if new['form_parts']:new['form']=display(new['form_parts'])
    return result


def realization(form,body,*,require_circumfix=False):
    """Legacy ellipsis circumfixes can be edited without losing either half."""
    parts=normalize(body.get('form_parts'))
    if not parts and 'form_parts' not in body and circumfix(body) and '…' in form:
        pieces=form.split('…')
        if len(pieces)==2 and all(p.strip(BOUNDARIES+' ') for p in pieces):parts=normalize(pieces)
    if require_circumfix and circumfix(body):
        if len(parts)!=2:raise ValueError('环缀须填写前、后两个形式部分')
        for i,p in enumerate(parts):
            side='right' if i==0 else 'left'
            if p[side] not in ('','-'):raise ValueError('环缀的两个部分须以短杠连接宿主')
            p[side]='-'
    return (display(parts) if parts else form),parts


def forms(body,form):
    _,parts=realization(form,body)
    return parts


def align_spellings(body,spelling,old,field):
    """Literal replacement and older clients edit the public citation string.

    Preserve an explicit part edit; otherwise update its structured counterpart
    from the changed citation, rejecting a loss of the saved part boundaries.
    """
    import copy
    if not isinstance(body,dict):raise ValueError('词典内容须为对象')
    body=copy.deepcopy(body)
    if not old:return body
    previous=json.loads(old['body']) if isinstance(old['body'],str) else old['body']
    def align(current,prior,value,was):
        parts=normalize(prior.get('form_parts'))
        if not parts:return
        if 'form_parts' not in current:current['form_parts']=parts
        if value!=was and normalize(current.get('form_parts'))==parts:
            pieces=value.split('…')
            if len(pieces)!=len(parts):raise ValueError('修改多部分形式须保留原有部分数量；若要合并，请在形式编辑中取消多部分形式')
            current['form_parts']=normalize(pieces)
    align(body,previous,spelling,old[field])
    variants={v['id']:v for v in previous.get('variants',[])}
    rows=body.get('variants',[])
    if not isinstance(rows,list) or any(not isinstance(v,dict) for v in rows):raise ValueError('形式列表格式不正确')
    for v in rows:
        if v.get('id') in variants:align(v,variants[v['id']],v['form'],variants[v['id']]['form'])
    return body


def key(text):return unicodedata.normalize('NFC',text)


class Catalog:
    def __init__(self):
        self.first=defaultdict(list)
    def __bool__(self):return bool(self.first)
    def add(self,lid,gloss,parts,candidate,body):
        if not parts:return
        self.first[(lid,gloss,key(parts[0]['text']))].append((parts,candidate,
            'circumfix' if circumfix(body) else body.get('entry_type') if body.get('entry_type') in ('root','stem') else 'unspecified'))

    def proposals(self,word,lid,gloss_key,occupied=()):
        """Match ordered atoms, never dot-separated labels or arbitrary substrings.

        A pathological word with >64 choices for one realization is left for
        manual grouping. No exponential set of partial choices is retained.
        """
        if word.get('infix_ambiguous') or word.get('group_reviews'):return [],False
        units=word.get('segments',[]);occupied=set(occupied)
        occupied.update(k for g in word.get('morph_groups',[]) for k in g['members'])
        usable={i:u for i,u in enumerate(units) if u['key'] not in occupied and u.get('kind')=='simple' and len(u.get('fragments',[]))==1}
        labels={i:gloss_key(u['gloss']) for i,u in usable.items()}
        out=[];overflow=False
        def fits(i,p):
            u=usable[i]
            left=u.get('boundary','');right=units[i+1].get('boundary','') if i+1<len(units) else ''
            return key(u['form'])==key(p['text']) and (not p['left'] or p['left']==left) and (not p['right'] or p['right']==right)
        for start,u in usable.items():
            for parts,candidate,kind in self.first.get((lid,labels[start],key(u['form'])),()):
                if not fits(start,parts[0]):continue
                paths=[(start,)]
                for p in parts[1:]:
                    following=[]
                    for path in paths:
                        for i in usable:
                            if i>path[-1] and labels[i]==labels[start] and fits(i,p):following.append((*path,i))
                            if len(following)>64:break
                        if len(following)>64:break
                    if len(following)>64:overflow=True;paths=[];break
                    paths=following
                    if not paths:break
                for path in paths:
                    if not any(b>a+1 for a,b in zip(path,path[1:])):continue
                    # A hyphen must separate a selected part from intervening
                    # material; the user's citation-ignore option never supplies it.
                    if not any(units[i].get('boundary')=='-' or i+1<len(units) and units[i+1].get('boundary')=='-' for i in path):continue
                    if kind=='circumfix' and (len(path)!=2 or units[path[0]+1].get('boundary')!='-' or units[path[1]].get('boundary')!='-'):continue
                    members=[units[i]['key'] for i in path]
                    out.append(dict(members=members,type=kind,gloss=u['gloss'],form='…'.join(units[i]['form'] for i in path),candidate=candidate))
        return ([] if overflow else out),overflow


def proposal_rows(db,kind,eid,body,units,catalog,lid,gloss_key,metadata):
    import corpus,gloss_inheritance,segmentation
    body=corpus.analyze(gloss_inheritance.load(db,kind,eid,body,metadata=False))
    parents={r['position']:r for r in units if r['kind']=='word'} if kind=='corpus' else {}
    children=defaultdict(list)
    for r in units:
        if r['kind']=='morpheme':children[r['parent_id']].append(r)
    rows=[];warnings=[]
    for wi,w in enumerate(body['words']):
        if w.get('unit_type')!='word':continue
        occupied=[]
        if kind=='corpus':
            parent=parents.get(wi)
            if not parent:continue
            for r in children[parent['id']]:
                if r['position']<len(w['morphemes']):
                    u=w['morphemes'][r['position']]
                    r['coverage']=[f'{kind}:{eid}:{wi}:'+k for k in u.get('members',[u['key']])]
                if r.get('link_id') and r['position']<len(w['morphemes']):
                    u=w['morphemes'][r['position']];occupied.extend(u.get('members',[u['key']]))
        else:
            for t in body.get('targets',[]):
                ref=t.get('segmentation_ref',{})
                if ref.get('word')==wi and not ref.get('detached'):
                    u=next((u for u in w['morphemes'] if u['key']==ref.get('key')),None)
                    if u:occupied.extend(u.get('members',[u['key']]))
        effective=body.get('language_id') or lid
        found,overflow=catalog.proposals(w,effective,lambda g:gloss_key(effective,g),occupied)
        if overflow:warnings.append(dict(kind=kind,id=eid,word=wi,reason='多部分形式的选段方式过多，请在分段与组合核对中手动选择'))
        for p in found:
            identity=json.dumps([kind,eid,wi,p['members'],w['form'],w['gloss']],ensure_ascii=False,separators=(',',':'))
            gid='auto-'+hashlib.sha256(identity.encode()).hexdigest()[:32]
            group={k:p[k] for k in ('members','type','gloss')}
            group.update(id=gid,notes='',snapshot={k:w[k] for k in ('form','gloss')})
            prefix=f'{kind}:{eid}:{wi}:'
            c=p['candidate']
            row=dict(entry_id=eid,entry_revision=metadata['entry_revision'],kind='morpheme',
                form=p['form'],gloss=p['gloss'],unit_id='multipart:'+gid,unit_revision=metadata['entry_revision'],
                effective_language_id=effective,**{k:metadata[k] for k in ('title','sentence_position')},**c,
                multipart_group=dict(kind=kind,id=eid,word=wi,group=group),
                coverage=[prefix+k for k in p['members']])
            row['match_reason']=f'组合 {len(p["members"])} 个不连续部分；'+c['match_reason']
            row['candidate_id']=hashlib.sha256(json.dumps([row['unit_id'],c['lexeme_id'],c['usage_id'],c['sense_id'],c['form_id']],ensure_ascii=False).encode()).hexdigest()
            rows.append(row)
    return rows,warnings


def conflicts(a,b):
    return a['unit_id']==b['unit_id'] or bool(set(a.get('coverage',()))&set(b.get('coverage',())))


def finish_plan(matches,ambiguous,suggestions,groups):
    """Competing atoms, target senses and overlapping groups remain choices."""
    if not groups:return
    groups=list({r['candidate_id']:r for r in groups}.values())
    group_units={g['unit_id'] for g in groups}
    group_coverage={k for g in groups for k in g.get('coverage',[])}
    def competing(row):return row['unit_id'] in group_units or bool(group_coverage.intersection(row.get('coverage',())))
    def suggest(row):
        r=dict(row)
        r['candidate_id']=hashlib.sha256(json.dumps([r['unit_id'],r['lexeme_id'],r['usage_id'],r['sense_id'],r.get('form_id')],ensure_ascii=False).encode()).hexdigest()
        r['default_selected']=False
        r['match_reason']+='；与多部分组合共用片段，请选择一种关联'
        suggestions.append(r)
    kept=[]
    for r in matches:
        if competing(r):suggest(r)
        else:kept.append(r)
    matches[:]=kept;kept=[]
    for r in ambiguous:
        if competing(r):
            for c in r['candidates']:suggest({**{k:v for k,v in r.items() if k!='candidates'},**c})
        else:kept.append(r)
    ambiguous[:]=kept
    suggestions.extend(groups)
    # Index shared coverage to avoid a quadratic comparison of a large corpus.
    peers=defaultdict(set)
    for r in suggestions:
        for k in ['unit:'+r['unit_id'],*r.get('coverage',[])]:peers[k].add(r['candidate_id'])
    for r in suggestions:
        related=set().union(*(peers[k] for k in ['unit:'+r['unit_id'],*r.get('coverage',[])]))-{r['candidate_id']}
        if r.get('multipart_group'):r['default_selected']=not related
        elif related:r['default_selected']=False
        if related:r['conflicts']=sorted(related)


def apply(db,item,lid):
    """Create one stable group and its binding in the caller's undo transaction."""
    import segmentation,lexicon
    p=item['multipart_group'];d=segmentation.get(db,p['kind'],p['id'])
    w=d['body']['words'][p['word']];g=p['group']
    if {k:w[k] for k in ('form','gloss')}!=g['snapshot']:raise ValueError('例句已变化，请重新预览多部分形式')
    segmentation.save(db,dict(kind=p['kind'],id=p['id'],revision=d['revision'],word=p['word'],
        action='save',members=g['members'],type=g['type'],gloss=g['gloss'],notes=g['notes']),lid)
    # save() allocates the real UUID. Read it back rather than persisting preview IDs.
    table='entries' if p['kind']=='corpus' else 'dictionary_examples'
    body=json.loads(db.execute('SELECT body FROM '+table+' WHERE id=?',(p['id'],)).fetchone()[0])
    group=body['words'][p['word']]['morph_groups'][-1]
    if p['kind']=='corpus':lexicon.sync_entry(db,p['id'],preserve_complex=True)
    fresh=segmentation.get(db,p['kind'],p['id'])
    segmentation.link(db,dict(kind=p['kind'],id=p['id'],revision=fresh['revision'],word=p['word'],
        key='group:'+group['id'],lexeme_id=item['lexeme_id'],lexeme_revision=item['lexeme_revision'],
        usage_id=item['usage_id'],sense_id=item['sense_id'],form_id=item.get('form_id'),notes=''),lid)
