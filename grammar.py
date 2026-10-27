"""Per-language gloss inventory and read-only consistency audit."""
import long_tasks
import json
import gloss_inheritance
import re
import uuid
import segmentation
from collections import Counter,OrderedDict
import corpus
import grammar_audit_cache
import grammar_reference
from functools import lru_cache
from corpus import plain,analyze,boundary_count,gloss_chunks

TABLES=('grammar_tags',)

def initialize(db):
    existed=db.execute("SELECT 1 FROM sqlite_master WHERE name='grammar_tags'").fetchone()
    db.execute('CREATE TABLE IF NOT EXISTS grammar_tags(id TEXT PRIMARY KEY,language_id TEXT NOT NULL,symbol TEXT NOT NULL,description TEXT NOT NULL DEFAULT \'\',category TEXT NOT NULL DEFAULT \'\',aliases TEXT NOT NULL DEFAULT \'[]\',notes TEXT NOT NULL DEFAULT \'\',revision INTEGER NOT NULL DEFAULT 1)')
    db.execute('CREATE INDEX IF NOT EXISTS grammar_language ON grammar_tags(language_id)')
    if not existed:
        for r in db.execute('SELECT id,metadata FROM languages').fetchall():
            migrated={}
            for symbol,description in json.loads(r['metadata']).get('glossary',{}).items():
                key=symbol.casefold()
                if key in migrated:
                    db.execute("UPDATE grammar_tags SET notes=notes||? WHERE id=?",('\n旧缩写表另有 '+symbol+'：'+description,migrated[key]))
                else:
                    xid=str(uuid.uuid4());migrated[key]=xid
                    db.execute('INSERT INTO grammar_tags VALUES(?,?,?,?,?,?,?,1)',(xid,r['id'],symbol,description,'','[]','从旧缩写表迁入'))

def listing(db,lid='all'):
    return [{**dict(r),'aliases':json.loads(r['aliases'])} for r in db.execute("SELECT * FROM grammar_tags WHERE ?='all' OR language_id=? ORDER BY symbol COLLATE NOCASE,id",(lid,lid))]

def index(rows):
    result={}
    for r in rows:
        for name in [r['symbol'],*r['aliases']]:result[(r['language_id'],name.casefold())]=r
    return result

def recognized(token,lid,lookup,explicit=False):
    row=lookup.get((lid,token.casefold()))
    if not row:return False
    if explicit or token.casefold() not in grammar_reference.LEXICAL:return True
    # ALL/all, ART/art and PASS/pass can be English words. Preserve explicitly
    # saved spellings and aliases; do not invent ambiguous lower-case aliases.
    return token in [row['symbol'],*row.get('aliases',[])] or token.isupper()

def validate(db):
    known=set();languages={r[0] for r in db.execute('SELECT id FROM languages')}
    for r in listing(db):
        if r['language_id'] not in languages:raise ValueError('标签所属语言不存在')
        for name in [r['symbol'],*r['aliases']]:
            key=(r['language_id'],name.casefold())
            if key in known:raise ValueError('标签或别名重复：'+name)
            known.add(key)

def publish(db,lid):
    row=db.execute('SELECT metadata FROM languages WHERE id=?',(lid,)).fetchone();meta=json.loads(row[0])
    meta['glossary']={name:r['description'] for r in listing(db,lid) for name in [r['symbol'],*r['aliases']]}
    db.execute('UPDATE languages SET metadata=?,revision=revision+1 WHERE id=?',(json.dumps(meta,ensure_ascii=False),lid))

