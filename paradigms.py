"""Optional inflection tables. Forms share variant IDs; meanings have stable IDs.

Template structure stays linked; forms and meanings remain entry-owned evidence.
Form meanings use their owning usage and their own sense identity in gloss_meanings.
"""
import uuid
import re
import unicodedata
import sense_gloss


def addition(value):
    """Literal tag spellings, like ordinary glosses; picking a tag inserts its symbol."""
    value=text(value).strip()
    if not value:return ''
    atoms=[p.strip() for p in value.split('.')]
    for atom in atoms:
        plain=re.sub(r'#(?:sub|super|sup)\[[A-Za-z0-9]+\]','',atom)
        if not plain or re.search(r'[\s.\-=:+/;\\,!?，。；：！？\[\](){}<>#]',plain):
            raise ValueError('附加标签请用点号分隔；带连接符或复杂结构的标注请使用独立标注')
    return '.'.join(dict.fromkeys(atoms))


def compose(base,extra):
    base=base.strip();extra=addition(extra)
    if not base:raise ValueError('继承标注须选择已填写简短释义的基本义项')
    if not extra:return base
    # Superscript/subscript decorations are part of an atom, not scope brackets.
    plain=re.sub(r'#(?:sub|super|sup)\[[A-Za-z0-9]+\]','',base)
    if re.search(r'[\s\-=+<>\[\](){}:;/\\#]',plain):
        raise ValueError('基本义项的标注含复杂结构，无法直接附加标签；请使用独立标注')
    parts=base.split('.')
    if any(not p for p in parts):raise ValueError('基本义项的标注含空片段，请先修正或使用独立标注')
    seen={p.casefold() for p in parts}
    for p in extra.split('.'):
        if p.casefold() not in seen:parts.append(p);seen.add(p.casefold())
    return '.'.join(parts)


def effective_gloss(body,table,meaning):
    if meaning.get('gloss_mode','independent')!='inherit':return meaning.get('short_gloss','')
    base=next((s for u in body.get('usages',[]) if u['id']==table['usage_id'] for s in u['senses'] if s['id']==meaning.get('base_sense_id')),None)
    if base is None:raise ValueError('继承标注对应的基本义项已不存在，请先调整变形表')
    return compose(sense_gloss.effective(base),meaning.get('gloss_addition',''))


def project(body,ordinary=True):
    """Search/replace projection. Never persist expanded labels in inherited cells."""
    projected={**body}
    if ordinary:
        if 'gloss' in body:projected['gloss']=sense_gloss.effective(body,'gloss')
        if 'senses' in body:projected['senses']=[{**s,'gloss':sense_gloss.effective(s,'gloss')} for s in body['senses']]
        if 'usages' in body:projected['usages']=[{**u,'senses':[{**s,'short_gloss':sense_gloss.effective(s)} for s in u.get('senses',[])]} for u in body['usages']]
    return {**projected,'paradigms':[{**t,'rows':[{**r,'realizations':[{**f,'meanings':[
        {**m,'short_gloss':effective_gloss(body,t,m)} for m in f['meanings']
    ]} for f in r['realizations']]} for r in t['rows']]} for t in body.get('paradigms',[])]}


def text(value):
    if not isinstance(value,str):raise ValueError('变形表字段须为文本')
    return value


def rows(value):
    if not isinstance(value,list) or any(not isinstance(x,dict) for x in value):raise ValueError('变形表格式不正确')
    return value


def layout(value,identity):
    dimensions=value.get('dimensions',[])
    if not isinstance(dimensions,list) or not 1<=len(dimensions)<=12 or any(not isinstance(x,str) or not x.strip() for x in dimensions):raise ValueError('变形表须有 1–12 个非空栏目名称')
    result=dict(id=identity(value),title=text(value.get('title','')).strip(),dimensions=[d.strip() for d in dimensions],rows=[])
    if not result['title']:raise ValueError('请填写变形表名称')
    for row in rows(value.get('rows',[])):
        labels=row.get('labels',[])
        if not isinstance(labels,list) or len(labels)!=len(dimensions) or any(not isinstance(x,str) for x in labels):raise ValueError('变形表行与栏目数量不一致')
        state=row.get('state','unfilled')
        if state not in ('unfilled','missing','filled'):raise ValueError('变形表行状态无效')
        item=dict(id=identity(row),labels=labels,state=state,realizations=[])
        if row.get('gloss_addition'):item['gloss_addition']=addition(row['gloss_addition'])
        result['rows'].append(item)
    return result


def templates(values):
    seen=set()
    def identity(v):
        key=v.get('id') or str(uuid.uuid4())
        if not isinstance(key,str) or key in seen:raise ValueError('变形表模板标识重复')
        seen.add(key);return key
    result=[]
    for value in rows(values):
        item=layout(value,identity)
        # A template carries layout only. It cannot smuggle form/meaning references.
        for row in item['rows']:row.pop('realizations');row['state']='unfilled'
        result.append(item)
    return result


