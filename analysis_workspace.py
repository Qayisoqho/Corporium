"""Corpus research queries, bounded recent runs and explicitly saved evidence.

Research notes are separate from linguistic annotations and the edit undo journal.
Result payloads are compressed JSON text so ordinary full backups remain portable.
"""
import long_tasks
import base64
import json
import gloss_inheritance
import math
import uuid
import zlib
import io
from collections import defaultdict
from datetime import datetime, timezone
from functools import lru_cache
import corpus
import grammar
import corpus_statistics
import annotations
import analysis_fields
import people_queries
import code_switching
import morpheme_colors
import analysis_payload
import grammaticality

TABLES=('analysis_state','analysis_runs','analysis_saved','analysis_groups','analysis_evidence')
VERSION=14
FIELDS=('reduplication','form','morpheme','tag','lexeme','pos','ipa','translation','notes','grammaticality')
SENTENCE_FIELDS=('ipa','translation','notes','grammaticality')
DIMENSIONS=('value','form','tag','lexeme','pos','text','sentence_speaker','speakers','place','date','genre','folder','grammaticality')


def encode(value):
    return json.dumps(value,ensure_ascii=False,separators=(',',':'))


class RecordStream:
    """Internal snapshot input: render and encode each record once, then release it."""
    def __init__(self,db,hits):self.db=db;self.hits=hits
    def __iter__(self):return materialized_items(self.db,self.hits,reuse_words=True)


def pack(value):
    # Keep the same JSON/base64/zlib format while avoiding full Unicode AND
    # UTF-8 copies of a large research snapshot at the same time.
    compressor=zlib.compressobj(6);out=io.BytesIO();encoder=json.JSONEncoder(ensure_ascii=False,separators=(',',':'))
    def encoded_key(key):
        if isinstance(key,str):return encoder.encode(key)
        if key is None or isinstance(key,(int,float,bool)):return encoder.encode(encoder.encode(key))
        raise TypeError('JSON object keys must be strings or numbers')
    def pairs(items):
        yield '{'
        for i,(key,item) in enumerate(items):
            if i:yield ','
            yield encoded_key(key);yield ':';yield encoder.encode(item)
        yield '}'
    def chunks():
        if not isinstance(value,dict):yield encoder.encode(value);return
        yield '{'
        for i,(key,item) in enumerate(value.items()):
            if i:yield ','
            yield encoded_key(key);yield ':'
            if key=='records' and isinstance(item,(dict,RecordStream)):yield from pairs(item.items() if isinstance(item,dict) else item)
            elif isinstance(item,list):
                yield '['
                for n,row in enumerate(item):
                    if n:yield ','
                    yield encoder.encode(row)
                yield ']'
            else:yield encoder.encode(item)
        yield '}'
    pending=[];size=0
    for chunk in chunks():
        pending.append(chunk);size+=len(chunk)
        if size>=65536:
            long_tasks.checkpoint(None,'正在整理分析结果…')
            out.write(compressor.compress(''.join(pending).encode('utf-8')));pending=[];size=0
    if pending:out.write(compressor.compress(''.join(pending).encode('utf-8')))
    out.write(compressor.flush())
    return base64.b64encode(out.getvalue()).decode('ascii')


def unpack(value):
    return json.loads(zlib.decompress(base64.b64decode(value)))


def now():return datetime.now(timezone.utc).isoformat()
def uid():return str(uuid.uuid4())


def initialize(db):
    db.executescript('''
    CREATE TABLE IF NOT EXISTS analysis_state(id INTEGER PRIMARY KEY,version TEXT NOT NULL);
    CREATE TABLE IF NOT EXISTS analysis_runs(id TEXT PRIMARY KEY,language_id TEXT NOT NULL,created TEXT NOT NULL,query TEXT NOT NULL,version TEXT NOT NULL,summary TEXT NOT NULL,payload TEXT NOT NULL);
    CREATE INDEX IF NOT EXISTS analysis_runs_scope ON analysis_runs(language_id,created);
    CREATE TABLE IF NOT EXISTS analysis_saved(id TEXT PRIMARY KEY,language_id TEXT NOT NULL,kind TEXT NOT NULL,name TEXT NOT NULL,notes TEXT NOT NULL,created TEXT NOT NULL,body TEXT NOT NULL,payload TEXT NOT NULL DEFAULT '');
    CREATE TABLE IF NOT EXISTS analysis_groups(id TEXT PRIMARY KEY,language_id TEXT NOT NULL,name TEXT NOT NULL,notes TEXT NOT NULL,created TEXT NOT NULL);
    CREATE TABLE IF NOT EXISTS analysis_evidence(id TEXT PRIMARY KEY,group_id TEXT NOT NULL,entry_id TEXT NOT NULL,word_position INTEGER NOT NULL,notes TEXT NOT NULL,created TEXT NOT NULL,payload TEXT NOT NULL);
    CREATE INDEX IF NOT EXISTS analysis_evidence_group ON analysis_evidence(group_id);
    ''')
    invalidate(db)
    trim(db)


def invalidate(db):
    db.execute('INSERT INTO analysis_state VALUES(1,?) ON CONFLICT(id) DO UPDATE SET version=excluded.version',(uid(),))


def version(db):return db.execute('SELECT version FROM analysis_state WHERE id=1').fetchone()[0]