def mutate(db,action,b,lid,*,lookup=None,publish_result=True):
    old=db.execute('SELECT * FROM grammar_tags WHERE id=?',(b.get('id'),)).fetchone()
    if b.get('id') and (not old or old['revision']!=b.get('revision')):raise ValueError('标签已修改或删除，请重新打开')
    if action=='grammar-delete':
        if not old or b.get('confirmed') is not True:raise ValueError('请确认删除标签定义；原句标注不会被删除')
        db.execute('DELETE FROM grammar_tags WHERE id=?',(old['id'],));publish(db,lid);return {'ok':True}
    if not isinstance(b.get('symbol',''),str):raise ValueError('标签须为文本')
    symbol=b.get('symbol','').strip();aliases=b.get('aliases',[])
    if not isinstance(aliases,list) or any(not isinstance(a,str) for a in aliases):raise ValueError('别名格式不正确')
    aliases=[a.strip() for a in aliases if a.strip()];names=[symbol,*aliases]
    def valid_symbol(n):
        base=re.sub(r'#(?:sub|super|sup)\[[A-Za-z0-9]+\]','',n)
        return bool(base) and not re.search(r'[\s.\-=:+~/;_\\,!?，。；：！？\[\](){}<>#]',base)
    if any(not valid_symbol(n) for n in names):raise ValueError('单个标签不能包含分隔符；上下标可写为 #sub[POT] 或 #super[2]')
    if len({n.casefold() for n in names})!=len(names):raise ValueError('标签和别名不能重复（不区分大小写）')
    lookup=index([r for r in listing(db,lid) if r['id']!=b.get('id')]) if lookup is None else lookup
    if any((lid,n.casefold()) in lookup for n in names):raise ValueError('此标签或别名已被其他定义使用')
    fields=[b.get(k,'') for k in ('description','category','notes')]
    if any(not isinstance(v,str) for v in fields):raise ValueError('标签说明、分类和备注须为文本')
    fields[1]=fields[1].strip()
    import categories
    if db.execute("SELECT 1 FROM sqlite_master WHERE name='category_classes'").fetchone():categories.ensure(db,lid,'grammar',fields[1])
    xid=b.get('id') or str(uuid.uuid4())
    db.execute('INSERT INTO grammar_tags VALUES(?,?,?,?,?,?,?,1) ON CONFLICT(id) DO UPDATE SET symbol=excluded.symbol,description=excluded.description,category=excluded.category,aliases=excluded.aliases,notes=excluded.notes,revision=grammar_tags.revision+1',(xid,lid,symbol,fields[0],fields[1],json.dumps(aliases,ensure_ascii=False),fields[2]))
    if publish_result:publish(db,lid)
    return {'ok':True,'id':xid}


IGNORED='grammar_ignored_candidates'

def ignored_values(metadata):
    values=metadata.get(IGNORED,[])
    if not isinstance(values,list) or len(values)>10000 or any(not isinstance(v,str) or not v.strip() or len(v)>200 for v in values):
        raise ValueError('忽略候选须为不超过 10000 个标签的列表')
    return list(dict.fromkeys(values))

def reference():
    return dict(version=grammar_reference.VERSION,source=grammar_reference.SOURCE,items=grammar_reference.ROWS)

def batch(db,action,b,lid):
    """Caller owns one transaction and journal step; never overwrite definitions."""
    items=b.get('items')
    if not isinstance(items,list) or not 1<=len(items)<=200 or any(not isinstance(r,dict) for r in items):
        raise ValueError('每次请选择 1–200 个候选')
    if any(r.get('language_id',lid)!=lid or r.get('id') for r in items):raise ValueError('请一次处理同一语言的新候选')
    lookup=index(listing(db,lid));seen=set()
    for item in items:
        symbol=item.get('symbol')
        if not isinstance(symbol,str) or not symbol.strip() or len(symbol)>200:raise ValueError('候选标签格式不正确')
        if symbol in seen:raise ValueError('候选重复：'+symbol)
        seen.add(symbol)
    if action=='grammar-register-batch':
        ids=[]
        for item in items:
            r=mutate(db,'grammar-save',item,lid,lookup=lookup,publish_result=False);ids.append(r['id'])
            for name in [item['symbol'],*item.get('aliases',[])]:lookup[(lid,name.strip().casefold())]=r
        publish(db,lid)
        return dict(ok=True,count=len(ids),ids=ids)
    row=db.execute('SELECT metadata FROM languages WHERE id=?',(lid,)).fetchone();meta=json.loads(row[0]);old=ignored_values(meta)
    if action=='grammar-ignore':
        # Ignore only discovery hints, never a registered definition or its use.
        if any((lid,s.casefold()) in lookup for s in seen):raise ValueError('已登记标签不能作为候选忽略；原定义与别名保持不变')
        new=list(dict.fromkeys([*old,*(r['symbol'] for r in items)]))
    elif action=='grammar-unignore':new=[s for s in old if s not in seen]
    else:raise ValueError('未知候选操作')
    meta[IGNORED]=new;ignored_values(meta)
    if new!=old:db.execute('UPDATE languages SET metadata=?,revision=revision+1 WHERE id=?',(json.dumps(meta,ensure_ascii=False),lid))
    return dict(ok=True,count=len(set(new)^set(old)))

