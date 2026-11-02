"""Read-only token/record counts, with explicit scope and identity deduplication."""
import long_tasks
import json
import unicodedata
import corpus
from collections import OrderedDict


def is_word(word):
    value=corpus.plain(word.get('form','')).strip()
    if not value or corpus.boundary_count(value):return False
    if word.get('punctuation') and word.get('punctuation_form')==word.get('form'):return False
    return any(not c.isspace() and c!='#' and not unicodedata.category(c).startswith('P') for c in value)


class WordCounter:
    """Operation-local reuse of the three source fields used by is_word."""
    def __init__(self):self.values=OrderedDict();self.bytes=0
    def __call__(self,word):
        key=(word.get('form',''),bool(word.get('punctuation')),word.get('punctuation_form'))
        if key in self.values:
            self.values.move_to_end(key);return self.values[key][0]
        value=is_word(word);cost=256+4*(len(key[0])+len(key[2] or ''))
        if cost<=4*1024**2:
            while self.values and (self.bytes+cost>4*1024**2 or len(self.values)>=4096):
                _,(_,old)=self.values.popitem(last=False);self.bytes-=old
            self.values[key]=(value,cost);self.bytes+=cost
        return value


def normalize(scope):
    if not isinstance(scope,dict):raise ValueError('统计范围无效')
    mode=scope.get('mode','language');ids=scope.get('text_ids',[])
    if mode not in ('language','texts','dictionary','independent'):raise ValueError('统计范围无效')
    if not isinstance(ids,list) or len(ids)>20000 or any(not isinstance(i,str) or not i or len(i)>200 for i in ids):raise ValueError('文本选择无效')
    include=scope.get('include_dictionary',False)
    if not isinstance(include,bool):raise ValueError('词典范围选项无效')
    independent=scope.get('include_independent',mode in ('language','independent'))
    if not isinstance(independent,bool):raise ValueError('独立例句范围选项无效')
    if mode=='texts' and not ids:raise ValueError('请至少选择一个文本')
    return dict(mode=mode,text_ids=sorted(set(ids)) if mode=='texts' else [],include_dictionary=include if mode=='texts' else mode in ('language','dictionary'),include_independent=independent if mode=='texts' else mode in ('language','independent'))