def trim(db):
    # Hard delete the row AND its only result payload. No hidden archive or undo copy.
    db.execute('DELETE FROM analysis_runs WHERE rowid NOT IN (SELECT rowid FROM analysis_runs ORDER BY rowid DESC LIMIT 30)')


def text(value,limit=2000):
    if not isinstance(value,str) or len(value)>limit:raise ValueError('文本内容无效或过长')
    return value


def normalize(b):
    if not isinstance(b,dict):raise ValueError('查询格式无效')
    if b.get('kind')=='counts':
        case=b.get('case',True)
        if type(case) is not bool:raise ValueError('搜索匹配设置无效')
        import vocabulary_selection
        selection=vocabulary_selection.normalize(b.get('vocabulary'))
        return dict(kind='counts',scope=corpus_statistics.normalize(b.get('scope',{})),case=case,engine=VERSION,**({'vocabulary':selection} if selection else {}))
    scope=b.get('scope',{})
    if not isinstance(scope,dict):raise ValueError('语料范围无效')
    normalized_scope={k:text(scope.get(k,'')) for k in ('text_id','folder_id','speakers','place','date','genre','sentence_language','code_mode','code_id')}
    code_switching.filter_sql(normalized_scope, "'corpus'", 'e.id')
    normalized_scope.update(people_queries.normalize(scope))
    conditions=b.get('conditions',[])
    if not isinstance(conditions,list) or not 1<=len(conditions)<=8:raise ValueError('请设置 1—8 个检索条件')
    normalized=[]
    for i,c in enumerate(conditions):
        if not isinstance(c,dict):raise ValueError('检索条件无效')
        field=c.get('field','form')
        if not isinstance(field,str):raise ValueError('检索字段无效')
        mode=c.get('mode','belongs' if field.startswith('class:') else 'exact');relation=c.get('relation','same_word')
        if (field not in FIELDS and not analysis_fields.custom(field)) or mode not in (('belongs','not_belongs') if field.startswith('class:') else ('exact','contains','prefix','suffix')) or relation not in ('same_word','sentence','left','right'):raise ValueError('检索层或条件关系无效')
        lo,hi=c.get('min',1),c.get('max',3)
        if type(lo) is not int or type(hi) is not int or not 1<=lo<=hi<=30:raise ValueError('词距须为 1—30 之间的整数')
        value=text(c.get('value',''))
        if i and not value.strip() and not field.startswith('class:'):raise ValueError('附加条件不能为空；请移除不用的条件')
        if i and relation!='sentence' and (is_sentence(field) or is_sentence(normalized[0]['field'])):raise ValueError('整句字段的组合条件请选择“同一句”')
        normalized.append(dict(field=field,value=value,mode=mode,relation=relation,min=lo,max=hi,exclude=bool(c.get('exclude',False)) if i else False))
        if analysis_fields.custom(field):normalized[-1]['include_children']=bool(c.get('include_children',True))
    return dict(scope=normalized_scope,conditions=normalized,case=bool(b.get('case',False)),engine=VERSION)


def is_sentence(field):return field in SENTENCE_FIELDS or analysis_fields.sentence(field)


def code_sentence_query(q):
    """A code scope without a content condition refers to whole sentences."""
    conditions=q.get('conditions',[]);scope=q.get('scope',{})
    return bool(scope.get('code_mode') or scope.get('code_id')) and len(conditions)==1 and conditions[0]['field']=='form' and not conditions[0]['value'].strip()


def accepts(value,condition,case):
    a=corpus.normalize(str(value),case);b=corpus.normalize(condition['value'],case)
    if not b:return True
    mode=condition['mode']
    return a==b if mode=='exact' else a.startswith(b) if mode=='prefix' else a.endswith(b) if mode=='suffix' else b in a


def sources(db,lid,scope):
    import collaborators
    people_names=collaborators.text_names(db)
    rows=db.execute("SELECT t.id,t.title,t.language_id,i.folder_id,COALESCE(i.metadata,'{}') metadata,COALESCE(f.name,'未分类') folder FROM texts t LEFT JOIN text_info i ON i.text_id=t.id LEFT JOIN folders f ON f.id=i.folder_id WHERE (?='all' OR t.language_id=?) ORDER BY t.rowid",(lid,lid))
    selected={}
    for r in rows:
        if scope['text_id'] and r['id']!=scope['text_id']:continue
        if scope['folder_id'] and (r['folder_id'] or 'unfiled')!=scope['folder_id']:continue
        meta=json.loads(r['metadata'])
        meta['speakers']=people_names.get(r['id'],meta.get('speakers') or meta.get('legacy_people',{}).get('speakers',''))
        if any(scope[k].casefold() not in str(meta.get(k,'')).casefold() for k in ('speakers','place','date','genre') if scope[k]):continue
        selected[r['id']]={**dict(r),'metadata':meta}
    return selected