def sync_legacy(db,lid,before,after):
    """Keep older clients' glossary edits compatible with the managed inventory."""
    if before==after:return
    for r in listing(db,lid):
        if r['symbol'] in before and r['symbol'] not in after:db.execute('DELETE FROM grammar_tags WHERE id=?',(r['id'],))
    for symbol,description in after.items():
        if before.get(symbol)==description:continue
        old=index(listing(db,lid)).get((lid,symbol.casefold()))
        if old:
            db.execute('UPDATE grammar_tags SET description=?,revision=revision+1 WHERE id=?',(description,old['id']))
        else:mutate(db,'grammar-save',dict(symbol=symbol,description=description),lid)
    publish(db,lid)

def import_bundle(db,bundle,mapping):
    result={}
    rows=bundle.get('grammar_tags')
    if rows is None:
        rows=[dict(language_id=bundle['language']['id'],symbol=s,description=d,aliases=[]) for s,d in json.loads(bundle['language'].get('metadata','{}')).get('glossary',{}).items()]
    for r in long_tasks.steps(rows):
        lid=mapping[r['language_id']];row={**r,'aliases':json.loads(r['aliases']) if isinstance(r.get('aliases'),str) else r.get('aliases',[])}
        existing=index(listing(db,lid)).get((lid,r['symbol'].casefold()))
        if existing:
            if any(existing.get(k,'')!=row.get(k,'') for k in ('symbol','description','category','notes')) or existing['aliases']!=row['aliases']:raise ValueError('导入标签与目标语言冲突：'+r['symbol']+'。请先核对定义，或导入到新语言。')
        else:existing=mutate(db,'grammar-save',{k:v for k,v in row.items() if k not in ('id','revision')},lid)
        if r.get('id'):result[r['id']]=existing['id']
    return result

def tokens(gloss,lid,lookup,lower=False,*,candidates=False):
    # Formal recognition and discovery share parsing, not authority. Neither a
    # Latin spelling nor grammatical brackets register a tag implicitly.
    decorated=r'[A-Za-z0-9]+(?:#(?:sub|super|sup)\[[^\[\]]*\])+'
    if re.search(decorated,gloss):
        for part in re.split('('+decorated+')',gloss):
            if re.fullmatch(decorated,part):
                if recognized(part,lid,lookup) or candidates and (lower or grammar_reference.candidate(part)):yield part
            elif part:yield from tokens(part,lid,lookup,lower,candidates=candidates)
        return
    raw=plain(gloss);chunks=[];cursor=0
    try:groups,_=segmentation.angles(raw,True)
    except ValueError:groups=[]
    for start,end,content in groups:
        chunks.append((raw[cursor:start],False));chunks.append((content,True));cursor=end
    chunks.append((raw[cursor:],False))
    for chunk, bracketed in [(part,forced or square) for value,forced in chunks for part,square in gloss_chunks(value)]:
        for token in re.split(r'[\s.\-=:+~/;_\\,!?，。；：！？(){}<>]+',chunk):
            token=token.strip('«»“”"')
            if not token or '#' in token:continue
            if recognized(token,lid,lookup,bracketed):yield token;continue
            person=re.fullmatch(r'([123])([A-Za-z]+)',token)
            if person and (recognized(person[2],lid,lookup,bracketed) or person[2].upper() in ('SG','PL','DU')):
                for piece in person.groups():
                    if recognized(piece,lid,lookup,bracketed) or candidates and (lower or grammar_reference.candidate(piece)):yield piece
                continue
            if (lid,token.casefold()) in lookup:continue
            if candidates and (grammar_reference.candidate(token) or lower and re.fullmatch(r'[A-Za-z][A-Za-z0-9]*|[123]',token)):yield token


