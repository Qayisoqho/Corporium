"""Materialize spelling edits at live occurrences of the referenced base or variant."""
import copy
import json
import re
import unicodedata
from collections import defaultdict
from difflib import SequenceMatcher

import corpus
import long_tasks
import dictionary_targets
from dictionary_gloss_sync import apply_record, raw_ranges
from morpheme_colors import plain_map


def changes_for(changes):
    result={}
    for (table,_),(before,after) in list(changes.items()):
        if table not in ('lexemes','morphemes') or not before or not after:continue
        field='form' if table=='morphemes' else 'headword'
        def forms(row):
            import multipart_forms
            body=json.loads(row['body'])
            def spelling(form,data):
                parts=multipart_forms.forms(data,form)
                return multipart_forms.lookup(parts) if parts else form
            return {None:spelling(row[field],body),**{v['id']:spelling(v['form'],v) for v in body.get('variants',[])}}
        a,z=forms(before),forms(after)
        delta={key:(value,z[key]) for key,value in a.items() if key in z and value!=z[key]}
        if delta:result[after['id']]=delta
    return result


def key(value):return unicodedata.normalize('NFC',value)


def surface(value,before,after):
    # Affix markers belong to the dictionary citation form, not to a surface
    # component. Keep the sentence's actual separators and surrounding punctuation.
    if key(value)==key(before.strip('-=.')):return after.strip('-=.')
    if key(value)==key(before):return after
    if '…' in value and key(value.replace('…',''))==key(before.strip('-=.')):return after.strip('-=.')
    return None


def clusters(text):
    result=[]
    for char in text:
        if result and unicodedata.combining(char):result[-1]+=char
        else:result.append(char)
    return result


def spread(parts,value):
    """Keep explicit discontinuous boundaries, including combining characters."""
    if len(parts)==1:return [value]
    for separator in ('…','...'):
        if separator in value:
            result=value.split(separator)
            if len(result)!=len(parts) or not all(result):raise ValueError('多部分语素的新形式须保留原有片段数量')
            return result
    old=[clusters(p) for p in parts];a=[c for p in old for c in p];z=clusters(value)
    matches=SequenceMatcher(None,list(map(key,a)),list(map(key,z)),autojunk=False).get_opcodes()
    cuts=[];cut=0
    for part in old[:-1]:
        cut+=len(part)
        for op,i,j,x,y in matches:
            if i<=cut<=j:
                cuts.append(x+cut-i if op=='equal' else y if cut==j else x+round((cut-i)*(y-x)/(j-i)) if j!=i else y)
                break
    offsets=[0,*cuts,len(z)];result=[''.join(z[a:b]) for a,b in zip(offsets,offsets[1:])]
    if len(result)!=len(parts) or not all(result):raise ValueError('新形式无法保留原有中缀或多部分结构，请用 … 标明各片段')
    return result


def transform(word,rules):
    old=copy.deepcopy(word);new=copy.deepcopy(word);raw=word['form'];plain,mapping=plain_map(raw)
    units={m['key']:m for m in word.get('morphemes',[])}
    units['@word']=dict(key='@word',form=plain,fragments=[dict(start=0,end=len(plain),text=plain)])
    edits={}
    for name,(before,after) in rules.items():
        unit=units.get(name)
        if not unit:continue
        value=surface(unit['form'],before,after)
        if value is None and name=='@word':
            # A whole inflected word may reference its lexical base. Only a unique
            # complete component identifies that base; never replace a substring.
            choices=[(u,surface(u['form'],before,after)) for u in word.get('morphemes',[])]
            choices=[(u,v) for u,v in choices if v is not None]
            if len(choices)==1:unit,value=choices[0]
        if value is None:continue  # An unspecified different allomorph is not the base.
        spans=raw_ranges(unit,mapping,raw,'fragments')
        if not spans:continue
        fragments=unit['fragments']
        replacements=spread([f['text'] for f in fragments],value)
        if len(spans)!=len(replacements):raise ValueError('书写标记跨越多个已关联成分，无法安全同步形式')
        for span,text in zip(spans,replacements):
            markup=re.fullmatch(r'#sub\[[^\[\]]*\]',raw[span[0]:span[1]])
            if markup:text='#sub['+text+']'
            if span in edits and edits[span]!=text:raise ValueError('同一词格的多个关联产生不同形式更新，请先调整重复关联')
            edits[span]=text
    ordered=sorted(edits)
    if any(a[1]>b[0] for a,b in zip(ordered,ordered[1:])):raise ValueError('整词与语素的形式更新范围重叠，请先调整重复关联')
    for (a,z),value in sorted(edits.items(),reverse=True):raw=raw[:a]+value+raw[z:]
    if raw==word['form']:return old
    new['form']=raw
    a={k:old[k] for k in ('form','gloss')};z={k:new[k] for k in ('form','gloss')}
    for group in new.get('morph_groups',[]):
        if group.get('snapshot')==a:group['snapshot']=z.copy()
    if old.get('infix_confirmation')==a:new['infix_confirmation']=z.copy()
    corpus.analyze(dict(ipa='',translation='',words=[new]))
    structure=lambda w:[(m['key'],m['kind'],len(m['fragments']),m.get('members'),m.get('boundary')) for m in w.get('morphemes',[])]
    if structure(new)!=structure(old) or new.get('infix_ambiguous')!=old.get('infix_ambiguous'):
        raise ValueError('新形式会改变已关联词格的语素切分，请保留原有语素边界后重试')
    checked,errors=corpus.parse(corpus.export_entry(dict(function='pass',ipa='',translation='',words=[new])))
    if errors or len(checked)!=1 or [(w['form'],w['gloss']) for w in checked[0]['words']]!=[(new['form'],new['gloss'])]:
        raise ValueError('新形式包含未配对括号或未转义引号，无法安全同步例句，请修正后重试')
    return new


