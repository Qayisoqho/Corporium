"""Materialize meaning edits only at active, explicitly sense-bound occurrences."""
import copy
import json
import re
from collections import defaultdict,OrderedDict

import corpus
import long_tasks
import segmentation
import dictionary_targets
from morpheme_colors import plain_map


class SyncCache:
    """Reuse only pure, already-validated word transformations in one operation."""
    def __init__(self):
        self.analysis=corpus.WordAnalysisCache();self.transformed=OrderedDict();self.bytes=0

    def transform(self,word,rules,transformer):
        encoded=json.dumps([word,rules],ensure_ascii=False,sort_keys=True).encode('utf-8')
        key=(transformer,encoded);saved=self.transformed.get(key)
        if saved is not None:
            self.transformed.move_to_end(key);return json.loads(saved)
        result=transformer(word,rules)
        saved=json.dumps(result,ensure_ascii=False).encode('utf-8');size=len(encoded)+len(saved)
        if size<=4*1024**2:
            while self.transformed and (self.bytes+size>4*1024**2 or len(self.transformed)>=256):
                (_,old),value=self.transformed.popitem(last=False);self.bytes-=len(old)+len(value)
            self.transformed[key]=saved;self.bytes+=size
        return result


def meanings(row, kind):
    body=json.loads(row['body'])
    if kind=='morphemes' and body.get('usages') is None:
        return {('@morpheme','@main'):body.get('gloss',''),
                **{('@morpheme',s['id']):s.get('gloss','') for s in body.get('senses',[])}}
    import paradigms
    return {(u['id'],s['id']):s.get('short_gloss','')
            for u in paradigms.usages(body) for s in u.get('senses',[])}


def changes_for(changes):
    changed={}
    for (table,_),(before,after) in list(changes.items()):
        if table not in ('lexemes','morphemes') or not before or not after or before['body']==after['body']:continue
        a,z=meanings(before,table),meanings(after,table)
        delta={key:(value,z[key]) for key,value in a.items() if key in z and value!=z[key]}
        if delta:changed[after['id']]=delta
    return changed


def replace_short(value,old,new):
    """Keep separately annotated features and simple rich-text wrappers."""
    def compact(value):
        return corpus.compact_gloss(re.sub(r'#(?:sub|sup|super)\[\]|\[\]','',value))
    if old:
        atom=lambda token:re.compile(r'(^|[._:;\\\s\[\-=+~<>])('+re.escape(token)+r')(?=$|[._:;\\\s\]\-=+~<>]|#(?:sub|sup|super)\[)',re.IGNORECASE)
        match=atom(old).search(value)
        if match:
            return compact(value[:match.start(2)]+new+value[match.end(2):])
        # Automatic association permits ordinary registered tags in either order.
        parts=re.split(r'[._:;\\]',old)
        if len(parts)>1 and all(parts) and not any(c in old+value for c in '-=+~<>[](){}#'):
            matches=[]
            for part in parts:
                match=next((m for m in atom(part).finditer(value) if (m.start(2),m.end(2)) not in matches),None)
                if not match:break
                matches.append((match.start(2),match.end(2)))
            if len(matches)==len(parts):
                matches.sort()
                for a,z in reversed(matches):value=value[:a]+(new if (a,z)==matches[0] else '')+value[z:]
                return compact(value)
    # A manually selected meaning is authoritative even if its old label differed.
    return new


def raw_ranges(unit,mapping,raw,field='gloss_fragments'):
    ranges=[]
    for f in unit.get(field,[]):
        a,z=f['start'],f['end']
        if 0<=a<z<=len(mapping):ranges.append((mapping[a][0],mapping[z-1][1]))
        elif a==z and 0<=a<=len(mapping):
            at=mapping[a][0] if a<len(mapping) else len(raw)
            ranges.append((at,at))
    return list(dict.fromkeys(ranges))


def transform(word,rules):
    old=copy.deepcopy(word);new=copy.deepcopy(word);raw=word['gloss'];_,mapping=plain_map(raw)
    edits={};groups={};units={m['key']:m for m in word.get('morphemes',[])}
    units['@word']=dict(key='@word',gloss=raw)
    segments={s['key']:s for s in word.get('segments',[])}
    for key,(before,after) in rules.items():
        unit=units.get(key)
        if not unit:continue
        members=[segments[k] for k in unit['members']] if unit.get('group_id') else [unit]
        if unit.get('group_id'):groups[unit['group_id']]=replace_short(unit['gloss'],before,after)
        for member in members:
            spans=[(mapping[0][0],mapping[-1][1]) if mapping else (0,len(raw))] if key=='@word' else raw_ranges(member,mapping,raw)
            if not spans:continue
            value=''.join(raw[a:z] for a,z in spans)
            replacement=replace_short(value,before,after)
            # Discontinuous hosts keep their infix delimiters and unit identity.
            for index,span in enumerate(spans):
                text=replacement if index==0 else ''
                if span in edits and edits[span]!=text:raise ValueError('同一词格的关联义项产生不同释义更新，请先调整重复关联')
                edits[span]=text
    ordered=sorted(edits)
    if any(a[1]>b[0] for a,b in zip(ordered,ordered[1:])):
        raise ValueError('整词与语素的释义更新范围重叠，请先调整重复关联')
    for (a,z),text in sorted(edits.items(),reverse=True):raw=raw[:a]+text+raw[z:]
    new['gloss']=raw
    a={k:old[k] for k in ('form','gloss')};z={k:new[k] for k in ('form','gloss')}
    for g in new.get('morph_groups',[]):
        if g.get('snapshot')==a:
            g['snapshot']=z.copy()
            if g['id'] in groups:g['gloss']=groups[g['id']]
    if old.get('infix_confirmation')==a:new['infix_confirmation']=z.copy()
    corpus.analyze(dict(ipa='',translation='',words=[new]))
    structure=lambda w:[(m['key'],m['kind'],m['form']) for m in w.get('morphemes',[])]
    if structure(new)!=structure(old):
        raise ValueError('新简短释义会改变已关联词格的语素切分，请保留原有语素边界后重试')
    return new