@lru_cache(maxsize=64)
def warning_policy(metadata,lid):
    meta=json.loads(metadata)
    # Include all explicit spellings in the same record for case-folded keys.
    groups={}
    for s in meta.get('glossary',{}):
        row=groups.setdefault((lid,s.casefold()),dict(symbol=s,aliases=[]))
        if row['symbol']!=s:row['aliases'].append(s)
    return groups,frozenset(ignored_values(meta))

def unknown_for_warning(gloss,lid,metadata):
    lookup,ignored=warning_policy(metadata,lid)
    return sorted({t for t in tokens(gloss,lid,lookup,candidates=True) if (lid,t.casefold()) not in lookup and t not in ignored})

class AuditAnalysisCache:
    """Private read-only projections, never used for returned sentence cards."""
    def __init__(self,limit=8*1024**2,items=4096):
        self.values=OrderedDict();self.bytes=0;self.limit=limit;self.items=items

    def apply(self,word,position):
        fields=('form','gloss','punctuation','punctuation_form','morph_groups','infix_confirmation')
        key=(word['form'],word['gloss'],bool(word.get('punctuation')),word.get('punctuation_form'),
             json.dumps(word['morph_groups'],ensure_ascii=False,sort_keys=True) if 'morph_groups' in word else None,
             json.dumps(word['infix_confirmation'],ensure_ascii=False,sort_keys=True) if 'infix_confirmation' in word else None)
        saved=self.values.get(key)
        if saved is None:
            source={k:word[k] for k in fields if k in word}
            fresh=corpus._analyze(dict(ipa='',translation='',words=[source]))
            derived={k:v for k,v in source.items() if k not in fields or k=='punctuation'}
            warnings=tuple(fresh['warnings'])
            cost=1024+16*len(json.dumps([key,derived,warnings],ensure_ascii=False))
            saved=(derived,warnings,cost)
            if cost<=self.limit and self.items>0:
                while self.values and (self.bytes+cost>self.limit or len(self.values)>=self.items):self.bytes-=self.values.popitem(last=False)[1][2]
                self.values[key]=saved;self.bytes+=cost
        else:self.values.move_to_end(key)
        word.update(saved[0])
        return [w.replace('第 1 ',f'第 {position+1} ',1) for w in saved[1]]


def audit_links(db,records,lid,source):
    # Read each unit once, preserving the UNION's lexeme-then-morpheme order.
    if source not in ('all','corpus'):return []
    catalogs=[dict(db.execute('SELECT id,language_id FROM '+table)) for table in ('lexemes','morphemes')]
    issues=[[],[]];live_entries=None
    for r in long_tasks.steps(db.execute('SELECT l.language_id,l.lexeme_id,u.entry_id,u.active,u.form,u.gloss FROM lexical_links l JOIN corpus_units u ON u.id=l.unit_id ORDER BY l.rowid')):
        base=records.get(('corpus',r['entry_id']))
        for n,catalog in enumerate(catalogs):
            if r['lexeme_id'] not in catalog:continue
            if not base and (lid=='all' or lid==r['language_id']):
                if live_entries is None:live_entries={row['id'] for row in db.execute('SELECT id FROM entries')}
                if r['entry_id'] not in live_entries:issues[n].append(dict(kind='corpus',id=r['entry_id'],language_id=r['language_id'],owner_language=r['language_id'],title='原句已删除',deleted=True,issue='link',message='原句已删除，词典旧关联仍保留',form=r['form'],gloss=r['gloss'],linked_lexeme=r['lexeme_id']))
            if base and '#' in r['form'] and boundary_count(r['form']):issues[n].append(dict(base,issue='link',message='原关联单位现识别为音系边界，请核对旧词典关联',form=r['form'],gloss=r['gloss'],linked_lexeme=r['lexeme_id']))
            elif base and (not r['active'] or base['language_id']!=catalog[r['lexeme_id']]):issues[n].append(dict(base,issue='link',message='词典关联的原单位已失效或语言已变化',form=r['form'],gloss=r['gloss'],linked_lexeme=r['lexeme_id']))
    return issues[0]+issues[1]


