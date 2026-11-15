"""Infer sentence-local reduplication only while committing sentence edits.

The gloss inventory supplies roles; spelling similarity never supplies direction.
Use the existing relation/endpoint format, including discontinuous grouped bases.
Reading, importing and replaying history must not call this module.
"""
import copy
import re

import corpus
import grammar
import grammar_reference
import reduplication
import segmentation


def gloss_role(value, language, lookup):
    """Return grammatical, lexical or unknown, retaining mixed lexical glosses."""
    scripts=[]
    marker='\ue000'
    while marker in value:marker+='\ue000'
    def hide(match):
        scripts.append(match[0]);return marker+str(len(scripts)-1)+marker
    raw=corpus.plain(re.sub(r'#(?:sub|sup|super)\[[^\[\]]*\]',hide,value))
    try:groups,_=segmentation.angles(raw,True)
    except ValueError:return 'unknown'
    chunks=[];cursor=0
    for start,end,content in groups:
        chunks.extend(((raw[cursor:start],False),(content,True)));cursor=end
    chunks.append((raw[cursor:],False))
    grammatical=lexical=False
    for text,forced in chunks:
        for part,bracketed in corpus.gloss_chunks(text):
            for atom in re.split(r'[\s.\-=:+~/;\\,!?，。；：！？(){}<>]+',part):
                atom=atom.strip('«»“”"')
                atom=re.sub(re.escape(marker)+r'(\d+)'+re.escape(marker),lambda m:scripts[int(m[1])],atom)
                if not atom:continue
                explicit=forced or bracketed
                if grammar.recognized(atom,language,lookup,explicit):
                    grammatical=True;continue
                person=re.fullmatch(r'[123]([A-Za-z]+)',atom)
                if person and grammar.recognized(person[1],language,lookup,explicit):
                    grammatical=True;continue
                # Undeclared labels are not evidence of a lexical base. Keep the
                # inventory's English homograph rules (all/art/pass) intact.
                if explicit or '#' in atom or grammar_reference.candidate(atom) or atom.isupper() or atom.isdecimal():
                    return 'unknown'
                lexical=True
    return 'lexical' if lexical else 'grammatical' if grammatical else 'unknown'


def candidates(word, language, lookup):
    """Each unambiguous two-node tilde component supplies one directed relation."""
    if (word.get('unit_type')!='word' or word.get('_legacy_tilde') or
            word.get('group_reviews') or word.get('infix_ambiguous') or not word.get('morphemes')):
        return []
    if any(not word.get(k,'').strip() for k in ('form','gloss')):return []
    for key in ('form','gloss'):
        value=re.sub(r'#(?:sub|sup|super)\[[^\[\]]*\]','',word[key])
        if '#' in value:return []
        depth=0
        for char in corpus.plain(value):
            if char=='[':depth+=1
            elif char==']':depth-=1
            if depth<0:return []
        if depth:return []
    # Reparse both rows: blank pieces and boundary mismatches invalidate the
    # whole cell, even if another tilde pair within it looks usable.
    form,gloss=(corpus.clean(word[k]) for k in ('form','gloss'))
    try:parts,ambiguous=segmentation.parse_word(form,gloss)
    except ValueError:return []
    if ambiguous or any(not u['form'].strip() or not u['gloss'].strip() for u in parts):return []
    units={u['key']:u for u in word['morphemes']}
    owners={key:key for key in units}
    for key,u in units.items():
        for member in u.get('members',[]):owners[member]=key
    edges={}
    split=segmentation.split_parts(form)
    for n,part in enumerate(split[:-1]):
        if part[2]!='~':continue
        left,right=(owners.get(f'r:{i}:host') for i in (n,n+1))
        if left is None or right is None or left==right:continue
        edges.setdefault(left,set()).add(right);edges.setdefault(right,set()).add(left)
    result=[];seen=set()
    for start in edges:
        if start in seen:continue
        component=set();pending=[start]
        while pending:
            key=pending.pop()
            if key in component:continue
            component.add(key);pending.extend(edges[key]-component)
        seen.update(component)
        if len(component)!=2:continue
        roles={key:gloss_role(units[key].get('display_gloss',units[key]['gloss']),language,lookup) for key in component}
        source=[key for key in component if roles[key]=='grammatical']
        base=[key for key in component if roles[key]=='lexical']
        if len(source)==len(base)==1:result.append((source[0],base[0]))
    return result


