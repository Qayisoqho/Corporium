"""Read-only paired display ranges from actual segmentation and dictionary links."""
import re
from collections import defaultdict

STRIP=' \t\r\n«»“”".,;:!?…。，；：！？'
COLORED_TYPES={'affix','clitic','infix','circumfix','connector','multipart'}


def plain_map(raw):
    """Mirror corpus.plain/clean while retaining source code-point positions."""
    text=[];positions=[];at=0
    for match in re.finditer(r'#sub\[([^\[\]]*)\]',raw):
        text.extend(raw[at:match.start()]);positions.extend((i,i+1) for i in range(at,match.start()))
        text.extend(match[1]);positions.extend([(match.start(),match.end())]*len(match[1]));at=match.end()
    text.extend(raw[at:]);positions.extend((i,i+1) for i in range(at,len(raw)))
    value=''.join(text);out=[];mapping=[];at=0
    for match in re.finditer(r'\\([\\"\[\]#~?])',value):
        out.extend(value[at:match.start()]);mapping.extend(positions[at:match.start()])
        out.append(match[1]);mapping.append((positions[match.start()][0],positions[match.end()-1][1]));at=match.end()
    out.extend(value[at:]);mapping.extend(positions[at:]);text=''.join(out)
    left=len(text)-len(text.lstrip(STRIP));right=len(text.rstrip(STRIP))
    return text[left:right],mapping[left:right]


def ranges(fragments,mapping):
    return [[mapping[f['start']][0],mapping[f['end']-1][1]] for f in fragments if 0<=f['start']<f['end']<=len(mapping)]


def tone(_unit,link):
    """Only a saved dictionary type supplies color; segmentation supplies ranges."""
    if not link:return 'base'
    entry_type=link['entry_type']
    if entry_type=='affix' and 'affix_position' in link.keys() and link['affix_position'] in ('infix','circumfix'):return link['affix_position']
    return entry_type if entry_type in COLORED_TYPES else 'base'


def prepare(db,ids):
    """Operation-local display data for at most one batch of sentence cards."""
    rows=defaultdict(list);catalog={};targets=set()
    if not ids:return dict(rows=rows,catalog=catalog)
    sql='''SELECT u.entry_id,COALESCE(p.position,u.position) word_position,u.position morph_position,u.kind,l.lexeme_id
        FROM corpus_units u LEFT JOIN corpus_units p ON p.id=u.parent_id JOIN lexical_links l ON l.unit_id=u.id
        WHERE u.entry_id IN ('''+','.join('?' for _ in ids)+''') AND u.active=1 AND (p.id IS NULL OR p.active=1)
        ORDER BY CASE WHEN u.kind='morpheme' THEN 1 ELSE 0 END,u.id'''
    for row in db.execute(sql,ids):rows[row['entry_id']].append(row);targets.add(row['lexeme_id'])
    targets=list(targets)
    for start in range(0,len(targets),400):
        batch=targets[start:start+400];marks=','.join('?' for _ in batch)
        # The display view changes usages/orthographies, not these source fields.
        for table in ('lexemes','morphemes'):
            for row in db.execute("SELECT id,language_id,COALESCE(json_extract(body,'$.entry_type'),'unspecified') entry_type,json_extract(body,'$.affix_position') affix_position FROM "+table+' WHERE id IN ('+marks+')',batch):
                catalog[row['language_id'],row['id']]=row
    return dict(rows=rows,catalog=catalog)