def classify_audit(db,q,facts):
    """Re-evaluate every label under the current inventory without rereading sources."""
    lid=q.get('language','all');lower=q.get('lower')=='true';tags=listing(db,lid);lookup=index(tags)
    usage=Counter();unknown=Counter();issues=[];token_cache=OrderedDict();token_bytes=0
    ignored={(r['id'],s) for r in db.execute('SELECT id,metadata FROM languages') for s in ignored_values(json.loads(r['metadata'])) if lid=='all' or r['id']==lid}
    def label_tokens(value,lang):
        nonlocal token_bytes
        key=(value,lang);cached=token_cache.get(key)
        if cached is not None:token_cache.move_to_end(key);return cached[0]
        result=tuple(t for t in tokens(value,lang,lookup,lower,candidates=True) if (lang,t.casefold()) in lookup or (lang,t) not in ignored);cost=256+4*(len(value)+len(lang)+sum(map(len,result)))
        if cost<=4*1024**2:
            while token_cache and (token_bytes+cost>4*1024**2 or len(token_cache)>=4096):token_bytes-=token_cache.popitem(last=False)[1][1]
            token_cache[key]=(result,cost);token_bytes+=cost
        return result
    for event in long_tasks.steps(facts['events']):
        if event[0]==1:issues.append(event[1]);continue
        _,bi,position,form,gloss,labels=event;base=facts['bases'][bi];lang=base['language_id']
        detail=dict(word=position,form=form,gloss=gloss)
        for mi,label in enumerate(labels):
            if mi and mi%64==0:long_tasks.checkpoint()
            seen=set()
            for ti,token in enumerate(label_tokens(label,lang)):
                if ti and ti%256==0:long_tasks.checkpoint()
                tag=lookup.get((lang,token.casefold()));identity=tag['id'] if tag else token.casefold()
                if identity in seen:continue
                seen.add(identity)
                if tag:
                    usage[tag['id']]+=1
                    if q.get('tag')==tag['id']:issues.append(dict(base,issue='usage',message='标签用例',token=token,canonical=tag['symbol'],body=True,**detail))
                    if token!=tag['symbol']:issues.append(dict(base,issue='alias',message='使用别名或大小写变体；不一定是错误',token=token,canonical=tag['symbol'],**detail))
                else:
                    unknown[(lang,token)]+=1;issues.append(dict(base,issue='unknown',message='未登记的标签候选，请人工确认',token=token,**detail))
    counts=dict(Counter(i['issue'] for i in issues))
    if 'usage' in counts:counts['usage']=len({(i['kind'],i['id']) for i in issues if i['issue']=='usage'})
    return dict(tags=[{**t,'uses':usage[t['id']]} for t in tags],unknown=[dict(language_id=k[0],symbol=k[1],uses=v,reference=grammar_reference.find(k[1])) for k,v in sorted(unknown.items(),key=lambda x:(-x[1],x[0]))],ignored=[dict(language_id=lang,symbol=s) for lang,s in sorted(ignored)],counts=counts,sentences=facts['sentences'],issues=issues)