def calculate(db,lid,q):
    judgment_catalog={r['id']:grammaticality.definitions(r['metadata']) for r in db.execute('SELECT id,metadata FROM languages')}
    custom=analysis_fields.Context(db,q);word_counter=corpus_statistics.WordCounter()
    people=people_queries.Context(db);scope=q['scope']
    corpus_code,corpus_args=code_switching.filter_sql(scope,"'corpus'",'e.id')
    independent_code,independent_args=code_switching.filter_sql(scope,"'independent'",'d.id')
    selected=sources(db,lid,q['scope']);conditions=q['conditions'];hits=[];sentence_count=0;word_count=0;linked_words=0
    lookup=grammar.index(grammar.listing(db,'all'));units=defaultdict(list);links=defaultdict(list)
    need_morph=any(c['field']=='morpheme' for c in conditions)
    eligible=None
    if scope['source']=='independent':eligible=set()
    elif scope['speaker_state']!='any' or any(scope[k] for k in ('text_id','folder_id','speakers','place','date','genre','speaker_ids','collaborator_ids','collaborator_role')):
        eligible={r['id'] for r in db.execute('SELECT id,text_id FROM entries') if r['text_id'] in selected and people.text_matches(r['text_id'],scope) and people.sentence_matches(people.attribution('corpus',r['id']),scope)}
    lexical={r['id']:{**dict(r),'body':json.loads(r['body'])} for r in db.execute('SELECT id,headword,body,language_id FROM dictionary_targets')}
    import component_links
    def load_batch(ids):
        units.clear();links.clear()
        if not ids:return
        marks=','.join('?' for _ in ids)
        for r in long_tasks.steps(db.execute("SELECT id,entry_id,kind,parent_id,position,form FROM corpus_units WHERE active=1 AND (? OR kind='word') AND entry_id IN ("+marks+')',[need_morph,*ids])):
            units[r['entry_id']].append(dict(r))
        sql='''SELECT l.*,u.entry_id,u.position,u.kind,p.position parent_position,c.body component_body,v.id review_id
            FROM lexical_links l JOIN corpus_units u ON u.id=l.unit_id LEFT JOIN corpus_units p ON p.id=u.parent_id
            LEFT JOIN component_links c ON c.id=l.id LEFT JOIN lexical_reviews v ON v.id=l.id
            WHERE u.active=1 AND u.entry_id IN ('''+marks+')'
        for r in long_tasks.steps(db.execute(sql,ids)):
            x=lexical.get(r['lexeme_id'])
            if not x or r['review_id'] is not None or component_links.review(x['body'],json.loads(r['component_body']) if r['component_body'] is not None else None):continue
            usage=next((u for u in x['body']['usages'] if u['id']==r['usage_id']),None)
            link=dict(r);link.pop('component_body');link.pop('review_id')
            links[(r['entry_id'],r['position'] if r['kind']=='word' else r['parent_position'])].append((x['id'],x['headword'],usage.get('pos','') if usage else '',x['language_id'],link,x))
    @lru_cache(maxsize=20000)
    def tag_values(gloss,language):return list(dict.fromkeys(grammar.tokens(gloss,language,lookup)))
    @lru_cache(maxsize=20000)
    def matches(value,index):return conditions[index]['field']=='grammaticality' or (conditions[index]['field']=='reduplication' and not conditions[index]['value']) or analysis_fields.custom(conditions[index]['field']) or accepts(value,conditions[index],q['case'])
    analysis_cache=corpus.WordAnalysisCache()
    def sentences():
        if scope['source']!='independent' and selected:
            where='1=1';args=[]
            if len(selected)<=400:
                where='e.text_id IN ('+','.join('?' for _ in selected)+')';args=list(selected)
            cursor=db.execute('SELECT e.id,e.text_id,e.body FROM texts t CROSS JOIN entries e ON e.text_id=t.id WHERE '+where+corpus_code+' ORDER BY t.rowid,e.position',[*args,*corpus_args])
            while batch:=cursor.fetchmany(400):
                ready=[r for r in batch if (eligible is None or r['id'] in eligible) and r['text_id'] in selected and people.text_matches(r['text_id'],scope)]
                load_batch([r['id'] for r in ready])
                gloss_inheritance.prefetch(db,'corpus',[r['id'] for r in ready],changed_only=True)
                for r in long_tasks.steps(ready):yield dict(r),selected[r['text_id']],'corpus',r['id']
        # Text-level filters must never silently include unrelated dictionary examples.
        text_scope=any(scope[k] for k in ('text_id','folder_id','speakers','place','date','genre','collaborator_ids','collaborator_role'))
        if scope['source']!='corpus' and not text_scope:
            for r in long_tasks.steps(gloss_inheritance.iter_rows(db,db.execute("SELECT d.* FROM dictionary_examples d WHERE (?='all' OR d.language_id=?)"+independent_code+' ORDER BY d.rowid',[lid,lid,*independent_args]),'independent')):
                units.clear();links.clear()
                key='independent:'+r['id'];body=corpus.analyze(gloss_inheritance.load(db,'independent',r['id'],r['body']),cache=analysis_cache)
                for i,w in long_tasks.steps(enumerate(body['words'])):
                    uid=w.get('annotation_id','');units[key].append(dict(id=uid,position=i,kind='word'))
                    if need_morph:
                        for j,m in long_tasks.steps(enumerate(w.get('morphemes',[]))):units[key].append(dict(id=uid+':m:'+str(j),parent_id=uid,kind='morpheme',form=m['form']))
                yield dict(id=key,text_id=None,body=body),dict(language_id=r['language_id'],metadata={},folder='独立例句'),'independent',r['id']
    for r,source,kind,record_id in long_tasks.steps(sentences()):
        if not source:continue
        attribution=people.attribution(kind,record_id)
        if not people.sentence_matches(attribution,scope):continue
        body=r['body'] if isinstance(r['body'],dict) else gloss_inheritance.load(db,kind,record_id,r['body'],metadata=False,lightweight=True);effective=body.get('language_id') or source['language_id']
        if q['scope']['sentence_language'] and effective!=q['scope']['sentence_language']:continue
        sentence_count+=1
        words=body['words'];positions=[i for i,w in enumerate(words) if word_counter(w)]
        ordinal={pos:i for i,pos in enumerate(positions)};word_count+=len(positions)
        word_units={u['position']:u for u in units[r['id']] if u['kind']=='word'}
        morphs=defaultdict(list)
        for u in long_tasks.steps(units[r['id']]):
            if u['kind']=='morpheme':morphs[u['parent_id']].append(u)
        tags={i:tag_values(words[i]['gloss'],effective) for i in positions}
        sentence_links={i:[x for x in links.get((r['id'],i),[]) if x[3]==effective] for i in positions}
        linked_words+=sum(bool(v) for v in sentence_links.values())
        import reduplication
        redup_values=reduplication.index(body) if any(c['field']=='reduplication' for c in conditions) else {}
        def values(condition,pos):
            field=condition['field']
            if analysis_fields.custom(field):
                unit=word_units.get(pos,{}).get('id','')
                linked=[(v[4],v[5]) for v in sentence_links.get(pos,[])]
                return [(v,unit) for v in custom.matched(condition,r['id'],unit,effective,linked,tags.get(pos,[]),accepts,q['case'])]
            if field in SENTENCE_FIELDS:
                if field=='grammaticality':
                    if kind!='independent':return []
                    item=grammaticality.selected(body.get('grammaticality',''),judgment_catalog[effective])
                    return [(item['name'],'')] if not condition['value'] or any(accepts(v,condition,q['case']) for v in (item['name'],item['symbol'])) else []
                if field=='notes':return [(str(body.get('notes',''))+' '+str(body.get('language_notes',''))+' '+str(source['metadata'].get('notes','')),'')]
                return [(body.get(field,''),'')]
            w=words[pos];unit=word_units.get(pos,{});ls=sentence_links.get(pos,[])
            if field=='reduplication':
                return [(v,unit.get('id','')) for v in redup_values.get(pos,[])]
            if field=='form':return [(corpus.clean(w['form']),unit.get('id',''))]
            if field=='morpheme':return [(u['form'],u['id']) for u in morphs[unit.get('id')]]
            if field=='tag':return [(v,unit.get('id','')) for v in tags[pos]]
            if field=='lexeme':return list(dict.fromkeys((v[1],v[0]) for v in ls))
            return list(dict.fromkeys((v[2],unit.get('id','')) for v in ls if v[2]))
        anchor=conditions[0]
        sentence_only=code_sentence_query(q)
        for pos in (long_tasks.steps([-1] if sentence_only or is_sentence(anchor['field']) else positions)):
            candidates=[(body.get('ipa') or ' '.join(w['form'] for w in words),'')] if sentence_only else [(v,u) for v,u in values(anchor,pos) if matches(v,0)]
            if not candidates:continue
            accepted=True
            for ci,c in long_tasks.steps(enumerate(conditions[1:],1)):
                if is_sentence(c['field']):targets=[-1]
                elif c['relation']=='same_word':targets=[pos]
                elif c['relation']=='sentence':targets=positions
                else:
                    targets=[p for p in positions if c['min'] <= ((ordinal[p]-ordinal[pos]) if c['relation']=='right' else (ordinal[pos]-ordinal[p])) <= c['max']]
                found=any(matches(v,ci) for p in targets for v,_ in values(c,p))
                if found==c['exclude']:accepted=False;break
            if not accepted:continue
            ls=sentence_links.get(pos,[])
            for value,unit in long_tasks.steps(candidates):
                dims=dict(value=[value],form=[corpus.clean(words[pos]['form'])] if pos>=0 else [],tag=tags.get(pos,[]),lexeme=list(dict.fromkeys(x[0] for x in ls)),pos=list(dict.fromkeys(x[2] for x in ls if x[2])),text=[r['text_id']],folder=[source['folder']])
                dims.update({k:[str(source['metadata'].get(k,'')).strip() or '（未填写）'] for k in ('speakers','place','date','genre')})
                dims['text']=[r['text_id']] if r['text_id'] else []
                dims['sentence_speaker']=[] if attribution['conflict'] else attribution['ids']
                dims['grammaticality']=[grammaticality.selected(body.get('grammaticality',''),judgment_catalog[effective])['name']] if kind=='independent' else []
                hits.append(dict(entry_id=r['id'],word=pos,unit_id=unit,value=value,dimensions=dims))
                if len(hits)>200000:raise ValueError('命中超过 200000 处，请缩小语料范围或检索条件')
    matched={('independent',h['entry_id'].partition(':')[2]) if h['entry_id'].startswith('independent:') else ('corpus',h['entry_id']) for h in hits}
    return dict(hits=hits,labels={'sentence_speaker':people.people,'text':{k:v['title'] for k,v in selected.items()},'lexeme':{k:v['headword'] for k,v in lexical.items()}},scope_sentences=sentence_count,scope_words=word_count,linked_words=linked_words,code_summary=code_switching.summary_records(db,matched))