def normalize(body,result):
    values=rows(body.get('paradigms',[]))
    if not values:return result
    seen={p['id'] for p in [*result.get('orthographies',[]),*result['variants'],*result['usages'],*(s for u in result['usages'] for s in u['senses'])]}
    def identity(value):
        key=value.get('id') or str(uuid.uuid4())
        if not isinstance(key,str) or key in seen:raise ValueError('变形表、形式或意义的标识重复')
        seen.add(key);return key
    forms={v['id'] for v in result['variants']};usages={u['id']:u for u in result['usages']}
    tables=[]
    for source in rows(values):
        table=layout(source,identity);uid=text(source.get('usage_id',''))
        if uid not in usages:raise ValueError('请为变形表选择词类用法')
        table.update(usage_id=uid,notes=text(source.get('notes','')),template_id=text(source.get('template_id','')))
        senses={s['id'] for s in usages[uid]['senses']}
        default=text(source.get('default_base_sense_id',''))
        if default:
            if default not in senses:raise ValueError('变形表的默认基本义项不存在或不属于本用法')
            table['default_base_sense_id']=default
        for original,row in zip(source.get('rows',[]),table['rows']):
            if original.get('template_row_id'):row['template_row_id']=text(original['template_row_id'])
            for item in rows(original.get('realizations',[])):
                fid=text(item.get('form_id',''))
                if fid not in forms:
                    label=' · '.join(row['labels']) or '未命名行'
                    raise ValueError(f'变形表「{table["title"]}」的「{label}」找不到引用的词形，请重新选择或填写该行词形。')
                realization=dict(id=identity(item),form_id=fid,meanings=[])
                for meaning in rows(item.get('meanings',[])):
                    base=text(meaning.get('base_sense_id',''))
                    if base and base not in senses:raise ValueError('变形意义对应的基本义项已不存在或不属于本用法')
                    m=dict(id=identity(meaning),base_sense_id=base,short_gloss=text(meaning.get('short_gloss','')),definition=text(meaning.get('definition','')),notes=text(meaning.get('notes','')))
                    mode=meaning.get('gloss_mode','independent')
                    if mode not in ('independent','inherit'):raise ValueError('变形标注模式无效')
                    if mode=='inherit':
                        m.update(gloss_mode=mode,gloss_addition=addition(meaning.get('gloss_addition','')),short_gloss='')
                        effective_gloss(result,table,m)
                    realization['meanings'].append(m)
                row['realizations'].append(realization)
            if row['state']!='filled' and row['realizations']:raise ValueError('已有变形形式的行须设为“已填写”；请先移除形式再改变状态')
        tables.append(table)
    result['paradigms']=tables
    return result


def meanings(body):
    for table in body.get('paradigms',[]):
        for row in table['rows']:
            if row['state']!='filled':continue
            for form in row['realizations']:
                for meaning in form['meanings']:
                    yield table,row,form,meaning


def usages(body):
    """Read projection only; never store form meanings among base entry senses."""
    added={}
    for table,row,form,meaning in meanings(body):
        added.setdefault(table['usage_id'],[]).append({**meaning,'short_gloss':effective_gloss(body,table,meaning),'features':[],'tags':[],
            'paradigm_form_id':form['form_id'],'paradigm_label':table['title']+' / '+' · '.join(row['labels'])})
    return [{**u,'senses':[*[{**s,'short_gloss':sense_gloss.effective(s)} for s in u['senses']],*added.get(u['id'],[])]} for u in body.get('usages',[])]


def candidates(body):
    """Build once per matching request, with no cross product of cells and forms."""
    assigned={f['form_id'] for t in body.get('paradigms',[]) for r in t['rows'] for f in r['realizations']}
    ordinary=[None,*[f for f in body.get('variants',[]) if f['id'] not in assigned]]
    forms={f['id']:f for f in body.get('variants',[])}
    for u in usages(body):
        for s in u['senses']:
            for form in ([forms[s['paradigm_form_id']]] if 'paradigm_form_id' in s else ordinary):
                yield u,s,form


def matching_candidates(body,headword,gloss_key):
    """Prefer the base sense when a table merely repeats its primary form.

    This is a matching projection, not an identity migration: manual references
    to table meanings and genuinely distinct base senses keep their stable IDs.
    """
    primary=unicodedata.normalize('NFC',headword)
    def key(u,s,form=None):
        features=[*body.get('features',[]),*u.get('features',[]),*s.get('features',[]),*(form.get('features',[]) if form else [])]
        return gloss_key(s.get('short_gloss',''),features)
    base={u['id']:{s['id']:key(u,{**s,'short_gloss':sense_gloss.effective(s)}) for s in u['senses']} for u in body.get('usages',[])}
    for u,s,form in candidates(body):
        if form and s.get('paradigm_form_id') and unicodedata.normalize('NFC',form['form'])==primary:
            meanings=base.get(u['id'],{})
            matches=[sid for sid,value in meanings.items() if value==key(u,s,form)]
            declared=s.get('base_sense_id')
            if (declared in matches if declared else len(matches)==1):continue
        yield u,s,form


def validate_selection(body,uid,sid,fid):
    for table,row,form,meaning in meanings(body):
        if meaning['id']==sid and (table['usage_id']!=uid or form['form_id']!=fid):
            raise ValueError('变形意义必须关联对应的词类用法与具体形式')


def remap(body,owner,submap):
    """Language exchange creates fresh table/row/realization/meaning identities."""
    for table in body.get('paradigms',[]):
        table['usage_id']=submap[(owner,table['usage_id'])]
        if table.get('default_base_sense_id'):table['default_base_sense_id']=submap[(owner,table['default_base_sense_id'])]
        # The copied structure remains self-contained if its source template is absent.
        table['template_id']=''
        for value in [table,*table['rows']]:value['id']=str(uuid.uuid4())
        for row in table['rows']:
            row.pop('template_row_id',None)
            for form in row['realizations']:
                form['id']=str(uuid.uuid4());form['form_id']=submap[(owner,form['form_id'])]
                for meaning in form['meanings']:
                    old=meaning['id'];meaning['id']=str(uuid.uuid4());submap[(owner,old)]=meaning['id']
                    if meaning['base_sense_id']:meaning['base_sense_id']=submap[(owner,meaning['base_sense_id'])]