def audit(db,q):
    cached=grammar_audit_cache.load(db,q)
    if cached is not None:return audit_page(db,q,cached)
    facts=grammar_audit_cache.load_facts(db,q)
    if facts is not None:
        data=classify_audit(db,q,facts);grammar_audit_cache.remember(db,q,data)
        return audit_page(db,q,data)
    lid=q.get('language','all');source=q.get('source','all');sentences=0;bases=[];events=[]
    analysis_cache=AuditAnalysisCache()
    target_cache=OrderedDict();target_bytes=0
    def target_body(xid):
        nonlocal target_bytes
        if xid in target_cache:
            target_cache.move_to_end(xid);return target_cache[xid][0]
        row=db.execute('SELECT body FROM dictionary_targets WHERE id=?',(xid,)).fetchone()
        value=json.loads(row['body']) if row else None;cost=512+(16*len(row['body']) if row else 0)
        if cost<=8*1024**2:
            while target_cache and (target_bytes+cost>8*1024**2 or len(target_cache)>=256):
                _,(_,old)=target_cache.popitem(last=False);target_bytes-=old
            target_cache[xid]=(value,cost);target_bytes+=cost
        return value
    def add(base,issue,message,**extra):events.append([1,{**base,'issue':issue,'message':message,**extra}])
    records={}
    for kind,sql in long_tasks.steps([('corpus','SELECT e.id,e.body,e.position,e.text_id,t.title,t.language_id FROM texts t CROSS JOIN entries e ON t.id=e.text_id ORDER BY t.rowid,e.position'),('independent','SELECT id,body,language_id FROM dictionary_examples ORDER BY rowid')]):
        if source not in ('all',kind):continue
        for row in long_tasks.steps(gloss_inheritance.iter_rows(db,db.execute(sql),kind,lightweight=True)):
            # Resolve all changed words fully, including independent references;
            # unchanged baseline bindings need no display metadata for the audit.
            b=gloss_inheritance.load(db,kind,row['id'],row['body'],metadata=False,changed_only=True);lang=b.get('language_id') or row['language_id']
            if lid!='all' and lang!=lid:continue
            sentences+=1;analyze(b,cache=analysis_cache)
            base=dict(kind=kind,id=row['id'],language_id=lang,owner_language=row['language_id'],title=row['title'] if kind=='corpus' else b.get('source') or '独立例句',text_id=row['text_id'] if kind=='corpus' else None,position=row['position'] if kind=='corpus' else None,lexeme_id=None if kind=='corpus' else (b['targets'][0]['lexeme_id'] if b.get('targets') else None))
            records[(kind,row['id'])]=base
            bi=len(bases);bases.append(base)
            if b.get('orphaned_morphology'):add(base,'pending','旧形态分析待核对')
            for relation in b.get('reduplication_info',{}).get('relations',[]):
                if relation['review']:
                    add(base,'pending','重叠关系待核对：'+relation['source']['form']+' → '+relation['base']['form'])
            if kind=='independent':
                import component_links,segmentation
                for target in long_tasks.steps(b.get('targets',[])):
                    x=target_body(target['lexeme_id'])
                    if x is None or component_links.review(x,target.get('component_ref')):add(base,'pending','独立例句关联的词条组分已变化，待核对')
                    if target.get('review_reason'):add(base,'pending',target['review_reason'])
                    if target.get('segmentation_review'):add(base,'pending','独立例句的词或语素已变化，旧关联待核对')
            for i,w in enumerate(b['words']):
                if i%64==0:long_tasks.checkpoint()
                if w.get('unit_type') in ('phonological_boundary','punctuation'): continue
                detail=dict(word=i+1,form=w['form'],gloss=w['gloss'])
                if w.get('group_reviews') or w.get('infix_ambiguous'):add(base,'pending','语素组合或中缀分析待核对',**detail)
                if not w['morphemes']:add(base,'boundary','语素数量或连接符不一致',**detail)
                labels=[]
                for mi,m in enumerate(w['morphemes'] or [w]):
                    if mi and mi%64==0:long_tasks.checkpoint()
                    display=m.get('display_gloss',m['gloss']);labels.append('<'+display+'>' if m.get('kind')=='infix' else display)
                events.append([0,bi,i+1,w['form'],w['gloss'],labels])
    events.extend([1,item] for item in audit_links(db,records,lid,source))
    for r in long_tasks.steps(db.execute('SELECT r.reason,u.entry_id,u.form,u.gloss FROM lexical_reviews r JOIN lexical_links l ON l.id=r.id JOIN corpus_units u ON u.id=l.unit_id')):
        base=records.get(('corpus',r['entry_id']))
        if base:add(base,'pending',r['reason'],form=r['form'],gloss=r['gloss'])
    import component_links
    for r in long_tasks.steps(db.execute('SELECT c.body ref,x.body,l.lexeme_id,u.entry_id,u.form,u.gloss FROM component_links c JOIN lexical_links l ON l.id=c.id JOIN corpus_units u ON u.id=l.unit_id JOIN dictionary_targets x ON x.id=l.lexeme_id')):
        base=records.get(('corpus',r['entry_id']))
        if base and component_links.review(json.loads(r['body']),json.loads(r['ref'])):add(base,'pending','关联的词条形态组分已变化，待核对',form=r['form'],gloss=r['gloss'])
    uncertain=set()
    import morpheme_registry
    for r in long_tasks.steps(db.execute('SELECT c.*,m.body morpheme_body,x.body lexeme_body FROM morpheme_components c JOIN morphemes m ON m.id=c.morpheme_id JOIN dictionary_targets x ON x.id=c.lexeme_id')):
        if morpheme_registry.current_component_ref(json.loads(r['lexeme_body']),json.loads(r['body']))[1]:uncertain.add(r['lexeme_id'])
    if uncertain:
        reported=set()
        for r in long_tasks.steps(db.execute('SELECT l.lexeme_id,u.entry_id FROM lexical_links l JOIN corpus_units u ON u.id=l.unit_id')):
            key=('corpus',r['entry_id']);base=records.get(key)
            if base and r['lexeme_id'] in uncertain and key not in reported:add(base,'pending','关联词条的原语素组分已删除');reported.add(key)
        for r in long_tasks.steps(db.execute('SELECT id,body FROM dictionary_examples')):
            base=records.get(('independent',r['id']))
            if base and any(t['lexeme_id'] in uncertain for t in json.loads(r['body']).get('targets',[])):add(base,'pending','关联词条的原语素组分已删除')
    cells=db.execute('SELECT c.*,l.language_id layer_language FROM annotation_cells c JOIN annotation_layers l ON l.id=c.layer_id')
    first=cells.fetchone()
    if first is not None:
        from itertools import chain
        live={r['id'] for r in db.execute("SELECT id FROM corpus_units WHERE active=1 AND kind='word'")}
        independent={r['id']:{w.get('annotation_id') for w in json.loads(r['body']).get('words',[])} for r in db.execute('SELECT id,body FROM dictionary_examples')}
        for c in long_tasks.steps(chain((first,),cells)):
            base=records.get((c['owner_kind'],c['record_id']))
            if base and (c['layer_language']!=base['language_id'] or c['unit_id']!='@sentence' and c['unit_id'] not in (live if c['owner_kind']=='corpus' else independent.get(c['record_id'],set()))):add(base,'annotation','附加标注的原词或所属语言已变化',form=c['value'])
    facts=dict(bases=bases,events=events,sentences=sentences)
    grammar_audit_cache.remember_facts(db,q,facts)
    data=classify_audit(db,q,facts)
    grammar_audit_cache.remember(db,q,data)
    return audit_page(db,q,data)