def summarize(result):
    hits=result['hits']
    return dict(hits=len(hits),sentences=len({h['entry_id'] for h in hits}),texts=len({t for h in hits for t in h['dimensions']['text']}),scope_sentences=result['scope_sentences'],scope_words=result['scope_words'],linked_words=result['linked_words'],code_summary=result['code_summary'])


def run(db,lid,b):
    q=analysis_fields.prepare(db,lid,normalize(b.get('query')));raw=encode(q)
    if not db.in_transaction:db.execute('BEGIN IMMEDIATE')
    v=version(db)
    cached=db.execute('SELECT payload,summary FROM analysis_runs WHERE language_id=? AND query=? AND version=? ORDER BY rowid DESC LIMIT 1',(lid,raw,v)).fetchone()
    if cached:payload,summary=cached['payload'],cached['summary']
    else:
        if q.get('kind')=='counts':
            import vocabulary_selection
            selection=vocabulary_selection.Selection(db,lid,q['vocabulary'],q['case']) if q.get('vocabulary') else None
            stats=corpus_statistics.calculate(db,lid,q['scope'],case=q.get('case',True),selection=selection)
            result=dict(hits=stats.pop('_hits'),vocabulary=stats.pop('_vocabulary'),statistics=stats)
            summary=encode(dict(kind='counts',**{k:v for k,v in stats.items() if k!='rows'}))
        else:
            result=calculate(db,lid,q);summary=encode(summarize(result))
        payload=pack(result)
    rid=uid();db.execute('INSERT INTO analysis_runs VALUES(?,?,?,?,?,?,?)',(rid,lid,now(),raw,v,summary,payload));trim(db)
    return dict(id=rid,query=q,summary=json.loads(summary),version=v,cached=bool(cached))