def apply_record(db,kind,row,rules,transformer=transform,analyzed=None,cache=None,unit_state=None):
    old=analyzed if analyzed is not None else corpus.analyze(json.loads(row['body']))
    # Copy the stored data, rather than deep-copying all derived analyses for
    # unchanged words. The selected word transformer owns its own copies.
    body=json.loads(row['body']);original_words=body['words'][:];changed=[]
    for index,word_rules in rules.items():
        if not 0<=index<len(body['words']):continue
        new=cache.transform(old['words'][index],word_rules,transformer) if cache is not None else transformer(old['words'][index],word_rules)
        if new!=old['words'][index]:body['words'][index]=new;changed.append(index)
    if not changed:return
    corpus.reanalyze(body,old,set(changed),cache=cache.analysis if cache else None)
    if kind=='independent':
        from text_replace import preserve_independent_refs
        preserve_independent_refs(old,body,changed,set(),analyzed=True)
        body['words']=[word if i in changed else original_words[i] for i,word in enumerate(body['words'])]
        db.execute('UPDATE dictionary_examples SET body=?,revision=revision+1 WHERE id=?',(json.dumps(body,ensure_ascii=False),row['id']))
    else:
        import lexicon
        body['edited']=True
        body['words']=[word if i in changed else original_words[i] for i,word in enumerate(body['words'])]
        encoded=json.dumps(body,ensure_ascii=False)
        db.execute('UPDATE entries SET body=?,revision=revision+1 WHERE id=?',(encoded,row['id']))
        lexicon.sync_entry(db,row['id'],preserve_complex=True,analyzed_body=body,preserve_slots=True,word_positions=set(changed),stored_body=encoded,unit_state=unit_state)


def sync_progress(index,total,label):
    if index%64==0:long_tasks.checkpoint(index*100/max(1,total),f'正在核对并同步例句{label}：{index} / {total}')


def source_records(db,records,kind='corpus'):
    """Fetch sources and unit snapshots once per bounded batch, not per row."""
    import lexicon
    ids=list(records)
    for start in range(0,len(ids),64):
        batch=ids[start:start+64];marks=','.join('?' for _ in batch)
        if kind=='corpus':
            rows={r['id']:r for r in db.execute('SELECT e.*,t.language_id owner_language FROM entries e JOIN texts t ON t.id=e.text_id WHERE e.id IN ('+marks+')',batch)}
            positions={eid:{link['word_position'] for link in records[eid]} for eid in batch}
            states=lexicon.prepare_sync(db,batch,positions)
        else:
            rows={r['id']:r for r in db.execute('SELECT * FROM dictionary_examples WHERE id IN ('+marks+')',batch)};states={}
        for eid in long_tasks.steps(batch):
            if eid in rows:yield eid,rows[eid],states.get(eid)


def sync(db,changes):
    changed=changes_for(changes)
    if not changed:return
    records=defaultdict(list);independent=set();ids=list(changed)
    for start in range(0,len(ids),400):
        batch=ids[start:start+400];marks=','.join('?' for _ in batch)
        for r in db.execute('''SELECT l.lexeme_id,l.usage_id,l.sense_id,u.entry_id,u.kind,u.position,
            COALESCE(p.position,u.position) word_position,u.form,u.gloss,x.language_id
            FROM lexical_links l JOIN corpus_units u ON u.id=l.unit_id
            LEFT JOIN corpus_units p ON p.id=u.parent_id JOIN '''+dictionary_targets.IDENTITIES+''' x ON x.id=l.lexeme_id
            WHERE u.active=1 AND (p.id IS NULL OR p.active=1) AND l.lexeme_id IN ('''+marks+')',batch):
            if (r['usage_id'],r['sense_id']) in changed[r['lexeme_id']]:records[r['entry_id']].append(dict(r))
        independent.update(r[0] for r in db.execute("SELECT DISTINCT e.id FROM dictionary_examples e,json_each(e.body,'$.targets') t WHERE json_extract(t.value,'$.lexeme_id') IN ("+marks+')',batch))
    total=len(records)+len(independent);cache=SyncCache()
    for index,(eid,row,unit_state) in enumerate(source_records(db,records)):
        sync_progress(index,total,'标注')
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
            key='@word' if link['kind']=='word' else unit['key']
            rules[i][key]=changed[link['lexeme_id']][link['usage_id'],link['sense_id']]
        apply_record(db,'corpus',row,rules,analyzed=body,cache=cache,unit_state=unit_state)
    for index,(eid,row,_) in enumerate(source_records(db,independent,'independent'),len(records)):
        sync_progress(index,total,'标注')
        body=corpus.analyze(json.loads(row['body']),cache=cache.analysis);rules=defaultdict(dict)
        for target in body.get('targets',[]):
            delta=changed.get(target['lexeme_id'],{}).get((target.get('usage_id'),target.get('sense_id')))
            ref=target.get('segmentation_ref')
            if not delta or not ref or target.get('segmentation_review') or ref.get('detached'):continue
            if body['words'][ref['word']].get('unit_type')!='word':continue
            at=rules[ref['word']]
            if ref['key'] in at and at[ref['key']]!=delta:raise ValueError('同一词格的关联义项产生不同释义更新，请先调整重复关联')
            at[ref['key']]=delta
        apply_record(db,'independent',row,rules,analyzed=body,cache=cache)
