"""Global welcome statistics and a bounded, deduplicated random sample."""
import json
import random
import read_views
import home_candidates
import sentence_rows

CANDIDATES=read_views.Cache(24*1024**2)

def overview(db):
    if not db.in_transaction:db.execute('BEGIN')
    counts={name:db.execute('SELECT COUNT(*) FROM '+table).fetchone()[0] for name,table in [('texts','texts'),('corpus_sentences','entries'),('independent_sentences','dictionary_examples'),('lexemes','lexemes')]}
    counts['sentences']=counts['corpus_sentences']+counts['independent_sentences']
    languages={r['id']:{'name':r['name'],'metadata':json.loads(r['metadata'])} for r in db.execute('SELECT * FROM languages')}
    stamp=read_views.token(db,'home')
    chosen=home_candidates.sample(db)
    candidates=CANDIDATES.get(stamp) if chosen is None else None
    if chosen is None and candidates is None:
        seen=set();candidates=[]
        for kind in ('corpus','independent'):
            for rid,lid,primary,translation,*_ in home_candidates.rows(db,kind):
                identity=(lid,primary,translation)
                if lid in languages and (primary.strip() or translation.strip()) and identity not in seen:
                    seen.add(identity);candidates.append((kind,rid,lid))
        CANDIDATES.put(stamp,candidates,512+sum(200+4*(len(rid)+len(lid)) for _,rid,lid in candidates))
    if chosen is None:chosen=random.sample(candidates,min(24,len(candidates)))
    samples=[]
    for kind,rid,lid in chosen:
        lang=languages[lid]
        samples.append(dict(kind=kind,id=rid,language_id=lid,language_name=lang['name'],
                            ipa_font=lang['metadata'].get('ipa_font','IPAPANNEW'),annotation_font=lang['metadata'].get('annotation_font','Junicode')))
    for item in samples:
        b=sentence_rows.one(db,item['kind'],item['id'])
        if item['kind']=='corpus':
            r=db.execute('SELECT e.position,e.text_id,t.title,t.language_id FROM entries e JOIN texts t ON t.id=e.text_id WHERE e.id=?',(item['id'],)).fetchone()
            item.update(text_id=r['text_id'],position=r['position'],owner_language=r['language_id'],source=r['title'],ipa=b.get('ipa',''),original=' '.join(w.get('form','') for w in b.get('words',[])))
        else:
            r=db.execute('''SELECT e.language_id,(SELECT lexeme_id FROM independent_links WHERE example_id=e.id ORDER BY position LIMIT 1) lexeme_id
                FROM dictionary_examples e WHERE e.id=?''',(item['id'],)).fetchone()
            item.update(lexeme_id=r['lexeme_id'],owner_language=r['language_id'],source=b.get('source','') or '独立例句',source_default=not bool(b.get('source')),ipa=b.get('ipa',''),original=b.get('original','') or ' '.join(w.get('form','') for w in b.get('words',[])))
        item['translation']=b.get('translation','')
    return dict(counts=counts,samples=samples)