def owned(db,table,rid,lid):
    row=db.execute('SELECT * FROM '+table+' WHERE id=? AND language_id=?',(rid,lid)).fetchone()
    if not row:raise ValueError('记录已不存在，或不属于当前语言范围')
    return row


def record_metadata(db,rid,lid,snapshot=False):
    table='analysis_saved' if snapshot else 'analysis_runs';row=owned(db,table,rid,lid)
    if snapshot:
        if row['kind']!='snapshot':raise ValueError('这不是结果快照，请重新运行收藏查询')
        saved=json.loads(row['body']);return row,saved['query'],saved['summary'],saved['version'],True
    return row,json.loads(row['query']),json.loads(row['summary']),row['version'],False


def record(db,rid,lid,snapshot=False):
    row,q,summary,v,frozen=record_metadata(db,rid,lid,snapshot)
    return row,unpack(row['payload']),q,summary,v,frozen


def materialize(db,hits):
    return dict(materialized_items(db,hits))


def source_record(record):
    # Older frozen evidence remains readable, without reviving retired text fields.
    if record and record.get('kind','corpus')!='independent':grammaticality.strip_corpus(record['body'])
    return record


def materialized_items(db,hits,*,reuse_words=False):
    if not hits:return
    judgments={r['id']:grammaticality.definitions(r['metadata']) for r in db.execute('SELECT id,metadata FROM languages')}
    # Retained cards keep the native analyzer's shared internal segment objects.
    # Streaming snapshots can reuse serialized analyses and release each card.
    analysis_cache=corpus.WordAnalysisCache() if reuse_words else None
    ids=list(dict.fromkeys(h['entry_id'] for h in hits))
    people=people_queries.Context(db)
    independent=[key.partition(':')[2] for key in ids if key.startswith('independent:')]
    ids=[key for key in ids if not key.startswith('independent:')]
    for start in long_tasks.steps(range(0,len(independent),400)):
        chunk=independent[start:start+400]
        for r in long_tasks.steps(db.execute('SELECT * FROM dictionary_examples WHERE id IN ('+','.join('?' for _ in chunk)+')',chunk)):
            body=annotations.enrich(db,json.loads(r['body']),'independent',r['id'])
            body['grammaticality_display']=dict(grammaticality.selected(body.get('grammaticality',''),judgments[r['language_id']]))
            yield 'independent:'+r['id'],{**dict(r),'kind':'independent','body':body,'owner_language':r['language_id'],'title':'词典独立例句','position':None,'metadata':{},'attribution':people.attribution('independent',r['id'])}
    definitions=defaultdict(list)
    for r in long_tasks.steps(db.execute('SELECT * FROM annotation_layers ORDER BY position,id')):definitions[r['language_id']].append(dict(r))
    for start in long_tasks.steps(range(0,len(ids),400)):
        chunk=ids[start:start+400]
        placeholders=','.join('?' for _ in chunk);units=defaultdict(dict);cells=defaultdict(list)
        for u in long_tasks.steps(db.execute("SELECT entry_id,position,id FROM corpus_units WHERE active=1 AND kind='word' AND entry_id IN ("+placeholders+')',chunk)):units[u['entry_id']][u['position']]=u['id']
        for c in long_tasks.steps(db.execute("SELECT * FROM annotation_cells WHERE owner_kind='corpus' AND record_id IN ("+placeholders+')',chunk)):cells[c['record_id']].append(dict(c))
        colors=morpheme_colors.prepare(db,chunk)
        gloss_inheritance.prefetch(db,'corpus',chunk)
        for r in long_tasks.steps(db.execute("SELECT e.*,t.title,t.language_id owner_language,COALESCE(i.metadata,'{}') metadata FROM entries e JOIN texts t ON t.id=e.text_id LEFT JOIN text_info i ON i.text_id=t.id WHERE e.id IN ("+','.join('?' for _ in chunk)+')',chunk)):
            body=corpus.analyze(gloss_inheritance.load(db,'corpus',r['id'],r['body']),cache=analysis_cache);language=body.get('language_id') or r['owner_language']
            grammaticality.strip_corpus(body)
            annotations.attach(body,[units[r['id']].get(i,'') for i in range(len(body['words']))],definitions[language],cells[r['id']])
            morpheme_colors.attach(db,body,'corpus',r['id'],language,prepared=colors)
            code_switching.attach(db,body,'corpus',r['id'])
            yield r['id'],{**dict(r),'kind':'corpus','body':body,'metadata':json.loads(r['metadata']),'attribution':people.attribution('corpus',r['id'])}