def protected_positions(body, previous):
    """Protect old endpoints even after an edit makes their snapshots stale."""
    words=body['words'];before=previous.get('words',[]);blocked=set()
    for relation in body.get('reduplications',[])+previous.get('reduplications',[]):
        for name in ('source','base'):
            ref=relation[name]
            positions=[i for i,w in enumerate(words) if w.get('redup_id')==ref['word_id']]
            if not positions:positions=[i for i,w in enumerate(words) if w['form']==ref['snapshot']]
            if not positions:
                old=[i for i,w in enumerate(before) if w.get('redup_id')==ref['word_id']]
                positions=old if len(before)==len(words) else []
            if not positions:
                # Without an unambiguous edited-slot mapping, leave the sentence
                # alone instead of adding a replacement for an orphaned relation.
                return set(range(len(words)))
            blocked.update(positions)
    return blocked


def coded_positions(db, kind, record_id, body, previous, word_ids):
    marked={r[0] for r in db.execute('''SELECT DISTINCT j.value FROM code_spans s,json_each(s.word_ids) j
        WHERE s.owner_kind=? AND s.record_id=?''',(kind,record_id))}
    if not marked:return set()
    if word_ids is not None:return {i for i,uid in enumerate(word_ids) if uid in marked}
    if kind=='independent':return {i for i,w in enumerate(body['words']) if w.get('annotation_id') in marked}
    old=list(db.execute("SELECT id,position,form FROM corpus_units WHERE entry_id=? AND kind='word' AND active=1",(record_id,)))
    blocked=set()
    for row in old:
        if row['id'] not in marked:continue
        positions=[i for i,w in enumerate(body['words']) if w['form']==row['form']]
        if not positions and len(previous.get('words',[]))==len(body['words']):positions=[row['position']]
        if not positions:return set(range(len(body['words'])))
        blocked.update(positions)
    return blocked


def on_save(db, kind, record_id, body, language, *, previous=None, lookup=None, word_ids=None):
    """Add only new certain relations; return their count without touching text.

    All pre-existing relations (including unresolved ones) are protected. A cell
    with code-switch annotations is left to manual analysis until its per-segment
    language can be resolved against the edited stable identities.
    """
    if not any('~' in w.get('form','') for w in body.get('words',[])):return 0
    analyzed=corpus.analyze(copy.deepcopy(body))
    previous=previous or {}
    blocked=protected_positions(body,previous)
    # No read of an all-sentence JSON view. These IDs are a narrow, optional
    # annotation scope; conservatively skip marked cells after ambiguous edits.
    blocked.update(coded_positions(db,kind,record_id,body,previous,word_ids))
    language=body.get('language_id') or language
    if lookup is None:lookup=grammar.index(grammar.listing(db,language))
    added=0
    for position,word in enumerate(analyzed['words']):
        if position in blocked:continue
        for source,base in candidates(word,language,lookup):
            before=copy.deepcopy(analyzed.get('reduplications',[]));identity=word.get('redup_id')
            try:
                reduplication.apply(analyzed,dict(source=dict(word=position,key=source),
                    base=dict(word=position,key=base),type='unspecified'))
            except ValueError:
                analyzed['reduplications']=before
                if identity:word['redup_id']=identity
                else:word.pop('redup_id',None)
                continue
            added+=1
    if added:
        body['reduplications']=analyzed['reduplications']
        for word,fresh in zip(body['words'],analyzed['words']):
            if fresh.get('redup_id'):word['redup_id']=fresh['redup_id']
        reduplication.decorate(body,body.setdefault('warnings',[]))
    return added
