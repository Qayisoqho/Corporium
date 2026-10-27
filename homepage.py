"""Global welcome statistics and a bounded, deduplicated random sample."""
import json
import random

def overview(db):
    counts={name:db.execute('SELECT COUNT(*) FROM '+table).fetchone()[0] for name,table in [('texts','texts'),('corpus_sentences','entries'),('independent_sentences','dictionary_examples'),('lexemes','lexemes')]}
    counts['sentences']=counts['corpus_sentences']+counts['independent_sentences']
    languages={r['id']:{'name':r['name'],'metadata':json.loads(r['metadata'])} for r in db.execute('SELECT * FROM languages')}
    samples=[];seen=set();n=0
    def add(item):
        nonlocal n
        lang=languages.get(item['language_id'])
        if not lang:return
        primary=item.get('ipa') or item.get('original') or ''
        if not primary.strip() and not item.get('translation','').strip():return
        key=(item['language_id'],primary,item['translation'])
        if key in seen:return
        seen.add(key);n+=1
        item['language_name']=lang['name'];item['ipa_font']=lang['metadata'].get('ipa_font','IPAPANNEW');item['annotation_font']=lang['metadata'].get('annotation_font','Junicode')
        if len(samples)<24:samples.append(item)
        else:
            at=random.randrange(n)
            if at<24:samples[at]=item
    # Scan only the deduplication key. Expanding every word/annotation in Python
    # made returning home proportional to the size of all stored analyses.
    # The same ordered reservoir still gives each distinct sentence one chance.
    forms="(SELECT COALESCE(group_concat(COALESCE(json_extract(w.value,'$.form'),''),' '),'') FROM json_each(e.body,'$.words') w)"
    for r in db.execute("SELECT e.id,COALESCE(NULLIF(json_extract(e.body,'$.language_id'),''),t.language_id) language_id,COALESCE(NULLIF(json_extract(e.body,'$.ipa'),''),"+forms+") primary_text,COALESCE(json_extract(e.body,'$.translation'),'') translation FROM entries e JOIN texts t ON t.id=e.text_id ORDER BY t.id,e.position"):
        add(dict(kind='corpus',id=r['id'],language_id=r['language_id'],ipa=r['primary_text'],translation=r['translation']))
    for r in db.execute("SELECT e.id,e.language_id,COALESCE(NULLIF(json_extract(e.body,'$.ipa'),''),NULLIF(json_extract(e.body,'$.original'),''),"+forms+") primary_text,COALESCE(json_extract(e.body,'$.translation'),'') translation FROM dictionary_examples e ORDER BY e.id"):
        add(dict(kind='independent',id=r['id'],language_id=r['language_id'],ipa=r['primary_text'],translation=r['translation']))
    for item in samples:
        if item['kind']=='corpus':
            r=db.execute('SELECT e.position,e.text_id,e.body,t.title,t.language_id FROM entries e JOIN texts t ON t.id=e.text_id WHERE e.id=?',(item['id'],)).fetchone();b=json.loads(r['body'])
            item.update(text_id=r['text_id'],position=r['position'],owner_language=r['language_id'],source=r['title'],ipa=b.get('ipa',''),original=' '.join(w.get('form','') for w in b.get('words',[])))
        else:
            r=db.execute('SELECT * FROM dictionary_examples WHERE id=?',(item['id'],)).fetchone();b=json.loads(r['body']);targets=b.get('targets',[])
            item.update(lexeme_id=targets[0]['lexeme_id'] if targets else None,owner_language=r['language_id'],source=b.get('source','') or '独立例句',ipa=b.get('ipa',''),original=b.get('original','') or ' '.join(w.get('form','') for w in b.get('words',[])))
    random.shuffle(samples)
    return dict(counts=counts,samples=samples)