def context_forms(db,hits,case):
    """Sort keys need original forms, not every sentence's rendered annotation."""
    result={};ids=list(dict.fromkeys(h['entry_id'] for h in hits if h['word']>=0))
    for independent,table in ((False,'entries'),(True,'dictionary_examples')):
        chosen=[key.partition(':')[2] if independent else key for key in ids if key.startswith('independent:')==independent]
        for start in long_tasks.steps(range(0,len(chosen),400)):
            batch=chosen[start:start+400]
            for row in db.execute('SELECT id,body FROM '+table+' WHERE id IN ('+','.join('?' for _ in batch)+')',batch):
                key=('independent:' if independent else '')+row['id']
                result[key]=tuple(corpus.normalize(w['form'],case) for w in json.loads(row['body'])['words'])
    return result


def result_page(db,lid,b):
    row,q,summary,v,frozen=record_metadata(db,b['id'],lid,b.get('snapshot')=='true')
    stale=v!=version(db)
    common=dict(id=row['id'],query=q,summary=summary,version=v,stale=stale,snapshot=frozen,created=row['created'])
    if stale and not frozen:return {**common,'items':[],'total':0,'page':1,'pages':1,'frequencies':[]}
    if q.get('kind')=='counts':
        result=analysis_payload.read(row['payload'],only={'statistics','vocabulary','hits'})
        if 'vocabulary' not in result:return {**common,'statistics':result['statistics'],'items':[],'page':1,'pages':1}
        import vocabulary_statistics
        profile,indices=vocabulary_statistics.page(result,b)
        selected=[{**result['hits'][i],'index':i} for i in indices]
        records=analysis_payload.read(row['payload'],only={'records'},record_ids={h['entry_id'] for h in selected}).get('records',{}) if frozen and selected else materialize(db,selected)
        profile['items']=[{**h,'record':source_record(records.get(h['entry_id']))} for h in selected]
        return {**common,'statistics':result['statistics'],'vocabulary':profile,'items':[],'page':1,'pages':1}
    if b.get('sort') in ('left','right') and frozen:
        import tempfile
        with tempfile.TemporaryFile() as spool:return read_page(db,row,q,b,common,spool)
    return read_page(db,row,q,b,common)


def read_page(db,row,q,b,common,spool=None):
    plan=None;signature=None;forms={} if spool is not None else None;offsets={}
    def retain(rid,raw):
        encoded=raw.encode('utf-8');offsets[rid]=(spool.tell(),len(encoded));spool.write(encoded)
    def choose(partial):
        nonlocal plan,signature
        if forms is not None or not {'hits','labels'}<=partial.keys():return ()
        plan=page_plan(db,partial,q,b);signature=(id(partial['hits']),id(partial['labels']))
        return {h['entry_id'] for _,h in plan['chosen']}
    result=analysis_payload.read(row['payload'],record_ids=choose,forms=forms,normalize=lambda s:corpus.normalize(s,q['case']),record_sink=retain if spool is not None else None)
    if signature!=(id(result['hits']),id(result['labels'])):
        plan=page_plan(db,result,q,b,forms=forms if result.get('records') else None)
        if result.get('records'):
            if spool is not None:
                for rid in {h['entry_id'] for _,h in plan['chosen']}:
                    if rid in offsets:
                        position,size=offsets[rid];spool.seek(position);result['records'][rid]=json.loads(spool.read(size))
            else:result['records']=analysis_payload.read(row['payload'],only={'records'},record_ids={h['entry_id'] for _,h in plan['chosen']})['records']
    chosen=plan.pop('chosen');visible_records=result.get('records') or materialize(db,[h for _,h in chosen])
    items=[{**h,'index':i,'record':source_record(visible_records.get(h['entry_id']))} for i,h in chosen]
    return {**common,'items':items,**plan}