def calculate(db,lid,scope,*,case=True,selection=None,separate_clitics=False):
    import grammaticality
    from vocabulary_statistics import Collector
    vocabulary=Collector(db,case,selection)
    catalogs={r['id']:grammaticality.definitions(r['metadata']) for r in db.execute('SELECT id,metadata FROM languages')};judgments={}
    def judgment(body,language,count):
        item=grammaticality.selected(body.get('grammaticality',''),catalogs[body.get('language_id') or language]);key=(body.get('language_id') or language,item['id'])
        row=judgments.setdefault(key,dict(language_id=key[0],id=item['id'],name=item['name'],symbol=item['symbol'],sentences=0,words=0));row['sentences']+=1;row['words']+=count
    word_counter=WordCounter()
    import mpw_statistics
    mpw=mpw_statistics.Counter(word_counter,separate_clitics);mpw_rows={}
    def record_mpw(key,words):
        values=mpw.record(words);total=mpw_rows.setdefault(key,[0,0,0])
        for i,field in enumerate(('morphemes','word_slots','clitic_words')):total[i]+=values[field]
    texts={r['id']:dict(r) for r in db.execute("SELECT id,title FROM texts WHERE ?='all' OR language_id=?",(lid,lid))}
    mode=scope['mode'];chosen=set(scope['text_ids']) if mode=='texts' else set(texts) if mode=='language' else set()
    if not chosen<=texts.keys():raise ValueError('所选文本已删除或不属于当前语言，请重新选择')
    include=scope['include_dictionary'];referenced=set();lexemes=0
    if include:
        lexemes=db.execute("SELECT COUNT(*) FROM lexemes WHERE ?='all' OR language_id=?",(lid,lid)).fetchone()[0]
        # Active references only. One sentence may be cited by many units/entries.
        # Establish each referenced sentence/language once before reading its
        # JSON. Dense references otherwise parse that same sentence per link.
        # Keep references before units: the automatic plan can otherwise scan
        # every unlinked unit instead of using links_lexeme and unit identities.
        for r in long_tasks.steps(db.execute("""SELECT DISTINCT e.id FROM (
            SELECT u.entry_id,x.language_id FROM lexemes x
            CROSS JOIN lexical_links l ON l.lexeme_id=x.id
            CROSS JOIN corpus_units u ON u.id=l.unit_id
            WHERE u.active=1 AND (?='all' OR x.language_id=?)
            GROUP BY u.entry_id,x.language_id
            ) refs JOIN entries e ON e.id=refs.entry_id JOIN texts t ON t.id=e.text_id
            WHERE COALESCE(NULLIF(json_extract(e.body,'$.language_id'),''),t.language_id)=refs.language_id""",(lid,lid))):
            referenced.add(r['id'])
    rows={tid:dict(id=tid,title=texts[tid]['title'],kind='text',sentences=0,words=0,excluded=0) for tid in texts if tid in chosen}
    corpus_sentences=corpus_words=excluded=overlap=0
    def corpus_rows():
        cursor=db.execute('SELECT e.id,e.text_id,e.body,t.title,t.language_id FROM entries e JOIN texts t ON t.id=e.text_id ORDER BY t.rowid,e.position')
        while batch:=cursor.fetchmany(400):
            selected=[r for r in batch if r['text_id'] in chosen or r['id'] in referenced]
            vocabulary.load_batch([r['id'] for r in selected]);yield from selected
    for r in long_tasks.steps(corpus_rows()):
        body=json.loads(r['body']);words=body.get('words',[])
        count=vocabulary.record(r['id'],body,body.get('language_id') or r['language_id'],r['text_id'],word_counter)
        record_mpw(r['text_id'],words)
        row=rows.setdefault(r['text_id'],dict(id=r['text_id'],title=r['title'],kind='dictionary_reference',sentences=0,words=0,excluded=0))
        row['sentences']+=1;row['words']+=count;row['excluded']+=len(words)-count
        corpus_sentences+=1;corpus_words+=count;excluded+=len(words)-count
        overlap+=r['text_id'] in chosen and r['id'] in referenced
    all_independent=scope.get('include_independent',mode in ('language','independent'))
    independent=dict(id='independent',title='独立例句库',kind='independent',sentences=0,words=0,excluded=0)
    if include or all_independent:
        for r in long_tasks.steps(db.execute("SELECT id,body,language_id FROM dictionary_examples WHERE ?='all' OR language_id=? ORDER BY rowid",(lid,lid))):
            body=json.loads(r['body'])
            if not all_independent and not body.get('targets'):continue
            words=body.get('words',[]);count=vocabulary.record('independent:'+r['id'],body,body.get('language_id') or r['language_id'],None,word_counter)
            record_mpw('@independent',words)
            judgment(body,r['language_id'],count)
            independent['sentences']+=1;independent['words']+=count;independent['excluded']+=len(words)-count
    result=dict(words=corpus_words+independent['words'],sentences=corpus_sentences+independent['sentences'],texts=len(rows),lexemes=lexemes,
                excluded=excluded+independent['excluded'],dictionary_included=include,dictionary_corpus_sentences=len(referenced),overlap_sentences=overlap,
                corpus_sentences=corpus_sentences,independent_sentences=independent['sentences'],rows=list(rows.values())+([independent] if include or all_independent else []),grammaticality=list(judgments.values()))
    result['_vocabulary']=vocabulary.finish(result);result['_hits']=vocabulary.hits
    result['mpw']=mpw.finish()
    for row in result['rows']:
        row['mpw']=mpw_statistics.result(*mpw_rows.get('@independent' if row['kind']=='independent' else row['id'],(0,0,0)),separate_clitics)
    return result