def sync(db,changes):
    changed=changes_for(changes)
    if not changed:return
    records=defaultdict(list);independent=set();ids=list(changed)
    for start in range(0,len(ids),400):
        batch=ids[start:start+400];marks=','.join('?' for _ in batch)
        for row in db.execute('''SELECT l.lexeme_id,a.form_id,u.entry_id,u.kind,u.position,
            COALESCE(p.position,u.position) word_position,u.form,u.gloss,x.language_id
            FROM lexical_links l JOIN corpus_units u ON u.id=l.unit_id
            LEFT JOIN corpus_units p ON p.id=u.parent_id JOIN '''+dictionary_targets.IDENTITIES+''' x ON x.id=l.lexeme_id
            LEFT JOIN morphology_analyses a ON a.id=l.id
            WHERE u.active=1 AND (p.id IS NULL OR p.active=1) AND l.lexeme_id IN ('''+marks+')',batch):
            if (row['form_id'] or None) in changed[row['lexeme_id']]:records[row['entry_id']].append({**dict(row),'form_id':row['form_id'] or None})
        independent.update(r[0] for r in db.execute("SELECT DISTINCT e.id FROM dictionary_examples e,json_each(e.body,'$.targets') t WHERE json_extract(t.value,'$.lexeme_id') IN ("+marks+')',batch))
    from dictionary_gloss_sync import sync_progress,SyncCache,source_records
    total=len(records)+len(independent);cache=SyncCache()
    for index,(eid,row,unit_state) in enumerate(source_records(db,records)):
        sync_progress(index,total,'形式')
        links=records[eid]
        body=corpus.analyze(json.loads(row['body']),cache=cache.analysis);rules=defaultdict(dict)
        for link in links:
            if (body.get('language_id') or row['owner_language'])!=link['language_id']:continue
            i=link['word_position']
            if not 0<=i<len(body['words']):continue
            word=body['words'][i];units=word.get('morphemes',[])
            if word.get('unit_type')!='word':continue
            unit=word if link['kind']=='word' else units[link['position']] if 0<=link['position']<len(units) else None
            if not unit or (unit['form'],unit['gloss'])!=(link['form'],link['gloss']):continue
            name='@word' if link['kind']=='word' else unit['key']
            rules[i][name]=changed[link['lexeme_id']][link['form_id']]
        apply_record(db,'corpus',row,rules,transform,analyzed=body,cache=cache,unit_state=unit_state)
    for index,(eid,row,_) in enumerate(source_records(db,independent,'independent'),len(records)):
        sync_progress(index,total,'形式')
        body=corpus.analyze(json.loads(row['body']),cache=cache.analysis);rules=defaultdict(dict)
        for target in body.get('targets',[]):
            delta=changed.get(target['lexeme_id'],{}).get(target.get('form_id') or None);ref=target.get('segmentation_ref')
            if not delta or not ref or target.get('segmentation_review') or ref.get('detached'):continue
            if body['words'][ref['word']].get('unit_type')!='word':continue
            at=rules[ref['word']]
            if ref['key'] in at and at[ref['key']]!=delta:raise ValueError('同一词格的多个关联产生不同形式更新，请先调整重复关联')
            at[ref['key']]=delta
        apply_record(db,'independent',row,rules,transform,analyzed=body,cache=cache)