def page_plan(db,result,q,b,*,forms=None):
    dimension=b.get('dimension','value')
    if dimension not in DIMENSIONS:raise ValueError('分布维度无效')
    hits=result['hits'];bins={}
    for h in long_tasks.steps(hits):
        if dimension=='grammaticality' and not h['entry_id'].startswith('independent:'):continue
        for value in long_tasks.steps(set(h['dimensions'].get(dimension,[]) or ['（未关联／未填写）'])):
            item=bins.setdefault(value,[0,set(),set()]);item[0]+=1;item[1].add(h['entry_id']);item[2].update(h['dimensions']['text'])
    frequencies=[dict(value=k,label=result['labels'].get(dimension,{}).get(k,k),hits=v[0],sentences=len(v[1]),texts=len(v[2])) for k,v in bins.items()]
    frequencies.sort(key=lambda x:(-x['hits'],x['label']))
    filtered=[(i,h) for i,h in enumerate(hits) if 'value' not in b or (dimension!='grammaticality' or h['entry_id'].startswith('independent:')) and b['value'] in (h['dimensions'].get(dimension,[]) or ['（未关联／未填写）'])]
    sort=b.get('sort','source')
    if sort not in ('source','left','right','value'):raise ValueError('排序方式无效')
    records=result.get('records')
    if sort in ('left','right'):
        forms=forms if forms is not None else None if records else context_forms(db,[h for _,h in filtered],q['case'])
        def context_key(pair):
            h=pair[1];p=h['word']
            if p<0:return ()
            words=forms[h['entry_id']] if forms is not None else tuple(corpus.normalize(w['form'],q['case']) for w in records[h['entry_id']]['body']['words'])
            return words[:p][::-1] if sort=='left' else words[p+1:]
        filtered.sort(key=context_key)
    elif sort=='value':filtered.sort(key=lambda pair:pair[1]['value'].casefold())
    pages=max(1,math.ceil(len(filtered)/30));page=max(1,min(int(b.get('page',1)),pages));chosen=filtered[(page-1)*30:page*30]
    # Frequency lists are paginated too; every row can drill into the same run.
    frequency_pages=max(1,math.ceil(len(frequencies)/100));fp=max(1,min(int(b.get('frequency_page',1)),frequency_pages))
    return dict(chosen=chosen,total=len(filtered),page=page,pages=pages,frequencies=frequencies[(fp-1)*100:fp*100],frequency_page=fp,frequency_pages=frequency_pages,frequency_total=len(frequencies))


def listing(db,lid):
    v=version(db)
    # Recent runs are disposable caches; explicit snapshots and research stay separate.
    db.execute('DELETE FROM analysis_runs WHERE version<>?',(v,))
    recent=[{**dict(r),'query':json.loads(r['query']),'summary':json.loads(r['summary']),'stale':r['version']!=v} for r in db.execute('SELECT id,created,query,summary,version FROM analysis_runs WHERE language_id=? ORDER BY rowid DESC',(lid,))]
    saved=[{**dict(r),'body':json.loads(r['body'])} for r in db.execute('SELECT id,kind,name,notes,created,body FROM analysis_saved WHERE language_id=? ORDER BY rowid DESC',(lid,))]
    groups=[dict(r) for r in db.execute('SELECT g.*,(SELECT COUNT(*) FROM analysis_evidence e WHERE e.group_id=g.id) count FROM analysis_groups g WHERE language_id=? ORDER BY rowid DESC',(lid,))]
    return dict(recent=recent,saved=saved,groups=groups,limit=30,version=v)


def mutate(db,lid,action,b):
    if not db.in_transaction:db.execute('BEGIN IMMEDIATE')
    if action=='save':
        name=text(b.get('name',''),200).strip();notes=text(b.get('notes',''),20000);kind=b.get('kind')
        if not name or kind not in ('query','scope','snapshot'):raise ValueError('请填写名称并选择保存类型')
        payload=''
        if kind=='scope':body={'scope':normalize(b['query'])['scope']}
        elif kind=='query':body={'query':analysis_fields.prepare(db,lid,normalize(b['query']))}
        else:
            source,q,summary,v,_=record_metadata(db,b['run_id'],lid)
            if v!=version(db):raise ValueError('语料已更新，请重新运行后保存快照')
            result=analysis_payload.read(source['payload'])
            result['records']=RecordStream(db,result['hits']);result['languages']=[dict(r) for r in db.execute('SELECT * FROM languages')]
            body=dict(query=q,summary=summary,version=v,engine=VERSION);payload=pack(result)
        sid=uid();db.execute('INSERT INTO analysis_saved VALUES(?,?,?,?,?,?,?,?)',(sid,lid,kind,name,notes,now(),encode(body),payload));return {'id':sid}
    if action=='rename':
        owned(db,'analysis_saved',b['id'],lid);name=text(b.get('name',''),200).strip()
        if not name:raise ValueError('名称不能为空')
        db.execute('UPDATE analysis_saved SET name=?,notes=? WHERE id=?',(name,text(b.get('notes',''),20000),b['id']));return {'ok':True}
    if action=='delete':
        if b.get('confirmed') is not True:raise ValueError('请确认删除记录及其结果；此操作不能撤销')
        table={'recent':'analysis_runs','saved':'analysis_saved','group':'analysis_groups'}.get(b.get('kind'))
        if not table:raise ValueError('记录类型无效')
        owned(db,table,b['id'],lid)
        if table=='analysis_groups':db.execute('DELETE FROM analysis_evidence WHERE group_id=?',(b['id'],))
        db.execute('DELETE FROM '+table+' WHERE id=?',(b['id'],));return {'ok':True}
    if action=='group':
        name=text(b.get('name',''),200).strip();notes=text(b.get('notes',''),20000)
        if not name:raise ValueError('请填写研究分组名称')
        gid=b.get('id') or uid()
        if b.get('id'):
            owned(db,'analysis_groups',gid,lid);db.execute('UPDATE analysis_groups SET name=?,notes=? WHERE id=?',(name,notes,gid))
        else:db.execute('INSERT INTO analysis_groups VALUES(?,?,?,?,?)',(gid,lid,name,notes,now()))
        return {'id':gid}
    if action=='evidence':
        owned(db,'analysis_groups',b['group_id'],lid)
        source,q,summary,v,frozen=record_metadata(db,b['run_id'],lid,bool(b.get('snapshot')))
        if not frozen and v!=version(db):raise ValueError('语料已更新，请重新运行后收集例证')
        index=b.get('index')
        if type(index) is not int or index<0:raise ValueError('请选择有效例证')
        h,records=analysis_payload.occurrence(source['payload'],index);records=records or materialize(db,[h]);e=records.get(h['entry_id'])
        if not e:raise ValueError('原句已不存在')
        eid=uid();payload=dict(hit=h,record=e,query=q,version=v,engine=VERSION)
        db.execute('INSERT INTO analysis_evidence VALUES(?,?,?,?,?,?,?)',(eid,b['group_id'],h['entry_id'],h['word'],text(b.get('notes',''),20000),now(),pack(payload)));return {'id':eid}
    if action in ('evidence-note','evidence-delete'):
        e=db.execute('SELECT e.* FROM analysis_evidence e JOIN analysis_groups g ON g.id=e.group_id WHERE e.id=? AND g.language_id=?',(b['id'],lid)).fetchone()
        if not e:raise ValueError('例证已不存在')
        if action=='evidence-note':db.execute('UPDATE analysis_evidence SET notes=? WHERE id=?',(text(b.get('notes',''),20000),b['id']))
        else:
            if b.get('confirmed') is not True:raise ValueError('请确认从研究分组删除此例证')
            db.execute('DELETE FROM analysis_evidence WHERE id=?',(b['id'],))
        return {'ok':True}
    raise ValueError('未知分析操作')