def attach(db,body,kind,rid,lid,prepared=None):
    words=body.get('words',[]);links={};whole=set()
    if kind=='corpus':
        sql="""SELECT COALESCE(p.position,u.position) word_position,u.position morph_position,u.kind,l.lexeme_id
        FROM corpus_units u LEFT JOIN corpus_units p ON p.id=u.parent_id
        JOIN lexical_links l ON l.unit_id=u.id
        WHERE u.entry_id=? AND u.active=1 AND (p.id IS NULL OR p.active=1)
        ORDER BY CASE WHEN u.kind='morpheme' THEN 1 ELSE 0 END,u.id"""
        rows=prepared['rows'].get(rid,[]) if prepared is not None else list(db.execute(sql,(rid,)))
        ids=[] if prepared is not None else list({r['lexeme_id'] for r in rows});catalog={}
        # Fetch only types referenced by this card. Joining the union view above
        # materialized every native morpheme body once per visible sentence.
        for start in range(0,len(ids),400):
            batch=ids[start:start+400]
            catalog.update((r['id'],r) for r in db.execute("SELECT id,COALESCE(json_extract(body,'$.entry_type'),'unspecified') entry_type,json_extract(body,'$.affix_position') affix_position FROM dictionary_targets WHERE language_id=? AND id IN ("+','.join('?' for _ in batch)+')',(lid,*batch)))
        for row in rows:
            target=prepared['catalog'].get((lid,row['lexeme_id'])) if prepared is not None else catalog.get(row['lexeme_id'])
            if target is None:continue
            r={**dict(row),'entry_type':target['entry_type'],'affix_position':target['affix_position']}
            index=r['word_position']
            if not 0<=index<len(words):continue
            if r['kind']=='word':whole.add(index)
            units=words[index].get('morphemes',[])
            pos=r['morph_position'] if r['kind']=='morpheme' else 0 if len(units)==1 else -1
            if 0<=pos<len(units):links[index,units[pos]['key']]=r
    else:
        targets=[t for t in body.get('targets',[]) if t.get('segmentation_ref') and not t.get('segmentation_review') and not t['segmentation_ref'].get('detached')]
        ids=list({t['lexeme_id'] for t in targets});catalog={}
        for start in range(0,len(ids),400):
            batch=ids[start:start+400]
            catalog.update((r['id'],r) for r in db.execute("SELECT id,COALESCE(json_extract(body,'$.entry_type'),'unspecified') entry_type,json_extract(body,'$.affix_position') affix_position FROM dictionary_targets WHERE language_id=? AND id IN ("+','.join('?' for _ in batch)+')',(lid,*batch)))
        for t in targets:
            ref=t['segmentation_ref'];index=ref['word'];link=catalog.get(t['lexeme_id'])
            if not link or not 0<=index<len(words):continue
            units=words[index].get('morphemes',[]);key=ref['key']
            if key=='@word':whole.add(index)
            if key=='@word' and len(units)==1:key=units[0]['key']
            links[index,key]=link
    for index,w in enumerate(words):
        w['morph_colors']=[]
        w['dictionary_linked']=index in whole
        if w.get('infix_ambiguous'):continue
        _,fm=plain_map(w['form']);_,gm=plain_map(w['gloss'])
        for unit in w.get('morphemes',[]):
            link=links.get((index,unit['key']))
            w['morph_colors'].append(dict(key=unit['key'],tone=tone(unit,link),linked=link is not None,form=ranges(unit.get('fragments',[]),fm),gloss=ranges(unit.get('gloss_fragments',[]),gm)))
        w['dictionary_linked']=w['dictionary_linked'] or bool(w['morph_colors']) and all(c['linked'] for c in w['morph_colors'])
    attach_reduplication(body)


def attach_reduplication(body):
    """Read-only source overlays, independent of dictionary-link classification.

    A tilde is only a candidate. Stale relations supply no display ranges, and
    gloss ranges require an unambiguous current alignment, never the tag name.
    """
    import reduplication
    words=body.get('words',[])
    for w in words:w.pop('redup_colors',None)
    if not body.get('reduplications'):return
    info=body.get('reduplication_info') or reduplication.describe(body)
    for relation in info['relations']:
        if relation['review']:continue
        w=words[relation['source_word']];ref=relation['source']
        _,fm=plain_map(w['form']);gloss,gm=plain_map(w['gloss'])
        fragments=ref['fragments'];gloss_fragments=[]
        if ref['key']=='@word':gloss_fragments=[dict(start=0,end=len(gloss),text=gloss)] if gloss else []
        elif not w.get('infix_ambiguous'):
            unit=next((u for u in [*w.get('morphemes',[]),*w.get('segments',[])] if u['key']==ref['key']),None)
            if unit:gloss_fragments=unit.get('gloss_fragments',[])
        w.setdefault('redup_colors',[]).append(dict(key=ref['key'],tone='reduplication',
            form=ranges(fragments,fm),gloss=ranges(gloss_fragments,gm),
            fragments=fragments,gloss_fragments=gloss_fragments))
