"""Atomic same-language word transfers, preserving per-word analyses and links."""
import copy
import json
import uuid
import annotations
import lexicon
import segmentation
import gloss_inheritance
from corpus import analyze


def uid(): return str(uuid.uuid4())
def dump(x): return json.dumps(x,ensure_ascii=False)


def snapshot(db,kind,rid):
    d=annotations.get(db,kind,rid)
    analyze(d['body'])
    # Include links/cells/configuration in the optimistic token, not only sentence revision.
    import hashlib
    import code_switching
    d['code_spans']=code_switching.rows(db,kind,rid)
    links=[]
    if kind=='corpus':
        links=[dict(r) for r in db.execute('SELECT l.*,a.form_id,a.features FROM lexical_links l JOIN corpus_units u ON u.id=l.unit_id LEFT JOIN morphology_analyses a ON a.id=l.id WHERE u.entry_id=? ORDER BY l.id',(rid,))]
    for link in links:
        link['component_ref']=lexicon.morphology.component_links.read(db,link['id'])
        link['review_reason']=lexicon.link_review.reason(db,link['id'])
    if kind=='corpus':
        row=db.execute('SELECT text_id,position FROM entries WHERE id=?',(rid,)).fetchone();d['adjacent']={};d['text_id']=row['text_id']
        for key,op,order in [('previous','<','DESC'),('next','>','ASC')]:
            r=db.execute('SELECT id FROM entries WHERE text_id=? AND position '+op+' ? ORDER BY position '+order+' LIMIT 1',(row['text_id'],row['position'])).fetchone()
            if r:d['adjacent'][key]=r[0]
    d['transfer_token']=hashlib.sha256(dump([d,links]).encode()).hexdigest()
    return d


def word_links(db,d,index):
    w=d['body']['words'][index];wid=d['words'][index]['id'];out=[]
    if d['kind']=='independent':
        for t in d['body'].get('targets',[]):
            ref=t.get('segmentation_ref')
            if ref and ref.get('word')==index:
                if ref.get('detached') or t.get('segmentation_review'):raise ValueError('所选词格含待核对的词典关联，请先处理后再转移')
                item=copy.deepcopy(t);item['_gloss_copy_source']=t.get('gloss_binding_id');out.append(item)
        return out
    for row in db.execute('SELECT l.*,u.kind,s.body segment,a.form_id,a.features FROM lexical_links l JOIN corpus_units u ON u.id=l.unit_id LEFT JOIN unit_segments s ON s.id=u.id LEFT JOIN morphology_analyses a ON a.id=l.id WHERE u.active=1 AND (u.id=? OR u.parent_id=?)',(wid,wid)):
        t={k:row[k] for k in ('lexeme_id','usage_id','sense_id','notes','form_id')};t['features']=json.loads(row['features'] or '[]')
        t['component_ref']=lexicon.morphology.component_links.read(db,row['id'])
        t['review_reason']=lexicon.link_review.reason(db,row['id'])
        unit=json.loads(row['segment']) if row['segment'] else dict(key='@word',form=w['form'],gloss=w['gloss'],fragments=[])
        if row['segment']:unit=next((m for m in w.get('morphemes',[]) if m['key']==unit['key']),unit)
        t['_gloss_copy_source']=row['id']
        t['segmentation_ref']=segmentation.reference(w,index,unit);out.append(t)
    return out