def evidence_page(db,lid,b):
    group=dict(owned(db,'analysis_groups',b['id'],lid));total=db.execute('SELECT COUNT(*) FROM analysis_evidence WHERE group_id=?',(b['id'],)).fetchone()[0]
    pages=max(1,math.ceil(total/30));page=max(1,min(int(b.get('page',1)),pages))
    items=[{**dict(r),'data':unpack(r['payload'])} for r in db.execute('SELECT * FROM analysis_evidence WHERE group_id=? ORDER BY rowid DESC LIMIT 30 OFFSET ?',(b['id'],(page-1)*30))]
    for item in items:
        item.pop('payload');source_record(item['data'].get('record'))
    return dict(group=group,items=items,total=total,page=page,pages=pages)


def export_result(db,lid,b):
    row,result,q,summary,v,frozen=record(db,b['id'],lid,b.get('snapshot')=='true')
    if not frozen and v!=version(db):raise ValueError('语料已更新，请重新运行后导出，或导出已保存快照')
    records=result.get('records') or materialize(db,result['hits'])
    for card in records.values():source_record(card)
    return dict(format='corporium-analysis-v1',created=row['created'],engine=VERSION,query=q,summary=summary,data_version=v,hits=result['hits'],records=records,statistics=result.get('statistics'),languages=result.get('languages') or [dict(r) for r in db.execute('SELECT * FROM languages')],**({'vocabulary':result['vocabulary']} if 'vocabulary' in result else {}))


def export_file(db,dbpath,lid,b):
    """Stage the same export document while retaining one hit/card at a time."""
    import tempfile
    from pathlib import Path
    import language_exchange
    row,q,summary,v,frozen=record_metadata(db,b['id'],lid,b.get('snapshot')=='true')
    if not frozen and v!=version(db):raise ValueError('语料已更新，请重新运行后导出，或导出已保存快照')
    payload=row['payload'];extra={}
    header=dict(format='corporium-analysis-v1',created=row['created'],engine=VERSION,query=q,summary=summary,data_version=v)
    encoder=json.JSONEncoder(ensure_ascii=False,separators=(',',':'));path=None
    try:
        with tempfile.NamedTemporaryFile(mode='w',encoding='utf-8',newline='\n',suffix='.json',dir=language_exchange.STAGING.name,delete=False) as stream:
            path=Path(stream.name);stream.write('{\n')
            for key,value in header.items():stream.write('  '+encoder.encode(key)+': '+encoder.encode(value)+',\n')
            ids={};have_hits=False;have_records=False
            def write_records(records):
                stream.write('  "records": {\n');first=True
                for rid,card in long_tasks.steps(records):
                    source_record(card)
                    if not first:stream.write(',\n')
                    first=False;stream.write('    '+encoder.encode(rid)+': '+encoder.encode(card))
                stream.write('\n  },\n')
            for section,values in analysis_payload.sections(payload):
                if section=='hits':
                    have_hits=True;ids={};stream.write('  "hits": [\n');first=True
                    for _,hit in long_tasks.steps(values):
                        if not first:stream.write(',\n')
                        first=False;stream.write('    '+encoder.encode(hit));ids[hit['entry_id']]=None
                    stream.write('\n  ],\n')
                elif section=='records':
                    from itertools import chain
                    first=next(values,None);have_records=first is not None
                    if have_records:write_records(chain([first],values))
                elif section in ('statistics','languages','vocabulary'):extra[section]=values
            if not have_hits:raise ValueError('分析结果缺少命中记录')
            if not have_records:write_records(materialized_items(db,[dict(entry_id=rid) for rid in ids],reuse_words=True))
            if 'vocabulary' in extra:stream.write('  "vocabulary": '+encoder.encode(extra['vocabulary'])+',\n')
            stream.write('  "statistics": '+encoder.encode(extra.get('statistics'))+',\n  "languages": '+encoder.encode(extra.get('languages') or [dict(r) for r in db.execute('SELECT * FROM languages')])+'\n}\n')
        long_tasks.checkpoint(None,'分析导出文件已生成')
        size=path.stat().st_size
        return dict(token=language_exchange.stage(dbpath,path,'analysis-json'),size=size)
    except BaseException:
        if path is not None:path.unlink(missing_ok=True)
        raise