def audit_page(db,q,data,analysis_cache=None):
    issues=data['issues'];kind_filter=q.get('issue','all');query=q.get('q','').casefold()
    analysis_cache=analysis_cache or corpus.WordAnalysisCache()
    filtered=[i for i in issues if (kind_filter=='all' or i['issue']==kind_filter) and (not q.get('candidate') or i.get('token')==q['candidate'] and i['language_id']==q.get('candidate_language',i['language_id'])) and (not query or query in ' '.join(str(i.get(k,'')) for k in ('message','token','canonical','title','form','gloss')).casefold())]
    if kind_filter=='usage':
        filtered=list({(i['kind'],i['id']):i for i in filtered}.values())
    pages=max(1,(len(filtered)+19)//20);page=max(1,min(int(q.get('page',1)),pages))
    items=filtered[(page-1)*20:page*20]
    import annotations
    for item in long_tasks.steps(items):
        if 'body' in item:
            table='entries' if item['kind']=='corpus' else 'dictionary_examples'
            row=db.execute('SELECT body FROM '+table+' WHERE id=?',(item['id'],)).fetchone()
            item['body']=analyze(gloss_inheritance.load(db,item['kind'],item['id'],row['body']),cache=analysis_cache)
            annotations.enrich(db,item['body'],item['kind'],item['id'])
    return {k:data[k] for k in ('tags','unknown','ignored','counts','sentences')}|dict(total=len(filtered),page=page,pages=pages,items=items)