def apply(db,b,lid):
    source=b['source'];target=b['target'];mode=b.get('mode')
    if mode not in ('copy','move'):raise ValueError('请选择复制或移动')
    if (source['kind'],source['id'])==(target['kind'],target.get('id')):raise ValueError('请选择另一个句子')
    s=snapshot(db,source['kind'],source['id'])
    if s['transfer_token']!=source.get('token'):raise ValueError('来源句子或关联已变化，请重新打开')
    if mode=='move' and not target.get('new'):
        t=snapshot(db,target['kind'],target['id'])
        if s['kind']!=t['kind'] or (s['kind']=='corpus' and s['text_id']!=t['text_id']):
            raise ValueError('词格移动仅限同一文本内；独立例句仅可在独立例句库内移动')
    if target.get('new'):
        if target['kind'] not in ('corpus','independent'):raise ValueError('新句来源无效')
        if target['kind']=='independent' and s['language_id']!=lid:raise ValueError('来源句子单独指定了其他语言，不能复制到当前语言的独立例句库；请选择相同句子语言的文本目标')
        tid=target.get('text_id') or s.get('text_id')
        if mode=='move' and (target['kind']!=s['kind'] or (s['kind']=='corpus' and tid!=s['text_id'])):raise ValueError('词格移动仅限同一文本内；独立例句仅可在独立例句库内移动')
        rid=uid();empty=dict(ipa='',translation='',notes='',words=[])
        if s['language_id']!=lid:empty['language_id']=s['language_id']
        if target['kind']=='corpus':
            empty.update(function='pass',raw='',line=None,edited=True)
            if not db.execute('SELECT 1 FROM texts WHERE id=? AND language_id=?',(tid,lid)).fetchone():raise ValueError('目标文本不存在或语言不一致')
            position=db.execute('SELECT position FROM entries WHERE id=?',(s['id'],)).fetchone()[0] if s['kind']=='corpus' and tid==s['text_id'] else db.execute('SELECT COALESCE(MAX(position),0) FROM entries WHERE text_id=?',(tid,)).fetchone()[0]
            db.execute('UPDATE entries SET position=position+1 WHERE text_id=? AND position>?',(tid,position))
            db.execute('INSERT INTO entries(id,text_id,position,body) VALUES(?,?,?,?)',(rid,tid,position+1,dump(analyze(empty))))
        else:
            empty.update(original='',targets=[],source='')
            db.execute('INSERT INTO dictionary_examples VALUES(?,?,?,1)',(rid,lid,dump(analyze(empty))))
        target={**target,'id':rid};t=snapshot(db,target['kind'],rid);target['token']=t['transfer_token']
    else:t=snapshot(db,target['kind'],target['id'])
    if s['owner_language']!=lid or t['owner_language']!=lid or s['language_id']!=t['language_id']:raise ValueError('词格转移仅支持同一语言的句子')
    if any(d['transfer_token']!=v.get('token') for d,v in ((s,source),(t,target))):raise ValueError('句子、标注或关联已变化，请重新打开转移窗口')
    selected=b.get('slots',[]);ids=[w['id'] for w in s['words']]
    if not isinstance(selected,list) or not selected or len(set(selected))!=len(selected) or any(x not in ids for x in selected):raise ValueError('请选择有效词格')
    indices=[i for i,x in enumerate(ids) if x in selected]
    position=b.get('position',len(t['words']))
    if type(position)!=int or not 0<=position<=len(t['words']):raise ValueError('插入位置已变化')
    if b.get('confirmed') is not True:raise ValueError('请确认检查两句的整句 IPA、翻译和时间对齐')
    if any(c['unit_id'] in selected for c in s['orphaned']):raise ValueError('所选词格有失效附加标注，请先核对')
    words=copy.deepcopy([s['body']['words'][i] for i in indices]);links=[word_links(db,s,i) for i in indices]
    # Morphological groups are word-local. Reject unresolved structures instead of silently dropping them.
    if any(w.get('group_reviews') for w in words):raise ValueError('所选词格含待核对的语素组合，请先处理')
    newids=[uid() for _ in words];mapping=dict(zip([ids[i] for i in indices],newids))
    for w,wid in zip(words,newids):w['annotation_id']=wid
    tb=copy.deepcopy(t['body'])
    import reduplication
    reduplication.transfer(s['body'],words,tb)
    tb['words'][position:position]=words
    for x in tb.get('targets',[]):
        ref=x.get('segmentation_ref')
        if ref and not ref.get('detached') and ref['word']>=position:ref['word']+=len(words)
    copies=[]
    if t['kind']=='independent':
        for offset,items in enumerate(links):
            for x in items:
                x['segmentation_ref']['word']=position+offset
                previous=x.pop('_gloss_copy_source',None)
                x.pop('gloss_binding_id',None)
                if previous:
                    x['gloss_binding_id']=uid();copies.append((previous,x['gloss_binding_id'],newids[offset],x['segmentation_ref']['key']))
                tb.setdefault('targets',[]).append(x)
    targetids=[w['id'] for w in t['words']];targetids[position:position]=newids
    write(db,t,tb,targetids)
    for old_id,new_id,word_id,key in copies:gloss_inheritance.copy_binding(db,old_id,new_id,t['kind'],t['id'],word_id,key)
    if t['kind']=='corpus':
        for offset,items in enumerate(links):
            wid=newids[offset]
            segments={json.loads(r['body'])['key']:r['id'] for r in db.execute('SELECT s.* FROM unit_segments s JOIN corpus_units u ON u.id=s.id WHERE u.parent_id=? AND u.active=1',(wid,))}
            for x in items:
                key=x['segmentation_ref']['key'];unit=wid if key=='@word' else segments.get(key)
                if not unit:raise ValueError('目标句子无法保留语素关联，请先核对分析')
                linkid=uid()
                db.execute('INSERT INTO lexical_links(id,unit_id,lexeme_id,usage_id,sense_id,notes,language_id,revision) VALUES(?,?,?,?,?,?,?,1)',(linkid,unit,x['lexeme_id'],x.get('usage_id'),x.get('sense_id'),x.get('notes',''),t['language_id']))
                if x.get('_gloss_copy_source'):gloss_inheritance.copy_binding(db,x['_gloss_copy_source'],linkid,'corpus',t['id'],wid,key)
                if x.get('review_reason'):db.execute('INSERT INTO lexical_reviews VALUES(?,?)',(linkid,x['review_reason']))
                if x.get('component_ref'):db.execute('INSERT INTO component_links VALUES(?,?)',(linkid,dump(x['component_ref'])))
                db.execute('INSERT INTO morphology_analyses VALUES(?,?,?)',(linkid,x.get('form_id'),dump(x.get('features',[]))))
    for c in s['cells']:
        if c['unit_id'] in mapping:db.execute('INSERT INTO annotation_cells VALUES(?,?,?,?,?,?,1)',(uid(),t['kind'],t['id'],mapping[c['unit_id']],c['layer_id'],c['value']))
    if mode=='move':
        sb=copy.deepcopy(s['body']);sb['words']=[w for i,w in enumerate(sb['words']) if i not in indices]
        moved={s['body']['words'][i].get('redup_id') for i in indices}
        if sb.get('reduplications'):
            sb['reduplications']=[r for r in sb['reduplications'] if not all(r[k]['word_id'] in moved for k in ('source','base'))]
            reduplication.prune_ids(sb)
        positions={old:new for new,old in enumerate(i for i in range(len(ids)) if i not in indices)}
        keep=[]
        for x in sb.get('targets',[]):
            ref=x.get('segmentation_ref')
            if ref and not ref.get('detached'):
                if ref['word'] in indices:continue
                ref['word']=positions[ref['word']]
            keep.append(x)
        if 'targets' in sb:sb['targets']=keep
        if s['kind']=='corpus':
            for wid in selected:
                ls=[r[0] for r in db.execute('SELECT l.id FROM lexical_links l JOIN corpus_units u ON u.id=l.unit_id WHERE u.active=1 AND (u.id=? OR u.parent_id=?)',(wid,wid))]
                for linkid in ls:
                    db.execute('DELETE FROM component_links WHERE id=?',(linkid,));db.execute('DELETE FROM morphology_analyses WHERE id=?',(linkid,));db.execute('DELETE FROM lexical_links WHERE id=?',(linkid,))
        for wid in selected:db.execute('DELETE FROM annotation_cells WHERE owner_kind=? AND record_id=? AND unit_id=?',(s['kind'],s['id'],wid))
        write(db,s,sb,[x for x in ids if x not in selected])
    import code_switching
    code_switching.copy_spans(db,s['kind'],s['id'],t['kind'],t['id'],mapping,move=mode=='move')
    return dict(ok=True,count=len(words),target=dict(kind=t['kind'],id=t['id']))


def write(db,d,body,ids):
    analyze(body)
    table='entries' if d['kind']=='corpus' else 'dictionary_examples'
    if d['kind']=='corpus':body['edited']=True
    db.execute('UPDATE '+table+' SET body=?,revision=revision+1 WHERE id=?',(dump(body),d['id']))
    if d['kind']=='corpus':lexicon.sync_entry(db,d['id'],ids)
